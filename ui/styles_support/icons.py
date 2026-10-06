"""테마 색에 맞춘 소형 글리프(화살표·닫기·체크)를 런타임에 그려 QSS에 연결한다.

QSS는 삼각형/체크 표시를 직접 그릴 수 없고 플랫폼 기본 글리프는 테마 색을
따르지 않는다. 이미지 리소스를 패키징하는 대신 팔레트 색으로 PNG를 그려
임시 폴더에 두고 ``image: url(...)``로 참조한다. 생성에 실패하면 빈 문자열을
돌려주어 플랫폼 기본 글리프로 동작한다.
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Dict

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen

from ui.styles_support.tokens import Palette

logger = logging.getLogger(__name__)

# 서브컨트롤보다 크게 그려 두면 QSS가 축소해 그리므로 고배율 화면에서도 선명하다.
_GLYPH_PX = 32
_CLOSE_CANVAS_PX = 56
_ICON_DIR_NAME = "news_scraper_pro_ui"
_qss_cache: Dict[str, str] = {}

_GLYPH_STROKES = {
    "chevron": [((8, 12), (16, 20)), ((16, 20), (24, 12))],
    "close": [((6, 6), (26, 26)), ((26, 6), (6, 26))],
    "check": [((7, 17), (13, 23)), ((13, 23), (25, 9))],
}


def _draw_glyph(path: str, glyph: str, color: str, width: float, canvas_w: int = _GLYPH_PX) -> None:
    image = QImage(canvas_w, _GLYPH_PX, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(color))
        pen.setWidthF(width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for (x1, y1), (x2, y2) in _GLYPH_STROKES[glyph]:
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    finally:
        painter.end()
    if not image.save(path, "PNG"):
        raise OSError(f"glyph save failed: {path}")


def glyph_qss(p: Palette) -> str:
    """팔레트용 글리프를 준비하고 이를 참조하는 QSS 조각을 반환한다."""
    cached = _qss_cache.get(p.name)
    if cached is not None:
        return cached

    try:
        icon_dir = os.path.join(tempfile.gettempdir(), _ICON_DIR_NAME)
        os.makedirs(icon_dir, exist_ok=True)
        urls: Dict[str, str] = {}
        for key, glyph, color, width, canvas_w in (
            ("chevron", "chevron", p.text_muted, 3.0, _GLYPH_PX),
            # 닫기 아이콘은 오른쪽에 투명 여백을 둬 탭 가장자리와 간격을 만든다.
            ("close", "close", p.text_muted, 3.4, _CLOSE_CANVAS_PX),
            ("close_hover", "close", p.danger, 4.0, _CLOSE_CANVAS_PX),
            ("check", "check", p.on_primary, 4.5, _GLYPH_PX),
        ):
            path = os.path.join(icon_dir, f"{p.name}_{key}.png")
            _draw_glyph(path, glyph, color, width, canvas_w)
            urls[key] = path.replace("\\", "/")
    except Exception as exc:
        logger.warning("UI 글리프 생성 실패, 기본 글리프를 사용합니다: %s", exc)
        _qss_cache[p.name] = ""
        return ""

    qss = f"""
        QComboBox::drop-down {{ border: none; width: 24px; }}
        QComboBox::down-arrow {{ image: url({urls['chevron']}); width: 12px; height: 12px; }}
        QTabBar::close-button {{
            image: url({urls['close']});
            subcontrol-position: right;
            width: 24px;
            height: 14px;
            margin: 2px;
        }}
        QTabBar::close-button:hover {{ image: url({urls['close_hover']}); }}
        QCheckBox::indicator:checked {{ image: url({urls['check']}); }}
    """
    _qss_cache[p.name] = qss
    return qss
