# Claude AI Assistant Guidelines - 뉴스 스크래퍼 Pro

> 이 문서는 Claude AI를 위한 프로젝트 컨텍스트 및 지침입니다.

---

## 🎯 프로젝트 컨텍스트

**뉴스 스크래퍼 Pro**는 네이버 뉴스 검색 API를 활용한 **PyQt6 기반 데스크톱 애플리케이션**입니다.

### 핵심 기능
- 🔖 **탭 기반 키워드 검색**: 여러 키워드를 독립 탭으로 관리
- ⏰ **자동 새로고침**: 10분~6시간 주기 백그라운드 업데이트
- 📌 **북마크 & 메모**: 중요 기사 영구 저장
- 🖥️ **시스템 트레이 통합**: 최소화/종료 시 트레이 상주
- 🌙 **라이트/다크 테마**: 현대적 UI 디자인

---

## 🛠️ 기술 스택

```yaml
언어: Python 3.10+ (개발/검증 기준 3.14)
GUI: PyQt6 (Qt 6.x)
데이터베이스: SQLite3
HTTP: requests
패키징: PyInstaller
정적 분석: Pyright / Pylance
```

---

## 📁 프로젝트 구조

```
navernews-tabsearch/
│
├── news_scraper_pro.py          # 엔트리포인트 + 호환 re-export 레이어
├── news_scraper_pro.spec        # PyInstaller 빌드 설정
├── pyrightconfig.json           # Pyright/Pylance 기준 설정
├── pytest.ini                   # pytest 진입점/수집 경로 고정
├── core/                        # 코어 로직 패키지
│   ├── __init__.py
│   ├── bootstrap.py             # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py             # RuntimePaths facade + 경로/버전 상수 (VERSION = '32.7.3')
│   ├── config_store.py          # 설정 스키마 정규화 + 원자 저장/.backup 회전
│   ├── database.py              # DatabaseManager facade (연결 풀 수명 주기)
│   ├── http_client.py           # 중앙 HTTP 구성 + worker-owned session factory
│   ├── runtime_support/         # runtime path 계산 + 레거시 파일 마이그레이션
│   │   ├── paths.py
│   │   └── migration.py
│   ├── _db_schema.py            # 스키마 초기화 / 무결성 검사 / 복구
│   ├── _db_duplicates.py        # 제목 해시 / 중복 플래그 재계산
│   ├── _db_queries.py           # 조회 / 개수 / 미읽음 집계
│   ├── _db_mutations.py         # upsert / 상태 변경 / 삭제 / 읽음 처리
│   ├── _db_analytics.py         # 통계 / 언론사 분석
│   ├── protocols.py             # lock/session Protocol 계약
│   ├── workers.py               # ApiWorker/DBWorker/AsyncJobWorker/IterativeJobWorker/InterruptibleReadWorker/DBQueryScope
│   ├── worker_registry.py       # WorkerHandle/WorkerRegistry (요청 ID 기반 관리)
│   ├── query_parser.py          # parse_tab_query/parse_search_query/has_positive_keyword/build_fetch_key
│   ├── backup.py                # AutoBackup/on-demand backup verification/apply_pending_restore_if_any
│   ├── backup_guard.py          # 리팩토링 백업 유틸리티
│   ├── startup.py               # StartupManager/StartupStatus (Windows 자동 시작 상태/레지스트리)
│   ├── keyword_groups.py        # KeywordGroupManager
│   ├── logging_setup.py         # configure_logging
│   ├── notifications.py         # NotificationSound
│   ├── text_utils.py            # TextUtils, parse_date_string, perf_timer, LRU 캐시
│   └── validation.py            # ValidationUtils
├── ui/                          # UI 로직 패키지
│   ├── __init__.py
│   ├── main_window.py           # MainApp facade / composition root
│   ├── main_window_support/     # MainApp 세부 책임 분리
│   │   ├── base.py
│   │   ├── config.py
│   │   └── ui_shell.py
│   ├── _main_window_tabs.py     # 탭 추가/닫기/리네임/그룹 연결
│   ├── _main_window_fetch.py    # fetch orchestration / worker 수명 주기
│   ├── _main_window_settings_io.py # 설정 import/export / 유지보수 동기화
│   ├── _main_window_tray.py     # 트레이 / 종료 / closeEvent 처리
│   ├── _main_window_analysis.py # 통계 / 분석 UI
│   ├── news_tab.py              # NewsTab facade / compatibility root
│   ├── news_tab_support/        # NewsTab 상태/로딩/렌더링/액션 분리
│   │   ├── state.py
│   │   ├── loading.py
│   │   ├── rendering.py
│   │   ├── ui_controls.py
│   │   └── actions.py
│   ├── dialog_adapters.py       # QFileDialog/QMessageBox adapter
│   ├── protocols.py             # 메인 윈도우/부모 capability Protocol
│   ├── settings_dialog.py       # SettingsDialog facade
│   ├── _settings_dialog_content.py # 설정/도움말/단축키 탭 조립
│   ├── _settings_dialog_docs.py # 도움말 / 단축키 HTML
│   ├── _settings_dialog_tasks.py # API 검증 / 데이터 정리 / 워커 정리
│   ├── dialogs.py               # NoteDialog/LogViewerDialog/KeywordGroupDialog/BackupDialog
│   ├── styles.py                # Colors/UIConstants/ToastType/AppStyle
│   ├── toast.py                 # ToastQueue/ToastMessage
│   └── widgets.py               # NewsBrowser/NoScrollComboBox
├── tests/                       # 회귀/호환성/안정성 테스트
│   ├── test_db_queries.py
│   ├── test_entrypoint_bootstrap.py
│   ├── test_import_settings_dedupe.py
│   ├── test_import_settings_normalization.py
│   ├── test_pagination_state_persistence.py
│   ├── test_plan_regression.py
│   ├── test_pending_restore_strict.py
│   ├── test_refactor_backup_guard.py
│   ├── test_refactor_compat.py
│   ├── test_settings_roundtrip.py
│   ├── test_single_instance_guard.py
│   ├── test_stability.py
│   ├── test_startup_registry_command.py
│   ├── test_symbol_resolution.py
│   ├── test_keyword_groups_storage.py
│   ├── test_backup_restore_mode.py
│   ├── test_dialog_adapters_smoke.py
│   ├── test_import_refresh_prompt.py
│   ├── test_news_tab_ext_read_policy.py
│   ├── test_shutdown_cleanup.py
│   ├── test_news_tab_performance.py
│   ├── test_settings_dialog_maintenance.py
│   └── test_risk_fixes.py
├── query_parser.py              # 호환 래퍼 (→ core.query_parser)
├── config_store.py              # 호환 래퍼 (→ core.config_store)
├── backup_manager.py            # 호환 래퍼 (→ core.backup)
├── worker_registry.py           # 호환 래퍼 (→ core.worker_registry)
├── workers.py                   # 호환 래퍼 (→ core.workers)
├── database_manager.py          # 호환 래퍼 (→ core.database)
├── styles.py                    # 호환 래퍼 (→ ui.styles)
├── news_icon.ico                # 앱 아이콘
├── README.md                    # 사용자 문서
├── implementation_audit_2026-04-18.md # 2026-04-18 감사 후속 기록
└── dist/                        # PyInstaller 빌드 결과물
```

---

## ✅ 현재 검증 기준

- `python -m pytest -q` => `251 passed, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`
- `tests/test_encoding_smoke.py`는 저장소 주요 텍스트 자산 전체에 대해 UTF-8 decode 실패, replacement char, 알려진 깨진 토큰, 대표적인 mojibake 패턴을 계속 감시한다.
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)

---

## 🚀 2026-04-22 RuntimePaths / Support-Module Refactor + Docs/Spec/Gitignore Revalidation

- Current verification line:
  - `python -m pytest -q` => `251 passed, 5 subtests passed`
  - `pyright` => `0 errors, 0 warnings, 0 informations`
  - `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)
- Runtime storage / migration:
  - `RuntimePaths`가 `config`, `db`, `log`, `pending_restore`, `backups`, lock/crash artifact 경로를 단일 객체로 묶고, `core.constants`는 호환 facade만 유지한다.
  - 레거시 파일 마이그레이션은 `core/runtime_support/migration.py`로 분리되었고, DB는 SQLite backup API 우선 + fallback integrity 검증, `pending_restore.json`은 `backup_dir` rebasing, `backups/`는 폴더 단위 merge로 강화됐다.
- Internal structure split:
  - `MainApp` 구현은 `ui/main_window_support/{base,config,ui_shell}.py`로, `NewsTab` 구현은 `ui/news_tab_support/{state,loading,rendering,ui_controls,actions}.py`로 분리되었다.
  - public import path (`ui.main_window.MainApp`, `ui.news_tab.NewsTab`)와 facade 진입점은 유지된다.
- Docs / packaging / repo hygiene:
  - `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, `news_scraper_pro.spec`를 현재 구조 기준으로 다시 동기화했다.
  - `.gitignore`는 portable/legacy 실행 폴더에 남을 수 있는 `keyword_groups.json`, `news_scraper_pro.lock`을 추가로 무시한다.
  - `implementation_audit_2026-04-18.md`를 복구해 감사 후속 기록이 저장소에서 빠지지 않도록 맞췄다.

## 🚀 2026-04-18 Implementation Follow-through + Docs/Spec/Gitignore Revalidation

- Current verification line:
  - `python -m pytest -q` => `236 passed, 5 subtests passed`
  - `pyright` => `0 errors, 0 warnings, 0 informations`
  - `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)
- Maintenance / refresh / alert correctness:
  - Settings-dialog maintenance actions now stage their completion result and flush parent sync only after maintenance teardown, so open-tab reload, badge refresh, and tray tooltip sync no longer race with the maintenance guard.
  - Sequential refresh now shares the same success-side notification path as manual refresh, including per-tab desktop/tray notifications and alert-keyword checks.
  - Fetch success UI now treats `new_items` / `new_count` as the canonical "new article" contract, so duplicate-titled-but-new links still participate in notifications and summary text.
  - `ApiWorker` now honors HTTP `Retry-After` for 429 responses in both delta-seconds and HTTP-date forms, and uses the same computed value for retry sleep and final cooldown metadata.
- Docs / packaging / repo hygiene:
  - Re-synced `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, and `news_scraper_pro.spec`.
  - Re-reviewed `.gitignore` with `git status --ignored --short`; existing rules still cover build outputs, caches, and local runtime artifacts, so no new ignore entry was required.
  - Recreated `implementation_audit_2026-04-18.md` as a checked-in follow-through summary for the resolved audit scope.

## 🚀 2026-04-16 Follow-up Risk Fixes + Docs/Spec Revalidation

- Fetch / hydration / long-task correctness:
  - `ApiWorker`는 `500/502/503/504` 등 `5xx`를 재시도 경로로 편입하고, 최종 실패 시에도 `retryable=True`인 `http_error` 메타를 유지한다.
  - `NewsTab` 초기 hydration은 request-id 취소 + late cleanup으로 hardened 되었고, 현재 탭 우선/나머지 순차 hydration queue가 maintenance, sequential refresh, shutdown 경계에서 멈추고 다시 이어진다.
  - `모두 읽음`, 오래된 기사 삭제, 전체 기사 삭제는 chunked `IterativeJobWorker` 경로로 이동해 `stop()`이 실제로 작업 중단에 반영된다.
- Import / backup / analysis / FTS:
  - 설정 import는 `stage -> persist -> apply-runtime -> startup reconcile` 순서로 재구성돼 부분 적용된 UI/runtime 상태를 남기지 않는다.
  - backup metadata는 legacy `include_db` 누락을 tri-state로 읽고 실제 payload 파일로 보정하며, 수동 검증/복원 직전 검증은 `last_verified_at`을 포함한 verification/restorable 메타를 `backup_info.json`에 저장한다.
  - 통계/언론사 분석은 `InterruptibleReadWorker`로 로드되고, 다이얼로그 종료 시 SQLite read interruption을 같이 요청한다.
  - startup FTS backfill은 dedicated retry scheduler로 `5s -> 15s -> 30s cap` backoff를 사용하며 maintenance/fetch 경계에서 pause/resume 된다.
- Docs / packaging / repo hygiene:
  - `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, `news_scraper_pro.spec`를 현재 구현/검증선으로 다시 동기화했다.
  - `.gitignore`는 빌드 후 `git status --ignored` 기준으로 다시 확인했으며, 기존 규칙이 `build/`, `dist/`, `.pytest_tmp/`, 로그/캐시 산출물을 계속 충분히 덮고 있어 추가 규칙이 필요하지 않았다.

---

## 🚀 2026-04-13 Implementation Risk Plan Closure

- Fetch / DB write correctness:
  - Added `core.database.DatabaseWriteError` and changed `upsert_news(...)` to raise on write failures instead of silently returning `(0, 0)`.
  - `ApiWorker` now routes DB read failures and DB write failures through explicit error paths, so fetch success toasts/notifications only happen after a successful DB upsert.
  - `MainApp.on_fetch_error(...)` now distinguishes DB errors from API/network errors in user-facing messaging.
- Legacy migration completion:
  - Replaced one-shot `LIMIT 1000` / `LIMIT 5000` startup backfills for `title_hash` and `pubDate_ts` with repeated chunk loops that run until no `NULL` rows remain.
  - Added regression coverage for legacy databases larger than the old chunk limits.
- Encoding / repo text hygiene:
  - Cleaned remaining mojibake UI/test literals in the repository.
  - Expanded `tests/test_encoding_smoke.py` from a single-token check to a multi-token + suspicious-pattern guard.
- Settings validation HTTP parity:
  - Settings-dialog API validation now uses the same `HttpClientConfig` session policy and the current `api_timeout` value from the dialog.
  - Added dedicated regression coverage so validation does not regress to raw `requests.get(...)` + fixed timeout behavior.
- Docs / spec / repo hygiene:
  - Re-synced `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, and `news_scraper_pro.spec`.
  - Re-reviewed `.gitignore`; this pass does not require new ignore rules.

---

## 🚀 2026-04-09 Implementation Risk Audit Plan Completion

- Fetch control plane:
  - Added `core.http_client.HttpClientConfig` so `ApiWorker` now builds a worker-owned `requests.Session` from centralized HTTP settings instead of depending on a mutable shared session on `MainApp`.
  - `ApiWorker.last_error_meta` now exposes `kind`, `status_code`, `cooldown_seconds`, `retryable`; `MainApp.on_fetch_error(...)` uses this to update a global fetch cooldown.
  - Manual refresh, auto refresh, sequential refresh, and `더 불러오기` now all check the same cooldown gate before starting.
- DB read/export stability:
  - Added `DatabaseManager.iter_news_snapshot_batches(...)` so CSV export traverses one read snapshot from start to finish instead of live offset paging across separate reads.
  - `DBWorker` now uses `open_read_connection(...)` / `interrupt_connection(...)` / `close_read_connection(...)` and requests interruption on `stop()` to improve cancellation during maintenance/close paths.
- Analysis async + FTS accelerator:
  - `show_statistics()` and `show_stats_analysis()` now open dialogs immediately and load DB-backed content through `AsyncJobWorker` with stale-result guards.
  - Added SQLite FTS5 schema (`news_fts`), sync triggers, `app_meta`, and incremental backfill worker startup. Until backfill completes, the app keeps the old `LIKE/NOT LIKE` SQL path as the semantic source of truth.
- Docs / spec / tests:
  - Synced `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, and `news_scraper_pro.spec` to the new contracts.
  - Added regression coverage for fetch cooldown, async analysis loading, FTS acceleration/backfill, snapshot export, and dedicated-read DB worker cancellation.

---

## 🚀 2026-04-05 Implementation Risk Audit Full Adoption

- DB 조회 실패 계약:
  - `core.database.DatabaseQueryError`를 도입해 `fetch_news(...)`, `count_news(...)`, `get_counts(...)`, unread 집계, `get_existing_links_for_query(...)`, `get_statistics(...)`, `get_top_publishers(...)`가 더 이상 `[]`/`0`으로 silent fallback 하지 않게 했다.
  - `DBWorker`는 query failure를 `error` 시그널로 올리고, `NewsTab`은 기존 캐시를 보존한 채 상태바/토스트로 실패를 알린다.
  - 통계/분석처럼 사용자가 명시적으로 연 작업은 bogus 빈 화면 대신 warning dialog를 사용한다.
- 유지보수 모드 전면 차단:
  - `MainApp` / `MainWindowProtocol`에 공용 maintenance guard를 추가했다.
  - fetch/load-more뿐 아니라 탭 DB 재조회, 필터/정렬/기간 변경 reload, CSV export, 통계/분석, `모두 읽음`, import 후 선택 refresh까지 차단한다.
  - 유지보수 진입/해제 시 관련 버튼/조작 가능 상태를 일관되게 잠그고 복원한다.
- 저장/백업 UX 정리:
  - `KeywordGroupManager.save_groups()`는 실패를 삼키지 않고, `KeywordGroupDialog.accept()`는 저장 실패 시 닫히지 않아 재시도 가능하다.
  - `AutoBackup.create_backup()`는 생성 직후 self-verify를 수행하고, 실패한 백업도 삭제하지 않은 채 목록에 `복원 불가` 상태로 남긴다.
  - import 후 새 탭 refresh prompt는 실제 실행 가능 여부를 먼저 확인한 뒤에만 노출한다.
- 타입/문서/패키징:
  - 테스트 더미의 direct mixin aliasing을 wrapper/cast 방식으로 정리해 `pyright`를 다시 `0 errors` 상태로 맞췄다.
  - `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, `news_scraper_pro.spec`를 현재 계약에 맞춰 갱신했다.
  - `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했고, 산출물은 `dist/NewsScraperPro_Safe.exe`다.

---

## 🚀 2026-04-02 Implementation Audit Full Adoption

- Dialog isolation:
  - Added `ui.dialog_adapters.QtDialogAdapter` and routed CSV export, settings export/import, and backup create/restore/delete through it.
  - Unit tests now inject fake adapters instead of patching Qt static dialogs directly.
  - Added offscreen smoke coverage for the real Qt dialog wiring.
- Shutdown hardening:
  - `MainApp._perform_real_close()` now cleans open `NewsTab` instances before DB/session teardown.
  - `NewsTab.cleanup()` is now idempotent and stops timers, detaches worker signals, interrupts/waits active `DBWorker` and `AsyncJobWorker`, and clears request/render state.
  - `AsyncJobWorker.stop()` was added so close paths can request interruption consistently.
- Backup integrity:
  - `AutoBackup.create_backup()` now requires a restorable payload preflight; config-file absence fails backup creation even for settings-only backups.
  - Manual backup UI prechecks config/db presence before create.
  - Startup auto-backup skips quietly when config is missing.
- Settings import UX:
  - Import tracks newly added tabs and asks once whether to refresh them immediately.
  - Added `refresh_selected_tabs(...)` so only imported tabs are queued, without mutating the global refresh-all path.
- Test/runtime alignment:
  - Added `tests/conftest.py` so pytest temp files stay under workspace-local `.pytest_tmp` in restricted environments.
  - Added regression coverage for backup preflight, import refresh prompt, shutdown cleanup, and dialog adapter wiring.
- Packaging / repo hygiene:
  - Re-reviewed `news_scraper_pro.spec`; dialog adapter isolation, shutdown cleanup sequencing, backup preflight tightening, and selective import refresh do not require additional hidden import/exclude/data changes.
  - Re-reviewed `.gitignore`; existing runtime/build/test ignore rules already cover this pass, so no new ignore entry was required.

### Validation
- `python -m pytest -q` => `196 passed, 5 subtests passed`
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)

---

## 🚀 2026-03-27 UI/UX Hardening + Docs/Packaging Revalidation

- `ui.settings_dialog.SettingsDialog`는 `help_mode` / `initial_tab`을 지원하고, `MainApp.show_help()`는 저장 경로와 분리된 read-only 도움말 다이얼로그를 연다.
- `ui.news_tab.NewsTab`은 기간 필터를 `적용`/`해제` 흐름으로 명시화했고, 외부 기사 열기 실패 시 읽음 처리하지 않으며, 하단 unread 수치를 현재 DB scope 기준으로 유지한다.
- `ui.main_window.MainApp`은 자동 새로고침 카운트다운을 전용 상태바 라벨로 분리하고, 트레이 미지원 환경에서도 데스크톱 fallback 알림을 유지한다.
- `ui.dialogs.KeywordGroupDialog`는 staged save/cancel 모델로 바뀌었고, `LogViewerDialog`는 debounce 검색을 사용하며, `BackupDialog`의 무거운 백업 검증은 사용자가 직접 시작한다.
- `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`, `news_scraper_pro.spec`를 현재 동작 기준으로 다시 맞췄다.
- `.gitignore`는 build/dist/runtime 산출물을 이미 충분히 무시하고 있어 이번 패스에서 추가 규칙이 필요하지 않았다.

---

## 🚀 2026-03-21 성능 리팩토링 메모

- `core.workers.DBQueryScope`가 탭 조회 scope 계산을 단일화하고, append 경로는 `known_total_count`를 재사용해 `count_news(...)`를 다시 호출하지 않는다.
- `ui.news_tab.NewsTab`은 `_item_by_link`로 단건 상태 변경 대상을 O(1)에 찾고, fragment cache + event-loop coalesced render로 HTML flush를 줄인다.
- `core._db_schema.init_db()`는 `news_keywords(query_key, keyword)`, `news_keywords(query_key, keyword, is_duplicate)`, `news(is_bookmarked, is_read, pubDate_ts DESC)` 복합 인덱스를 보장한다.
- `news_scraper_pro.spec`는 2026-03-21 기준으로 재검토되었고, 이번 패스는 표준 라이브러리/기존 번들 의존성만 사용하므로 추가 packaging 수정이 필요하지 않다.

---

## 📦 2026-03-24 문서/패키징 재검증 메모

- `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`를 현재 구조/검증 기준에 맞춰 다시 대조한다.
- `news_scraper_pro.spec`는 2026-03-24 기준 재검토되었고, 2026-03-21 성능 리팩토링 이후에도 추가 hidden import/exclude/data 수정이 필요하지 않다.
- `.gitignore`는 `build/`, `dist/`, 런타임 DB/복구 잔여물을 이미 무시하므로 이번 패스에서 추가 규칙이 필요하지 않다.
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했고, 산출물은 `dist/NewsScraperPro_Safe.exe`다.

---

## 🔍 코드 탐색 가이드

### 주요 클래스 위치

| 클래스명 | 설명 | 위치 |
|----------|------|-------------|
| `Colors` | 테마 색상 상수 | `ui/styles.py` |
| `AppStyle` | QSS 스타일시트 + HTML 템플릿 | `ui/styles.py` |
| `UIConstants` | UI 상수 | `ui/styles.py` |
| `ToastType` | 토스트 메시지 유형 열거 | `ui/styles.py` |
| `ToastQueue` | 토스트 메시지 큐 관리 | `ui/toast.py` |
| `ToastMessage` | 토스트 메시지 위젯 | `ui/toast.py` |
| `NewsBrowser` | 커스텀 브라우저 (링크 차단, 미리보기) | `ui/widgets.py` |
| `NoScrollComboBox` | 휠 스크롤 방지 콤보박스 | `ui/widgets.py` |
| `DatabaseManager` | 스레드 안전 DB 매니저 (연결 풀) | `core/database.py` |
| `HttpClientConfig` | HTTP 풀/헤더 정책과 worker-owned session 생성기 | `core/http_client.py` |
| `ApiWorker` | API 호출 워커 (재시도, DB 저장) | `core/workers.py` |
| `DBWorker` | `DBQueryScope`를 소비하는 DB 조회 전용 워커 스레드 | `core/workers.py` |
| `AsyncJobWorker` | 단발성 비동기 작업 워커 | `core/workers.py` |
| `IterativeJobWorker` | 취소 가능한 반복형 장시간 작업 워커 | `core/workers.py` |
| `InterruptibleReadWorker` | SQLite read interruption을 지원하는 분석/집계 전용 워커 | `core/workers.py` |
| `DBQueryScope` | 탭 조회 scope를 정규화한 내부 dataclass | `core/workers.py` |
| `WorkerRegistry` | 요청 ID 기반 워커 레지스트리 | `core/worker_registry.py` |
| `WorkerHandle` | 워커 핸들 데이터클래스 | `core/worker_registry.py` |
| `LockFileProtocol` | 단일 인스턴스 lock capability 계약 | `core/protocols.py` |
| `RequestGetProtocol` / `ClosableProtocol` | requests 세션 capability 계약 | `core/protocols.py` |
| `AutoBackup` | 설정/DB 자동 백업 | `core/backup.py` |
| `KeywordGroupManager` | 키워드 그룹(폴더) 관리 | `core/keyword_groups.py` |
| `StartupManager` | Windows 시작프로그램 레지스트리 | `core/startup.py` |
| `StartupStatus` | 자동 시작 등록 health 상태 구조체 | `core/startup.py` |
| `NotificationSound` | 시스템 알림 소리 재생 | `core/notifications.py` |
| `ValidationUtils` | API 키/키워드 입력 검증 | `core/validation.py` |
| `TextUtils` | 텍스트 처리 (하이라이팅 등) | `core/text_utils.py` |
| `AppConfig` | 설정 파일 TypedDict 스키마 | `core/config_store.py` |
| `MainApp` | 메인 윈도우 | `ui/main_window.py` |
| `MainWindowProtocol` | `NewsTab`이 의존하는 메인 윈도우 capability | `ui/protocols.py` |
| `NewsTab` | 개별 뉴스 탭 위젯 (fragment cache + coalesced render) | `ui/news_tab.py` |
| `SettingsDialog` | 설정 다이얼로그 | `ui/settings_dialog.py` |
| `SettingsDialogParentProtocol` | `SettingsDialog` 부모 capability | `ui/protocols.py` |
| `NoteDialog` | 메모 편집 다이얼로그 | `ui/dialogs.py` |
| `LogViewerDialog` | 로그 뷰어 다이얼로그 | `ui/dialogs.py` |
| `KeywordGroupDialog` | 키워드 그룹 관리 다이얼로그 | `ui/dialogs.py` |
| `BackupDialog` | 백업 관리 다이얼로그 | `ui/dialogs.py` |

---

## ⚙️ 설정 구조

### Runtime Storage (`DATA_DIR`)

- Windows 기본값: `%LOCALAPPDATA%\\NaverNewsScraperPro`
- macOS 기본값: `~/Library/Application Support/NaverNewsScraperPro`
- Linux 기본값: `$XDG_DATA_HOME/NaverNewsScraperPro` 또는 `~/.local/share/NaverNewsScraperPro`
- `NEWS_SCRAPER_DATA_DIR` 환경변수로 강제 지정 가능
- `NEWS_SCRAPER_PORTABLE=1`이면 `APP_DIR` 사용
- 시작 시 실행 폴더의 레거시 `news_scraper_config.json`, `news_database.db`, `pending_restore.json`, `backups/`는 비파괴적으로 `DATA_DIR`로 복사 마이그레이션됨

### news_scraper_config.json

```json
{
    "app_settings": {
        "client_id": "네이버 API Client ID",
        "client_secret": "네이버 API Client Secret",
        "client_secret_enc": "",
        "client_secret_storage": "plain",   // plain | dpapi
        "theme_index": 0,              // 0=라이트, 1=다크
        "refresh_interval_index": 2,   // 콤보박스 인덱스
        "notification_enabled": true,
        "minimize_to_tray": true,      // 최소화 버튼 → 트레이
        "close_to_tray": true,         // 닫기(X) 버튼 → 트레이
        "api_timeout": 15
    },
    "tabs": ["키워드1", "키워드2"],
    "search_history": [],
    "keyword_groups": {
        "그룹명": ["키워드1", "키워드2"]
    },
    "pagination_state": {
        "<fetch_key>": 301
    }
}
```

---

## 🎨 스타일 가이드라인

### 색상 사용

```python
# ✅ 올바른 사용 (ui/styles.py에서 임포트)
from ui.styles import Colors

# 위젯 적용
widget.setStyleSheet(f"color: {Colors.LIGHT_PRIMARY};")
```

### 토스트 메시지

```python
# 성공 알림
self.toast_queue.add("저장되었습니다", ToastType.SUCCESS)

# 오류 알림
self.toast_queue.add(f"오류: {error}", ToastType.ERROR)

# 정보 알림
self.toast_queue.add("새 기사 10건", ToastType.INFO)

# 경고 알림
self.toast_queue.add("API 키를 확인하세요", ToastType.WARNING)
```

---

## 🔒 스레드 안전성

### DatabaseManager 사용

```python
# ✅ 안전한 DB 접근 (권장)
with self.db_manager.connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM articles WHERE keyword=?", (keyword,))
    results = cursor.fetchall()

# ❌ 직접 연결 금지
conn = sqlite3.connect("news_database.db")  # 스레드 문제 발생
```

### QThread 패턴

```python
class SearchWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def run(self):
        try:
            results = self.search_news()
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
```

### 탭 키워드 파싱 정책 (v32.5.0)

탭 문자열 파싱은 반드시 `parse_tab_query(raw)`를 사용합니다.

```python
db_keyword, exclude_words = parse_tab_query("IT 기술 -광고")
# db_keyword: "IT"  (레거시 정책 유지)
# exclude_words: ["광고"]
```

- 조회/배지/리네임/수집 경로에서 동일한 파싱 함수를 사용해 동작 일관성을 유지합니다.
- 신규 코드에서 `split()[0]` 직접 파싱은 사용하지 않습니다.
- 탭 문자열은 최소 1개 이상의 양(+) 키워드를 포함해야 하며, 제외어-only 입력은 허용하지 않습니다.

---

## 🐛 자주 발생하는 이슈

### 1. HiDPI 스케일링 문제
```python
# PyQt6 import 전에 반드시 설정
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
```

### 2. PyInstaller 경로 문제
```python
def get_app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))
```

### 3. 링크 클릭 시 화면 깜빡임
```python
# NewsBrowser에서 setOpenLinks(False) 설정
self.setOpenExternalLinks(False)
self.setOpenLinks(False)
```

---

## 📝 수정 체크리스트

코드 수정 시 다음을 확인하세요:

- [ ] `VERSION` 상수 업데이트
- [ ] `update_history.md`에 변경 내역 추가
- [ ] 라이트/다크 테마 모두 테스트
- [ ] PyInstaller 빌드 테스트
- [ ] 로깅 추가 (`logger.info`, `logger.error`)
- [ ] 타입 힌트 작성
- [ ] 한국어 UI 텍스트 일관성

---

## 🧭 작업 유형별 가이드

### UI 수정 시
1. `Colors` 클래스에서 색상 확인
2. `AppStyle.LIGHT` 및 `AppStyle.DARK` 동시 수정
3. `UIConstants`에서 패딩, 마진 등 참조

### DB 스키마 수정 시
1. `DatabaseManager._init_schema()` 수정
2. 마이그레이션 로직 추가
3. 기존 사용자 데이터 보존 확인

### 새 기능 추가 시
1. 관련 클래스 위치 파악 (위 테이블 참조)
2. 시그널/슬롯 패턴 준수
3. 설정 항목이 필요하면 
ews_scraper_config.json` 스키마 확장

### 버그 수정 시
1. 
ews_scraper.log` 확인
2. 관련 예외 처리 강화
3. 토스트 메시지로 사용자 알림

---

## 🔧 워커 클래스 패턴

### ApiWorker (API 호출)

```python
class ApiWorker(QObject):
    """비동기 API 호출 워커"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    
    def __init__(self, client_id, client_secret, search_query,
                 db_keyword, exclude_words, db_manager, start_idx=1,
                 max_retries=3, timeout=15, session=None,
                 display_keyword=None):
        ...
    
    def run(self):
        """재시도 로직 포함 API 호출"""
        for attempt in range(self.max_retries):
            try:
                resp = session.get(url, headers=headers, params=params)
                # 429 Rate Limit 처리
                # 결과 DB 저장
                self.finished.emit(result)
            except requests.Timeout:
                # 재시도
            ...
    
    def stop(self):
        self._destroyed = True
        self.is_running = False
```

### DBWorker (DB 조회)

```python
class DBWorker(QThread):
    """비동기 DB 조회 워커"""
    finished = pyqtSignal(list, int)  # data, total_count
    error = pyqtSignal(str)
    
    def run(self):
        search_keyword, exclude_words = parse_search_query(self.keyword)
        db_keyword, _ = parse_tab_query(self.keyword)
        query_key = build_fetch_key(search_keyword, exclude_words)

        total_count = self.db.count_news(...)
        data = self.db.fetch_news(..., limit=self.limit, offset=self.offset)

        self.finished.emit(data, total_count)
```

### AsyncJobWorker (범용 비동기)

```python
class AsyncJobWorker(QThread):
    """단발성 비동기 작업 수행"""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    
    def __init__(self, job_func, *args, **kwargs):
        self.job_func = job_func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        result = self.job_func(*self.args, **self.kwargs)
        self.finished.emit(result)
```

---

## 📝 HTML 템플릿 시스템

### AppStyle.HTML_TEMPLATE

뉴스 렌더링에 사용되는 CSS 템플릿 (Colors 헬퍼와 함께 사용):

```python
colors = Colors.get_html_colors(is_dark=True)
css = AppStyle.HTML_TEMPLATE.format(**colors)
```

### 뉴스 아이템 HTML 구조

```html
<div class="news-item read duplicate">
    <a href="app://open/{hash}" class="title-link">⭐ 제목</a>
    <div class="meta-info">
        <span class="meta-left">
            📰 언론사 · 날짜 
            <span class="keyword-tag">키워드</span>
            <span class="duplicate-badge">유사</span>
        </span>
        <span class="actions">
            <a href='app://share/{hash}'>공유</a>
            <a href='app://ext/{hash}'>외부</a>
            <a href='app://note/{hash}'>메모 📝</a>
            <a href='app://bm/{hash}'>북마크</a>
        </span>
    </div>
    <div class="description">기사 요약...</div>
</div>
```

---

## ⚙️ 설정 옵션 상세

### app_settings 전체 필드

```json
{
    "app_settings": {
        "client_id": "네이버 클라이언트 ID",
        "client_secret": "네이버 클라이언트 시크릿",
        "client_secret_enc": "",
        "client_secret_storage": "plain",   // plain | dpapi
        "theme_index": 0,              // 0=라이트, 1=다크
        "refresh_interval_index": 2,   // 0=10분, 1=30분, 2=1시간...
        "notification_enabled": true,  // 데스크톱 알림
        "alert_keywords": [],          // 특정 키워드 알림
        "sound_enabled": true,         // 알림 소리
        "minimize_to_tray": true,      // 최소화→트레이
        "close_to_tray": true,         // 닫기→트레이
        "start_minimized": false,      // 최소화 상태로 시작
        "auto_start_enabled": false,   // Windows 시작 시 자동 실행
        "notify_on_refresh": false,    // 새로고침 완료 알림
        "api_timeout": 15,             // API 타임아웃 (초)
        "window_geometry": {           // 창 위치/크기
            "x": 100, "y": 100,
            "width": 1100, "height": 850
        }
    },
    "tabs": ["키워드1", "키워드2"],
    "search_history": [],
    "keyword_groups": {                // KeywordGroupManager 관리
        "그룹명": ["키워드1", "키워드2"]
    },
    "pagination_state": {              // fetch_key -> 마지막 API start 인덱스
        "<fetch_key>": 301
    }
}
```

### 설정 Export/Import 현재 정책

- export 포맷 버전은 `1.2`
- API 자격증명(`client_id`, `client_secret`, `client_secret_enc`)은 export/import 대상에서 제외
- `settings.auto_start_enabled`는 export/import 대상에 포함
- import는 `1.1`과 `1.2`를 모두 허용
- 트레이/자동 시작 미지원 환경에서는 `start_minimized`, `auto_start_enabled`를 안전한 값으로 보정
- 자동 시작 import는 UI 상태만이 아니라 실제 `StartupManager.enable_startup(...)` / `disable_startup()` 호출로 로컬 레지스트리 상태까지 동기화

### 새로고침 간격 인덱스

| 인덱스 | 간격 |
|--------|------|
| 0 | 10분 |
| 1 | 30분 |
| 2 | 1시간 |
| 3 | 2시간 |
| 4 | 6시간 |
| 5 | 비활성화 |

---

## 🐞 문제 해결 가이드

### 1. API 오류

```python
# HTTP 401: 인증 실패
→ API 키 확인 (설정 다이얼로그)

# HTTP 429: 요청 제한 초과
→ 자동 재시도 (2초, 4초, 6초 대기)
→ 실패 시 "잠시 후 다시 시도" 메시지

# HTTP 5xx: 서버 오류
→ 네이버 API 서버 상태 확인
```

### 2. DB 오류

```python
# "database is locked"
→ 다른 프로세스가 DB 사용 중
→ 앱 재시작 또는 프로세스 확인

# 테이블 없음
→ DatabaseManager._init_schema() 자동 실행됨
→ 수동 복구: DB 파일 삭제 후 재시작
```

### 2-1. 백업/복원 무결성 (v32.6.0)

```python
# 백업
# 1) sqlite backup API로 일관된 스냅샷 생성 시도
# 2) 실패 시 파일 복사 fallback
# 3) -wal/-shm sidecar 동시 처리

# 복원
# 1) UI에서 즉시 복원하지 않고 pending restore 예약
# 2) 앱 재시작 시 DB 본체/sidecar(-wal, -shm) 적용
```

- 실행 중 DB 덮어쓰기를 피하기 위해 복원은 재시작 적용 정책으로 고정되었습니다.
- 시작 시 생성되는 자동 백업은 설정만 포함합니다. DB 복원 지점이 필요하면 수동 백업에서 `데이터베이스 포함`을 선택해야 합니다.
- 백업 목록 메타에는 `is_restorable` / `restore_error`가 포함되며, 필요한 payload가 없는 항목은 복원 전에 즉시 차단됩니다.

### 3. UI 깜빡임

```python
# 원인: setOpenLinks(True)가 페이지 내비게이션 유발
# 해결:
self.browser.setOpenExternalLinks(False)
self.browser.setOpenLinks(False)

# 스크롤 위치 유지
scroll_pos = self.browser.verticalScrollBar().value()
self.browser.setHtml(html)
QTimer.singleShot(0, lambda: self.browser.verticalScrollBar().setValue(scroll_pos))
```

### 4. 메모리 누수

```python
# 토스트 애니메이션 정리
if hasattr(self, 'anim_out'):
    self.anim_out.stop()
    self.anim_out.deleteLater()

# 워커 스레드 정리
if self.worker and self.worker.isRunning():
    self.worker.stop()
    self.worker.wait(1000)
```

---

## 🔍 디버깅 팁

### 로그 확인

```python
# 로그 파일 위치
LOG_FILE = os.path.join(DATA_DIR, "news_scraper.log")

# 로그 레벨별 색상 (LogViewerDialog)
[ERROR], [CRITICAL] → 빨간색
[WARNING] → 노란색
[INFO] → 초록색
```

### 런타임 디버깅

```python
# 워커 상태 확인
logger.info(f"ApiWorker 시작: {self.keyword}")
logger.info(f"ApiWorker 완료: {self.keyword} ({len(items)}개)")

# DB 연결 상태
logger.info(f"DB 연결 {closed_count}개 정상 종료")
logger.warning(f"비상 연결 {emergency_count}개가 정리되지 않음")
```

### 크래시 로그

```python
# 예외 발생 시 자동 기록
try:
    ...
except Exception as e:
    logger.error(f"오류: {e}")
    traceback.print_exc()
```

---

## 🎨 테마 커스터마이징

### 새 색상 추가

```python
# Colors 클래스에 추가
class Colors:
    # 새 색상 정의
    LIGHT_MY_COLOR = "#123456"
    DARK_MY_COLOR = "#654321"
    
    @classmethod
    def get_html_colors(cls, is_dark: bool) -> Dict[str, str]:
        if is_dark:
            return {
                ...
                'my_color': cls.DARK_MY_COLOR,
            }
        else:
            return {
                ...
                'my_color': cls.LIGHT_MY_COLOR,
            }
```

### QSS 스타일 수정

```python
# AppStyle 클래스 수정
class AppStyle:
    LIGHT = f"""
        QPushButton#MyButton {{
            background-color: {Colors.LIGHT_MY_COLOR};
        }}
    """
```

---

## 📚 참고 자료

- [네이버 검색 API 문서](https://developers.naver.com/docs/search/news/)
- [PyQt6 공식 문서](https://www.riverbankcomputing.com/static/Docs/PyQt6/)
- [SQLite 문서](https://www.sqlite.org/docs.html)
- [gemini.md](gemini.md) - Gemini AI 지침서

---

## 💡 팁

1. **중간 모듈 분리 구조**: 엔트리포인트는 
ews_scraper_pro.py`이며 핵심 로직은 `query_parser.py`, `config_store.py`, `backup_manager.py`, `workers.py`, `worker_registry.py`로 분리됨
2. **한국어 환경**: UI 텍스트, 로그, 주석 모두 한국어
3. **Windows 특화**: 시스템 트레이, 자동 시작 등 Windows 전용 기능 포함
4. **성능 최적화**: LRU 캐시, 연결 풀, 비동기 처리, 디바운싱 적용됨
5. **버전 관리**: 변경 시 `VERSION` 상수와 `update_history.md` 동시 업데이트



## v32.7.0 → v32.7.1 Refactor Update

### Architecture Baseline
- Entrypoint: 
ews_scraper_pro.py` (thin compatibility layer + re-export)
- Core modules: `core/*` (16개 모듈)
- UI modules: `ui/*` (8개 모듈)
- Compatibility wrappers: root-level `query_parser.py`, `config_store.py`, `backup_manager.py`, `worker_registry.py`, `workers.py`, `database_manager.py`, `styles.py`

### v32.7.1 추가 변경사항
- 단일 인스턴스 가드 (`QLockFile`) 추가
- `sound_enabled`, `api_timeout` 설정 플러밍 보완
- 설정 창 API 키 검증/데이터 정리 비동기 처리
- 설정 가져오기 탭 중복 병합(dedupe) 강화
- 자동 시작 최소화 옵션 변경 시 레지스트리 재등록

### v32.7.3 추가 변경사항
- 장시간 반복 작업용 `IterativeJobWorker` 추가 및 CSV export/백업 검증 경로 적용
- 백업 검증 상태(`pending/ok/failed`)와 SQLite integrity/sidecar 정책 검사 도입
- 백업 생성 직후 self-verify를 수행해 정상 생성 항목은 즉시 `ok`, 실패 항목은 `복원 불가` 상태로 유지
- `StartupManager.get_startup_status()` 도입 및 설정 창 자동 시작 수리 버튼 추가
- 설정 저장 시 `save_primary_config_file()`로 main config + `.backup` 원자 회전 저장
- `NewsTab` 읽음/북마크/메모/삭제 로컬 변경 경로를 helper로 일원화
- DB emergency connection cap/logging 추가

### v32.7.2 추가 변경사항
- `get_statistics()['duplicates']`를 
ews_keywords.is_duplicate` 기준으로 보정
- 설정 가져오기 시 타입/범위 정규화(`theme_index`, `refresh_interval_index`, `api_timeout`, bool 필드, `alert_keywords`)
- 설정 가져오기 `keyword_groups` 정책을 덮어쓰기에서 병합+중복제거로 변경
- 탭 리네임 시 fetch key 변경 여부에 따라 페이지네이션 상태 안전 초기화
- `모두 읽음`을 `현재 표시 결과만`/`탭 전체` 2모드로 확장
- `DatabaseManager.mark_links_as_read(links)` API 추가
- `DatabaseManager.delete_link(link)` API 추가 및 UI 삭제 경로 raw SQL 제거
- 기사 삭제 후 duplicate flag 부분 재계산(`delete_old_news`, `delete_all_news`, `delete_link`)
- pending restore 엄격 정책: `restore_db=true`인데 DB 백업 누락 시 실패 반환 + pending 유지
- `pagination_state` 스키마 추가 및 fetch key 커서 영속화(`더 불러오기` DB count fallback 제거)
- 백업 복원 예약 시 backup metadata(`include_db`) 기반으로 복원 범위 자동 결정 (`설정만`/`설정+DB`)
- `NewsTab` 읽음 상태 변경 공통 경로(`_set_read_state`)로 `open/unread/ext` 정책 일원화
- 읽음 상태 DB 반영 실패 시 UI 캐시/배지 미갱신으로 상태 불일치 방지
- `DatabaseManager.count_news(..., exclude_words=...)` 확장 및 탭 배지 제외어 반영 집계
- 설정 창 워커 종료 안정화(대기 초과 시 parent 분리 + finish 시점 deleteLater 보장)
- 자동 시작 백업에 `trigger=auto` 메타 도입 + 자동/수동 백업 보존 정책 분리
- `BackupDialog` 목록 표시에서 마이크로초 타임스탬프 파싱 + `자동`/`수동` 라벨 추가
- 설정 창의 데이터 정리 완료 후 메인 UI 동기화 훅(`on_database_maintenance_completed`) 추가
- `DatabaseManager.mark_query_as_read(...)` 추가로 `탭 전체` 읽음 처리 시 제외어 조건 보존
- `DatabaseManager.get_top_publishers(..., exclude_words=...)` 확장으로 탭 분석 제외어 반영
- DatabaseManager.connection(timeout=...) 공식 컨텍스트 매니저 추가로 문서/구현 접근 패턴 일치
- DatabaseManager.get_total_unread_count() 추가로 트레이 미읽음 집계를 DB 총계 기준으로 계산
- pending restore 적용을 스테이징+롤백 방식으로 강화 (검증/적용 실패 시 pending 유지)
- AutoBackup.get_backup_list() 항목 메타 확장: is_corrupt, error 필드 제공
- BackupDialog에서 손상 백업 항목을 손상됨으로 표시하고 삭제/무시 분기 제공
### Compatibility Contract
- Keep `python news_scraper_pro.py` launch behavior.
- Keep `import news_scraper_pro as app` compatibility.
- Keep these exports: `parse_tab_query`, `parse_search_query`, `has_positive_keyword`, `build_fetch_key`, `DatabaseManager`, `AutoBackup`, `apply_pending_restore_if_any`, `PENDING_RESTORE_FILENAME`.

### Test Policy
- Prefer behavior/contract tests over monolithic source-string checks.
- Validate entrypoint and wrapper compatibility explicitly.
- Tests: `tests/` 디렉터리의 최신 테스트 모듈 목록을 기준으로 유지/확장.


---

## 2026-02-28 Addendum (Core Stabilization Pass 2)

### Implemented
- Risk 1~8 remediation completed.
- Worker cancellation hardening in `core/workers.py`:
  - cancellation checks after response and before DB upsert
  - worker-owned session close on `stop()`
  - cancellation-path exception silence (no user-facing error emit)
  - case-insensitive exclude-word filtering in worker path
- Session-sharing removed from fetch path in `ui/main_window.py` (`ApiWorker(..., session=self.session)` removed).
- Backup hardening in `core/backup.py`:
  - microsecond backup folder names + collision retry
  - strict `restore_backup(restore_db=True)` DB-file requirement
  - `-wal/-shm` sidecar sync policy aligned with pending-restore behavior
- Load-more terminal-state guard in `ui/main_window.py`:
  - 
ext_start = last_api_start_index + 100`
  - `has_more = next_start <= min(1000, total)`
- `ext` read policy unified in `ui/news_tab.py` via shared helper (open implies read).
- Test entrypoint alignment:
  - added `pytest.ini` (`pythonpath = .`, `testpaths = tests`)

### Added Tests
- `tests/test_worker_cancellation.py`
- `tests/test_backup_collision_and_restore.py`
- `tests/test_load_more_total_guard.py`
- `tests/test_news_tab_ext_read_policy.py`
- extension in `tests/test_stability.py`
- `tests/test_backup_restore_mode.py`

### Validation
- `python -m pytest -q` => `83 passed`
- `pytest -q` => `83 passed`

### Packaging
- 
ews_scraper_pro.spec` reviewed for this pass; no change required.

---

## 2026-03-02 Addendum (Audit Full Adoption)

### Query Policy
- `parse_search_query(raw)`:
  - API request query and fetch-dedupe key
  - all positive keywords joined with spaces
- `parse_tab_query(raw)`:
  - DB grouping key (
ews_keywords.keyword`)
  - first positive keyword only

### Tray + Minimized Startup
- `start_minimized` and `--minimized` are applied only when system tray is available.
- In tray-unavailable environments, app startup must remain visible and show reason in UI.
- Settings dialog must disable `start_minimized` option when tray is unavailable.

### Version/History Guard
- `update_history.md` is required project history source.
- Any `VERSION` update requires a matching update in `update_history.md`.
- Guard test: `tests/test_version_history_guard.py`.

### Spec Sync
- 
ews_scraper_pro.spec` must include `PyQt6.QtNetwork` when bootstrap imports `QLocalServer` / `QLocalSocket`.
- Keep `PyQt6.QtNetwork` in `hiddenimports` and do not place it in `excludes`.

---

## 2026-03-03 Addendum (Audit Remediation Follow-up)

### Implemented
- Backup restore mode auto-detection:
  - `BackupDialog` now stores backup metadata (`backup_name`, `include_db`) in list item payload.
  - `schedule_restore(..., restore_db=...)` is derived from metadata; legacy fallback checks DB backup file presence.
- Read/unread UI-DB consistency:
  - `NewsTab._set_read_state(...)` added and shared by `open/unread/ext` flows.
  - DB update failure no longer mutates in-memory state/badge counters.
- Settings dialog worker lifecycle hardening:
  - Worker creation unified in `_create_worker(...)`.
  - `_shutdown_worker(...)` now handles wait timeout with parent detachment and deferred cleanup.
- Badge accuracy for exclude words:
  - `MainApp.update_all_tab_badges()` computes per-tab unread count with `exclude_words` when needed.
  - cache key switched to tab keyword to avoid collision.
- Packaging sync:
  - 
ews_scraper_pro.spec` removed forced `chardet` hidden import to align with requests optional dependency path.

### Added/Updated Tests
- Added: `tests/test_backup_restore_mode.py`
- Extended:
  - `tests/test_news_tab_ext_read_policy.py`
  - `tests/test_settings_roundtrip.py`
  - `tests/test_db_queries.py`
  - `tests/test_risk_fixes.py`

### Validation
- `python -m pytest -q` => `105 passed, 5 subtests passed`

---

## 2026-03-06 Addendum (Audit Adoption Follow-through)

### Implemented
- Backup retention policy split:
  - Added `trigger` metadata (`auto` / `manual`) to backup creation.
  - `core.backup.AutoBackup` now uses separate retention windows for automatic and manual backups.
- Backup UI clarity:
  - `BackupDialog.format_backup_timestamp(...)` supports microsecond timestamps.
  - Backup list now shows source label (`자동` / `수동`) together with restore scope metadata.
- Database maintenance synchronization:
  - Settings dialog cleanup actions now notify parent window via `on_database_maintenance_completed(...)`.
  - Main window refreshes open tabs, bookmark tab, badge cache, and tray tooltip after DB maintenance.
- Query semantics preservation:
  - Added `DatabaseManager.mark_query_as_read(...)` and wired `NewsTab.mark_all_read()` tab-wide path to preserve `exclude_words`.
  - Extended `DatabaseManager.get_top_publishers(..., exclude_words=...)`.
  - Stats analysis combo now stores raw tab query instead of collapsing to `db_keyword`.

### Added/Updated Tests
- Added:
  - `tests/test_settings_dialog_maintenance.py`
- Extended:
  - `tests/test_backup_restore_mode.py`
  - `tests/test_db_queries.py`
  - `tests/test_risk_fixes.py`

### Validation
- `python -m pytest -q` => `112 passed, 5 subtests passed`

### Packaging
- `news_scraper_pro.spec` reviewed again after this pass; no additional changes required.

---

## 2026-03-07 Addendum (Audit Plan Full Implementation)

### Implemented
- Worker/tab lifecycle hardening:
  - `close_tab()` and `rename_tab()` now clean up active workers before tab state mutation.
  - Tab title rendering unified via `_format_tab_title(...)` to keep icon + unread badge consistent.
- Restore/backup durability:
  - `apply_pending_restore_if_any(...)` now applies staged copy + rollback semantics.
  - Corrupt backup metadata entries are exposed with `is_corrupt` / `error` and handled in UI (`손상됨`, `삭제/무시`).
- DB safety updates:
  - `DatabaseManager.connection(timeout=...)` context manager added.
  - `mark_query_as_read(...)` moved to single-connection path (no nested acquisition).
  - `delete_old_news(...)` excludes `pubDate_ts <= 0`.
  - Tray unread tooltip now uses `DatabaseManager.get_total_unread_count()`.
- Secret storage / config recovery:
  - Added `client_secret_enc`, `client_secret_storage` schema fields.
  - Windows path uses DPAPI encrypted payload with plaintext migration on load.
  - Config load now supports `.backup` fallback recovery.

### Packaging / Spec Review
- `news_scraper_pro.spec` re-reviewed for this pass.
- No new hidden import/exclude changes required; DPAPI path relies on stdlib (`ctypes`, `base64`).

### Repo Hygiene
- `.gitignore` updated to ignore runtime recovery leftovers:
  - `.restore_stage_*/`
  - `*.db.corrupt_*`

### Validation
- `python -m pytest -q` => `128 passed, 5 subtests passed`

---

## 2026-03-09 Addendum (Type + Encoding Consistency)

### Implemented
- Added `pyrightconfig.json` (Windows / Python 3.14 / app+tests scope).
- Added `core/protocols.py` and `ui/protocols.py` to make lock/session/window-parent contracts explicit.
- Resolved repo-wide Pylance/Pyright issues without global ignores.
- Expanded UTF-8 smoke coverage from selected Python files to repository text assets.
- Refined `.gitignore` so runtime JSON/DB files stay ignored but tracked repo config such as `pyrightconfig.json` remains committable.

### Validation
- `pyright` => `0 errors, 0 warnings, 0 informations`
- `pytest -q` => `128 passed, 5 subtests passed`

---

## 2026-03-14 Addendum (Implementation Audit Completion)

### Query Scope
- `parse_tab_query(raw)` should now be read as the representative-keyword helper only.
- Actual tab membership, unread badges, analytics, duplicate tracking, and pagination scope use `query_key = build_fetch_key(parse_search_query(raw_tab_query))`.
- `news_keywords` now uses `PRIMARY KEY (link, query_key)`, so the same article link can belong to multiple tab scopes while `news.is_read`, `news.is_bookmarked`, `news.notes`, and delete state remain global per article.
- Legacy multi-keyword tabs may require one refresh after migration before the new `query_key` scope is fully populated.

### Pagination / Settings I/O
- Added top-level `pagination_totals` schema alongside `pagination_state`.
- Load-more enable/disable state is restored from `cursor + total`, not from DB-count fallback.
- Settings export/import format is now `1.1` and includes `search_history`, `pagination_state`, `pagination_totals`, and `window_geometry` in addition to prior payloads.
- Imported `start_minimized=true` is forced to `False` when system tray support is unavailable.

### Restore / Notification Behavior
- `restore_backup(...)` and `apply_pending_restore_if_any(...)` now share the same atomic restore helper (`preflight -> snapshot -> staged copy -> rollback`).
- `show_desktop_notification()` remains tray-first, but falls back to toast + sound when tray support is unavailable.

### Packaging / Repo Hygiene
- `news_scraper_pro.spec` was re-reviewed for this pass; no additional hidden import/exclude change was required.
- `.gitignore` was re-reviewed for this pass; existing rules already cover the generated/runtime artifacts involved here.

### Validation
- `pytest -q` => `136 passed, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`

---

## 2026-03-16 Addendum (Implementation Audit Follow-through)

### Implemented
- Global article state synchronization:
  - Single-item read/bookmark/note/delete actions now synchronize by `link` across all open news tabs and the bookmark tab.
  - Delete removes the cached item from every open tab immediately.
  - Bulk actions such as `mark all read` now reuse the same full-refresh path as DB maintenance completion.
- Alert / tab identity / export consistency:
  - `ApiWorker.finished` now includes `new_items`, computed from pre-existing links in the current `query_key` scope before upsert.
  - Alert keywords run only against newly added items and do not fire when `added_count == 0`.
  - Tab dedupe, rename conflict detection, settings import dedupe, and search-history dedupe now share canonical-query identity.
  - At the 2026-03-16 pass, CSV export used `filtered_data_cache` (visible-only); later passes superseded this with full-scope DB export and then the 2026-03-25 async chunked path.
- Backup / docs / packaging alignment:
  - Startup auto-backup remains settings-only, and the UI/docs now explicitly call out that DB restore points require a manual backup with DB included.
  - `news_scraper_pro.spec` was re-reviewed; no additional hidden import/exclude changes were required.
  - `.gitignore` was re-reviewed; no additional ignore rule was required.

### Added / Updated Tests
- Added `tests/test_audit_followthrough.py`
- Expanded:
  - `tests/test_worker_cancellation.py`
  - `tests/test_db_queries.py`
  - `tests/test_import_settings_dedupe.py`
  - `tests/test_news_tab_ext_read_policy.py`

### Validation
- `pytest -q` => `146 passed, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`

---

## 2026-03-18 Addendum (Execution Risk Full Pass)

### Implemented
- Settings portability / import-export:
  - settings export/import format is now `1.2`
  - API credentials remain excluded, while `settings.auto_start_enabled` is now included
  - import supports `1.1` and `1.2`, coerces unavailable `start_minimized` / `auto_start_enabled` safely, and reconciles the actual startup registry state through `StartupManager.enable_startup(...)` / `disable_startup()`
- Maintenance mode / fetch coordination:
  - the app now enters a global maintenance mode before settings-dialog cleanup tasks touch the DB
  - active fetch workers are cancelled with a bounded wait, and new refresh / tab-fetch / load-more entrypoints are blocked during maintenance
  - maintenance state is surfaced through status/toast messaging and UI lockout
- DB pagination / read-state semantics:
  - local tab browsing now uses DB-backed filtering + pagination via `count_news(...)` and `fetch_news(..., limit, offset, filter_txt=...)`
  - HTML `더 보기` appends the next DB page instead of revealing a preloaded in-memory slice
  - `filtered_data_cache` now represents the currently loaded slice only
  - CSV export and `현재 표시 결과만` read-all both re-query the current tab's full filtered scope from DB
  - `DatabaseManager.mark_query_as_read(...)` now uses a single SQL update path and preserves `filter_txt`, duplicate-hide, date range, bookmark scope, and `query_key`
- Backup / restore preflight:
  - `create_backup(include_db=True)` now fails when the DB payload is missing
  - `backup_info.json.include_db` is kept consistent with the actual payload
  - backup list entries now expose `is_restorable` / `restore_error`, and BackupDialog blocks non-restorable items before scheduling restore

### Packaging / Repo Hygiene
- `news_scraper_pro.spec` was re-reviewed on 2026-03-18; no additional hidden import / exclude / data change was required for this pass.
- `.gitignore` was re-reviewed on 2026-03-18; existing runtime/build ignore rules already cover the files generated by this pass.

### Added / Updated Tests
- Added:
  - `tests/test_dbworker_pagination.py`
  - `tests/test_maintenance_mode.py`
  - `tests/test_news_tab_mark_all_read_scope.py`
  - `tests/test_settings_import_export_portability.py`
- Expanded:
  - `tests/test_audit_followthrough.py`
  - `tests/test_backup_restore_mode.py`
  - `tests/test_db_queries.py`
  - `tests/test_risk_fixes.py`
  - `tests/test_settings_dialog_maintenance.py`
  - `tests/test_stability.py`

### Validation
- `python -m pytest -q` => `165 passed, 5 subtests passed`
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`
