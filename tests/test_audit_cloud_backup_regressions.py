"""Behavioral regressions for the 2026-11 functional audit, using isolated data."""
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest

from core.backup import AutoBackup
from core.cloud_sync import create_cloud_snapshot, import_cloud_snapshot, preview_cloud_snapshot_import, read_snapshot_manifest
from core.database import DatabaseManager, DatabaseWriteError
from core.text_utils import parse_date_to_ts


LINK = "https://example.com/audit"


def item(title="Original", date="Mon, 01 Jan 2024 00:00:00 +0000", description="Summary"):
    return dict(link=LINK, title=title, description=description, pubDate=date, publisher="example.com")


@pytest.fixture
def peers(tmp_path):
    a = DatabaseManager(str(tmp_path / "a.db"), max_connections=2)
    b = DatabaseManager(str(tmp_path / "b.db"), max_connections=2)
    try:
        for db in (a, b):
            db.upsert_news([item()], "audit", query_key="audit|")
        yield a, b
    finally:
        a.close()
        b.close()


def set_time(db, column, value):
    with db.connection() as conn, conn:
        conn.execute(f"UPDATE news SET {column}=?", (value,))


def row(db):
    with db.connection() as conn:
        return dict(conn.execute("SELECT * FROM news WHERE link=?", (LINK,)).fetchone())


def merge(source, target, snapshot_id):
    kwargs = dict(snapshot_id=snapshot_id, source_machine_id="source", local_machine_id="target")
    preview = target.preview_cloud_snapshot_db(source.db_file, **kwargs)
    result = target.merge_cloud_snapshot_db(source.db_file, **kwargs)
    for key in ("news_added", "memberships_added", "content_changed", "read_changed",
                "bookmark_changed", "notes_changed", "tags_changed", "deleted", "restored"):
        assert result[key] == preview[key], key
    return result


@pytest.mark.parametrize("removal", ["edit", "everywhere", "bulk"])
def test_last_tag_removal_survives_zip_and_roundtrip(peers, tmp_path, removal):
    a, b = peers
    for db in peers:
        db.set_tags(LINK, ["x"])
        with db.connection() as conn, conn:
            conn.execute("UPDATE news_tag_state SET tags_updated_at=100")
    if removal == "edit":
        a.set_tags(LINK, [])
    elif removal == "everywhere":
        a.delete_tag_everywhere("x")
    else:
        a.bulk_remove_tag_from_links([LINK], "x")
    snap = create_cloud_snapshot(sync_dir=str(tmp_path / "sync"), config={},
                                 db_file=a.db_file, machine_id="a", app_version="test")
    preview = preview_cloud_snapshot_import(db_manager=b, zip_path=snap.path, local_machine_id="b")
    assert preview["tags_changed"] == 1
    result = import_cloud_snapshot(db_manager=b, zip_path=snap.path, local_machine_id="b")
    assert result["tags_changed"] == 1
    assert b.get_tags(LINK) == []
    with a.connection() as ac, b.connection() as bc:
        assert ac.execute("SELECT tags_updated_at FROM news_tag_state").fetchone()[0] == bc.execute(
            "SELECT tags_updated_at FROM news_tag_state"
        ).fetchone()[0]
    assert import_cloud_snapshot(db_manager=b, zip_path=snap.path, local_machine_id="b")["skipped"]
    merge(b, a, "reverse")
    assert a.get_tags(LINK) == []


def test_newer_local_tags_and_timestamp_only_changes(peers):
    a, b = peers
    a.set_tags(LINK, ["x"])
    b.set_tags(LINK, ["y"])
    with a.connection() as ac, ac, b.connection() as bc, bc:
        ac.execute("UPDATE news_tag_state SET tags_updated_at=100")
        bc.execute("UPDATE news_tag_state SET tags_updated_at=200")
    assert merge(a, b, "older")["tags_changed"] == 0
    assert b.get_tags(LINK) == ["y"]
    a.set_tags(LINK, ["y"])
    assert merge(a, b, "same-value-new-time")["tags_changed"] == 0


@pytest.mark.parametrize("equal_timestamp", [False, True])
def test_state_and_tags_converge_in_both_orders(peers, equal_timestamp):
    a, b = peers
    a.set_tags(LINK, ["a|b", "c"])
    b.set_tags(LINK, ["a", "b|c"])
    for db, read, note, ts in ((a, 0, "alpha", 100), (b, 1, "zeta", 100 if equal_timestamp else 10000)):
        with db.connection() as conn, conn:
            conn.execute("UPDATE news SET is_read=?, is_bookmarked=?, notes=?, read_updated_at=?, "
                         "bookmark_updated_at=?, notes_updated_at=?", (read, read, note, ts, ts, ts))
            conn.execute("UPDATE news_tag_state SET tags_updated_at=?", (ts,))
    merge(a, b, "a-to-b")
    merge(b, a, "b-to-a")
    for field in ("is_read", "is_bookmarked", "notes", "read_updated_at", "bookmark_updated_at", "notes_updated_at"):
        assert row(a)[field] == row(b)[field]
    assert a.get_tags(LINK) == b.get_tags(LINK)
    assert row(a)["notes"] == "zeta"


def test_delete_restore_tie_has_stable_winner(peers):
    a, b = peers
    with a.connection() as conn, conn:
        conn.execute("UPDATE news SET is_deleted=1, delete_updated_at=100, delete_machine_id='a', delete_reason='manual'")
    with b.connection() as conn, conn:
        conn.execute("UPDATE news SET is_deleted=0, delete_updated_at=100, delete_machine_id='b', delete_reason='restore'")
    merge(a, b, "deletion")
    merge(b, a, "reverse")
    for field in ("is_deleted", "delete_updated_at", "delete_machine_id", "delete_reason"):
        assert row(a)[field] == row(b)[field]
    assert row(b)["is_deleted"] == 1


def test_delayed_content_does_not_undo_correction_or_date_pair(peers):
    a, b = peers
    set_time(a, "content_updated_at", 100)
    b.upsert_news([item("Corrected", "Tue, 02 Jan 2024 00:00:00 +0000", "Correction")], "audit")
    set_time(b, "content_updated_at", 200)
    assert merge(a, b, "old")["content_changed"] == 0
    corrected = row(b)
    assert corrected["title"] == "Corrected"
    assert corrected["description"] == "Correction"
    assert corrected["pubDate_ts"] == parse_date_to_ts(corrected["pubDate"])
    assert merge(b, a, "correction")["content_changed"] == 1
    assert row(a)["title_hash"] == row(b)["title_hash"]


def test_content_edit_without_date_change_and_unchanged_fetch(peers):
    a, b = peers
    set_time(a, "content_updated_at", 100)
    set_time(b, "content_updated_at", 100)
    b.upsert_news([item("Correction", description="")], "audit")
    timestamp = row(b)["content_updated_at"]
    b.upsert_news([item("Correction", description="")], "audit")
    assert row(b)["content_updated_at"] == timestamp
    merge(b, a, "changed")
    assert row(a)["title"] == "Correction"
    assert row(a)["description"] == ""
    assert row(a)["pubDate_ts"] == parse_date_to_ts(item()["pubDate"])


def test_content_tie_and_legacy_compatibility(peers, tmp_path):
    a, b = peers
    a.upsert_news([item("alpha")], "audit")
    b.upsert_news([item("zeta")], "audit")
    for db in peers:
        set_time(db, "content_updated_at", 100)
    merge(a, b, "tie-first")
    merge(b, a, "tie-second")
    assert row(a)["title"] == row(b)["title"] == "zeta"
    legacy_path = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_path) as conn:
        conn.execute("CREATE TABLE news(link TEXT, title TEXT, description TEXT, pubDate TEXT)")
        conn.execute("INSERT INTO news VALUES(?, 'legacy title', '', '')", (LINK,))
        conn.execute("INSERT INTO news VALUES('https://example.com/new', 'legacy new', '', '')")
    a.merge_cloud_snapshot_db(str(legacy_path), snapshot_id="legacy")
    assert row(a)["title"] == "zeta"
    assert len(a.search_archive()) == 2


def test_legacy_row_is_promoted_only_on_api_observation(peers):
    a, _ = peers
    set_time(a, "content_updated_at", 0)
    a.upsert_news([item()], "audit")
    assert row(a)["content_updated_at"] > 0


def test_inconsistent_legacy_derived_values_are_normalized(peers):
    a, b = peers
    for db in peers:
        set_time(db, "content_updated_at", 0)
    with a.connection() as conn, conn:
        conn.execute("UPDATE news SET pubDate_ts=1, title_hash='bad-source'")
    with b.connection() as conn, conn:
        conn.execute("UPDATE news SET pubDate_ts=2, title_hash='zzz-stale-local'")
    assert merge(a, b, "normalized")["content_changed"] == 1
    assert row(b)["pubDate_ts"] == parse_date_to_ts(row(b)["pubDate"])
    assert row(b)["title_hash"] == b._calculate_title_hash(row(b)["title"])


@pytest.mark.parametrize("offset,warning", [(-7200, False), (10, False), (7200, True)])
def test_only_future_snapshot_time_warns_about_clock_skew(peers, tmp_path, offset, warning):
    a, b = peers
    snap = create_cloud_snapshot(sync_dir=str(tmp_path / "sync"), config={}, db_file=a.db_file,
                                 machine_id="a", app_version="test")
    manifest = read_snapshot_manifest(snap.path)
    manifest["created_at"] = (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat()
    with mock.patch("core.cloud_sync_support.import_flow.read_snapshot_manifest", return_value=manifest):
        result = import_cloud_snapshot(db_manager=b, zip_path=snap.path, local_machine_id="b")
    assert result["clock_skew_warning"] is warning


def test_tag_legacy_without_state_and_orphan_ignored(peers):
    a, b = peers
    a.set_tags(LINK, ["legacy"])
    with a.connection() as conn, conn:
        conn.execute("DROP TABLE news_tag_state")
    assert merge(a, b, "legacy-tags")["tags_changed"] == 1
    assert b.get_tags(LINK) == ["legacy"]


def test_merge_failure_preserves_full_local_state(peers):
    a, b = peers
    a.set_tags(LINK, ["new"])
    a.save_note(LINK, "new memo")
    before = row(b)
    with mock.patch.object(b, "_recalculate_duplicate_flags_for_entire_database", side_effect=sqlite3.OperationalError("disk full")):
        with pytest.raises(DatabaseWriteError):
            merge(a, b, "fail")
    assert row(b) == before
    assert b.get_tags(LINK) == []
    assert "fail" not in b.get_cloud_sync_seen_snapshot_ids()


@pytest.fixture
def backup_manager(tmp_path):
    cfg = tmp_path / "설정 file.json"
    cfg.write_text('{}', encoding="utf-8")
    db = tmp_path / "news.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE sample(value TEXT)")
        conn.execute("INSERT INTO sample VALUES('keep')")
    manager = AutoBackup(str(cfg), str(db))
    manager.MAX_AUTO_BACKUPS = 2
    manager.MAX_MANUAL_BACKUPS = 2
    manager.MAX_FAILED_BACKUPS = 2
    return manager


def payload_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


@pytest.mark.parametrize("trigger", ["auto", "manual"])
@pytest.mark.parametrize("failure", ["config", "integrity", "exception"])
def test_failed_backups_never_displace_valid_payloads(backup_manager, trigger, failure):
    manager = backup_manager
    good = [Path(manager.create_backup(True, trigger)) for _ in range(2)]
    before = {str(path): payload_hashes(path) for path in good}
    for _ in range(3):
        if failure == "config":
            Path(manager.config_file).write_text('{bad', encoding="utf-8")
            result = manager.create_backup(True, trigger)
        else:
            result_value = dict(is_restorable=False, verification_state="failed", is_corrupt=True, error="integrity failed")
            patch = mock.patch("core.backup_support.auto_backup_support.create.verify_backup_payload",
                               side_effect=OSError("access denied") if failure == "exception" else None,
                               return_value=result_value)
            with patch:
                result = manager.create_backup(True, trigger)
        assert result is None
        assert manager.last_create_error
        for path in good:
            assert payload_hashes(path) == before[str(path)]
    assert sum(e["verification_state"] == "failed" for e in manager.get_backup_list()) <= 2
    Path(manager.config_file).write_text('{}', encoding="utf-8")
    assert manager.create_backup(True, trigger)
    entries = manager.get_backup_list()
    assert sum(e["verification_state"] == "ok" for e in entries) == 2


def test_wal_backup_can_restore_user_state_and_status(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text('{}', encoding="utf-8")
    db = DatabaseManager(str(tmp_path / "live.db"), max_connections=2)
    manager = AutoBackup(str(cfg), db.db_file)
    try:
        db.upsert_news([item()], "audit")
        db.save_note(LINK, "한글 " + "x" * 9997)
        db.update_status(LINK, "is_bookmarked", 1)
        db.set_tags(LINK, ["중요"])
        path = manager.create_backup(True, "auto")
        assert path
        status = manager.get_auto_backup_status()
        assert status["last_success_include_db"]
        assert status["last_success_path"] == path
        restored = DatabaseManager(str(Path(path) / "live.db"), max_connections=1)
        try:
            assert row(restored)["notes"] == row(db)["notes"]
            assert row(restored)["is_bookmarked"] == 1
            assert restored.get_tags(LINK) == ["중요"]
        finally:
            restored.close()
        cfg.write_text('{bad', encoding="utf-8")
        assert manager.create_backup(True, "auto") is None
        new_status = AutoBackup(str(cfg), db.db_file).get_auto_backup_status()
        assert new_status["last_success_at"] == status["last_success_at"]
        assert new_status["last_error"]
    finally:
        db.close()


def test_overlapping_backup_returns_without_creating_artifacts(backup_manager):
    manager = backup_manager
    manager._create_lock.acquire()
    try:
        assert manager.create_backup(True, "auto") is None
        assert manager.get_backup_list() == []
    finally:
        manager._create_lock.release()


def test_failed_online_snapshot_never_falls_back_to_live_file_copy(backup_manager):
    manager = backup_manager
    good = Path(manager.create_backup(True, "auto"))
    before = payload_hashes(good)
    with mock.patch.object(manager, "_snapshot_db", return_value=False), mock.patch.object(
        manager, "_copy_db_with_sidecars"
    ) as raw_copy:
        assert manager.create_backup(True, "auto") is None
        raw_copy.assert_not_called()
    assert payload_hashes(good) == before
