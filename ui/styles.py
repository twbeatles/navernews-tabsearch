from typing import Dict
from enum import Enum

# --- 색상 상수 (중앙화) ---
class Colors:
    """앱 전체에서 사용되는 색상 상수 - 현대화된 팔레트"""
    # 라이트 테마 - Tailwind CSS 인디고 기반
    LIGHT_PRIMARY = "#6366F1"          # 인디고 500
    LIGHT_PRIMARY_HOVER = "#4F46E5"    # 인디고 600
    LIGHT_PRIMARY_LIGHT = "#E0E7FF"    # 인디고 100
    LIGHT_SECONDARY = "#64748B"        # 슬레이트 500
    LIGHT_SUCCESS = "#10B981"          # 에메랄드 500
    LIGHT_SUCCESS_LIGHT = "#D1FAE5"    # 에메랄드 100
    LIGHT_WARNING = "#F59E0B"          # 앰버 500
    LIGHT_DANGER = "#EF4444"           # 레드 500
    LIGHT_INFO = "#06B6D4"             # 시안 500
    LIGHT_BG = "#F8FAFC"               # 슬레이트 50
    LIGHT_CARD_BG = "#FFFFFF"
    LIGHT_BORDER = "#E2E8F0"           # 슬레이트 200
    LIGHT_TEXT = "#1E293B"             # 슬레이트 800
    LIGHT_TEXT_MUTED = "#94A3B8"       # 슬레이트 400
    
    # 다크 테마 - 깊은 슬레이트 기반
    DARK_PRIMARY = "#818CF8"           # 인디고 400
    DARK_PRIMARY_HOVER = "#A5B4FC"     # 인디고 300
    DARK_PRIMARY_LIGHT = "#312E81"     # 인디고 900
    DARK_SECONDARY = "#64748B"         # 슬레이트 500
    DARK_SUCCESS = "#34D399"           # 에메랄드 400
    DARK_WARNING = "#FBBF24"           # 앰버 400
    DARK_DANGER = "#F87171"            # 레드 400
    DARK_INFO = "#22D3EE"              # 시안 400
    DARK_BG = "#0F172A"                # 슬레이트 900
    DARK_CARD_BG = "#1E293B"           # 슬레이트 800
    DARK_BORDER = "#334155"            # 슬레이트 700
    DARK_TEXT = "#F1F5F9"              # 슬레이트 100
    DARK_TEXT_MUTED = "#94A3B8"        # 슬레이트 400
    
    # 공통 색상
    HIGHLIGHT = "#FCD34D"              # 앰버 300
    BOOKMARK = "#FBBF24"               # 앰버 400
    DUPLICATE = "#FB923C"              # 오렌지 400
    
    @classmethod
    def get_html_colors(cls, is_dark: bool) -> Dict[str, str]:
        """HTML 렌더링용 테마별 색상 딕셔너리 반환 - 현대화된 팔레트"""
        if is_dark:
            return {
                'text_color': "#F1F5F9",        # 슬레이트 100
                'link_color': "#818CF8",        # 인디고 400
                'link_hover': "#A5B4FC",        # 인디고 300
                'accent_color': "#34D399",      # 에메랄드 400
                'border_color': "#475569",      # 슬레이트 600
                'bg_color': "#1E293B",          # 슬레이트 800
                'bg_gradient': "#0F172A",       # 슬레이트 900
                'bg_hover': "#334155",          # 슬레이트 700
                'read_bg': "#0F172A",           # 슬레이트 900
                'title_color': "#F1F5F9",       # 슬레이트 100
                'meta_color': "#94A3B8",        # 슬레이트 400
                'desc_color': "#CBD5E1",        # 슬레이트 300
                'tag_bg': "#6366F1",            # 인디고 500
                'tag_color': "#FFFFFF",
                'action_bg': "rgba(129, 140, 248, 0.12)",
                'action_bg_end': "rgba(129, 140, 248, 0.08)",
                'action_hover': "rgba(129, 140, 248, 0.25)",
                'bookmark_bg': "#6366F1",       # 인디고 500
                'bookmark_end': "#34D399",      # 에메랄드 400
                'empty_bg': "rgba(255, 255, 255, 0.03)",
                'scrollbar_track': "#1E293B",   # 슬레이트 800
                'scrollbar_thumb': "#475569"    # 슬레이트 600
            }
        else:
            return {
                'text_color': "#1E293B",        # 슬레이트 800
                'link_color': "#6366F1",        # 인디고 500
                'link_hover': "#4F46E5",        # 인디고 600
                'accent_color': "#10B981",      # 에메랄드 500
                'border_color': "#E2E8F0",      # 슬레이트 200
                'bg_color': "#FFFFFF",
                'bg_gradient': "#F8FAFC",       # 슬레이트 50
                'bg_hover': "#EEF2FF",          # 인디고 50
                'read_bg': "#F1F5F9",           # 슬레이트 100
                'title_color': "#0F172A",       # 슬레이트 900
                'meta_color': "#64748B",        # 슬레이트 500
                'desc_color': "#475569",        # 슬레이트 600
                'tag_bg': "#6366F1",            # 인디고 500
                'tag_color': "#FFFFFF",
                'action_bg': "rgba(99, 102, 241, 0.08)",
                'action_bg_end': "rgba(99, 102, 241, 0.04)",
                'action_hover': "rgba(99, 102, 241, 0.18)",
                'bookmark_bg': "#6366F1",       # 인디고 500
                'bookmark_end': "#10B981",      # 에메랄드 500
                'empty_bg': "rgba(0, 0, 0, 0.02)",
                'scrollbar_track': "#F1F5F9",   # 슬레이트 100
                'scrollbar_thumb': "#CBD5E1"    # 슬레이트 300
            }


# --- UI 상수 ---
class UIConstants:
    """UI 관련 상수"""
    CARD_PADDING = "16px 20px"
    BORDER_RADIUS = "10px"
    ANIMATION_DURATION = 300
    TOAST_DURATION = 2500
    MAX_PREVIEW_LENGTH = 200
    TAB_BADGE_NEW = "🔵"
    TAB_BADGE_UNREAD = "🟠"
    FIRST_RUN_KEY = "first_run_completed"


# --- 토스트 메시지 유형 ---
class ToastType(Enum):
    """토스트 메시지 유형"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"


# --- 스타일시트 (AppStyle) ---
class AppStyle:
    """애플리케이션 전체 스타일시트 및 HTML 템플릿"""
    
    LIGHT = f"""
        QMainWindow, QDialog {{ background-color: {Colors.LIGHT_BG}; }}
        QGroupBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif;
            font-size: 11pt;
            font-weight: 600;
            margin-top: 16px;
            padding: 20px 16px 16px 16px;
            border: 1px solid {Colors.LIGHT_BORDER};
            border-radius: 12px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {Colors.LIGHT_CARD_BG}, stop:1 {Colors.LIGHT_BG});
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            top: 4px;
            padding: 4px 12px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.LIGHT_PRIMARY}, stop:1 #8B5CF6);
            color: white;
            border-radius: 8px;
        }}
        QLabel, QDialog QLabel {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.LIGHT_TEXT}; 
        }}
        QPushButton {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            font-weight: 500;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 #FFFFFF, stop:1 {Colors.LIGHT_BG});
            color: {Colors.LIGHT_TEXT}; 
            padding: 10px 18px; 
            border-radius: 10px; 
            border: 1px solid {Colors.LIGHT_BORDER};
            min-width: 70px;
            margin: 0 4px;
        }}
        QPushButton:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {Colors.LIGHT_PRIMARY_LIGHT}, stop:1 #FFFFFF);
            border-color: {Colors.LIGHT_PRIMARY};
            color: {Colors.LIGHT_PRIMARY};
        }}
        QPushButton:pressed {{
            background: {Colors.LIGHT_PRIMARY_LIGHT};
            border-color: {Colors.LIGHT_PRIMARY};
        }}
        QPushButton:disabled {{ 
            background-color: {Colors.LIGHT_BG}; 
            color: {Colors.LIGHT_TEXT_MUTED}; 
            border-color: {Colors.LIGHT_BORDER};
        }}
        QPushButton#AddTab {{ 
            font-weight: bold; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.LIGHT_PRIMARY}, stop:1 #8B5CF6);
            color: white; 
            border: none; 
            padding: 12px 24px;
        }}
        QPushButton#AddTab:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.LIGHT_PRIMARY_HOVER}, stop:1 #7C3AED);
        }}
        QPushButton#RefreshBtn {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.LIGHT_SUCCESS}, stop:1 #34D399);
            color: white; 
            border: none; 
        }}
        QPushButton#RefreshBtn:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #059669, stop:1 #10B981);
        }}
        QComboBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            padding: 8px 12px; 
            border-radius: 10px; 
            border: 1px solid {Colors.LIGHT_BORDER}; 
            background-color: {Colors.LIGHT_CARD_BG}; 
            color: {Colors.LIGHT_TEXT};
            min-width: 90px;
        }}
        QComboBox:hover {{ border-color: {Colors.LIGHT_PRIMARY}; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox::down-arrow {{ 
            image: none; 
            border-left: 5px solid transparent; 
            border-right: 5px solid transparent; 
            border-top: 5px solid {Colors.LIGHT_TEXT_MUTED}; 
        }}
        QComboBox QAbstractItemView {{ 
            background-color: {Colors.LIGHT_CARD_BG}; 
            color: {Colors.LIGHT_TEXT}; 
            selection-background-color: {Colors.LIGHT_PRIMARY}; 
            selection-color: white; 
            border: 1px solid {Colors.LIGHT_BORDER}; 
            border-radius: 8px;
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{ padding: 8px; border-radius: 6px; }}
        QComboBox QAbstractItemView::item:hover {{ 
            background-color: {Colors.LIGHT_PRIMARY_LIGHT}; 
            color: {Colors.LIGHT_TEXT};
        }}
        QComboBox QAbstractItemView::item:selected {{ 
            background-color: {Colors.LIGHT_PRIMARY}; 
            color: white;
        }}
        QTextBrowser, QTextEdit, QListWidget {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            background-color: {Colors.LIGHT_CARD_BG}; 
            border: 1px solid {Colors.LIGHT_BORDER}; 
            border-radius: 12px; 
            color: {Colors.LIGHT_TEXT};
            padding: 12px;
        }}
        QListWidget::item:selected {{ 
            background-color: {Colors.LIGHT_PRIMARY}; 
            color: white; 
            border-radius: 6px; 
        }}
        QTabWidget::pane {{ 
            border: 1px solid {Colors.LIGHT_BORDER}; 
            border-radius: 12px;
            background-color: {Colors.LIGHT_CARD_BG};
            margin-top: -1px;
        }}
        QTabBar::tab {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.LIGHT_TEXT_MUTED}; 
            padding: 12px 20px; 
            min-height: 30px;
            border: 1px solid transparent; 
            border-bottom: none; 
            background-color: transparent;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{ 
            background-color: {Colors.LIGHT_CARD_BG}; 
            border-color: {Colors.LIGHT_BORDER}; 
            border-bottom: 3px solid {Colors.LIGHT_PRIMARY};
            border-top-left-radius: 10px; 
            border-top-right-radius: 10px; 
            color: {Colors.LIGHT_PRIMARY}; 
            font-weight: 600; 
        }}
        QTabBar::tab:!selected {{ color: {Colors.LIGHT_TEXT_MUTED}; }}
        QTabBar::tab:!selected:hover {{ 
            color: {Colors.LIGHT_TEXT}; 
            background-color: {Colors.LIGHT_PRIMARY_LIGHT}; 
            border-bottom: 2px solid rgba(99, 102, 241, 0.4);
            border-top-left-radius: 10px; 
            border-top-right-radius: 10px; 
        }}
        QLineEdit {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            padding: 10px 14px; 
            border-radius: 10px; 
            border: 1px solid {Colors.LIGHT_BORDER}; 
            background-color: {Colors.LIGHT_CARD_BG}; 
            color: {Colors.LIGHT_TEXT};
        }}
        QLineEdit:focus {{ 
            border: 2px solid {Colors.LIGHT_PRIMARY}; 
            padding: 9px 13px; 
            background-color: #FEFFFE;
        }}
        QLineEdit#FilterActive {{ 
            border: 2px solid {Colors.LIGHT_PRIMARY}; 
            background-color: {Colors.LIGHT_PRIMARY_LIGHT}; 
        }}
        QLineEdit::placeholder {{ color: {Colors.LIGHT_TEXT_MUTED}; }}
        QProgressBar {{ 
            border: none; 
            border-radius: 6px; 
            text-align: center; 
            background-color: {Colors.LIGHT_BORDER}; 
            color: {Colors.LIGHT_TEXT};
            height: 8px;
        }}
        QProgressBar::chunk {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.LIGHT_PRIMARY}, stop:1 {Colors.LIGHT_INFO});
            border-radius: 6px;
        }}
        QCheckBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.LIGHT_TEXT}; 
            spacing: 8px;
        }}
        QCheckBox::indicator {{ width: 22px; height: 22px; }}
        QCheckBox::indicator:unchecked {{ 
            border: 2px solid {Colors.LIGHT_BORDER}; 
            background-color: {Colors.LIGHT_CARD_BG}; 
            border-radius: 6px; 
        }}
        QCheckBox::indicator:checked {{ 
            border: none; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 {Colors.LIGHT_PRIMARY}, stop:1 #8B5CF6);
            border-radius: 6px; 
        }}
        QCheckBox::indicator:checked:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 {Colors.LIGHT_PRIMARY_HOVER}, stop:1 #7C3AED);
        }}
        QStatusBar {{ 
            background-color: {Colors.LIGHT_CARD_BG}; 
            border-top: 1px solid {Colors.LIGHT_BORDER}; 
            padding: 4px;
        }}
        QScrollBar:vertical {{ 
            background: {Colors.LIGHT_BG}; 
            width: 10px; 
            border-radius: 5px; 
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{ 
            background: {Colors.LIGHT_BORDER}; 
            border-radius: 5px; 
            min-height: 30px; 
        }}
        QScrollBar::handle:vertical:hover {{ background: {Colors.LIGHT_TEXT_MUTED}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """

    
    DARK = f"""
        QMainWindow, QDialog {{ background-color: {Colors.DARK_BG}; }}
        QGroupBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif;
            color: {Colors.DARK_TEXT}; 
            font-size: 11pt;
            font-weight: 600; 
            margin-top: 16px;
            padding: 20px 16px 16px 16px;
            border: none;
            border-radius: 12px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {Colors.DARK_CARD_BG}, stop:1 {Colors.DARK_BG});
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            top: 4px;
            padding: 4px 12px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.DARK_PRIMARY}, stop:1 #A78BFA);
            color: white;
            border-radius: 8px;
        }}
        QLabel, QDialog QLabel {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.DARK_TEXT}; 
        }}
        QPushButton {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt;
            font-weight: 500;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {Colors.DARK_CARD_BG}, stop:1 {Colors.DARK_BG});
            color: {Colors.DARK_TEXT}; 
            padding: 10px 18px; 
            border-radius: 10px; 
            border: 1px solid {Colors.DARK_BORDER};
            min-width: 70px;
            margin: 0 4px;
        }}
        QPushButton:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                stop:0 {Colors.DARK_BORDER}, stop:1 {Colors.DARK_CARD_BG});
            border-color: {Colors.DARK_PRIMARY};
            color: {Colors.DARK_PRIMARY};
        }}
        QPushButton:pressed {{
            background: {Colors.DARK_BORDER};
            border-color: {Colors.DARK_PRIMARY};
        }}
        QPushButton:disabled {{ 
            background-color: {Colors.DARK_BG}; 
            color: {Colors.DARK_TEXT_MUTED}; 
            border-color: {Colors.DARK_BORDER};
        }}
        QPushButton#AddTab {{ 
            font-weight: bold; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.DARK_PRIMARY}, stop:1 #A78BFA);
            color: white; 
            border: none; 
            padding: 12px 24px;
        }}
        QPushButton#AddTab:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.DARK_PRIMARY_HOVER}, stop:1 #C4B5FD);
        }}
        QPushButton#RefreshBtn {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.DARK_SUCCESS}, stop:1 #6EE7B7);
            color: #064E3B; 
            border: none; 
        }}
        QPushButton#RefreshBtn:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #6EE7B7, stop:1 {Colors.DARK_SUCCESS});
        }}
        QComboBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            padding: 8px 12px; 
            border-radius: 10px; 
            border: 1px solid {Colors.DARK_BORDER}; 
            background-color: {Colors.DARK_CARD_BG}; 
            color: {Colors.DARK_TEXT};
            min-width: 90px;
        }}
        QComboBox:hover {{ border-color: {Colors.DARK_PRIMARY}; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox::down-arrow {{ 
            image: none; 
            border-left: 5px solid transparent; 
            border-right: 5px solid transparent; 
            border-top: 5px solid {Colors.DARK_TEXT_MUTED}; 
        }}
        QComboBox QAbstractItemView {{ 
            background-color: {Colors.DARK_CARD_BG}; 
            color: {Colors.DARK_TEXT}; 
            selection-background-color: {Colors.DARK_PRIMARY}; 
            selection-color: white; 
            border: 1px solid {Colors.DARK_BORDER}; 
            border-radius: 8px;
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{ padding: 8px; border-radius: 6px; }}
        QComboBox QAbstractItemView::item:hover {{ 
            background-color: {Colors.DARK_BORDER}; 
            color: {Colors.DARK_TEXT};
        }}
        QComboBox QAbstractItemView::item:selected {{ 
            background-color: {Colors.DARK_PRIMARY}; 
            color: white;
        }}
        QTextBrowser, QTextEdit, QListWidget {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            background-color: {Colors.DARK_CARD_BG}; 
            border: 1px solid {Colors.DARK_BORDER}; 
            border-radius: 12px; 
            color: {Colors.DARK_TEXT};
            padding: 12px;
        }}
        QListWidget::item:selected {{ 
            background-color: {Colors.DARK_PRIMARY}; 
            color: white; 
            border-radius: 6px; 
        }}
        QTabWidget::pane {{ 
            border: 1px solid {Colors.DARK_BORDER}; 
            border-radius: 12px;
            background-color: {Colors.DARK_CARD_BG};
            margin-top: -1px;
        }}
        QTabBar::tab {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.DARK_TEXT_MUTED}; 
            padding: 12px 20px; 
            min-height: 30px;
            border: 1px solid transparent; 
            border-bottom: none; 
            background-color: transparent;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{ 
            background-color: {Colors.DARK_CARD_BG}; 
            border-color: {Colors.DARK_BORDER}; 
            border-bottom: 3px solid {Colors.DARK_PRIMARY};
            border-top-left-radius: 10px; 
            border-top-right-radius: 10px; 
            color: {Colors.DARK_PRIMARY}; 
            font-weight: 600; 
        }}
        QTabBar::tab:!selected {{ color: {Colors.DARK_TEXT_MUTED}; }}
        QTabBar::tab:!selected:hover {{ 
            color: {Colors.DARK_TEXT}; 
            background-color: {Colors.DARK_PRIMARY_LIGHT}; 
            border-bottom: 2px solid rgba(129, 140, 248, 0.4);
            border-top-left-radius: 10px; 
            border-top-right-radius: 10px; 
        }}
        QLineEdit {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            padding: 10px 14px; 
            border-radius: 10px; 
            border: 1px solid {Colors.DARK_BORDER}; 
            background-color: {Colors.DARK_CARD_BG}; 
            color: {Colors.DARK_TEXT};
        }}
        QLineEdit:focus {{ 
            border: 2px solid {Colors.DARK_PRIMARY}; 
            padding: 9px 13px; 
            background-color: {Colors.DARK_BORDER};
        }}
        QLineEdit#FilterActive {{ 
            border: 2px solid {Colors.DARK_PRIMARY}; 
            background-color: {Colors.DARK_PRIMARY_LIGHT}; 
        }}
        QLineEdit::placeholder {{ color: {Colors.DARK_TEXT_MUTED}; }}
        QProgressBar {{ 
            border: none; 
            border-radius: 6px; 
            text-align: center; 
            background-color: {Colors.DARK_BORDER}; 
            color: {Colors.DARK_TEXT};
            height: 8px;
        }}
        QProgressBar::chunk {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 {Colors.DARK_PRIMARY}, stop:1 {Colors.DARK_INFO});
            border-radius: 6px;
        }}
        QCheckBox {{ 
            font-family: '맑은 고딕', -apple-system, sans-serif; 
            font-size: 10pt; 
            color: {Colors.DARK_TEXT}; 
            spacing: 8px;
        }}
        QCheckBox::indicator {{ width: 22px; height: 22px; }}
        QCheckBox::indicator:unchecked {{ 
            border: 2px solid {Colors.DARK_BORDER}; 
            background-color: {Colors.DARK_BG}; 
            border-radius: 6px; 
        }}
        QCheckBox::indicator:checked {{ 
            border: none; 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 {Colors.DARK_PRIMARY}, stop:1 #A78BFA);
            border-radius: 6px; 
        }}
        QCheckBox::indicator:checked:hover {{ 
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                stop:0 {Colors.DARK_PRIMARY_HOVER}, stop:1 #C4B5FD);
        }}
        QStatusBar {{ 
            background-color: {Colors.DARK_CARD_BG}; 
            border-top: 1px solid {Colors.DARK_BORDER}; 
            color: {Colors.DARK_TEXT}; 
            padding: 4px;
        }}
        QScrollBar:vertical {{ 
            background: {Colors.DARK_BG}; 
            width: 10px; 
            border-radius: 5px; 
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{ 
            background: {Colors.DARK_BORDER}; 
            border-radius: 5px; 
            min-height: 30px; 
        }}
        QScrollBar::handle:vertical:hover {{ background: {Colors.DARK_TEXT_MUTED}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


    HTML_TEMPLATE = """
    <style>
        body {{ 
            font-family: '맑은 고딕', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
            margin: 12px; 
            color: {text_color};
            line-height: 1.6;
        }}
        a {{ text-decoration: none; color: {link_color}; }}
        a:hover {{ color: {link_hover}; }}
        
        /* 뉴스 카드 - QTextBrowser 호환 디자인 */
        .news-item {{ 
            border: 1px solid {border_color};
            border-left: 4px solid {link_color};
            border-radius: 12px; 
            padding: 18px 22px; 
            margin-bottom: 10px; 
            background: {bg_color};
        }}
        .news-item.read {{ 
            background: {read_bg}; 
            border-left-color: {border_color};
            opacity: 0.7;
        }}
        .news-item.duplicate {{ 
            border-left-color: #FB923C; 
        }}
        .news-item.bookmarked {{
            border-left-color: #FBBF24;
        }}
        
        /* 제목 링크 */
        .title-link {{ 
            font-size: 12.5pt; 
            font-weight: 600; 
            color: {title_color}; 
            line-height: 1.45; 
            display: block; 
            margin-bottom: 8px;
        }}
        .title-link:hover {{
            color: {link_color};
            text-decoration: underline;
        }}
        
        /* 메타 정보 */
        .meta-info {{ 
            font-size: 9pt; 
            color: {meta_color}; 
            margin-top: 4px; 
            border-bottom: 1px solid {border_color}; 
            padding-bottom: 8px; 
            margin-bottom: 10px;
        }}
        .meta-left {{
            display: inline;
        }}
        
        /* 본문 */
        .description {{ 
            margin-top: 0; 
            line-height: 1.7; 
            color: {desc_color}; 
            font-size: 10.5pt;
        }}
        
        /* 액션 버튼 - 간소화 스타일 */
        .actions {{ 
            font-size: 9pt; 
            margin-top: 10px;
        }}
        .actions a {{ 
            padding: 5px 12px;
            border-radius: 16px;
            font-weight: 500;
            font-size: 8.5pt;
            background: {action_bg};
            margin-right: 6px;
        }}
        .actions a:hover {{
            background: {action_hover};
            text-decoration: none;
        }}
        .actions a.bookmark {{
            background: {link_color};
            color: white;
        }}
        .actions a.unbookmark {{
            background: #EF4444;
            color: white;
        }}
        
        /* 빈 상태 */
        .empty-state {{ 
            text-align: center; 
            padding: 80px 40px; 
            color: {meta_color}; 
            font-size: 14pt;
            background: {bg_gradient};
            border-radius: 16px;
            margin: 20px 10px;
            border: 2px dashed {border_color};
        }}
        .empty-state-title {{
            font-size: 18pt;
            font-weight: 700;
            margin-bottom: 16px;
            color: {link_color};
        }}
        
        /* 하이라이트 */
        .highlight {{ 
            background: #FCD34D; 
            color: #000000; 
            padding: 2px 5px; 
            border-radius: 3px; 
            font-weight: 600;
        }}
        
        /* 키워드 태그 */
        .keyword-tag {{ 
            background: {tag_bg};
            color: {tag_color}; 
            padding: 3px 10px; 
            border-radius: 12px; 
            font-size: 8.5pt; 
            margin-right: 6px;
            font-weight: 600;
        }}
        
        /* 중복 배지 */
        .duplicate-badge {{ 
            background: #FFA500;
            color: #FFFFFF; 
            padding: 3px 10px; 
            border-radius: 12px; 
            font-size: 8.5pt; 
            margin-right: 6px;
            font-weight: 600;
        }}
        
        /* 메모 아이콘 */
        .note-icon {{
            color: {link_color};
            font-weight: bold;
        }}
    </style>
    """
