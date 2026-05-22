# pyright: reportAttributeAccessIssue=false, reportArgumentType=false, reportGeneralTypeIssues=false
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import QTimer

from core.config_store import (
    AppConfig,
    encode_client_secret_for_storage,
    normalize_import_settings,
    normalize_loaded_config,
    save_primary_config_file,
)
from core.cloud_sync import (
    cleanup_old_snapshots,
    cloud_sync_path_conflicts_with_runtime,
    create_cloud_snapshot,
    import_cloud_snapshot,
    run_cloud_sync_cycle,
    runtime_storage_is_probably_cloud,
    select_cloud_snapshots_for_import,
)
from core.constants import CONFIG_FILE, RUNTIME_PATHS, VERSION
from core.content_filters import normalize_publisher_filter_lists
from core.keyword_groups import merge_keyword_groups
from core.machine_identity import get_machine_identity
from core.automation_rules import normalize_automation_rules
from core.publisher_aliases import canonical_publisher, normalize_publisher_aliases
from core.startup import StartupManager
from core.workers import DBQueryScope, IterativeJobWorker, delete_qthread_when_finished
from ui.dialog_adapters import get_dialog_adapter
from ui.settings_dialog import SettingsDialog
from ui.styles import AppStyle

if TYPE_CHECKING:
    from ui.main_window import MainApp

logger = logging.getLogger(__name__)
EXPORT_CHUNK_SIZE = 500


class _ImportStageMergeHelpersMixin:
    def _merge_search_history(
        self: MainApp,
        imported_history: Any,
    ) -> List[str]:
        merged: List[str] = []
        seen_identities = set()
        raw_items: List[str] = []
        if isinstance(imported_history, list):
            raw_items.extend(str(item).strip() for item in imported_history if isinstance(item, str))
        raw_items.extend(str(item).strip() for item in self.search_history if isinstance(item, str))
        for keyword in raw_items:
            if not keyword:
                continue
            identity = self._history_identity_for_keyword(keyword)
            if identity in seen_identities:
                continue
            seen_identities.add(identity)
            merged.append(keyword)
        return merged[:10]

    def _merge_int_mapping_keep_max(
        self: MainApp,
        current: Dict[str, int],
        incoming: Any,
        minimum: int,
    ) -> Dict[str, int]:
        merged: Dict[str, int] = {
            str(key): int(value)
            for key, value in current.items()
            if isinstance(key, str) and key.strip() and isinstance(value, int) and value >= minimum
        }
        if not isinstance(incoming, dict):
            return merged

        for raw_key, raw_value in incoming.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key.strip()
            if not key:
                continue
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                continue
            if value < minimum:
                continue
            current_value = merged.get(key)
            if current_value is None or value > current_value:
                merged[key] = value
        return merged

    def _validated_import_window_geometry(
        self: MainApp,
        raw_geometry: Any,
    ) -> Optional[Dict[str, int]]:
        if not isinstance(raw_geometry, dict):
            return None

        try:
            parsed = {
                "x": int(raw_geometry.get("x")),
                "y": int(raw_geometry.get("y")),
                "width": int(raw_geometry.get("width")),
                "height": int(raw_geometry.get("height")),
            }
        except (TypeError, ValueError):
            return None

        normalized = self._normalize_window_geometry(parsed)
        if normalized != parsed:
            return None
        return parsed

    def _canonicalize_tab_refresh_policies(
        self: MainApp,
        policies: Any,
        *,
        known_keywords: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        if not isinstance(policies, dict):
            return {}

        allowed = {"inherit", "off", "10", "30", "60", "120", "360"}
        known_keys = {
            self._canonical_fetch_key_for_keyword(keyword): keyword
            for keyword in (known_keywords or [])
            if isinstance(keyword, str) and self._canonical_fetch_key_for_keyword(keyword)
        }
        normalized: Dict[str, str] = {}
        for raw_key, raw_policy in policies.items():
            if not isinstance(raw_key, str):
                continue
            key_text = raw_key.strip()
            if not key_text:
                continue
            canonical_key = key_text.lower() if "|" in key_text else self._canonical_fetch_key_for_keyword(key_text)
            if not canonical_key:
                continue
            if known_keys and canonical_key not in known_keys and "|" not in key_text:
                # Raw labels from imports must map to a known/current tab identity.
                continue
            policy = str(raw_policy or "inherit").strip().lower()
            if policy not in allowed:
                policy = "inherit"
            normalized[canonical_key] = policy
        return normalized

    def _compute_imported_new_tabs(
        self: MainApp,
        imported_tabs: Any,
    ) -> Tuple[List[str], int]:
        existing_fetch_keys = {
            self._canonical_fetch_key_for_keyword(tab.keyword)
            for _index, tab in self._iter_news_tabs(start_index=1)
            if self._canonical_fetch_key_for_keyword(tab.keyword)
        }
        imported_new_keywords: List[str] = []
        skipped_invalid_tabs = 0
        for keyword in imported_tabs if isinstance(imported_tabs, list) else []:
            normalized_keyword = self._normalize_tab_keyword(keyword.strip()) if isinstance(keyword, str) else None
            normalized_fetch_key = (
                self._canonical_fetch_key_for_keyword(normalized_keyword)
                if normalized_keyword
                else ""
            )
            if normalized_keyword and normalized_fetch_key and normalized_fetch_key not in existing_fetch_keys:
                existing_fetch_keys.add(normalized_fetch_key)
                imported_new_keywords.append(normalized_keyword)
            elif not normalized_keyword:
                skipped_invalid_tabs += 1
        return imported_new_keywords, skipped_invalid_tabs

    def _merge_imported_keyword_groups(
        self: MainApp,
        imported_groups: Any,
    ) -> Dict[str, List[str]]:
        group_manager = self.keyword_group_manager
        normalize_groups = getattr(group_manager, "_normalize_groups", None)
        existing_groups = dict(getattr(group_manager, "groups", {}))
        if callable(normalize_groups):
            normalized_existing = normalize_groups(existing_groups)
            normalized_incoming = normalize_groups(imported_groups if isinstance(imported_groups, dict) else {})
        else:
            normalized_existing = existing_groups
            normalized_incoming = imported_groups if isinstance(imported_groups, dict) else {}
        return merge_keyword_groups(normalized_existing, normalized_incoming)
