import warnings
from core.config_store import *  # noqa: F401,F403

warnings.warn(
    "Root config_store imports are deprecated; use core.config_store instead.",
    DeprecationWarning,
    stacklevel=2,
)
