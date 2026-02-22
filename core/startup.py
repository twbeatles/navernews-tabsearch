import logging
import os
import sys

from core.constants import APP_DIR

try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    WINREG_AVAILABLE = False

logger = logging.getLogger(__name__)

class StartupManager:
    """Windows 시작프로그램 레지스트리 관리"""
    REGISTRY_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    APP_NAME = "NaverNewsScraperPro"
    
    @classmethod
    def is_available(cls) -> bool:
        """Windows 레지스트리 사용 가능 여부"""
        return WINREG_AVAILABLE and sys.platform == 'win32'
    
    @classmethod
    def is_startup_enabled(cls) -> bool:
        """시작프로그램 등록 여부 확인"""
        if not cls.is_available():
            return False
        
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REGISTRY_KEY, 0, winreg.KEY_READ) as key:
                try:
                    winreg.QueryValueEx(key, cls.APP_NAME)
                    return True
                except FileNotFoundError:
                    return False
        except Exception as e:
            logger.warning(f"레지스트리 읽기 오류: {e}")
            return False
    
    @classmethod
    def enable_startup(cls, start_minimized: bool = False) -> bool:
        """시작프로그램에 등록"""
        if not cls.is_available():
            return False
        
        try:
            exe_path = cls.build_startup_command(start_minimized=start_minimized)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, cls.APP_NAME, 0, winreg.REG_SZ, exe_path)
            
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
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls.REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
                try:
                    winreg.DeleteValue(key, cls.APP_NAME)
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
