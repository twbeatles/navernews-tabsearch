from ui.styles_support.tokens import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    Palette,
    Typography,
)

_FONT = Typography.FONT_FAMILY


def _build_stylesheet(p: Palette) -> str:
    """단일 템플릿에서 테마별 Qt 스타일시트를 생성한다.

    라이트/다크의 차이는 전부 ``Palette`` 슬롯으로 흡수되어, 동일한 구조의
    QSS를 두 팔레트로 렌더링한다. (이전의 중복된 LIGHT/DARK f-string 대체)
    """
    return f"""
        QMainWindow, QDialog {{ background-color: {p.bg}; }}
        QGroupBox {{
            font-family: {_FONT};
            color: {p.text};
            font-size: 11pt;
            font-weight: 600;
            margin-top: 16px;
            padding: 20px 16px 16px 16px;
            border: {p.groupbox_border_css};
            border-radius: 12px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {p.surface}, stop:1 {p.bg});
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 16px;
            top: 4px;
            padding: 4px 12px;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.primary}, stop:1 {p.primary_grad_end});
            color: white;
            border-radius: 8px;
        }}
        QLabel, QDialog QLabel {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text};
        }}
        QPushButton {{
            font-family: {_FONT};
            font-size: 10pt;
            font-weight: 500;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {p.surface}, stop:1 {p.bg});
            color: {p.text};
            padding: 10px 18px;
            border-radius: 10px;
            border: 1px solid {p.border};
            min-width: 70px;
            margin: 0 4px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {p.btn_hover_start}, stop:1 {p.surface});
            border-color: {p.primary};
            color: {p.primary};
        }}
        QPushButton:pressed {{
            background: {p.btn_pressed_bg};
            border-color: {p.primary};
        }}
        QPushButton:disabled {{
            background-color: {p.bg};
            color: {p.text_muted};
            border-color: {p.border};
        }}
        QPushButton#IconButton {{
            min-width: 0;
            padding: 9px 11px;
            font-size: 12pt;
            margin: 0 2px;
        }}
        QToolButton#Disclosure {{
            font-family: {_FONT};
            font-size: 10pt;
            font-weight: 600;
            color: {p.text_muted};
            background: transparent;
            border: none;
            padding: 4px 8px;
            border-radius: 8px;
        }}
        QToolButton#Disclosure:hover {{
            color: {p.primary};
            background-color: {p.primary_soft};
        }}
        QToolButton#Disclosure:checked {{ color: {p.primary}; }}
        QPushButton#AddTab {{
            font-weight: bold;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.primary}, stop:1 {p.primary_grad_end});
            color: white;
            border: none;
            padding: 12px 24px;
        }}
        QPushButton#AddTab:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.primary_hover}, stop:1 {p.primary_grad_end_hover});
        }}
        QPushButton#RefreshBtn {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.success}, stop:1 {p.success_grad_end});
            color: {p.refresh_text};
            border: none;
        }}
        QPushButton#RefreshBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.success_hover_start}, stop:1 {p.success_hover_end});
        }}
        QComboBox {{
            font-family: {_FONT};
            font-size: 10pt;
            padding: 8px 12px;
            border-radius: 10px;
            border: 1px solid {p.border};
            background-color: {p.surface};
            color: {p.text};
            min-width: 90px;
        }}
        QComboBox:hover {{ border-color: {p.primary}; }}
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {p.text_muted};
        }}
        QComboBox QAbstractItemView {{
            background-color: {p.surface};
            color: {p.text};
            selection-background-color: {p.primary};
            selection-color: white;
            border: 1px solid {p.border};
            border-radius: 8px;
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{ padding: 8px; border-radius: 6px; }}
        QComboBox QAbstractItemView::item:hover {{
            background-color: {p.btn_hover_start};
            color: {p.text};
        }}
        QComboBox QAbstractItemView::item:selected {{
            background-color: {p.primary};
            color: white;
        }}
        QTextBrowser, QTextEdit, QListWidget {{
            font-family: {_FONT};
            background-color: {p.surface};
            border: 1px solid {p.border};
            border-radius: 12px;
            color: {p.text};
            padding: 12px;
        }}
        QListWidget::item:selected {{
            background-color: {p.primary};
            color: white;
            border-radius: 6px;
        }}
        QTabWidget::pane {{
            border: 1px solid {p.border};
            border-radius: 12px;
            background-color: {p.surface};
            margin-top: -1px;
        }}
        QTabBar::tab {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text_muted};
            padding: 12px 20px;
            min-height: 30px;
            border: 1px solid transparent;
            border-bottom: none;
            background-color: transparent;
            margin-right: 4px;
        }}
        QTabBar::tab:selected {{
            background-color: {p.surface};
            border-color: {p.border};
            border-bottom: 3px solid {p.primary};
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            color: {p.primary};
            font-weight: 600;
        }}
        QTabBar::tab:!selected {{ color: {p.text_muted}; }}
        QTabBar::tab:!selected:hover {{
            color: {p.text};
            background-color: {p.primary_soft};
            border-bottom: 2px solid {p.tab_hover_underline};
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
        }}
        QLineEdit {{
            font-family: {_FONT};
            font-size: 10pt;
            padding: 10px 14px;
            border-radius: 10px;
            border: 1px solid {p.border};
            background-color: {p.surface};
            color: {p.text};
        }}
        QLineEdit:focus {{
            border: 2px solid {p.primary};
            padding: 9px 13px;
            background-color: {p.input_focus_bg};
        }}
        QLineEdit#FilterActive {{
            border: 2px solid {p.primary};
            background-color: {p.primary_soft};
        }}
        QLineEdit::placeholder {{ color: {p.text_muted}; }}
        QProgressBar {{
            border: none;
            border-radius: 6px;
            text-align: center;
            background-color: {p.border};
            color: {p.text};
            height: 8px;
        }}
        QProgressBar::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {p.primary}, stop:1 {p.info});
            border-radius: 6px;
        }}
        QCheckBox {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text};
            spacing: 8px;
        }}
        QCheckBox::indicator {{ width: 22px; height: 22px; }}
        QCheckBox::indicator:unchecked {{
            border: 2px solid {p.border};
            background-color: {p.checkbox_bg};
            border-radius: 6px;
        }}
        QCheckBox::indicator:checked {{
            border: none;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p.primary}, stop:1 {p.primary_grad_end});
            border-radius: 6px;
        }}
        QCheckBox::indicator:checked:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {p.primary_hover}, stop:1 {p.primary_grad_end_hover});
        }}
        QStatusBar {{
            background-color: {p.surface};
            border-top: 1px solid {p.border};
            color: {p.text};
            padding: 4px;
        }}
        QScrollBar:vertical {{
            background: {p.bg};
            width: 10px;
            border-radius: 5px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {p.border};
            border-radius: 5px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def card_qss(p: Palette, object_name: str = "FilterCard") -> str:
    """카드형 QFrame 컨테이너의 테마별 스타일 - 토큰 기반."""
    return f"""
        QFrame#{object_name} {{
            background-color: {p.surface};
            border: 1px solid {p.border};
            border-radius: 12px;
            padding: 8px;
        }}
    """


class AppStyle:
    """애플리케이션 전체 스타일시트 및 HTML 템플릿"""

    LIGHT = _build_stylesheet(LIGHT_PALETTE)

    DARK = _build_stylesheet(DARK_PALETTE)


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
