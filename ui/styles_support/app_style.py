from ui.styles_support.tokens import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    Palette,
    Typography,
)

_FONT = Typography.FONT_FAMILY


def _build_stylesheet(p: Palette) -> str:
    """단일 템플릿에서 테마별 Qt 스타일시트를 생성한다.

    라이트/다크의 차이는 전부 ``Palette`` 슬롯으로 흡수된다. 그라데이션 없이
    단색 표면 + 1px 테두리만 쓰고, 강조색 버튼은 ``#AddTab`` 하나만 둔다.
    """
    return f"""
        QMainWindow, QDialog {{ background-color: {p.bg}; }}
        QGroupBox {{
            font-family: {_FONT};
            color: {p.text};
            font-size: 10pt;
            font-weight: 600;
            margin-top: 18px;
            padding: 12px;
            border: 1px solid {p.border};
            border-radius: 8px;
            background-color: {p.surface};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 4px;
            padding: 0 4px;
            color: {p.text_muted};
        }}
        QLabel, QDialog QLabel {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text};
        }}
        QLabel#Hint, QLabel#TabStatus {{
            font-size: 9pt;
            color: {p.text_muted};
        }}
        QPushButton {{
            font-family: {_FONT};
            font-size: 10pt;
            background-color: {p.surface};
            color: {p.text};
            padding: 6px 14px;
            border-radius: 6px;
            border: 1px solid {p.border};
            min-width: 56px;
        }}
        QPushButton:hover {{
            background-color: {p.btn_hover_start};
            border-color: {p.primary};
        }}
        QPushButton:pressed {{ background-color: {p.btn_pressed_bg}; }}
        QPushButton:disabled {{
            background-color: {p.bg};
            color: {p.text_muted};
            border-color: {p.border};
        }}
        QPushButton::menu-indicator {{
            subcontrol-origin: padding;
            subcontrol-position: right center;
            right: 8px;
        }}
        QPushButton#MoreMenu {{ padding-right: 24px; }}
        QPushButton#Chip {{
            min-width: 0;
            padding: 3px 10px;
            font-size: 9pt;
            border-radius: 11px;
        }}
        QPushButton#AddTab {{
            font-weight: 600;
            background-color: {p.primary};
            color: {p.on_primary};
            border-color: {p.primary};
        }}
        QPushButton#AddTab:hover {{
            background-color: {p.primary_hover};
            border-color: {p.primary_hover};
        }}
        QPushButton#AddTab:disabled {{
            background-color: {p.bg};
            color: {p.text_muted};
            border-color: {p.border};
        }}
        QToolButton#Disclosure {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text_muted};
            background: transparent;
            border: none;
            padding: 4px 8px;
            border-radius: 6px;
        }}
        QToolButton#Disclosure:hover {{
            color: {p.primary};
            background-color: {p.btn_hover_start};
        }}
        QToolButton#Disclosure:checked {{ color: {p.primary}; }}
        QMenu {{
            font-family: {_FONT};
            font-size: 10pt;
            background-color: {p.surface};
            color: {p.text};
            border: 1px solid {p.border};
            border-radius: 6px;
            padding: 4px;
        }}
        QMenu::item {{ padding: 6px 28px 6px 12px; border-radius: 4px; }}
        QMenu::item:selected {{ background-color: {p.btn_hover_start}; color: {p.text}; }}
        QMenu::item:disabled {{ color: {p.text_muted}; }}
        QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 8px; }}
        QToolTip {{
            font-family: {_FONT};
            background-color: {p.surface};
            color: {p.text};
            border: 1px solid {p.border};
            padding: 4px 6px;
        }}
        QComboBox {{
            font-family: {_FONT};
            font-size: 10pt;
            padding: 5px 10px;
            border-radius: 6px;
            border: 1px solid {p.border};
            background-color: {p.surface};
            color: {p.text};
            min-width: 80px;
        }}
        QComboBox:hover {{ border-color: {p.primary}; }}
        QComboBox QAbstractItemView {{
            background-color: {p.surface};
            color: {p.text};
            selection-background-color: {p.btn_hover_start};
            selection-color: {p.text};
            border: 1px solid {p.border};
            padding: 4px;
        }}
        QComboBox QAbstractItemView::item {{ padding: 6px 8px; }}
        QTextBrowser, QTextEdit, QListWidget {{
            font-family: {_FONT};
            background-color: {p.surface};
            border: 1px solid {p.border};
            border-radius: 8px;
            color: {p.text};
            padding: 6px;
        }}
        QTextBrowser#DocBrowser {{ border: none; background-color: {p.bg}; }}
        QScrollArea#SettingsScroll {{ border: none; background-color: {p.bg}; }}
        QWidget#SettingsPage {{ background-color: {p.bg}; }}
        QListWidget::item:selected {{
            background-color: {p.btn_hover_start};
            color: {p.text};
        }}
        QTabWidget::pane {{
            border: none;
            border-top: 1px solid {p.border};
            background-color: {p.bg};
        }}
        QTabBar {{ qproperty-drawBase: 0; }}
        QTabBar::tab {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text_muted};
            padding: 2px 14px;
            min-height: 30px;
            border: none;
            border-bottom: 2px solid transparent;
            background-color: transparent;
            margin-right: 2px;
        }}
        QTabBar::tab:selected {{
            color: {p.primary};
            font-weight: 600;
            border-bottom: 2px solid {p.primary};
        }}
        QTabBar::tab:!selected:hover {{
            color: {p.text};
            border-bottom: 2px solid {p.border};
        }}
        QLineEdit {{
            font-family: {_FONT};
            font-size: 10pt;
            padding: 6px 10px;
            border-radius: 6px;
            border: 1px solid {p.border};
            background-color: {p.surface};
            color: {p.text};
        }}
        QLineEdit:focus {{
            border-color: {p.primary};
            background-color: {p.input_focus_bg};
        }}
        QLineEdit#FilterActive {{ border-color: {p.primary}; }}
        QLineEdit::placeholder {{ color: {p.text_muted}; }}
        QProgressBar {{
            border: none;
            border-radius: 2px;
            background-color: {p.border};
            max-height: 4px;
        }}
        QProgressBar::chunk {{
            background-color: {p.primary};
            border-radius: 2px;
        }}
        QCheckBox {{
            font-family: {_FONT};
            font-size: 10pt;
            color: {p.text};
            spacing: 6px;
        }}
        QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; }}
        QCheckBox::indicator:unchecked {{
            border: 1px solid {p.text_muted};
            background-color: {p.checkbox_bg};
        }}
        QCheckBox::indicator:checked {{
            border: 1px solid {p.primary};
            background-color: {p.primary};
        }}
        QCheckBox::indicator:disabled {{ border-color: {p.border}; }}
        QStatusBar {{
            font-family: {_FONT};
            font-size: 9pt;
            background-color: {p.bg};
            color: {p.text_muted};
        }}
        QStatusBar::item {{ border: none; }}
        QStatusBar QLabel {{ font-size: 9pt; color: {p.text_muted}; }}
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 2px;
        }}
        QScrollBar::handle:vertical {{
            background: {p.border};
            border-radius: 3px;
            min-height: 30px;
        }}
        QScrollBar::handle:vertical:hover {{ background: {p.text_muted}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


def card_qss(p: Palette, object_name: str = "FilterCard") -> str:
    """필터 영역 QFrame 컨테이너의 테마별 스타일 - 토큰 기반."""
    return f"""
        QFrame#{object_name} {{
            background-color: transparent;
            border: none;
        }}
    """


class AppStyle:
    """애플리케이션 전체 스타일시트 및 HTML 템플릿"""

    LIGHT = _build_stylesheet(LIGHT_PALETTE)

    DARK = _build_stylesheet(DARK_PALETTE)

    @classmethod
    def for_theme(cls, is_dark: bool) -> str:
        """실행 중인 앱에 적용할 스타일시트(기본 QSS + 테마 색 글리프)."""
        from ui.styles_support.icons import glyph_qss

        if is_dark:
            return cls.DARK + glyph_qss(DARK_PALETTE)
        return cls.LIGHT + glyph_qss(LIGHT_PALETTE)

    # QTextBrowser는 CSS 일부만 지원한다(border-radius, opacity, :hover,
    # display 미지원). 지원되는 속성만으로 납작한 목록형을 구성한다.
    HTML_TEMPLATE = """
    <style>
        body {{
            font-family: '맑은 고딕', -apple-system, 'Segoe UI', sans-serif;
            color: {text_color};
        }}
        a {{ text-decoration: none; color: {link_color}; }}

        .news-item {{ margin: 0 8px; }}
        .rule {{ background-color: {border_color}; font-size: 1px; }}

        .title-link {{
            font-size: 12pt;
            font-weight: 600;
            color: {title_color};
        }}
        .title-link-read {{
            font-size: 12pt;
            font-weight: normal;
            color: {read_color};
        }}
        .description {{
            margin-top: 4px;
            font-size: 10pt;
            color: {desc_color};
        }}
        .description-read {{
            margin-top: 4px;
            font-size: 10pt;
            color: {read_color};
        }}
        .meta {{ font-size: 9pt; color: {meta_color}; }}
        .actions {{ font-size: 9pt; }}
        .tag {{ color: {link_color}; }}
        .dup {{ color: {warn_color}; }}
        .star {{ color: {warn_color}; }}

        .empty-state-title {{
            margin-top: 72px;
            margin-bottom: 6px;
            font-size: 13pt;
            font-weight: 600;
            color: {text_color};
        }}
        .empty-state {{
            margin-top: 0;
            color: {meta_color};
            font-size: 10pt;
        }}
        .load-more {{ margin: 16px; font-size: 10pt; }}

        .highlight {{
            background: #FCD34D;
            color: #000000;
            font-weight: 600;
        }}
    </style>
    """
