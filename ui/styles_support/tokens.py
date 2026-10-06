from dataclasses import dataclass
from enum import Enum
from typing import Dict

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
    LIGHT_TEXT_MUTED = "#64748B"       # 슬레이트 500 (흰 배경 대비 확보)

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
        """기사 목록 HTML 렌더링용 테마별 색상 딕셔너리"""
        if is_dark:
            return {
                'text_color': cls.DARK_TEXT,
                'link_color': cls.DARK_PRIMARY,
                'border_color': cls.DARK_BORDER,
                'title_color': cls.DARK_TEXT,
                'read_color': "#64748B",        # 슬레이트 500
                'meta_color': cls.DARK_TEXT_MUTED,
                'desc_color': "#CBD5E1",        # 슬레이트 300
                'warn_color': cls.DARK_WARNING,
            }
        return {
            'text_color': cls.LIGHT_TEXT,
            'link_color': cls.LIGHT_PRIMARY_HOVER,
            'border_color': cls.LIGHT_BORDER,
            'title_color': "#0F172A",       # 슬레이트 900
            'read_color': "#94A3B8",        # 슬레이트 400
            'meta_color': cls.LIGHT_TEXT_MUTED,
            'desc_color': "#475569",        # 슬레이트 600
            'warn_color': "#B45309",        # 앰버 700 (흰 배경 대비 확보)
        }


class Typography:
    """타이포그래피 토큰 - 폰트 스택과 사이즈 스케일의 단일 소스"""
    FONT_FAMILY = "'맑은 고딕', -apple-system, 'Segoe UI', sans-serif"
    SIZE_XS = "8.5pt"
    SIZE_SM = "9pt"
    SIZE_MD = "10pt"
    SIZE_LG = "11pt"
    SIZE_XL = "12.5pt"


class Spacing:
    """여백 스케일 (px)"""
    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 20
    XXL = 24


class Radius:
    """모서리 라운드 스케일 (px)"""
    SM = 6
    MD = 8
    LG = 10
    XL = 12
    XXL = 16
    PILL = 999


@dataclass(frozen=True)
class Palette:
    """테마별 시맨틱 색상 슬롯 - 라이트/다크 스타일시트의 단일 소스."""
    name: str
    # 표면/구조
    bg: str
    surface: str
    border: str
    text: str
    text_muted: str
    # 강조(인디고)
    primary: str
    primary_hover: str
    primary_soft: str
    on_primary: str              # primary 배경 위 글자색
    # 시맨틱
    success: str
    info: str
    warning: str
    danger: str
    # 컴포넌트 세부
    btn_hover_start: str         # 버튼/메뉴 hover 배경
    btn_pressed_bg: str
    input_focus_bg: str
    checkbox_bg: str


LIGHT_PALETTE = Palette(
    name="light",
    bg=Colors.LIGHT_BG,
    surface=Colors.LIGHT_CARD_BG,
    border=Colors.LIGHT_BORDER,
    text=Colors.LIGHT_TEXT,
    text_muted=Colors.LIGHT_TEXT_MUTED,
    primary=Colors.LIGHT_PRIMARY,
    primary_hover=Colors.LIGHT_PRIMARY_HOVER,
    primary_soft=Colors.LIGHT_PRIMARY_LIGHT,
    on_primary="#FFFFFF",
    success=Colors.LIGHT_SUCCESS,
    info=Colors.LIGHT_INFO,
    warning=Colors.LIGHT_WARNING,
    danger=Colors.LIGHT_DANGER,
    btn_hover_start="#EEF2FF",         # 인디고 50
    btn_pressed_bg=Colors.LIGHT_PRIMARY_LIGHT,
    input_focus_bg=Colors.LIGHT_CARD_BG,
    checkbox_bg=Colors.LIGHT_CARD_BG,
)


DARK_PALETTE = Palette(
    name="dark",
    bg=Colors.DARK_BG,
    surface=Colors.DARK_CARD_BG,
    border=Colors.DARK_BORDER,
    text=Colors.DARK_TEXT,
    text_muted=Colors.DARK_TEXT_MUTED,
    primary=Colors.DARK_PRIMARY,
    primary_hover=Colors.DARK_PRIMARY_HOVER,
    primary_soft=Colors.DARK_PRIMARY_LIGHT,
    on_primary=Colors.DARK_BG,
    success=Colors.DARK_SUCCESS,
    info=Colors.DARK_INFO,
    warning=Colors.DARK_WARNING,
    danger=Colors.DARK_DANGER,
    btn_hover_start=Colors.DARK_BORDER,
    btn_pressed_bg=Colors.DARK_BORDER,
    input_focus_bg=Colors.DARK_CARD_BG,
    checkbox_bg=Colors.DARK_BG,
)


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
class ToastType(Enum):
    """토스트 메시지 유형"""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
