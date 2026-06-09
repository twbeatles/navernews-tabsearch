# 프로젝트 구조 분석

이 문서는 현재 코드베이스의 구조와 변경 진입점을 요약합니다. 과거 구현 로그는 제거했고, 실제 유지보수에 필요한 현재 상태를 우선합니다.

## 한눈에 보는 구조

```text
news_scraper_pro.py
  -> core.bootstrap.main()
  -> ui.main_window.MainApp
  -> core.database.DatabaseManager
  -> core.workers_support.ApiWorker / DBWorker
```

- `core/`: 런타임 경로, 설정, DB schema/query/mutation, worker, backup, cloud sync, query parser
- `ui/`: MainApp, NewsTab, dialog, settings, styles, rendering/action/loading support
- `tests/`: 공개 API 호환성, DB 의미, worker lifecycle, UI 성능, cloud/backup/settings 회귀 테스트
- root wrappers: `database_manager.py`, `query_parser.py`, `workers.py`, `styles.py` 등 legacy import 유지용

## 런타임 흐름

### 시작

1. `news_scraper_pro.py`가 `core.bootstrap.main()`을 호출합니다.
2. 단일 인스턴스와 pending restore를 처리합니다.
3. `RuntimePaths`가 `DATA_DIR`를 정하고 레거시 런타임 파일을 비파괴 마이그레이션합니다.
4. `MainApp`이 설정, DB, 탭, 트레이, 자동 새로고침을 조립합니다.

### Fetch

1. `MainApp`이 탭 query를 `parse_search_query(...)`와 `build_fetch_key(...)`로 canonicalize합니다.
2. `ApiWorker`가 worker-owned `requests.Session`으로 네이버 API를 호출합니다.
3. `DatabaseManager.upsert_news_detailed(...)`가 기사와 query membership을 저장하고 현재 scope의 신규 link를 반환합니다.
4. 자동화 규칙과 알림은 이번 fetch에서 새로 감지된 link 집합을 기준으로 동작합니다.
5. 탭은 DB reload로 화면과 count/badge를 맞춥니다.

### DB Load

1. `NewsTab`은 `DBWorker`에 `DBQueryScope`와 필터를 전달합니다.
2. full reload는 `count_news_states(...)`로 total/unread를 한 번에 계산합니다.
3. append reload는 known total을 재사용합니다.
4. 로드 완료 unread count는 MainApp badge cache와 탭 제목에 즉시 반영됩니다.

### Sync/Backup

- live DB는 로컬 `DATA_DIR`에 둡니다.
- cloud 폴더에는 `news_scraper_sync_*.zip` 스냅샷만 교환합니다.
- backup/restore는 pending restore 방식으로 다음 시작 시 안전하게 적용합니다.

## 핵심 모듈

| 영역 | 위치 | 역할 |
|---|---|---|
| 부팅 | `core/bootstrap.py` | QApplication, 단일 인스턴스, pending restore |
| 런타임 경로 | `core/runtime_support/` | DATA_DIR, portable mode, legacy migration |
| DB facade | `core/database.py` | connection pool과 mixin 조립 |
| DB schema | `core/db_schema_support/` | table/index/schema migration |
| DB query | `core/db_queries_support/` | fetch/count/archive/analytics query |
| DB mutation | `core/db_mutations_support/` | upsert, read/bookmark/note/tag, maintenance |
| Worker | `core/workers_support/` | ApiWorker, DBWorker, iterative jobs |
| Main UI | `ui/main_window.py` | MainApp facade |
| Main support | `ui/main_window_support/` | shell, config, badge, tray, maintenance |
| Fetch orchestration | `ui/main_window_fetch_support/` | refresh flow and worker cleanup |
| Import/export/sync UI | `ui/main_window_io_support/` | settings, cloud, data export/import |
| News tab | `ui/news_tab.py`, `ui/news_tab_support/` | tab state, loading, rendering, actions |
| Dialogs | `ui/dialogs_support/` | archive, tags, aliases, automation, backup |

## 현재 성능 계약

- Fetch 저장은 `upsert_news_detailed(...)` fast path를 우선 사용합니다.
- 같은 batch의 동일 link는 DB 쓰기 기준 마지막 항목이 이기고, 신규 link 순서는 최초 등장 순서를 따릅니다.
- `news`와 `news_keywords` upsert는 값이 동일하면 UPDATE를 피합니다.
- duplicate flag 재계산은 영향을 받은 title hash로 제한합니다.
- full reload count는 `count_news_states(...)` 한 번으로 total/unread를 계산합니다.
- 탭 badge는 이미 확보한 unread cache를 우선 사용합니다.
- FTS table/backfill은 유지하지만 검색 의미는 LIKE token-AND가 기준입니다.

## 변경 진입점

| 작업 | 우선 확인 위치 |
|---|---|
| 새 DB field/index | `core/db_schema_support/`, `tests/test_db_queries.py` |
| fetch 저장 의미 변경 | `core/db_mutations_support/news_upsert.py`, `core/workers_support/api_worker.py` |
| 목록/count/filter 변경 | `core/db_queries_support/fetch.py`, `ui/news_tab_support/loading_support/` |
| 탭 렌더링/액션 | `ui/news_tab_support/rendering.py`, `ui/news_tab_support/actions_support/` |
| MainApp badge/tray | `ui/main_window_support/ui_shell_support/` |
| 설정 import/export | `ui/main_window_io_support/import_stage_support/`, `core/config_store_support/` |
| cloud snapshot | `core/cloud_sync_support/`, `core/db_cloud_sync_support/` |
| backup/restore | `core/backup_support/`, `ui/dialogs_support/backup_dialog/` |
| 패키징 | `news_scraper_pro.spec`, `tests/test_spec_runtime_tmpdir.py` |

## 유지보수 규칙

- 공개 facade와 root compatibility wrapper를 깨지 않습니다.
- 사용자-visible 검색 의미와 필터 의미를 바꿀 때는 DB query, badge, tray, export, archive까지 같이 확인합니다.
- DB write 실패는 성공처럼 삼키지 않고 `DatabaseWriteError`로 드러냅니다.
- DB query 실패는 빈 결과로 숨기지 않고 `DatabaseQueryError`로 드러냅니다.
- PyQt worker는 cancel/cleanup 경로와 thread affinity를 함께 검증합니다.
- `.md`, `.spec`, `.json`, `.ini`, `.yml`, `.yaml`, `.py`는 UTF-8로 유지합니다.

## 검증 세트

```bash
python -m pytest -q
python -m pyright
python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q
```

패키징 변경이나 릴리스 전에는 아래도 실행합니다.

```bash
python -m PyInstaller --noconfirm --clean news_scraper_pro.spec
```
