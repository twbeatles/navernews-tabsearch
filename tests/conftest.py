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
