import os
import signal
import sys
import threading
import traceback
import hashlib
import time
from datetime import datetime
from typing import Callable, Optional

os.environ.setdefault('QT_AUTO_SCREEN_SCALE_FACTOR', '1')
os.environ.setdefault('QT_ENABLE_HIGHDPI_SCALING', '1')

from PyQt6.QtCore import QLockFile, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.backup import apply_pending_restore_if_any
from core.constants import APP_DIR, APP_NAME, CONFIG_FILE, DB_FILE, PENDING_RESTORE_FILE, VERSION
from core.logging_setup import configure_logging
from core.protocols import LockFileProtocol
from ui.main_window import MainApp

configure_logging()
import logging
logger = logging.getLogger(__name__)

CRASH_LOG_FILE = os.path.join(APP_DIR, "crash_log.txt")
INSTANCE_LOCK_FILE = os.path.join(APP_DIR, "news_scraper_pro.lock")
INSTANCE_SERVER_NAME = f"news_scraper_pro_single_instance_{hashlib.sha1(APP_DIR.encode('utf-8')).hexdigest()[:12]}"
INSTANCE_SHOW_COMMAND = "SHOW"


def _notify_existing_instance(timeout_ms: int = 1200) -> bool:
    """동일 앱의 기존 인스턴스에 창 복원 요청을 전달."""
    deadline = time.time() + max(0.2, timeout_ms / 1000.0)
    while time.time() < deadline:
        socket = QLocalSocket()
        socket.connectToServer(INSTANCE_SERVER_NAME)
        if socket.waitForConnected(200):
            try:
                socket.write(INSTANCE_SHOW_COMMAND.encode("utf-8"))
                socket.flush()
                socket.waitForBytesWritten(200)
            finally:
                socket.disconnectFromServer()
            return True
        socket.abort()
        time.sleep(0.08)
    return False


def _setup_instance_server(
    app: QApplication,
    activate_window: Callable[[], object | None],
) -> Optional[QLocalServer]:
    """기존 인스턴스가 복원 요청을 받을 로컬 서버를 시작."""
    QLocalServer.removeServer(INSTANCE_SERVER_NAME)
    server = QLocalServer(app)
    if not server.listen(INSTANCE_SERVER_NAME):
        logger.warning(
            "단일 인스턴스 IPC 서버 시작 실패: %s",
            server.errorString(),
        )
        return None

    def _consume_payload(socket):
        if socket is None:
            return
        if bool(socket.property("_instance_payload_handled")):
            return
        payload = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip().upper()
        if not payload:
            return
        socket.setProperty("_instance_payload_handled", True)
        if payload == INSTANCE_SHOW_COMMAND:
            QTimer.singleShot(0, activate_window)

    def on_new_connection():
        while server.hasPendingConnections():
            socket = server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda s=socket: _consume_payload(s))
            socket.disconnected.connect(socket.deleteLater)
            _consume_payload(socket)

    server.newConnection.connect(on_new_connection)
    return server


def _resolve_single_instance_conflict(
    instance_lock: LockFileProtocol,
    notifier: Callable[[], bool] = _notify_existing_instance,
) -> str:
    """중복 실행 충돌 해소를 시도하고 상태 코드를 반환."""
    if notifier():
        return "notify_success"

    try:
        instance_lock.removeStaleLockFile()
    except Exception as e:
        logger.warning("stale lock 파일 제거 시도 실패: %s", e)

    if instance_lock.tryLock(0):
        return "stale_recovered"
    return "blocked"

def main():
    """메인 함수 - 안정성 개선 버전 (종료 원인 추적 포함)"""
    app: Optional[QApplication] = None
    window: Optional[MainApp] = None
    instance_lock: Optional[QLockFile] = None
    instance_server: Optional[QLocalServer] = None

    def cleanup_instance_state() -> None:
        nonlocal instance_lock, instance_server
        try:
            if instance_lock is not None:
                instance_lock.unlock()
        except Exception:
            pass
        try:
            if instance_server is not None:
                instance_server.close()
                QLocalServer.removeServer(INSTANCE_SERVER_NAME)
        except Exception:
            pass
        instance_lock = None
        instance_server = None

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
        instance_lock.setStaleLockTime(10000)
        if not instance_lock.tryLock(0):
            while True:
                conflict_state = _resolve_single_instance_conflict(instance_lock)
                logger.info("single_instance|status=%s", conflict_state)
                if conflict_state == "notify_success":
                    logger.info("중복 실행 감지: 기존 인스턴스에 창 복원 요청 전달 후 종료")
                    sys.exit(0)
                if conflict_state == "stale_recovered":
                    logger.info("단일 인스턴스 락 복구 성공: stale lock 제거 후 실행 지속")
                    break

                message_box = QMessageBox()
                message_box.setIcon(QMessageBox.Icon.Information)
                message_box.setWindowTitle("이미 실행 중")
                message_box.setText("뉴스 스크래퍼 Pro가 이미 실행 중이거나 잠금 파일이 남아 있습니다.")
                message_box.setInformativeText(
                    "기존 창 복원 요청에 실패했습니다.\n"
                    "잠금 파일 문제일 수 있습니다. 다시 시도할까요?"
                )
                message_box.setStandardButtons(
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close
                )
                message_box.setDefaultButton(QMessageBox.StandardButton.Retry)
                reply = message_box.exec()
                if reply != QMessageBox.StandardButton.Retry:
                    logger.info("single_instance|status=blocked")
                    sys.exit(0)

        # app.setStyle("Fusion")
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        font = app.font()
        font.setFamily("맑은 고딕")
        app.setFont(font)
        
        window = MainApp()
        instance_server = _setup_instance_server(
            app,
            lambda: window.show_window() if window else None,
        )
        window.show()
        
        logger.info(f"{APP_NAME} v{VERSION} 시작됨")
        
        exit_code = app.exec()
        cleanup_instance_state()
        sys.exit(exit_code)
        
    except Exception as e:
        error_msg = f"애플리케이션 시작 오류: {e}"
        logger.error(error_msg)
        traceback.print_exc()
        cleanup_instance_state()
        
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
            app_instance = QApplication.instance()
            app = app_instance if isinstance(app_instance, QApplication) else QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "시작 오류",
                f"프로그램을 시작할 수 없습니다:\n\n{str(e)}\n\n자세한 내용은 {CRASH_LOG_FILE}를 확인하세요.",
            )
        except Exception:
            pass
        
        sys.exit(1)

