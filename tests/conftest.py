import os
import tempfile
from pathlib import Path


_TMP_ROOT = Path(__file__).resolve().parent.parent / ".pytest_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)
_RUNTIME_ROOT = _TMP_ROOT / "runtime_data"
_RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)

for _name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_name] = str(_TMP_ROOT)

os.environ["NEWS_SCRAPER_DATA_DIR"] = str(_RUNTIME_ROOT)

tempfile.tempdir = str(_TMP_ROOT)


# --- Optional runtime dependencies -------------------------------------------
# This is a Windows PyQt6 desktop app, so the test suite legitimately depends on
# PyQt6 and cryptography. When one of them is missing (a headless CI image, or a
# platform with no prebuilt wheel), importing those test modules used to raise
# at COLLECTION time, which aborts the whole run: pytest reports
# "Interrupted: N errors during collection" and the hundreds of dependency-free
# core tests never execute. Turning that into a normal skip keeps the rest of
# the suite meaningful and makes the reason visible in the summary.
import importlib.util

import pytest

_OPTIONAL_DEPENDENCIES = ("PyQt6", "cryptography")


def _missing_optional_dependencies() -> list[str]:
    missing = []
    for name in _OPTIONAL_DEPENDENCIES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


_MISSING_OPTIONAL = _missing_optional_dependencies()


def pytest_report_header(config):
    if not _MISSING_OPTIONAL:
        return None
    joined = ", ".join(_MISSING_OPTIONAL)
    return (
        f"optional dependencies missing: {joined} "
        f"-- test modules needing them are skipped, not failed "
        f"(install with: pip install -r requirements.txt)"
    )


class _OptionalDependencyModule(pytest.Module):
    """Test module that skips instead of erroring on a missing optional dep."""

    def collect(self):
        try:
            return super().collect()
        except Exception as exc:
            missing = _module_name_from_import_error(exc)
            if missing is not None:
                pytest.skip(
                    f"requires optional dependency {missing!r}",
                    allow_module_level=True,
                )
            raise


def _module_name_from_import_error(exc: BaseException):
    """Return the missing optional dependency named by exc, else None."""
    seen = set()
    current = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModuleNotFoundError) and current.name:
            root = str(current.name).split(".")[0]
            if root in _OPTIONAL_DEPENDENCIES:
                return root
        current = current.__cause__ or current.__context__
    return None


def pytest_pycollect_makemodule(module_path, parent):
    if not _MISSING_OPTIONAL:
        return None
    return _OptionalDependencyModule.from_parent(parent, path=module_path)
