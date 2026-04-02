import os
import tempfile
from pathlib import Path


_TMP_ROOT = Path(__file__).resolve().parent.parent / ".pytest_tmp"
_TMP_ROOT.mkdir(parents=True, exist_ok=True)

for _name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_name] = str(_TMP_ROOT)

tempfile.tempdir = str(_TMP_ROOT)
