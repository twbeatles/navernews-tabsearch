from pathlib import Path

from core.constants import RUNTIME_PATHS


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_dependency_contract_pins_direct_binary_dependencies():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for package in ("PySide6", "requests", "cryptography"):
        assert f"{package}==" in requirements


def test_ci_installs_contract_and_smokes_qtnetwork_entrypoint():
    quality = (ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    for workflow in (quality, release):
        assert "requirements-build.txt" in workflow
        assert "from PySide6 import QtNetwork; import news_scraper_pro" in workflow


def test_documented_runtime_filenames_match_runtime_paths():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert Path(RUNTIME_PATHS.db_file).name in readme
    assert Path(RUNTIME_PATHS.config_file).name in readme
