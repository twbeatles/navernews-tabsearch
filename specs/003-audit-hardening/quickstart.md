# Quickstart: 감사 후속 안정성 강화 검증

## Environment

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
```

## Focused validation

```powershell
.venv\Scripts\python -m pytest tests/test_cloud_sync.py tests/test_maintenance_mode.py tests/test_csv_import_export_hardening.py tests/test_dependency_contract.py -q
```

## Static and full regression

```powershell
.venv\Scripts\python -m pyright
.venv\Scripts\python -m pytest -q
```

## Runtime/package smoke

```powershell
.venv\Scripts\python -c "from PySide6 import QtNetwork; import news_scraper_pro"
.venv\Scripts\python -m PyInstaller --noconfirm --clean news_scraper_pro.spec
```

## Optional real NAVER API verification

API HUB credential과 별도 test query를 준비한 비-production 환경에서만 수행한다. 실제 사용자 DB/config를 사용하지 않는다.

```powershell
$env:NAVER_API_LIVE_TEST = "1"
$env:NAVER_API_HUB_CLIENT_ID = "test-key-id"
$env:NAVER_API_HUB_CLIENT_SECRET = "test-key-secret"
python -m pytest tests/test_live_naver_api_e2e.py -q
```

이 테스트는 이번 작업 환경에서는 credential이 없어 실행하지 않았다. 기본 suite에서는 명시적으로 skip된다.
