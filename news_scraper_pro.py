# --- 필요 라이브러리 설치 ---
# pip install PyQt6 requests
import sys
import json
import traceback
import requests
from requests.adapters import HTTPAdapter
import os
import html
import urllib.parse
import sqlite3
import threading
import csv
import shutil
import hashlib
import re
import time
import logging
import signal
import inspect
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from collections import deque
from typing import List, Dict, Optional, Tuple
from queue import Queue
from functools import partial, lru_cache
from enum import Enum
from styles import Colors, UIConstants, ToastType, AppStyle

# Windows 전용 레지스트리 모듈 (자동 시작 기능용)
try:
    import winreg
    WINREG_AVAILABLE = True
except ImportError:
    WINREG_AVAILABLE = False

# --- HiDPI 지원 (반드시 PyQt6 임포트 전에 설정) ---
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextBrowser, QLabel, QMessageBox,
    QTabWidget, QInputDialog, QComboBox, QFileDialog, QSystemTrayIcon,
    QMenu, QStyle, QTabBar, QDialog, QDialogButtonBox, QGroupBox,
    QGridLayout, QProgressBar, QCheckBox, QTextEdit, QListWidget,
    QGraphicsOpacityEffect, QToolTip, QScrollArea, QDateEdit, QToolButton,
    QFrame
)
from PyQt6.QtCore import (
    QThread, QObject, pyqtSignal, Qt, QTimer, QUrl, 
    QPropertyAnimation, QEasingCurve, QMutex, QMutexLocker, QDate
)
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut, QIcon

# --- 로깅 설정 (PyInstaller frozen 환경 대응) ---
def get_app_dir():
    """실행 파일 또는 스크립트가 있는 디렉토리 반환"""
    if getattr(sys, 'frozen', False):
        # PyInstaller로 빌드된 경우
        return os.path.dirname(sys.executable)
    else:
        # 일반 Python 실행
        return os.path.dirname(os.path.abspath(__file__))

APP_DIR = get_app_dir()
LOG_FILE = os.path.join(APP_DIR, "news_scraper.log")

# 로깅 핸들러 안전하게 설정
try:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
except Exception:
    # 파일 로깅 실패시 콘솔만 사용
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler()]
    )
logger = logging.getLogger(__name__)

# --- 상수 및 설정 ---
CONFIG_FILE = os.path.join(APP_DIR, "news_scraper_config.json")
DB_FILE = os.path.join(APP_DIR, "news_database.db")
ICON_FILE = "news_icon.ico"
ICON_PNG = "news_icon.png"
APP_NAME = "뉴스 스크래퍼 Pro"
VERSION = "32.5.0"  # UI/UX Refactoring + Modularization (styles.py)

# --- 색상 상수 (중앙화) ---
# --- 프리컴파일된 정규식 패턴 (성능 최적화) ---
RE_HTML_TAGS = re.compile(r'<[^>]+>')
RE_WHITESPACE = re.compile(r'\s+')
RE_BOLD_TAGS = re.compile(r'</?b>')

# --- 날짜 포맷 상수 ---
DATE_FORMATS = (
    '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%d'
)
DATE_OUTPUT_FORMAT = '%Y.%m.%d %H:%M'

def parse_date_string(date_str: str) -> str:
    """날짜 문자열 파싱 헬퍼 함수 (RFC 2822 및 여러 포맷 지원)"""
    if not date_str:
        return ""
    try:
        # RFC 2822 형식 먼저 시도 (네이버 API 기본 형식)
        dt = parsedate_to_datetime(date_str)
        return dt.strftime(DATE_OUTPUT_FORMAT)
    except (ValueError, TypeError):
        # 대체 포맷들 시도
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.strftime(DATE_OUTPUT_FORMAT)
            except (ValueError, TypeError):
                continue
    
    # 추가: 한국어 날짜 형식 등 기타 포맷 시도 (필요시 확장)
    
    return date_str  # 파싱 실패 시 원본 반환

def parse_date_to_ts(date_str: str) -> float:
    """날짜 문자열을 타임스탬프로 변환 (정렬용)"""
    if not date_str:
        return 0.0
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.timestamp()
    except (ValueError, TypeError):
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(date_str[:19], fmt)
                return dt.timestamp()
            except (ValueError, TypeError):
                continue
    return 0.0

# --- 하이라이트 패턴 캐시 (LRU 최적화) ---
@lru_cache(maxsize=128)
def get_highlight_pattern(keyword: str) -> re.Pattern:
    """하이라이트 패턴 캐시 반환 (LRU 캐시 사용)"""
    return re.compile(f'({re.escape(keyword)})', re.IGNORECASE)


# --- 유틸리티 함수 ---
class ValidationUtils:
    """입력 검증 유틸리티"""
    
    @staticmethod
    def validate_api_credentials(client_id: str, client_secret: str) -> Tuple[bool, str]:
        """API 자격증명 검증"""
        if not client_id or not client_id.strip():
            return False, "Client ID가 비어있습니다."
        if not client_secret or not client_secret.strip():
            return False, "Client Secret이 비어있습니다."
        if len(client_id.strip()) < 10:
            return False, "Client ID가 너무 짧습니다."
        if len(client_secret.strip()) < 10:
            return False, "Client Secret이 너무 짧습니다."
        return True, ""
    
    @staticmethod
    def sanitize_keyword(keyword: str) -> str:
        """키워드 정제"""
        return keyword.strip()[:100]

class TextUtils:
    """텍스트 처리 유틸리티"""
    
    @staticmethod
    def highlight_text(text: str, keyword: str) -> str:
        """텍스트에서 키워드 하이라이팅 (캐시된 패턴 사용)"""
        if not keyword:
            return html.escape(text)
        
        escaped_text = html.escape(text)
        escaped_keyword = html.escape(keyword)
        
        # 캐시된 패턴 사용 (성능 최적화)
        pattern = get_highlight_pattern(escaped_keyword)
        highlighted = pattern.sub(r"<span class='highlight'>\1</span>", escaped_text)
        
        return highlighted


# --- Windows 시작프로그램 관리 ---
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
            # 실행 파일 경로 가져오기
            if getattr(sys, 'frozen', False):
                # PyInstaller로 빌드된 경우
                exe_path = sys.executable
            else:
                # 일반 Python 실행
                exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
            
            # 최소화 옵션 추가
            if start_minimized:
                exe_path += ' --minimized'
            
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


# --- UI 상수 ---
# --- 커스텀 위젯: 토스트 메시지 큐 시스템 ---
class ToastQueue:
    """토스트 메시지 큐 관리 - 유형별 스타일 지원"""
    def __init__(self, parent):
        self.parent = parent
        self.queue = deque()
        self.current_toast = None
        self.y_offset = 100
        
    def add(self, message: str, toast_type: ToastType = ToastType.INFO):
        """토스트 메시지 추가"""
        self.queue.append((message, toast_type))
        if self.current_toast is None:
            self._show_next()
    
    def _show_next(self):
        """다음 토스트 표시"""
        if not self.queue:
            self.current_toast = None
            return
        
        message, toast_type = self.queue.popleft()
        self.current_toast = ToastMessage(self.parent, message, self, toast_type)
        
    def on_toast_finished(self):
        """토스트 종료 시 호출"""
        self.current_toast = None
        self._show_next()

class ToastMessage(QLabel):
    """화면에 잠시 나타났다 사라지는 알림 메시지 - 유형별 스타일 지원"""
    
    # 유형별 스타일 정의 - 현대화된 디자인
    STYLES = {
        ToastType.INFO: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(30, 41, 59, 245), stop:1 rgba(51, 65, 85, 245));
            color: #F1F5F9;
            border: 1px solid rgba(148, 163, 184, 0.2);
        """,
        ToastType.SUCCESS: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(5, 150, 105, 245), stop:1 rgba(16, 185, 129, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
        ToastType.WARNING: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(217, 119, 6, 245), stop:1 rgba(245, 158, 11, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
        ToastType.ERROR: """
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 rgba(185, 28, 28, 245), stop:1 rgba(239, 68, 68, 245));
            color: #FFFFFF;
            border: 1px solid rgba(255, 255, 255, 0.2);
        """,
    }
    
    # 유형별 아이콘
    ICONS = {
        ToastType.INFO: "ℹ️",
        ToastType.SUCCESS: "✓",
        ToastType.WARNING: "⚠️",
        ToastType.ERROR: "✗",
    }
    
    def __init__(self, parent, message: str, queue: ToastQueue, toast_type: ToastType = ToastType.INFO):
        # 아이콘 추가 (SUCCESS 메시지에는 이미 ✓가 있을 수 있으므로 조건부)
        display_message = message
        if toast_type == ToastType.ERROR and not message.startswith("✗"):
            display_message = f"✗ {message}"
        elif toast_type == ToastType.WARNING and not message.startswith("⚠"):
            display_message = f"⚠️ {message}"
            
        super().__init__(display_message, parent)
        self.queue = queue
        self.toast_type = toast_type
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # 유형별 스타일 적용
        base_style = self.STYLES.get(toast_type, self.STYLES[ToastType.INFO])
        self.setStyleSheet(f"""
            {base_style}
            padding: 14px 28px;
            border-radius: 24px;
            font-family: '맑은 고딕';
            font-size: 14px;
            font-weight: bold;
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        
        self.update_position()
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim_in = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.anim_in.setDuration(UIConstants.ANIMATION_DURATION)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)
        self.anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_in.start()
        
        self.show()
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(UIConstants.TOAST_DURATION)
    
    def update_position(self):
        """부모 크기 변경에 대응하는 위치 업데이트"""
        if self.parent():
            p_rect = self.parent().rect()
            self.move(
                p_rect.center().x() - self.width() // 2,
                p_rect.bottom() - self.queue.y_offset
            )

    def fade_out(self):
        """페이드 아웃 애니메이션"""
        self.anim_out = QPropertyAnimation(self.opacity_effect, b"opacity", self)
        self.anim_out.setDuration(400)
        self.anim_out.setStartValue(1.0)
        self.anim_out.setEndValue(0.0)
        self.anim_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self.anim_out.finished.connect(self.on_finished)
        self.anim_out.start()
    
    def on_finished(self):
        """애니메이션 종료 후 정리 - 메모리 누수 방지 개선"""
        try:
            # 타이머 정리
            if hasattr(self, 'timer') and self.timer and self.timer.isActive():
                self.timer.stop()
            # 애니메이션 정리
            if hasattr(self, 'anim_out'):
                self.anim_out.stop()
                self.anim_out.deleteLater()
            if hasattr(self, 'anim_in'):
                self.anim_in.stop()
                self.anim_in.deleteLater()
            # opacity_effect 정리
            if hasattr(self, 'opacity_effect') and self.opacity_effect:
                self.opacity_effect.deleteLater()
        except RuntimeError:
            pass  # 이미 삭제된 경우
        finally:
            queue = self.queue  # 참조 미리 저장 (안전성)
            self.close()
            self.deleteLater()
            if queue:
                queue.on_toast_finished()

# --- 휠 스크롤 방지 콤보박스 ---
class NoScrollComboBox(QComboBox):
    """마우스 휠로 값이 변경되지 않는 콤보박스 (설정창 UX 개선)"""
    
    def wheelEvent(self, event):
        """휠 이벤트 무시 - 부모 위젯으로 전달"""
        event.ignore()

# --- 커스텀 브라우저 (미리보기 기능) ---
class NewsBrowser(QTextBrowser):
    """링크 클릭 시 페이지 이동 차단, 호버 시 미리보기 표시"""
    action_triggered = pyqtSignal(str, str) # action, link_hash
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)  
        self.setOpenLinks(False)
        self.setMouseTracking(True)
        self.preview_data = {}
        
    def setSource(self, url):
        if url.scheme() == 'app':
            return
        super().setSource(url)
    
    def set_preview_data(self, data: Dict[str, str]):
        """미리보기 데이터 설정"""
        self.preview_data = data
    
    def mouseMoveEvent(self, event):
        """마우스 호버 시 미리보기 표시"""
        anchor = self.anchorAt(event.pos())
        
        if anchor and anchor.startswith('app://open/'):
            link_hash = anchor.split('/')[-1]
            if link_hash in self.preview_data:
                preview_text = self.preview_data[link_hash]
                if len(preview_text) > 200:
                    preview_text = preview_text[:200] + "..."
                
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"<div style='max-width: 400px;'>{html.escape(preview_text)}</div>",
                    self
                )
        else:
            QToolTip.hideText()
        
        super().mouseMoveEvent(event)

    def contextMenuEvent(self, event):
        # 마우스오버 또는 클릭 위치의 링크 확인
        anchor = self.anchorAt(event.pos())
        
        link_hash = ""
        if anchor:
            url = QUrl(anchor)
            if url.scheme() == 'app':
                link_hash = url.path().lstrip('/')
        
        # 링크 위가 아니라면 기본 메뉴 사용 (복사 등)
        if not link_hash:
            super().contextMenuEvent(event)
            return
            
        # 커스텀 메뉴 생성
        menu = QMenu(self)
        
        act_open = menu.addAction("🌐 브라우저로 열기")
        act_copy = menu.addAction("📋 제목 및 링크 복사")
        menu.addSeparator()
        act_bm = menu.addAction("⭐ 북마크 토글")
        act_read = menu.addAction("👁 읽음/안읽음 토글")
        act_note = menu.addAction("📝 메모 편집")
        menu.addSeparator()
        act_del = menu.addAction("🗑 목록에서 삭제")
        
        # 메뉴 실행
        action = menu.exec(event.globalPos())
        
        if action == act_open:
            self.emit_action("ext", link_hash)
        elif action == act_copy:
            self.emit_action("share", link_hash)
        elif action == act_bm:
            self.emit_action("bm", link_hash)
        elif action == act_read:
            self.emit_action("toggle_read", link_hash)
        elif action == act_note:
            self.emit_action("note", link_hash)
        elif action == act_del:
            self.emit_action("delete", link_hash)
            
    def emit_action(self, action, link_hash):
        self.action_triggered.emit(action, link_hash)


# --- 스타일시트 ---
# --- 개선된 데이터베이스 관리 (연결 풀 패턴) ---
class DatabaseManager:
    """스레드 안전한 데이터베이스 매니저 (연결 풀 사용) - 디버깅 버전"""
    
    def __init__(self, db_file: str, max_connections: int = 10):
        self.db_file = db_file
        self.max_connections = max_connections
        self.connection_pool = Queue(maxsize=max_connections)
        self._lock = threading.Lock()  # 추가: 스레드 안전성
        self._active_connections = 0   # 추가: 활성 연결 추적
        self._closed = False  # 추가: 종료 상태 추적
        self._emergency_connections = set()  # 추가: 비상 연결 추적
        
        # DB 무결성 검사 및 복구
        if os.path.exists(self.db_file):
            if not self._check_integrity():
                logger.error("데이터베이스 손상 감지. 복구를 시도합니다.")
                self._recover_database()
        
        self.init_db()
        
        for _ in range(max_connections):
            conn = self._create_connection()
            self.connection_pool.put(conn)
    
    def _create_connection(self):
        """새 DB 연결 생성"""
        conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")  # 추가: 30초 busy timeout
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_connection(self, timeout: float = 10.0):
        """연결 풀에서 연결 가져오기 (타임아웃 추가)"""
        if self._closed:
            conn = self._create_connection()
            with self._lock:
                self._emergency_connections.add(id(conn))
            return conn
        try:
            conn = self.connection_pool.get(timeout=timeout)
            with self._lock:
                self._active_connections += 1
            return conn
        except Exception as e:
            logger.warning(f"DB 연결 획득 실패 (timeout={timeout}s): {e}")
            logger.warning(f"활성 연결 수: {self._active_connections}/{self.max_connections}")
            # 비상 연결 생성 (풀에 반환되지 않음)
            conn = self._create_connection()
            with self._lock:
                self._emergency_connections.add(id(conn))
            return conn
    
    def return_connection(self, conn):
        """연결 풀에 연결 반환 - 비상 연결 처리 개선"""
        if conn is None:
            return
        
        conn_id = id(conn)
        
        # 비상 연결이면 풀에 반환하지 않고 닫기
        with self._lock:
            if conn_id in self._emergency_connections:
                self._emergency_connections.discard(conn_id)
                try:
                    conn.close()
                    logger.debug("비상 연결 정리됨")
                except sqlite3.Error:
                    pass
                return
        
        if self._closed:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            return
        try:
            with self._lock:
                self._active_connections = max(0, self._active_connections - 1)
            # 풀이 가득 찼으면 연결 닫기
            if self.connection_pool.full():
                conn.close()
            else:
                self.connection_pool.put_nowait(conn)
        except Exception as e:
            logger.warning(f"DB 연결 반환 실패: {e}")
            try:
                conn.close()
            except sqlite3.Error:
                pass
    def _check_integrity(self) -> bool:
        """데이터베이스 무결성 검사"""
        try:
            conn = sqlite3.connect(self.db_file)
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == "ok":
                return True
            return False
        except Exception as e:
            logger.error(f"DB 무결성 검사 실패: {e}")
            return False

    def _recover_database(self):
        """손상된 데이터베이스 백업 및 재생성"""
        try:
            # 기존 연결 풀 닫기 (이 시점엔 아직 생성 안됐지만 혹시 모르니)
            
            # 파일 백업
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{self.db_file}.corrupt_{timestamp}"
            
            if os.path.exists(self.db_file):
                try:
                    os.rename(self.db_file, backup_name)
                    logger.info(f"손상된 DB 백업 완료: {backup_name}")
                except OSError:
                    # 파일이 잠겨있거나 사용 중일 경우 복사 시도
                    import shutil
                    shutil.copy2(self.db_file, backup_name)
                    os.remove(self.db_file)
                    logger.info(f"손상된 DB 복사 및 삭제 완료: {backup_name}")
            
        except Exception as e:
            logger.critical(f"DB 복구 실패: {e}")
            # 최후의 수단: 파일명 변경 시도 (충돌 회피)
            
    def init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_file)
        conn.execute("PRAGMA foreign_keys=ON")
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news (
                    link TEXT PRIMARY KEY,
                    keyword TEXT,
                    title TEXT,
                    description TEXT,
                    pubDate TEXT,
                    publisher TEXT,
                    is_read INTEGER DEFAULT 0,
                    is_bookmarked INTEGER DEFAULT 0,
                    pubDate_ts REAL,
                    created_at REAL DEFAULT (strftime('%s', 'now')),
                    notes TEXT,
                    title_hash TEXT,
                    is_duplicate INTEGER DEFAULT 0
                )
            """)
            
            # 새 컬럼 추가 (기존 DB 호환성)
            columns_added = False
            
            # pubDate_ts 컬럼 추가 (구버전 호환)
            try:
                conn.execute("ALTER TABLE news ADD COLUMN pubDate_ts REAL")
                logger.info("pubDate_ts 컬럼 추가됨")
            except sqlite3.OperationalError:
                pass  # 이미 존재
            
            # 구버전 호환성 보강 (missing columns check)
            for col, dtype in [
                ("publisher", "TEXT"),
                ("is_read", "INTEGER DEFAULT 0"),
                ("is_bookmarked", "INTEGER DEFAULT 0"),
                ("created_at", "REAL DEFAULT (strftime('%s', 'now'))"),
                ("notes", "TEXT"),
                ("title_hash", "TEXT"),
                ("is_duplicate", "INTEGER DEFAULT 0")
            ]:
                try:
                    conn.execute(f"ALTER TABLE news ADD COLUMN {col} {dtype}")
                    logger.info(f"{col} 컬럼 추가됨 (마이그레이션)")
                    if col == "title_hash":
                        columns_added = True
                except sqlite3.OperationalError:
                    pass
            
            # 컬럼 추가 후 인덱스 생성 (성능 최적화)
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)",
                "CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)",
                "CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)",
                "CREATE INDEX IF NOT EXISTS idx_title_hash ON news(title_hash)",
                "CREATE INDEX IF NOT EXISTS idx_duplicate ON news(is_duplicate)",
                # 복합 인덱스 추가 (Phase 3 성능 최적화)
                "CREATE INDEX IF NOT EXISTS idx_keyword_read ON news(keyword, is_read)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_ts ON news(keyword, pubDate_ts DESC)",
                "CREATE INDEX IF NOT EXISTS idx_keyword_dup ON news(keyword, is_duplicate)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked_ts ON news(is_bookmarked, pubDate_ts DESC)"
            ]
            for idx in indexes:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError as e:
                    logger.debug(f"Index creation skipped: {e}")

            # 키워드-기사 매핑 테이블 (동일 기사가 여러 탭에 보이도록)
            # - news: 기사 본문/상태(읽음, 북마크, 메모 등) = 링크 단위로 1개
            # - news_keywords: 키워드 탭과 기사 매핑 + 키워드별 중복 플래그
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS news_keywords (
                        link TEXT NOT NULL,
                        keyword TEXT NOT NULL,
                        is_duplicate INTEGER DEFAULT 0,
                        created_at REAL DEFAULT (strftime('%s', 'now')),
                        PRIMARY KEY (link, keyword),
                        FOREIGN KEY (link) REFERENCES news(link) ON DELETE CASCADE
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nk_keyword ON news_keywords(keyword)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nk_link ON news_keywords(link)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_nk_keyword_dup ON news_keywords(keyword, is_duplicate)")
            except sqlite3.Error as e:
                logger.error(f"news_keywords 테이블 생성 오류: {e}")

            # 기존 DB 마이그레이션: news.keyword 기반으로 news_keywords 채우기
            # (구버전 호환: keyword/is_duplicate 컬럼에 있던 탭 정보를 매핑 테이블로 이관)
            try:
                conn.execute("""
                    INSERT OR IGNORE INTO news_keywords (link, keyword, is_duplicate)
                    SELECT link, keyword, COALESCE(is_duplicate, 0)
                    FROM news
                    WHERE keyword IS NOT NULL AND keyword != ''
                """)
            except sqlite3.Error as e:
                logger.warning(f"news_keywords 마이그레이션 스킵/실패: {e}")

            
            # 기존 데이터의 title_hash 업데이트 (마이그레이션)
            if columns_added:
                cursor = conn.execute("SELECT link, title FROM news WHERE title_hash IS NULL LIMIT 1000")
                rows = cursor.fetchall()
                if rows:
                    logger.info(f"기존 데이터 마이그레이션 중... ({len(rows)}개)")
                    for link, title in rows:
                        if title:
                            title_hash = self._calculate_title_hash(title)
                            conn.execute("UPDATE news SET title_hash = ? WHERE link = ?", (title_hash, link))
                    logger.info("마이그레이션 완료")
            
            # pubDate_ts Backfill (성능 최적화: 인덱스 활용을 위한 데이터 보정)
            cursor = conn.execute("SELECT link, pubDate FROM news WHERE pubDate_ts IS NULL LIMIT 5000")
            rows = cursor.fetchall()
            if rows:
                logger.info(f"pubDate_ts 데이터 보정 중... ({len(rows)}개)")
                updates = []
                for link, pub_date in rows:
                    ts = parse_date_to_ts(pub_date)
                    updates.append((ts, link))
                
                if updates:
                    conn.executemany("UPDATE news SET pubDate_ts = ? WHERE link = ?", updates)
                logger.info("pubDate_ts 데이터 보정 완료")
        
        conn.close()
    
    def _calculate_title_hash(self, title: str) -> str:
        """제목의 해시 계산 (중복 감지용) - 프리컴파일된 정규식 사용"""
        normalized = RE_WHITESPACE.sub('', title.lower())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def upsert_news(self, items: List[Dict], keyword: str) -> Tuple[int, int]:
        """뉴스 삽입 및 중복 감지 (배치 처리 최적화)"""
        if not items:
            return 0, 0
        
        conn = self.get_connection()
        added_count = 0
        duplicate_count = 0
        
        try:
            # 1. 데이터 전처리 (해시 계산 및 날짜 파싱)
            prepared_items: List[Dict[str, object]] = []
            hashes: List[str] = []

            for item in items:
                link = (item.get('link') or '').strip()
                if not link:
                    continue

                title = item.get('title') or ''
                desc = item.get('description') or ''
                pub_date = item.get('pubDate') or ''
                publisher = item.get('publisher') or ''

                ts = parse_date_to_ts(pub_date)
                title_hash = self._calculate_title_hash(title)
                hashes.append(title_hash)

                prepared_items.append({
                    'link': link,
                    'title': title,
                    'description': desc,
                    'pubDate': pub_date,
                    'publisher': publisher,
                    'pubDate_ts': ts,
                    'title_hash': title_hash,
                })

            if not prepared_items:
                return 0, 0

            with conn:
                # 2. 키워드 단위 중복 여부 확인 (news + news_keywords JOIN)
                # SQLite 변수 제한(999)을 고려해도 보통 100개 단위이므로 직접 조회
                placeholders = ','.join(['?'] * len(hashes))
                cursor = conn.execute(
                    f"""
                        SELECT n.title_hash
                        FROM news n
                        JOIN news_keywords nk ON nk.link = n.link
                        WHERE nk.keyword = ? AND n.title_hash IN ({placeholders})
                    """,
                    [keyword] + hashes,
                )
                existing_hashes = {row[0] for row in cursor.fetchall()}

                # 3. 데이터 분류 (신규 vs 중복) 및 삽입 데이터 준비
                # - 중복은 '키워드 탭' 단위로 관리 (news_keywords.is_duplicate)
                # - 동일 응답 내 중복도 잡기 위해 seen_hashes를 사용
                seen_hashes = set(existing_hashes)

                news_insert_data = []
                kw_insert_data = []

                for item in prepared_items:
                    title_hash = item['title_hash']
                    is_dup = title_hash in seen_hashes
                    if is_dup:
                        duplicate_count += 1
                    else:
                        added_count += 1
                    seen_hashes.add(title_hash)

                    # news: 기사 본문/상태는 link 단위로 1개만 유지
                    news_insert_data.append(
                        (
                            item['link'],
                            keyword,
                            item['title'],
                            item['description'],
                            item['pubDate'],
                            item['publisher'],
                            item['pubDate_ts'],
                            item['title_hash'],
                        )
                    )

                    # news_keywords: 키워드-기사 매핑 + 키워드별 중복 플래그
                    kw_insert_data.append(
                        (
                            item['link'],
                            keyword,
                            1 if is_dup else 0,
                        )
                    )

                # 4. 일괄 삽입/갱신
                # - ON CONFLICT(link): 기존 상태(읽음/북마크/메모)는 보존하면서 본문만 갱신
                # - keyword 컬럼은 레거시 호환을 위해 "비어있을 때만" 채움
                conn.executemany(
                    """
                        INSERT INTO news
                        (link, keyword, title, description, pubDate, publisher, pubDate_ts, title_hash)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(link) DO UPDATE SET
                            keyword = CASE WHEN keyword IS NULL OR keyword = '' THEN excluded.keyword ELSE keyword END,
                            title = excluded.title,
                            description = excluded.description,
                            pubDate = excluded.pubDate,
                            publisher = excluded.publisher,
                            pubDate_ts = CASE WHEN excluded.pubDate_ts > 0 THEN excluded.pubDate_ts ELSE pubDate_ts END,
                            title_hash = excluded.title_hash
                    """,
                    news_insert_data,
                )

                conn.executemany(
                    """
                        INSERT INTO news_keywords (link, keyword, is_duplicate)
                        VALUES (?, ?, ?)
                        ON CONFLICT(link, keyword) DO UPDATE SET
                            is_duplicate = excluded.is_duplicate
                    """,
                    kw_insert_data,
                )

            return added_count, duplicate_count
        
        except sqlite3.Error as e:
            logger.error(f"DB Batch Upsert Error: {e}")
            return 0, 0
        finally:
            self.return_connection(conn)
    
    def fetch_news(self, keyword: str, filter_txt: str = "", sort_mode: str = "최신순", 
                   only_bookmark: bool = False, only_unread: bool = False,
                   hide_duplicates: bool = False,
                   start_date: str = None, end_date: str = None) -> List[Dict]:
        """뉴스 조회 - 안전한 버전 (날짜 필터 추가)"""
        conn = self.get_connection()
        news_items = []
        try:
            params = []

            # 동일 기사가 여러 탭에 보이도록, 키워드 필터는 news_keywords를 기준으로 JOIN
            if only_bookmark:
                # 북마크 탭: 전체 북마크를 기사 단위로 조회
                query = """
                    SELECT
                        n.link,
                        n.title,
                        n.description,
                        n.pubDate,
                        n.publisher,
                        n.is_read,
                        n.is_bookmarked,
                        n.pubDate_ts,
                        n.created_at,
                        n.notes,
                        n.title_hash,
                        CASE
                            WHEN EXISTS (
                                SELECT 1 FROM news_keywords nk
                                WHERE nk.link = n.link AND nk.is_duplicate = 1
                            ) THEN 1
                            ELSE 0
                        END AS is_duplicate
                    FROM news n
                    WHERE n.is_bookmarked = 1
                """
            else:
                # 일반 탭: 키워드-기사 매핑을 따라 조회
                query = """
                    SELECT
                        n.link,
                        n.title,
                        n.description,
                        n.pubDate,
                        n.publisher,
                        n.is_read,
                        n.is_bookmarked,
                        n.pubDate_ts,
                        n.created_at,
                        n.notes,
                        n.title_hash,
                        nk.is_duplicate AS is_duplicate
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword = ?
                """
                params.append(keyword)

            # 읽지 않은 항목 필터
            if only_unread:
                query += " AND n.is_read = 0"

            # 중복 숨김 필터
            if hide_duplicates:
                if only_bookmark:
                    query += " AND NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link AND nk.is_duplicate = 1)"
                else:
                    query += " AND nk.is_duplicate = 0"

            # 텍스트 검색 필터 (제목 또는 설명)
            if filter_txt:
                query += " AND (n.title LIKE ? OR n.description LIKE ?)"
                wildcard = f"%{filter_txt}%"
                params.extend([wildcard, wildcard])

            # 날짜 범위 필터 (SQL 레벨 - pubDate_ts 인덱스 활용)
            if start_date:
                try:
                    s_ts = datetime.strptime(start_date, "%Y-%m-%d").timestamp()
                    query += " AND n.pubDate_ts >= ?"
                    params.append(s_ts)
                except ValueError:
                    logger.warning(f"Invalid start_date format: {start_date}")

            if end_date:
                try:
                    e_ts = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).timestamp()
                    query += " AND n.pubDate_ts < ?"
                    params.append(e_ts)
                except ValueError:
                    logger.warning(f"Invalid end_date format: {end_date}")

            # 정렬
            if sort_mode == "최신순":
                query += " ORDER BY n.pubDate_ts DESC"
            else:
                query += " ORDER BY n.pubDate_ts ASC"

            cursor = conn.cursor()
            cursor.execute(query, params)
            columns = [column[0] for column in cursor.description]
            for row in cursor.fetchall():
                news_items.append(dict(zip(columns, row)))
                
        except Exception as e:
            logger.error(f"뉴스 조회 오류: {e}")
        finally:
            self.return_connection(conn)
            
        return news_items
    
    def get_counts(self, keyword: str) -> int:
        """특정 키워드 뉴스 개수"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news_keywords WHERE keyword=?", (keyword,))
            return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_counts 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def get_unread_count(self, keyword: str) -> int:
        """안 읽은 뉴스 개수"""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                """
                    SELECT COUNT(*)
                    FROM news n
                    JOIN news_keywords nk ON nk.link = n.link
                    WHERE nk.keyword = ? AND n.is_read = 0
                """,
                (keyword,),
            )
            return cursor.fetchone()[0] or 0
        except Exception as e:
            logger.error(f"get_unread_count 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    # 허용된 업데이트 필드 (SQL Injection 방지)
    ALLOWED_UPDATE_FIELDS = {'is_read', 'is_bookmarked', 'notes', 'is_duplicate'}
    
    def update_status(self, link: str, field: str, value) -> bool:
        """뉴스 상태 업데이트 - SQL Injection 방지 버전"""
        # 필드 화이트리스트 검증
        if field not in self.ALLOWED_UPDATE_FIELDS:
            logger.error(f"허용되지 않은 필드: {field}")
            return False
        
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return True
        except sqlite3.Error as e:
            logger.error(f"DB Update Error: {e}")
            return False
        finally:
            self.return_connection(conn)
    
    def save_note(self, link: str, note: str) -> bool:
        """메모 저장"""
        return self.update_status(link, "notes", note)
    
    def get_note(self, link: str) -> str:
        """메모 조회"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT notes FROM news WHERE link=?", (link,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else ""
        except Exception as e:
            logger.error(f"get_note 오류: {e}")
            return ""
        finally:
            self.return_connection(conn)
    
    def delete_old_news(self, days: int) -> int:
        """오래된 뉴스 삭제"""
        conn = self.get_connection()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        try:
            with conn:
                cur = conn.execute(
                    "DELETE FROM news WHERE is_bookmarked=0 AND pubDate_ts < ?", 
                    (cutoff,)
                )
                return cur.rowcount
        except Exception as e:
            logger.error(f"delete_old_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def delete_all_news(self) -> int:
        """모든 뉴스 삭제 (북마크 제외)"""
        conn = self.get_connection()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0")
                return cur.rowcount
        except Exception as e:
            logger.error(f"delete_all_news 오류: {e}")
            return 0
        finally:
            self.return_connection(conn)
    
    def get_statistics(self) -> Dict[str, int]:
        """통계 정보"""
        conn = self.get_connection()
        try:
            stats = {}
            stats['total'] = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            stats['unread'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_read=0").fetchone()[0]
            stats['bookmarked'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_bookmarked=1").fetchone()[0]
            stats['with_notes'] = conn.execute("SELECT COUNT(*) FROM news WHERE notes IS NOT NULL AND notes != ''").fetchone()[0]
            stats['duplicates'] = conn.execute(
                "SELECT COUNT(DISTINCT link) FROM news_keywords WHERE is_duplicate=1"
            ).fetchone()[0]
            return stats
        except Exception as e:
            logger.error(f"get_statistics 오류: {e}")
            return {'total': 0, 'unread': 0, 'bookmarked': 0, 'with_notes': 0, 'duplicates': 0}
        finally:
            self.return_connection(conn)
    
    def get_top_publishers(self, keyword: Optional[str] = None, limit: int = 10) -> List[Tuple[str, int]]:
        """주요 언론사 통계"""
        conn = self.get_connection()
        try:
            if keyword:
                cursor = conn.execute("""
                    SELECT publisher, COUNT(*) as count 
                    FROM news 
                    WHERE link IN (SELECT link FROM news_keywords WHERE keyword=?)
                    GROUP BY publisher 
                    ORDER BY count DESC 
                    LIMIT ?
                """, (keyword, limit))
            else:
                cursor = conn.execute("""
                    SELECT publisher, COUNT(*) as count 
                    FROM news 
                    GROUP BY publisher 
                    ORDER BY count DESC 
                    LIMIT ?
                """, (limit,))
            return [(row[0], row[1]) for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"get_top_publishers 오류: {e}")
            return []
        finally:
            self.return_connection(conn)
    
    def mark_all_as_read(self, keyword: str, only_bookmark: bool) -> int:
        """모든 기사 읽음 처리"""
        conn = self.get_connection()
        count = 0
        try:
            with conn:
                if only_bookmark:
                    cursor = conn.execute("UPDATE news SET is_read=1 WHERE is_bookmarked=1 AND is_read=0")
                else:
                    cursor = conn.execute(
                        """
                            UPDATE news
                            SET is_read = 1
                            WHERE is_read = 0
                              AND link IN (SELECT link FROM news_keywords WHERE keyword = ?)
                        """,
                        (keyword,),
                    )
                count = cursor.rowcount
        except Exception as e:
            logger.error(f"일괄 읽음 처리 오류: {e}")
            raise
        finally:
            self.return_connection(conn)
        return count

    def close(self):
        """모든 연결 종료 - 안전한 버전"""
        self._closed = True
        closed_count = 0
        
        # 비상 연결 정리 (경고 로그만 남김 - 이미 반환해야 했지만 남아있는 연결)
        with self._lock:
            emergency_count = len(self._emergency_connections)
            if emergency_count > 0:
                logger.warning(f"비상 연결 {emergency_count}개가 정리되지 않고 남아있음")
            self._emergency_connections.clear()
        
        try:
            while not self.connection_pool.empty():
                try:
                    conn = self.connection_pool.get_nowait()
                    conn.close()
                    closed_count += 1
                except (sqlite3.Error, Exception):
                    break
            logger.info(f"DB 연결 {closed_count}개 정상 종료")
        except Exception as e:
            logger.error(f"DB 종료 중 오류: {e}")


# --- 비동기 작업 워커 (일괄 업데이트 등) ---
class AsyncJobWorker(QThread):
    """단발성 비동기 작업 수행 워커"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, job_func, *args, **kwargs):
        super().__init__()
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        try:
            result = self.job_func(*self.args, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()

# --- 전역 HTTP 세션 풀 (성능 최적화) ---
_global_session: Optional[requests.Session] = None
_session_lock = threading.Lock()

def get_shared_session() -> requests.Session:
    """공유 HTTP 세션 반환 (커넥션 재사용으로 성능 향상)"""
    global _global_session
    with _session_lock:
        if _global_session is None:
            _global_session = requests.Session()
            adapter = HTTPAdapter(
                pool_connections=5,
                pool_maxsize=10,
                max_retries=0  # 재시도는 ApiWorker에서 처리
            )
            _global_session.mount('https://', adapter)
            _global_session.mount('http://', adapter)
        return _global_session


def close_shared_session():
    """전역 HTTP 세션 정리 (애플리케이션 종료 시 호출)"""
    global _global_session
    with _session_lock:
        if _global_session is not None:
            try:
                _global_session.close()
                logger.info("전역 HTTP 세션 종료")
            except Exception as e:
                logger.warning(f"세션 종료 오류: {e}")
            finally:
                _global_session = None

# --- 개선된 API 워커 (재시도 로직) ---
class ApiWorker(QObject):
    """API 호출 워커 (재시도 로직 및 백그라운드 DB 저장 포함) - 안정성 개선 버전"""
    
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, client_id: str, client_secret: str, keyword: str, 
                 exclude_words: List[str], db_manager: DatabaseManager, 
                 start_idx: int = 1, max_retries: int = 3, timeout: int = 15,
                 session: Optional[requests.Session] = None):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.keyword = keyword
        self.exclude_words = exclude_words
        self.db = db_manager
        self.start = start_idx
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session
        self._is_running = True
        self._lock = threading.Lock()
        self._destroyed = False

    @property
    def is_running(self):
        with self._lock:
            return self._is_running and not self._destroyed
    
    @is_running.setter
    def is_running(self, value):
        with self._lock:
            self._is_running = value

    def _safe_emit(self, signal, value):
        """안전한 시그널 발신 (객체 삭제 시 크래시 방지)"""
        try:
            if not self._destroyed and self.is_running:
                signal.emit(value)
        except RuntimeError:
            logger.warning(f"시그널 발신 실패 (객체 삭제됨): {self.keyword}")
        except Exception as e:
            logger.error(f"시그널 발신 오류: {e}")

    def run(self):
        """API 호출 및 DB 저장 실행 - 안정성 개선 버전"""
        logger.info(f"ApiWorker 시작: {self.keyword}")
        
        if not self.is_running:
            return
        
        for attempt in range(self.max_retries):
            if not self.is_running:
                logger.info(f"ApiWorker 중단됨: {self.keyword}")
                return
            
            try:
                self._safe_emit(self.progress, f"'{self.keyword}' 검색 중... (시도 {attempt + 1}/{self.max_retries})")
                
                headers = {
                    "X-Naver-Client-Id": self.cid.strip(), 
                    "X-Naver-Client-Secret": self.csec.strip()
                }
                url = "https://openapi.naver.com/v1/search/news.json"
                params = {
                    "query": self.keyword, 
                    "display": 100, 
                    "start": self.start, 
                    "sort": "date"
                }
                
                
                # 공유 세션 사용 (커넥션 재사용으로 성능 향상)
                session = self.session or get_shared_session()
                resp = session.get(url, headers=headers, params=params, timeout=self.timeout)
                
                if resp.status_code == 429:
                    if attempt < self.max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        self._safe_emit(self.progress, f"요청 제한 초과. {wait_time}초 후 재시도...")
                        for _ in range(wait_time):
                            if not self.is_running:
                                return
                            time.sleep(1)
                        continue
                    else:
                        self._safe_emit(self.error, "API 요청 제한 초과. 잠시 후 다시 시도해주세요.")
                        return

                if resp.status_code == 401:
                    self._safe_emit(self.error, "API 인증 실패(401). 설정(Ctrl+,)에서 Client ID/Secret을 확인해주세요.")
                    return
                
                if resp.status_code != 200:
                    try:
                        error_data = resp.json()
                        error_msg = error_data.get('errorMessage', '알 수 없는 오류')
                        error_code = error_data.get('errorCode', '')
                    except (json.JSONDecodeError, KeyError, ValueError):
                        error_msg = f"HTTP {resp.status_code}"
                        error_code = ""
                    self._safe_emit(self.error, f"API 오류 {resp.status_code} ({error_code}): {error_msg}")
                    return
                
                data = resp.json()
                items = []
                filtered_count = 0
                
                for item in data.get('items', []):
                    if not self.is_running:
                        break
                    
                    try:
                        # 프리컴파일된 정규식 사용 (성능 최적화)
                        title = html.unescape(RE_BOLD_TAGS.sub('', item.get('title', '')))
                        desc = html.unescape(RE_BOLD_TAGS.sub('', item.get('description', '')))
                        
                        if self.exclude_words:
                            should_exclude = False
                            for ex in self.exclude_words:
                                if ex and (ex in title or ex in desc):
                                    should_exclude = True
                                    filtered_count += 1
                                    break
                            if should_exclude:
                                continue
                        
                        naver_link = item.get('link', '')
                        org_link = item.get('originallink', '')
                        
                        final_link = ""
                        if "news.naver.com" in naver_link:
                            final_link = naver_link
                        elif "news.naver.com" in org_link:
                            final_link = org_link
                        else:
                            final_link = naver_link if naver_link else org_link

                        publisher = "정보 없음"
                        if org_link:
                            publisher = urllib.parse.urlparse(org_link).netloc.replace('www.', '')
                        elif final_link:
                            if "news.naver.com" in final_link:
                                publisher = "네이버뉴스"
                            else:
                                publisher = urllib.parse.urlparse(final_link).netloc.replace('www.', '')
                        
                        items.append({
                            'title': title,
                            'description': desc,
                            'link': final_link,
                            'pubDate': item.get('pubDate', ''),
                            'publisher': publisher
                        })
                    except Exception as item_error:
                        logger.warning(f"아이템 처리 오류: {item_error}")
                        continue
                
                # 백그라운드 DB 저장 (UI 프리징 방지)
                self._safe_emit(self.progress, f"'{self.keyword}' 저장 중...")
                search_keyword_only = self.keyword.split()[0] if self.keyword.split() else self.keyword
                added_count, dup_count = self.db.upsert_news(items, search_keyword_only)
                
                result = {
                    'items': items,
                    'total': data.get('total', 0),
                    'filtered': filtered_count,
                    'added_count': added_count,
                    'dup_count': dup_count
                }
                
                logger.info(f"ApiWorker 완료: {self.keyword} ({len(items)}개, 추가 {added_count}, 중복 {dup_count})")
                self._safe_emit(self.progress, f"'{self.keyword}' 완료 (추가: {added_count}개)")
                self._safe_emit(self.finished, result)
                return

            except requests.Timeout:
                logger.warning(f"API 타임아웃: {self.keyword} (시도 {attempt + 1})")
                if attempt < self.max_retries - 1:
                    self._safe_emit(self.progress, f"요청 시간 초과. 재시도 중...")
                    time.sleep(1)
                    continue
                else:
                    self._safe_emit(self.error, "요청 시간이 초과되었습니다. 네트워크 연결을 확인해주세요.")
                    return
            
            except requests.RequestException as e:
                logger.warning(f"네트워크 오류: {self.keyword} - {e}")
                if attempt < self.max_retries - 1:
                    self._safe_emit(self.progress, f"네트워크 오류. 재시도 중...")
                    time.sleep(1)
                    continue
                else:
                    self._safe_emit(self.error, f"네트워크 오류: {str(e)}")
                    return
            
            except Exception as e:
                logger.error(f"ApiWorker 예외: {self.keyword} - {e}")
                traceback.print_exc()
                self._safe_emit(self.error, f"오류 발생: {str(e)}")
                return

    def stop(self):
        """워커 중지"""
        logger.info(f"ApiWorker 중지 요청: {self.keyword}")
        self._destroyed = True
        self.is_running = False


# --- DB 로딩 워커 (비동기 로딩) ---
class DBWorker(QThread):
    """DB 데이터 로딩을 위한 워커 스레드 (UI 프리징 방지)"""
    finished = pyqtSignal(list, int)  # result_data, total_count
    error = pyqtSignal(str)
    
    def __init__(self, db_manager: DatabaseManager, keyword: str, 
                 filter_txt: str = "", sort_mode: str = "최신순",
                 only_bookmark: bool = False, only_unread: bool = False,
                 hide_duplicates: bool = False,
                 start_date: str = None, end_date: str = None):
        super().__init__()
        self.db = db_manager
        self.keyword = keyword
        self.filter_txt = filter_txt
        self.sort_mode = sort_mode
        self.only_bookmark = only_bookmark
        self.only_unread = only_unread
        self.hide_duplicates = hide_duplicates
        self.start_date = start_date
        self.end_date = end_date
        self._is_cancelled = False

    def stop(self):
        """워커 중지 (플래그 설정)"""
        self._is_cancelled = True
        self.quit()
        self.wait(100)
        
    def run(self):
        try:
            if self._is_cancelled: return
            # 키워드 파싱 (제외어 처리)
            parts = self.keyword.split()
            if not parts:
                self.finished.emit([], 0)
                return
                
            search_keyword = parts[0] # 첫 단어를 DB 검색용 키워드로 사용
            exclude_words = [w[1:] for w in parts if w.startswith('-')]
            
            # DB 조회 수행 (검색 키워드로 조회)
            data = self.db.fetch_news(
                keyword=search_keyword,
                filter_txt=self.filter_txt,
                sort_mode=self.sort_mode,
                only_bookmark=self.only_bookmark,
                only_unread=self.only_unread,
                hide_duplicates=self.hide_duplicates,
                start_date=self.start_date,
                end_date=self.end_date
            )
            
            # 제외어 필터링 (메모리에서 수행)
            if exclude_words:
                filtered_data = []
                for item in data:
                    title = item.get('title', '')
                    desc = item.get('description', '')
                    
                    should_exclude = False
                    for ex in exclude_words:
                        if ex and (ex in title or ex in desc):
                            should_exclude = True
                            break
                    
                    if not should_exclude:
                        filtered_data.append(item)
                data = filtered_data
            
            # 총 개수는 별도로 계산하지 않고 리스트 길이로 대체하거나 필요시 추가 쿼리
            total_count = len(data)
            
            self.finished.emit(data, total_count)
            
        except Exception as e:
            self.error.emit(str(e))
            traceback.print_exc()

# --- 메모 다이얼로그 ---
class NoteDialog(QDialog):
    """메모 편집 다이얼로그"""
    
    def __init__(self, current_note: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("메모 편집")
        self.resize(500, 300)
        
        layout = QVBoxLayout(self)
        
        label = QLabel("이 기사에 대한 메모를 작성하세요:")
        layout.addWidget(label)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(current_note)
        self.text_edit.setPlaceholderText("메모를 입력하세요...")
        layout.addWidget(self.text_edit)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def get_note(self) -> str:
        """메모 내용 반환"""
        return self.text_edit.toPlainText().strip()


# --- 로그 뷰어 다이얼로그 ---
class LogViewerDialog(QDialog):
    """애플리케이션 로그 뷰어"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📋 로그 뷰어")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        # 상단 버튼
        btn_layout = QHBoxLayout()
        
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.clicked.connect(self.load_logs)
        
        self.btn_clear = QPushButton("🗑 로그 지우기")
        self.btn_clear.clicked.connect(self.clear_logs)
        
        self.btn_open_file = QPushButton("📁 로그 파일 열기")
        self.btn_open_file.clicked.connect(self.open_log_file)
        
        self.chk_auto_scroll = QCheckBox("자동 스크롤")
        self.chk_auto_scroll.setChecked(True)
        
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_clear)
        btn_layout.addWidget(self.btn_open_file)
        btn_layout.addStretch()
        btn_layout.addWidget(self.chk_auto_scroll)
        layout.addLayout(btn_layout)
        
        # 필터
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("레벨 필터:"))
        
        self.combo_level = QComboBox()
        self.combo_level.addItems(["모두", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.combo_level.currentIndexChanged.connect(self.load_logs)
        filter_layout.addWidget(self.combo_level)
        
        filter_layout.addWidget(QLabel("검색:"))
        self.inp_search = QLineEdit()
        self.inp_search.setPlaceholderText("로그 내용 검색...")
        self.inp_search.textChanged.connect(self.load_logs)
        filter_layout.addWidget(self.inp_search, 1)
        
        layout.addLayout(filter_layout)
        
        # 로그 표시 영역
        self.log_browser = QTextBrowser()
        self.log_browser.setOpenExternalLinks(False)
        self.log_browser.setStyleSheet("""
            QTextBrowser {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
                background-color: #1E1E1E;
                color: #D4D4D4;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.log_browser)
        
        # 상태 레이블
        self.lbl_status = QLabel("대기 중...")
        layout.addWidget(self.lbl_status)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        
        # 로그 로드
        self.load_logs()
    
    def load_logs(self):
        """로그 파일 로드 - 최근 로그만 최적화하여 로드"""
        try:
            if not os.path.exists(LOG_FILE):
                self.log_browser.setPlainText("로그 파일이 없습니다.")
                self.lbl_status.setText("로그 파일 없음")
                return
            
            # 대용량 로그 파일 처리 최적화 - 마지막 50KB만 읽기
            file_size = os.path.getsize(LOG_FILE)
            read_size = 50 * 1024  # 50KB
            
            lines = []
            with open(LOG_FILE, 'r', encoding='utf-8', errors='replace') as f:
                if file_size > read_size:
                    f.seek(file_size - read_size)
                    # 첫 줄은 잘릴 수 있으므로 버림
                    f.readline()
                lines = f.readlines()
            
            # 필터 적용
            level_filter = self.combo_level.currentText()
            search_text = self.inp_search.text().strip().lower()
            
            filtered_lines = []
            for line in lines:
                # 레벨 필터
                if level_filter != "모두":
                    if f"[{level_filter}]" not in line:
                        continue
                
                # 검색 필터
                if search_text and search_text not in line.lower():
                    continue
                
                filtered_lines.append(line)
            
            # 색상 코딩된 HTML 생성
            html_lines = []
            for line in filtered_lines:
                if "[ERROR]" in line or "[CRITICAL]" in line:
                    color = "#FF6B6B"
                elif "[WARNING]" in line:
                    color = "#FFD93D"
                elif "[INFO]" in line:
                    color = "#6BCB77"
                else:
                    color = "#D4D4D4"
                
                escaped = html.escape(line.rstrip())
                html_lines.append(f"<span style='color: {color};'>{escaped}</span>")
            
            html_content = "<pre style='margin: 0;'>" + "<br>".join(html_lines) + "</pre>"
            if file_size > read_size:
                html_content = f"<div style='color: #888; margin-bottom: 10px;'>... 이전 로그 생략됨 (전체 크기: {file_size/1024:.1f}KB) ...</div>" + html_content
                
            self.log_browser.setHtml(html_content)
            
            # 자동 스크롤
            if self.chk_auto_scroll.isChecked():
                self.log_browser.verticalScrollBar().setValue(
                    self.log_browser.verticalScrollBar().maximum()
                )
            
            self.lbl_status.setText(f"총 {len(lines)}줄 중 {len(filtered_lines)}줄 표시")
            
        except Exception as e:
            self.log_browser.setPlainText(f"로그 로드 오류: {str(e)}")
            self.lbl_status.setText(f"오류: {str(e)}")
    
    def clear_logs(self):
        """로그 파일 지우기"""
        reply = QMessageBox.question(
            self,
            "로그 지우기",
            "로그 파일을 지우시겠습니까?\n이 작업은 취소할 수 없습니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                with open(LOG_FILE, 'w', encoding='utf-8') as f:
                    f.write("")
                self.load_logs()
                logger.info("로그 파일 초기화됨")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"로그 지우기 실패: {str(e)}")
    
    def open_log_file(self):
        """로그 파일을 기본 편집기로 열기"""
        if os.path.exists(LOG_FILE):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(LOG_FILE)))
        else:
            QMessageBox.information(self, "알림", "로그 파일이 아직 생성되지 않았습니다.")


# --- 알림 소리 유틸리티 ---
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


# --- 키워드 그룹 관리자 ---
class KeywordGroupManager:
    """키워드 그룹(폴더) 관리"""
    
    def __init__(self, config_file: str = CONFIG_FILE):
        self.config_file = config_file
        self.groups: Dict[str, List[str]] = {}  # {그룹명: [키워드 목록]}
        self.load_groups()
    
    def load_groups(self):
        """그룹 설정 로드"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                self.groups = config.get('keyword_groups', {})
        except Exception as e:
            logger.error(f"키워드 그룹 로드 오류: {e}")
            self.groups = {}
    
    def save_groups(self):
        """그룹 설정 저장"""
        try:
            config = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            
            config['keyword_groups'] = self.groups
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"키워드 그룹 저장 오류: {e}")
    
    def create_group(self, name: str) -> bool:
        """새 그룹 생성"""
        if name in self.groups:
            return False
        self.groups[name] = []
        self.save_groups()
        return True
    
    def delete_group(self, name: str) -> bool:
        """그룹 삭제"""
        if name not in self.groups:
            return False
        del self.groups[name]
        self.save_groups()
        return True
    
    def add_keyword_to_group(self, group: str, keyword: str) -> bool:
        """그룹에 키워드 추가"""
        if group not in self.groups:
            return False
        if keyword not in self.groups[group]:
            self.groups[group].append(keyword)
            self.save_groups()
        return True
    
    def remove_keyword_from_group(self, group: str, keyword: str) -> bool:
        """그룹에서 키워드 제거"""
        if group not in self.groups:
            return False
        if keyword in self.groups[group]:
            self.groups[group].remove(keyword)
            self.save_groups()
        return True
    
    def get_group_keywords(self, group: str) -> List[str]:
        """그룹의 키워드 목록 반환"""
        return self.groups.get(group, [])
    
    def get_all_groups(self) -> List[str]:
        """모든 그룹명 반환"""
        return list(self.groups.keys())
    
    def get_keyword_group(self, keyword: str) -> Optional[str]:
        """키워드가 속한 그룹 반환"""
        for group, keywords in self.groups.items():
            if keyword in keywords:
                return group
        return None


# --- 키워드 그룹 다이얼로그 ---
class KeywordGroupDialog(QDialog):
    """키워드 그룹 관리 다이얼로그"""
    
    def __init__(self, group_manager: KeywordGroupManager, current_tabs: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("📁 키워드 그룹 관리")
        self.resize(600, 500)
        self.group_manager = group_manager
        self.current_tabs = current_tabs
        
        self.setup_ui()
        self.load_groups()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 설명
        info = QLabel("키워드를 그룹(폴더)으로 정리하여 관리할 수 있습니다.")
        info.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(info)
        
        # 그룹 관리 영역
        main_layout = QHBoxLayout()
        
        # 왼쪽: 그룹 목록
        left_group = QGroupBox("📁 그룹")
        left_layout = QVBoxLayout(left_group)
        
        self.group_list = QListWidget()
        self.group_list.currentRowChanged.connect(self.on_group_selected)
        left_layout.addWidget(self.group_list)
        
        group_btn_layout = QHBoxLayout()
        self.btn_add_group = QPushButton("➕ 추가")
        self.btn_add_group.clicked.connect(self.add_group)
        self.btn_del_group = QPushButton("🗑 삭제")
        self.btn_del_group.clicked.connect(self.delete_group)
        group_btn_layout.addWidget(self.btn_add_group)
        group_btn_layout.addWidget(self.btn_del_group)
        left_layout.addLayout(group_btn_layout)
        
        main_layout.addWidget(left_group, 1)
        
        # 중앙: 버튼
        center_layout = QVBoxLayout()
        center_layout.addStretch()
        self.btn_add_to_group = QPushButton("→")
        self.btn_add_to_group.setFixedWidth(40)
        self.btn_add_to_group.clicked.connect(self.add_keyword_to_group)
        self.btn_remove_from_group = QPushButton("←")
        self.btn_remove_from_group.setFixedWidth(40)
        self.btn_remove_from_group.clicked.connect(self.remove_keyword_from_group)
        center_layout.addWidget(self.btn_add_to_group)
        center_layout.addWidget(self.btn_remove_from_group)
        center_layout.addStretch()
        main_layout.addLayout(center_layout)
        
        # 오른쪽: 키워드 목록
        right_group = QGroupBox("🔑 키워드")
        right_layout = QVBoxLayout(right_group)
        
        # 그룹의 키워드
        right_layout.addWidget(QLabel("그룹 내 키워드:"))
        self.group_keywords_list = QListWidget()
        right_layout.addWidget(self.group_keywords_list)
        
        # 미분류 키워드
        right_layout.addWidget(QLabel("미분류 키워드:"))
        self.unassigned_list = QListWidget()
        right_layout.addWidget(self.unassigned_list)
        
        main_layout.addWidget(right_group, 1)
        
        layout.addLayout(main_layout)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
    
    def load_groups(self):
        """그룹 및 키워드 목록 로드"""
        self.group_list.clear()
        for group in self.group_manager.get_all_groups():
            count = len(self.group_manager.get_group_keywords(group))
            self.group_list.addItem(f"📁 {group} ({count})")
        
        self.update_keyword_lists()
    
    def update_keyword_lists(self):
        """키워드 목록 업데이트"""
        self.group_keywords_list.clear()
        self.unassigned_list.clear()
        
        # 현재 선택된 그룹의 키워드
        current_row = self.group_list.currentRow()
        if current_row >= 0:
            groups = self.group_manager.get_all_groups()
            if current_row < len(groups):
                group_name = groups[current_row]
                for kw in self.group_manager.get_group_keywords(group_name):
                    self.group_keywords_list.addItem(kw)
        
        # 미분류 키워드 (어떤 그룹에도 속하지 않은 탭)
        assigned = set()
        for group in self.group_manager.get_all_groups():
            assigned.update(self.group_manager.get_group_keywords(group))
        
        for tab in self.current_tabs:
            if tab not in assigned and tab != "북마크":
                self.unassigned_list.addItem(tab)
    
    def on_group_selected(self, row: int):
        """그룹 선택 시"""
        self.update_keyword_lists()
    
    def add_group(self):
        """새 그룹 추가"""
        name, ok = QInputDialog.getText(self, "새 그룹", "그룹 이름:")
        if ok and name.strip():
            if self.group_manager.create_group(name.strip()):
                self.load_groups()
            else:
                QMessageBox.warning(self, "오류", "이미 존재하는 그룹 이름입니다.")
    
    def delete_group(self):
        """그룹 삭제"""
        current_row = self.group_list.currentRow()
        if current_row < 0:
            return
        
        groups = self.group_manager.get_all_groups()
        if current_row < len(groups):
            group_name = groups[current_row]
            reply = QMessageBox.question(
                self, "그룹 삭제",
                f"'{group_name}' 그룹을 삭제하시겠습니까?\n(그룹 내 키워드는 미분류로 이동됩니다)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.group_manager.delete_group(group_name)
                self.load_groups()
    
    def add_keyword_to_group(self):
        """선택한 키워드를 그룹에 추가"""
        group_row = self.group_list.currentRow()
        keyword_item = self.unassigned_list.currentItem()
        
        if group_row < 0 or not keyword_item:
            return
        
        groups = self.group_manager.get_all_groups()
        if group_row < len(groups):
            group_name = groups[group_row]
            keyword = keyword_item.text()
            self.group_manager.add_keyword_to_group(group_name, keyword)
            self.load_groups()
    
    def remove_keyword_from_group(self):
        """그룹에서 키워드 제거"""
        group_row = self.group_list.currentRow()
        keyword_item = self.group_keywords_list.currentItem()
        
        if group_row < 0 or not keyword_item:
            return
        
        groups = self.group_manager.get_all_groups()
        if group_row < len(groups):
            group_name = groups[group_row]
            keyword = keyword_item.text()
            self.group_manager.remove_keyword_from_group(group_name, keyword)
            self.load_groups()


# --- 자동 백업 관리자 ---
class AutoBackup:
    """설정 및 데이터베이스 자동 백업"""
    
    BACKUP_DIR = "backups"
    MAX_BACKUPS = 5  # 최대 보관 백업 수
    
    def __init__(self, config_file: str = CONFIG_FILE, db_file: str = DB_FILE):
        self.config_file = config_file
        self.db_file = db_file
        self.backup_dir = os.path.join(os.path.dirname(os.path.abspath(config_file)), self.BACKUP_DIR)
        self._ensure_backup_dir()
    
    def _ensure_backup_dir(self):
        """백업 디렉토리 생성"""
        if not os.path.exists(self.backup_dir):
            try:
                os.makedirs(self.backup_dir)
                logger.info(f"백업 디렉토리 생성: {self.backup_dir}")
            except Exception as e:
                logger.error(f"백업 디렉토리 생성 실패: {e}")
    
    def create_backup(self, include_db: bool = True) -> Optional[str]:
        """백업 생성"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"backup_{timestamp}"
            backup_path = os.path.join(self.backup_dir, backup_name)
            os.makedirs(backup_path, exist_ok=True)
            
            # 설정 파일 백업
            if os.path.exists(self.config_file):
                import shutil
                shutil.copy2(
                    self.config_file, 
                    os.path.join(backup_path, os.path.basename(self.config_file))
                )
            
            # 데이터베이스 백업 (선택적)
            if include_db and os.path.exists(self.db_file):
                import shutil
                shutil.copy2(
                    self.db_file,
                    os.path.join(backup_path, os.path.basename(self.db_file))
                )
            
            # 백업 정보 파일 생성
            info = {
                'timestamp': timestamp,
                'app_version': VERSION,
                'include_db': include_db,
                'created_at': datetime.now().isoformat()
            }
            with open(os.path.join(backup_path, 'backup_info.json'), 'w', encoding='utf-8') as f:
                json.dump(info, f, indent=2, ensure_ascii=False)
            
            logger.info(f"백업 생성 완료: {backup_path}")
            
            # 오래된 백업 정리
            self._cleanup_old_backups()
            
            return backup_path
            
        except Exception as e:
            logger.error(f"백업 생성 실패: {e}")
            traceback.print_exc()
            return None
    
    def _cleanup_old_backups(self):
        """오래된 백업 정리 (MAX_BACKUPS 초과 시)"""
        try:
            backups = self.get_backup_list()
            if len(backups) > self.MAX_BACKUPS:
                # 오래된 순으로 정렬 후 삭제
                backups_to_delete = backups[self.MAX_BACKUPS:]
                for backup in backups_to_delete:
                    backup_path = os.path.join(self.backup_dir, backup['name'])
                    import shutil
                    shutil.rmtree(backup_path, ignore_errors=True)
                    logger.info(f"오래된 백업 삭제: {backup['name']}")
        except Exception as e:
            logger.error(f"백업 정리 오류: {e}")
    
    def get_backup_list(self) -> List[Dict]:
        """백업 목록 조회 (최신순)"""
        backups = []
        try:
            if not os.path.exists(self.backup_dir):
                return backups
            
            for name in os.listdir(self.backup_dir):
                backup_path = os.path.join(self.backup_dir, name)
                if os.path.isdir(backup_path):
                    info_file = os.path.join(backup_path, 'backup_info.json')
                    if os.path.exists(info_file):
                        with open(info_file, 'r', encoding='utf-8') as f:
                            info = json.load(f)
                        info['name'] = name
                        info['path'] = backup_path
                        backups.append(info)
            
            # 최신순 정렬
            backups.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
        except Exception as e:
            logger.error(f"백업 목록 조회 오류: {e}")
        
        return backups
    
    def restore_backup(self, backup_name: str, restore_db: bool = True) -> bool:
        """백업 복원"""
        try:
            backup_path = os.path.join(self.backup_dir, backup_name)
            if not os.path.exists(backup_path):
                logger.error(f"백업을 찾을 수 없음: {backup_name}")
                return False
            
            import shutil
            
            # 설정 파일 복원
            config_backup = os.path.join(backup_path, os.path.basename(self.config_file))
            if os.path.exists(config_backup):
                shutil.copy2(config_backup, self.config_file)
            
            # 데이터베이스 복원 (선택적)
            if restore_db:
                db_backup = os.path.join(backup_path, os.path.basename(self.db_file))
                if os.path.exists(db_backup):
                    shutil.copy2(db_backup, self.db_file)
            
            logger.info(f"백업 복원 완료: {backup_name}")
            return True
            
        except Exception as e:
            logger.error(f"백업 복원 실패: {e}")
            traceback.print_exc()
            return False


# --- 백업 관리 다이얼로그 ---
class BackupDialog(QDialog):
    """백업 관리 UI"""
    
    def __init__(self, auto_backup: AutoBackup, parent=None):
        super().__init__(parent)
        self.setWindowTitle("💾 백업 관리")
        self.resize(500, 400)
        self.auto_backup = auto_backup
        self.setup_ui()
        self.load_backups()
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # 백업 생성 버튼
        btn_layout = QHBoxLayout()
        
        self.btn_create = QPushButton("📦 새 백업 생성")
        self.btn_create.clicked.connect(self.create_backup)
        
        self.chk_include_db = QCheckBox("데이터베이스 포함")
        self.chk_include_db.setChecked(True)
        
        btn_layout.addWidget(self.btn_create)
        btn_layout.addWidget(self.chk_include_db)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        # 백업 목록
        layout.addWidget(QLabel("📁 백업 목록:"))
        self.backup_list = QListWidget()
        self.backup_list.itemDoubleClicked.connect(self.restore_backup)
        layout.addWidget(self.backup_list)
        
        # 하단 버튼
        bottom_layout = QHBoxLayout()
        
        self.btn_restore = QPushButton("♻ 복원")
        self.btn_restore.clicked.connect(self.restore_backup)
        
        self.btn_delete = QPushButton("🗑 삭제")
        self.btn_delete.clicked.connect(self.delete_backup)
        
        self.btn_open_folder = QPushButton("📂 폴더 열기")
        self.btn_open_folder.clicked.connect(self.open_backup_folder)
        
        bottom_layout.addWidget(self.btn_restore)
        bottom_layout.addWidget(self.btn_delete)
        bottom_layout.addWidget(self.btn_open_folder)
        bottom_layout.addStretch()
        layout.addLayout(bottom_layout)
        
        # 닫기 버튼
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
    
    def load_backups(self):
        """백업 목록 로드"""
        self.backup_list.clear()
        backups = self.auto_backup.get_backup_list()
        
        for backup in backups:
            timestamp = backup.get('timestamp', 'Unknown')
            version = backup.get('app_version', '?')
            include_db = "📊 DB포함" if backup.get('include_db') else "⚙ 설정만"
            
            # 날짜 포맷팅
            try:
                dt = datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
                date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                date_str = timestamp
            
            item_text = f"📁 {date_str} (v{version}) {include_db}"
            item = self.backup_list.addItem(item_text)
            self.backup_list.item(self.backup_list.count() - 1).setData(
                Qt.ItemDataRole.UserRole, backup['name']
            )
    
    def create_backup(self):
        """백업 생성"""
        include_db = self.chk_include_db.isChecked()
        result = self.auto_backup.create_backup(include_db)
        
        if result:
            QMessageBox.information(self, "완료", f"백업이 생성되었습니다:\n{result}")
            self.load_backups()
        else:
            QMessageBox.warning(self, "오류", "백업 생성에 실패했습니다.")
    
    def restore_backup(self):
        """백업 복원"""
        current_item = self.backup_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "알림", "복원할 백업을 선택하세요.")
            return
        
        backup_name = current_item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(
            self, "백업 복원",
            f"'{backup_name}' 백업을 복원하시겠습니까?\n\n"
            "⚠️ 현재 설정이 덮어씌워집니다.\n"
            "복원 후 프로그램을 재시작해야 합니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if self.auto_backup.restore_backup(backup_name):
                QMessageBox.information(
                    self, "완료", 
                    "백업이 복원되었습니다.\n프로그램을 재시작하세요."
                )
            else:
                QMessageBox.warning(self, "오류", "백업 복원에 실패했습니다.")
    
    def delete_backup(self):
        """백업 삭제"""
        current_item = self.backup_list.currentItem()
        if not current_item:
            return
        
        backup_name = current_item.data(Qt.ItemDataRole.UserRole)
        
        reply = QMessageBox.question(
            self, "백업 삭제",
            f"'{backup_name}' 백업을 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            backup_path = os.path.join(self.auto_backup.backup_dir, backup_name)
            try:
                import shutil
                shutil.rmtree(backup_path, ignore_errors=True)
                self.load_backups()
            except Exception as e:
                QMessageBox.warning(self, "오류", f"삭제 실패: {str(e)}")
    
    def open_backup_folder(self):
        """백업 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.auto_backup.backup_dir))


# --- 개별 뉴스 탭 위젯 (필터링 최적화) ---
class NewsTab(QWidget):
    """개별 뉴스 탭 (메모리 캐싱 및 필터링 최적화) - Phase 3 성능 최적화"""
    
    # 렌더링 최적화 상수
    INITIAL_RENDER_COUNT = 50   # 초기 렌더링 개수
    LOAD_MORE_COUNT = 30        # 추가 로딩 개수
    MAX_RENDER_COUNT = 500      # 최대 렌더링 개수
    FILTER_DEBOUNCE_MS = 250    # 필터 디바운싱 시간 (ms) - 성능 최적화
    
    def __init__(self, keyword: str, db_manager: DatabaseManager, theme_mode: int = 0, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.db = db_manager
        self.theme = theme_mode
        self.is_bookmark_tab = (keyword == "북마크")
        
        self.news_data_cache = []
        self.filtered_data_cache = []
        self.total_api_count = 0
        self.last_update = None
        
        # 렌더링 최적화 변수 (Phase 3)
        self._rendered_count = 0           # 현재 렌더링된 항목 수
        self._is_loading_more = False      # 추가 로딩 중 여부
        
        # Async DB Worker
        self.worker = None
        
        self.setup_ui()
        self.load_data_from_db()

    @property
    def db_keyword(self):
        """DB 저장용 키워드 (첫 번째 단어만 사용)"""
        return self.keyword.split()[0] if self.keyword else ""

    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # --- 상단 필터 카드 ---
        filter_card = QFrame()
        filter_card.setObjectName("FilterCard")
        
        filter_layout = QVBoxLayout(filter_card)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        filter_layout.setSpacing(8)
        
        # 1열: 검색/정렬
        row1_layout = QHBoxLayout()
        row1_layout.setSpacing(10)
        
        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)
        
        # 필터 디바운싱 타이머 (300ms)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self._apply_filter_debounced)
        self.inp_filter.textChanged.connect(self._on_filter_changed)
        
        self.combo_sort = NoScrollComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self.load_data_from_db)
        
        row1_layout.addWidget(self.inp_filter, 4)
        row1_layout.addWidget(self.combo_sort, 1)
        
        filter_layout.addLayout(row1_layout)
        
        # 2열: 옵션 체크박스 + 날짜 필터
        row2_layout = QHBoxLayout()
        row2_layout.setSpacing(12)
        
        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self.load_data_from_db)
        
        self.chk_hide_dup = QCheckBox("중복 숨김")
        self.chk_hide_dup.stateChanged.connect(self.load_data_from_db)
        
        row2_layout.addWidget(self.chk_unread)
        row2_layout.addWidget(self.chk_hide_dup)
        
        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        row2_layout.addWidget(sep)
        
        self.btn_date_toggle = QToolButton()
        self.btn_date_toggle.setObjectName("DateToggle")
        self.btn_date_toggle.setText("📅 기간")
        self.btn_date_toggle.setCheckable(True)
        self.btn_date_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_date_toggle.toggled.connect(self._toggle_date_filter)
        
        self.date_container = QWidget()
        date_inner_layout = QHBoxLayout(self.date_container)
        date_inner_layout.setContentsMargins(0, 0, 0, 0)
        date_inner_layout.setSpacing(4)
        
        self.date_start = QDateEdit()
        self.date_start.setCalendarPopup(True)
        self.date_start.setDisplayFormat("yyyy-MM-dd")
        self.date_start.setDate(QDate.currentDate().addDays(-7))
        self.date_start.dateChanged.connect(self.load_data_from_db)
        
        self.lbl_tilde = QLabel("~")
        
        self.date_end = QDateEdit()
        self.date_end.setCalendarPopup(True)
        self.date_end.setDisplayFormat("yyyy-MM-dd")
        self.date_end.setDate(QDate.currentDate())
        self.date_end.dateChanged.connect(self.load_data_from_db)
        
        date_inner_layout.addWidget(self.date_start)
        date_inner_layout.addWidget(self.lbl_tilde)
        date_inner_layout.addWidget(self.date_end)
        
        row2_layout.addWidget(self.btn_date_toggle)
        row2_layout.addWidget(self.date_container)
        row2_layout.addStretch()
        
        filter_layout.addLayout(row2_layout)
        
        # 초기에는 날짜 필터 숨김
        self.date_container.setVisible(False)
        
        layout.addWidget(filter_card)
        
        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_link_clicked)
        self.browser.action_triggered.connect(self.on_browser_action)
        layout.addWidget(self.browser)
        
        btm_layout = QHBoxLayout()
        
        self.btn_load = QPushButton("📥 더 불러오기")
        self.btn_read_all = QPushButton("✓ 모두 읽음")
        self.btn_top = QPushButton("⬆ 맨 위로")
        self.lbl_status = QLabel("대기 중")
        
        if self.is_bookmark_tab:
            self.btn_load.hide()
        
        btm_layout.addWidget(self.btn_load)
        btm_layout.addWidget(self.btn_read_all)
        btm_layout.addWidget(self.btn_top)
        btm_layout.addStretch()
        btm_layout.addWidget(self.lbl_status)
        layout.addLayout(btm_layout)

        self.btn_top.clicked.connect(lambda: self.browser.verticalScrollBar().setValue(0))
        self.btn_read_all.clicked.connect(self.mark_all_read)
    
    def _toggle_date_filter(self, checked: bool):
        """날짜 필터 표시/숨김 토글"""
        self.date_container.setVisible(checked)
        
        if not checked:
            self.load_data_from_db() # 끄면 전체 조회

    def _on_filter_changed(self):
        """필터 입력 변경 시 디바운싱 타이머 시작"""
        self.filter_timer.stop()
        self.filter_timer.start(self.FILTER_DEBOUNCE_MS)
    
    def _apply_filter_debounced(self):
        """디바운싱된 필터 적용"""
        self.apply_filter()

    def load_data_from_db(self):
        """DB에서 데이터 로드 (비동기 처리)"""
        # 실행 중인 워커가 있다면 중지
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            
        self.lbl_status.setText("⏳ 데이터 로딩 중...")
        self.btn_load.setEnabled(False)
        
        # 날짜 필터 파라미터 준비
        s_date = None
        e_date = None
        if self.btn_date_toggle.isChecked():
            s_date = self.date_start.date().toString("yyyy-MM-dd")
            e_date = self.date_end.date().toString("yyyy-MM-dd")
        
        # DB 워커 시작
        self.worker = DBWorker(
            self.db, 
            keyword=self.keyword,
            filter_txt="", # 텍스트 필터는 메모리에서 처리 (fetch_all 후 apply_filter)
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab,
            only_unread=self.chk_unread.isChecked(),
            hide_duplicates=self.chk_hide_dup.isChecked(),
            start_date=s_date,
            end_date=e_date
        )
        self.worker.finished.connect(self.on_data_loaded)
        self.worker.error.connect(self.on_data_error)
        self.worker.start()

    def on_data_loaded(self, data, total_count):
        """데이터 로드 완료 시 호출"""
        self.news_data_cache = data
        self.total_api_count = total_count
        self.btn_load.setEnabled(True)
        self.apply_filter() # 렌더링 수행
        
    def on_data_error(self, err_msg):
        """데이터 로드 오류 시 호출"""
        self.lbl_status.setText(f"⚠️ 오류: {err_msg}")
        self.btn_load.setEnabled(True)
    
    def apply_filter(self):
        """메모리 내 필터링 (DB 쿼리 없이)"""
        filter_txt = self.inp_filter.text().strip()
        
        if filter_txt:
            self.inp_filter.setObjectName("FilterActive")
        else:
            self.inp_filter.setObjectName("")
        self.inp_filter.setStyle(self.inp_filter.style())
        
        if filter_txt:
            self.filtered_data_cache = [
                item for item in self.news_data_cache
                if filter_txt.lower() in item['title'].lower() or 
                   filter_txt.lower() in item['description'].lower()
            ]
        else:
            self.filtered_data_cache = self.news_data_cache
        
        # Phase 3: 필터 변경 시 렌더링 카운트 초기화
        self._rendered_count = 0
        self.render_html()

    def _render_single_item(self, item: Dict, filter_word: str) -> str:
        """단일 뉴스 아이템 HTML 렌더링"""
        # 안전한 딕셔너리 접근
        is_read_cls = " read" if item.get('is_read', 0) else ""
        is_dup_cls = " duplicate" if item.get('is_duplicate', 0) else ""
        is_bm_cls = " bookmarked" if item.get('is_bookmarked', 0) else ""
        title_pfx = "⭐ " if item.get('is_bookmarked', 0) else ""
        item_link = item.get('link', '')
        item_title = item.get('title', '(제목 없음)')
        item_desc = item.get('description', '')
        
        link_hash = hashlib.md5(item_link.encode()).hexdigest()
        
        # 미리보기 데이터 저장 (append 시에도 동작)
        if hasattr(self.browser, 'preview_data'):
            self.browser.preview_data[link_hash] = item_desc
        
        if filter_word:
            title = TextUtils.highlight_text(item_title, filter_word)
            desc = TextUtils.highlight_text(item_desc, filter_word)
        else:
            title = html.escape(item_title)
            desc = html.escape(item_desc)

        # 북마크 버튼 텍스트/클래스
        is_bookmarked = bool(item.get('is_bookmarked', 0))
        bk_txt = "북마크 해제" if is_bookmarked else "북마크"
        bk_cls = "action-unbookmark" if is_bookmarked else "action-bookmark"
        
        date_str = item.get('pubDate', '')
        date_str = parse_date_string(date_str)

        has_note = bool(item.get('notes') and str(item.get('notes')).strip())
        note_indicator = " <span class='note-badge'>📝</span>" if has_note else ""

        # 액션 버튼
        actions = f"""
            <a class='action action-share' href='app://share/{link_hash}'>공유</a>
            <a class='action action-ext' href='app://ext/{link_hash}'>외부</a>
            <a class='action action-note' href='app://note/{link_hash}'>메모{note_indicator}</a>
        """
        if item.get('is_read', 0):
            actions += f"<a class='action action-unread' href='app://unread/{link_hash}'>안 읽음</a>"
        actions += f"<a class='action {bk_cls}' href='app://bm/{link_hash}'>{bk_txt}</a>"

        badges = ""
        if not self.is_bookmark_tab and self.keyword:
            keywords = self.keyword.split()
            for kw in keywords:
                if not kw.startswith('-'):
                    badges += f"<span class='keyword-tag'>{html.escape(kw)}</span>"
        
        if item.get('is_duplicate', 0):
            badges += "<span class='duplicate-badge'>유사</span>"

        return f"""
        <div class="news-item{is_read_cls}{is_dup_cls}{is_bm_cls}">
            <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
            <div class="meta-info">
                <div class="meta-left">📰 {html.escape(item.get('publisher', '정보 없음'))} · {date_str} {badges}</div>
                <div class="actions">{actions}</div>
            </div>
            <div class="description">{desc}</div>
        </div>
        """

    def _get_load_more_html(self, remaining: int) -> str:
        """더 보기 버튼 HTML"""
        return f"""
        <div class="load-more-container">
            <a class="load-more-btn" href="app://load_more">더 보기 ({remaining}개 남음)</a>
        </div>
        """

    def render_html(self):
        """HTML 렌더링 - Colors 헬퍼 사용 버전"""
        scroll_pos = self.browser.verticalScrollBar().value()
        
        is_dark = (self.theme == 1)
        
        # Colors 헬퍼를 사용하여 테마별 색상 가져오기
        colors = Colors.get_html_colors(is_dark)

        css = AppStyle.HTML_TEMPLATE.format(**colors)
        
        html_parts = [f"<html><head><meta charset='utf-8'>{css}</head><body>"]
        
        # 미리보기 데이터 초기화
        if hasattr(self.browser, 'set_preview_data'):
            self.browser.set_preview_data({})
        
        if not self.filtered_data_cache:
            if self.is_bookmark_tab:
                msg = "<div class='empty-state-title'>⭐ 북마크</div>북마크된 기사가 없습니다.<br><br>기사 카드의 [북마크] 버튼을 눌러<br>중요한 기사를 저장하세요."
            elif self.chk_unread.isChecked():
                msg = "<div class='empty-state-title'>✓ 완료!</div>모든 기사를 읽었습니다."
            else:
                msg = "<div class='empty-state-title'>📰 뉴스</div>표시할 기사가 없습니다.<br><br>새로고침 버튼을 눌러 최신 뉴스를 가져오세요."
            html_parts.append(f"<div class='empty-state'>{msg}</div>")
        else:
            filter_word = self.inp_filter.text().strip()
            
            # Phase 3: 렌더링 최적화 - 초기에는 제한된 수만 렌더링
            total_items = len(self.filtered_data_cache)
            render_limit = min(self._rendered_count + self.INITIAL_RENDER_COUNT, self.MAX_RENDER_COUNT)
            # 첫 렌더링 시 _rendered_count 보정
            if self._rendered_count < self.INITIAL_RENDER_COUNT:
                self._rendered_count = self.INITIAL_RENDER_COUNT
            
            render_limit = min(self._rendered_count, total_items) # 실제 데이터 개수 제한
            items_to_render = self.filtered_data_cache[:render_limit]
            self._rendered_count = len(items_to_render)
            
            for item in items_to_render:
                html_parts.append(self._render_single_item(item, filter_word))
            
            # 더 많은 항목이 있으면 "더 보기" 링크 표시
            remaining = total_items - self._rendered_count
            if remaining > 0:
                html_parts.append(self._get_load_more_html(remaining))
        
        html_parts.append("</body></html>")
        
        final_html = "".join(html_parts)
        self.browser.setHtml(final_html)
        
        # 스크롤 위치 복원
        if scroll_pos > 0:
            QTimer.singleShot(0, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))
        self.update_status_label()


    def append_items(self):
        """추가 아이템 로딩 (최적화: 전체 재렌더링 대신 _rendered_count 증가 후 렌더링)"""
        total_items = len(self.filtered_data_cache)
        start_idx = self._rendered_count
        end_idx = min(start_idx + self.LOAD_MORE_COUNT, total_items)
        
        if start_idx >= end_idx:
            return
        
        # _rendered_count 증가 (render_html에서 이 값까지 렌더링)
        self._rendered_count = end_idx
        
        # 스크롤 위치 저장 후 렌더링
        scroll_pos = self.browser.verticalScrollBar().value()
        self.render_html()
        
        # 스크롤 위치 복원 (약간의 지연 필요)
        if scroll_pos > 0:
            QTimer.singleShot(10, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))


    def update_status_label(self):
        """상태 레이블 업데이트 - 캐시 기반 최적화"""
        total_filtered = len(self.filtered_data_cache)
        rendered = self._rendered_count
        
        if not self.is_bookmark_tab:
            # 캐시된 데이터에서 안 읽은 수 계산 (DB 쿼리 방지)
            unread = sum(1 for item in self.news_data_cache if not item.get('is_read', 0))
            msg = f"'{self.keyword}': 총 {self.total_api_count}개"
            
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                msg += f" | 필터링: {total_filtered}개"
            else:
                msg += f" | {len(self.news_data_cache)}개"
            
            # Phase 3: 렌더링된 항목 수 표시
            if rendered < total_filtered:
                msg += f" (표시: {rendered}개)"
            
            if unread > 0:
                msg += f" | 안 읽음: {unread}개"
            if self.last_update:
                msg += f" | 업데이트: {self.last_update}"
            self.lbl_status.setText(msg)
        else:
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                status_text = f"⭐ 북마크 {len(self.news_data_cache)}개 중 {total_filtered}개"
            else:
                status_text = f"⭐ 북마크 {len(self.news_data_cache)}개"
            
            # Phase 3: 렌더링된 항목 수 표시
            if rendered < total_filtered:
                status_text += f" (표시: {rendered}개)"
            
            self.lbl_status.setText(status_text)


    def on_link_clicked(self, url: QUrl):
        """링크 클릭 처리"""
        scheme = url.scheme()
        if scheme != "app":
            return

        action = url.host()
        link_hash = url.path().lstrip('/')
        
        # Phase 3: 더 보기 액션 처리 (최적화: 부분 렌더링)
        if action == "load_more":
            # self._rendered_count += self.LOAD_MORE_COUNT # append_items 내부에서 처리됨
            self.append_items()
            return
        
        target = next(
            (i for i in self.news_data_cache if hashlib.md5(i['link'].encode()).hexdigest() == link_hash), 
            None
        )
        
        if not target:
            return


        link = target['link']

        if action == "open":
            self.db.update_status(link, "is_read", 1)
            QDesktopServices.openUrl(QUrl(link))
            target['is_read'] = 1
            self.apply_filter()
            
        elif action == "bm":
            new_val = 0 if target['is_bookmarked'] else 1
            if self.db.update_status(link, "is_bookmarked", new_val):
                target['is_bookmarked'] = new_val
                if self.is_bookmark_tab and new_val == 0:
                    self.news_data_cache.remove(target)
                self.apply_filter()
                if self.window() and hasattr(self.window(), 'refresh_bookmark_tab'):
                    self.window().refresh_bookmark_tab()
                    
                if self.window():
                    msg = "⭐ 북마크에 추가되었습니다." if new_val else "북마크가 해제되었습니다."
                    self.window().show_toast(msg)
                    
        elif action == "share":
            clip = f"{target['title']}\n{target['link']}"
            QApplication.clipboard().setText(clip)
            if self.window():
                self.window().show_toast("📋 링크와 제목이 복사되었습니다!")
            return
            
        elif action == "unread":
            self.db.update_status(link, "is_read", 0)
            target['is_read'] = 0
            self.apply_filter()
            if self.window():
                self.window().show_toast("📖 안 읽음으로 표시되었습니다.")
        
        elif action == "note":
            current_note = self.db.get_note(link)
            dialog = NoteDialog(current_note, self)
            if dialog.exec():
                new_note = dialog.get_note()
                if self.db.save_note(link, new_note):
                    target['notes'] = new_note
                    self.apply_filter()
                    if self.window():
                        self.window().show_toast("📝 메모가 저장되었습니다.")
            return
            
        elif action == "ext":
            QDesktopServices.openUrl(QUrl(link))
            return



# ... (in NewsTab) ...

    def mark_all_read(self):
        """모두 읽음으로 표시 (비동기)"""
        reply = QMessageBox.question(
            self,
            "모두 읽음으로 표시",
            "현재 표시된 모든 기사를 읽음으로 표시하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.lbl_status.setText("⏳ 처리 중...")
            self.btn_read_all.setEnabled(False)
            
            # 비동기 워커 실행
            # DB 검색용 키워드(db_keyword)를 사용
            self.job_worker = AsyncJobWorker(
                self.db.mark_all_as_read, 
                self.db_keyword, 
                self.is_bookmark_tab
            )
            self.job_worker.finished.connect(self._on_mark_all_read_done)
            self.job_worker.error.connect(self._on_mark_all_read_error)
            self.job_worker.start()
            
    def _on_mark_all_read_done(self, count):
        """모두 읽음 처리 완료"""
        self.btn_read_all.setEnabled(True)
        self.load_data_from_db() # UI 갱신
        if self.window():
            self.window().show_toast(f"✓ {count}개의 기사를 읽음으로 표시했습니다.")
            
    def _on_mark_all_read_error(self, err_msg):
        """모두 읽음 처리 오류"""
        self.btn_read_all.setEnabled(True)
        self.lbl_status.setText("오류 발생")
        QMessageBox.critical(self, "오류", f"처리 중 오류가 발생했습니다:\n\n{err_msg}")

    def update_timestamp(self):
        """업데이트 시간 갱신"""
        self.last_update = datetime.now().strftime('%H:%M:%S')


    def on_browser_action(self, action, link_hash):
        """브라우저 컨텍스트 메뉴 액션 처리"""
        target = next((i for i in self.news_data_cache if hashlib.md5(i['link'].encode()).hexdigest() == link_hash), None)
        if not target:
            return
            
        link = target['link']
        
        if action == "ext":
            QDesktopServices.openUrl(QUrl(link))
            if not target.get('is_read'):
                self.db.update_status(link, "is_read", 1)
                target['is_read'] = 1
                self.apply_filter()
                
        elif action == "share":
             clip = f"{target['title']}\n{target['link']}"
             QApplication.clipboard().setText(clip)
             if self.window(): self.window().show_toast("📋 복사되었습니다.")
             
        elif action == "bm":
            new_val = 0 if target.get('is_bookmarked') else 1
            if self.db.update_status(link, "is_bookmarked", new_val):
                target['is_bookmarked'] = new_val
                if self.is_bookmark_tab and new_val == 0:
                     self.news_data_cache.remove(target)
                self.apply_filter()
                if self.window():
                     if hasattr(self.window(), 'refresh_bookmark_tab'):
                        self.window().refresh_bookmark_tab()
                     msg = "⭐ 북마크됨" if new_val else "북마크 해제됨"
                     self.window().show_toast(msg)

        elif action == "toggle_read":
            new_val = 0 if target.get('is_read') else 1
            if self.db.update_status(link, "is_read", new_val):
                target['is_read'] = new_val
                self.apply_filter()
            
        elif action == "note":
            current_note = self.db.get_note(link)
            dialog = NoteDialog(current_note, self)
            if dialog.exec():
                new_note = dialog.get_note()
                if self.db.save_note(link, new_note):
                    target['notes'] = new_note
                    self.apply_filter()
                    if self.window():
                        self.window().show_toast("📝 메모가 저장되었습니다.")
             
        elif action == "delete":
             reply = QMessageBox.question(self, "삭제", "이 기사를 목록에서 삭제하시겠습니까?\n(DB에서 완전히 삭제됩니다)", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
             if reply == QMessageBox.StandardButton.Yes:
                 conn = self.db.get_connection()
                 try:
                     conn.execute("DELETE FROM news WHERE link=?", (link,))
                     conn.commit()
                     self.news_data_cache.remove(target)
                     # filtered_data_cache도 동기화
                     if target in self.filtered_data_cache:
                         self.filtered_data_cache.remove(target)
                     self.apply_filter()
                     if self.window(): self.window().show_toast("🗑 삭제되었습니다.")
                 except Exception as e:
                     QMessageBox.warning(self, "오류", f"삭제 실패: {e}")
                 finally:
                     self.db.return_connection(conn)

    def cleanup(self):
        """탭 종료 시 리소스 정리"""
        # 필터 타이머 정리
        if hasattr(self, 'filter_timer') and self.filter_timer:
            self.filter_timer.stop()
        
        # DB 워커 정리
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(1000)
        
        # Job 워커 정리
        if hasattr(self, 'job_worker') and self.job_worker and self.job_worker.isRunning():
            self.job_worker.wait(1000)
        
        logger.debug(f"NewsTab 정리 완료: {self.keyword}")


# --- 메인 윈도우 ---
class MainApp(QMainWindow):
    """메인 애플리케이션 윈도우 - 안정성 개선 버전"""
    
    def __init__(self):
        super().__init__()
        if not os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "w", encoding="utf-8") as f:
                    pass
            except Exception:
                pass
        
        logger.info("MainApp 초기화 시작")
        
        # 종료 원인 추적을 위한 플래그 (가장 먼저 초기화)
        self._system_shutdown = False       # Windows 시스템 종료
        self._user_requested_close = False  # 사용자가 종료 요청
        self._force_close = False           # 강제 종료 (확인 다이얼로그 스킵)
        
        # 안전한 초기화를 위해 기본 속성 미리 정의
        self.client_id = ""
        self.client_secret = ""
        self.toast_queue = None
        self.db = None
        self.session = None  # 세션 초기화
        
        try:
            self.db = DatabaseManager(DB_FILE)
            
            # Requests Session 설정 (성능 최적화: 연결 재사용)
            self.session = requests.Session()
            # Connection Pool 크기 증가 (동시 요청 처리)
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=3)
            self.session.mount('https://', adapter)
            self.session.mount('http://', adapter)
            
            self.workers = {}
            self.toast_queue = ToastQueue(self)
            
            # 새로고침 상태 추적 (안정성 개선)
            self._refresh_in_progress = False
            self._refresh_queue = []
            self._refresh_mutex = QMutex()
            self._last_refresh_time = None
            
            # 순차 새로고침 관련 변수 (완전 구현)
            self._pending_refresh_keywords = []
            self._sequential_refresh_active = False
            self._current_refresh_idx = 0
            self._total_refresh_count = 0
            self._sequential_added_count = 0  # 누적 추가 건수
            self._sequential_dup_count = 0    # 누적 중복 건수
            
            # 알림 관련 설정
            self.notification_enabled = True  # 데스크톱 알림 활성화
            self.alert_keywords = []  # 알림 키워드 목록
            self.sound_enabled = True  # 알림 소리 활성화
            self.notify_on_refresh = False  # 자동 새로고침 완료 알림 (기본 비활성화)
            
            # 키워드 그룹 관리자
            self.keyword_group_manager = KeywordGroupManager(os.path.join(APP_DIR, "keyword_groups.json"))
            
            # 자동 백업 관리자
            self.auto_backup = AutoBackup()
            
            # 검색 히스토리 (최근 10개)
            self.search_history = []
            
            # 네트워크 상태 추적
            self._network_error_count = 0  # 연속 네트워크 오류 횟수
            self._max_network_errors = 3   # 연속 오류 허용 횟수
            self._network_available = True  # 네트워크 연결 상태
            
            # 다음 새로고침 카운트다운 타이머
            self._countdown_timer = QTimer(self)
            self._countdown_timer.timeout.connect(self._update_countdown)
            self._next_refresh_seconds = 0
            
            # 아이콘 설정
            self.set_application_icon()
            
            self.load_config()
            self.init_ui()
            self.setup_shortcuts()
            
            # 타이머 설정 (안정성 개선)
            self.timer = QTimer(self)
            self.timer.timeout.connect(self._safe_refresh_all)
            self.apply_refresh_interval()
            
            if self.client_id and self.tabs.count() > 1:
                QTimer.singleShot(1000, self._safe_refresh_all)
            
            
            # 종료 원인 추적 플래그 (상단으로 이동됨)
            
            # 탭 배지 업데이트 타이머 (30초마다)
            self._tab_badge_timer = QTimer(self)
            self._tab_badge_timer.timeout.connect(self.update_all_tab_badges)
            self._tab_badge_timer.start(30000)  # 30초
            
            # 첫 실행 가이드 표시
            QTimer.singleShot(500, self._check_first_run)
            
            # 시작 시 자동 백업 (설정 파일이 있으면)
            if os.path.exists(CONFIG_FILE):
                QTimer.singleShot(2000, lambda: self.auto_backup.create_backup(include_db=False))
            
            # 시스템 트레이 설정
            self.setup_system_tray()
            
            # 최소화 상태로 시작 옵션 처리
            if '--minimized' in sys.argv or self.config.get('start_minimized', False):
                QTimer.singleShot(100, self.hide)
            
            logger.info("MainApp 초기화 완료")
        except Exception as e:
            logger.critical(f"MainApp 초기화 중 치명적 오류: {e}")
            traceback.print_exc()
            QMessageBox.critical(None, "초기화 오류", f"프로그램 초기화 중 오류가 발생했습니다:\n{e}")

    
    def _update_countdown(self):
        """상태바 카운트다운 업데이트"""
        if self._next_refresh_seconds > 0:
            self._next_refresh_seconds -= 1
            minutes = self._next_refresh_seconds // 60
            seconds = self._next_refresh_seconds % 60
            
            if not self._sequential_refresh_active:
                if minutes > 0:
                    countdown_text = f"⏰ 다음 새로고침: {minutes}분 {seconds}초 후"
                else:
                    countdown_text = f"⏰ 다음 새로고침: {seconds}초 후"
                self.statusBar().showMessage(countdown_text)
        else:
            self._countdown_timer.stop()

    
    def set_application_icon(self):
        """애플리케이션 아이콘 설정"""
        icon_path = None
        
        # 실행 파일과 같은 디렉토리에서 아이콘 찾기
        resource_dir = (
            getattr(sys, '_MEIPASS', APP_DIR)
            if getattr(sys, 'frozen', False)
            else APP_DIR
        )
        
        # Windows: .ico 파일 우선
        if sys.platform == 'win32':
            ico_path = os.path.join(resource_dir, ICON_FILE)
            if os.path.exists(ico_path):
                icon_path = ico_path
        
        # .ico가 없으면 .png 사용
        if not icon_path:
            png_path = os.path.join(resource_dir, ICON_PNG)
            if os.path.exists(png_path):
                icon_path = png_path
        
        # 아이콘 적용
        if icon_path and os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            QApplication.setWindowIcon(app_icon)  # 모든 창에 적용
        else:
            logger.warning(f"아이콘 파일을 찾을 수 없습니다: {ICON_FILE} 또는 {ICON_PNG}")
            logger.warning(f"실행 파일과 같은 폴더에 아이콘 파일을 배치하세요.")

    def setup_system_tray(self):
        """시스템 트레이 아이콘 설정"""
        try:
            # 트레이 아이콘 지원 확인
            if not QSystemTrayIcon.isSystemTrayAvailable():
                logger.warning("시스템 트레이를 사용할 수 없습니다.")
                self.tray = None
                return
            
            self.tray = QSystemTrayIcon(self)
            
            # 아이콘 설정
            resource_dir = (
                getattr(sys, '_MEIPASS', APP_DIR)
                if getattr(sys, 'frozen', False)
                else APP_DIR
            )

            icon_path = os.path.join(resource_dir, ICON_FILE)
            if not os.path.exists(icon_path):
                icon_path = os.path.join(resource_dir, ICON_PNG)
            
            if os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                # 기본 아이콘 사용
                self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
            
            # 트레이 컨텍스트 메뉴 생성
            tray_menu = QMenu(self)
            
            # 열기 액션
            action_show = tray_menu.addAction("📰 열기")
            action_show.triggered.connect(self.show_window)
            
            # 새로고침 액션
            action_refresh = tray_menu.addAction("🔄 새로고침")
            action_refresh.triggered.connect(self._safe_refresh_all)
            
            tray_menu.addSeparator()
            
            # 설정 액션
            action_settings = tray_menu.addAction("⚙ 설정")
            action_settings.triggered.connect(self.open_settings)
            
            tray_menu.addSeparator()
            
            # 종료 액션
            action_quit = tray_menu.addAction("❌ 종료")
            action_quit.triggered.connect(self.real_quit)
            
            self.tray.setContextMenu(tray_menu)
            
            # 더블클릭 시 창 보이기
            self.tray.activated.connect(self.on_tray_activated)
            
            # 초기 툴팁 설정
            self.update_tray_tooltip()
            
            # 트레이 아이콘 표시
            self.tray.show()
            
            logger.info("시스템 트레이 아이콘 설정 완료")
        except Exception as e:
            logger.error(f"시스템 트레이 설정 오류: {e}")
            self.tray = None
    
    def on_tray_activated(self, reason):
        """트레이 아이콘 활성화 이벤트 처리"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_window()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # 싱글 클릭 시 툴팁 업데이트
            self.update_tray_tooltip()
    
    def update_tray_tooltip(self):
        """트레이 아이콘 툴팁 업데이트 (읽지 않은 기사 수 표시)"""
        if not hasattr(self, 'tray') or not self.tray:
            return
        
        try:
            unread_count = 0
            for i in range(1, self.tabs.count()):
                tab_widget = self.tabs.widget(i)
                if tab_widget and hasattr(tab_widget, 'news_data_cache'):
                    for news_item in tab_widget.news_data_cache:
                        if not news_item.get('is_read', False):
                            unread_count += 1
            
            if unread_count > 0:
                tooltip = f"{APP_NAME}\n📬 읽지 않은 기사: {unread_count:,}개"
            else:
                tooltip = f"{APP_NAME}\n✅ 모든 기사를 읽었습니다"
            
            self.tray.setToolTip(tooltip)
        except Exception as e:
            logger.warning(f"트레이 툴팁 업데이트 오류: {e}")
            self.tray.setToolTip(APP_NAME)
    
    def show_window(self):
        """창 표시 (트레이에서 복원)"""
        self.showNormal()
        self.activateWindow()
        self.raise_()
        self.update_tray_tooltip()
    
    def real_quit(self):
        """프로그램 완전 종료 (트레이 메뉴에서 호출)"""
        logger.info("사용자가 트레이 메뉴에서 종료 요청")
        self._user_requested_close = True
        self._force_close = True
        
        # 설정 저장
        try:
            self.save_config()
        except Exception as e:
            logger.error(f"종료 전 설정 저장 오류: {e}")
        
        # 트레이 아이콘 숨기기
        if hasattr(self, 'tray') and self.tray:
            self.tray.hide()
        
        self.close()
    
    def show_tray_notification(self, title: str, message: str, icon_type=None):
        """시스템 트레이 알림 표시 (새 뉴스 도착 등)"""
        if not hasattr(self, 'tray') or not self.tray:
            return
        
        try:
            if icon_type is None:
                icon_type = QSystemTrayIcon.MessageIcon.Information
            
            self.tray.showMessage(
                title,
                message,
                icon_type,
                5000  # 5초간 표시
            )
        except Exception as e:
            logger.warning(f"트레이 알림 표시 오류: {e}")

    def load_config(self):
        """설정 로드"""
        self.config = {
            'client_id': '',
            'client_secret': '',
            'theme': 0,
            'interval': 2,
            'tabs': []
        }
        
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    
                if "app_settings" in loaded:
                    settings = loaded["app_settings"]
                    self.config['client_id'] = settings.get('client_id', '')
                    self.config['client_secret'] = settings.get('client_secret', '')
                    self.config['theme'] = settings.get('theme_index', 0)
                    self.config['interval'] = settings.get('refresh_interval_index', 2)
                    self.config['tabs'] = loaded.get('tabs', [])
                    self.config['notification_enabled'] = settings.get('notification_enabled', True)
                    self.config['alert_keywords'] = settings.get('alert_keywords', [])
                    self.config['sound_enabled'] = settings.get('sound_enabled', True)

                    # 새 설정: 트레이/자동시작/창 상태
                    self.config['minimize_to_tray'] = settings.get('minimize_to_tray', True)
                    self.config['close_to_tray'] = settings.get('close_to_tray', True)
                    self.config['start_minimized'] = settings.get('start_minimized', False)
                    self.config['auto_start_enabled'] = settings.get('auto_start_enabled', False)
                    self.config['notify_on_refresh'] = settings.get('notify_on_refresh', False)
                    self.config['api_timeout'] = settings.get('api_timeout', 15)
                    self.config['window_geometry'] = settings.get('window_geometry', None)

                    # 루트 데이터
                    self.config['search_history'] = loaded.get('search_history', [])
                else:
                    self.config['client_id'] = loaded.get('id', '')
                    self.config['client_secret'] = loaded.get('secret', '')
                    self.config['theme'] = loaded.get('theme', 0)
                    self.config['interval'] = loaded.get('interval', 2)
                    self.config['tabs'] = loaded.get('tabs', [])

                    # 레거시 호환
                    self.config['notification_enabled'] = loaded.get('notification_enabled', True)
                    self.config['alert_keywords'] = loaded.get('alert_keywords', [])
                    self.config['sound_enabled'] = loaded.get('sound_enabled', True)
                    self.config['minimize_to_tray'] = loaded.get('minimize_to_tray', True)
                    self.config['close_to_tray'] = loaded.get('close_to_tray', True)
                    self.config['start_minimized'] = loaded.get('start_minimized', False)
                    self.config['auto_start_enabled'] = loaded.get('auto_start_enabled', False)
                    self.config['notify_on_refresh'] = loaded.get('notify_on_refresh', False)
                    self.config['window_geometry'] = loaded.get('window_geometry', None)

                    self.config['search_history'] = loaded.get('search_history', []) # 검색 히스토리 로드
                    self.config['api_timeout'] = loaded.get('api_timeout', 15) # API 타임아웃 로드
            except Exception as e:
                logger.error(f"Config Load Error: {e}")
                QMessageBox.warning(
                    self, 
                    "설정 로드 오류", 
                    f"설정 파일을 읽는 중 오류가 발생했습니다.\n기본 설정으로 시작합니다.\n\n{str(e)}"
                )
        
        self.client_id = self.config['client_id']
        self.client_secret = self.config['client_secret']
        self.theme_idx = self.config['theme']
        self.interval_idx = self.config['interval']
        self.tabs_data = self.config['tabs']
        self.notification_enabled = self.config.get('notification_enabled', True)
        self.alert_keywords = self.config.get('alert_keywords', [])
        self.sound_enabled = self.config.get('sound_enabled', True)
        
        # 새 설정: 트레이/자동시작/창 상태
        self.minimize_to_tray = self.config.get('minimize_to_tray', True)  # 트레이로 최소화
        self.close_to_tray = self.config.get('close_to_tray', True)  # 닫기 시 트레이로
        self.start_minimized = self.config.get('start_minimized', False)  # 최소화 상태로 시작
        self.auto_start_enabled = self.config.get('auto_start_enabled', False)  # 윈도우 시작 시 자동 실행
        self._saved_geometry = self.config.get('window_geometry', None)  # 창 위치/크기
        self.notify_on_refresh = self.config.get('notify_on_refresh', False)  # 새로고침 완료 알림 (기본 비활성화)
        self.search_history = self.config.get('search_history', [])  # 검색 히스토리 초기화 (저장된 값 사용)
        self.api_timeout = self.config.get('api_timeout', 15) # 타임아웃 설정

    def save_config(self):
        """설정 저장"""
        tab_names = []
        for i in range(1, self.tabs.count()):
            tab_widget = self.tabs.widget(i)
            if tab_widget and hasattr(tab_widget, 'keyword'):
                tab_names.append(tab_widget.keyword)
        
        data = {
            'app_settings': {
                'client_id': self.client_id,
                'client_secret': self.client_secret,
                'theme_index': self.theme_idx,
                'refresh_interval_index': self.interval_idx,
                'notification_enabled': self.notification_enabled,
                'alert_keywords': self.alert_keywords,
                'sound_enabled': self.sound_enabled,
                'minimize_to_tray': self.minimize_to_tray,
                'close_to_tray': self.close_to_tray,
                'start_minimized': self.start_minimized,
                'auto_start_enabled': self.auto_start_enabled,
                'notify_on_refresh': self.notify_on_refresh,
                'api_timeout': self.api_timeout, # 타임아웃 저장
                'window_geometry': {
                    'x': self.x(),
                    'y': self.y(),
                    'width': self.width(),
                    'height': self.height()
                }
            },
            'tabs': tab_names,
            'search_history': self.search_history  # 검색 히스토리 저장
        }
        
        try:
            if os.path.exists(CONFIG_FILE):
                backup_file = CONFIG_FILE + '.backup'
                with open(CONFIG_FILE, 'r', encoding='utf-8') as src:
                    with open(backup_file, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Config Save Error: {e}")
            QMessageBox.warning(self, "저장 오류", f"설정을 저장하는 중 오류가 발생했습니다:\n\n{str(e)}")

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        
        # 저장된 창 상태 복원
        if self._saved_geometry:
            try:
                self.setGeometry(
                    self._saved_geometry.get('x', 100),
                    self._saved_geometry.get('y', 100),
                    self._saved_geometry.get('width', 1100),
                    self._saved_geometry.get('height', 850)
                )
            except Exception as e:
                logger.warning(f"창 상태 복원 실패: {e}")
                self.resize(1100, 850)
        else:
            self.resize(1100, 850)
        
        self.setMinimumSize(600, 400)  # 최소 창 크기 설정
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        
        # --- 주요 액션 그룹 ---
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_refresh.setToolTip("모든 탭의 뉴스를 새로고침합니다 (Ctrl+R, F5)")
        self.btn_refresh.setObjectName("RefreshBtn")
        
        self.btn_save = QPushButton("💾 내보내기")
        self.btn_save.setToolTip("현재 탭의 뉴스를 CSV로 내보냅니다 (Ctrl+S)")
        
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_save)
        
        # 구분선 1
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        sep1.setStyleSheet(f"color: {Colors.LIGHT_BORDER if self.theme_idx == 0 else Colors.DARK_BORDER};")
        toolbar.addWidget(sep1)
        
        # --- 분석/관리 그룹 ---
        self.btn_stats = QPushButton("📊 통계")
        self.btn_stats.setToolTip("전체 뉴스 통계 및 언론사별 분석 보기")
        
        self.btn_setting = QPushButton("⚙ 설정")
        self.btn_setting.setToolTip("API 키 및 프로그램 설정 (Ctrl+,)")
        
        self.btn_backup = QPushButton("🗂 백업")
        self.btn_backup.setToolTip("설정 백업 및 복원")
        
        self.btn_help = QPushButton("❓ 도움말")
        self.btn_help.setToolTip("사용 방법 및 도움말 (F1)")
        
        toolbar.addWidget(self.btn_stats)
        toolbar.addWidget(self.btn_setting)
        toolbar.addWidget(self.btn_backup)
        toolbar.addWidget(self.btn_help)
        
        toolbar.addStretch()
        
        # --- 탭 관리 그룹 ---
        self.btn_add = QPushButton("➕ 새 탭")
        self.btn_add.setToolTip("새로운 키워드 탭 추가 (Ctrl+T)")
        self.btn_add.setObjectName("AddTab")
        
        toolbar.addWidget(self.btn_add)
        layout.addLayout(toolbar)
        
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setTextVisible(True)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.tabBar().tabBarDoubleClicked.connect(self.rename_tab)
        self.tabs.tabBar().tabMoved.connect(self.on_tab_moved)  # 탭 순서 저장
        self.tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self.on_tab_context_menu)
        layout.addWidget(self.tabs)
        
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_setting.clicked.connect(self.open_settings)
        self.btn_stats.clicked.connect(self.show_stats_analysis)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_backup.clicked.connect(self.show_backup_dialog)
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.btn_save.clicked.connect(self.export_data)
        
        self.bm_tab = NewsTab("북마크", self.db, self.theme_idx, self)
        self.tabs.addTab(self.bm_tab, "⭐ 북마크")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        
        for key in self.tabs_data:
            if key and key != "북마크":
                self.add_news_tab(key)
        
        # 초기 탭 배지 업데이트
        QTimer.singleShot(100, self.update_all_tab_badges)
        
        # 상태바 초기 메시지
        if self.client_id:
            self.statusBar().showMessage(f"✅ 준비됨 - {len(self.tabs_data)}개 탭")
        else:
            self.statusBar().showMessage("⚠️ API 키가 설정되지 않았습니다. 설정에서 API 키를 입력하세요.")
        


    def setup_shortcuts(self):
        """키보드 단축키 설정"""
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_all)
        QShortcut(QKeySequence("Ctrl+T"), self, self.add_tab_dialog)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+S"), self, self.export_data)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings)
        QShortcut(QKeySequence("F1"), self, self.show_help)
        QShortcut(QKeySequence("F5"), self, self.refresh_all)
        
        for i in range(1, 10):
            QShortcut(QKeySequence(f"Alt+{i}"), self, lambda idx=i-1: self.switch_to_tab(idx))
        
        QShortcut(QKeySequence("Ctrl+F"), self, self.focus_filter)

    def _check_first_run(self):
        """첫 실행 시 API 키 설정 가이드 표시"""
        if not self.client_id or not self.client_secret:
            reply = QMessageBox.question(
                self,
                "🚀 뉴스 스크래퍼 Pro에 오신 것을 환영합니다!",
                "네이버 뉴스를 검색하려면 API 키가 필요합니다.\n\n"
                "네이버 개발자 센터에서 무료로 발급받을 수 있습니다.\n"
                "(https://developers.naver.com)\n\n"
                "지금 API 키를 설정하시겠습니까?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.open_settings()
    
    def update_all_tab_badges(self):
        """모든 탭의 배지(미읽음 수) 업데이트"""
        try:
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if widget and hasattr(widget, 'keyword'):
                    keyword = widget.keyword
                    # DB 조회 시에는 메인 키워드(첫 단어)만 사용
                    search_keyword = keyword.split()[0] if keyword else ""
                    unread_count = self.db.get_unread_count(search_keyword)
                    
                    # 탭 이름 업데이트
                    if unread_count > 0:
                        if unread_count > 99:
                            badge = f" ({99}+)"
                        else:
                            badge = f" ({unread_count})"
                        self.tabs.setTabText(i, f"{keyword}{badge}")
                    else:
                        self.tabs.setTabText(i, keyword)
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류: {e}")
    
    def update_tab_badge(self, keyword: str):
        """특정 탭의 배지 업데이트"""
        try:
            for i in range(1, self.tabs.count()):
                widget = self.tabs.widget(i)
                if widget and hasattr(widget, 'keyword') and widget.keyword == keyword:
                    # DB 조회 시에는 메인 키워드(첫 단어)만 사용
                    search_keyword = keyword.split()[0] if keyword else ""
                    unread_count = self.db.get_unread_count(search_keyword)
                    
                    if unread_count > 0:
                        badge = f" ({unread_count})" if unread_count <= 99 else " (99+)"
                        self.tabs.setTabText(i, f"{keyword}{badge}")
                    else:
                        self.tabs.setTabText(i, keyword)
                    break
        except Exception as e:
            logger.warning(f"탭 배지 업데이트 오류 ({keyword}): {e}")

    def switch_to_tab(self, index: int):
        """탭 전환"""
        if 0 <= index < self.tabs.count():
            self.tabs.setCurrentIndex(index)
    
    def focus_filter(self):
        """현재 탭의 필터 입력란에 포커스"""
        current_widget = self.tabs.currentWidget()
        if current_widget and hasattr(current_widget, 'inp_filter'):
            current_widget.inp_filter.setFocus()
            current_widget.inp_filter.selectAll()
    
    def on_tab_moved(self, from_idx: int, to_idx: int):
        """탭 이동 시 순서 저장"""
        logger.info(f"탭 이동: {from_idx} -> {to_idx}")
        self.save_config()
    
    def show_desktop_notification(self, title: str, message: str):
        """데스크톱 알림 표시"""
        if not self.notification_enabled:
            return
        try:
            if hasattr(self, 'tray') and self.tray:
                self.tray.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    3000  # 3초
                )
                # 알림 소리 재생
                if self.sound_enabled:
                    NotificationSound.play('success')
        except Exception as e:
            logger.warning(f"데스크톱 알림 오류: {e}")
    
    def show_log_viewer(self):
        """로그 뷰어 다이얼로그 표시"""
        dialog = LogViewerDialog(self)
        dialog.exec()
    
    def show_keyword_groups(self):
        """키워드 그룹 관리 다이얼로그 표시"""
        # 현재 탭 목록 수집
        current_tabs = []
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget and hasattr(widget, 'keyword'):
                current_tabs.append(widget.keyword)
        
        dialog = KeywordGroupDialog(self.keyword_group_manager, current_tabs, self)
        dialog.exec()
    
    def show_backup_dialog(self):
        """백업 관리 다이얼로그 표시"""
        dialog = BackupDialog(self.auto_backup, self)
        dialog.exec()
    
    def check_alert_keywords(self, items: list) -> list:
        """알림 키워드 체크 - 해당 키워드 포함된 기사 반환"""
        if not self.alert_keywords:
            return []
        
        matched = []
        for item in items:
            title = item.get('title', '').lower()
            desc = item.get('description', '').lower()
            for kw in self.alert_keywords:
                if kw.lower() in title or kw.lower() in desc:
                    matched.append((item, kw))
                    break
        return matched

    def show_toast(self, message: str, toast_type: ToastType = ToastType.INFO):
        """토스트 메시지 표시 - 유형별 스타일 지원"""
        self.toast_queue.add(message, toast_type)
    
    def show_success_toast(self, message: str):
        """성공 토스트 메시지"""
        self.show_toast(message, ToastType.SUCCESS)
    
    def show_warning_toast(self, message: str):
        """경고 토스트 메시지"""
        self.show_toast(message, ToastType.WARNING)
    
    def show_error_toast(self, message: str):
        """오류 토스트 메시지"""
        self.show_toast(message, ToastType.ERROR)
    
    def resizeEvent(self, event):
        """창 크기 변경 시 토스트 위치 업데이트"""
        super().resizeEvent(event)
        if hasattr(self, 'toast_queue') and self.toast_queue and self.toast_queue.current_toast:
            self.toast_queue.current_toast.update_position()

    def close_current_tab(self):
        """현재 탭 닫기"""
        idx = self.tabs.currentIndex()
        if idx > 0:
            self.close_tab(idx)

    def add_news_tab(self, keyword: str):
        """뉴스 탭 추가"""
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            if hasattr(widget, 'keyword') and widget.keyword == keyword:
                self.tabs.setCurrentIndex(i)
                return
        
        tab = NewsTab(keyword, self.db, self.theme_idx, self)
        tab.btn_load.clicked.connect(lambda: self.fetch_news(keyword, is_more=True))
        icon_text = "📰" if not keyword.startswith("-") else "🚫"
        self.tabs.addTab(tab, f"{icon_text} {keyword}")
        
        # 탭 추가 직후 캐시 로드 (오프라인 모드 지원 및 즉각적인 UI 표시)
        QTimer.singleShot(50, tab.load_data_from_db)

    def add_tab_dialog(self):
        """새 탭 추가 다이얼로그 - 검색 히스토리 지원"""
        dialog = QDialog(self)
        dialog.setWindowTitle("새 탭 추가")
        dialog.resize(450, 300)
        
        layout = QVBoxLayout(dialog)
        
        info_label = QLabel(
            "검색할 키워드를 입력하세요.\n"
            "제외 키워드는 '-'를 앞에 붙여주세요.\n\n"
            "예시: 주식 -코인, 인공지능 AI -광고"
        )
        info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info_label)
        
        input_field = QLineEdit()
        input_field.setPlaceholderText("🔍 키워드 입력...")
        layout.addWidget(input_field)
        
        # 최근 검색 히스토리 표시
        if self.search_history:
            history_label = QLabel("📋 최근 검색:")
            history_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
            layout.addWidget(history_label)
            
            history_layout = QHBoxLayout()
            for kw in self.search_history[:5]:  # 최근 5개
                btn = QPushButton(kw)
                btn.setStyleSheet("padding: 4px 8px; font-size: 9pt;")
                btn.clicked.connect(lambda checked, text=kw: input_field.setText(text))
                history_layout.addWidget(btn)
            history_layout.addStretch()
            layout.addLayout(history_layout)
        
        # 빠른 입력 (추천 키워드)
        quick_label = QLabel("💡 추천 키워드:")
        quick_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(quick_label)
        
        quick_layout = QHBoxLayout()
        examples = ["주식", "부동산", "IT 기술", "스포츠", "경제"]
        for example in examples:
            btn = QPushButton(example)
            btn.setStyleSheet("padding: 4px 8px; font-size: 9pt;")
            btn.clicked.connect(lambda checked, text=example: input_field.setText(text))
            quick_layout.addWidget(btn)
        quick_layout.addStretch()
        layout.addLayout(quick_layout)
        
        layout.addStretch()
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec():
            raw_keyword = input_field.text().strip()
            
            # 키워드 입력 검증
            if not raw_keyword:
                QMessageBox.warning(self, "입력 오류", "키워드를 입력해 주세요.")
                return
            
            if len(raw_keyword) > 100:
                QMessageBox.warning(
                    self, 
                    "입력 오류", 
                    f"키워드가 너무 깁니다. ({len(raw_keyword)}자)\n"
                    "최대 100자까지 입력 가능합니다."
                )
                return
            
            keyword = ValidationUtils.sanitize_keyword(raw_keyword)
            
            # 중복 탭 체크
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if hasattr(w, 'keyword') and w.keyword == keyword:
                    QMessageBox.information(
                        self, 
                        "중복 태브", 
                        f"'{keyword}' 탭이 이미 존재합니다.\n해당 탭으로 이동합니다."
                    )
                    self.tabs.setCurrentIndex(i)
                    return
            
            self.add_news_tab(keyword)
            self.fetch_news(keyword)
            
            # 검색 히스토리에 추가
            if keyword not in self.search_history:
                self.search_history.insert(0, keyword)
                self.search_history = self.search_history[:10]  # 최대 10개 유지
            
            # 설정 저장 (히스토리 업데이트)
            self.save_config()

    def close_tab(self, idx: int):
        """탭 닫기"""
        if idx == 0:
            return
        
        widget = self.tabs.widget(idx)
        if widget:
            widget.deleteLater()
        self.tabs.removeTab(idx)
        self.save_config()

    def rename_tab(self, idx: int):
        """탭 이름 변경"""
        if idx == 0:
            return
        
        w = self.tabs.widget(idx)
        if not w:
            return
        
        text, ok = QInputDialog.getText(
            self,
            '탭 이름 변경',
            '새 검색 키워드를 입력하세요:',
            QLineEdit.EchoMode.Normal,
            w.keyword
        )
        
        if ok and text.strip():
            old_keyword = w.keyword
            new_keyword = ValidationUtils.sanitize_keyword(text)
            w.keyword = new_keyword
            
            icon_text = "📰" if not new_keyword.startswith("-") else "🚫"
            self.tabs.setTabText(idx, f"{icon_text} {new_keyword}")
            
            # DB 업데이트: 검색 키워드(첫 번째 단어)만 사용
            old_search_keyword = old_keyword.split()[0] if old_keyword.split() else old_keyword
            new_search_keyword = new_keyword.split()[0] if new_keyword.split() else new_keyword
            
            conn = self.db.get_connection()
            try:
                with conn:
                    conn.execute("UPDATE news SET keyword=? WHERE keyword=?", 
                                (new_search_keyword, old_search_keyword))
            except Exception as e:
                logger.error(f"Rename error: {e}")
            finally:
                self.db.return_connection(conn)
            
            self.fetch_news(new_keyword)
            self.save_config()

    def on_tab_context_menu(self, pos):
        """탭 바 컨텍스트 메뉴"""
        idx = self.tabs.tabBar().tabAt(pos)
        if idx <= 0:  # 0은 북마크 탭
            return
            
        widget = self.tabs.widget(idx)
        if not widget or not hasattr(widget, 'keyword'):
            return
            
        keyword = widget.keyword
        
        menu = QMenu(self)
        
        act_refresh = menu.addAction("🔄 새로고침")
        act_rename = menu.addAction("✏️ 이름 변경")
        menu.addSeparator()
        
        # 그룹 메뉴
        group_menu = menu.addMenu("📁 그룹에 추가")
        groups = self.keyword_group_manager.get_all_groups()
        if groups:
            for group in groups:
                act = group_menu.addAction(group)
                act.triggered.connect(lambda checked, g=group, k=keyword: 
                                    self._add_to_group_callback(g, k))
        else:
            group_menu.setDisabled(True)
            
        menu.addSeparator()
        act_close = menu.addAction("❌ 탭 닫기")
        
        # mapToGlobal은 self.tabs.tabBar() 기준으로 변환해야 함
        action = menu.exec(self.tabs.tabBar().mapToGlobal(pos))
        
        if action == act_refresh:
            self.fetch_news(keyword)
        elif action == act_rename:
            self.rename_tab(idx)
        elif action == act_close:
            self.close_tab(idx)

    def _add_to_group_callback(self, group: str, keyword: str):
        """컨텍스트 메뉴에서 그룹 추가 콜백"""
        if self.keyword_group_manager.add_keyword_to_group(group, keyword):
            self.show_success_toast(f"'{keyword}'을(를) '{group}' 그룹에 추가했습니다.")
        else:
            self.show_warning_toast(f"이미 '{group}' 그룹에 존재하는 키워드입니다.")

    def _safe_refresh_all(self):
        """안전한 자동 새로고침 래퍼 (타이머에서 호출)"""
        # 네트워크 연속 오류 시 자동 새로고침 일시 중지
        if self._network_error_count >= self._max_network_errors:
            if self._network_available:  # 첫 번째 감지 시에만 로그
                logger.warning(f"네트워크 연속 오류 {self._network_error_count}회. 자동 새로고침 일시 중지.")
                self._network_available = False
                self.statusBar().showMessage("⚠ 네트워크 오류로 자동 새로고침 일시 중지 (수동 새로고침으로 재개)")
            return
        
        # 이미 새로고침 진행 중이면 건너뜀
        with QMutexLocker(self._refresh_mutex):
            if self._refresh_in_progress or self._sequential_refresh_active:
                logger.warning("새로고침이 이미 진행 중입니다. 건너킵니다.")
                return
            self._refresh_in_progress = True
        
        try:
            self.refresh_all()
            # 주의: refresh_all은 비동기 작업을 시작함
            # _refresh_in_progress 플래그는 _finish_sequential_refresh에서 해제됨
        except Exception as e:
            logger.error(f"자동 새로고침 오류: {e}")
            # 오류 발생 시에만 여기서 플래그 해제
            with QMutexLocker(self._refresh_mutex):
                self._refresh_in_progress = False

    def refresh_all(self):
        """모든 탭 새로고침 - 완전한 순차 새로고침 버전"""
        logger.info("전체 새로고침 시작")
        
        # 이미 순차 새로고침 진행 중이면 무시
        if self._sequential_refresh_active:
            logger.warning("순차 새로고침이 이미 진행 중입니다. 건너킵니다.")
            return
        
        try:
            valid, msg = ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
            if not valid:
                self.statusBar().showMessage(f"⚠ {msg}")
                logger.warning(f"API 자격증명 오류: {msg}")
                return

            # 수동 새로고침 시 네트워크 오류 카운터 리셋 (자동 새로고침 재개)
            self._network_error_count = 0
            self._network_available = True
            
            # 북마크 탭 새로고침 (동기)
            try:
                self.bm_tab.load_data_from_db()
            except Exception as e:
                logger.error(f"북마크 탭 로드 오류: {e}")
            
            # 새로고침할 키워드 목록 수집
            self._pending_refresh_keywords = []
            tab_count = self.tabs.count()
            for i in range(1, tab_count):
                try:
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'keyword'):
                        self._pending_refresh_keywords.append(widget.keyword)
                except Exception as e:
                    logger.error(f"탭 {i} 접근 오류: {e}")
            
            if not self._pending_refresh_keywords:
                self.statusBar().showMessage("새로고침할 탭이 없습니다.")
                return
            
            # 순차 새로고침 상태 초기화
            self._sequential_refresh_active = True
            self._current_refresh_idx = 0
            self._total_refresh_count = len(self._pending_refresh_keywords)
            self._sequential_added_count = 0  # 누적 카운터 초기화
            self._sequential_dup_count = 0
            
            # UI 설정
            self.progress.setVisible(True)
            self.progress.setRange(0, self._total_refresh_count)
            self.progress.setValue(0)
            self.statusBar().showMessage(f"🔄 순차 새로고침 중... (0/{self._total_refresh_count})")
            self.btn_refresh.setEnabled(False)
            
            logger.info(f"순차 새로고침 시작: {self._total_refresh_count}개 탭")
            
            # 첫 번째 탭 새로고침 시작
            self._process_next_refresh()
                    
        except Exception as e:
            logger.error(f"refresh_all 오류: {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 새로고침 오류: {str(e)}")
            self._finish_sequential_refresh()

    def _process_next_refresh(self):
        """순차 새로고침 체인: 다음 탭 처리"""
        if not self._sequential_refresh_active:
            return
            
        if self._current_refresh_idx >= len(self._pending_refresh_keywords):
            # 모든 탭 완료
            self._finish_sequential_refresh()
            return
        
        keyword = self._pending_refresh_keywords[self._current_refresh_idx]
        logger.info(f"순차 새로고침: [{self._current_refresh_idx + 1}/{self._total_refresh_count}] '{keyword}'")
        
        self.progress.setValue(self._current_refresh_idx)
        self.statusBar().showMessage(
            f"🔄 '{keyword}' 새로고침 중... ({self._current_refresh_idx + 1}/{self._total_refresh_count})"
        )
        
        try:
            self.fetch_news(keyword, is_sequential=True)
        except Exception as e:
            logger.error(f"'{keyword}' 새로고침 오류: {e}")
            # 오류 발생해도 다음 탭 진행
            self._current_refresh_idx += 1
            QTimer.singleShot(500, self._process_next_refresh)

    def _on_sequential_fetch_done(self, keyword: str):
        """순차 새로고침에서 하나의 fetch 완료 시 호출"""
        if not self._sequential_refresh_active:
            return
            
        self._current_refresh_idx += 1
        
        # 약간의 딜레이 후 다음 탭 처리 (API rate limit 방지)
        QTimer.singleShot(300, self._process_next_refresh)

    def _finish_sequential_refresh(self):
        """순차 새로고침 완료 처리"""
        self._sequential_refresh_active = False
        self._pending_refresh_keywords = []
        self._last_refresh_time = datetime.now()
        
        # _safe_refresh_all에서 설정한 플래그도 해제
        with QMutexLocker(self._refresh_mutex):
            self._refresh_in_progress = False
        
        self.progress.setValue(self._total_refresh_count)
        self.progress.setVisible(False)
        self.btn_refresh.setEnabled(True)
        
        # 누적 카운터를 사용한 최종 메시지
        added = self._sequential_added_count
        dup = self._sequential_dup_count
        
        logger.info(f"순차 새로고침 완료 ({self._total_refresh_count}개 탭, {added}건 추가, {dup}건 중복)")
        
        toast_msg = f"✓ {self._total_refresh_count}개 탭 새로고침 완료 ({added}건 추가"
        if dup > 0:
            toast_msg += f", {dup}건 중복"
        toast_msg += ")"
        
        self.statusBar().showMessage(toast_msg, 5000)
        self.show_toast(toast_msg)
        
        # 자동 새로고침 완료 윈도우 알림 (설정 시)
        if self.notify_on_refresh and added > 0:
            self.show_tray_notification(
                "📰 자동 새로고침 완료",
                f"{added}건의 새 뉴스가 업데이트되었습니다."
            )
        
        # 카운트다운 타이머 재시작
        self.apply_refresh_interval()

    def fetch_news(self, keyword: str, is_more: bool = False, is_sequential: bool = False):
        """뉴스 가져오기 - 순차 새로고침 지원"""
        parts = keyword.split()
        search_keyword = parts[0] if parts else keyword
        exclude_words = [p[1:] for p in parts[1:] if p.startswith('-')]
        
        start_idx = 1
        if is_more:
            start_idx = self.db.get_counts(search_keyword) + 1
            if start_idx > 1000:
                QMessageBox.information(
                    self,
                    "알림",
                    "네이버 검색 API는 최대 1,000개까지만 조회할 수 있습니다."
                )
                # 순차 새로고침 중이면 다음 탭으로 진행
                if is_sequential:
                    self._on_sequential_fetch_done(keyword)
                return

        # 기존 워커가 있으면 완전히 정리
        if keyword in self.workers:
            old_worker, old_thread = self.workers[keyword]
            try:
                old_worker.stop()
                old_thread.quit()
                if not old_thread.wait(1000):  # 최대 1초 대기
                    logger.warning(f"기존 스레드 강제 종료: {keyword}")
                    old_thread.terminate()
                    old_thread.wait(500)
            except (RuntimeError, AttributeError):
                pass
            self.cleanup_worker(keyword)

        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(False)
                w.btn_load.setText("⏳ 로딩 중...")
                break

        worker = ApiWorker(
            self.client_id, 
            self.client_secret, 
            search_keyword, 
            exclude_words, 
            self.db,  # DB 매니저 전달
            start_idx,
            timeout=self.api_timeout, # 타임아웃 전달
            session=self.session      # 공유 세션 전달
        )
        thread = QThread()
        worker.moveToThread(thread)
        
        self.workers[keyword] = (worker, thread)
        # Note: self.threads는 workers와 중복되므로 제거됨
        
        worker.finished.connect(lambda res: self.on_fetch_done(res, keyword, is_more, is_sequential))
        worker.error.connect(lambda err: self.on_fetch_error(err, keyword, is_sequential))
        if not is_sequential:
            worker.progress.connect(self.statusBar().showMessage)
        
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        worker.error.connect(worker.deleteLater)  # 오류 시에도 워커 정리
        
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.cleanup_worker(keyword))
        
        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(self, result: Dict, keyword: str, is_more: bool, is_sequential: bool = False):
        """뉴스 가져오기 완료 - 순차 새로고침 지원"""
        try:
            search_keyword = keyword.split()[0] if keyword.split() else keyword
            
            # DB 저장은 Worker에서 이미 수행됨
            added_count = result.get('added_count', 0)
            dup_count = result.get('dup_count', 0)
            
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if w and hasattr(w, 'keyword') and w.keyword == keyword:
                    w.total_api_count = result['total']
                    w.update_timestamp()
                    w.load_data_from_db()
                    
                    w.btn_load.setEnabled(True)
                    w.btn_load.setText("📥 더 불러오기")
                    
                    if not is_more and not is_sequential:
                        msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                        if dup_count > 0:
                            msg += f", {dup_count}건 중복"
                        if result.get('filtered', 0) > 0:
                            msg += f", {result['filtered']}건 필터링"
                        msg += ")"
                        w.lbl_status.setText(msg)
                    break
            
            # 순차 새로고침 중이면 UI 복원하지 않음
            if not is_sequential:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)
                
                if not is_more:
                    toast_msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                    if dup_count > 0:
                        toast_msg += f", {dup_count}건 유사"
                    toast_msg += ")"
                    self.show_toast(toast_msg)
                    self.statusBar().showMessage(toast_msg, 3000)
                    
                    # 새 기사가 있으면 데스크톱 알림
                    if added_count > 0:
                        self.show_desktop_notification(
                            f"📰 {keyword}",
                            f"{added_count}건의 새 뉴스가 있습니다."
                        )
                        # 창이 숨겨져 있으면 트레이 알림도 표시
                        if not self.isVisible():
                            self.show_tray_notification(
                                f"📰 {keyword}",
                                f"{added_count}건의 새 뉴스가 도착했습니다."
                            )
                        # 트레이 툴팁 업데이트
                        self.update_tray_tooltip()
                    
                    # 알림 키워드 체크
                    matched = self.check_alert_keywords(result['items'])
                    if matched:
                        for item, kw in matched[:3]:  # 최대 3개
                            title = html.unescape(RE_HTML_TAGS.sub('', item.get('title', '')))
                            self.show_desktop_notification(
                                f"🔔 알림 키워드: {kw}",
                                title[:50]
                            )
            else:
                # 순차 새로고침 체인: 카운터 누적 후 다음 탭으로 진행
                self._sequential_added_count += added_count
                self._sequential_dup_count += dup_count
                logger.info(f"순차 새로고침 완료: '{keyword}' ({added_count}건 추가)")
                self._on_sequential_fetch_done(keyword)
            
            # 성공 시 네트워크 오류 카운터 리셋
            self._network_error_count = 0
            self._network_available = True
            
            # 탭 배지 업데이트
            self.update_tab_badge(keyword)
                
        except Exception as e:
            logger.error(f"Fetch Done Error: {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 처리 중 오류: {str(e)}")
            # UI 복원
            if not is_sequential:
                self.progress.setVisible(False)
                self.btn_refresh.setEnabled(True)
            else:
                # 순차 새로고침 중 오류 발생해도 다음 탭 진행
                self._on_sequential_fetch_done(keyword)

    def on_fetch_error(self, error_msg: str, keyword: str, is_sequential: bool = False):
        """뉴스 가져오기 오류 - 순차 새로고침 지원"""
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(True)
                w.btn_load.setText("📥 더 불러오기")
                break
        
        if not is_sequential:
            # 개별 새로고침 시 UI 복원 및 오류 메시지
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self.btn_refresh.setEnabled(True)
            
            self.statusBar().showMessage(f"⚠ '{keyword}' 오류: {error_msg}", 5000)
            QMessageBox.critical(
                self, 
                "API 오류", 
                f"'{keyword}' 검색 중 오류가 발생했습니다:\n\n{error_msg}\n\n"
                "API 키가 올바른지, 네트워크 연결 상태를 확인해주세요."
            )
        else:
            # 순차 새로고침 중에는 오류 로그만 남기고 다음 탭으로 진행
            logger.warning(f"순차 새로고침 중 오류: '{keyword}' - {error_msg}")
            self._on_sequential_fetch_done(keyword)
        
        # 네트워크 관련 오류인 경우 카운터 증가
        network_error_keywords = ['네트워크', 'timeout', '연결', 'connection', 'Timeout', 'Network']
        is_network_error = any(kw in error_msg for kw in network_error_keywords)
        if is_network_error:
            self._network_error_count += 1
            logger.warning(f"네트워크 오류 카운트: {self._network_error_count}/{self._max_network_errors}")
        else:
            # 네트워크가 아닌 오류는 카운터 리셋 (API 키 오류 등)
            self._network_error_count = 0

    def cleanup_worker(self, keyword: str):
        """워커 정리 - 안정성 개선 버전"""
        try:
            if keyword in self.workers:
                worker, thread = self.workers[keyword]
                
                # worker가 아직 유효한지 확인
                try:
                    # sip (PyQt 내부)로 객체 삭제 여부 확인
                    if worker is None:
                        del self.workers[keyword]
                        return
                except RuntimeError:
                    # C++ 객체가 이미 삭제됨
                    del self.workers[keyword]
                    logger.info(f"워커 이미 삭제됨: {keyword}")
                    return
                
                # 시그널 안전하게 disconnect (크래시 방지)
                try:
                    worker.finished.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.error.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    worker.progress.disconnect()
                except (TypeError, RuntimeError):
                    pass
                
                try:
                    worker.stop()
                except (AttributeError, RuntimeError):
                    pass
                del self.workers[keyword]
                logger.info(f"워커 정리 완료: {keyword}")
        except Exception as e:
            logger.error(f"워커 정리 오류 ({keyword}): {e}")

    def refresh_bookmark_tab(self):
        """북마크 탭 새로고침"""
        self.bm_tab.load_data_from_db()

    def export_data(self):
        """데이터 내보내기"""
        cur_widget = self.tabs.currentWidget()
        if not cur_widget or not hasattr(cur_widget, 'news_data_cache') or not cur_widget.news_data_cache:
            QMessageBox.information(self, "알림", "저장할 뉴스가 없습니다.")
            return
        
        keyword = cur_widget.keyword
        default_name = f"{keyword}_뉴스_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "데이터 내보내기",
            default_name,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if fname:
            try:
                with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['제목', '링크', '날짜', '출처', '요약', '읽음', '북마크', '메모', '중복'])
                    
                    for item in cur_widget.news_data_cache:
                        writer.writerow([
                            item['title'],
                            item['link'],
                            item['pubDate'],
                            item['publisher'],
                            item['description'],
                            '읽음' if item['is_read'] else '안읽음',
                            '⭐' if item['is_bookmarked'] else '',
                            item.get('notes', ''),
                            '유사' if item.get('is_duplicate', 0) else ''
                        ])
                
                self.show_success_toast(f"✓ {len(cur_widget.news_data_cache)}개 항목이 저장되었습니다")
                QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")
                
            except Exception as e:
                QMessageBox.warning(self, "오류", f"저장 중 오류 발생:\n{str(e)}")
    
    def export_settings(self):
        """설정 JSON 내보내기 (API 키 제외)"""
        fname, _ = QFileDialog.getSaveFileName(
            self,
            "설정 내보내기",
            f"news_scraper_settings_{datetime.now().strftime('%Y%m%d')}.json",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if fname:
            # API 키는 보안상 제외
            export_data = {
                'export_version': '1.0',
                'app_version': VERSION,
                'settings': {
                    'theme_index': self.theme_idx,
                    'refresh_interval_index': self.interval_idx,
                    'notification_enabled': self.notification_enabled,
                    'alert_keywords': self.alert_keywords,
                    'close_to_tray': self.close_to_tray,
                    'start_minimized': self.start_minimized,
                    'notify_on_refresh': self.notify_on_refresh
                },
                'tabs': [self.tabs.widget(i).keyword 
                        for i in range(1, self.tabs.count()) 
                        if hasattr(self.tabs.widget(i), 'keyword')]
            }
            
            try:
                with open(fname, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=4, ensure_ascii=False)
                self.show_success_toast("✓ 설정이 내보내기되었습니다.")
                QMessageBox.information(self, "완료", f"설정이 저장되었습니다:\n{fname}\n\n(API 키는 보안상 제외됨)")
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 내보내기 오류:\n{str(e)}")
    
    def import_settings(self):
        """설정 JSON 가져오기"""
        fname, _ = QFileDialog.getOpenFileName(
            self,
            "설정 가져오기",
            "",
            "JSON Files (*.json);;All Files (*)"
        )
        
        if fname:
            try:
                with open(fname, 'r', encoding='utf-8') as f:
                    import_data = json.load(f)
                
                # 설정 적용
                settings = import_data.get('settings', {})
                self.theme_idx = settings.get('theme_index', self.theme_idx)
                self.interval_idx = settings.get('refresh_interval_index', self.interval_idx)
                self.notification_enabled = settings.get('notification_enabled', True)
                self.alert_keywords = settings.get('alert_keywords', [])
                
                # 테마 적용
                self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
                for i in range(self.tabs.count()):
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'theme'):
                        widget.theme = self.theme_idx
                        widget.render_html()
                
                # 탭 추가 (중복 제외)
                imported_tabs = import_data.get('tabs', [])
                existing_keywords = [self.tabs.widget(i).keyword 
                                    for i in range(1, self.tabs.count()) 
                                    if hasattr(self.tabs.widget(i), 'keyword')]
                
                new_tabs = 0
                for keyword in imported_tabs:
                    if keyword and keyword not in existing_keywords:
                        self.add_news_tab(keyword)
                        new_tabs += 1
                
                self.apply_refresh_interval()
                self.save_config()
                
                msg = "✓ 설정을 가져왔습니다."
                if new_tabs > 0:
                    msg += f" ({new_tabs}개 탭 추가됨)"
                self.show_toast(msg)
                
            except Exception as e:
                QMessageBox.warning(self, "오류", f"설정 가져오기 오류:\n{str(e)}")

    def show_statistics(self):
        """통계 정보 표시"""
        stats = self.db.get_statistics()
        
        if stats['total'] > 0:
            read_count = stats['total'] - stats['unread']
            read_percent = (read_count / stats['total']) * 100
        else:
            read_percent = 0
        
        dialog = QDialog(self)
        dialog.setWindowTitle("통계 정보")
        dialog.resize(350, 350)
        
        layout = QVBoxLayout(dialog)
        
        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()
        
        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
            ("탭 개수:", f"{self.tabs.count() - 1}개"),
        ]
        
        for i, (label, value) in enumerate(items):
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel(value)
            val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
            grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
        
        group.setLayout(grid)
        layout.addWidget(group)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()

    def show_stats_analysis(self):
        """통계 및 분석 통합 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("📊 통계 및 분석")
        dialog.resize(550, 500)
        
        main_layout = QVBoxLayout(dialog)
        
        # 탭 위젯
        tab_widget = QTabWidget()
        
        # === 통계 탭 ===
        stats_widget = QWidget()
        stats_layout = QVBoxLayout(stats_widget)
        
        stats = self.db.get_statistics()
        if stats['total'] > 0:
            read_percent = ((stats['total'] - stats['unread']) / stats['total']) * 100
        else:
            read_percent = 0
        
        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()
        
        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
            ("중복 기사:", f"{stats['duplicates']:,}개"),
            ("읽은 비율:", f"{read_percent:.1f}%"),
            ("탭 개수:", f"{self.tabs.count() - 1}개"),
        ]
        
        for i, (label, value) in enumerate(items):
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: bold;")
            val = QLabel(value)
            val.setStyleSheet("color: #007AFF;" if self.theme_idx == 0 else "color: #0A84FF;")
            grid.addWidget(lbl, i, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val, i, 1, Qt.AlignmentFlag.AlignLeft)
        
        group.setLayout(grid)
        stats_layout.addWidget(group)
        stats_layout.addStretch()
        
        # === 분석 탭 ===
        analysis_widget = QWidget()
        analysis_layout = QVBoxLayout(analysis_widget)
        
        tab_label = QLabel("분석할 탭을 선택하세요:")
        analysis_layout.addWidget(tab_label)
        
        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword'):
                # DB 조회용 키워드(db_keyword)를 data로 저장
                db_kw = w.db_keyword if hasattr(w, 'db_keyword') else w.keyword.split()[0]
                tab_combo.addItem(w.keyword, db_kw)
        analysis_layout.addWidget(tab_combo)
        
        result_label = QLabel("📈 언론사별 기사 수:")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        analysis_layout.addWidget(result_label)
        
        result_list = QListWidget()
        analysis_layout.addWidget(result_list)
        
        def update_analysis():
            result_list.clear()
            keyword = tab_combo.currentData()
            publishers = self.db.get_top_publishers(keyword, limit=20)
            
            if publishers:
                for i, (pub, count) in enumerate(publishers, 1):
                    result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                result_list.addItem("데이터가 없습니다.")
        
        tab_combo.currentIndexChanged.connect(update_analysis)
        update_analysis()
        
        # 탭 추가
        tab_widget.addTab(stats_widget, "📊 통계")
        tab_widget.addTab(analysis_widget, "📈 언론사 분석")
        
        main_layout.addWidget(tab_widget)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        main_layout.addWidget(btn_close)
        
        dialog.exec()

    def show_analysis(self):
        """언론사별 분석 (호환성 유지)"""
        self.show_stats_analysis()

    def show_help(self):
        """도움말 표시 (설정 창의 도움말 탭으로 열기)"""
        current_config = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'interval': self.interval_idx,
            'theme': self.theme_idx
        }
        
        dlg = SettingsDialog(current_config, self)
        # 도움말 탭으로 전환 (탭 인덱스 1)
        if hasattr(dlg, 'findChild'):
            tab_widget = dlg.findChild(QTabWidget)
            if tab_widget:
                tab_widget.setCurrentIndex(1)  # 도움말 탭
        
        dlg.exec()

    def open_settings(self):
        """설정 다이얼로그"""
        current_config = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'interval': self.interval_idx,
            'theme': self.theme_idx,
            'notification_enabled': self.notification_enabled,
            'alert_keywords': self.alert_keywords,
            'close_to_tray': self.close_to_tray,
            'start_minimized': self.start_minimized,
            'auto_start_enabled': self.auto_start_enabled,
            'notify_on_refresh': self.notify_on_refresh
        }
        
        dlg = SettingsDialog(current_config, self)
        if dlg.exec():
            data = dlg.get_data()
            
            self.client_id = data['id']
            self.client_secret = data['secret']
            self.interval_idx = data['interval']
            
            # 알림 설정 적용
            self.notification_enabled = data.get('notification_enabled', True)
            self.alert_keywords = data.get('alert_keywords', [])
            
            # 트레이 설정 적용
            self.close_to_tray = data.get('close_to_tray', True)
            self.start_minimized = data.get('start_minimized', False)
            self.notify_on_refresh = data.get('notify_on_refresh', False)
            
            # 자동 시작 설정 적용 (Windows 레지스트리)
            new_auto_start = data.get('auto_start_enabled', False)
            if new_auto_start != self.auto_start_enabled:
                if new_auto_start:
                    if StartupManager.enable_startup(self.start_minimized):
                        self.show_success_toast("✓ 윈도우 시작 시 자동 실행이 설정되었습니다.")
                    else:
                        self.show_error_toast("자동 시작 설정에 실패했습니다.")
                else:
                    if StartupManager.disable_startup():
                        self.show_success_toast("✓ 자동 실행이 해제되었습니다.")
                self.auto_start_enabled = new_auto_start
            
            if self.theme_idx != data['theme']:
                self.theme_idx = data['theme']
                self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
                
                for i in range(self.tabs.count()):
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'theme'):
                        widget.theme = self.theme_idx
                        widget.render_html()
            
            self.apply_refresh_interval()
            self.save_config()
            
            self.show_success_toast("✓ 설정이 저장되었습니다.")

    def apply_refresh_interval(self):
        """자동 새로고침 간격 적용 - 카운트다운 지원 버전"""
        try:
            self.timer.stop()
            self._countdown_timer.stop()
            idx = self.interval_idx
            minutes = [10, 30, 60, 180, 360]
            
            if 0 <= idx < len(minutes):
                ms = minutes[idx] * 60 * 1000
                self.timer.setInterval(ms)
                self.timer.start()
                
                # 카운트다운 타이머 시작
                self._next_refresh_seconds = minutes[idx] * 60
                self._countdown_timer.setInterval(1000)  # 1초마다 업데이트
                self._countdown_timer.start()
                
                self.statusBar().showMessage(f"⏰ 자동 새로고침: {minutes[idx]}분 간격")
                logger.info(f"자동 새로고침 설정: {minutes[idx]}분 ({ms}ms)")
            else:
                # 인덱스 5 = "자동 새로고침 안함"
                self.timer.stop()
                self._countdown_timer.stop()
                self._next_refresh_seconds = 0
                self.statusBar().showMessage("⏰ 자동 새로고침 꺼짐")
                logger.info("자동 새로고침 비활성화됨")
        except Exception as e:
            logger.error(f"타이머 설정 오류: {e}")
            traceback.print_exc()


    def closeEvent(self, event):
        """종료 이벤트 - 트레이 최소화 지원 버전"""
        # 초기화 실패 시에도 안전하게 동작하도록 방어적 코딩
        if not hasattr(self, '_system_shutdown'):
            self._system_shutdown = False
        if not hasattr(self, '_force_close'):
            self._force_close = False
        if not hasattr(self, '_user_requested_close'):
            self._user_requested_close = False
        
        # 종료 원인 분석을 위한 호출 스택 로깅
        caller_info = self._get_close_caller_info() if hasattr(self, '_get_close_caller_info') else "Unknown"
        logger.info(f"closeEvent 호출됨 (호출 원인: {caller_info})")
        
        # 시스템 종료거나 강제 종료 요청인 경우 → 실제 종료
        if self._system_shutdown or self._force_close:
            if self._system_shutdown:
                logger.warning("시스템 종료로 인한 프로그램 종료")
            # 실제 종료 처리로 진행
            self._perform_real_close(event)
            return
        
        # 트레이 아이콘이 있고, 트레이로 최소화 설정이 켜져 있으면 → 트레이로 숨기기
        if hasattr(self, 'tray') and self.tray and self.close_to_tray:
            logger.info("창을 트레이로 최소화")
            event.ignore()
            self.hide()
            
            # 처음 트레이로 숨길 때 알림 표시
            if not hasattr(self, '_tray_hide_notified') or not self._tray_hide_notified:
                self.show_tray_notification(
                    APP_NAME,
                    "프로그램이 시스템 트레이에서 계속 실행됩니다.\n트레이 아이콘을 더블클릭하여 창을 열 수 있습니다."
                )
                self._tray_hide_notified = True
            
            # 트레이 툴팁 업데이트
            self.update_tray_tooltip()
            return
        
        # 트레이 최소화가 비활성화된 경우 → 종료 확인 다이얼로그
        if not self._user_requested_close:
            reply = QMessageBox.question(
                self,
                "프로그램 종료",
                "정말로 프로그램을 종료하시겠습니까?\n\n"
                "종료하면 뉴스 자동 새로고침이 중지됩니다.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                logger.info("사용자가 종료를 취소함")
                event.ignore()
                return
            
            self._user_requested_close = True
            logger.info("사용자가 종료 확인함")
        
        # 실제 종료 처리
        self._perform_real_close(event)
    
    def _perform_real_close(self, event):
        """프로그램 실제 종료 처리"""
        logger.info("프로그램 실제 종료 시작...")
        
        try:
            # 모든 타이머 중지 (초기화되지 않았을 수 있으므로 hasattr 체크)
            if hasattr(self, 'timer') and self.timer:
                self.timer.stop()
            if hasattr(self, '_countdown_timer') and self._countdown_timer:
                self._countdown_timer.stop()
            if hasattr(self, '_tab_badge_timer') and self._tab_badge_timer:
                self._tab_badge_timer.stop()
            logger.info("타이머 중지됨")
            
            # 모든 워커 정리 (시그널 disconnect 포함)
            for keyword, (worker, thread) in list(self.workers.items()):
                try:
                    # 시그널 안전하게 disconnect
                    try:
                        worker.finished.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        worker.error.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    try:
                        worker.progress.disconnect()
                    except (TypeError, RuntimeError):
                        pass
                    
                    worker.stop()
                    thread.quit()
                    if not thread.wait(2000):
                        logger.warning(f"스레드 강제 종료: {keyword}")
                        thread.terminate()
                        thread.wait(1000)
                except Exception as e:
                    logger.error(f"워커 종료 오류 ({keyword}): {e}")
            
            self.workers.clear()
            logger.info("워커 정리 완료")
            
            # 설정 저장
            try:
                self.save_config()
                logger.info("설정 저장 완료")
            except Exception as e:
                logger.error(f"설정 저장 오류: {e}")
            
            # DB 종료
            if hasattr(self, 'db') and self.db:
                try:
                    self.db.close()
                    logger.info("DB 연결 종료")
                except Exception as e:
                    logger.error(f"DB 종료 오류: {e}")
            
            # HTTP 세션 종료
            if hasattr(self, 'session') and self.session:
                try:
                    self.session.close()
                    logger.info("HTTP 세션 종료")
                except Exception as e:
                    logger.error(f"세션 종료 오류: {e}")
            
            # 전역 HTTP 세션 정리
            close_shared_session()
            
            logger.info("프로그램 종료 처리 완료")
            
            # 명시적으로 애플리케이션 종료
            QApplication.instance().quit()
            
        except Exception as e:
            logger.error(f"종료 처리 중 오류: {e}")
            traceback.print_exc()
            # 오류가 나더라도 종료 시도
            QApplication.instance().quit()
        
        event.accept()
    
    def _get_close_caller_info(self) -> str:
        """종료 호출 원인을 분석하여 반환"""
        try:
            # 호출 스택 분석
            stack = inspect.stack()
            caller_info = []
            
            for frame_info in stack[2:8]:  # closeEvent 이후 최대 6개 프레임 분석
                func_name = frame_info.function
                filename = os.path.basename(frame_info.filename)
                lineno = frame_info.lineno
                
                # 중요한 호출자 정보만 기록
                if func_name not in ['closeEvent', '_get_close_caller_info']:
                    caller_info.append(f"{func_name}@{filename}:{lineno}")
            
            if not caller_info:
                return "Unknown"
            
            return " <- ".join(caller_info[:3])  # 최대 3개만 표시
        except Exception as e:
            return f"Error analyzing stack: {e}"
    
    # def nativeEvent(self, eventType, message):
    #     """Windows 네이티브 이벤트 처리 - 시스템 종료 감지"""
    #     return super().nativeEvent(eventType, message)
    
    def request_close(self, confirmed: bool = False):
        """트레이 메뉴 등에서 종료 요청 시 사용"""
        if confirmed:
            self._user_requested_close = True
            self._force_close = True
        self.close()


# --- 설정 다이얼로그 ---
class SettingsDialog(QDialog):
    """설정 다이얼로그 (검증 기능 + 도움말 추가)"""
    
    def __init__(self, config: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 및 도움말")
        self.resize(600, 550)
        self.config = config
        # 테마 설정 (부모에서 가져오기)
        self.is_dark = False
        if parent and hasattr(parent, 'theme_idx'):
            self.is_dark = parent.theme_idx == 1
        self.setup_ui()

    def setup_ui(self):
        """테마 적용 UI 설정"""
        layout = QVBoxLayout(self)
        
        # 테마별 색상
        if self.is_dark:
            bg_color = "#1A1A1D"
            text_color = "#FFFFFF"
        else:
            bg_color = "#FFFFFF"
            text_color = "#000000"
        # 탭 위젯 생성
        tab_widget = QTabWidget()
        
        # === 설정 탭 (스크롤 가능) ===
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet(f"QScrollArea {{ background-color: {bg_color}; border: none; }}")
        
        settings_widget = QWidget()
        settings_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        settings_layout = QVBoxLayout(settings_widget)
        
        gp_api = QGroupBox("📡 네이버 API 설정")
        form = QGridLayout()
        
        self.txt_id = QLineEdit(self.config.get('client_id', ''))
        self.txt_id.setPlaceholderText("네이버 개발자센터에서 발급받은 Client ID")
        
        self.txt_sec = QLineEdit(self.config.get('client_secret', ''))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_sec.setPlaceholderText("Client Secret")
        
        self.chk_show_pw = QCheckBox("비밀번호 표시")
        self.chk_show_pw.stateChanged.connect(
            lambda: self.txt_sec.setEchoMode(
                QLineEdit.EchoMode.Normal if self.chk_show_pw.isChecked() 
                else QLineEdit.EchoMode.Password
            )
        )
        
        btn_get_key = QPushButton("🔑 API 키 발급받기")
        btn_get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://developers.naver.com/apps/#/register"))
        )
        
        btn_validate = QPushButton("✓ API 키 검증")
        btn_validate.clicked.connect(self.validate_api_key)
        
        form.addWidget(QLabel("Client ID:"), 0, 0)
        form.addWidget(self.txt_id, 0, 1, 1, 2)
        form.addWidget(QLabel("Client Secret:"), 1, 0)
        form.addWidget(self.txt_sec, 1, 1, 1, 2)
        form.addWidget(self.chk_show_pw, 2, 1)
        form.addWidget(btn_get_key, 3, 0, 1, 2)
        form.addWidget(btn_validate, 3, 2)
        
        gp_api.setLayout(form)
        settings_layout.addWidget(gp_api)
        
        gp_app = QGroupBox("⚙ 일반 설정")
        form2 = QGridLayout()
        
        self.cb_time = NoScrollComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "3시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get('interval', 2)
        if isinstance(idx, int) and 0 <= idx <= 5:
            self.cb_time.setCurrentIndex(idx)
        else:
            self.cb_time.setCurrentIndex(2)
        
        self.cb_theme = NoScrollComboBox()
        self.cb_theme.addItems(["☀ 라이트 모드", "🌙 다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get('theme', 0))
        
        form2.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form2.addWidget(self.cb_time, 0, 1)
        form2.addWidget(QLabel("테마:"), 1, 0)
        form2.addWidget(self.cb_theme, 1, 1)
        
        gp_app.setLayout(form2)
        settings_layout.addWidget(gp_app)
        
        # 시스템 트레이 및 자동 시작 설정
        gp_tray = QGroupBox("🖥️ 시스템 트레이 및 시작 설정")
        tray_layout = QVBoxLayout()
        
        # 트레이로 최소화 옵션
        self.chk_close_to_tray = QCheckBox("X 버튼 클릭 시 트레이로 최소화 (종료하지 않음)")
        self.chk_close_to_tray.setChecked(self.config.get('close_to_tray', True))
        tray_layout.addWidget(self.chk_close_to_tray)
        
        # 자동 시작 옵션 (Windows만)
        self.chk_auto_start = QCheckBox("윈도우 시작 시 자동 실행")
        if StartupManager.is_available():
            self.chk_auto_start.setChecked(StartupManager.is_startup_enabled())
        else:
            self.chk_auto_start.setEnabled(False)
            self.chk_auto_start.setToolTip("Windows에서만 사용 가능합니다.")
        tray_layout.addWidget(self.chk_auto_start)
        
        # 최소화 상태로 시작 옵션
        self.chk_start_minimized = QCheckBox("시작 시 최소화 상태로 시작 (트레이로)")
        self.chk_start_minimized.setChecked(self.config.get('start_minimized', False))
        tray_layout.addWidget(self.chk_start_minimized)
        
        # 자동 새로고침 완료 알림 옵션
        self.chk_notify_on_refresh = QCheckBox("자동 새로고침 완료 시 알림 표시")
        self.chk_notify_on_refresh.setChecked(self.config.get('notify_on_refresh', False))
        tray_layout.addWidget(self.chk_notify_on_refresh)
        
        # 안내 메시지
        tray_info = QLabel("💡 트레이로 최소화하면 백그라운드에서 뉴스를 계속 수집합니다.")
        tray_info.setStyleSheet("color: #666; font-size: 9pt;")
        tray_layout.addWidget(tray_info)
        
        gp_tray.setLayout(tray_layout)
        settings_layout.addWidget(gp_tray)
        
        gp_data = QGroupBox("🗂 데이터 관리")
        vbox = QVBoxLayout()
        
        btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        btn_clean.clicked.connect(self.clean_data)
        
        btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        btn_all.clicked.connect(self.clean_all)
        
        # JSON 설정 백업/복원 버튼
        backup_layout = QHBoxLayout()
        btn_export_settings = QPushButton("📤 설정 내보내기")
        btn_export_settings.clicked.connect(self.export_settings_dialog)
        btn_import_settings = QPushButton("📥 설정 가져오기")
        btn_import_settings.clicked.connect(self.import_settings_dialog)
        backup_layout.addWidget(btn_export_settings)
        backup_layout.addWidget(btn_import_settings)
        
        # 고급 도구 버튼 (툴바에서 이동)
        tools_layout = QHBoxLayout()
        btn_log = QPushButton("📋 로그 보기")
        btn_log.clicked.connect(self.show_log_dialog)
        btn_folder = QPushButton("📁 데이터 폴더")
        btn_folder.clicked.connect(self.open_data_folder)
        btn_groups = QPushButton("🗂 키워드 그룹")
        btn_groups.clicked.connect(self.show_groups_dialog)
        tools_layout.addWidget(btn_log)
        tools_layout.addWidget(btn_folder)
        tools_layout.addWidget(btn_groups)
        
        vbox.addWidget(btn_clean)
        vbox.addWidget(btn_all)
        vbox.addLayout(backup_layout)
        vbox.addLayout(tools_layout)
        gp_data.setLayout(vbox)
        settings_layout.addWidget(gp_data)
        
        # 알림 설정 그룹
        gp_notification = QGroupBox("🔔 알림 설정")
        notif_layout = QVBoxLayout()
        
        self.chk_notification = QCheckBox("데스크톱 알림 활성화 (새 뉴스 도착 시)")
        self.chk_notification.setChecked(self.config.get('notification_enabled', True))
        notif_layout.addWidget(self.chk_notification)
        
        keywords_label = QLabel("알림 키워드 (쉼표로 구분, 최대 10개):")
        notif_layout.addWidget(keywords_label)
        
        self.txt_alert_keywords = QLineEdit()
        current_keywords = self.config.get('alert_keywords', [])
        self.txt_alert_keywords.setText(", ".join(current_keywords) if current_keywords else "")
        self.txt_alert_keywords.setPlaceholderText("예: 긴급, 속보, 단독")
        notif_layout.addWidget(self.txt_alert_keywords)
        
        keywords_info = QLabel("💡 위 키워드가 기사 제목이나 내용에 포함되면 알림이 표시됩니다.")
        keywords_info.setStyleSheet("color: #666; font-size: 9pt;")
        notif_layout.addWidget(keywords_info)
        
        # 알림 소리 설정
        self.chk_sound = QCheckBox("알림 소리 활성화")
        self.chk_sound.setChecked(self.config.get('sound_enabled', True))
        notif_layout.addWidget(self.chk_sound)
        
        # 소리 테스트 버튼
        btn_test_sound = QPushButton("🔊 소리 테스트")
        btn_test_sound.clicked.connect(lambda: NotificationSound.play('success'))
        notif_layout.addWidget(btn_test_sound)
        
        gp_notification.setLayout(notif_layout)
        settings_layout.addWidget(gp_notification)
        
        settings_layout.addStretch()
        
        # === 도움말 탭 ===
        help_widget = QWidget()
        help_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        help_layout = QVBoxLayout(help_widget)
        
        help_browser = QTextBrowser()
        help_browser.setOpenExternalLinks(True)
        help_browser.setStyleSheet(f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}")
        help_browser.setHtml(self.get_help_html())
        help_layout.addWidget(help_browser)
        
        # === 단축키 탭 ===
        shortcuts_widget = QWidget()
        shortcuts_widget.setStyleSheet(f"QWidget {{ background-color: {bg_color}; color: {text_color}; }}")
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        
        shortcuts_browser = QTextBrowser()
        shortcuts_browser.setOpenExternalLinks(False)
        shortcuts_browser.setStyleSheet(f"QTextBrowser {{ background-color: {bg_color}; color: {text_color}; border: none; }}")
        shortcuts_browser.setHtml(self.get_shortcuts_html())
        shortcuts_layout.addWidget(shortcuts_browser)
        
        # 스크롤 영역에 설정 위젯 추가
        scroll_area.setWidget(settings_widget)
        
        # 탭에 추가
        tab_widget.addTab(scroll_area, "⚙ 설정")
        tab_widget.addTab(help_widget, "📖 도움말")
        tab_widget.addTab(shortcuts_widget, "⌨ 단축키")
        
        layout.addWidget(tab_widget)
        
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept_with_validation)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
    
    def get_help_html(self) -> str:
        """도움말 HTML 생성"""
        return """
        <html>
        <head>
            <style>
                body { font-family: '맑은 고딕', sans-serif; padding: 15px; line-height: 1.6; }
                h2 { color: #007AFF; border-bottom: 2px solid #007AFF; padding-bottom: 5px; }
                h3 { color: #333; margin-top: 20px; }
                .section { margin-bottom: 25px; }
                .tip { background-color: #FFF3CD; padding: 10px; border-left: 4px solid #FFC107; margin: 10px 0; }
                .warning { background-color: #F8D7DA; padding: 10px; border-left: 4px solid #DC3545; margin: 10px 0; }
                .info { background-color: #D1ECF1; padding: 10px; border-left: 4px solid #17A2B8; margin: 10px 0; }
                code { background-color: #F5F5F5; padding: 2px 6px; border-radius: 3px; font-family: monospace; }
                ul { margin-left: 20px; }
                li { margin: 5px 0; }
                a { color: #007AFF; text-decoration: none; }
                a:hover { text-decoration: underline; }
            </style>
        </head>
        <body>
            <h2>🎯 빠른 시작 가이드</h2>
            
            <div class="section">
                <h3>1️⃣ API 키 설정</h3>
                <ul>
                    <li><a href="https://developers.naver.com/apps/#/register">네이버 개발자센터</a>에서 애플리케이션 등록</li>
                    <li>검색 API 선택 (뉴스 검색)</li>
                    <li>Client ID와 Client Secret을 설정 탭에 입력</li>
                    <li>"✓ API 키 검증" 버튼으로 정상 작동 확인</li>
                </ul>
                <div class="tip">
                    <strong>💡 팁:</strong> API 키는 안전하게 로컬 파일에만 저장됩니다.
                </div>
            </div>
            
            <div class="section">
                <h3>2️⃣ 탭 추가 및 검색</h3>
                <ul>
                    <li><strong>기본 검색:</strong> <code>주식</code></li>
                    <li><strong>제외 키워드:</strong> <code>주식 -코인</code> (코인 제외)</li>
                    <li><strong>복합 검색:</strong> <code>인공지능 AI -광고 -채용</code></li>
                </ul>
                <div class="info">
                    <strong>ℹ️ 정보:</strong> 제외 키워드는 '-' 기호로 시작하며, 여러 개 사용 가능합니다.
                </div>
            </div>
            
            <div class="section">
                <h3>3️⃣ 기사 관리</h3>
                <ul>
                    <li><strong>읽음 표시:</strong> 제목 클릭 시 자동으로 읽음 처리</li>
                    <li><strong>북마크:</strong> ⭐ 버튼으로 중요 기사 저장</li>
                    <li><strong>메모:</strong> 📝 버튼으로 기사별 메모 작성</li>
                    <li><strong>공유:</strong> 📋 버튼으로 제목+링크 클립보드 복사</li>
                    <li><strong>미리보기:</strong> 제목에 마우스 올리면 내용 미리보기</li>
                </ul>
            </div>
            
            <div class="section">
                <h3>4️⃣ 필터링 및 정렬</h3>
                <ul>
                    <li><strong>실시간 필터:</strong> 검색창에 입력하면 즉시 반영</li>
                    <li><strong>안 읽은 것만:</strong> 읽지 않은 기사만 표시</li>
                    <li><strong>중복 숨김:</strong> 유사한 기사 자동 숨김</li>
                    <li><strong>정렬:</strong> 최신순 / 오래된순 선택</li>
                </ul>
                <div class="tip">
                    <strong>💡 팁:</strong> Ctrl+F를 누르면 필터 검색창에 즉시 포커스됩니다.
                </div>
            </div>
            
            <div class="section">
                <h3>5️⃣ 데이터 관리</h3>
                <ul>
                    <li><strong>내보내기:</strong> Ctrl+S로 현재 탭의 기사를 CSV로 저장</li>
                    <li><strong>통계:</strong> 📊 버튼으로 전체 통계 확인</li>
                    <li><strong>분석:</strong> 📈 버튼으로 언론사별 기사 수 분석</li>
                    <li><strong>오래된 데이터 정리:</strong> 30일 이전 기사 삭제 (북마크 제외)</li>
                </ul>
                <div class="warning">
                    <strong>⚠️ 주의:</strong> 북마크하지 않은 기사는 데이터 정리 시 삭제될 수 있습니다.
                </div>
            </div>
            
            <div class="section">
                <h3>6️⃣ 자동 새로고침</h3>
                <ul>
                    <li>설정에서 간격 선택: 10분 / 30분 / 1시간 / 3시간 / 6시간</li>
                    <li>백그라운드에서 자동으로 새 기사 수집</li>
                    <li>새 기사 발견 시 토스트 알림 표시</li>
                </ul>
            </div>
            
            <div class="section">
                <h3>7️⃣ 문제 해결</h3>
                <ul>
                    <li><strong>검색 결과가 없을 때:</strong> 키워드 철자 확인, 제외 키워드 줄이기</li>
                    <li><strong>API 오류:</strong> 설정에서 "✓ API 키 검증" 실행</li>
                    <li><strong>앱이 느릴 때:</strong> 오래된 데이터 정리 실행</li>
                    <li><strong>중복 기사가 많을 때:</strong> "중복 숨김" 체크박스 활성화</li>
                </ul>
            </div>
            
            <div class="info" style="margin-top: 30px;">
                <strong>📚 더 많은 정보:</strong> 단축키는 "⌨ 단축키" 탭을 참고하세요.
            </div>
        </body>
        </html>
        """
    
    def get_shortcuts_html(self) -> str:
        """단축키 안내 HTML 생성"""
        return """
        <html>
        <head>
            <style>
                body { font-family: '맑은 고딕', sans-serif; padding: 15px; line-height: 1.6; }
                h2 { color: #007AFF; border-bottom: 2px solid #007AFF; padding-bottom: 5px; }
                h3 { color: #333; margin-top: 20px; background-color: #F5F5F5; padding: 8px; border-radius: 5px; }
                .shortcut-table { width: 100%; border-collapse: collapse; margin: 15px 0; }
                .shortcut-table th { background-color: #007AFF; color: white; padding: 10px; text-align: left; }
                .shortcut-table td { padding: 10px; border-bottom: 1px solid #E0E0E0; }
                .shortcut-table tr:hover { background-color: #F8F9FA; }
                .key { background-color: #FFFFFF; border: 2px solid #CCCCCC; border-radius: 5px; padding: 3px 8px; font-family: monospace; font-weight: bold; color: #333; display: inline-block; margin: 0 2px; box-shadow: 0 2px 3px rgba(0,0,0,0.1); }
                .description { color: #555; }
                .category { background-color: #E3F2FD; padding: 5px 10px; border-radius: 3px; font-weight: bold; color: #1976D2; margin-top: 15px; }
            </style>
        </head>
        <body>
            <h2>⌨️ 키보드 단축키 가이드</h2>
            
            <div class="category">🔄 새로고침 & 탭 관리</div>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><span class="key">Ctrl</span> + <span class="key">R</span> 또는 <span class="key">F5</span></td>
                    <td class="description">모든 탭 새로고침</td>
                </tr>
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">T</span></td>
                    <td class="description">새 탭 추가</td>
                </tr>
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">W</span></td>
                    <td class="description">현재 탭 닫기 (북마크 탭은 제외)</td>
                </tr>
                <tr>
                    <td><span class="key">Alt</span> + <span class="key">1</span>~<span class="key">9</span></td>
                    <td class="description">탭 빠른 전환 (1=북마크, 2=첫 번째 탭, ...)</td>
                </tr>
            </table>
            
            <div class="category">🔍 검색 & 필터링</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">F</span></td>
                    <td class="description">필터 검색창에 포커스 (전체 선택)</td>
                </tr>
            </table>
            
            <div class="category">💾 데이터 관리</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">S</span></td>
                    <td class="description">현재 탭 데이터 CSV로 내보내기</td>
                </tr>
            </table>
            
            <div class="category">⚙️ 설정 & 도움말</div>
            <table class="shortcut-table">
                <tr>
                    <td><span class="key">Ctrl</span> + <span class="key">,</span></td>
                    <td class="description">설정 창 열기</td>
                </tr>
                <tr>
                    <td><span class="key">F1</span></td>
                    <td class="description">도움말 열기</td>
                </tr>
            </table>
            
            <h3>🖱️ 마우스 동작</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>제목 클릭</strong></td>
                    <td class="description">기사 열기 (자동으로 읽음 처리)</td>
                </tr>
                <tr>
                    <td><strong>제목 호버</strong></td>
                    <td class="description">기사 내용 미리보기 (툴팁)</td>
                </tr>
                <tr>
                    <td><strong>탭 더블클릭</strong></td>
                    <td class="description">탭 이름(키워드) 변경</td>
                </tr>
                <tr>
                    <td><strong>탭 X 버튼</strong></td>
                    <td class="description">탭 닫기</td>
                </tr>
            </table>
            
            <h3>📋 기사 카드 버튼</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>공유</strong></td>
                    <td class="description">제목과 링크를 클립보드에 복사</td>
                </tr>
                <tr>
                    <td><strong>외부</strong></td>
                    <td class="description">기본 브라우저에서 열기</td>
                </tr>
                <tr>
                    <td><strong>메모 📝</strong></td>
                    <td class="description">기사에 메모 작성/편집 (메모가 있으면 📝 표시)</td>
                </tr>
                <tr>
                    <td><strong>안읽음</strong></td>
                    <td class="description">읽음 → 안읽음으로 변경</td>
                </tr>
                <tr>
                    <td><strong>북마크 / 북마크 해제</strong></td>
                    <td class="description">중요 기사로 표시/해제 (⭐ 북마크 탭에서 모아보기)</td>
                </tr>
            </table>
            
            <h3>💡 유용한 팁</h3>
            <table class="shortcut-table">
                <tr>
                    <td style="width: 35%;"><strong>탭 드래그</strong></td>
                    <td class="description">탭 순서 변경 가능</td>
                </tr>
                <tr>
                    <td><strong>필터 검색</strong></td>
                    <td class="description">입력하는 즉시 실시간으로 필터링 적용</td>
                </tr>
                <tr>
                    <td><strong>중복 숨김</strong></td>
                    <td class="description">유사한 제목의 기사 자동 숨김</td>
                </tr>
                <tr>
                    <td><strong>안 읽은 것만</strong></td>
                    <td class="description">읽지 않은 기사만 표시</td>
                </tr>
            </table>
            
            <div style="margin-top: 30px; padding: 15px; background-color: #E8F5E9; border-radius: 8px; border-left: 4px solid #4CAF50;">
                <strong>🎯 프로 팁:</strong> 단축키를 조합하여 사용하면 훨씬 빠르게 작업할 수 있습니다!<br>
                예: <span class="key">Alt</span>+<span class="key">2</span> (탭 전환) → <span class="key">Ctrl</span>+<span class="key">F</span> (필터 포커스) → 검색어 입력
            </div>
        </body>
        </html>
        """
    
    def validate_api_key(self):
        """API 키 검증"""
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()
        
        valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
        
        if not valid:
            QMessageBox.warning(self, "검증 실패", msg)
            return
        
        try:
            headers = {
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret
            }
            url = "https://openapi.naver.com/v1/search/news.json"
            params = {"query": "테스트", "display": 1}
            
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            
            if resp.status_code == 200:
                QMessageBox.information(
                    self, 
                    "검증 성공", 
                    "✓ API 키가 정상적으로 작동합니다!"
                )
            else:
                error_data = resp.json()
                error_msg = error_data.get('errorMessage', '알 수 없는 오류')
                QMessageBox.warning(
                    self,
                    "검증 실패",
                    f"API 키가 올바르지 않습니다.\n\n오류: {error_msg}"
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "검증 오류",
                f"API 키 검증 중 오류가 발생했습니다:\n\n{str(e)}"
            )
    
    def accept_with_validation(self):
        """검증 후 저장"""
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()
        
        if client_id or client_secret:
            valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
            if not valid:
                reply = QMessageBox.question(
                    self,
                    "API 키 확인",
                    f"{msg}\n\n그래도 저장하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        
        self.accept()

    def clean_data(self):
        """오래된 데이터 정리"""
        reply = QMessageBox.question(
            self,
            "데이터 정리",
            "30일 이전의 기사를 삭제하시겠습니까?\n\n(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            db = DatabaseManager(DB_FILE)
            cnt = db.delete_old_news(30)
            db.close()
            QMessageBox.information(self, "완료", f"✓ {cnt:,}개의 오래된 기사를 삭제했습니다.")

    def clean_all(self):
        """모든 기사 삭제"""
        reply = QMessageBox.warning(
            self,
            "⚠ 경고",
            "정말 모든 기사를 삭제하시겠습니까?\n\n"
            "이 작업은 취소할 수 없습니다.\n"
            "(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            db = DatabaseManager(DB_FILE)
            cnt = db.delete_all_news()
            db.close()
            QMessageBox.information(self, "완료", f"✓ {cnt:,}개의 기사를 삭제했습니다.")
    
    def export_settings_dialog(self):
        """설정 내보내기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'export_settings'):
            self.parent().export_settings()
    
    def import_settings_dialog(self):
        """설정 가져오기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'import_settings'):
            self.parent().import_settings()
    
    def show_log_dialog(self):
        """로그 뷰어 표시 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_log_viewer'):
            self.parent().show_log_viewer()
    
    def open_data_folder(self):
        """데이터 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE))))
    
    def show_groups_dialog(self):
        """키워드 그룹 관리 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_keyword_groups'):
            self.parent().show_keyword_groups()

    def get_data(self) -> Dict:
        """설정 데이터 반환"""
        # 알림 키워드 파싱 (쉼표로 구분, 최대 10개)
        keywords_text = self.txt_alert_keywords.text().strip()
        alert_keywords = []
        if keywords_text:
            alert_keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()][:10]
        
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex(),
            'notification_enabled': self.chk_notification.isChecked(),
            'alert_keywords': alert_keywords,
            'close_to_tray': self.chk_close_to_tray.isChecked(),
            'auto_start_enabled': self.chk_auto_start.isChecked(),
            'start_minimized': self.chk_start_minimized.isChecked(),
            'notify_on_refresh': self.chk_notify_on_refresh.isChecked()
        }
        form = QGridLayout()
        
        self.txt_id = QLineEdit(self.config.get('client_id', ''))
        self.txt_id.setPlaceholderText("네이버 개발자센터에서 발급받은 Client ID")
        
        self.txt_sec = QLineEdit(self.config.get('client_secret', ''))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_sec.setPlaceholderText("Client Secret")
        
        self.chk_show_pw = QCheckBox("비밀번호 표시")
        self.chk_show_pw.stateChanged.connect(
            lambda: self.txt_sec.setEchoMode(
                QLineEdit.EchoMode.Normal if self.chk_show_pw.isChecked() 
                else QLineEdit.EchoMode.Password
            )
        )
        
        btn_get_key = QPushButton("🔑 API 키 발급받기")
        btn_get_key.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://developers.naver.com/apps/#/register"))
        )
        
        btn_validate = QPushButton("✓ API 키 검증")
        btn_validate.clicked.connect(self.validate_api_key)
        
        form.addWidget(QLabel("Client ID:"), 0, 0)
        form.addWidget(self.txt_id, 0, 1, 1, 2)
        form.addWidget(QLabel("Client Secret:"), 1, 0)
        form.addWidget(self.txt_sec, 1, 1, 1, 2)
        form.addWidget(self.chk_show_pw, 2, 1)
        form.addWidget(btn_get_key, 3, 0, 1, 2)
        form.addWidget(btn_validate, 3, 2)
        
        gp_api.setLayout(form)
        settings_layout.addWidget(gp_api)
        
        gp_app = QGroupBox("⚙ 일반 설정")
        form2 = QGridLayout()
        
        self.cb_time = NoScrollComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "3시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get('interval', 2)
        if isinstance(idx, int) and 0 <= idx <= 5:
            self.cb_time.setCurrentIndex(idx)
        else:
            self.cb_time.setCurrentIndex(2)
        
        self.cb_theme = NoScrollComboBox()
        self.cb_theme.addItems(["☀ 라이트 모드", "🌙 다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get('theme', 0))
        
        form2.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form2.addWidget(self.cb_time, 0, 1)
        form2.addWidget(QLabel("테마:"), 1, 0)
        form2.addWidget(self.cb_theme, 1, 1)
        
        gp_app.setLayout(form2)
        settings_layout.addWidget(gp_app)
        
        # 시스템 트레이 및 자동 시작 설정
        gp_tray = QGroupBox("🖥️ 시스템 트레이 및 시작 설정")
        tray_layout = QVBoxLayout()
        
        # 트레이로 최소화 옵션
        self.chk_close_to_tray = QCheckBox("X 버튼 클릭 시 트레이로 최소화 (종료하지 않음)")
        self.chk_close_to_tray.setChecked(self.config.get('close_to_tray', True))
        tray_layout.addWidget(self.chk_close_to_tray)
        
        # 자동 시작 옵션 (Windows만)
        self.chk_auto_start = QCheckBox("윈도우 시작 시 자동 실행")
        if StartupManager.is_available():
            self.chk_auto_start.setChecked(StartupManager.is_startup_enabled())
        else:
            self.chk_auto_start.setEnabled(False)
            self.chk_auto_start.setToolTip("Windows에서만 사용 가능합니다.")
        tray_layout.addWidget(self.chk_auto_start)
        
        # 최소화 상태로 시작 옵션
        self.chk_start_minimized = QCheckBox("시작 시 최소화 상태로 시작 (트레이로)")
        self.chk_start_minimized.setChecked(self.config.get('start_minimized', False))
        tray_layout.addWidget(self.chk_start_minimized)
        
        # 자동 새로고침 완료 알림 옵션
        self.chk_notify_on_refresh = QCheckBox("자동 새로고침 완료 시 알림 표시")
        self.chk_notify_on_refresh.setChecked(self.config.get('notify_on_refresh', False))
        tray_layout.addWidget(self.chk_notify_on_refresh)
        
        # 안내 메시지
        tray_info = QLabel("💡 트레이로 최소화하면 백그라운드에서 뉴스를 계속 수집합니다.")
        tray_info.setStyleSheet("color: #666; font-size: 9pt;")
        tray_layout.addWidget(tray_info)
        
        gp_tray.setLayout(tray_layout)
        settings_layout.addWidget(gp_tray)
        
        gp_data = QGroupBox("🗂 데이터 관리")
        vbox = QVBoxLayout()
        
        btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        btn_clean.clicked.connect(self.clean_data)
        
        btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        btn_all.clicked.connect(self.clean_all)
        
        # JSON 설정 백업/복원 버튼
        backup_layout = QHBoxLayout()
        btn_export_settings = QPushButton("📤 설정 내보내기")
        btn_export_settings.clicked.connect(self.export_settings_dialog)
        btn_import_settings = QPushButton("📥 설정 가져오기")
        btn_import_settings.clicked.connect(self.import_settings_dialog)
        backup_layout.addWidget(btn_export_settings)
        backup_layout.addWidget(btn_import_settings)
        
        # 고급 도구 버튼 (툴바에서 이동)
        tools_layout = QHBoxLayout()
        btn_log = QPushButton("📋 로그 보기")
        btn_log.clicked.connect(self.show_log_dialog)
        btn_folder = QPushButton("📁 데이터 폴더")
        btn_folder.clicked.connect(self.open_data_folder)
        btn_groups = QPushButton("🗂 키워드 그룹")
        btn_groups.clicked.connect(self.show_groups_dialog)
        tools_layout.addWidget(btn_log)
        tools_layout.addWidget(btn_folder)
        tools_layout.addWidget(btn_groups)
        
        vbox.addWidget(btn_clean)
        vbox.addWidget(btn_all)
        vbox.addLayout(backup_layout)
        vbox.addLayout(tools_layout)
        gp_data.setLayout(vbox)
        settings_layout.addWidget(gp_data)
        
        # 알림 설정 그룹
        gp_notification = QGroupBox("🔔 알림 설정")
        notif_layout = QVBoxLayout()
        
        self.chk_notification = QCheckBox("데스크톱 알림 활성화 (새 뉴스 도착 시)")
        self.chk_notification.setChecked(self.config.get('notification_enabled', True))
        notif_layout.addWidget(self.chk_notification)
        
        keywords_label = QLabel("알림 키워드 (쉼표로 구분, 최대 10개):")
        notif_layout.addWidget(keywords_label)
        
        self.txt_alert_keywords = QLineEdit()
        current_keywords = self.config.get('alert_keywords', [])
        self.txt_alert_keywords.setText(", ".join(current_keywords) if current_keywords else "")
        self.txt_alert_keywords.setPlaceholderText("예: 긴급, 속보, 단독")
        notif_layout.addWidget(self.txt_alert_keywords)
        
        keywords_info = QLabel("💡 위 키워드가 기사 제목이나 내용에 포함되면 알림이 표시됩니다.")
        keywords_info.setStyleSheet("color: #666; font-size: 9pt;")
        notif_layout.addWidget(keywords_info)
        
        # 알림 소리 설정
        self.chk_sound = QCheckBox("알림 소리 활성화")
        self.chk_sound.setChecked(self.config.get('sound_enabled', True))
        notif_layout.addWidget(self.chk_sound)
        
        # 소리 테스트 버튼
        btn_test_sound = QPushButton("🔊 소리 테스트")
        btn_test_sound.clicked.connect(lambda: NotificationSound.play('success'))
        notif_layout.addWidget(btn_test_sound)
        
        gp_notification.setLayout(notif_layout)
        settings_layout.addWidget(gp_notification)
        
        settings_layout.addStretch()
        
        # === 도움말 탭 ===
        help_widget = QWidget()
        help_layout = QVBoxLayout(help_widget)
        
        help_browser = QTextBrowser()
        help_browser.setOpenExternalLinks(True)
        help_browser.setHtml(self.get_help_html())
        help_layout.addWidget(help_browser)
        
        # === 단축키 탭 ===
        shortcuts_widget = QWidget()
        shortcuts_layout = QVBoxLayout(shortcuts_widget)
        
        shortcuts_browser = QTextBrowser()
        shortcuts_browser.setOpenExternalLinks(False)
        shortcuts_browser.setHtml(self.get_shortcuts_html())
        shortcuts_layout.addWidget(shortcuts_browser)
        
        # 스크롤 영역에 설정 위젯 추가
        scroll_area.setWidget(settings_widget)
        
        # 탭에 추가
        tab_widget.addTab(scroll_area, "⚙ 설정")
        tab_widget.addTab(help_widget, "📖 도움말")
        tab_widget.addTab(shortcuts_widget, "⌨ 단축키")
        
        layout.addWidget(tab_widget)
        
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept_with_validation)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _get_docs_css(self) -> str:
        """설정/도움말 탭에서 쓰는 HTML 공통 CSS (라이트/다크 대응)."""
        if self.is_dark:
            bg = Colors.DARK_BG
            card = Colors.DARK_CARD_BG
            border = Colors.DARK_BORDER
            text = "#E2E8F0" # Slate 200 (더 밝은 텍스트)
            muted = "#94A3B8"
            primary = Colors.DARK_PRIMARY
            success = Colors.DARK_SUCCESS
            warning = Colors.DARK_WARNING
            danger = Colors.DARK_DANGER
            info = Colors.DARK_INFO
            code_bg = "#334155" # 더 명확한 코드 배경
        else:
            bg = "#F8FAFC"
            card = "#FFFFFF"
            border = "#E2E8F0"
            text = "#0F172A" # Slate 900 (더 진한 텍스트)
            muted = "#475569" # Slate 600 (덜 흐릿한 Muted)
            primary = Colors.LIGHT_PRIMARY
            success = Colors.LIGHT_SUCCESS
            warning = Colors.LIGHT_WARNING
            danger = Colors.LIGHT_DANGER
            info = Colors.LIGHT_INFO
            code_bg = "#F1F5F9"

        return f"""
        <style>
            @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
            
            body {{
                font-family: 'Pretendard', 'Malgun Gothic', -apple-system, sans-serif;
                padding: 24px;
                margin: 0;
                line-height: 1.7;
                background: {bg};
                color: {text};
            }}
            h2 {{
                margin: 0 0 16px 0;
                font-size: 18pt;
                font-weight: 700;
                color: {primary};
                border-bottom: 2px solid {border};
                padding-bottom: 8px;
            }}
            h3 {{
                margin: 24px 0 12px 0;
                font-size: 13pt;
                font-weight: 600;
                color: {text};
            }}
            .card {{
                background: {card};
                border: 1px solid {border};
                border-radius: 12px;
                padding: 20px;
                margin: 16px 0;
                box-shadow: 0 1px 3px rgba(0,0,0,0.05); /* 미세한 그림자 */
            }}
            .muted {{ color: {muted}; font-size: 0.95em; }}
            a {{ color: {primary}; text-decoration: none; font-weight: 600; }}
            a:hover {{ text-decoration: underline; }}
            code {{
                background: {code_bg};
                padding: 3px 6px;
                border-radius: 6px;
                font-family: Consolas, 'Monaco', monospace;
                font-size: 0.9em;
                color: {primary};
            }}
            ul {{ margin: 8px 0 0 20px; padding: 0; }}
            li {{ margin: 6px 0; color: {text}; }}
            .callout {{
                border-left: 4px solid {primary};
                background: {card};
                border: 1px solid {border};
                border-left-width: 4px; /* 중복 보장이지만 명시 */
                border-radius: 8px;
                padding: 12px 16px;
                margin-top: 16px;
            }}
            .callout.success {{ border-left-color: {success}; }}
            .callout.warning {{ border-left-color: {warning}; }}
            .callout.danger {{ border-left-color: {danger}; }}
            .callout.info {{ border-left-color: {info}; }}
            
            table {{ width: 100%; border-collapse: separate; border-spacing: 0; margin-top: 12px; border: 1px solid {border}; border-radius: 8px; overflow: hidden; }}
            th, td {{ padding: 12px 16px; border-bottom: 1px solid {border}; text-align: left; }}
            th {{ background-color: {code_bg}; color: {text}; font-weight: 700; border-bottom: 1px solid {border}; }}
            tr:last-child td {{ border-bottom: none; }}
            
            .key {{
                display: inline-block;
                padding: 4px 8px;
                border-radius: 6px;
                border: 1px solid {border};
                background: {code_bg};
                font-family: Consolas, 'Monaco', monospace;
                font-weight: 700;
                font-size: 0.85em;
                box-shadow: 0 1px 0 {border};
            }}
        </style>
        """
    
    def get_help_html(self) -> str:
        """도움말 HTML 생성"""
        css = self._get_docs_css()
        return f"""
        <html>
        <head>{css}</head>
        <body>
            <h2>사용 가이드</h2>

            <div class='card'>
                <h3>1) API 키 설정</h3>
                <ul>
                    <li><a href='https://developers.naver.com/apps/#/register'>네이버 개발자센터</a>에서 애플리케이션 등록</li>
                    <li>검색 API(뉴스) 권한 선택</li>
                    <li>설정 탭에 <code>Client ID</code> / <code>Client Secret</code> 입력</li>
                    <li><span class='muted'>"✓ API 키 검증"</span> 버튼으로 정상 동작 확인</li>
                </ul>
                <div class='callout info'>API 키는 로컬 설정 파일에만 저장됩니다.</div>
            </div>

            <div class='card'>
                <h3>2) 탭 추가 / 검색</h3>
                <ul>
                    <li>기본: <code>주식</code></li>
                    <li>제외어: <code>주식 -코인</code></li>
                    <li>복합: <code>인공지능 AI -광고 -채용</code></li>
                </ul>
            </div>

            <div class='card'>
                <h3>3) 기사 관리</h3>
                <ul>
                    <li>제목 클릭: 기본 브라우저로 열고 자동으로 읽음 처리</li>
                    <li>기사 카드: 공유 / 외부 / 메모 / 북마크</li>
                    <li>제목 호버: 내용 미리보기 툴팁</li>
                </ul>
            </div>

            <div class='card'>
                <h3>4) 필터 & 정렬</h3>
                <ul>
                    <li>검색창: 입력 즉시 필터링</li>
                    <li>안 읽은 것만 / 중복 숨김 / 기간 필터</li>
                    <li>정렬: 최신순 / 오래된순</li>
                </ul>
                <div class='callout success'>팁: <span class='key'>Ctrl</span>+<span class='key'>F</span>로 필터 입력란에 바로 포커스합니다.</div>
            </div>
        </body>
        </html>
        """
    
    def get_shortcuts_html(self) -> str:
        """단축키 안내 HTML 생성"""
        css = self._get_docs_css()
        return f"""
        <html>
        <head>{css}</head>
        <body>
            <h2>단축키</h2>

            <div class='card'>
                <h3>앱 공통</h3>
                <table>
                    <tr><th style='width: 38%;'>키</th><th>동작</th></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>R</span> / <span class='key'>F5</span></td><td>모든 탭 새로고침</td></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>T</span></td><td>새 탭 추가</td></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>W</span></td><td>현재 탭 닫기</td></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>S</span></td><td>CSV 내보내기</td></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>,</span></td><td>설정 열기</td></tr>
                    <tr><td><span class='key'>F1</span></td><td>도움말 열기</td></tr>
                    <tr><td><span class='key'>Alt</span>+<span class='key'>1</span>~<span class='key'>9</span></td><td>탭 바로가기</td></tr>
                    <tr><td><span class='key'>Ctrl</span>+<span class='key'>F</span></td><td>현재 탭 필터 포커스</td></tr>
                </table>
            </div>

            <div class='card'>
                <h3>마우스</h3>
                <ul>
                    <li>제목 클릭: 기사 열기(읽음 처리)</li>
                    <li>제목 호버: 미리보기</li>
                    <li>탭 더블클릭: 탭 이름 변경</li>
                    <li>탭 우클릭: 컨텍스트 메뉴</li>
                </ul>
            </div>
        </body>
        </html>
        """
    
    def validate_api_key(self):
        """API 키 검증"""
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()
        
        valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
        
        if not valid:
            QMessageBox.warning(self, "검증 실패", msg)
            return
        
        try:
            headers = {
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret
            }
            url = "https://openapi.naver.com/v1/search/news.json"
            params = {"query": "테스트", "display": 1}
            
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            
            if resp.status_code == 200:
                QMessageBox.information(
                    self, 
                    "검증 성공", 
                    "✓ API 키가 정상적으로 작동합니다!"
                )
            else:
                error_data = resp.json()
                error_msg = error_data.get('errorMessage', '알 수 없는 오류')
                QMessageBox.warning(
                    self,
                    "검증 실패",
                    f"API 키가 올바르지 않습니다.\n\n오류: {error_msg}"
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "검증 오류",
                f"API 키 검증 중 오류가 발생했습니다:\n\n{str(e)}"
            )
    
    def accept_with_validation(self):
        """검증 후 저장"""
        client_id = self.txt_id.text().strip()
        client_secret = self.txt_sec.text().strip()
        
        if client_id or client_secret:
            valid, msg = ValidationUtils.validate_api_credentials(client_id, client_secret)
            if not valid:
                reply = QMessageBox.question(
                    self,
                    "API 키 확인",
                    f"{msg}\n\n그래도 저장하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        
        self.accept()

    def clean_data(self):
        """오래된 데이터 정리"""
        reply = QMessageBox.question(
            self,
            "데이터 정리",
            "30일 이전의 기사를 삭제하시겠습니까?\n\n(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            db = DatabaseManager(DB_FILE)
            cnt = db.delete_old_news(30)
            db.close()
            QMessageBox.information(self, "완료", f"✓ {cnt:,}개의 오래된 기사를 삭제했습니다.")

    def clean_all(self):
        """모든 기사 삭제"""
        reply = QMessageBox.warning(
            self,
            "⚠ 경고",
            "정말 모든 기사를 삭제하시겠습니까?\n\n"
            "이 작업은 취소할 수 없습니다.\n"
            "(북마크된 기사는 삭제되지 않습니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            db = DatabaseManager(DB_FILE)
            cnt = db.delete_all_news()
            db.close()
            QMessageBox.information(self, "완료", f"✓ {cnt:,}개의 기사를 삭제했습니다.")
    
    def export_settings_dialog(self):
        """설정 내보내기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'export_settings'):
            self.parent().export_settings()
    
    def import_settings_dialog(self):
        """설정 가져오기 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'import_settings'):
            self.parent().import_settings()
    
    def show_log_dialog(self):
        """로그 뷰어 표시 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_log_viewer'):
            self.parent().show_log_viewer()
    
    def open_data_folder(self):
        """데이터 폴더 열기"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE))))
    
    def show_groups_dialog(self):
        """키워드 그룹 관리 (부모 호출)"""
        if self.parent() and hasattr(self.parent(), 'show_keyword_groups'):
            self.parent().show_keyword_groups()

    def get_data(self) -> Dict:
        """설정 데이터 반환"""
        # 알림 키워드 파싱 (쉼표로 구분, 최대 10개)
        keywords_text = self.txt_alert_keywords.text().strip()
        alert_keywords = []
        if keywords_text:
            alert_keywords = [kw.strip() for kw in keywords_text.split(',') if kw.strip()][:10]
        
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex(),
            'notification_enabled': self.chk_notification.isChecked(),
            'alert_keywords': alert_keywords,
            'close_to_tray': self.chk_close_to_tray.isChecked(),
            'auto_start_enabled': self.chk_auto_start.isChecked(),
            'start_minimized': self.chk_start_minimized.isChecked(),
            'notify_on_refresh': self.chk_notify_on_refresh.isChecked()
        }

# --- 메인 실행 ---
def main():
    """메인 함수 - 안정성 개선 버전 (종료 원인 추적 포함)"""
    # 전역 예외 처리기
    def exception_hook(exc_type, exc_value, exc_tb):
        logger.critical("처리되지 않은 예외 발생:")
        logger.critical("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        # 크래시 로그 파일에도 저장
        try:
            with open("crash_log.txt", "a", encoding="utf-8") as f:
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
            with open("crash_log.txt", "a", encoding="utf-8") as f:
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
            with open("crash_log.txt", "a", encoding="utf-8") as f:
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
    
    try:
        logger.info(f"{APP_NAME} v{VERSION} 시작 중...")
        
        app = QApplication(sys.argv)
        # app.setStyle("Fusion")
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        font = app.font()
        font.setFamily("맑은 고딕")
        app.setFont(font)
        
        window = MainApp()
        window.show()
        
        logger.info(f"{APP_NAME} v{VERSION} 시작됨")
        
        sys.exit(app.exec())
        
    except Exception as e:
        error_msg = f"애플리케이션 시작 오류: {e}"
        logger.error(error_msg)
        traceback.print_exc()
        
        # 크래시 로그 파일에 기록
        try:
            with open("crash_log.txt", "a", encoding="utf-8") as f:
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
            QMessageBox.critical(None, "시작 오류", f"프로그램을 시작할 수 없습니다:\n\n{str(e)}\n\n자세한 내용은 crash_log.txt를 확인하세요.")
        except:
            pass
        
        sys.exit(1)

if __name__ == "__main__":
    main()
