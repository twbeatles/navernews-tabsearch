import logging
import os
import re
import sys
from types import ModuleType
from typing import Optional, TypedDict

from core.constants import APP_DIR

try:
    import winreg
    _WINREG: Optional[ModuleType] = winreg
    WINREG_AVAILABLE = True
except ImportError:
    _WINREG = None
    WINREG_AVAILABLE = False

logger = logging.getLogger(__name__)


class StartupStatus(TypedDict):
    has_registry_value: bool
    expected_command: str
    actual_command: str
    expected_target: str
    actual_target: str
    command_matches: bool
    target_exists: bool
    is_healthy: bool
    needs_repair: bool


def _get_winreg() -> ModuleType:
    if _WINREG is None:
        raise RuntimeError("winreg is unavailable on this platform")
    return _WINREG

class StartupManager:
    """Windows 시작프로그램 레지스트리 관리"""
    REGISTRY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "NaverNewsScraperPro"
    
    @classmethod
    def is_available(cls) -> bool:
        """Windows 레지스트리 사용 가능 여부"""
        return WINREG_AVAILABLE and sys.platform == 'win32'

    @staticmethod
    def _tokenize_command(command: str) -> list[str]:
        tokens = []
        for match in re.finditer(r'"([^"]*)"|(\S+)', str(command or "").strip()):
            token = match.group(1) if match.group(1) is not None else match.group(2)
            if token is not None:
                tokens.append(token)
        return tokens

    @classmethod
    def _extract_target_path(cls, command: str) -> str:
        tokens = cls._tokenize_command(command)
        if not tokens:
            return ""
        if len(tokens) >= 2 and tokens[1].lower().endswith(".py"):
            return tokens[1]
        return tokens[0]

    @classmethod
    def get_startup_status(cls, start_minimized: bool = False) -> StartupStatus:
        expected_command = cls.build_startup_command(start_minimized=start_minimized) if cls.is_available() else ""
        actual_command = ""
        has_registry_value = False

        if cls.is_available():
            try:
                winreg_mod = _get_winreg()
                with winreg_mod.OpenKey(
                    winreg_mod.HKEY_CURRENT_USER,
                    cls.REGISTRY_KEY,
                    0,
                    winreg_mod.KEY_READ,
                ) as key:
                    try:
                        raw_value, _value_type = winreg_mod.QueryValueEx(key, cls.APP_NAME)
                        actual_command = str(raw_value or "")
                        has_registry_value = bool(actual_command.strip())
                    except FileNotFoundError:
                        has_registry_value = False
            except Exception as e:
                logger.warning("레지스트리 읽기 오류: %s", e)

        actual_target = cls._extract_target_path(actual_command)
        expected_target = cls._extract_target_path(expected_command)
        command_matches = bool(has_registry_value and actual_command.strip() == expected_command.strip())
        target_exists = bool(actual_target and os.path.exists(actual_target))
        is_healthy = bool(has_registry_value and command_matches and target_exists)

        return {
            "has_registry_value": has_registry_value,
            "expected_command": expected_command,
            "actual_command": actual_command,
            "expected_target": expected_target,
            "actual_target": actual_target,
            "command_matches": command_matches,
            "target_exists": target_exists,
            "is_healthy": is_healthy,
            "needs_repair": bool(has_registry_value and not is_healthy),
        }
    
    @classmethod
    def is_startup_enabled(cls) -> bool:
        """호환용 wrapper: 등록 상태가 건강한 경우에만 True."""
        return bool(cls.get_startup_status().get("is_healthy", False))

    @classmethod
    def has_startup_entry(cls) -> bool:
        """레지스트리 값 존재 여부만 확인."""
        return bool(cls.get_startup_status().get("has_registry_value", False))
    
    @classmethod
    def enable_startup(cls, start_minimized: bool = False) -> bool:
        """시작프로그램에 등록"""
        if not cls.is_available():
            return False
        
        try:
            exe_path = cls.build_startup_command(start_minimized=start_minimized)
            winreg_mod = _get_winreg()
            with winreg_mod.OpenKey(
                winreg_mod.HKEY_CURRENT_USER,
                cls.REGISTRY_KEY,
                0,
                winreg_mod.KEY_SET_VALUE,
            ) as key:
                winreg_mod.SetValueEx(key, cls.APP_NAME, 0, winreg_mod.REG_SZ, exe_path)
            
            logger.info(f"시작프로그램 등록 완료: {exe_path}")
            return True
        except Exception as e:
            logger.error(f"시작프로그램 등록 오류: {e}")
            return False
    
    @classmethod
    def disable_startup(cls) -> bool:
        """시작프로그램에서 제거"""
        if not cls.is_available():
            return False
        
        try:
            winreg_mod = _get_winreg()
            with winreg_mod.OpenKey(
                winreg_mod.HKEY_CURRENT_USER,
                cls.REGISTRY_KEY,
                0,
                winreg_mod.KEY_SET_VALUE,
            ) as key:
                try:
                    winreg_mod.DeleteValue(key, cls.APP_NAME)
                    logger.info("시작프로그램 등록 해제 완료")
                    return True
                except FileNotFoundError:
                    # 이미 등록되어 있지 않음
                    return True
        except Exception as e:
            logger.error(f"시작프로그램 해제 오류: {e}")
            return False

    @classmethod
    def build_startup_command(cls, start_minimized: bool = False) -> str:
        """시작프로그램 등록용 실행 명령 생성."""
        if getattr(sys, 'frozen', False):
            command = f'"{sys.executable}"'
        else:
            entrypoint_path = os.path.join(APP_DIR, "news_scraper_pro.py")
            command = f'"{sys.executable}" "{entrypoint_path}"'

        if start_minimized:
            command += " --minimized"
        return command
