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

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextBrowser, QLabel, QMessageBox,
    QTabWidget, QInputDialog, QComboBox, QFileDialog, QSystemTrayIcon,
    QMenu, QStyle, QTabBar, QDialog, QDialogButtonBox, QGroupBox,
    QGridLayout, QProgressBar
)
from PyQt6.QtCore import QThread, QObject, pyqtSignal, pyqtSlot, Qt, QTimer, QUrl, QMutex, QSize
from PyQt6.QtGui import QDesktopServices, QIcon, QAction

# --- 상수 및 설정 ---
CONFIG_FILE = "news_scraper_config.json"
DB_FILE = "news_database.db"
APP_NAME = "뉴스 스크래퍼 Pro (Final)"
VERSION = "24.0" # 날짜 형식 한국어화 (최종 완성)

# --- 커스텀 브라우저 (화면 사라짐 방지 핵심 클래스) ---
class NewsBrowser(QTextBrowser):
    """
    링크 클릭 시 페이지 이동을 원천 차단하고 시그널만 발생시키는 브라우저.
    '공유' 버튼 클릭 시 화면이 하얗게 변하는 문제를 방지합니다.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # 중요: 외부 링크 자동 열기를 끄고, 내부 링크 이동도 차단합니다.
        self.setOpenExternalLinks(False)  
        self.setOpenLinks(False) 

    def setSource(self, url):
        # app 스키마는 로직 처리용이므로 화면 이동을 수행하지 않음
        if url.scheme() == 'app':
            return
        super().setSource(url)

# --- 스타일시트 (UI 디자인 및 레이아웃) ---
class AppStyle:
    # 라이트 모드 색상
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
        QTextBrowser { font-family: '맑은 고딕'; background-color: #FFFFFF; border: 1px solid #DCDCDC; border-radius: 8px; }
        QTabWidget::pane { border-top: 1px solid #DCDCDC; }
        QTabBar::tab { font-family: '맑은 고딕'; font-size: 10pt; color: #333; padding: 10px 15px; border: 1px solid transparent; border-bottom: none; background-color: transparent; }
        QTabBar::tab:selected { background-color: #FFFFFF; border-color: #DCDCDC; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #000; font-weight: bold; }
        QTabBar::tab:!selected { color: #777; }
        QTabBar::tab:!selected:hover { color: #333; }
        QLineEdit { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px 8px; border-radius: 6px; border: 1px solid #ccc; background-color: #FFFFFF; color: #000000; }
        QLineEdit#FilterActive { border: 2px solid #007AFF; background-color: #F0F8FF; }
        QProgressBar { border: 1px solid #DCDCDC; border-radius: 3px; text-align: center; background-color: #FFFFFF; }
        QProgressBar::chunk { background-color: #007AFF; }
    """
    
    # 다크 모드 색상
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
        QTextBrowser { font-family: '맑은 고딕'; background-color: #3C3C3C; border: 1px solid #606060; border-radius: 8px; color: #E0E0E0; }
        QTabWidget::pane { border-top: 1px solid #606060; }
        QTabBar::tab { font-family: '맑은 고딕'; font-size: 10pt; color: #CCCCCC; padding: 10px 15px; border: 1px solid transparent; border-bottom: none; background-color: transparent; }
        QTabBar::tab:selected { background-color: #3C3C3C; border-color: #606060; border-top-left-radius: 6px; border-top-right-radius: 6px; color: #FFFFFF; font-weight: bold; }
        QTabBar::tab:!selected { color: #AAAAAA; }
        QTabBar::tab:!selected:hover { color: #FFFFFF; }
        QLineEdit { font-family: '맑은 고딕'; font-size: 10pt; padding: 5px 8px; border-radius: 6px; border: 1px solid #606060; background-color: #4A4A4A; color: #E0E0E0; }
        QLineEdit#FilterActive { border: 2px solid #0A84FF; background-color: #2A3A4A; }
        QProgressBar { border: 1px solid #606060; border-radius: 3px; text-align: center; background-color: #3C3C3C; color: #E0E0E0; }
        QProgressBar::chunk { background-color: #0A84FF; }
    """

    # HTML 템플릿 (가독성 개선 + 한국어 폰트 최적화)
    HTML_TEMPLATE = """
    <style>
        body {{ font-family: '맑은 고딕', sans-serif; margin: 5px; color: {text_color}; }}
        a {{ text-decoration: none; color: {link_color}; transition: color 0.2s; }}
        a:hover {{ color: {link_hover}; }}
        /* 뉴스 카드 스타일: 여백을 늘려 가독성 확보 */
        .news-item {{ 
            border: 1px solid {border_color}; 
            border-radius: 10px; 
            padding: 20px; 
            margin-bottom: 20px; 
            background-color: {bg_color}; 
            transition: box-shadow 0.2s;
        }}
        .news-item:hover {{ box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
        .news-item.read {{ background-color: {read_bg}; opacity: 0.7; }}
        
        .title-link {{ font-size: 13pt; font-weight: bold; color: {title_color}; line-height: 1.4; }}
        .meta-info {{ font-size: 9.5pt; color: {meta_color}; margin-top: 8px; border-bottom: 1px solid {border_color}; padding-bottom: 8px; margin-bottom: 8px; }}
        .description {{ margin-top: 0px; line-height: 1.7; color: {desc_color}; font-size: 10.5pt; }}
        
        .actions {{ float: right; font-size: 9.5pt; white-space: nowrap; }}
        .actions a {{ margin-left: 12px; }}
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
        if not hasattr(self.local, 'conn'):
            self.local.conn = sqlite3.connect(self.db_file, timeout=30.0)
            self.local.conn.execute("PRAGMA journal_mode=WAL") 
            self.local.conn.execute("PRAGMA synchronous=NORMAL")
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
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_keyword ON news(keyword)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarked ON news(is_bookmarked)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON news(pubDate_ts)")
        conn.close()

    def upsert_news(self, items, keyword):
        conn = self.get_conn()
        added_count = 0
        self.mutex.lock()
        try:
            with conn:
                for item in items:
                    ts = 0.0
                    try: ts = parsedate_to_datetime(item['pubDate']).timestamp()
                    except: pass
                    try:
                        cur = conn.execute("""
                            INSERT OR IGNORE INTO news (link, keyword, title, description, pubDate, publisher, data, pubDate_ts)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (item['link'], keyword, item['title'], item['description'], 
                              item['pubDate'], item['publisher'], json.dumps(item), ts))
                        if cur.rowcount > 0: added_count += 1
                    except: pass
        finally:
            self.mutex.unlock()
        return added_count

    def fetch_news(self, keyword, filter_txt, sort_mode, only_bookmark=False):
        conn = self.get_conn()
        query = "SELECT * FROM news WHERE 1=1"
        params = []

        if only_bookmark:
            query += " AND is_bookmarked = 1"
        else:
            query += " AND keyword = ?"
            params.append(keyword)

        if filter_txt:
            query += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{filter_txt}%", f"%{filter_txt}%"])
            
        order = "DESC" if sort_mode == "최신순" else "ASC"
        query += f" ORDER BY pubDate_ts {order} LIMIT 1000"

        self.mutex.lock()
        try:
            cursor = conn.execute(query, tuple(params))
            cols = [d[0] for d in cursor.description]
            return [dict(zip(cols, row)) for row in cursor.fetchall()]
        finally:
            self.mutex.unlock()

    def get_counts(self, keyword):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news WHERE keyword=?", (keyword,))
            return cursor.fetchone()[0] or 0
        except: return 0
        finally: self.mutex.unlock()

    def get_unread_count(self, keyword):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM news WHERE keyword=? AND is_read=0", (keyword,))
            return cursor.fetchone()[0] or 0
        except: return 0
        finally: self.mutex.unlock()

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

    def delete_old_news(self, days):
        conn = self.get_conn()
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        self.mutex.lock()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0 AND pubDate_ts < ?", (cutoff,))
                return cur.rowcount
        finally: self.mutex.unlock()

    def delete_all_news(self):
        conn = self.get_conn()
        self.mutex.lock()
        try:
            with conn:
                cur = conn.execute("DELETE FROM news WHERE is_bookmarked=0")
                return cur.rowcount
        finally: self.mutex.unlock()

    def close(self):
        if hasattr(self.local, 'conn'): self.local.conn.close()

# --- API 워커 ---
class ApiWorker(QObject):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, client_id, client_secret, keyword, exclude, start_idx=1):
        super().__init__()
        self.cid = client_id
        self.csec = client_secret
        self.keyword = keyword
        self.exclude = exclude
        self.start = start_idx
        self.is_running = True

    def run(self):
        if not self.is_running: return
        try:
            headers = {"X-Naver-Client-Id": self.cid.strip(), "X-Naver-Client-Secret": self.csec.strip()}
            url = "https://openapi.naver.com/v1/search/news.json"
            params = {"query": self.keyword, "display": 100, "start": self.start, "sort": "date"}
            
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                raise Exception(f"API Error {resp.status_code}: {resp.json().get('errorMessage', '')}")
            
            data = resp.json()
            items = []
            for item in data.get('items', []):
                if not self.is_running: break
                title = html.unescape(item['title']).replace('<b>','').replace('</b>','')
                desc = html.unescape(item['description']).replace('<b>','').replace('</b>','')
                
                if self.exclude and any(ex in title or ex in desc for ex in self.exclude): continue
                
                # [링크 로직 개선]
                naver_link = item.get('link', '')
                org_link = item.get('originallink', '')
                
                final_link = ""
                if "news.naver.com" in naver_link:
                    final_link = naver_link
                elif "news.naver.com" in org_link:
                    final_link = org_link
                else:
                    final_link = naver_link if naver_link else org_link

                # [출처 표시 개선] 원본 링크 우선
                publisher = "정보 없음"
                if org_link:
                    publisher = urllib.parse.urlparse(org_link).netloc.replace('www.', '')
                elif final_link:
                    if "news.naver.com" in final_link:
                         publisher = "네이버뉴스"
                    else:
                         publisher = urllib.parse.urlparse(final_link).netloc.replace('www.', '')
                
                items.append({
                    'title': title, 'description': desc, 'link': final_link, 
                    'pubDate': item['pubDate'], 'publisher': publisher
                })
            
            self.finished.emit({'items': items, 'total': data.get('total', 0)})

        except Exception as e:
            self.error.emit(str(e))

    def stop(self):
        self.is_running = False

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
        
        self.setup_ui()
        self.load_data_from_db()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 0)
        
        top_layout = QHBoxLayout()
        self.inp_filter = QLineEdit()
        self.inp_filter.setPlaceholderText("결과 내에서 필터링...")
        self.inp_filter.textChanged.connect(self.refresh_ui_only)
        
        self.combo_sort = QComboBox()
        self.combo_sort.addItems(["최신순", "오래된순"])
        self.combo_sort.currentIndexChanged.connect(self.load_data_from_db)
        
        top_layout.addWidget(self.inp_filter)
        top_layout.addWidget(self.combo_sort)
        layout.addLayout(top_layout)
        
        # [중요] 커스텀 브라우저 사용
        self.browser = NewsBrowser()
        self.browser.setOpenExternalLinks(False)
        self.browser.setOpenLinks(False) # 화면 이동 원천 차단
        self.browser.anchorClicked.connect(self.on_link_clicked)
        layout.addWidget(self.browser)
        
        btm_layout = QHBoxLayout()
        self.btn_load = QPushButton("더 불러오기")
        self.btn_read_all = QPushButton("모두 읽음으로")
        self.btn_top = QPushButton("맨 위로")
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
        if filter_txt: self.inp_filter.setObjectName("FilterActive")
        else: self.inp_filter.setObjectName("")
        self.inp_filter.setStyle(self.inp_filter.style())
        
        self.news_data = self.db.fetch_news(
            keyword=self.keyword,
            filter_txt=filter_txt,
            sort_mode=self.combo_sort.currentText(),
            only_bookmark=self.is_bookmark_tab
        )
        self.render_html()

    def refresh_ui_only(self):
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

        css = AppStyle.HTML_TEMPLATE.format(
            text_color=text_color, link_color=link_color, link_hover=link_hover,
            border_color=border_color, bg_color=bg_color, read_bg=read_bg,
            title_color=title_color, meta_color=meta_color, desc_color=desc_color
        )
        
        html_parts = [f"<html><head>{css}</head><body>"]
        
        if not self.news_data:
            msg = "북마크된 기사가 없습니다." if self.is_bookmark_tab else "표시할 뉴스 기사가 없습니다."
            html_parts.append(f"<div style='text-align:center; padding:20px; color:{meta_color}'>{msg}</div>")
        else:
            filter_word = self.inp_filter.text()
            for item in self.news_data:
                if filter_word and (filter_word not in item['title'] and filter_word not in item['description']):
                    continue

                is_read_cls = " read" if item['is_read'] else ""
                title_pfx = "⭐ " if item['is_bookmarked'] else ""
                link_hash = hashlib.md5(item['link'].encode()).hexdigest()
                
                title = html.escape(item['title'])
                desc = html.escape(item['description'])
                
                if filter_word:
                    hl = f"<span style='background-color: #FCD34D; color: black;'>{filter_word}</span>"
                    title = title.replace(filter_word, hl)
                    desc = desc.replace(filter_word, hl)

                bk_txt = "[북마크 해제]" if item['is_bookmarked'] else "[북마크]"
                bk_col = "#DC3545" if item['is_bookmarked'] else "#17A2B8"
                
                # [날짜 형식 한국어화]
                date_str = item.get('pubDate', '')
                try: 
                    dt = parsedate_to_datetime(date_str)
                    date_str = dt.strftime('%Y년 %m월 %d일 %H:%M')
                except: pass

                # URL 구조: app://action/hash
                actions = f"""
                    <a href='app://share/{link_hash}'>[공유]</a>
                    <a href='app://ext/{link_hash}'>[외부에서 열기]</a>
                """
                if item['is_read']:
                    actions += f"<a href='app://unread/{link_hash}'>[안 읽음]</a> "
                actions += f"<a href='app://bm/{link_hash}' style='color:{bk_col}'>{bk_txt}</a>"

                # [UI 간격 개선]
                html_parts.append(f"""
                <div class="news-item{is_read_cls}">
                    <div><a href="app://open/{link_hash}" class="title-link">{title_pfx}{title}</a></div>
                    <div class="meta-info">
                        {item['publisher']} | {date_str}
                        <span class="actions">{actions}</span>
                    </div>
                    <div class="description">{desc}</div>
                </div>
                """)
        
        html_parts.append("</body></html>")
        self.browser.setHtml("".join(html_parts))
        self.browser.verticalScrollBar().setValue(scroll_pos)
        
        cnt = len(self.news_data)
        if not self.is_bookmark_tab:
            unread = self.db.get_unread_count(self.keyword)
            msg = f"'{self.keyword}': 총 {self.total_api_count}개 중 {cnt}개 표시"
            if unread > 0: msg += f" (안 읽음: {unread}개)"
            self.lbl_status.setText(msg)
        else:
            self.lbl_status.setText(f"북마크 {cnt}개 표시됨")

    def on_link_clicked(self, url):
        scheme = url.scheme()
        if scheme != "app": return

        action = url.host()
        link_hash = url.path().lstrip('/')
        
        target = next((i for i in self.news_data if hashlib.md5(i['link'].encode()).hexdigest() == link_hash), None)
        if not target: return

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
                self.render_html()
                if self.window() and hasattr(self.window(), 'refresh_bookmark_tab'):
                    self.window().refresh_bookmark_tab()
        elif action == "share":
            clip = f"{target['title']}\n{target['link']}"
            QApplication.clipboard().setText(clip)
            if self.window():
                self.window().statusBar().showMessage("클립보드에 복사되었습니다.", 2000)
            return # 화면 갱신 차단
        elif action == "unread":
            self.db.update_status(link, "is_read", 0)
            target['is_read'] = 0
            self.render_html()
        elif action == "ext":
            QDesktopServices.openUrl(QUrl(link))
            return # 화면 갱신 차단

    def mark_all_read(self):
        conn = self.db.get_conn()
        with conn:
            if self.is_bookmark_tab:
                conn.execute("UPDATE news SET is_read=1 WHERE is_bookmarked=1")
            else:
                conn.execute("UPDATE news SET is_read=1 WHERE keyword=?", (self.keyword,))
        self.load_data_from_db()

# --- 메인 윈도우 ---
class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = DatabaseManager(DB_FILE)
        self.workers = {}
        self.load_config()
        self.init_ui()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.apply_refresh_interval()
        
        if self.client_id and self.tabs.count() > 1:
             QTimer.singleShot(500, self.refresh_all)

    def load_config(self):
        self.config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config = json.load(f)
            except: pass
        
        if "app_settings" in self.config:
            settings = self.config["app_settings"]
            self.client_id = settings.get('client_id', '')
            self.client_secret = settings.get('client_secret', '')
            self.theme_idx = settings.get('theme_index', 0)
            self.interval_idx = settings.get('refresh_interval_index', 2)
            self.tabs_data = self.config.get('tabs', [])
        else:
            self.client_id = self.config.get('id', '')
            self.client_secret = self.config.get('secret', '')
            self.theme_idx = self.config.get('theme', 0)
            self.interval_idx = self.config.get('interval', 2)
            self.tabs_data = self.config.get('tabs', [])

    def save_config(self):
        tab_names = []
        for i in range(1, self.tabs.count()):
            tab_names.append(self.tabs.widget(i).keyword)
        data = {
            'id': self.client_id,
            'secret': self.client_secret,
            'theme': self.theme_idx,
            'interval': self.interval_idx,
            'tabs': tab_names
        }
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)

    def init_ui(self):
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.resize(900, 750)
        self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(15, 15, 15, 15)
        
        hbox = QHBoxLayout()
        self.btn_refresh = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload), " 새로고침")
        self.btn_save = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton), " 결과 저장")
        self.btn_setting = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView), " 설정")
        self.btn_folder = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon), " 설정 폴더")
        self.btn_add = QPushButton(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon), "+ 새 탭 추가")
        self.btn_add.setObjectName("AddTab")
        
        self.refresh_interval_combo = QComboBox()
        self.refresh_interval_combo.addItems(["10분", "30분", "1시간", "3시간", "6시간", "자동 새로고침 안함"])
        self.refresh_interval_combo.hide()
        
        hbox.addWidget(self.btn_refresh)
        hbox.addWidget(self.btn_save)
        hbox.addWidget(self.btn_setting)
        hbox.addWidget(self.btn_folder)
        hbox.addStretch(1)
        hbox.addWidget(self.btn_add)
        layout.addLayout(hbox)
        
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
        self.btn_folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(os.path.abspath(CONFIG_FILE)))))
        self.btn_add.clicked.connect(self.add_tab_dialog)
        self.btn_save.clicked.connect(self.export_data)
        
        self.bm_tab = NewsTab("북마크", self.db, self.theme_idx, self)
        self.tabs.addTab(self.bm_tab, self.style().standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon), "북마크")
        self.tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, None)
        
        for key in self.tabs_data:
            self.add_news_tab(key)
            
        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray.show()

    def add_news_tab(self, keyword):
        for i in range(self.tabs.count()):
            if getattr(self.tabs.widget(i), 'keyword', '') == keyword:
                self.tabs.setCurrentIndex(i)
                return
        
        tab = NewsTab(keyword, self.db, self.theme_idx, self)
        tab.btn_load.clicked.connect(lambda: self.fetch_news(keyword, is_more=True))
        self.tabs.addTab(tab, keyword)

    def add_tab_dialog(self):
        text, ok = QInputDialog.getText(self, "탭 추가", "검색 키워드 입력 (예: 주식 -코인)")
        if ok and text:
            self.add_news_tab(text)
            self.fetch_news(text)

    def close_tab(self, idx):
        if idx == 0: return
        widget = self.tabs.widget(idx)
        widget.deleteLater()
        self.tabs.removeTab(idx)

    def rename_tab(self, idx):
        if idx == 0: return
        w = self.tabs.widget(idx)
        text, ok = QInputDialog.getText(self, '이름 변경', '새 키워드:', text=w.keyword)
        if ok and text:
            w.keyword = text
            self.tabs.setTabText(idx, text)
            self.fetch_news(text)

    def refresh_all(self):
        if not self.client_id:
            self.statusBar().showMessage("설정에서 API 키를 먼저 입력해주세요.")
            self.open_settings()
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.statusBar().showMessage("모든 탭 업데이트 중...")
        
        self.bm_tab.load_data_from_db()
        for i in range(1, self.tabs.count()):
            keyword = self.tabs.widget(i).keyword
            self.fetch_news(keyword)

    def fetch_news(self, keyword, is_more=False):
        start_idx = 1
        if is_more:
            start_idx = self.db.get_counts(keyword)[0] + 1
            if start_idx > 1000:
                self.statusBar().showMessage("최대 검색 한도 도달")
                return

        worker = ApiWorker(self.client_id, self.client_secret, keyword.split()[0], [], start_idx)
        thread = QThread()
        worker.moveToThread(thread)
        self.workers[keyword] = (worker, thread)
        
        worker.finished.connect(lambda res: self.on_fetch_done(res, keyword, is_more))
        worker.error.connect(lambda err: self.statusBar().showMessage(f"오류 ({keyword}): {err}"))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self.workers.pop(keyword, None))
        
        thread.started.connect(worker.run)
        thread.start()

    def on_fetch_done(self, result, keyword, is_more):
        count = self.db.upsert_news(result['items'], keyword)
        for i in range(1, self.tabs.count()):
            w = self.tabs.widget(i)
            if w.keyword == keyword:
                w.total_api_count = result['total']
                w.load_data_from_db()
                w.lbl_status.setText(f"업데이트: {datetime.now().strftime('%H:%M:%S')} (+{count}건)")
                break
        
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        if not is_more:
            self.statusBar().showMessage(f"'{keyword}' 업데이트 완료 ({count}건 추가)", 3000)

    def refresh_bookmark_tab(self):
        self.bm_tab.load_data_from_db()

    def export_data(self):
        cur_widget = self.tabs.currentWidget()
        if not cur_widget.news_data:
            QMessageBox.information(self, "알림", "저장할 뉴스가 없습니다.")
            return
            
        fname, _ = QFileDialog.getSaveFileName(self, "저장", f"{cur_widget.keyword}_뉴스.csv", "CSV Files (*.csv);;Text Files (*.txt)")
        if fname:
            try:
                with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['제목', '링크', '날짜', '출처', '요약'])
                    for item in cur_widget.news_data:
                        writer.writerow([item['title'], item['link'], item['pubDate'], item['publisher'], item['description']])
                self.statusBar().showMessage("저장 완료", 3000)
            except Exception as e:
                QMessageBox.warning(self, "오류", str(e))

    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            data = dlg.get_data()
            self.client_id = data['id']
            self.client_secret = data['secret']
            self.interval_idx = data['interval']
            self.theme_idx = data['theme']
            
            self.setStyleSheet(AppStyle.DARK if self.theme_idx == 1 else AppStyle.LIGHT)
            self.refresh_interval_combo.setCurrentIndex(self.interval_idx)
            self.apply_refresh_interval()
            self.save_config()
            
            for i in range(self.tabs.count()):
                self.tabs.widget(i).theme = self.theme_idx
                self.tabs.widget(i).render_html()

    def apply_refresh_interval(self):
        self.timer.stop()
        idx = self.interval_idx
        minutes = [10, 30, 60, 180, 360]
        if 0 <= idx < len(minutes):
            ms = minutes[idx] * 60 * 1000
            self.timer.start(ms)
            self.statusBar().showMessage(f"자동 새로고침: {minutes[idx]}분 간격")
        else:
            self.statusBar().showMessage("자동 새로고침 꺼짐")

    def closeEvent(self, event):
        self.save_config()
        self.db.close()
        super().closeEvent(event)

class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.resize(450, 300)
        self.config = config
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        gp_api = QGroupBox("네이버 API 설정")
        form = QGridLayout()
        self.txt_id = QLineEdit(self.config.get('id', '') or self.config.get('client_id', ''))
        self.txt_sec = QLineEdit(self.config.get('secret', '') or self.config.get('client_secret', ''))
        self.txt_sec.setEchoMode(QLineEdit.EchoMode.Password)
        
        form.addWidget(QLabel("Client ID:"), 0, 0)
        form.addWidget(self.txt_id, 0, 1)
        form.addWidget(QLabel("Client Secret:"), 1, 0)
        form.addWidget(self.txt_sec, 1, 1)
        gp_api.setLayout(form)
        layout.addWidget(gp_api)
        
        gp_app = QGroupBox("일반 설정")
        form2 = QGridLayout()
        self.cb_time = QComboBox()
        self.cb_time.addItems(["10분", "30분", "1시간", "3시간", "6시간", "자동 새로고침 안함"])
        idx = self.config.get('interval', 2)
        if isinstance(idx, int) and 0 <= idx <= 5:
            self.cb_time.setCurrentIndex(idx)
        else:
            self.cb_time.setCurrentIndex(2)
        
        self.cb_theme = QComboBox()
        self.cb_theme.addItems(["라이트 모드", "다크 모드"])
        self.cb_theme.setCurrentIndex(self.config.get('theme', 0))
        
        form2.addWidget(QLabel("새로고침 간격:"), 0, 0)
        form2.addWidget(self.cb_time, 0, 1)
        form2.addWidget(QLabel("테마:"), 1, 0)
        form2.addWidget(self.cb_theme, 1, 1)
        gp_app.setLayout(form2)
        layout.addWidget(gp_app)
        
        gp_data = QGroupBox("데이터 관리")
        vbox = QVBoxLayout()
        btn_clean = QPushButton("오래된 데이터 정리 (30일)")
        btn_clean.clicked.connect(self.clean_data)
        btn_all = QPushButton("모든 기사 삭제 (북마크 제외)")
        btn_all.clicked.connect(self.clean_all)
        vbox.addWidget(btn_clean)
        vbox.addWidget(btn_all)
        gp_data.setLayout(vbox)
        layout.addWidget(gp_data)
        
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def clean_data(self):
        db = DatabaseManager(DB_FILE)
        cnt = db.delete_old_news(30)
        QMessageBox.information(self, "완료", f"{cnt}개의 오래된 기사를 삭제했습니다.")
        db.close()

    def clean_all(self):
        if QMessageBox.question(self, "경고", "정말 모든 기사를 삭제하시겠습니까?") == QMessageBox.StandardButton.Yes:
            db = DatabaseManager(DB_FILE)
            cnt = db.delete_all_news()
            QMessageBox.information(self, "완료", f"{cnt}개의 기사를 삭제했습니다.")
            db.close()

    def get_data(self):
        return {
            'id': self.txt_id.text().strip(),
            'secret': self.txt_sec.text().strip(),
            'interval': self.cb_time.currentIndex(),
            'theme': self.cb_theme.currentIndex()
        }

def main():
    sys.excepthook = lambda cls, exc, tb: traceback.print_exception(cls, exc, tb)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
