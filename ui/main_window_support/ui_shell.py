
"""Compatibility facade for MainApp UI shell mixins."""

from ui.main_window_support.ui_shell_support import (
    _MainWindowActionShellMixin,
    _MainWindowBadgeShellMixin,
    _MainWindowNotificationShellMixin,
    _MainWindowSetupShellMixin,
    _MainWindowThemeShellMixin,
)


class _MainWindowUIShellMixin(
    _MainWindowThemeShellMixin,
    _MainWindowSetupShellMixin,
    _MainWindowBadgeShellMixin,
    _MainWindowActionShellMixin,
    _MainWindowNotificationShellMixin,
):
    """Composes MainApp visual shell, badges, actions, and notifications."""


__all__ = ["_MainWindowUIShellMixin"]
