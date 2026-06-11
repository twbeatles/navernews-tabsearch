# Project Audit

## 1. Executive Summary

이 프로젝트는 PyQt6 기반 네이버 뉴스 검색 데스크톱 앱이며, README.md/claude.md의 현재 설명과 실제 구조는 전반적으로 잘 맞습니다. CodeGraph 기준 250개 Python 파일, 4,524개 심볼, 10,077개 엣지로 인덱싱되어 있으며, 핵심 실행 흐름은 `news_scraper_pro.py` -> `core.bootstrap.main()` -> `ui.main_window.MainApp` -> `core.database.DatabaseManager` / worker 계층입니다.

감사 당시 전체 위험도는 **Medium-High**였습니다. 이후 2026-06-12 구현으로 아래 확인된 문제는 모두 수정되었고, 남은 위험도는 회귀 테스트와 운영 환경 검증 전제하에 **Low-Medium**입니다.

- 단일 탭 fetch 경로가 API 자격증명 검증을 우회합니다.
- 탭 닫기/이름 변경이 worker 정리 실패를 무시해 오래 걸리는 API worker와 새 상태가 겹칠 수 있습니다.
- 백업 삭제/복원 예약 public API가 backup name을 단일 경로 세그먼트로 검증하지 않습니다.
- core cloud sync API의 빈 `sync_dir` 검증이 `abspath("")` 때문에 무력화될 수 있습니다.
- 메모 입력/CSV import 메모 값에 크기 제한이 없어 DB, 렌더링, cloud snapshot 크기 문제로 이어질 수 있습니다.

감사 당시 검증 결과:

- `python -m pytest -q`: 339 passed, 7 deprecation warnings, 5 subtests passed
- `python -m pyright`: 0 errors, 0 warnings, 0 informations

구현 상태:

- Issue 1 수정 완료: `fetch_news()`에 API 자격증명 guard를 중앙화하고 단일 탭/순차 fetch 회귀 테스트를 추가했습니다.
- Issue 2 수정 완료: 탭 닫기/이름 변경에서 worker cleanup 실패 시 상태 변경을 중단하고 사용자 알림을 표시합니다.
- Issue 3 수정 완료: backup name root-containment helper를 추가하고 삭제/복원 예약/즉시 복원/pending restore에 적용했습니다.
- Issue 4 수정 완료: cloud sync path resolver를 추가하고 빈 `sync_dir`을 core API에서 거부합니다.
- Issue 5 수정 완료: 메모를 10,000자로 정규화하고 UI 저장/아카이브 편집/CSV import/DB 저장 경로에 적용했습니다.
- Issue 6 수정 완료: export dialog 기본 파일명에 OS-safe filename component를 사용합니다.

구현 후 추가한 주요 회귀 테스트:

- `tests/test_fetch_cooldown.py`: API 자격증명 누락 시 worker 미생성, 순차 fetch 진행 보장
- `tests/test_risk_fixes.py`: 탭 worker cleanup 실패 방어 계약
- `tests/test_backup_collision_and_restore.py`, `tests/test_pending_restore_strict.py`: backup traversal 거부
- `tests/test_cloud_sync.py`: 빈 cloud sync folder 거부
- `tests/test_db_queries.py`, `tests/test_followup_20260508.py`: 메모 길이 제한과 CSV import truncate
- `tests/test_audit_followthrough.py`: export 기본 파일명 정규화

구현 후 검증 결과:

- `python -m pytest -q`: 347 passed, 7 warnings, 5 subtests passed
- `python -m pyright`: 0 errors, 0 warnings, 0 informations
- `python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q`: 4 passed

## 2. Project Understanding

README.md와 `claude.md`가 정의한 프로젝트 목적은 네이버 뉴스 검색 API를 사용하는 PyQt6 데스크톱 앱입니다. 앱은 탭별 검색어, canonical query/fetch key, 읽음/북마크/메모/태그, 출처 필터, 자동화 규칙, 백업/복원, cloud snapshot sync를 로컬 SQLite DB 위에서 관리합니다.

문서상 주요 계약:

- 실행 진입점: `news_scraper_pro.py`
- 앱 부팅: `core.bootstrap.main()`
- 메인 UI: `ui.main_window.MainApp`
- DB facade: `core.database.DatabaseManager`
- root compatibility wrapper는 유지해야 하며 새 코드는 `core.*`, `ui.*`를 우선합니다.
- 검색 의미는 `parse_search_query(...)` + `build_fetch_key(...)`로 만든 canonical query/fetch key가 기준입니다.
- `ApiWorker.finished` payload, `DatabaseManager.upsert_news(...)`, `count_news(...)` 등의 legacy 공개 계약은 유지 대상입니다.
- cloud sync는 live DB를 직접 공유하지 않고 ZIP snapshot만 교환해야 합니다.

CodeGraph로 확인한 주요 실행 흐름:

- `news_scraper_pro.py:136`에서 `main()`을 호출하고, root 공개 API를 compatibility re-export합니다.
- `core.bootstrap.main()`은 legacy runtime migration, single-instance lock/server, pending restore 적용, QApplication 생성, `MainApp` 생성 및 표시를 담당합니다.
- `MainApp.__init__`은 `DatabaseManager`, `WorkerRegistry`, 자동 백업/클라우드 타이머, FTS backfill, UI, tray, 설정 로드를 초기화합니다.
- 네트워크 fetch는 `ui/main_window_fetch_support/worker_flow_support/start.py::fetch_news()`가 `ApiWorker`를 만들고 QThread에 연결합니다.
- `ApiWorker.run()`은 Naver API 요청, redirect 차단, 429 cooldown 처리, DB upsert, `new_items`/`new_count` payload 생성을 담당합니다.
- DB 탭 로딩은 `DBWorker.run()` -> `count_news_states()` -> `fetch_news()` 경로로 읽기 전용 연결을 사용합니다.
- 설정 import/export는 `ui/main_window_io_support/settings_dialogs.py`와 `import_stage_support`에서 정규화, staging, rollback을 수행합니다.
- cloud sync는 `ui/main_window_io_support/cloud.py`에서 유지보수 모드로 worker를 실행하고, `core/cloud_sync_support`에서 snapshot 선택/추출/병합을 담당합니다.

README/CLAUDE와 실제 구현의 큰 방향은 대체로 일치합니다. 특히 FTS rowid hard prefilter는 `fetch.py`에 조건부 코드가 남아 있지만, `core/db_queries_support/filters.py::_fts_match_expression()`이 항상 빈 문자열을 반환하므로 현재 사용자-visible 필터는 문서 설명대로 LIKE token-AND 기반입니다.

## 3. High-Risk Issues

### Issue 1. 단일 탭 fetch 경로가 API 자격증명 검증을 우회함

위치: `ui/main_window_fetch_support/worker_flow_support/start.py::fetch_news`, `ui/main_window_fetch_support/refresh_flow.py::_refresh_block_reason`, `ui/_main_window_tabs.py::add_tab_dialog`, `ui/_main_window_tabs.py::rename_tab`

문제:
`refresh_all()` / `refresh_selected_tabs()` 계열은 `_refresh_block_reason()`에서 `ValidationUtils.validate_api_credentials()`를 호출하지만, 실제 단일 탭 fetch 진입점인 `fetch_news()` 내부에는 API 키 검증이 없습니다. 새 탭 추가, 탭 이름 변경 후 fetch, 더 불러오기 버튼은 `fetch_news()`를 직접 호출합니다.

영향:
API 키가 비어 있거나 너무 짧은 상태에서도 단일 탭 요청이 `ApiWorker`까지 내려가 빈/무효 헤더로 네이버 API 요청을 보낼 수 있습니다. 기능적으로는 첫 사용/설정 누락 상태에서 불필요한 API 오류 dialog가 발생하고, 새 탭/더 불러오기/전체 새로고침 간 UX와 실패 의미가 달라집니다.

근거:
`_refresh_block_reason()`은 `valid, msg = self._validate_api_credentials()` 후 실패 시 block message를 반환합니다. 반면 `fetch_news()`는 maintenance, query, cooldown, dedupe만 검사하고 곧바로 `ApiWorker(self.client_id, self.client_secret, ...)`를 생성합니다. `add_tab_dialog()`는 `self.add_news_tab(keyword)` 후 `self.fetch_news(keyword)`를 직접 호출하고, `add_news_tab()`은 더 불러오기 버튼에 `self.fetch_news(tab_ref.keyword, is_more=True)`를 연결합니다.

권장 수정 방향:
검증 책임을 caller가 아니라 `fetch_news()` 초입에 중앙화합니다. `is_more`, rename 후 fetch, sequential fetch 모두 같은 `_validate_api_credentials()` 정책을 지나게 하고, 실패 시 worker 생성 전에 UI 상태를 원복해야 합니다. 테스트는 API 키 누락 상태에서 새 탭 추가/더 불러오기/rename fetch가 worker를 만들지 않는지 확인해야 합니다.

우선순위: High

### Issue 2. 탭 닫기/이름 변경이 worker 정리 실패를 무시함

위치: `ui/_main_window_tabs.py::close_tab`, `ui/_main_window_tabs.py::rename_tab`, `ui/main_window_fetch_support/worker_flow_support/completion.py::cleanup_worker`

문제:
`cleanup_worker()`는 worker/thread 정리가 timeout되면 `False`를 반환하고 registry에 handle을 유지합니다. `fetch_news()`는 이 반환값을 확인해 새 요청을 건너뜁니다. 그러나 `close_tab()`과 `rename_tab()`은 `cleanup_worker()` 결과를 확인하지 않고 탭 삭제/이름 변경/새 fetch를 계속 진행합니다.

영향:
긴 API 요청이나 DB upsert 중인 worker가 종료되지 않은 상태에서 탭이 삭제되거나 다른 query로 변경될 수 있습니다. signals는 disconnect되더라도 worker는 기존 keyword/query_key로 DB 저장을 계속할 수 있고, rename 경로는 곧바로 새 keyword fetch를 시작할 수 있어 중복 네트워크 요청, 예상 밖 DB membership 저장, 사용자-visible 상태 불일치가 생길 수 있습니다.

근거:
`cleanup_worker()`는 `thread.wait(...)` 실패 시 `retain_qthread_until_finished(thread, worker)` 후 `return False`를 수행합니다. `fetch_news()`는 이전 worker 정리 실패 시 버튼 상태를 되돌리고 요청을 skip합니다. 반면 `close_tab()`은 active request cleanup 호출 뒤 `widget.cleanup()`, `removeTab()`, state prune을 계속 진행하고, `rename_tab()`은 cleanup 호출 뒤 `w.keyword = new_keyword`, `w.load_data_from_db()`, `self.fetch_news(new_keyword)`까지 진행합니다.

권장 수정 방향:
`close_tab()`과 `rename_tab()`에서도 `cleanup_worker()` 반환값을 검사해 실패 시 작업을 중단하거나 사용자에게 "이전 새로고침 종료 중" 메시지를 표시해야 합니다. rename은 cleanup 성공 후에만 keyword/state/policy를 변경해야 하며, close는 timeout 시 탭 삭제를 보류하는 편이 안전합니다.

우선순위: High

### Issue 3. 백업 삭제/복원 예약 API가 backup name 경로 세그먼트를 검증하지 않음

위치: `core/backup_support/auto_backup_support/restore_delete.py::schedule_restore`, `core/backup_support/auto_backup_support/restore_delete.py::delete_backup`, `core/backup_support/restore.py::apply_pending_restore_if_any`

문제:
`schedule_restore()`와 `delete_backup()`은 `backup_name`을 `strip()`하거나 그대로 사용한 뒤 `os.path.join(self.backup_dir, backup_name)`을 수행합니다. `apply_pending_restore_if_any()`도 pending JSON의 `backup_dir`와 `backup_name`을 조합해 복원 대상을 찾습니다. `backup_name`이 단일 디렉터리 이름인지, 최종 resolved path가 backup root 아래인지 확인하는 검증이 없습니다.

영향:
정상 UI 목록은 `os.listdir(self.backup_dir)`에서 온 이름을 사용하므로 일반 클릭 경로는 비교적 안전합니다. 하지만 public API 직접 호출, 변조된 `pending_restore.json`, 테스트/자동화 호출에서 `..` 또는 절대/상대 path segment가 섞이면 backup root 밖의 디렉터리를 복원하거나 삭제 대상으로 삼을 수 있습니다. 특히 `delete_backup()`은 `_rmtree_force(backup_path)`로 재귀 삭제를 수행합니다.

근거:
`schedule_restore()`는 `backup_path = os.path.join(self.backup_dir, str(backup_name or ""))` 후 `os.path.isdir(backup_path)`만 확인합니다. `delete_backup()`도 `backup_path = os.path.join(self.backup_dir, backup_name)` 후 존재하면 `_rmtree_force(backup_path)`를 호출합니다. `apply_pending_restore_if_any()`는 payload의 `backup_dir`를 우선 candidate로 추가하고 `os.path.join(str(backup_dir), backup_name)` 결과가 directory인지 확인합니다.

권장 수정 방향:
공용 helper를 추가해 `backup_name == os.path.basename(backup_name)`, path separator/drive/absolute path 금지, resolved path가 allowed backup root 아래인지 검증해야 합니다. pending restore에서는 `backup_dir`도 runtime backup dir 또는 명시적으로 허용된 이전 backup dir인지 확인하고, 실패 시 pending file을 유지하되 적용은 막아야 합니다.

우선순위: High

### Issue 4. core cloud sync API의 빈 `sync_dir` 검증이 무력화됨

위치: `core/cloud_sync_support/snapshot_io.py::create_cloud_snapshot`, `core/cloud_sync_support/snapshot_io.py::list_cloud_snapshots`, `core/cloud_sync_support/import_flow.py::run_cloud_sync_cycle`

문제:
`create_cloud_snapshot()`은 `target_dir = os.path.abspath(... str(sync_dir or ""))`를 먼저 수행한 뒤 `if not target_dir:`로 빈 경로를 검사합니다. Python에서 `os.path.abspath("")`는 현재 작업 디렉터리를 반환하므로, 이 검사는 빈 `sync_dir`을 잡지 못합니다.

영향:
UI의 `_cloud_sync_block_reason()`은 빈 folder를 먼저 차단하므로 일반 UI 경로에서는 방어됩니다. 그러나 core API를 테스트, 스크립트, 향후 자동화, 혹은 UI 우회 경로에서 직접 호출하면 빈 sync dir이 현재 작업 디렉터리로 해석되어 snapshot zip 생성/조회/cleanup이 의도하지 않은 위치에서 수행될 수 있습니다.

근거:
`create_cloud_snapshot()`은 `target_dir = os.path.abspath(os.path.expanduser(os.path.expandvars(str(sync_dir or ""))))` 후 `os.makedirs(target_dir, exist_ok=True)`를 호출합니다. `run_cloud_sync_cycle()`은 `sync_dir`을 별도 검증하지 않고 `select_cloud_snapshots_for_import()`와 `create_cloud_snapshot()`으로 전달합니다.

권장 수정 방향:
경로 expand/abspath 전에 raw `sync_dir`의 stripped 값이 비어 있는지 검사해야 합니다. core 계층에 `resolve_cloud_sync_dir(sync_dir, require_existing=False)` 같은 단일 정책 함수를 두고 UI와 core가 같은 검증을 쓰도록 정리하는 것이 좋습니다.

우선순위: Medium

### Issue 5. 메모 입력과 CSV import 메모 값에 크기 제한이 없음

위치: `ui/dialogs_support/basic.py::NoteDialog.get_note`, `ui/news_tab_support/actions_support/article_state.py::_save_note_state`, `core/db_mutations_support/state_tags_support/article_state.py::update_status`, `ui/main_window_io_support/exports.py::import_bookmarks_notes_from_csv`

문제:
태그는 `normalize_tags()`에서 길이와 개수를 제한하지만, 메모는 UI dialog, CSV import, DB update 경로에서 크기 제한 없이 문자열로 저장됩니다.

영향:
사용자가 매우 큰 메모를 입력하거나 CSV로 가져오면 SQLite DB가 급격히 커지고, 탭 렌더 캐시/HTML 렌더링, CSV/Markdown export, cloud snapshot DB 크기 제한에 영향을 줄 수 있습니다. cloud snapshot은 DB 크기 제한을 검사하므로, 큰 메모가 누적되면 동기화 실패로 이어질 수 있습니다.

근거:
`NoteDialog.get_note()`는 `self.text_edit.toPlainText().strip()`을 그대로 반환합니다. `_save_note_state()`는 `new_note = str(note or "")`를 만든 뒤 `db.save_note()`로 전달합니다. `update_status()`는 field가 `notes`이면 `normalized_value = "" if value is None else str(value)`만 수행하고 UPDATE합니다. CSV import도 `note_value = str(...)` 후 `db.save_note(link, note_value)`를 호출합니다.

권장 수정 방향:
메모 최대 길이를 명시적으로 정하고 UI 입력, CSV import, DB 저장 경로에서 같은 상한을 적용해야 합니다. 잘리는 경우 사용자 경고 또는 import warning을 남기고, cloud sync/export 문서에도 제한을 반영합니다.

우선순위: Medium

### Issue 6. export 기본 파일명이 raw keyword를 그대로 사용함

위치: `ui/main_window_io_support/data_io.py::export_data`, `core/validation.py::ValidationUtils.sanitize_keyword`

문제:
탭 keyword는 `sanitize_keyword()`에서 trim과 100자 제한만 적용됩니다. `export_data()`는 이 keyword를 그대로 `default_name = f"{keyword}_뉴스_...csv"`에 넣습니다.

영향:
Windows 파일명 금지 문자(`\\ / : * ? " < > |`)나 path separator가 포함된 검색어를 탭 이름으로 사용할 수 있고, 이 값이 save dialog 기본 파일명에 들어가면 저장 dialog가 이상한 기본 경로를 표시하거나 사용자가 그대로 저장할 때 실패할 수 있습니다. 검색어 자체는 자유롭게 허용하더라도 파일명에는 별도 sanitize가 필요합니다.

근거:
`ValidationUtils.sanitize_keyword()`는 `keyword.strip()[:100]`만 수행합니다. `export_data()`는 현재 탭의 `keyword`를 그대로 default filename prefix로 사용합니다.

권장 수정 방향:
검색어 정규화와 파일명 정규화를 분리합니다. `safe_filename_component(keyword, max_len=...)`를 만들어 export, backup/export artifact 이름에만 적용하고, 원래 검색어는 파일 내부 metadata나 dialog text에 유지합니다.

우선순위: Medium

## 4. Potential Functional Gaps

- 추정: `fetch_news()`에 API credential guard가 중앙화되지 않아 앞으로 새 단일 탭 fetch entrypoint가 추가될 때 같은 누락이 반복될 가능성이 높습니다.
- 추정: backup name 검증 helper가 없어서 delete, restore schedule, pending restore, corrupt backup cleanup 같은 destructive 경로가 서로 다른 수준의 path 신뢰를 가질 수 있습니다.
- 추정: cloud sync 경로 검증이 UI와 core에 분산되어 있어 headless helper나 future CLI가 추가되면 UI 방어를 우회할 수 있습니다.
- 추정: 메모 크기 정책이 없어서 cloud snapshot 크기 제한, 렌더링 성능, CSV import 안정성 사이의 계약이 불명확합니다.
- 추정: FTS rowid prefilter dead branch는 현재 기능상 문제는 아니지만, 향후 `_fts_match_expression()`을 다시 활성화할 때 README/claude.md의 false-negative 계약을 쉽게 깨뜨릴 수 있습니다.
- 추정: API credential validation은 최소 길이만 검사합니다. 더 엄격한 형식 검증이 필요한지는 Naver API key format 정책을 확인한 뒤 결정해야 합니다.

## 5. Recommended Fix Plan

### 1단계: 즉시 수정해야 할 문제

1. `fetch_news()` 초입에 API credential validation을 추가하고, 새 탭/rename/더 불러오기 경로가 worker를 만들지 않는 테스트를 추가합니다.
2. `close_tab()`과 `rename_tab()`에서 `cleanup_worker()` 반환값을 확인하고, 실패 시 상태 변경/삭제/새 fetch를 중단합니다.
3. backup name path validation helper를 만들고 `schedule_restore()`, `delete_backup()`, `apply_pending_restore_if_any()`에 적용합니다.

### 2단계: 안정성 개선

1. cloud sync core 계층에서 raw `sync_dir` 빈 값 검사를 먼저 수행하고, UI/core 공용 path resolver를 둡니다.
2. 메모 최대 길이를 정의하고 NoteDialog, CSV import, DB 저장 경로에 동일하게 적용합니다.
3. export 기본 파일명용 safe filename sanitizer를 추가합니다.

### 3단계: 구조 개선

1. fetch 실행 전 guard를 `can_start_fetch(keyword, mode)` 같은 단일 정책으로 분리해 refresh_all, selected refresh, single tab fetch, load more가 같은 규칙을 쓰게 합니다.
2. destructive filesystem 작업은 `resolve_child_dir(root, name)` 형태의 공용 helper를 통해 root containment를 강제합니다.
3. FTS acceleration 관련 dead branch는 명시적 feature flag나 테스트 이름으로 계약을 고정해 향후 회귀를 줄입니다.

## 6. Test Recommendations

- API credential guard:
  - API 키가 빈 상태에서 `fetch_news("AI")`가 `ApiWorker`를 생성하지 않는 테스트
  - 새 탭 추가 후 자동 fetch가 credential 누락 시 차단되는 테스트
  - `is_more=True` load-more 버튼 경로도 credential 누락 시 차단되는 테스트

- Worker cleanup race:
  - `cleanup_worker()`가 `False`를 반환할 때 `rename_tab()`이 keyword/state/config/fetch를 변경하지 않는 테스트
  - `cleanup_worker()`가 `False`를 반환할 때 `close_tab()`이 탭 제거와 state prune을 보류하는 테스트
  - timeout된 old worker가 나중에 완료되어도 renamed/new tab UI에 영향을 주지 않는 회귀 테스트

- Backup path safety:
  - `delete_backup("../outside")` 또는 separator 포함 name이 거부되는 테스트
  - `schedule_restore("../outside")`가 pending file을 만들지 않는 테스트
  - 변조된 `pending_restore.json`의 `backup_dir`/`backup_name` 조합이 runtime backup root 밖이면 적용되지 않는 테스트

- Cloud sync path safety:
  - `create_cloud_snapshot(sync_dir="")`와 `run_cloud_sync_cycle(sync_dir="")`가 명시적 `CloudSyncError`를 발생시키는 테스트
  - relative path 허용 여부를 정책화하고 해당 동작을 고정하는 테스트

- Memo limits:
  - NoteDialog 저장 경로에서 max length 초과 메모 처리 테스트
  - CSV import에서 긴 메모가 truncate/reject/warn 중 정해진 정책대로 처리되는 테스트
  - cloud snapshot DB size limit에 도달하기 전 사용자-visible warning을 줄 수 있는 테스트

- Export filename:
  - `keyword='AI:경제/증권?'` 같은 탭에서 save dialog 기본 파일명이 Windows-safe component로 바뀌는 테스트

- Existing validation 유지:
  - `python -m pytest -q`
  - `python -m pyright`
