from __future__ import annotations

import ctypes
import logging
import os
import sys
from typing import Any, Optional

from core.constants import APP_DIR, APP_NAME, APP_USER_MODEL_ID, ICON_FILE, ICON_PNG

logger = logging.getLogger(__name__)


_CLASS_ICON_HANDLES: list[int] = []


def _resolve_notification_icon_path(app_dir: str = APP_DIR) -> Optional[str]:
    for icon_name in (ICON_FILE, ICON_PNG):
        icon_path = os.path.abspath(os.path.join(app_dir, icon_name))
        if os.path.exists(icon_path):
            return icon_path
    return None


def resolve_runtime_icon_path(
    *,
    app_dir: str = APP_DIR,
    extra_dirs: tuple[str, ...] | list[str] = (),
    meipass: Optional[str] = None,
    frozen: Optional[bool] = None,
    executable: Optional[str] = None,
) -> Optional[str]:
    """Find the icon Qt should load for the window and tray.

    One-file builds extract ``news_icon.ico`` into the temporary bundle
    directory, not next to the executable the updater replaces.
    """
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    search_dirs: list[str] = []
    bundle_dir = meipass if meipass is not None else getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        search_dirs.append(str(bundle_dir))
    search_dirs.append(app_dir)
    if is_frozen:
        exe_path = executable if executable is not None else getattr(sys, "executable", "")
        if exe_path:
            search_dirs.append(os.path.dirname(os.path.abspath(exe_path)))
    elif app_dir:
        search_dirs.append(os.path.dirname(os.path.abspath(app_dir)))
    search_dirs.extend(str(path) for path in extra_dirs if path)

    seen: set[str] = set()
    for base_dir in search_dirs:
        normalized = os.path.abspath(base_dir)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if sys.platform == "win32":
            ico_path = os.path.join(normalized, ICON_FILE)
            if os.path.isfile(ico_path):
                return ico_path
        png_path = os.path.join(normalized, ICON_PNG)
        if os.path.isfile(png_path):
            return png_path
    return None


def resolve_shell_icon_uri(
    *,
    app_dir: str = APP_DIR,
    frozen: Optional[bool] = None,
    executable: Optional[str] = None,
) -> Optional[str]:
    """Return a stable icon path for the Windows app identity.

    A one-file update replaces only the executable, so a sidecar icon is not
    part of the download. The executable's own icon resource is the stable
    identity. Temporary bundle paths are not, because they disappear on exit.
    """
    is_frozen = bool(getattr(sys, "frozen", False) if frozen is None else frozen)
    stable_dirs = [app_dir]
    if not is_frozen and app_dir:
        stable_dirs.append(os.path.dirname(os.path.abspath(app_dir)))
    for base_dir in stable_dirs:
        if not base_dir:
            continue
        icon_path = _resolve_notification_icon_path(base_dir)
        if icon_path:
            return icon_path
    if not is_frozen:
        return None
    exe_path = os.path.abspath(executable if executable is not None else getattr(sys, "executable", ""))
    if exe_path and os.path.isfile(exe_path):
        return exe_path
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

    icon_path = resolve_shell_icon_uri()
    _set_process_app_user_model_id(APP_USER_MODEL_ID)
    _register_notification_app_identity(APP_USER_MODEL_ID, APP_NAME, icon_path)


def assign_window_class_icon(hwnd: int) -> bool:
    """Point the shared Qt window class at the same icon Windows shows for the exe.

    The startup splash creates the Qt window class before the main window sets
    its icon. Windows then keeps that class icon for the taskbar and Alt-Tab,
    which is the generic Qt window rather than the application icon.
    """
    if sys.platform != "win32" or not hwnd:
        return False
    icon_source = resolve_shell_icon_uri() or resolve_runtime_icon_path()
    if not icon_source:
        return False
    try:
        big, small = _load_shell_icons(icon_source)
        if not big and not small:
            return False
        user32 = ctypes.windll.user32
        setter = getattr(user32, "SetClassLongPtrW", None) or user32.SetClassLongW
        setter.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        setter.restype = ctypes.c_void_p
        if big:
            setter(hwnd, -14, big)  # GCLP_HICON
            _CLASS_ICON_HANDLES.append(big)
        if small:
            setter(hwnd, -34, small)  # GCLP_HICONSM
            _CLASS_ICON_HANDLES.append(small)
        return True
    except Exception as exc:
        logger.warning("창 클래스 아이콘 설정 오류: %s", exc)
        return False


def _load_shell_icons(icon_source: str) -> tuple[int, int]:
    if icon_source.lower().endswith(".exe"):
        shell32 = ctypes.windll.shell32
        large = ctypes.c_void_p()
        small = ctypes.c_void_p()
        extract = shell32.ExtractIconExW
        extract.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_uint,
        ]
        extract.restype = ctypes.c_uint
        if not extract(icon_source, 0, ctypes.byref(large), ctypes.byref(small), 1):
            return 0, 0
        return int(large.value or 0), int(small.value or 0)

    user32 = ctypes.windll.user32
    image_icon = 1
    load_from_file = 0x0010
    user32.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.LoadImageW.restype = ctypes.c_void_p

    def load(width_metric: int, height_metric: int, fallback: int) -> int:
        width = int(user32.GetSystemMetrics(width_metric) or fallback)
        height = int(user32.GetSystemMetrics(height_metric) or fallback)
        handle = user32.LoadImageW(None, icon_source, image_icon, width, height, load_from_file)
        return int(handle or 0)

    return load(11, 12, 32), load(49, 50, 16)
