import importlib
import unittest

import news_scraper_pro as app


class TestRefactorCompat(unittest.TestCase):
    def test_public_exports_available(self):
        for name in [
            'parse_tab_query',
            'parse_search_query',
            'build_fetch_key',
            'DatabaseManager',
            'AutoBackup',
            'apply_pending_restore_if_any',
            'PENDING_RESTORE_FILENAME',
            'MainApp',
            'NewsTab',
        ]:
            self.assertTrue(hasattr(app, name), name)

    def test_wrapper_modules_import(self):
        modules = [
            'query_parser',
            'config_store',
            'backup_manager',
            'worker_registry',
            'workers',
            'database_manager',
            'styles',
        ]
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            self.assertIsNotNone(mod)

    def test_support_packages_import(self):
        modules = [
            'core.workers_support.api_worker',
            'core.workers_support.db_worker',
            'core.backup_support.auto_backup',
            'core.db_mutations_support.maintenance',
            'ui.main_window_fetch_support.worker_flow',
            'ui.main_window_io_support.settings_dialogs',
            'ui.dialogs_support.backups',
            'ui.styles_support.app_style',
        ]
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            self.assertIsNotNone(mod)

    def test_database_manager_wrapper_points_to_core(self):
        core_db = importlib.import_module('core.database')
        wrapper = importlib.import_module('database_manager')
        self.assertIs(wrapper.DatabaseManager, core_db.DatabaseManager)

    def test_public_all_exports_are_unique(self):
        modules = [
            'core.constants',
            'core.runtime_support',
            'core.cloud_sync_support',
            'core.config_store_support',
        ]
        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            exports = list(getattr(mod, '__all__', []))
            self.assertEqual(len(exports), len(set(exports)), mod_name)


if __name__ == '__main__':
    unittest.main()
