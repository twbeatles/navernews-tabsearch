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
from core.content_filters import normalize_publisher_filter_lists, truncate_note
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

def _dialogs_for(target: Any):
    return get_dialog_adapter(target)
def _export_row(item: Dict[str, Any]) -> List[str]:
    return [
        str(item.get("title", "") or ""),
        str(item.get("link", "") or ""),
        str(item.get("pubDate", "") or ""),
        str(item.get("publisher", "") or ""),
        str(item.get("description", "") or ""),
        "읽음" if item.get("is_read") else "안읽음",
        "북마크" if item.get("is_bookmarked") else "",
        str(item.get("notes", "") or ""),
        "중복" if item.get("is_duplicate", 0) else "",
        str(item.get("tags", "") or ""),
    ]
def _markdown_escape(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text.replace("|", "\\|")
def _export_item_markdown(item: Dict[str, Any], aliases: Optional[Dict[str, str]] = None) -> str:
    title = str(item.get("title", "") or "(제목 없음)").strip()
    link = str(item.get("link", "") or "").strip()
    publisher = canonical_publisher(item.get("publisher", ""), aliases or {}) or str(item.get("publisher", "") or "")
    date = str(item.get("pubDate", "") or "").strip()
    tags = str(item.get("tags", "") or "").strip()
    notes = str(item.get("notes", "") or "").strip()
    description = str(item.get("description", "") or "").strip()
    state = ["읽음" if item.get("is_read") else "안읽음"]
    if item.get("is_bookmarked"):
        state.append("북마크")
    if item.get("is_duplicate"):
        state.append("중복")
    title_line = f"### [{title}]({link})" if link else f"### {title}"
    lines = [
        title_line,
        f"- 날짜: {_markdown_escape(date)}",
        f"- 출처: {_markdown_escape(publisher)}",
        f"- 상태: {_markdown_escape(', '.join(state))}",
    ]
    if tags:
        lines.append(f"- 태그: {_markdown_escape(tags)}")
    if description:
        lines.extend(["", description])
    if notes:
        lines.extend(["", f"> 메모: {_markdown_escape(notes)}"])
    return "\n".join(lines).strip()
def export_items_to_csv(
    items: List[Dict[str, Any]],
    output_path: str,
    keyword: str,
) -> Dict[str, Any]:
    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복", "태그"])
            for item in items:
                writer.writerow(_export_row(item))
                written += 1
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword}
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
def export_items_to_markdown(
    items: List[Dict[str, Any]],
    output_path: str,
    keyword: str,
    *,
    publisher_aliases: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0
    try:
        with os.fdopen(fd, "w", newline="\n", encoding="utf-8") as f:
            f.write(f"# 뉴스 Digest - {keyword or '뉴스'}\n\n")
            f.write(f"- 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 항목 수: {len(items)}\n\n")
            for item in items:
                f.write(_export_item_markdown(item, publisher_aliases))
                f.write("\n\n")
                written += 1
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword, "format": "markdown"}
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
def export_scope_to_csv(
    context,
    db_manager,
    scope: DBQueryScope,
    output_path: str,
    keyword: str,
    chunk_size: int = EXPORT_CHUNK_SIZE,
) -> Dict[str, Any]:
    if hasattr(db_manager, "iter_news_snapshot_batches"):
        total_count, batch_iter = db_manager.iter_news_snapshot_batches(
            scope,
            chunk_size=max(1, int(chunk_size)),
        )
    else:
        total_count = int(db_manager.count_news(**scope.count_kwargs()))
        batch_iter = None
    try:
        context.report(current=0, total=total_count, message="내보내기 준비 중...", payload={"stage": "count"})
        context.check_cancelled()

        if total_count <= 0:
            raise ValueError("내보낼 뉴스가 없습니다.")
    except Exception:
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
        raise

    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["제목", "링크", "날짜", "출처", "요약", "읽음", "북마크", "메모", "중복", "태그"])

            if batch_iter is None:
                def _fallback_iter():
                    offset = 0
                    while written < total_count:
                        rows = db_manager.fetch_news(
                            limit=max(1, int(chunk_size)),
                            offset=max(0, int(offset)),
                            **scope.fetch_kwargs(),
                        )
                        if not rows:
                            break
                        offset += len(rows)
                        yield rows

                batch_iter = _fallback_iter()

            for rows in batch_iter:
                context.check_cancelled()
                if not rows:
                    break

                for item in rows:
                    context.check_cancelled()
                    writer.writerow(_export_row(item))
                    written += 1

                f.flush()
                os.fsync(f.fileno())
                context.report(
                    current=written,
                    total=total_count,
                    message=f"CSV 내보내는 중... ({written}/{total_count})",
                    payload={"stage": "write", "written": written, "path": output_path},
                )

        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword}
    except Exception:
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
def export_scope_to_markdown(
    context,
    db_manager,
    scope: DBQueryScope,
    output_path: str,
    keyword: str,
    chunk_size: int = EXPORT_CHUNK_SIZE,
    *,
    publisher_aliases: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    if hasattr(db_manager, "iter_news_snapshot_batches"):
        total_count, batch_iter = db_manager.iter_news_snapshot_batches(
            scope,
            chunk_size=max(1, int(chunk_size)),
        )
    else:
        total_count = int(db_manager.count_news(**scope.count_kwargs()))
        batch_iter = None
    try:
        context.report(current=0, total=total_count, message="Markdown 준비 중...", payload={"stage": "count"})
        context.check_cancelled()
        if total_count <= 0:
            raise ValueError("내보낼 뉴스가 없습니다.")
    except Exception:
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
        raise

    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".export_", suffix=".tmp", dir=directory)
    written = 0

    try:
        with os.fdopen(fd, "w", newline="\n", encoding="utf-8") as f:
            f.write(f"# 뉴스 Digest - {keyword or '뉴스'}\n\n")
            f.write(f"- 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"- 항목 수: {total_count}\n\n")

            if batch_iter is None:
                def _fallback_iter():
                    offset = 0
                    while written < total_count:
                        rows = db_manager.fetch_news(
                            limit=max(1, int(chunk_size)),
                            offset=max(0, int(offset)),
                            **scope.fetch_kwargs(),
                        )
                        if not rows:
                            break
                        offset += len(rows)
                        yield rows

                batch_iter = _fallback_iter()

            for rows in batch_iter:
                context.check_cancelled()
                if not rows:
                    break
                for item in rows:
                    context.check_cancelled()
                    f.write(_export_item_markdown(item, publisher_aliases))
                    f.write("\n\n")
                    written += 1
                f.flush()
                os.fsync(f.fileno())
                context.report(
                    current=written,
                    total=total_count,
                    message=f"Markdown 내보내는 중... ({written}/{total_count})",
                    payload={"stage": "write", "written": written, "path": output_path},
                )

        os.replace(tmp_path, output_path)
        return {"count": written, "path": output_path, "keyword": keyword, "format": "markdown"}
    except Exception:
        close_batch_iter = getattr(batch_iter, "close", None)
        if callable(close_batch_iter):
            close_batch_iter()
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise
def _csv_truthy(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on", "북마크", "bookmarked", "bookmark"}
def import_bookmarks_notes_from_csv(
    context,
    db,
    input_path: str,
    chunk_size: int = 200,
) -> Dict[str, int]:
    processed = 0
    updated_rows = 0
    missing_rows = 0
    truncated_notes = 0
    safe_chunk_size = max(1, int(chunk_size or 200))
    with open(input_path, "r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {"processed": 0, "updated": 0, "missing": 0, "truncated_notes": 0}
        for row in reader:
            context.check_cancelled()
            processed += 1
            link = str(row.get("링크") or row.get("link") or row.get("Link") or "").strip()
            if not link:
                missing_rows += 1
                continue
            changed = False
            if any(key in row for key in ("북마크", "bookmark", "Bookmark")):
                bookmark_value = row.get("북마크", row.get("bookmark", row.get("Bookmark", "")))
                changed = bool(db.update_status(link, "is_bookmarked", 1 if _csv_truthy(bookmark_value) else 0)) or changed
            if any(key in row for key in ("메모", "notes", "Notes")):
                note_value, note_truncated = truncate_note(
                    row.get("메모", row.get("notes", row.get("Notes", "")))
                )
                if note_truncated:
                    truncated_notes += 1
                changed = bool(db.save_note(link, note_value)) or changed
            if changed:
                updated_rows += 1
            else:
                missing_rows += 1
            if processed % safe_chunk_size == 0:
                context.report(
                    current=processed,
                    total=0,
                    message=f"CSV 가져오는 중... ({processed}행 처리)",
                )
    context.report(current=processed, total=processed, message="CSV 가져오기 완료")
    return {
        "processed": processed,
        "updated": updated_rows,
        "missing": missing_rows,
        "truncated_notes": truncated_notes,
    }
