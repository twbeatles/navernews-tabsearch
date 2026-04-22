# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, Optional

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.config_store import (
    AppConfig,
    default_config,
    encode_client_secret_for_storage,
    load_config_file,
    resolve_client_secret_for_runtime,
    save_primary_config_file,
)
from core.constants import APP_DIR, APP_NAME, ICON_FILE, ICON_PNG, VERSION
from core.startup import StartupManager

logger = logging.getLogger(__name__)


class _MainWindowConfigMixin:
    def set_application_icon(self):
        """애플리케이션 아이콘 설정"""
        icon_path = self._resolve_icon_path()

        if icon_path and os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            QApplication.setWindowIcon(app_icon)
        else:
            logger.warning("아이콘 파일을 찾을 수 없습니다: %s 또는 %s", ICON_FILE, ICON_PNG)
            logger.warning("실행 파일과 같은 폴더에 아이콘 파일을 배치하세요.")

    def _resolve_icon_path(self):
        """런타임 환경(소스/onefile/onedir)에 맞는 아이콘 경로 해석"""
        search_dirs = []
        meipass_dir = getattr(sys, "_MEIPASS", None)
        if meipass_dir:
            search_dirs.append(meipass_dir)
        search_dirs.extend(
            [
                APP_DIR,
                os.path.dirname(os.path.abspath(__file__)),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ]
        )

        for base_dir in search_dirs:
            if not base_dir:
                continue
            if sys.platform == "win32":
                ico_path = os.path.join(base_dir, ICON_FILE)
                if os.path.exists(ico_path):
                    return ico_path
            png_path = os.path.join(base_dir, ICON_PNG)
            if os.path.exists(png_path):
                return png_path
        return None

    def load_config(self):
        """설정 로드"""
        loaded_cfg: Optional[AppConfig] = None
        try:
            loaded_cfg = load_config_file(self.runtime_paths.config_file)
        except Exception as exc:
            logger.error("설정 로드 오류 (Config Load Error): %s", exc)
            QMessageBox.warning(
                self,
                "설정 로드 오류",
                f"설정 파일을 읽는 중 오류가 발생했습니다.\n기본 설정으로 시작합니다.\n\n{str(exc)}",
            )

        if loaded_cfg is None:
            loaded_cfg = default_config()

        settings = loaded_cfg.get("app_settings", {})
        resolved_client_secret, _ = resolve_client_secret_for_runtime(settings)
        self.config = {
            "client_id": settings.get("client_id", ""),
            "client_secret": resolved_client_secret,
            "client_secret_enc": settings.get("client_secret_enc", ""),
            "client_secret_storage": settings.get("client_secret_storage", "plain"),
            "theme": settings.get("theme_index", 0),
            "interval": settings.get("refresh_interval_index", 2),
            "tabs": loaded_cfg.get("tabs", []),
            "notification_enabled": settings.get("notification_enabled", True),
            "alert_keywords": settings.get("alert_keywords", []),
            "sound_enabled": settings.get("sound_enabled", True),
            "minimize_to_tray": settings.get("minimize_to_tray", True),
            "close_to_tray": settings.get("close_to_tray", True),
            "start_minimized": settings.get("start_minimized", False),
            "auto_start_enabled": settings.get("auto_start_enabled", False),
            "notify_on_refresh": settings.get("notify_on_refresh", False),
            "window_geometry": settings.get("window_geometry"),
            "search_history": loaded_cfg.get("search_history", []),
            "api_timeout": settings.get("api_timeout", 15),
            "keyword_groups": loaded_cfg.get("keyword_groups", {}),
            "pagination_state": loaded_cfg.get("pagination_state", {}),
            "pagination_totals": loaded_cfg.get("pagination_totals", {}),
        }

        self.client_id = self.config["client_id"]
        self.client_secret = self.config["client_secret"]
        self.theme_idx = self.config["theme"]
        self.interval_idx = self.config["interval"]
        self.tabs_data = self.config["tabs"]
        self.notification_enabled = self.config.get("notification_enabled", True)
        self.alert_keywords = self.config.get("alert_keywords", [])
        self.sound_enabled = self.config.get("sound_enabled", True)

        self.minimize_to_tray = self.config.get("minimize_to_tray", True)
        self.close_to_tray = self.config.get("close_to_tray", True)
        self.start_minimized = self.config.get("start_minimized", False)
        self.auto_start_enabled = self.config.get("auto_start_enabled", False)
        self._saved_geometry = self.config.get("window_geometry", None)
        self.notify_on_refresh = self.config.get("notify_on_refresh", False)
        self.search_history = self.config.get("search_history", [])
        self.api_timeout = self.config.get("api_timeout", 15)
        self.keyword_group_manager.groups = self.keyword_group_manager._normalize_groups(
            self.config.get("keyword_groups", {})
        )
        raw_pagination_state = self.config.get("pagination_state", {})
        self._fetch_cursor_by_key = {
            str(fetch_key): int(start_idx)
            for fetch_key, start_idx in (raw_pagination_state.items() if isinstance(raw_pagination_state, dict) else [])
            if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
        }
        raw_pagination_totals = self.config.get("pagination_totals", {})
        self._fetch_total_by_key = {
            str(fetch_key): int(total)
            for fetch_key, total in (raw_pagination_totals.items() if isinstance(raw_pagination_totals, dict) else [])
            if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
        }
        if StartupManager.is_available():
            startup_status = StartupManager.get_startup_status(start_minimized=self.start_minimized)
            self.auto_start_enabled = bool(startup_status.get("is_healthy", False))

    def save_config(self):
        """설정 저장"""
        tab_names = [tab.keyword for _index, tab in self._iter_news_tabs(start_index=1)]

        secret_payload = encode_client_secret_for_storage(self.client_secret)
        data: AppConfig = {
            "app_settings": {
                "client_id": self.client_id,
                "client_secret": secret_payload.get("client_secret", ""),
                "client_secret_enc": secret_payload.get("client_secret_enc", ""),
                "client_secret_storage": secret_payload.get("client_secret_storage", "plain"),
                "theme_index": self.theme_idx,
                "refresh_interval_index": self.interval_idx,
                "notification_enabled": self.notification_enabled,
                "alert_keywords": self.alert_keywords,
                "sound_enabled": self.sound_enabled,
                "minimize_to_tray": self.minimize_to_tray,
                "close_to_tray": self.close_to_tray,
                "start_minimized": self.start_minimized,
                "auto_start_enabled": self.auto_start_enabled,
                "notify_on_refresh": self.notify_on_refresh,
                "api_timeout": self.api_timeout,
                "window_geometry": {
                    "x": self.x(),
                    "y": self.y(),
                    "width": self.width(),
                    "height": self.height(),
                },
            },
            "tabs": tab_names,
            "search_history": self.search_history,
            "keyword_groups": self.keyword_group_manager.groups,
            "pagination_state": {
                str(fetch_key): max(1, min(1000, int(start_idx)))
                for fetch_key, start_idx in self._fetch_cursor_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(start_idx, int) and start_idx > 0
            },
            "pagination_totals": {
                str(fetch_key): int(total)
                for fetch_key, total in self._fetch_total_by_key.items()
                if isinstance(fetch_key, str) and fetch_key.strip() and isinstance(total, int) and total >= 0
            },
        }

        try:
            save_primary_config_file(self._config_path_for_persistence(), data)
        except Exception as exc:
            logger.error("설정 저장 오류 (Config Save Error): %s", exc)
            QMessageBox.warning(self, "저장 오류", f"설정을 저장하는 중 오류가 발생했습니다:\n\n{str(exc)}")

    def _get_available_screen_geometry(self) -> QRect:
        screen = self.screen() or QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            if rect.width() > 0 and rect.height() > 0:
                return rect
        return QRect(0, 0, 1366, 900)

    def _build_default_window_geometry(self) -> Dict[str, int]:
        screen_rect = self._get_available_screen_geometry()
        min_width = min(980, screen_rect.width())
        min_height = min(700, screen_rect.height())

        width = int(screen_rect.width() * 0.92)
        height = int(screen_rect.height() * 0.88)
        width = max(min_width, min(width, screen_rect.width()))
        height = max(min_height, min(height, screen_rect.height()))

        x = screen_rect.x() + max(0, (screen_rect.width() - width) // 2)
        y = screen_rect.y() + max(0, (screen_rect.height() - height) // 2)
        return {"x": x, "y": y, "width": width, "height": height}

    def _normalize_window_geometry(self, raw_geometry: Optional[Dict[str, Any]]) -> Dict[str, int]:
        default_geometry = self._build_default_window_geometry()
        if not isinstance(raw_geometry, dict):
            return default_geometry

        screen_rect = self._get_available_screen_geometry()

        def _to_int(value: Any, fallback: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return fallback

        width = _to_int(raw_geometry.get("width"), default_geometry["width"])
        height = _to_int(raw_geometry.get("height"), default_geometry["height"])
        x = _to_int(raw_geometry.get("x"), default_geometry["x"])
        y = _to_int(raw_geometry.get("y"), default_geometry["y"])

        min_width = min(600, screen_rect.width())
        min_height = min(400, screen_rect.height())
        width = max(min_width, min(width, screen_rect.width()))
        height = max(min_height, min(height, screen_rect.height()))

        max_x = screen_rect.x() + max(0, screen_rect.width() - width)
        max_y = screen_rect.y() + max(0, screen_rect.height() - height)
        x = max(screen_rect.x(), min(x, max_x))
        y = max(screen_rect.y(), min(y, max_y))

        return {"x": x, "y": y, "width": width, "height": height}
