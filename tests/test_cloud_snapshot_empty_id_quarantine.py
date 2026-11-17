"""빈 snapshot_id snapshot에 대한 방어 테스트.

PROJECT_AUDIT.md 3.3:
- read_snapshot_manifest 가 빈 snapshot_id snapshot을 CloudSyncError 로 거부 (기존 동작)
- merge_cloud_snapshot_db / preview_cloud_snapshot_db 에 빈 snapshot_id 전달 시
  DatabaseWriteError / DatabaseQueryError 로 거부 (신규 방어)
"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.cloud_sync import CloudSyncError, read_snapshot_manifest
from core.database import (
    DatabaseManager,
    DatabaseQueryError,
    DatabaseWriteError,
)


class TestEmptySnapshotId(unittest.TestCase):
    def _db(self, path: Path) -> DatabaseManager:
        return DatabaseManager(str(path), max_connections=2)

    def _make_empty_id_snapshot(self, root: Path) -> Path:
        """snapshot_id 가 빈 문자열인 snapshot zip 생성 (DB 파일은 최소 더미)."""
        zip_path = root / "news_scraper_sync_emptyid.zip"
        dummy_db = root / "news_database.db"
        # manifest 검증은 DB 내용을 보지 않으므로 최소 파일만 있으면 충분
        dummy_db.write_bytes(b"")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = {
                "format_version": "1.0",
                "snapshot_id": "",
                "machine_id": "machine-a",
                "created_at": "2024-01-01T00:00:00+00:00",
                "app_version": "test",
                "db_file": "news_database.db",
            }
            zf.writestr("manifest.json", json.dumps(manifest))
            zf.writestr("settings.json", json.dumps({"app_settings": {}}))
            zf.write(dummy_db, "news_database.db")
        return zip_path

    def test_read_snapshot_manifest_rejects_empty_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            zip_path = self._make_empty_id_snapshot(root)
            with self.assertRaises(CloudSyncError):
                read_snapshot_manifest(str(zip_path))

    def test_merge_rejects_empty_snapshot_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target_db = self._db(root / "target.db")
            source_db_path = root / "source.db"
            try:
                # merge_cloud_snapshot_db 를 직접 호출 — 빈 snapshot_id 전달
                with self.assertRaises(DatabaseWriteError):
                    target_db.merge_cloud_snapshot_db(
                        str(source_db_path),
                        snapshot_id="",
                        source_machine_id="machine-a",
                        local_machine_id="machine-b",
                    )
            finally:
                target_db.close()

    def test_merge_rejects_whitespace_only_snapshot_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target_db = self._db(root / "target.db")
            source_db_path = root / "source.db"
            try:
                with self.assertRaises(DatabaseWriteError):
                    target_db.merge_cloud_snapshot_db(
                        str(source_db_path),
                        snapshot_id="   ",
                        source_machine_id="machine-a",
                        local_machine_id="machine-b",
                    )
            finally:
                target_db.close()

    def test_preview_rejects_empty_snapshot_id(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target_db = self._db(root / "target.db")
            source_db_path = root / "source.db"
            try:
                with self.assertRaises(DatabaseQueryError):
                    target_db.preview_cloud_snapshot_db(
                        str(source_db_path),
                        snapshot_id="",
                        source_machine_id="machine-a",
                        local_machine_id="machine-b",
                    )
            finally:
                target_db.close()
