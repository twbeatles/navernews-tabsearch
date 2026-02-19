import ast
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

import news_scraper_pro as app


class TestParseTabQuery(unittest.TestCase):
    def test_parse_tab_query_basic(self):
        self.assertEqual(app.parse_tab_query(''), ('', []))
        self.assertEqual(app.parse_tab_query('AI'), ('AI', []))

    def test_parse_tab_query_excludes(self):
        self.assertEqual(app.parse_tab_query('AI -광고 -코인'), ('AI', ['광고', '코인']))
        self.assertEqual(app.parse_tab_query('AI - 광고'), ('AI', []))
        self.assertEqual(app.parse_tab_query('-광고 AI'), ('AI', ['광고']))


class TestBackupAndRestore(unittest.TestCase):
    def _make_db(self, path: Path, value: int) -> None:
        conn = sqlite3.connect(str(path))
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('CREATE TABLE IF NOT EXISTS t (v INTEGER)')
            conn.execute('DELETE FROM t')
            conn.execute('INSERT INTO t(v) VALUES (?)', (value,))
            conn.commit()
        finally:
            conn.close()

    def _read_db_value(self, path: Path) -> int:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute('SELECT v FROM t LIMIT 1').fetchone()
            return int(row[0]) if row else -1
        finally:
            conn.close()

    def test_backup_snapshot_does_not_copy_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            cfg = d / 'config.json'
            db = d / 'db.sqlite'
            cfg.write_text(json.dumps({'app_settings': {}}, ensure_ascii=False), encoding='utf-8')
            self._make_db(db, 1)

            (Path(str(db) + '-wal')).write_text('fake', encoding='utf-8')
            (Path(str(db) + '-shm')).write_text('fake', encoding='utf-8')

            ab = app.AutoBackup(config_file=str(cfg), db_file=str(db))
            backup_path = ab.create_backup(include_db=True)
            self.assertIsNotNone(backup_path)

            backup_db = Path(backup_path) / db.name
            conn = sqlite3.connect(str(backup_db))
            try:
                ok = conn.execute('PRAGMA integrity_check').fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(ok, 'ok')

            self.assertFalse(Path(str(backup_db) + '-wal').exists())
            self.assertFalse(Path(str(backup_db) + '-shm').exists())

    def test_backup_fallback_copies_sidecars(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            cfg = d / 'config.json'
            db = d / 'db.sqlite'
            cfg.write_text(json.dumps({'app_settings': {}}, ensure_ascii=False), encoding='utf-8')
            self._make_db(db, 1)

            (Path(str(db) + '-wal')).write_text('fake', encoding='utf-8')
            (Path(str(db) + '-shm')).write_text('fake', encoding='utf-8')

            ab = app.AutoBackup(config_file=str(cfg), db_file=str(db))
            ab._snapshot_db = lambda _dst: False

            backup_path = ab.create_backup(include_db=True)
            self.assertIsNotNone(backup_path)

            backup_db = Path(backup_path) / db.name
            self.assertTrue(Path(str(backup_db) + '-wal').exists())
            self.assertTrue(Path(str(backup_db) + '-shm').exists())

    def test_pending_restore_applies_on_startup(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            cfg = d / 'config.json'
            db = d / 'db.sqlite'
            pending = d / app.PENDING_RESTORE_FILENAME

            cfg.write_text(json.dumps({'app_settings': {'x': 1}}, ensure_ascii=False), encoding='utf-8')
            self._make_db(db, 1)
            (Path(str(db) + '-wal')).write_text('fake', encoding='utf-8')
            (Path(str(db) + '-shm')).write_text('fake', encoding='utf-8')

            ab = app.AutoBackup(config_file=str(cfg), db_file=str(db))

            backup_name = 'backup_test'
            backup_dir = Path(ab.backup_dir) / backup_name
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / cfg.name).write_text(
                json.dumps({'app_settings': {'x': 2}}, ensure_ascii=False),
                encoding='utf-8',
            )
            backup_db = backup_dir / db.name
            self._make_db(backup_db, 2)
            for suffix in ('-wal', '-shm'):
                p = Path(str(backup_db) + suffix)
                if p.exists():
                    p.unlink()

            ok = ab.schedule_restore(backup_name, restore_db=True, pending_file=str(pending))
            self.assertTrue(ok)
            self.assertTrue(pending.exists())

            applied = app.apply_pending_restore_if_any(
                pending_file=str(pending),
                config_file=str(cfg),
                db_file=str(db),
            )
            self.assertTrue(applied)
            self.assertFalse(pending.exists())

            cfg_loaded = json.loads(cfg.read_text(encoding='utf-8'))
            self.assertEqual(cfg_loaded['app_settings']['x'], 2)
            self.assertEqual(self._read_db_value(db), 2)
            self.assertFalse(Path(str(db) + '-wal').exists())
            self.assertFalse(Path(str(db) + '-shm').exists())


class TestDatabaseManager(unittest.TestCase):
    def test_get_connection_after_close_raises(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / 'db.sqlite'
            mgr = app.DatabaseManager(str(db), max_connections=2)
            mgr.close()
            with self.assertRaises(RuntimeError):
                mgr.get_connection()


class TestPerformanceRegressionGuards(unittest.TestCase):
    def test_split_module_layout_exists(self):
        required = [
            'core/constants.py',
            'core/database.py',
            'core/workers.py',
            'core/bootstrap.py',
            'ui/main_window.py',
            'ui/news_tab.py',
            'ui/dialogs.py',
            'ui/settings_dialog.py',
            'ui/styles.py',
        ]
        for path in required:
            self.assertTrue(Path(path).exists(), path)

    def test_main_session_transport_retry_disabled(self):
        src = Path('ui/main_window.py').read_text(encoding='utf-8')
        self.assertIn('HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=0)', src)

    def test_newstab_has_required_helper_methods(self):
        src = Path('ui/news_tab.py').read_text(encoding='utf-8')
        module = ast.parse(src)
        news_tab = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'NewsTab')
        method_names = {node.name for node in news_tab.body if isinstance(node, ast.FunctionDef)}
        for required in {
            '_prepare_item',
            '_rebuild_item_indexes',
            '_target_by_hash',
            '_refresh_after_local_change',
            '_notify_badge_change',
        }:
            self.assertIn(required, method_names)

    def test_close_tab_calls_cleanup_before_delete_later(self):
        src = Path('ui/main_window.py').read_text(encoding='utf-8')
        start = src.index('def close_tab')
        end = src.index('def rename_tab')
        block = src[start:end]
        self.assertIn('widget.cleanup()', block)
        self.assertIn('widget.deleteLater()', block)
        self.assertLess(block.index('widget.cleanup()'), block.index('widget.deleteLater()'))

    def test_on_fetch_done_does_not_use_split_index_parsing(self):
        src = Path('ui/main_window.py').read_text(encoding='utf-8')
        self.assertNotIn('search_keyword = keyword.split()[0] if keyword.split() else keyword', src)

    def test_dbworker_has_no_extra_count_news_roundtrip(self):
        src = Path('core/workers.py').read_text(encoding='utf-8')
        start = src.index('class DBWorker')
        block = src[start:]
        self.assertNotIn('total_count = self.db.count_news(', block)
        self.assertIn('total_count = len(data)', block)

    def test_render_html_skips_when_signature_unchanged(self):
        src = Path('ui/news_tab.py').read_text(encoding='utf-8')
        self.assertIn('if render_signature == self._last_render_signature', src)
