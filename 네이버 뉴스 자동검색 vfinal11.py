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
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from collections import Counter

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextBrowser, QLabel, QMessageBox,
    QTabWidget, QInputDialog, QComboBox, QFileDialog, QSystemTrayIcon,
    QMenu, QStyle, QTabBar, QDialog, QDialogButtonBox, QGroupBox,
    QGridLayout, QProgressBar, QSplitter, QCheckBox, QTextEdit, QListWidget,
    QGraphicsOpacityEffect
)
from PyQt6.QtCore import (
    QThread, QObject, pyqtSignal, pyqtSlot, Qt, QTimer, QUrl, 
    QMutex, QSize, QPropertyAnimation, QEasingCurve, QPoint
)
from PyQt6.QtGui import QDesktopServices, QIcon, QAction, QKeySequence, QShortcut

# --- 상수 및 설정 ---
CONFIG_FILE = "news_scraper_config.json"
DB_FILE = "news_database.db"
APP_NAME = "뉴스 스크래퍼 Pro"
VERSION = "24.6"  # 토스트 메시지 중복 해결 (Batch 요약)

# --- 커스텀 위젯: 토스트 메시지 ---
class ToastMessage(QLabel):
    """화면에 잠시 나타났다 사라지는 알림 메시지"""
    def __init__(self, parent, message):
        super().__init__(message, parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.SubWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # 클릭 통과
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # 스타일 설정 (반투명 검정 배경, 둥근 모서리)
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
        
        # 위치 설정 (부모 윈도우 하단 중앙)
        if parent:
            p_rect = parent.rect()
            self.move(
                p_rect.center().x() - self.width() // 2,
                p_rect.bottom() - 100  # 바닥에서 100px 위
            )
            
        # 투명도 효과 설정
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        # 페이드 인 애니메이션
        self.anim_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_in.setDuration(300)
        self.anim_in.setStartValue(0.0)
        self.anim_in.setEndValue(1.0)
        self.anim_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim_in.start()
        
        self.show()
        
        # 일정 시간 후 사라짐
        self.timer = QTimer()
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        self.timer.start(2000)  # 2초간 표시

    def fade_out(self):
        # 페이드 아웃 애니메이션
        self.anim_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim_out.setDuration(500)
        self.anim_out.setStartValue(1.0)
        self.anim_out.setEndValue(0.0)
        self.anim_out.finished.connect(self.close) # 애니메이션 끝나면 위젯 삭제
        self.anim_out.start()

# --- 커스텀 브라우저 ---
class NewsBrowser(QTextBrowser):
    """링크 클릭 시 페이지 이동을 원천 차단하고 시그널만 발생"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)  
        self.setOpenLinks(False) 

    def setSource(self, url):
        if url.scheme() == 'app':
            return
        super().setSource(url)

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
        
        .title-link {{ font-size: 13pt; font-weight: bold; color: {title_color}; line-height: 1.5; display: block; margin-bottom: 8px; }}
        .meta-info {{ font-size: 9.5pt; color: {meta_color}; margin-top: 8px; border-bottom: 1px solid {border_color}; padding-bottom: 8px; margin-bottom: 12px; }}
        .description {{ margin-top: 0px; line-height: 1.8; color: {desc_color}; font-size: 10.5pt; }}
        
        .actions {{ float: right; font-size: 9.5pt; white-space: nowrap; }}
        .actions a {{ margin-left: 12px; }}
        
        .empty-state {{ text-align: center; padding: 60px 20px; color: {meta_color}; font-size: 11pt; }}
        .highlight {{ background-color: #FCD34D; color: #000000; padding: 2px 4px; border-radius: 3px; font-weight: bold; }}
        .keyword-tag {{ display: inline-block; background-color: {tag_bg}; color: {tag_color}; padding: 2px 8px; border-radius: 10px; font-size: 8.5pt; margin-right: 5px; }}
    </style>
    """

# --- 데이터베이스 관리 ---
class DatabaseManager:
    def __init__(self, db_file):
        self.db_file = db_file
        self.local = threading.local()
        self.mutex = QMutex()
        self.init_db()

    def get_conn(self):
        if not hasattr(self.local, 'conn') or self.local.conn is None:
            self.local.conn = sqlite3.connect(self.db_file, timeout=30.0, check_same_thread=False)
            self.local.conn.execute("PRAGMA journal_mode=WAL") 
            self.local.conn.execute("PRAGMA synchronous=NORMAL")
            self.local.conn.row_factory = sqlite3.Row
        return self.local.conn

    def init_db(self):
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
                    notes TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_read ON news(is_read)")
            
            try:
                conn.execute("ALTER TABLE news ADD COLUMN notes TEXT")
            except sqlite3.OperationalError:
                pass
        conn.close()

    def upsert_news(self, items, keyword):
        if not items:
            return 0
            
        conn = self.get_conn()
        added_count = 0
        self.mutex.lock()
        try:
            with conn:
                for item in items:
                    ts = 0.0
                    try:
                        ts = parsedate_to_datetime(item['pubDate']).timestamp()
                    except:
                        pass
                    
                    try:
                        cur = conn.execute("""
                            INSERT OR IGNORE INTO news (link, keyword, title, description, pubDate, publisher, pubDate_ts)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (item['link'], keyword, item['title'], item['description'], 
                              item['pubDate'], item['publisher'], ts))
                        if cur.rowcount > 0:
                            added_count += 1
                    except sqlite3.Error as e:
                        print(f"DB Insert Error: {e}")
                        continue
        finally:
            self.mutex.unlock()
        return added_count

    def fetch_news(self, keyword, filter_txt, sort_mode, only_bookmark=False, only_unread=False):
        conn = self.get_conn()
        query = "SELECT * FROM news WHERE 1=1"
        params = []

        if only_bookmark:
            query += " AND is_bookmarked = 1"
        else:
            query += " AND keyword = ?"
            params.append(keyword)

        if only_unread:
            query += " AND is_read = 0"

        if filter_txt:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{filter_txt}%", f"%{filter_txt}%"])
            
        order = "DESC" if sort_mode == "최신순" else "ASC"
        query += f" ORDER BY pubDate_ts {order} LIMIT 1000"

        self.mutex.lock()
        try:
            cursor = conn.execute(query, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            print(f"DB Fetch Error: {e}")
            return []
        finally:
            self.mutex.unlock()

    def get_counts(self, keyword):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news WHERE keyword=?", (keyword,))
            return cursor.fetchone()[0] or 0
        except:
            return 0
        finally:
            self.mutex.unlock()

    def get_unread_count(self, keyword):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news WHERE keyword=? AND is_read=0", (keyword,))
            return cursor.fetchone()[0] or 0
        except:
            return 0
        finally:
            self.mutex.unlock()

    def update_status(self, link, field, value):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            with conn:
                conn.execute(f"UPDATE news SET {field} = ? WHERE link = ?", (value, link))
            return True
        except sqlite3.Error as e:
            print(f"DB Update Error: {e}")
            return False
        finally:
            self.mutex.unlock()

    def save_note(self, link, note):
        return self.update_status(link, "notes", note)

    def get_note(self, link):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            cursor = conn.execute("SELECT notes FROM news WHERE link=?", (link,))
            result = cursor.fetchone()
            return result[0] if result and result[0] else ""
        except:
            return ""
        finally:
            self.mutex.unlock()

    def delete_old_news(self, days):
        conn = self.get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        self.mutex.lock()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0 AND pubDate_ts < ?", (cutoff,))
                return cur.rowcount
        except:
            return 0
        finally:
            self.mutex.unlock()

    def delete_all_news(self):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0")
                return cur.rowcount
        except:
            return 0
        finally:
            self.mutex.unlock()

    def get_statistics(self):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
            unread = conn.execute("SELECT COUNT(*) FROM news WHERE is_read=0").fetchone()[0]
            bookmarked = conn.execute("SELECT COUNT(*) FROM news WHERE is_bookmarked=1").fetchone()[0]
            with_notes = conn.execute("SELECT COUNT(*) FROM news WHERE notes IS NOT NULL AND notes != ''").fetchone()[0]
            return {'total': total, 'unread': unread, 'bookmarked': bookmarked, 'with_notes': with_notes}
        except:
            return {'total': 0, 'unread': 0, 'bookmarked': 0, 'with_notes': 0}
        finally:
            self.mutex.unlock()

    def get_top_publishers(self, keyword=None, limit=10):
        conn = self.get_conn()
        self.mutex.lock()
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
            self.mutex.unlock()

    def close(self):
        if hasattr(self.local, 'conn') and self.local.conn:
            self.local.conn.close()
            self.local.conn = None

# --- API 워커 ---
class ApiWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, client_id, client_secret, keyword, exclude_words, start_idx=1):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.keyword = keyword
        self.exclude_words = exclude_words
        self.start = start_idx
        self.is_running = True

    def run(self):
        if not self.is_running:
            return
            
        try:
            self.progress.emit(f"'{self.keyword}' 검색 중...")
            
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
            
            if resp.status_code != 200:
                error_msg = resp.json().get('errorMessage', '알 수 없는 오류')
                raise Exception(f"API 오류 {resp.status_code}: {error_msg}")
            
            data = resp.json()
            items = []
            filtered_count = 0
            
            for item in data.get('items', []):
                if not self.is_running:
                    break
                    
                title = html.unescape(item['title']).replace('<b>', '').replace('</b>', '')
                desc = html.unescape(item['description']).replace('<b>', '').replace('</b>', '')
                
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
                    'pubDate': item['pubDate'],
                    'publisher': publisher
                })
            
            result = {
                'items': items,
                'total': data.get('total', 0),
                'filtered': filtered_count
            }
            
            self.progress.emit(f"'{self.keyword}' 검색 완료 (필터링: {filtered_count}개)")
            self.finished.emit(result)

        except requests.Timeout:
            self.error.emit("요청 시간 초과. 네트워크 연결을 확인해주세요.")
        except requests.RequestException as e:
            self.error.emit(f"네트워크 오류: {str(e)}")
        except Exception as e:
            self.error.emit(f"오류 발생: {str(e)}")

    def stop(self):
        self.is_running = False

# --- 메모 다이얼로그 ---
class NoteDialog(QDialog):
    def __init__(self, current_note="", parent=None):
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
    
    def get_note(self):
        return self.text_edit.toPlainText().strip()

# --- 개별 뉴스 탭 위젯 ---
class NewsTab(QWidget):
    def __init__(self, keyword, db_manager, theme_mode=0, parent=None):
        super().__init__(parent)
        self.keyword = keyword
        self.db = db_manager
        self.theme = theme_mode
        self.is_bookmark_tab = (keyword == "북마크")
        
        self.news_data = []
        self.total_api_count = 0
        self.last_update = None
        
        self.setup_ui()
        self.load_data_from_db()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        
        top_layout = QHBoxLayout()
        
        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("🔍 제목 또는 내용으로 필터링...")
        self.inp_filter.setClearButtonEnabled(True)
        self.inp_filter.textChanged.connect(self.refresh_ui_only)
        
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self.load_data_from_db)
        
        self.chk_unread = QCheckBox("안 읽은 것만")
        self.chk_unread.stateChanged.connect(self.load_data_from_db)
        
        top_layout.addWidget(self.inp_filter, 3)
        top_layout.addWidget(self.combo_sort, 1)
        top_layout.addWidget(self.chk_unread, 1)
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
        filter_txt = self.inp_filter.text()
        if filter_txt:
            self.inp_filter.setObjectName("FilterActive")
        else:
            self.inp_filter.setObjectName("")
        self.inp_filter.setStyle(self.inp_filter.style())
        
        self.news_data = self.db.fetch_news(
            keyword=self.keyword,
            filter_txt=filter_txt,
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab,
            only_unread=self.chk_unread.isChecked()
        )
        self.render_html()

    def refresh_ui_only(self):
        filter_txt = self.inp_filter.text()
        if filter_txt:
            self.inp_filter.setObjectName("FilterActive")
        else:
            self.inp_filter.setObjectName("")
        self.inp_filter.setStyle(self.inp_filter.style())
        self.render_html()

    def render_html(self):
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
        
        if not self.news_data:
            if self.is_bookmark_tab:
                msg = "⭐ 북마크된 기사가 없습니다.<br><br>기사 카드의 [북마크] 버튼을 눌러 중요한 기사를 저장하세요."
            elif self.chk_unread.isChecked():
                msg = "✓ 모든 기사를 읽었습니다!"
            else:
                msg = "📰 표시할 뉴스 기사가 없습니다.<br><br>새로고침 버튼을 눌러 최신 뉴스를 가져오세요."
            html_parts.append(f"<div class='empty-state'>{msg}</div>")
        else:
            filter_word = self.inp_filter.text()
            displayed_count = 0
            
            for item in self.news_data:
                if filter_word and (filter_word not in item['title'] and filter_word not in item['description']):
                    continue

                displayed_count += 1
                is_read_cls = " read" if item['is_read'] else ""
                title_pfx = "⭐ " if item['is_bookmarked'] else ""
                link_hash = hashlib.md5(item['link'].encode()).hexdigest()
                
                title = html.escape(item['title'])
                desc = html.escape(item['description'])
                
                if filter_word:
                    hl = f"<span class='highlight'>{html.escape(filter_word)}</span>"
                    title = title.replace(html.escape(filter_word), hl)
                    desc = desc.replace(html.escape(filter_word), hl)

                bk_txt = "북마크 해제" if item['is_bookmarked'] else "북마크"
                bk_col = "#DC3545" if item['is_bookmarked'] else "#17A2B8"
                
                date_str = item.get('pubDate', '')
                try:
                    dt = parsedate_to_datetime(date_str)
                    date_str = dt.strftime('%Y년 %m월 %d일 %H:%M')
                except:
                    pass

                # 메모 여부 표시
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

                # 키워드 태그 표시
                keyword_tags = ""
                if not self.is_bookmark_tab and self.keyword:
                    keywords = self.keyword.split()
                    for kw in keywords:
                        if not kw.startswith('-'):
                            keyword_tags += f"<span class='keyword-tag'>{html.escape(kw)}</span>"

                html_parts.append(f"""
                <div class="news-item{is_read_cls}">
                    <a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a>
                    <div class="meta-info">
                        📌 {item['publisher']} | 🕐 {date_str} {keyword_tags}
                        <span class="actions">{actions}</span>
                    </div>
                    <div class="description">{desc}</div>
                </div>
                """)
            
            if displayed_count == 0:
                html_parts.append(f"<div class='empty-state'>'{filter_word}' 검색 결과가 없습니다.</div>")
        
        html_parts.append("</body></html>")
        self.browser.setHtml("".join(html_parts))
        
        QTimer.singleShot(10, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))
        self.update_status_label()

    def update_status_label(self):
        filter_word = self.inp_filter.text()
        
        if filter_word:
            displayed = sum(1 for item in self.news_data 
                          if filter_word in item['title'] or filter_word in item['description'])
        else:
            displayed = len(self.news_data)
        
        if not self.is_bookmark_tab:
            unread = self.db.get_unread_count(self.keyword)
            msg = f"'{self.keyword}': 총 {self.total_api_count}개"
            
            if filter_word:
                msg += f" | 필터링: {displayed}개 표시"
            else:
                msg += f" | {len(self.news_data)}개 표시"
            
            if unread > 0:
                msg += f" | 안 읽음: {unread}개"
            if self.last_update:
                msg += f" | 업데이트: {self.last_update}"
            self.lbl_status.setText(msg)
        else:
            if filter_word:
                self.lbl_status.setText(f"⭐ 북마크 {len(self.news_data)}개 중 {displayed}개 표시")
            else:
                self.lbl_status.setText(f"⭐ 북마크 {len(self.news_data)}개")

    def on_link_clicked(self, url):
        scheme = url.scheme()
        if scheme != "app":
            return

        action = url.host()
        link_hash = url.path().lstrip('/')
        
        target = next((i for i in self.news_data if hashlib.md5(i['link'].encode()).hexdigest() == link_hash), None)
        if not target:
            return

        link = target['link']

        if action == "open":
            self.db.update_status(link, "is_read", 1)
            QDesktopServices.openUrl(QUrl(link))
            target['is_read'] = 1
            self.render_html()
            
        elif action == "bm":
            new_val = 0 if target['is_bookmarked'] else 1
            if self.db.update_status(link, "is_bookmarked", new_val):
                target['is_bookmarked'] = new_val
                if self.is_bookmark_tab and new_val == 0:
                    self.news_data.remove(target)
                self.render_html()
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
            self.render_html()
            if self.window():
                self.window().statusBar().showMessage("안 읽음으로 표시되었습니다.", 1500)
        
        elif action == "note":
            current_note = self.db.get_note(link)
            dialog = NoteDialog(current_note, self)
            if dialog.exec():
                new_note = dialog.get_note()
                if self.db.save_note(link, new_note):
                    target['notes'] = new_note
                    self.render_html()
                    if self.window():
                        self.window().show_toast("📝 메모가 저장되었습니다.")
            return
            
        elif action == "ext":
            QDesktopServices.openUrl(QUrl(link))
            return

    def mark_all_read(self):
        reply = QMessageBox.question(
            self,
            "모두 읽음으로 표시",
            "현재 표시된 모든 기사를 읽음으로 표시하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            conn = self.db.get_conn()
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

    def update_timestamp(self):
        self.last_update = datetime.now().strftime('%H:%M:%S')

# --- 메인 윈도우 ---
class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager(DB_FILE)
        self.workers = {}
        self.threads = {}
        
        # 배치 업데이트용 변수 초기화
        self.batch_remaining = 0
        self.batch_added_count = 0
        
        self.load_config()
        self.init_ui()
        self.setup_shortcuts()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.apply_refresh_interval()
        
        if self.client_id and self.tabs.count() > 1:
            QTimer.singleShot(500, self.refresh_all)

    def load_config(self):
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
        
        self.client_id = self.config['client_id']
        self.client_secret = self.config['client_secret']
        self.theme_idx = self.config['theme']
        self.interval_idx = self.config['interval']
        self.tabs_data = self.config['tabs']

    def save_config(self):
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
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Config Save Error: {e}")

    def init_ui(self):
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
        self.btn_folder = QPushButton("📁 폴더")
        self.btn_add = QPushButton("➕ 새 탭")
        self.btn_add.setObjectName("AddTab")
        
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_save)
        toolbar.addWidget(self.btn_stats)
        toolbar.addWidget(self.btn_analysis)
        toolbar.addWidget(self.btn_setting)
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
        QShortcut(QKeySequence("Ctrl+R"), self, self.refresh_all)
        QShortcut(QKeySequence("Ctrl+T"), self, self.add_tab_dialog)
        QShortcut(QKeySequence("Ctrl+W"), self, self.close_current_tab)
        QShortcut(QKeySequence("Ctrl+S"), self, self.export_data)
        QShortcut(QKeySequence("Ctrl+,"), self, self.open_settings)
        QShortcut(QKeySequence("F5"), self, self.refresh_all)

    def show_toast(self, message):
        """토스트 메시지를 띄우는 헬퍼 메서드"""
        ToastMessage(self, message)

    def close_current_tab(self):
        idx = self.tabs.currentIndex()
        if idx > 0:
            self.close_tab(idx)

    def add_news_tab(self, keyword):
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
            keyword = input_field.text().strip()
            self.add_news_tab(keyword)
            self.fetch_news(keyword)

    def close_tab(self, idx):
        if idx == 0:
            return
            
        widget = self.tabs.widget(idx)
        if widget:
            widget.deleteLater()
        self.tabs.removeTab(idx)
        self.save_config()

    def rename_tab(self, idx):
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
            new_keyword = text.strip()
            w.keyword = new_keyword
            
            icon_text = "📰" if not new_keyword.startswith("-") else "🚫"
            self.tabs.setTabText(idx, f"{icon_text} {new_keyword}")
            
            conn = self.db.get_conn()
            try:
                with conn:
                    conn.execute("UPDATE news SET keyword=? WHERE keyword=?", (new_keyword, old_keyword))
            except:
                pass
            
            self.fetch_news(new_keyword)
            self.save_config()

    def refresh_all(self):
        if not self.client_id or not self.client_secret:
            self.statusBar().showMessage("⚠ API 키가 설정되지 않았습니다.")
            self.open_settings()
            return

        # [Batch Logic Start]
        target_tabs = []
        for i in range(1, self.tabs.count()):
            widget = self.tabs.widget(i)
            if widget and hasattr(widget, 'keyword'):
                target_tabs.append(widget.keyword)
        
        if not target_tabs:
            self.bm_tab.load_data_from_db()
            return

        self.batch_remaining = len(target_tabs)
        self.batch_added_count = 0

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("🔄 모든 탭 업데이트 중...")
        self.btn_refresh.setEnabled(False)
        
        self.bm_tab.load_data_from_db()
        
        for keyword in target_tabs:
            self.fetch_news(keyword, is_batch=True)

    def fetch_news(self, keyword, is_more=False, is_batch=False):
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
            old_thread.wait(1000)

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
        
        # [Batch Logic Connection] Pass is_batch flag
        worker.finished.connect(lambda res: self.on_fetch_done(res, keyword, is_more, is_batch))
        worker.error.connect(lambda err: self.on_fetch_error(err, keyword))
        if not is_batch:
            worker.progress.connect(self.statusBar().showMessage)
        
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(thread.quit)
        
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.cleanup_worker(keyword))
        
        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(self, result, keyword, is_more, is_batch=False):
        try:
            search_keyword = keyword.split()[0] if keyword.split() else keyword
            
            count = self.db.upsert_news(result['items'], search_keyword)
            
            for i in range(1, self.tabs.count()):
                w = self.tabs.widget(i)
                if w and hasattr(w, 'keyword') and w.keyword == keyword:
                    w.total_api_count = result['total']
                    w.update_timestamp()
                    w.load_data_from_db()
                    
                    w.btn_load.setEnabled(True)
                    w.btn_load.setText("📥 더 불러오기")
                    
                    if not is_more and not is_batch:
                        msg = f"✓ '{keyword}' 업데이트 완료 ({count}건 추가"
                        if result.get('filtered', 0) > 0:
                            msg += f", {result['filtered']}건 필터링"
                        msg += ")"
                        w.lbl_status.setText(msg)
                    break
            
            # [Batch Logic End]
            if is_batch:
                self.batch_added_count += count
                self.batch_remaining -= 1
                
                if self.batch_remaining <= 0:
                    self.progress.setVisible(False)
                    self.progress.setRange(0, 100)
                    self.btn_refresh.setEnabled(True)
                    
                    msg = f"✅ 모든 업데이트 완료 (총 {self.batch_added_count}건 추가)"
                    self.show_toast(msg)
                    self.statusBar().showMessage(msg, 3000)
                else:
                    self.statusBar().showMessage(f"🔄 업데이트 중... (남은 탭: {self.batch_remaining})")
            else:
                # Individual refresh logic
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)
                
                if not is_more:
                    self.show_toast(f"✓ '{keyword}' 업데이트 완료 ({count}건 추가)")
                    self.statusBar().showMessage(f"✓ '{keyword}' 업데이트 완료 ({count}건 추가)", 3000)
                
        except Exception as e:
            print(f"Fetch Done Error: {e}")
            self.statusBar().showMessage(f"⚠ 처리 중 오류: {str(e)}")

    def on_fetch_error(self, error_msg, keyword):
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword') and w.keyword == keyword:
                w.btn_load.setEnabled(True)
                w.btn_load.setText("📥 더 불러오기")
                break
        
        # If batch process is running, decrement remaining count even on error
        if self.batch_remaining > 0:
            self.batch_remaining -= 1
            if self.batch_remaining <= 0:
                self.progress.setVisible(False)
                self.progress.setRange(0, 100)
                self.btn_refresh.setEnabled(True)
                self.show_toast(f"⚠ 업데이트 완료 (일부 오류 발생)")
        
        if self.batch_remaining <= 0:
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)
            self.btn_refresh.setEnabled(True)
        
        self.statusBar().showMessage(f"⚠ '{keyword}' 오류: {error_msg}", 5000)
        # Batch mode generally suppresses error popups to avoid spamming
        if self.batch_remaining <= 0: 
            QMessageBox.critical(self, "API 오류", f"'{keyword}' 검색 중 오류가 발생했습니다:\n\n{error_msg}")

    def cleanup_worker(self, keyword):
        if keyword in self.workers:
            del self.workers[keyword]
        if keyword in self.threads:
            del self.threads[keyword]

    def refresh_bookmark_tab(self):
        self.bm_tab.load_data_from_db()

    def export_data(self):
        cur_widget = self.tabs.currentWidget()
        if not cur_widget or not hasattr(cur_widget, 'news_data') or not cur_widget.news_data:
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
                    writer.writerow(['제목', '링크', '날짜', '출처', '요약', '읽음', '북마크', '메모'])
                    
                    for item in cur_widget.news_data:
                        writer.writerow([
                            item['title'],
                            item['link'],
                            item['pubDate'],
                            item['publisher'],
                            item['description'],
                            '읽음' if item['is_read'] else '안읽음',
                            '⭐' if item['is_bookmarked'] else '',
                            item.get('notes', '')
                        ])
                
                self.show_toast(f"✓ {len(cur_widget.news_data)}개 항목이 저장되었습니다")
                QMessageBox.information(self, "완료", f"파일이 저장되었습니다:\n{fname}")
                
            except Exception as e:
                QMessageBox.warning(self, "오류", f"저장 중 오류 발생:\n{str(e)}")

    def show_statistics(self):
        stats = self.db.get_statistics()
        
        if stats['total'] > 0:
            read_count = stats['total'] - stats['unread']
            read_percent = (read_count / stats['total']) * 100
        else:
            read_percent = 0
        
        dialog = QDialog(self)
        dialog.setWindowTitle("통계 정보")
        dialog.resize(350, 300)
        
        layout = QVBoxLayout(dialog)
        
        group = QGroupBox("📊 데이터베이스 통계")
        grid = QGridLayout()
        
        items = [
            ("총 기사 수:", f"{stats['total']:,}개"),
            ("안 읽은 기사:", f"{stats['unread']:,}개"),
            ("읽은 기사:", f"{stats['total'] - stats['unread']:,}개"),
            ("북마크:", f"{stats['bookmarked']:,}개"),
            ("메모 작성:", f"{stats['with_notes']:,}개"),
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
        """언론사별 분석 및 키워드 통계"""
        dialog = QDialog(self)
        dialog.setWindowTitle("뉴스 분석")
        dialog.resize(600, 500)
        
        # 다이얼로그 내 위젯들이 테마 스타일을 확실히 따르도록 함
        
        layout = QVBoxLayout(dialog)
        
        # 탭 선택
        tab_label = QLabel("분석할 탭을 선택하세요:")
        layout.addWidget(tab_label)
        
        tab_combo = QComboBox()
        tab_combo.addItem("전체", None)
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w and hasattr(w, 'keyword'):
                tab_combo.addItem(w.keyword, w.keyword)
        layout.addWidget(tab_combo)
        
        # 결과 표시
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
                    # 텍스트 포맷팅
                    result_list.addItem(f"{i}. {pub}: {count:,}개")
            else:
                result_list.addItem("데이터가 없습니다.")
        
        tab_combo.currentIndexChanged.connect(update_analysis)
        update_analysis()
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(dialog.accept)
        layout.addWidget(btn_close)
        
        dialog.exec()

    def open_settings(self):
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
        self.timer.stop()
        idx = self.interval_idx
        minutes = [10, 30, 60, 180, 360]
        
        if 0 <= idx < len(minutes):
            ms = minutes[idx] * 60 * 1000
            self.timer.start(ms)
            self.statusBar().showMessage(f"⏰ 자동 새로고침: {minutes[idx]}분 간격")
        else:
            self.statusBar().showMessage("⏰ 자동 새로고침 꺼짐")

    def closeEvent(self, event):
        # 작업 중인 스레드 안전하게 종료
        for keyword, (worker, thread) in list(self.workers.items()):
            worker.stop()
            thread.quit()
            thread.wait(1000)
        
        self.save_config()
        self.db.close()
        super().closeEvent(event)

# --- 설정 다이얼로그 ---
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(500, 400)
        self.config = config
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
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
        
        form.addWidget(QLabel("Client ID:"), 0, 0)
        form.addWidget(self.txt_id, 0, 1, 1, 2)
        form.addWidget(QLabel("Client Secret:"), 1, 0)
        form.addWidget(self.txt_sec, 1, 1, 1, 2)
        form.addWidget(self.chk_show_pw, 2, 1)
        form.addWidget(btn_get_key, 3, 0, 1, 3)
        
        gp_api.setLayout(form)
        layout.addWidget(gp_api)
        
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
        layout.addWidget(gp_app)
        
        gp_data = QGroupBox("🗂 데이터 관리")
        vbox = QVBoxLayout()
        
        btn_clean = QPushButton("🧹 오래된 데이터 정리 (30일 이전)")
        btn_clean.clicked.connect(self.clean_data)
        
        btn_all = QPushButton("🗑 모든 기사 삭제 (북마크 제외)")
        btn_all.clicked.connect(self.clean_all)
        
        vbox.addWidget(btn_clean)
        vbox.addWidget(btn_all)
        gp_data.setLayout(vbox)
        layout.addWidget(gp_data)
        
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def clean_data(self):
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

    def get_data(self):
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex()
        }

# --- 메인 실행 ---
def main():
    sys.excepthook = lambda cls, exc, tb: traceback.print_exception(cls, exc, tb)
    
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    
    window = MainApp()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
