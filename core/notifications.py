import logging
import sys

from core.logging_setup import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

class NotificationSound:
    """시스템 알림 소리 재생"""
    
    @staticmethod
    def play(sound_type: str = "default"):
        """
        알림 소리 재생
        sound_type: 'default', 'success', 'warning', 'error'
        """
        try:
            if sys.platform == 'win32':
                import winsound
                sounds = {
                    'default': winsound.MB_OK,
                    'success': winsound.MB_ICONASTERISK,
                    'warning': winsound.MB_ICONEXCLAMATION,
                    'error': winsound.MB_ICONHAND,
                }
                sound = sounds.get(sound_type, winsound.MB_OK)
                winsound.MessageBeep(sound)
            else:
                # macOS/Linux: 터미널 벨 사용
                print('\a', end='', flush=True)
        except Exception as e:
            logger.debug(f"알림 소리 재생 실패: {e}")
    
    @staticmethod
    def is_available() -> bool:
        """알림 소리 사용 가능 여부"""
        if sys.platform == 'win32':
            try:
                import winsound
                return True
            except ImportError:
                return False
        return True
