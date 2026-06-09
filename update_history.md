# Update History

이 파일은 현재 릴리스에서 유지해야 할 변경 요약만 기록합니다. 과거 날짜별 누적 로그는 문서 본문에서 제거했으며, 필요하면 Git history와 이전 태그를 기준으로 확인합니다.

## v32.7.3 (Unreleased)

### Current State

- Python 3.14, PyQt6, SQLite, requests, PyInstaller onefile 기준입니다.
- `news_scraper_pro.py`는 실행 진입점과 legacy re-export를 유지합니다.
- `core.database.DatabaseManager`, `core.workers`, `ui.main_window.MainApp`, `ui.news_tab.NewsTab` facade 경로는 호환성을 위해 유지합니다.
- 내부 구현은 `core/*_support`와 `ui/*_support` 패키지로 분리되어 있습니다.

### Fetch/DB Performance

- `NewsUpsertResult`와 `DatabaseManager.upsert_news_detailed(...)`를 추가했습니다.
- `DatabaseManager.upsert_news(...) -> tuple[int, int]`는 기존 반환 계약을 유지하면서 detailed path를 사용합니다.
- API fetch 저장 시 기존 scope membership prequery를 줄이고, 동일 값 재수집의 no-op UPDATE를 줄였습니다.
- duplicate flag 재계산은 신규 membership 또는 title hash 변경이 있는 hash로 제한합니다.
- `NewsCountSummary`와 `DatabaseManager.count_news_states(...)`를 추가해 full reload의 total/unread count를 단일 쿼리로 계산합니다.
- `ApiWorker.finished` payload shape는 유지합니다.
- `DBWorker` append reload는 known total을 재사용합니다.
- 탭 배지는 DB load unread count와 NewsTab unread cache를 우선 반영합니다.

### Docs/Spec/Gitignore Reconciliation

- README, assistant guide, 구조 분석 문서에서 오래된 날짜별 수정 내역을 제거하고 현재 코드베이스 기준으로 재작성했습니다.
- `news_scraper_pro.spec`의 누적 review 주석을 현재 패키징 계약 중심으로 줄였습니다.
- `.gitignore`에 `.codegraph/` 로컬 분석 산출물을 추가했습니다.
- 새 의존성, 새 bundled data, cloud snapshot wire format 변경은 없습니다.

### Validation

- `python -m pytest tests/test_worker_cancellation.py tests/test_dbworker_pagination.py tests/test_db_queries.py tests/test_news_tab_performance.py -q` => `60 passed`
- `python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q` => `4 passed`
- `python -m pytest -q` => `338 passed, 7 warnings, 5 subtests passed`
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`
- `python -m PyInstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)
- Temp DB benchmark: initial detailed upsert `833.44ms`, repeated identical detailed upsert `169.46ms`, `count_news_states` `6.44ms`, first page fetch `9.99ms`, offset-1000 fetch `17.66ms`

## Earlier Versions

이전 버전의 상세 변경 로그는 저장소 이력에 보존되어 있습니다. 현재 문서는 유지보수자가 실제 코드 구조, 공개 API, 검증 계약을 빠르게 확인하는 것을 우선합니다.
