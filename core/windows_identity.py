from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Any, Optional

from core.constants import APP_DIR, APP_NAME, APP_USER_MODEL_ID, ICON_FILE, ICON_PNG

logger = logging.getLogger(__name__)


def _resolve_notification_icon_path(app_dir: str = APP_DIR) -> Optional[str]:
    for icon_name in (ICON_FILE, ICON_PNG):
        icon_path = os.path.abspath(os.path.join(app_dir, icon_name))
        if os.path.exists(icon_path):
            return icon_path
    return None


def _set_process_app_user_model_id(app_user_model_id: str, *, shell32: Any = None) -> bool:
    try:
        shell = shell32 if shell32 is not None else ctypes.windll.shell32
        set_app_id = shell.SetCurrentProcessExplicitAppUserModelID
        set_app_id.argtypes = [ctypes.c_wchar_p]
        set_app_id.restype = ctypes.c_long
        result = int(set_app_id(app_user_model_id))
        if result != 0:
            logger.warning("Windows AppUserModelID 설정 실패: HRESULT=%s", result)
            return False
        return True
    except Exception as exc:
        logger.warning("Windows AppUserModelID 설정 오류: %s", exc)
        return False


def _register_notification_app_identity(
    app_user_model_id: str,
    display_name: str,
    icon_path: Optional[str],
    *,
    winreg_module: Any = None,
) -> bool:
    try:
        if winreg_module is None:
            import winreg as _winreg  # type: ignore[import-not-found]

            winreg = _winreg
        else:
            winreg = winreg_module

        registry_path = fr"Software\Classes\AppUserModelId\{app_user_model_id}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, display_name)
            if icon_path:
                winreg.SetValueEx(key, "IconUri", 0, winreg.REG_EXPAND_SZ, icon_path)
        return True
    except Exception as exc:
        logger.warning("Windows 알림 앱 ID 등록 오류: %s", exc)
        return False


def configure_windows_app_identity(*, platform: Optional[str] = None) -> None:
    """Give Windows tray/toast notifications a stable app name and icon."""
    if (platform or sys.platform) != "win32":
        return

    icon_path = _resolve_notification_icon_path()
    _set_process_app_user_model_id(APP_USER_MODEL_ID)
    _register_notification_app_identity(APP_USER_MODEL_ID, APP_NAME, icon_path)
