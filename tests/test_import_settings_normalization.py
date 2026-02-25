import unittest
import json
import tempfile
from pathlib import Path

from core.config_store import load_config_file, normalize_import_settings


class TestImportSettingsNormalization(unittest.TestCase):
    def test_normalize_import_settings_coerces_types_and_ranges(self):
        fallback = {
            "theme_index": 0,
            "refresh_interval_index": 2,
            "notification_enabled": True,
            "alert_keywords": ["기존"],
            "sound_enabled": True,
            "minimize_to_tray": True,
            "close_to_tray": True,
            "start_minimized": False,
            "notify_on_refresh": False,
            "api_timeout": 15,
        }
        raw = {
            "theme_index": "9",
            "refresh_interval_index": "abc",
            "notification_enabled": "no",
            "alert_keywords": ["AI", "AI", "", "경제", 100, None, "증시"],
            "sound_enabled": 0,
            "minimize_to_tray": "true",
            "close_to_tray": "invalid",
            "start_minimized": 1,
            "notify_on_refresh": "off",
            "api_timeout": "999",
        }

        normalized, warnings = normalize_import_settings(raw, fallback)

        self.assertEqual(normalized["theme_index"], 1)
        self.assertEqual(normalized["refresh_interval_index"], 2)
        self.assertEqual(normalized["notification_enabled"], False)
        self.assertEqual(normalized["alert_keywords"], ["AI", "경제", "100", "증시"])
        self.assertEqual(normalized["sound_enabled"], False)
        self.assertEqual(normalized["minimize_to_tray"], True)
        self.assertEqual(normalized["close_to_tray"], True)
        self.assertEqual(normalized["start_minimized"], True)
        self.assertEqual(normalized["notify_on_refresh"], False)
        self.assertEqual(normalized["api_timeout"], 60)

        self.assertGreaterEqual(len(warnings), 1)
        self.assertTrue(any("api_timeout" in warning for warning in warnings))
        self.assertTrue(any("alert_keywords" in warning for warning in warnings))

    def test_normalize_import_settings_handles_invalid_settings_payload(self):
        fallback = {
            "theme_index": 1,
            "refresh_interval_index": 4,
            "notification_enabled": False,
            "alert_keywords": ["A"],
            "sound_enabled": False,
            "minimize_to_tray": False,
            "close_to_tray": False,
            "start_minimized": True,
            "notify_on_refresh": True,
            "api_timeout": 20,
        }

        normalized, warnings = normalize_import_settings("invalid", fallback)
        self.assertEqual(normalized["theme_index"], 1)
        self.assertEqual(normalized["refresh_interval_index"], 4)
        self.assertEqual(normalized["api_timeout"], 20)
        self.assertEqual(normalized["alert_keywords"], ["A"])
        self.assertEqual(len(warnings), 1)
        self.assertIn("settings 형식", warnings[0])

    def test_alert_keywords_is_limited_to_ten(self):
        fallback = {
            "theme_index": 0,
            "refresh_interval_index": 2,
            "notification_enabled": True,
            "alert_keywords": [],
            "sound_enabled": True,
            "minimize_to_tray": True,
            "close_to_tray": True,
            "start_minimized": False,
            "notify_on_refresh": False,
            "api_timeout": 15,
        }
        raw = {"alert_keywords": [f"k{i}" for i in range(15)]}

        normalized, warnings = normalize_import_settings(raw, fallback)
        self.assertEqual(len(normalized["alert_keywords"]), 10)
        self.assertTrue(any("alert_keywords" in warning for warning in warnings))

    def test_load_config_file_normalizes_runtime_values(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "config.json"
            cfg_path.write_text(
                json.dumps(
                    {
                        "app_settings": {
                            "theme_index": 9,
                            "refresh_interval_index": 999,
                            "notification_enabled": "true",
                            "alert_keywords": ["AI", "AI", "ECON"] + [f"k{i}" for i in range(20)],
                            "sound_enabled": "0",
                            "minimize_to_tray": "yes",
                            "close_to_tray": "no",
                            "start_minimized": 1,
                            "auto_start_enabled": 0,
                            "notify_on_refresh": "off",
                            "api_timeout": -1,
                        },
                        "pagination_state": {
                            "ai|coin": "301",
                            "too-large": 5000,
                            "zero": 0,
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            loaded = load_config_file(str(cfg_path))
            app = loaded["app_settings"]

            self.assertEqual(app["theme_index"], 1)
            self.assertEqual(app["refresh_interval_index"], 5)
            self.assertEqual(app["api_timeout"], 5)
            self.assertTrue(app["notification_enabled"])
            self.assertFalse(app["sound_enabled"])
            self.assertTrue(app["minimize_to_tray"])
            self.assertFalse(app["close_to_tray"])
            self.assertTrue(app["start_minimized"])
            self.assertFalse(app["auto_start_enabled"])
            self.assertFalse(app["notify_on_refresh"])
            self.assertLessEqual(len(app["alert_keywords"]), 10)
            self.assertEqual(app["alert_keywords"][0], "AI")

            self.assertEqual(loaded["pagination_state"]["ai|coin"], 301)
            self.assertEqual(loaded["pagination_state"]["too-large"], 1000)
            self.assertNotIn("zero", loaded["pagination_state"])

