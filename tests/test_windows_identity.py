import tempfile
import unittest
from pathlib import Path

from core.constants import APP_USER_MODEL_ID
from core.windows_identity import (
    _register_notification_app_identity,
    _resolve_notification_icon_path,
    _set_process_app_user_model_id,
    configure_windows_app_identity,
)


class _FakeSetAppId:
    def __init__(self, result=0):
        self.result = result
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, app_user_model_id):
        self.calls.append(app_user_model_id)
        return self.result


class _FakeShell32:
    def __init__(self, result=0):
        self.SetCurrentProcessExplicitAppUserModelID = _FakeSetAppId(result=result)


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeWinreg:
    HKEY_CURRENT_USER = object()
    REG_SZ = 1
    REG_EXPAND_SZ = 2

    def __init__(self):
        self.created = []
        self.values = []

    def CreateKey(self, root, path):
        self.created.append((root, path))
        return _FakeKey()

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values.append((name, reserved, value_type, value))


class WindowsIdentityTests(unittest.TestCase):
    def test_app_user_model_id_is_windows_safe(self):
        self.assertLessEqual(len(APP_USER_MODEL_ID), 128)
        self.assertNotIn(" ", APP_USER_MODEL_ID)
        self.assertEqual(APP_USER_MODEL_ID, "Twbeatles.NaverNewsScraperPro")

    def test_resolve_notification_icon_prefers_ico(self):
        with tempfile.TemporaryDirectory() as tmp:
            app_dir = Path(tmp)
            (app_dir / "news_icon.png").write_bytes(b"png")
            (app_dir / "news_icon.ico").write_bytes(b"ico")

            resolved = _resolve_notification_icon_path(str(app_dir))

        self.assertTrue(str(resolved).endswith("news_icon.ico"))

    def test_set_process_app_user_model_id_calls_shell_api(self):
        shell32 = _FakeShell32()

        self.assertTrue(_set_process_app_user_model_id(APP_USER_MODEL_ID, shell32=shell32))

        self.assertEqual(shell32.SetCurrentProcessExplicitAppUserModelID.calls, [APP_USER_MODEL_ID])

    def test_register_notification_app_identity_sets_display_name_and_icon(self):
        fake_winreg = _FakeWinreg()

        self.assertTrue(
            _register_notification_app_identity(
                APP_USER_MODEL_ID,
                "뉴스 스크래퍼 Pro",
                r"C:\Apps\NaverNewsScraperPro\news_icon.ico",
                winreg_module=fake_winreg,
            )
        )

        self.assertEqual(
            fake_winreg.created,
            [
                (
                    fake_winreg.HKEY_CURRENT_USER,
                    r"Software\Classes\AppUserModelId\Twbeatles.NaverNewsScraperPro",
                )
            ],
        )
        self.assertIn(("DisplayName", 0, fake_winreg.REG_SZ, "뉴스 스크래퍼 Pro"), fake_winreg.values)
        self.assertIn(
            (
                "IconUri",
                0,
                fake_winreg.REG_EXPAND_SZ,
                r"C:\Apps\NaverNewsScraperPro\news_icon.ico",
            ),
            fake_winreg.values,
        )

    def test_configure_windows_app_identity_is_noop_off_windows(self):
        self.assertIsNone(configure_windows_app_identity(platform="linux"))


if __name__ == "__main__":
    unittest.main()
