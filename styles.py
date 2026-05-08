import warnings

warnings.warn(
    "Root styles imports are deprecated; use ui.styles instead.",
    DeprecationWarning,
    stacklevel=2,
)

from ui.styles import AppStyle, Colors, ToastType, UIConstants

__all__ = ['Colors', 'UIConstants', 'ToastType', 'AppStyle']
