import warnings

warnings.warn(
    "Root config_store imports are deprecated; use core.config_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

from core.config_store import *  # noqa: F401,F403
