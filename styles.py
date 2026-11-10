import warnings
from ui.styles import AppStyle, Colors, ToastType, UIConstants

warnings.warn(
    "Root styles imports are deprecated; use ui.styles instead.",
    DeprecationWarning,
    stacklevel=2,
)


__all__ = ['Colors', 'UIConstants', 'ToastType', 'AppStyle']
