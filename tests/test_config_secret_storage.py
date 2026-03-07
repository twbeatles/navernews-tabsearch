import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.config_store import (
    default_config,
    encode_client_secret_for_storage,
    load_config_file,
    resolve_client_secret_for_runtime,
    save_config_file_atomic,
)


class TestConfigSecretStorage(unittest.TestCase):
    def test_default_schema_contains_secret_storage_fields(self):
        cfg = default_config()
        app_settings = cfg["app_settings"]
        self.assertIn("client_secret_enc", app_settings)
        self.assertIn("client_secret_storage", app_settings)

    def test_encode_client_secret_plain_off_windows(self):
        with mock.patch("core.config_store._is_windows_platform", return_value=False):
            payload = encode_client_secret_for_storage("plain-secret")

        self.assertEqual(payload["client_secret"], "plain-secret")
        self.assertEqual(payload["client_secret_enc"], "")
        self.assertEqual(payload["client_secret_storage"], "plain")

    def test_resolve_prefers_encrypted_payload_on_windows(self):
        settings = {
            "client_secret": "legacy-plain",
            "client_secret_enc": "encrypted",
            "client_secret_storage": "dpapi",
        }
        with mock.patch("core.config_store._is_windows_platform", return_value=True):
            with mock.patch("core.config_store._dpapi_decrypt_text", return_value="decrypted"):
                secret, needs_migration = resolve_client_secret_for_runtime(settings)

        self.assertEqual(secret, "decrypted")
        self.assertTrue(needs_migration)

    def test_load_config_file_uses_backup_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg_path = root / "news_scraper_config.json"
            backup_path = Path(f"{cfg_path}.backup")

            cfg_path.write_text("{broken-json", encoding="utf-8")

            payload = default_config()
            payload["app_settings"]["client_id"] = "cid-backup"
            save_config_file_atomic(str(backup_path), payload)

            loaded = load_config_file(str(cfg_path))
            self.assertEqual(loaded["app_settings"]["client_id"], "cid-backup")

            reloaded_main = json.loads(cfg_path.read_text(encoding="utf-8"))
            self.assertIn("app_settings", reloaded_main)
            self.assertEqual(reloaded_main["app_settings"]["client_id"], "cid-backup")

    def test_plain_secret_is_migrated_to_dpapi_on_windows(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "news_scraper_config.json"
            payload = default_config()
            payload["app_settings"]["client_secret"] = "legacy-secret"
            payload["app_settings"]["client_secret_enc"] = ""
            payload["app_settings"]["client_secret_storage"] = "plain"
            save_config_file_atomic(str(cfg_path), payload)

            with mock.patch("core.config_store._is_windows_platform", return_value=True):
                with mock.patch("core.config_store._dpapi_encrypt_text", return_value="ENC_PAYLOAD"):
                    loaded = load_config_file(str(cfg_path))

            app_settings = loaded["app_settings"]
            self.assertEqual(app_settings["client_secret"], "")
            self.assertEqual(app_settings["client_secret_enc"], "ENC_PAYLOAD")
            self.assertEqual(app_settings["client_secret_storage"], "dpapi")

            persisted = json.loads(cfg_path.read_text(encoding="utf-8"))
            persisted_app = persisted["app_settings"]
            self.assertEqual(persisted_app["client_secret"], "")
            self.assertEqual(persisted_app["client_secret_enc"], "ENC_PAYLOAD")
            self.assertEqual(persisted_app["client_secret_storage"], "dpapi")
