# --- 필요 라이브러리 설치 ---
# pip install PyQt6 requests
import sys
import json
import traceback
import requests
import os
import html
import urllib.parse
import sqlite3
import threading
import csv
import hashlib
import re
import time  # 추가: 안전한 sleep 사용
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from collections import deque
from typing import List, Dict, Optional, Tuple
from queue import Queue

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextBrowser, QLabel, QMessageBox,
    QTabWidget, QInputDialog, QComboBox, QFileDialog, QSystemTrayIcon,
    QMenu, QStyle, QTabBar, QDialog, QDialogButtonBox, QGroupBox,
    QGridLayout, QProgressBar, QCheckBox, QTextEdit, QListWidget,
    QGraphicsOpacityEffect, QToolTip
)
from PyQt6.QtCore import (
    QThread, QObject, pyqtSignal, Qt, QTimer, QUrl, 
    QPropertyAnimation, QEasingCurve
)
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut, QIcon

# --- 상수 및 설정 ---
CONFIG_FILE = "news_scraper_config.json"
DB_FILE = "news_database.db"
ICON_FILE = "news_icon.ico"  # Windows용 아이콘
ICON_PNG = "news_icon.png"   # 범용 아이콘
APP_NAME = "뉴스 스크래퍼 Pro"
VERSION = "26.0"  # 디버깅 버전

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
        """텍스트에서 키워드 하이라이팅 (성능 개선)"""
        if not keyword:
            return html.escape(text)
        
        escaped_text = html.escape(text)
        escaped_keyword = html.escape(keyword)
        
        pattern = re.compile(f'({re.escape(escaped_keyword)})', re.IGNORECASE)
        highlighted = pattern.sub(r"<span class='highlight'>\1</span>", escaped_text)
        
        return highlighted

# --- 커스텀 위젯: 토스트 메시지 큐 시스템 ---
class ToastQueue:
    """토스트 메시지 큐 관리"""
    def __init__(self, parent):
        self.parent = parent
        self.queue = deque()
        self.current_toast = None
        self.y_offset = 100
        
    def add(self, message: str):
        """토스트 메시지 추가"""
        self.queue.append(message)
        if self.current_toast is None:
            self._show_next()
    
    def _show_next(self):
        """다음 토스트 표시"""
        if not self.queue:
            self.current_toast = None
            return
        
        message = self.queue.popleft()
        self.current_toast = ToastMessage(self.parent, message, self)
        
    def on_toast_finished(self):
        """토스트 종료 시 호출"""
        self.current_toast = None
        self._show_next()

class ToastMessage(QLabel):
    """화면에 잠시 나타났다 사라지는 알림 메시지"""
    def __init__(self, parent, message, queue):
        super().__init__(message, parent)
        self.queue = queue
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 220);
            color: #FFFFFF;
            padding: 12px 24px;
            border-radius: 20px;
            font-family: '맑은 고딕';
            font-size: 14px;
            font-weight: bold;
        """)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        
        self.update_position()
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_in.setDuration(300)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)
        self.anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_in.start()
        
        self.show()
        
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(2500)
    
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
        self.anim_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_out.setDuration(500)
        self.anim_out.setStartValue(1.0)
        self.anim_out.setEndValue(0.0)
        self.anim_out.finished.connect(self.on_finished)
        self.anim_out.start()
    
    def on_finished(self):
        """애니메이션 종료 후 정리"""
        self.close()
        self.deleteLater()
        if self.queue:
            self.queue.on_toast_finished()

# --- 커스텀 브라우저 (미리보기 기능) ---
class NewsBrowser(QTextBrowser):
    """링크 클릭 시 페이지 이동 차단, 호버 시 미리보기 표시"""
    
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


# --- 스타일시트 ---
class AppStyle:
    LIGHT = """
        QMainWindow, QDialog { background-color: #F0F2F5; }
        QGroupBox { font-family: '맑은 고딕'; font-weight: bold; margin-top: 10px; }
        QLabel, QDialog QLabel { font-family: '맑은 고딕'; font-size: 10pt; color: #000000; }
        QPushButton { font-family: '맑은 고딕'; font-size: 10pt; background-color: #FFFFFF; color: #333; padding: 8px 12px; border-radius: 6px; border: 1px solid #DCDCDC; }
        QPushButton:hover { background-color: #E8E8E8; }
        QPushButton:disabled { background-color: #F5F5F5; color: #999; }
        QPushButton#AddTab { font-weight: bold; background-color: #007AFF; color: white; border: none; }
        QPushButton#AddTab:hover { background-color: #0056b3; }
        QComboBox { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px; border-radius: 6px; border: 1px solid #ccc; background-color: #FFFFFF; color: #000000; }
        QComboBox::drop-down { border: none; }
        QComboBox QAbstractItemView { background-color: #FFFFFF; color: #000000; selection-background-color: #007AFF; selection-color: #FFFFFF; border: 1px solid #CCCCCC; }
        QComboBox QAbstractItemView::item { padding: 5px; }
        QComboBox QAbstractItemView::item:hover { background-color: #E8F4FF; }
        QTextBrowser, QTextEdit, QListWidget { font-family: '맑은 고딕'; background-color: #FFFFFF; border: 1px solid #DCDCDC; border-radius: 8px; color: #000000; }
        QListWidget::item:selected { background-color: #007AFF; color: #FFFFFF; }
        QTabWidget::pane { border-top: 1px solid #DCDCDC; }
        QTabBar::tab { font-family: '맑은 고딕'; font-size: 10pt; color: #333; padding: 10px 15px; border: 1px solid transparent; border-bottom: none; background-color: transparent; }
        QTabBar::tab:selected { background-color: #FFFFFF; border-color: #DCDCDC; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #000; font-weight: bold; }
        QTabBar::tab:!selected { color: #777; }
        QTabBar::tab:!selected:hover { color: #333; }
        QLineEdit { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px 8px; border-radius: 6px; border: 1px solid #ccc; background-color: #FFFFFF; color: #000000; }
        QLineEdit#FilterActive { border: 2px solid #007AFF; background-color: #F0F8FF; }
        QLineEdit::placeholder { color: #999999; }
        QProgressBar { border: 1px solid #DCDCDC; border-radius: 3px; text-align: center; background-color: #FFFFFF; color: #000000; }
        QProgressBar::chunk { background-color: #007AFF; }
        QCheckBox { font-family: '맑은 고딕'; font-size: 10pt; color: #000000; }
        QCheckBox::indicator { width: 18px; height: 18px; }
        QCheckBox::indicator:unchecked { border: 2px solid #CCCCCC; background-color: #FFFFFF; border-radius: 3px; }
        QCheckBox::indicator:checked { border: 2px solid #007AFF; background-color: #007AFF; border-radius: 3px; }
    """
    
    DARK = """
        QMainWindow, QDialog { background-color: #2E2E2E; }
        QGroupBox { font-family: '맑은 고딕'; color: #E0E0E0; font-weight: bold; margin-top: 10px; }
        QLabel, QDialog QLabel { font-family: '맑은 고딕'; font-size: 10pt; color: #E0E0E0; }
        QPushButton { font-family: '맑은 고딕'; font-size: 10pt; background-color: #4A4A4A; color: #E0E0E0; padding: 8px 12px; border-radius: 6px; border: 1px solid #606060; }
        QPushButton:hover { background-color: #5A5A5A; }
        QPushButton:disabled { background-color: #3A3A3A; color: #666; }
        QPushButton#AddTab { font-weight: bold; background-color: #0A84FF; color: white; border: none; }
        QPushButton#AddTab:hover { background-color: #0060C0; }
        QComboBox { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px; border-radius: 6px; border: 1px solid #606060; background-color: #4A4A4A; color: #E0E0E0; }
        QComboBox::drop-down { border: none; }
        QComboBox QAbstractItemView { background-color: #FFFFFF; color: #000000; selection-background-color: #0A84FF; selection-color: #FFFFFF; border: 1px solid #CCCCCC; }
        QComboBox QAbstractItemView::item { padding: 5px; }
        QComboBox QAbstractItemView::item:hover { background-color: #E8F4FF; }
        QTextBrowser, QTextEdit, QListWidget { font-family: '맑은 고딕'; background-color: #3C3C3C; border: 1px solid #606060; border-radius: 8px; color: #E0E0E0; }
        QListWidget::item:selected { background-color: #0A84FF; color: #FFFFFF; }
        QTabWidget::pane { border-top: 1px solid #606060; }
        QTabBar::tab { font-family: '맑은 고딕'; font-size: 10pt; color: #CCCCCC; padding: 10px 15px; border: 1px solid transparent; border-bottom: none; background-color: transparent; }
        QTabBar::tab:selected { background-color: #3C3C3C; border-color: #606060; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #FFFFFF; font-weight: bold; }
        QTabBar::tab:!selected { color: #AAAAAA; }
        QTabBar::tab:!selected:hover { color: #FFFFFF; }
        QLineEdit { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px 8px; border-radius: 6px; border: 1px solid #606060; background-color: #4A4A4A; color: #E0E0E0; }
        QLineEdit#FilterActive { border: 2px solid #0A84FF; background-color: #2A3A4A; }
        QLineEdit::placeholder { color: #888888; }
        QProgressBar { border: 1px solid #606060; border-radius: 3px; text-align: center; background-color: #3C3C3C; color: #E0E0E0; }
        QProgressBar::chunk { background-color: #0A84FF; }
        QCheckBox { font-family: '맑은 고딕'; font-size: 10pt; color: #E0E0E0; }
        QCheckBox::indicator { width: 18px; height: 18px; }
        QCheckBox::indicator:unchecked { border: 2px solid #606060; background-color: #3C3C3C; border-radius: 3px; }
        QCheckBox::indicator:checked { border: 2px solid #0A84FF; background-color: #0A84FF; border-radius: 3px; }
    """

    HTML_TEMPLATE = """
    <style>
        body {{ font-family: '맑은 고딕', sans-serif; margin: 5px; color: {text_color}; }}
        a {{ text-decoration: none; color: {link_color}; transition: color 0.2s; }}
        a:hover {{ color: {link_hover}; text-decoration: underline; }}
        .news-item {{ 
            border: 1px solid {border_color}; 
            border-radius: 10px; 
            padding: 20px; 
            margin-bottom: 20px; 
            background-color: {bg_color}; 
            transition: box-shadow 0.2s;
        }}
        .news-item:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.15); }}
        .news-item.read {{ background-color: {read_bg}; opacity: 0.7; }}
        .news-item.duplicate {{ border-left: 4px solid #FFA500; }}
        .title-link {{ font-size: 13pt; font-weight: bold; color: {title_color}; line-height: 1.5; display: block; margin-bottom: 8px; }}
        .meta-info {{ font-size: 9.5pt; color: {meta_color}; margin-top: 8px; border-bottom: 1px solid {border_color}; padding-bottom: 8px; margin-bottom: 12px; }}
        .description {{ margin-top: 0px; line-height: 1.8; color: {desc_color}; font-size: 10.5pt; }}
        .actions {{ float: right; font-size: 9.5pt; white-space: nowrap; }}
        .actions a {{ margin-left: 12px; }}
        .empty-state {{ text-align: center; padding: 60px 20px; color: {meta_color}; font-size: 11pt; }}
        .highlight {{ background-color: #FCD34D; color: #000000; padding: 2px 4px; border-radius: 3px; font-weight: bold; }}
        .keyword-tag {{ display: inline-block; background-color: {tag_bg}; color: {tag_color}; padding: 2px 8px; border-radius: 10px; font-size: 8.5pt; margin-right: 5px; }}
        .duplicate-badge {{ display: inline-block; background-color: #FFA500; color: #FFFFFF; padding: 2px 8px; border-radius: 10px; font-size: 8.5pt; margin-right: 5px; }}
    </style>
    """


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
        self.init_db()
        
        for _ in range(max_connections):
            conn = self._create_connection()
            self.connection_pool.put(conn)
    
    def _create_connection(self):
        """새 DB 연결 생성"""
        conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA busy_timeout=30000")  # 추가: 30초 busy timeout
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_connection(self, timeout: float = 10.0):
        """연결 풀에서 연결 가져오기 (타임아웃 추가)"""
        if self._closed:
            return self._create_connection()
        try:
            conn = self.connection_pool.get(timeout=timeout)
            with self._lock:
                self._active_connections += 1
            return conn
        except Exception as e:
            print(f"⚠️ DB 연결 획득 실패 (timeout={timeout}s): {e}")
            print(f"   활성 연결 수: {self._active_connections}/{self.max_connections}")
            # 비상 연결 생성
            return self._create_connection()
    
    def return_connection(self, conn):
        """연결 풀에 연결 반환"""
        if conn is None:
            return
        if self._closed:
            try:
                conn.close()
            except:
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
            print(f"⚠️ DB 연결 반환 실패: {e}")
            try:
                conn.close()
            except:
                pass
    
    def init_db(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.db_file)
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
            try:
                conn.execute("ALTER TABLE news ADD COLUMN notes TEXT")
            except sqlite3.OperationalError:
                pass
            
            try:
                conn.execute("ALTER TABLE news ADD COLUMN title_hash TEXT")
                columns_added = True
            except sqlite3.OperationalError:
                pass
            
            try:
                conn.execute("ALTER TABLE news ADD COLUMN is_duplicate INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            
            # 컬럼 추가 후 인덱스 생성
            indexes = [
                "CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)",
                "CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)",
                "CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)",
                "CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)",
                "CREATE INDEX IF NOT EXISTS idx_title_hash ON news(title_hash)",
                "CREATE INDEX IF NOT EXISTS idx_duplicate ON news(is_duplicate)"
            ]
            for idx in indexes:
                try:
                    conn.execute(idx)
                except sqlite3.OperationalError as e:
                    print(f"Index creation skipped: {e}")
            
            # 기존 데이터의 title_hash 업데이트 (마이그레이션)
            if columns_added:
                cursor = conn.execute("SELECT link, title FROM news WHERE title_hash IS NULL LIMIT 1000")
                rows = cursor.fetchall()
                if rows:
                    print(f"🔄 기존 데이터 마이그레이션 중... ({len(rows)}개)")
                    for link, title in rows:
                        if title:
                            title_hash = self._calculate_title_hash(title)
                            conn.execute("UPDATE news SET title_hash = ? WHERE link = ?", (title_hash, link))
                    print("✅ 마이그레이션 완료")
        
        conn.close()
    
    def _calculate_title_hash(self, title: str) -> str:
        """제목의 해시 계산 (중복 감지용)"""
        normalized = re.sub(r'\s+', '', title.lower())
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def upsert_news(self, items: List[Dict], keyword: str) -> Tuple[int, int]:
        """뉴스 삽입 및 중복 감지"""
        if not items:
            return 0, 0
        
        conn = self.get_connection()
        added_count = 0
        duplicate_count = 0
        
        try:
            with conn:
                for item in items:
                    ts = 0.0
                    try:
                        ts = parsedate_to_datetime(item['pubDate']).timestamp()
                    except:
                        pass
                    
                    title_hash = self._calculate_title_hash(item['title'])
                    
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM news WHERE title_hash = ? AND keyword = ?",
                        (title_hash, keyword)
                    )
                    is_duplicate = cursor.fetchone()[0] > 0
                    
                    try:
                        cur = conn.execute("""
                            INSERT OR IGNORE INTO news 
                            (link, keyword, title, description, pubDate, publisher, pubDate_ts, title_hash, is_duplicate)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (item['link'], keyword, item['title'], item['description'], 
                              item['pubDate'], item['publisher'], ts, title_hash, 1 if is_duplicate else 0))
                        
                        if cur.rowcount > 0:
                            if is_duplicate:
                                duplicate_count += 1
                            else:
                                added_count += 1
                    except sqlite3.Error as e:
                        print(f"DB Insert Error: {e}")
                        continue
            
            return added_count, duplicate_count
        
        finally:
            self.return_connection(conn)
    
    def fetch_news(self, keyword: str, filter_txt: str = "", sort_mode: str = "최신순", 
                   only_bookmark: bool = False, only_unread: bool = False,
                   hide_duplicates: bool = False) -> List[Dict]:
        """뉴스 조회 - 안전한 버전"""
        conn = None
        try:
            conn = self.get_connection(timeout=5.0)
            
            query = "SELECT * FROM news WHERE 1=1"
            params = []

            if only_bookmark:
                query += " AND is_bookmarked = 1"
            else:
                query += " AND keyword = ?"
                params.append(keyword)

            if only_unread:
                query += " AND is_read = 0"
            
            if hide_duplicates:
                query += " AND is_duplicate = 0"

            if filter_txt:
                query += " AND (title LIKE ? OR description LIKE ?)"
                params.extend([f"%{filter_txt}%", f"%{filter_txt}%"])
            
            order = "DESC" if sort_mode == "최신순" else "ASC"
            query += f" ORDER BY pubDate_ts {order} LIMIT 1000"

            cursor = conn.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        
        except sqlite3.Error as e:
            print(f"DB Fetch Error: {e}")
            traceback.print_exc()
            return []
        except Exception as e:
            print(f"Unexpected Fetch Error: {e}")
            traceback.print_exc()
            return []
        finally:
            if conn:
                self.return_connection(conn)
    
    def get_counts(self, keyword: str) -> int:
        """특정 키워드 뉴스 개수"""
        conn = self.get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news WHERE keyword=?", (keyword,))
            return cursor.fetchone()[0] or 0
        except:
            return 0
        finally:
            self.return_connection(conn)
    
    def get_unread_count(self, keyword: str) -> int:
        """안 읽은 뉴스 개수"""
        conn = self.get_connection()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM news WHERE keyword=? AND is_read=0", 
                (keyword,)
            )
            return cursor.fetchone()[0] or 0
        except:
            return 0
        finally:
            self.return_connection(conn)
    
    def update_status(self, link: str, field: str, value) -> bool:
        """뉴스 상태 업데이트"""
        conn = self.get_connection()
        try:
            with conn:
                conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return True
        except sqlite3.Error as e:
            print(f"DB Update Error: {e}")
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
        except:
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
        except:
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
        except:
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
            stats['duplicates'] = conn.execute("SELECT COUNT(*) FROM news WHERE is_duplicate=1").fetchone()[0]
            return stats
        except:
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
                    WHERE keyword=? 
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
        except:
            return []
        finally:
            self.return_connection(conn)
    
    def close(self):
        """모든 연결 종료 - 안전한 버전"""
        self._closed = True
        closed_count = 0
        try:
            while not self.connection_pool.empty():
                try:
                    conn = self.connection_pool.get_nowait()
                    conn.close()
                    closed_count += 1
                except:
                    break
            print(f"✅ DB 연결 {closed_count}개 정상 종료")
        except Exception as e:
            print(f"⚠️ DB 종료 중 오류: {e}")


# --- 개선된 API 워커 (재시도 로직) ---
class ApiWorker(QObject):
    """API 호출 워커 (재시도 로직 포함) - 안전한 버전"""
    
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, client_id: str, client_secret: str, keyword: str, 
                 exclude_words: List[str], start_idx: int = 1, max_retries: int = 3):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.keyword = keyword
        self.exclude_words = exclude_words
        self.start = start_idx
        self._is_running = True  # 변경: private 변수
        self._lock = threading.Lock()  # 추가: 스레드 안전성
        self.max_retries = max_retries

    @property
    def is_running(self):
        with self._lock:
            return self._is_running
    
    @is_running.setter
    def is_running(self, value):
        with self._lock:
            self._is_running = value

    def run(self):
        """API 호출 실행 - 안전한 버전"""
        if not self.is_running:
            return
        
        for attempt in range(self.max_retries):
            if not self.is_running:
                return
            
            try:
                self.progress.emit(f"'{self.keyword}' 검색 중... (시도 {attempt + 1}/{self.max_retries})")
                
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
                
                resp = requests.get(url, headers=headers, params=params, timeout=15)
                
                if resp.status_code == 429:
                    if attempt < self.max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        self.progress.emit(f"요청 제한 초과. {wait_time}초 후 재시도...")
                        # time.sleep 사용 (안전)
                        for _ in range(wait_time):
                            if not self.is_running:
                                return
                            time.sleep(1)
                        continue
                    else:
                        self.error.emit("API 요청 제한 초과. 잠시 후 다시 시도해주세요.")
                        return
                
                if resp.status_code != 200:
                    try:
                        error_data = resp.json()
                        error_msg = error_data.get('errorMessage', '알 수 없는 오류')
                        error_code = error_data.get('errorCode', '')
                    except:
                        error_msg = f"HTTP {resp.status_code}"
                        error_code = ""
                    self.error.emit(f"API 오류 {resp.status_code} ({error_code}): {error_msg}")
                    return
                
                data = resp.json()
                items = []
                filtered_count = 0
                
                for item in data.get('items', []):
                    if not self.is_running:
                        break
                    
                    try:
                        title = html.unescape(item.get('title', '')).replace('<b>', '').replace('</b>', '')
                        desc = html.unescape(item.get('description', '')).replace('<b>', '').replace('</b>', '')
                        
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
                        print(f"아이템 처리 오류: {item_error}")
                        continue
                
                result = {
                    'items': items,
                    'total': data.get('total', 0),
                    'filtered': filtered_count
                }
                
                self.progress.emit(f"'{self.keyword}' 검색 완료 (필터링: {filtered_count}개)")
                self.finished.emit(result)
                return

            except requests.Timeout:
                if attempt < self.max_retries - 1:
                    self.progress.emit(f"요청 시간 초과. 재시도 중...")
                    time.sleep(1)
                    continue
                else:
                    self.error.emit("요청 시간이 초과되었습니다. 네트워크 연결을 확인해주세요.")
                    return
            
            except requests.RequestException as e:
                if attempt < self.max_retries - 1:
                    self.progress.emit(f"네트워크 오류. 재시도 중...")
                    time.sleep(1)
                    continue
                else:
                    self.error.emit(f"네트워크 오류: {str(e)}")
                    return
            
            except Exception as e:
                print(f"ApiWorker 예외: {e}")
                traceback.print_exc()
                self.error.emit(f"오류 발생: {str(e)}")
                return

    def stop(self):
        """워커 중지"""
        self.is_running = False

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


# --- 개별 뉴스 탭 위젯 (필터링 최적화) ---
class NewsTab(QWidget):
    """개별 뉴스 탭 (메모리 캐싱 및 필터링 최적화)"""
    
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
        
        self.setup_ui()
        self.load_data_from_db()

    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        
        top_layout = QHBoxLayout()
        
        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)
        self.inp_filter.textChanged.connect(self.apply_filter)
        
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self.load_data_from_db)
        
        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self.load_data_from_db)
        
        self.chk_hide_dup = QCheckBox("중복 숨김")
        self.chk_hide_dup.stateChanged.connect(self.load_data_from_db)
        
        top_layout.addWidget(self.inp_filter, 3)
        top_layout.addWidget(self.combo_sort, 1)
        top_layout.addWidget(self.chk_unread, 1)
        top_layout.addWidget(self.chk_hide_dup, 1)
        layout.addLayout(top_layout)
        
        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False)
        self.browser.anchorClicked.connect(self.on_link_clicked)
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

    def load_data_from_db(self):
        """DB에서 데이터 로드 (캐싱)"""
        self.news_data_cache = self.db.fetch_news(
            keyword=self.keyword,
            filter_txt="",
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab,
            only_unread=self.chk_unread.isChecked(),
            hide_duplicates=self.chk_hide_dup.isChecked()
        )
        self.apply_filter()
    
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
        
        self.render_html()

    def render_html(self):
        """HTML 렌더링"""
        scroll_pos = self.browser.verticalScrollBar().value()
        
        is_dark = (self.theme == 1)
        text_color = "#E0E0E0" if is_dark else "#000000"
        link_color = "#58A6FF" if is_dark else "#007BFF"
        link_hover = "#79C0FF" if is_dark else "#0056b3"
        border_color = "#4A4A4A" if is_dark else "#E9ECEF"
        bg_color = "#3C3C3C" if is_dark else "#FFFFFF"
        read_bg = "#313131" if is_dark else "#F8F9FA"
        title_color = "#E0E0E0" if is_dark else "#212529"
        meta_color = "#AAAAAA" if is_dark else "#6C757D"
        desc_color = "#CCCCCC" if is_dark else "#495057"
        tag_bg = "#0A84FF" if is_dark else "#007AFF"
        tag_color = "#FFFFFF"

        css = AppStyle.HTML_TEMPLATE.format(
            text_color=text_color, link_color=link_color, link_hover=link_hover,
            border_color=border_color, bg_color=bg_color, read_bg=read_bg,
            title_color=title_color, meta_color=meta_color, desc_color=desc_color,
            tag_bg=tag_bg, tag_color=tag_color
        )
        
        html_parts = [f"<html><head><meta charset='utf-8'>{css}</head><body>"]
        
        preview_data = {}
        
        if not self.filtered_data_cache:
            if self.is_bookmark_tab:
                msg = "⭐ 북마크된 기사가 없습니다.<br><br>기사 카드의 [북마크] 버튼을 눌러 중요한 기사를 저장하세요."
            elif self.chk_unread.isChecked():
                msg = "✓ 모든 기사를 읽었습니다!"
            else:
                msg = "📰 표시할 뉴스 기사가 없습니다.<br><br>새로고침 버튼을 눌러 최신 뉴스를 가져오세요."
            html_parts.append(f"<div class='empty-state'>{msg}</div>")
        else:
            filter_word = self.inp_filter.text().strip()
            
            for item in self.filtered_data_cache:
                is_read_cls = " read" if item['is_read'] else ""
                is_dup_cls = " duplicate" if item.get('is_duplicate', 0) else ""
                title_pfx = "⭐ " if item['is_bookmarked'] else ""
                link_hash = hashlib.md5(item['link'].encode()).hexdigest()
                
                preview_data[link_hash] = item['description']
                
                if filter_word:
                    title = TextUtils.highlight_text(item['title'], filter_word)
                    desc = TextUtils.highlight_text(item['description'], filter_word)
                else:
                    title = html.escape(item['title'])
                    desc = html.escape(item['description'])

                bk_txt = "북마크 해제" if item['is_bookmarked'] else "북마크"
                bk_col = "#DC3545" if item['is_bookmarked'] else "#17A2B8"
                
                date_str = item.get('pubDate', '')
                try:
                    dt = parsedate_to_datetime(date_str)
                    date_str = dt.strftime('%Y년 %m월 %d일 %H:%M')
                except:
                    pass

                has_note = item.get('notes') and item['notes'].strip()
                note_indicator = " 📝" if has_note else ""

                actions = f"""
                    <a href='app://share/{link_hash}'>공유</a>
                    <a href='app://ext/{link_hash}'>외부</a>
                    <a href='app://note/{link_hash}'>메모{note_indicator}</a>
                """
                if item['is_read']:
                    actions += f"<a href='app://unread/{link_hash}'>안읽음</a> "
                actions += f"<a href='app://bm/{link_hash}' style='color:{bk_col}'>{bk_txt}</a>"

                badges = ""
                if not self.is_bookmark_tab and self.keyword:
                    keywords = self.keyword.split()
                    for kw in keywords:
                        if not kw.startswith('-'):
                            badges += f"<span class='keyword-tag'>{html.escape(kw)}</span>"
                
                if item.get('is_duplicate', 0):
                    badges += "<span class='duplicate-badge'>유사 기사</span>"

                html_parts.append(f"""
                <div class="news-item{is_read_cls}{is_dup_cls}">
                    <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
                    <div class="meta-info">
                        📌 {item['publisher']} | 🕐 {date_str} {badges}
                        <span class="actions">{actions}</span>
                    </div>
                    <div class="description">{desc}</div>
                </div>
                """)
        
        html_parts.append("</body></html>")
        
        self.browser.set_preview_data(preview_data)
        
        self.browser.setHtml("".join(html_parts))
        
        QTimer.singleShot(10, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))
        self.update_status_label()

    def update_status_label(self):
        """상태 레이블 업데이트"""
        displayed = len(self.filtered_data_cache)
        
        if not self.is_bookmark_tab:
            unread = self.db.get_unread_count(self.keyword)
            msg = f"'{self.keyword}': 총 {self.total_api_count}개"
            
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                msg += f" | 필터링: {displayed}개 표시"
            else:
                msg += f" | {len(self.news_data_cache)}개 표시"
            
            if unread > 0:
                msg += f" | 안 읽음: {unread}개"
            if self.last_update:
                msg += f" | 업데이트: {self.last_update}"
            self.lbl_status.setText(msg)
        else:
            filter_word = self.inp_filter.text().strip()
            if filter_word:
                self.lbl_status.setText(f"⭐ 북마크 {len(self.news_data_cache)}개 중 {displayed}개 표시")
            else:
                self.lbl_status.setText(f"⭐ 북마크 {len(self.news_data_cache)}개")

    def on_link_clicked(self, url: QUrl):
        """링크 클릭 처리"""
        scheme = url.scheme()
        if scheme != "app":
            return

        action = url.host()
        link_hash = url.path().lstrip('/')
        
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

    def mark_all_read(self):
        """모두 읽음으로 표시"""
        reply = QMessageBox.question(
            self,
            "모두 읽음으로 표시",
            "현재 표시된 모든 기사를 읽음으로 표시하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.db.get_connection()
            try:
                with conn:
                    if self.is_bookmark_tab:
                        conn.execute("UPDATE news SET is_read=1 WHERE is_bookmarked=1")
                    else:
                        conn.execute("UPDATE news SET is_read=1 WHERE keyword=?", (self.keyword,))
                self.load_data_from_db()
                if self.window():
                    self.window().show_toast("✓ 모든 기사를 읽음으로 표시했습니다.")
            except Exception as e:
                QMessageBox.critical(self, "오류", f"처리 중 오류가 발생했습니다:\n\n{str(e)}")
            finally:
                self.db.return_connection(conn)

    def update_timestamp(self):
        """업데이트 시간 갱신"""
        self.last_update = datetime.now().strftime('%H:%M:%S')


# --- 메인 윈도우 ---
class MainApp(QMainWindow):
    """메인 애플리케이션 윈도우"""
    
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager(DB_FILE)
        self.workers = {}
        self.threads = {}
        self.toast_queue = ToastQueue(self)
        
        # 아이콘 설정
        self.set_application_icon()
        
        self.load_config()
        self.init_ui()
        self.setup_shortcuts()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.apply_refresh_interval()
        
        if self.client_id and self.tabs.count() > 1:
            QTimer.singleShot(500, self.refresh_all)
    
    def set_application_icon(self):
        """애플리케이션 아이콘 설정"""
        icon_path = None
        
        # 실행 파일과 같은 디렉토리에서 아이콘 찾기
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Windows: .ico 파일 우선
        if sys.platform == 'win32':
            ico_path = os.path.join(script_dir, ICON_FILE)
            if os.path.exists(ico_path):
                icon_path = ico_path
        
        # .ico가 없으면 .png 사용
        if not icon_path:
            png_path = os.path.join(script_dir, ICON_PNG)
            if os.path.exists(png_path):
                icon_path = png_path
        
        # 아이콘 적용
        if icon_path and os.path.exists(icon_path):
            app_icon = QIcon(icon_path)
            self.setWindowIcon(app_icon)
            QApplication.setWindowIcon(app_icon)  # 모든 창에 적용
        else:
            # 아이콘 파일이 없으면 경고 (한 번만)
            print(f"⚠️  아이콘 파일을 찾을 수 없습니다: {ICON_FILE} 또는 {ICON_PNG}")
            print(f"    실행 파일과 같은 폴더에 아이콘 파일을 배치하세요.")

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
                else:
                    self.config['client_id'] = loaded.get('id', '')
                    self.config['client_secret'] = loaded.get('secret', '')
                    self.config['theme'] = loaded.get('theme', 0)
                    self.config['interval'] = loaded.get('interval', 2)
                    self.config['tabs'] = loaded.get('tabs', [])
            except Exception as e:
                print(f"Config Load Error: {e}")
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
                'refresh_interval_index': self.interval_idx
            },
            'tabs': tab_names
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
            print(f"Config Save Error: {e}")
            QMessageBox.warning(self, "저장 오류", f"설정을 저장하는 중 오류가 발생했습니다:\n\n{str(e)}")

    def init_ui(self):
        """UI 초기화"""
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(1100, 850)
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        
        toolbar = QHBoxLayout()
        
        self.btn_refresh = QPushButton("🔄 새로고침")
        self.btn_save = QPushButton("💾 내보내기")
        self.btn_setting = QPushButton("⚙ 설정")
        self.btn_stats = QPushButton("📊 통계")
        self.btn_analysis = QPushButton("📈 분석")
        self.btn_help = QPushButton("❓ 도움말")
        self.btn_folder = QPushButton("📁 폴더")
        self.btn_add = QPushButton("➕ 새 탭")
        self.btn_add.setObjectName("AddTab")
        
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_stats)
        toolbar.addWidget(self.btn_analysis)
        toolbar.addWidget(self.btn_setting)
        toolbar.addWidget(self.btn_help)
        toolbar.addWidget(self.btn_folder)
        toolbar.addStretch()
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
        layout.addWidget(self.tabs)
        
        self.btn_refresh.clicked.connect(self.refresh_all)
        self.btn_setting.clicked.connect(self.open_settings)
        self.btn_stats.clicked.connect(self.show_statistics)
        self.btn_analysis.clicked.connect(self.show_analysis)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE)))
        ))
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.btn_save.clicked.connect(self.export_data)
        
        self.bm_tab = NewsTab("북마크", self.db, self.theme_idx, self)
        self.tabs.addTab(self.bm_tab, "⭐ 북마크")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        
        for key in self.tabs_data:
            if key and key != "북마크":
                self.add_news_tab(key)
        
        self.statusBar().showMessage("준비됨")
        
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.setToolTip(APP_NAME)
        
        tray_menu = QMenu()
        show_action = tray_menu.addAction("창 표시")
        show_action.triggered.connect(self.show)
        refresh_action = tray_menu.addAction("새로고침")
        refresh_action.triggered.connect(self.refresh_all)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("종료")
        quit_action.triggered.connect(self.close)
        
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

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

    def show_toast(self, message: str):
        """토스트 메시지 표시"""
        self.toast_queue.add(message)
    
    def resizeEvent(self, event):
        """창 크기 변경 시 토스트 위치 업데이트"""
        super().resizeEvent(event)
        if self.toast_queue.current_toast:
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

    def add_tab_dialog(self):
        """새 탭 추가 다이얼로그"""
        dialog = QDialog(self)
        dialog.setWindowTitle("새 탭 추가")
        dialog.resize(400, 250)
        
        layout = QVBoxLayout(dialog)
        
        info_label = QLabel(
            "검색할 키워드를 입력하세요.\n"
            "제외 키워드는 '-'를 앞에 붙여주세요.\n\n"
            "예시:\n"
            "• 주식\n"
            "• 주식 -코인 (코인 제외)\n"
            "• 인공지능 AI -광고"
        )
        info_label.setStyleSheet("color: #666; font-size: 9pt;")
        layout.addWidget(info_label)
        
        input_field = QLineEdit()
        input_field.setPlaceholderText("예: 주식 -코인")
        layout.addWidget(input_field)
        
        quick_layout = QHBoxLayout()
        quick_label = QLabel("빠른 입력:")
        quick_layout.addWidget(quick_label)
        
        examples = ["주식", "부동산", "IT 기술", "스포츠", "날씨"]
        for example in examples:
            btn = QPushButton(example)
            btn.clicked.connect(lambda checked, text=example: input_field.setText(text))
            quick_layout.addWidget(btn)
        
        quick_layout.addStretch()
        layout.addLayout(quick_layout)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() and input_field.text().strip():
            keyword = ValidationUtils.sanitize_keyword(input_field.text())
            self.add_news_tab(keyword)
            self.fetch_news(keyword)

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
            
            conn = self.db.get_connection()
            try:
                with conn:
                    conn.execute("UPDATE news SET keyword=? WHERE keyword=?", (new_keyword, old_keyword))
            except Exception as e:
                print(f"Rename error: {e}")
            finally:
                self.db.return_connection(conn)
            
            self.fetch_news(new_keyword)
            self.save_config()

    def refresh_all(self):
        """모든 탭 새로고침 - 안전한 버전"""
        try:
            valid, msg = ValidationUtils.validate_api_credentials(self.client_id, self.client_secret)
            if not valid:
                self.statusBar().showMessage(f"⚠ {msg}")
                # 자동 새로고침 중일 때는 설정창 열지 않음 (무한 팝업 방지)
                return

            self.progress.setVisible(True)
            self.progress.setRange(0, max(1, self.tabs.count() - 1))
            self.progress.setValue(0)
            self.statusBar().showMessage("🔄 모든 탭 업데이트 중...")
            self.btn_refresh.setEnabled(False)
            
            # 북마크 탭 새로고침
            try:
                self.bm_tab.load_data_from_db()
            except Exception as e:
                print(f"북마크 탭 로드 오류: {e}")
            
            # 각 탭 새로고침
            tab_count = self.tabs.count()
            for i in range(1, tab_count):
                try:
                    widget = self.tabs.widget(i)
                    if widget and hasattr(widget, 'keyword'):
                        self.fetch_news(widget.keyword)
                        self.progress.setValue(i)
                except Exception as e:
                    print(f"탭 {i} 새로고침 오류: {e}")
                    continue
                    
        except Exception as e:
            print(f"refresh_all 오류: {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 새로고침 오류: {str(e)}")
        finally:
            # UI 상태 복원 (지연)
            QTimer.singleShot(3000, lambda: self.btn_refresh.setEnabled(True))

    def fetch_news(self, keyword: str, is_more: bool = False):
        """뉴스 가져오기"""
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
                return

        if keyword in self.workers:
            old_worker, old_thread = self.workers[keyword]
            old_worker.stop()
            old_thread.quit()
            old_thread.wait(3000)

        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(False)
                w.btn_load.setText("⏳ 로딩 중...")
                break

        worker = ApiWorker(self.client_id, self.client_secret, search_keyword, exclude_words, start_idx)
        thread = QThread()
        worker.moveToThread(thread)
        
        self.workers[keyword] = (worker, thread)
        self.threads[keyword] = thread
        
        worker.finished.connect(lambda res: self.on_fetch_done(res, keyword, is_more))
        worker.error.connect(lambda err: self.on_fetch_error(err, keyword))
        worker.progress.connect(self.statusBar().showMessage)
        
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.cleanup_worker(keyword))
        
        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(self, result: Dict, keyword: str, is_more: bool):
        """뉴스 가져오기 완료 - 안전한 버전"""
        try:
            search_keyword = keyword.split()[0] if keyword.split() else keyword
            
            added_count, dup_count = self.db.upsert_news(result['items'], search_keyword)
            
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if w and hasattr(w, 'keyword') and w.keyword == keyword:
                    w.total_api_count = result['total']
                    w.update_timestamp()
                    w.load_data_from_db()
                    
                    w.btn_load.setEnabled(True)
                    w.btn_load.setText("📥 더 불러오기")
                    
                    if not is_more:
                        msg = f"✓ '{keyword}' 업데이트 완료 ({added_count}건 추가"
                        if dup_count > 0:
                            msg += f", {dup_count}건 중복"
                        if result.get('filtered', 0) > 0:
                            msg += f", {result['filtered']}건 필터링"
                        msg += ")"
                        w.lbl_status.setText(msg)
                    break
            
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
                
        except Exception as e:
            print(f"Fetch Done Error: {e}")
            traceback.print_exc()
            self.statusBar().showMessage(f"⚠ 처리 중 오류: {str(e)}")
            # UI 복원
            self.progress.setVisible(False)
            self.btn_refresh.setEnabled(True)

    def on_fetch_error(self, error_msg: str, keyword: str):
        """뉴스 가져오기 오류"""
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(True)
                w.btn_load.setText("📥 더 불러오기")
                break
        
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

    def cleanup_worker(self, keyword: str):
        """워커 정리 - 안전한 버전"""
        try:
            if keyword in self.workers:
                worker, thread = self.workers[keyword]
                try:
                    worker.stop()
                except:
                    pass
                del self.workers[keyword]
            if keyword in self.threads:
                del self.threads[keyword]
        except Exception as e:
            print(f"워커 정리 오류 ({keyword}): {e}")

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
                
                self.show_toast(f"✓ {len(cur_widget.news_data_cache)}개 항목이 저장되었습니다")
                QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")
                
            except Exception as e:
                QMessageBox.warning(self, "오류", f"저장 중 오류 발생:\n{str(e)}")

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

    def show_analysis(self):
        """언론사별 분석"""
        dialog = QDialog(self)
        dialog.setWindowTitle("뉴스 분석")
        dialog.resize(600, 500)
        
        layout = QVBoxLayout(dialog)
        
        tab_label = QLabel("분석할 탭을 선택하세요:")
        layout.addWidget(tab_label)
        
        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword'):
                tab_combo.addItem(w.keyword, w.keyword)
        layout.addWidget(tab_combo)
        
        result_label = QLabel("📈 언론사별 기사 수:")
        result_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(result_label)
        
        result_list = QListWidget()
        layout.addWidget(result_list)
        
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
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()

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
            'theme': self.theme_idx
        }
        
        dlg = SettingsDialog(current_config, self)
        if dlg.exec():
            data = dlg.get_data()
            
            self.client_id = data['id']
            self.client_secret = data['secret']
            self.interval_idx = data['interval']
            
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
            
            self.show_toast("✓ 설정이 저장되었습니다.")

    def apply_refresh_interval(self):
        """자동 새로고침 간격 적용 - 안전한 버전"""
        try:
            self.timer.stop()
            idx = self.interval_idx
            minutes = [10, 30, 60, 180, 360]
            
            if 0 <= idx < len(minutes):
                ms = minutes[idx] * 60 * 1000
                self.timer.setInterval(ms)  # 명시적으로 간격 설정
                self.timer.start()
                self.statusBar().showMessage(f"⏰ 자동 새로고침: {minutes[idx]}분 간격")
                print(f"✅ 자동 새로고침 설정: {minutes[idx]}분 ({ms}ms)")
            else:
                # 인덱스 5 = "자동 새로고침 안함"
                self.timer.stop()
                self.statusBar().showMessage("⏰ 자동 새로고침 꺼짐")
                print("✅ 자동 새로고침 비활성화됨")
        except Exception as e:
            print(f"⚠️ 타이머 설정 오류: {e}")
            traceback.print_exc()

    def closeEvent(self, event):
        """종료 이벤트 - 안전한 버전"""
        print("🔄 프로그램 종료 시작...")
        try:
            # 타이머 중지
            self.timer.stop()
            print("  ✅ 타이머 중지됨")
            
            # 모든 워커 정리
            for keyword, (worker, thread) in list(self.workers.items()):
                try:
                    worker.stop()
                    thread.quit()
                    if not thread.wait(2000):  # 2초로 단축
                        print(f"  ⚠️ 스레드 강제 종료: {keyword}")
                        thread.terminate()
                        thread.wait(1000)
                except Exception as e:
                    print(f"  워커 종료 오류 ({keyword}): {e}")
            
            self.workers.clear()
            self.threads.clear()
            print("  ✅ 워커 정리 완료")
            
            # 설정 저장
            try:
                self.save_config()
                print("  ✅ 설정 저장 완료")
            except Exception as e:
                print(f"  설정 저장 오류: {e}")
            
            # DB 종료
            try:
                self.db.close()
                print("  ✅ DB 종료 완료")
            except Exception as e:
                print(f"  DB 종료 오류: {e}")
                
            print("✅ 프로그램 정상 종료")
        except Exception as e:
            print(f"⚠️ 종료 처리 오류: {e}")
            traceback.print_exc()
        finally:
            super().closeEvent(event)


# --- 설정 다이얼로그 ---
class SettingsDialog(QDialog):
    """설정 다이얼로그 (검증 기능 + 도움말 추가)"""
    
    def __init__(self, config: Dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정 및 도움말")
        self.resize(600, 550)
        self.config = config
        self.setup_ui()

    def setup_ui(self):
        """UI 설정"""
        layout = QVBoxLayout(self)
        
        # 탭 위젯 생성
        tab_widget = QTabWidget()
        
        # === 설정 탭 ===
        settings_widget = QWidget()
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
        
        self.cb_time = QComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "3시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get('interval', 2)
        if isinstance(idx, int) and 0 <= idx <= 5:
            self.cb_time.setCurrentIndex(idx)
        else:
            self.cb_time.setCurrentIndex(2)
        
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["☀ 라이트 모드", "🌙 다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get('theme', 0))
        
        form2.addWidget(QLabel("자동 새로고침:"), 0, 0)
        form2.addWidget(self.cb_time, 0, 1)
        form2.addWidget(QLabel("테마:"), 1, 0)
        form2.addWidget(self.cb_theme, 1, 1)
        
        gp_app.setLayout(form2)
        settings_layout.addWidget(gp_app)
        
        gp_data = QGroupBox("🗂 데이터 관리")
        vbox = QVBoxLayout()
        
        btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        btn_clean.clicked.connect(self.clean_data)
        
        btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        btn_all.clicked.connect(self.clean_all)
        
        vbox.addWidget(btn_clean)
        vbox.addWidget(btn_all)
        gp_data.setLayout(vbox)
        settings_layout.addWidget(gp_data)
        
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
        
        # 탭에 추가
        tab_widget.addTab(settings_widget, "⚙ 설정")
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

    def get_data(self) -> Dict:
        """설정 데이터 반환"""
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex()
        }

# --- 메인 실행 ---
def main():
    """메인 함수 - 안전한 버전"""
    # 전역 예외 처리기
    def exception_hook(exc_type, exc_value, exc_tb):
        print("=" * 50)
        print("⚠️ 처리되지 않은 예외 발생:")
        traceback.print_exception(exc_type, exc_value, exc_tb)
        print("=" * 50)
        # 로그 파일에도 저장
        try:
            with open("crash_log.txt", "a", encoding="utf-8") as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"시간: {datetime.now()}\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except:
            pass
    
    sys.excepthook = exception_hook
    
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION)
        
        font = app.font()
        font.setFamily("맑은 고딕")
        app.setFont(font)
        
        window = MainApp()
        window.show()
        
        print(f"✅ {APP_NAME} v{VERSION} 시작됨")
        
        sys.exit(app.exec())
        
    except Exception as e:
        print(f"애플리케이션 시작 오류: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
