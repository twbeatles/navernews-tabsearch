import os
import signal
import sys
import threading
import traceback
from datetime import datetime

os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from PyQt6.QtCore import QLockFile
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.backup import apply_pending_restore_if_any
from core.constants import APP_DIR, APP_NAME, CONFIG_FILE, DB_FILE, PENDING_RESTORE_FILE, VERSION
from core.logging_setup import configure_logging
from ui.main_window import MainApp

configure_logging()
import logging
logger = logging.getLogger(__name__)

CRASH_LOG_FILE = os.path.join(APP_DIR, "crash_log.txt")
INSTANCE_LOCK_FILE = os.path.join(APP_DIR, "news_scraper_pro.lock")

def main():
    """메인 함수 - 안정성 개선 버전 (종료 원인 추적 포함)"""
    # 전역 예외 처리기
    def exception_hook(exc_type, exc_value, exc_tb):
        logger.critical("처리되지 않은 예외 발생:")
        logger.critical("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        # 크래시 로그 파일에도 저장
        try:
            with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {datetime.now()}\n")
                f.write(f"유형: Main Thread Exception\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except (IOError, OSError) as e:
            logger.error(f"크래시 로그 저장 실패: {e}")
    
    # 스레드 예외 처리기 (Python 3.8+)
    def thread_exception_hook(args):
        logger.critical(f"스레드 예외 발생 ({args.thread.name if args.thread else 'Unknown'}):")
        logger.critical("".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
        try:
            with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {datetime.now()}\n")
                f.write(f"유형: Thread Exception ({args.thread.name if args.thread else 'Unknown'})\n")
                traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback, file=f)
        except (IOError, OSError) as e:
            logger.error(f"크래시 로그 저장 실패: {e}")
    
    sys.excepthook = exception_hook
    
    # Python 3.8+ 스레드 예외 훅
    if hasattr(threading, 'excepthook'):
        threading.excepthook = thread_exception_hook
    
    # 윈도우 참조 저장 (시그널 핸들러에서 사용)
    window = None
    
    # SIGTERM/SIGINT 핸들러 (외부에서 프로세스 종료 시)
    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.warning(f"외부 종료 신호 수신: {sig_name}")
        try:
            with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {datetime.now()}\n")
                f.write(f"유형: Signal Received - {sig_name}\n")
        except (IOError, OSError):
            pass
        
        if window:
            window._system_shutdown = True
            window._force_close = True
            window.close()
    
    # Windows에서는 SIGTERM이 지원될 수 있음
    try:
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    except (ValueError, OSError) as e:
        logger.warning(f"시그널 핸들러 등록 실패: {e}")

    # 재시작 적용형 백업 복원 처리 (DB 초기화 전)
    try:
        if apply_pending_restore_if_any(
            pending_file=PENDING_RESTORE_FILE,
            config_file=CONFIG_FILE,
            db_file=DB_FILE,
        ):
            logger.info("예약된 백업 복원이 시작 시 적용되었습니다.")
    except Exception as e:
        logger.error(f"예약 복원 적용 중 오류: {e}")
    
    try:
        logger.info(f"{APP_NAME} v{VERSION} 시작 중...")
        
        app = QApplication(sys.argv)
        instance_lock = QLockFile(INSTANCE_LOCK_FILE)
        instance_lock.setStaleLockTime(30000)
        if not instance_lock.tryLock(0):
            QMessageBox.information(
                None,
                "이미 실행 중",
                "뉴스 스크래퍼 Pro가 이미 실행 중입니다.\n기존 창을 사용해주세요.",
            )
            logger.info("중복 실행 감지: 새 인스턴스를 종료합니다.")
            sys.exit(0)

        app._instance_lock = instance_lock
        # app.setStyle("Fusion")
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        font = app.font()
        font.setFamily("맑은 고딕")
        app.setFont(font)
        
        window = MainApp()
        window.show()
        
        logger.info(f"{APP_NAME} v{VERSION} 시작됨")
        
        exit_code = app.exec()
        try:
            if hasattr(app, "_instance_lock") and app._instance_lock:
                app._instance_lock.unlock()
        except Exception:
            pass
        sys.exit(exit_code)
        
    except Exception as e:
        error_msg = f"애플리케이션 시작 오류: {e}"
        logger.error(error_msg)
        traceback.print_exc()

        try:
            app_instance = QApplication.instance()
            if app_instance and hasattr(app_instance, "_instance_lock") and app_instance._instance_lock:
                app_instance._instance_lock.unlock()
        except Exception:
            pass
        
        # 크래시 로그 파일에 기록
        try:
            with open(CRASH_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {datetime.now()}\n")
                f.write(f"오류: {error_msg}\n")
                f.write(traceback.format_exc())
        except (IOError, OSError):
            pass
        
        # 메시지 박스 표시 (가능한 경우)
        try:
            # QApplication은 이미 전역으로 import 되어 있음
            # 만약 QApplication이 없다면 이 부분도 실패하겠지만, main 진입했다면 import는 성공한 상태임
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "시작 오류",
                f"프로그램을 시작할 수 없습니다:\n\n{str(e)}\n\n자세한 내용은 {CRASH_LOG_FILE}를 확인하세요.",
            )
        except Exception:
            pass
        
        sys.exit(1)

