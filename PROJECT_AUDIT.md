# Project Audit

## 1. Executive Summary

**프로젝트:** 뉴스 스크래퍼 Pro v32.7.3 — PyQt6 데스크톱 앱, 네이버 뉴스 API + 로컬 SQLite

**검증 상태 (2026-06-25 기준):**
- `python -m pytest -q` → **347 passed**, 7 warnings
- `python -m pyright` → **0 errors**

**전체 위험도: Medium**

코드베이스는 문서화된 계약(검색 canonical key, worker payload, 백업/클라우드 경로 정책)과 테스트 스위트가 잘 맞물려 있으며, 이전 감사에서 지적된 worker 정리·탭 닫기·fetch dedupe·stale callback 방어 등이 구현·회귀 테스트로 고정되어 있다. 다만 **QThread worker 정리 타임아웃**, **DB 연결 풀 고갈**, **비-Windows 자격증명 저장**은 실사용에서 기능 장애나 데이터 노출로 이어질 수 있는 잔여 리스크다.

| 영역 | 수준 | 요약 |
|------|------|------|
| 비동기/worker 생명주기 | Medium–High | cleanup 실패 시 탭 닫기·이름 변경·유지보수·새 fetch 차단 |
| DB 안정성 | Medium | 손상 시 자동 복구 있음; unreadable(잠금/접근 불가) 시 복구 생략 |
| 보안 | Medium (비-Windows) | API secret은 Windows DPAPI, 그 외 plain 저장 |
| 테스트 | Low–Medium | 회귀 스위트 풍부; 탭 닫기/이름 변경 등 UI 통합 테스트는 소스 검사 위주 |
| 문서 일치 | Low | README/CLAUDE.md와 구현 대체로 일치; 플랫폼 범위는 “Windows 우선”과 실제 구현이 일치 |

---

## 2. Project Understanding

### 2.1 목적

탭별 네이버 뉴스 검색, 읽음/북마크/메모/태그, 필터·자동화·백업·클라우드 ZIP 스냅샷 동기화를 로컬 SQLite 위에서 관리하는 데스크톱 앱이다.

### 2.2 아키텍처 (README.md, Claude.md, CodeGraph)

```text
news_scraper_pro.py
  └─ core.bootstrap.main()
       ├─ migrate_legacy_runtime_files()
       ├─ single-instance lock (QLockFile + QLocalServer)
       ├─ pending restore 적용
       └─ ui.main_window.MainApp(runtime_paths)
            ├─ load_config / save_config (ui/main_window_support/config.py)
            ├─ NewsTab × N (ui/news_tab.py)
            │    ├─ DBWorker — 탭 목록/필터 로드
            │    └─ IterativeJobWorker — 일괄 읽음 등
            ├─ fetch_news() — ApiWorker + QThread
            │    ├─ ValidationUtils.validate_api_credentials (guard)
            │    ├─ cooldown / dedupe
            │    ├─ WorkerRegistry (request_id, tab_keyword)
            │    └─ on_fetch_done / on_fetch_error (stale guard)
            ├─ cloud sync (IterativeJobWorker + maintenance mode)
            └─ backup / import-export
core.database.DatabaseManager (facade)
  ├─ db_queries_support/fetch.py — fetch_news, count_news_states
  ├─ db_mutations_support/news_upsert.py — upsert_news_detailed
  ├─ cloud_sync_support/ — ZIP snapshot I/O·병합
  └─ backup_support/ — 경로 containment, pending restore
```

### 2.3 주요 실행 흐름

**앱 시작**
1. `core.bootstrap.main()` — 전역 예외 훅, 레거시 런타임 마이그레이션, 단일 인스턴스 락
2. `apply_pending_restore_if_any()` — 재시작 시 예약 복원
3. `MainApp` 생성 → `load_config()` → 탭 복원·hydration 큐

**탭 새로고침**
1. `MainApp.fetch_news(keyword)` (`ui/main_window_fetch_support/worker_flow_support/start.py`)
2. 유지보수 모드·양수 키워드·API 자격증명·cooldown·dedupe·기존 worker cleanup 검사
3. `ApiWorker.run()` — API 호출 → 제외어/링크 정규화 → `upsert_news_detailed()`
4. `on_fetch_done()` — `_is_active_worker_request()` stale guard → pagination state → `NewsTab.load_data_from_db()`

**탭 DB 로드**
1. `NewsTab.load_data_from_db()` — request_id 증가, 이전 DBWorker 중단
2. `DBWorker.run()` — `open_read_connection` + `fetch_news` / `count_news_states`
3. `on_data_loaded()` — stale/cancelled request_id 무시 후 렌더링

**클라우드 동기화**
1. `_cloud_sync_block_reason()` — 폴더·경로 충돌·refresh 진행·중복 실행 검사
2. `begin_database_maintenance("cloud_sync")` — 활성 fetch worker 1.5초 내 정리 요구
3. ZIP 스냅샷 export/import, 손상 스냅샷 `.invalid/` 격리

### 2.4 CodeGraph blast radius 요약

| 심볼 | 호출자 규모 | 테스트 |
|------|------------|--------|
| `ApiWorker` | 5 callers | `test_worker_cancellation`, `test_followup_20260508` |
| `DBWorker` | 4 callers (탭 로딩) | `test_dbworker_pagination` |
| `cleanup_worker` | 5 callers | 소스/동작 일부 (`test_fetch_cooldown`); **직접 통합 테스트 부족** |
| `close_tab` / `rename_tab` | 각 1–2 callers | **소스 검사만** (`test_risk_fixes`) |
| `DatabaseManager` | 광범위 | `test_db_queries`, `test_cloud_sync` 등 |
| `load_config` / `save_config` | 14+ save callers | `test_settings_roundtrip`, `test_config_secret_storage` 등 간접 |

---

## 3. High-Risk Issues

### 3.1 Worker cleanup 타임아웃 시 UI 동작 차단

* **위치:** `ui/main_window_fetch_support/worker_flow_support/completion.py` — `cleanup_worker()`; `ui/_main_window_tabs.py` — `close_tab()`, `rename_tab()`; `ui/main_window_support/base_support/maintenance.py` — `begin_database_maintenance()`
* **문제:** `thread.wait(wait_ms)` 실패 시 registry에 worker가 남고 `retain_qthread_until_finished()`로 위임한다. 이 상태에서 탭 닫기·이름 변경·유지보수 진입·동일 탭 새 fetch가 거부되거나 스킵된다.
* **영향:** 사용자가 탭을 닫지 못하거나, “이전 새로고침이 아직 종료 중” 메시지 후 기능이 막힌다. 유지보수(클라우드 동기화, DB 정리)도 1.5초 내 정리 실패 시 시작 불가.
* **근거:**
  - `cleanup_worker()` L311–314: timeout 시 `return False`, registry 유지
  - `close_tab()` L286–292: cleanup 실패 시 `return`으로 탭 제거 중단
  - `test_fetch_cooldown.py::test_cleanup_worker_timeout_keeps_running_thread_registered`
  - `test_maintenance_mode.py::test_begin_database_maintenance_fails_when_worker_cleanup_times_out`
* **권장 수정 방향:** (1) timeout 후 강제 interrupt + registry orphan 정리 정책 명문화, (2) 사용자-facing “worker 강제 종료” 액션, (3) tab close 시 비동기 orphan 정리 후 UI는 먼저 제거하는 완화 경로 검토.
* **우선순위:** **High**

### 3.2 DB 연결 풀 고갈 시 일반 RuntimeError 전파

* **위치:** `core/database.py` — `get_connection()`; `core/db_mutations_support/news_upsert.py` — `upsert_news_detailed()`; `core/workers_support/db_worker.py` — `run()`
* **문제:** 풀+emergency cap 초과 시 `RuntimeError("Database connection pool exhausted")` 발생. `upsert_news_detailed()`는 `get_connection()`을 `try` 밖에서 호출하며 `sqlite3.Error`만 `DatabaseWriteError`로 변환한다.
* **영향:** 동시 DB 작업 폭주 시 ApiWorker는 `internal_error`로, DBWorker는 generic error 문자열로 실패한다. `DatabaseWriteError`/`DatabaseQueryError` 기반 UI 분기·복구 힌트를 쓰지 못한다.
* **근거:**
  - `database.py` L164–172: emergency cap 초과 시 `RuntimeError`
  - `news_upsert.py` L73: `get_connection()`이 try 밖; L263–265: `sqlite3.Error`만 처리
  - `test_stabilization_round1.py::TestDatabaseEmergencyCap`
  - ApiWorker L468–475: broad `except Exception` → `kind="internal_error"`
* **권장 수정 방향:** `get_connection()` 실패를 `_new_write_error`/`_new_query_error`로 통일; UI에 “DB 과부하, 잠시 후 재시도” 메시지 추가.
* **우선순위:** **Medium**

### 3.3 DB 무결성 검사 unreadable 시 자동 복구 생략

* **위치:** `core/database.py` — `DatabaseManager.__init__()`; `core/db_schema_support/connection.py` — `_check_integrity()`
* **문제:** `integrity_result.state == "unreadable"`이면 자동 `_recover_database()`를 호출하지 않는다.
* **영향:** 다른 프로세스가 DB를 잠근 채 시작하거나 파일 접근이 일시 불가하면, 손상이 아닌데도 복구 없이 `init_db()`로 진행해 이후 쿼리가 연쇄 실패할 수 있다.
* **근거:**
  - `database.py` L130–142
  - `test_db_integrity_recovery.py::test_startup_skips_recovery_when_unreadable`
* **권장 수정 방향:** unreadable 시 제한적 재시도(backoff) 후 corrupt와 분기; UI에 “DB 사용 중/잠김” 안내 및 읽기 전용 모드(추정) 검토.
* **우선순위:** **Medium**

### 3.4 비-Windows 환경 API Client Secret 평문 저장

* **위치:** `core/config_store_support/secrets.py` — `_dpapi_encrypt_text()`, `encode_client_secret_for_storage()`
* **문제:** DPAPI는 `sys.platform == "win32"`에서만 동작한다. macOS/Linux는 `client_secret_storage="plain"`으로 config JSON에 저장된다.
* **영향:** README는 Windows 우선이지만 macOS/Linux 데이터 경로도 문서화되어 있어, 해당 환경 사용자 config 파일 유출 시 API secret 노출.
* **근거:**
  - `secrets.py` L25–26, L17–21
  - `test_config_secret_storage.py` (Windows DPAPI 경로)
  - README L9: “Windows 우선”
* **권장 수정 방향:** macOS Keychain / Linux secret service 연동, 또는 최소한 plain 저장 시 경고 토스트·설정 UI 표시.
* **우선순위:** **Medium** (비-Windows 사용 시 **High**)

### 3.5 `_is_active_worker_request`의 request_id=None 허용

* **위치:** `ui/main_window_fetch_support/worker_flow_support/state.py` — `_is_active_worker_request()`
* **문제:** `request_id is None`이면 무조건 `True`를 반환해 stale guard가 비활성화된다.
* **영향:** 현재 `fetch_news()`는 항상 `request_id`를 전달하지만, 향후 호출 경로 추가 시 완료된 worker 콜백이 pagination/badge를 오염시킬 수 있다.
* **근거:** `state.py` L36–38; `on_fetch_done()` L37–39
* **권장 수정 방향:** `request_id is None`을 deprecated로 로그 경고 후 거부하거나, 레거시 경로 제거.
* **우선순위:** **Low**

### 3.6 레거시 `self.workers` dict와 `WorkerRegistry` 이중 추적

* **위치:** `ui/main_window_fetch_support/worker_flow_support/start.py` L182; `completion.py` L317; `ui/_main_window_tray.py` L314
* **문제:** worker 상태가 `WorkerRegistry`와 `self.workers`에 중복 보관된다.
* **영향:** 한쪽만 갱신되는 regression 시 orphan 참조 가능. 현재 start/cleanup/tray clear는 동기화되어 있으나 유지보수 부담.
* **근거:** CodeGraph caller 분석; grep `self.workers` 5곳
* **권장 수정 방향:** `WorkerRegistry` 단일 소스로 통합.
* **우선순위:** **Low**

---

## 4. Potential Functional Gaps

아래 항목 중 **(추정)** 표시는 코드에서 명시적 미구현을 확인하지 못한 항목이다.

### 4.1 확인된 보완 여지

| 항목 | 설명 |
|------|------|
| 탭 닫기/이름 변경 통합 테스트 | `test_risk_fixes`는 `inspect.getsource` 수준. 실제 QThread timeout·rename 중 fetch 완료 시나리오 부재 |
| `cleanup_worker` 직접 테스트 | cooldown 테스트에 일부 있으나, tray shutdown·sequential refresh 교차 시나리오 제한적 |
| DB pool exhaustion UI 회복 | 테스트는 DB 레이어까지만; MainApp에서 연쇄 탭 로드 시 사용자 경험 미검증 |
| 네이버 API 1,000건 상한 | `fetch_news()` L116–124에서 QMessageBox 후 중단 — 기능 한계로 문서화됨, 우회 없음 |

### 4.2 (추정) 추가 가능성이 높은 기능

| 항목 | 근거 |
|------|------|
| API 키 없이 캐시-only 모드 | 자격증명 guard가 fetch 전면 차단; 오프라인 열람 니즈 있을 수 있음 |
| macOS/Linux 트레이·자동 시작 완성도 | `core/startup.py` winreg 의존; README “Windows 우선” |
| 프록시/엔터프라이즈 네트워크 설정 | HTTP client는 timeout·redirect 차단만; 시스템 프록시 명시 설정 UI 없음 |
| Worker 강제 종료/진단 화면 | cleanup timeout 시 사용자 복구 수단 제한적 (3.1과 연계) |
| 클라우드 동기화 충돌 시 사용자 머지 UI | timestamp 최신값 병합은 자동; 충돌 preview는 import 시만 |
| 대용량 아카이브 export 진행률 | export worker 존재; 초대형 DB 시 취소·재개 UX (추정) |

### 4.3 문서 vs 구현

| 항목 | 상태 |
|------|------|
| 버전 32.7.3 | `core/constants.py` `VERSION`과 README 일치 |
| export schema 1.3 | `ui/main_window_io_support/settings_dialogs.py`, `test_settings_import_export_portability.py` 일치 |
| FTS hard prefilter 미사용 | README·CLAUDE.md 명시; 구현과 일치 (의도적 성능/정확도 트레이드오프) |
| 탭 닫기 시 worker cleanup 실패 보류 | README L120–121, `close_tab()` 구현 일치 |
| Python 3.14 | README 명시; 현재 환경에서 pytest 통과 확인 |

---

## 5. Recommended Fix Plan

### 1단계 — 즉시 수정 (Critical/High)

1. **Worker cleanup 실패 UX 및 복구 경로** (3.1)
   - timeout 빈도 로깅·metrics
   - 설정/도움말에 “새로고침 완료 대기” 안내
   - (가능하면) orphan worker 강제 정리 API

2. **탭 닫기/이름 변경 behavioral 테스트 추가**
   - mock QThread로 timeout/true/false 분기 검증
   - rename 후 `_tab_fetch_state`·`_fetch_cursor_by_key` 마이그레이션 검증

### 2단계 — 안정성 개선 (Medium)

3. **DB pool exhaustion 에러 타입 통일** (3.2)
   - `get_connection()` 실패를 query/write error로 래핑
   - DBWorker/ApiWorker/NewsTab에 사용자 메시지 매핑

4. **DB unreadable 시작 경로** (3.3)
   - 짧은 재시도 + 명확한 시작 차단/안내 dialog

5. **비-Windows secret 저장** (3.4)
   - plain 저장 시 경고 + 향후 OS keyring 추상화

6. **`request_id=None` stale guard 제거** (3.5)

### 3단계 — 구조 개선 (Low)

7. **`self.workers` → `WorkerRegistry` 통합** (3.6)
8. **예외 처리 정밀화** — UI layer의 무분별한 `except Exception: pass`를 기능별 로깅/토스트로 분류 (예: `ui/_main_window_tabs.py` L135–136)
9. **CodeGraph 미커버 경로 테스트 보강** — `core/db_queries_support/fetch.py` UI 연계, `apply_cloud_sync_settings()` 타이머 동작

---

## 6. Test Recommendations

### 6.1 우선 추가할 테스트

| 테스트 | 목적 |
|--------|------|
| `test_tab_lifecycle_worker_cleanup.py` | `close_tab`/`rename_tab`이 cleanup False 시 상태 불변, True 시 registry·`_tab_fetch_state` 정리 검증 |
| `test_fetch_done_after_rename_stale.py` | rename 후 old keyword·old request_id 콜백이 pagination/UI를 변경하지 않음 |
| `test_db_pool_exhaustion_ui.py` | pool exhausted 시 ApiWorker `internal_error`, DBWorker `error` signal, NewsTab 상태 복구 |
| `test_startup_db_unreadable.py` | unreadable DB 파일 잠금 시나리오(실제 subprocess lock)에서 시작 동작 |
| `test_cloud_sync_blocks_during_refresh.py` | `_refresh_in_progress`/`_sequential_refresh_active` 시 `_cloud_sync_block_reason` 메시지 |

### 6.2 기존 스위트 보강

| 파일 | 보강 내용 |
|------|----------|
| `test_fetch_cooldown.py` | sequential refresh + tab close 동시 시나리오 |
| `test_maintenance_mode.py` | cloud_sync maintenance와 탭 DBWorker 동시 취소 |
| `test_config_secret_storage.py` | non-Windows plain 저장 경고 정책 (플랫폼 mock) |
| `test_shutdown_cleanup.py` | `cleanup_worker` timeout 후 앱 종료 시 orphan thread 누수 없음 |

### 6.3 회귀 유지 (삭제·약화 금지)

- `test_risk_fixes.py`, `test_worker_cancellation.py`, `test_db_integrity_recovery.py`
- `test_settings_import_export_portability.py`, `test_backup_collision_and_restore.py`
- `test_single_instance_guard.py`, `test_qthread_lifetime.py`

### 6.4 수동/E2E 권장 시나리오

1. 느린 네트워크에서 새로고침 중 탭 닫기·이름 변경 반복
2. 클라우드 폴더를 OneDrive/Google Drive 경로로 설정 시 동기화 지연·잠금
3. `%LOCALAPPDATA%\NaverNewsScraperPro` 백업 후 pending restore 재시작
4. API 429 응답 후 cooldown·toast·재시도 간격 확인

---

*본 문서는 코드 수정 없이 정적 분석·CodeGraph MCP·pytest/pyright 실행 결과를 바탕으로 작성되었다.*