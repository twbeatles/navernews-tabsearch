import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config_store
from query_parser import build_fetch_key


class TestConfigStore(unittest.TestCase):
    def test_roundtrip_preserves_critical_fields(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / 'config.json'
            payload = config_store.default_config()
            payload['app_settings']['close_to_tray'] = False
            payload['app_settings']['start_minimized'] = True
            payload['app_settings']['notify_on_refresh'] = True
            payload['app_settings']['api_timeout'] = 22
            payload['search_history'] = ['AI', 'ECON']
            payload['keyword_groups'] = {'시장': ['AI', '경제']}

            config_store.save_config_file_atomic(str(cfg_path), payload)
            loaded = config_store.load_config_file(str(cfg_path))

            self.assertEqual(loaded['app_settings']['close_to_tray'], False)
            self.assertEqual(loaded['app_settings']['start_minimized'], True)
            self.assertEqual(loaded['app_settings']['notify_on_refresh'], True)
            self.assertEqual(loaded['app_settings']['api_timeout'], 22)
            self.assertEqual(loaded['search_history'], ['AI', 'ECON'])
            self.assertEqual(loaded['keyword_groups'], {'시장': ['AI', '경제']})

    def test_atomic_save_failure_does_not_corrupt_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / 'config.json'
            cfg_path.write_text(json.dumps({'stable': True}), encoding='utf-8')

            with self.assertRaises(OSError):
                with mock.patch('config_store.os.replace', side_effect=OSError('replace failed')):
                    config_store.save_config_file_atomic(str(cfg_path), config_store.default_config())

            data = json.loads(cfg_path.read_text(encoding='utf-8'))
            self.assertEqual(data, {'stable': True})


class TestPlanSourceGuards(unittest.TestCase):
    def _read(self, path: str) -> str:
        return Path(path).read_text(encoding='utf-8')

    def test_build_fetch_key_separates_queries_with_same_keyword(self):
        k1 = build_fetch_key('AI', ['광고'])
        k2 = build_fetch_key('AI', ['코인'])
        self.assertNotEqual(k1, k2)

    def test_main_starts_with_pending_restore_apply(self):
        src = self._read('core/bootstrap.py')
        self.assertIn('if apply_pending_restore_if_any(', src)
        self.assertIn('pending_file=PENDING_RESTORE_FILE', src)

    def test_backup_dialog_restore_uses_schedule_restore(self):
        src = self._read('ui/dialogs.py')
        start = src.index('def restore_backup(self):')
        end = src.index('def delete_backup(self):')
        block = src[start:end]
        self.assertIn('self.auto_backup.schedule_restore(', block)
        self.assertNotIn('self.auto_backup.restore_backup(', block)

    def test_thread_terminate_removed(self):
        for path in ['ui/main_window.py', 'ui/news_tab.py', 'core/workers.py']:
            src = self._read(path)
            self.assertNotIn('thread.terminate()', src)

    def test_date_toggle_calls_reload_immediately(self):
        src = self._read('ui/news_tab.py')
        start = src.index('def _toggle_date_filter')
        end = src.index('def _update_date_toggle_style')
        block = src[start:end]
        self.assertIn('self.load_data_from_db()', block)
        self.assertNotIn('if not checked', block)

    def test_date_style_call_order_in_setup_ui(self):
        src = self._read('ui/news_tab.py')
        start = src.index('def setup_ui')
        end = src.index('def _toggle_date_filter')
        block = src[start:end]
        date_start_idx = block.index('self.date_start = QDateEdit()')
        style_call_idx = block.index('self._update_date_toggle_style(False)')
        self.assertGreater(style_call_idx, date_start_idx)

    def test_update_date_toggle_style_has_init_guard(self):
        src = self._read('ui/news_tab.py')
        start = src.index('def _update_date_toggle_style')
        end = src.index('def _on_filter_changed')
        block = src[start:end]
        self.assertIn('hasattr(self, "date_start")', block)
        self.assertIn('hasattr(self, "date_end")', block)
        self.assertIn('hasattr(self, "lbl_tilde")', block)

    def test_fetch_dedupe_uses_build_fetch_key(self):
        src = self._read('ui/main_window.py')
        start = src.index('def fetch_news')
        end = src.index('def on_fetch_done')
        block = src[start:end]
        self.assertIn('fetch_key = build_fetch_key(search_keyword, exclude_words)', block)
        self.assertIn('self._last_fetch_request_ts[fetch_key] = now_ts', block)


if __name__ == '__main__':
    unittest.main()
