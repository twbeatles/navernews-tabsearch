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
    """테마별 시맨틱 색상 슬롯 - 라이트/다크 스타일시트의 단일 소스.

    값은 기존 Colors.LIGHT_*/DARK_* 상수에서 매핑되어, 토큰 도입 시
    기존 외형과 동일하게 렌더링된다(시각 변화 0).
    """
    name: str
    # 표면/구조
    bg: str
    surface: str
    border: str
    text: str
    text_muted: str
    # 브랜드(인디고)
    primary: str
    primary_hover: str
    primary_soft: str
    primary_grad_end: str        # 그라데이션 동반 색(바이올렛)
    primary_grad_end_hover: str
    # 시맨틱
    success: str
    success_grad_end: str
    success_hover_start: str
    success_hover_end: str
    refresh_text: str
    info: str
    warning: str
    danger: str
    # 컴포넌트 세부
    btn_hover_start: str         # 버튼/메뉴 hover 시작색
    btn_pressed_bg: str
    input_focus_bg: str
    checkbox_bg: str
    groupbox_border_css: str     # "1px solid <border>" 또는 "none"
    tab_hover_underline: str


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
    # 보라(#8B5CF6) 혼합 대신 모노크롬 인디고 그라데이션으로 응집감 강화
    primary_grad_end="#818CF8",        # 인디고 400
    primary_grad_end_hover="#6366F1",  # 인디고 500
    success=Colors.LIGHT_SUCCESS,
    success_grad_end="#34D399",
    success_hover_start="#059669",
    success_hover_end="#10B981",
    refresh_text="white",
    info=Colors.LIGHT_INFO,
    warning=Colors.LIGHT_WARNING,
    danger=Colors.LIGHT_DANGER,
    btn_hover_start=Colors.LIGHT_PRIMARY_LIGHT,
    btn_pressed_bg=Colors.LIGHT_PRIMARY_LIGHT,
    input_focus_bg="#FEFFFE",
    checkbox_bg=Colors.LIGHT_CARD_BG,
    groupbox_border_css=f"1px solid {Colors.LIGHT_BORDER}",
    tab_hover_underline="rgba(99, 102, 241, 0.4)",
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
    # 보라(#A78BFA) 혼합 대신 모노크롬 인디고 그라데이션으로 응집감 강화
    primary_grad_end="#A5B4FC",        # 인디고 300
    primary_grad_end_hover="#C7D2FE",  # 인디고 200
    success=Colors.DARK_SUCCESS,
    success_grad_end="#6EE7B7",
    success_hover_start="#6EE7B7",
    success_hover_end=Colors.DARK_SUCCESS,
    refresh_text="#064E3B",
    info=Colors.DARK_INFO,
    warning=Colors.DARK_WARNING,
    danger=Colors.DARK_DANGER,
    btn_hover_start=Colors.DARK_BORDER,
    btn_pressed_bg=Colors.DARK_BORDER,
    input_focus_bg=Colors.DARK_BORDER,
    checkbox_bg=Colors.DARK_BG,
    groupbox_border_css="none",
    tab_hover_underline="rgba(129, 140, 248, 0.4)",
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
