# 프로젝트 구조 분석 및 기능 확장 가이드

작성일: 2026-03-16 (최근 갱신: 2026-04-16)

## 분석 범위

이 문서는 아래 자료를 함께 참고해 정리했다.

- `README.md`
- `claude.md`
- `gemini.md`
- `update_history.md`
- `news_scraper_pro.py`
- `core/*.py`
- `ui/*.py`
- `tests/*.py`

문서 기준 설계 의도와 실제 코드 구조를 함께 대조했고, "앞으로 기능을 어디에 어떻게 붙이면 안전한가"에 초점을 맞췄다.

## 0. 2026-04-18 구현 수정 반영 / 문서·spec·gitignore 재검증

이번 재검증에서는 2026-04-18 감사 후속 수정 배치와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- `ui.settings_dialog.SettingsDialog`는 유지보수 작업 완료 결과를 즉시 부모로 흘리지 않고, `end_database_maintenance()` 이후에만 flush하도록 바뀌어 열린 탭 reload, 배지 refresh, tray tooltip sync가 유지보수 가드에 막히지 않는다.
- 순차 새로고침은 수동 새로고침과 동일한 성공 후처리 경로를 공유하게 되어, 각 탭 완료 시점마다 데스크톱 알림, 트레이 알림, 알림 키워드 검사가 다시 실행된다.
- fetch 성공 후 "새 기사" 의미는 `new_items` / `new_count`로 통일되었고, 제목 중복이더라도 새 링크인 기사는 알림과 요약 집계에 계속 포함된다.
- `core.workers.ApiWorker`는 HTTP `429` 응답에서 `Retry-After`의 delta-seconds / HTTP-date 형식을 모두 해석하고, 재시도 대기와 최종 cooldown 메타 계산에 같은 값을 사용한다.
- `news_scraper_pro.spec`는 2026-04-18 기준 다시 재검토되었고, 이번 패스의 유지보수 완료 sync 순서 고정, 순차 새로고침 즉시 알림, `new_count` 의미 통일, `Retry-After` 지원, 남은 pyright 정리는 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않았다.
- `.gitignore`는 `git status --ignored --short` 기준으로 다시 확인했으며, `build/`, `dist/`, `__pycache__/`, `.pytest_cache/`, 로컬 DB/설정/로그 산출물을 계속 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `236 passed, 5 subtests passed`, `pyright` => `0 errors, 0 warnings, 0 informations`, `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드 성공이다.

## 0. 2026-04-16 구현 리스크 후속/문서 정합화 재검증

이번 재검증에서는 2026-04-16 follow-up risk fixes 배치와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- `core.workers.ApiWorker`는 `500/502/503/504` 등 `5xx`를 재시도 경로로 편입하고, 최종 실패 시에도 `last_error_meta(kind=http_error, retryable=True)`를 유지한다.
- `ui.news_tab.NewsTab`의 초기 hydration은 request-id 취소 + late cleanup 방식으로 강화되었고, 시작 시 북마크/현재 탭만 즉시 로드한 뒤 나머지 뉴스 탭은 순차 hydration queue로 읽어들인다.
- `ui._main_window_settings_io.py`의 설정 import는 `stage -> persist -> apply-runtime -> startup reconcile` 순서로 재구성되어, 중간 실패 시 부분 적용된 UI/runtime 상태를 남기지 않는다.
- `core.backup.AutoBackup`은 legacy `include_db` 누락을 tri-state로 읽고 실제 payload 파일로 복원 범위를 자동 판정하며, 수동 검증/복원 직전 검증 결과(`verification_state`, `last_verified_at` 등)를 `backup_info.json`에 저장한다.
- 통계/언론사 분석은 `AsyncJobWorker`가 아니라 `InterruptibleReadWorker` 기반 비동기 로드로 전환되었고, 다이얼로그 종료 시 SQLite read interruption을 함께 요청한다.
- startup FTS backfill은 dedicated retry scheduler로 `5초 -> 15초 -> 30초 cap` backoff를 사용하며 유지보수/전체 fetch/순차 refresh/종료 경계에서 pause/resume 된다.
- `news_scraper_pro.spec`는 2026-04-16 기준 다시 재검토되었고, 이번 패스의 hydration late-cleanup, staged import atomicity, backup metadata compatibility/persistence, interruptible analysis read, FTS retry scheduler는 기존 번들 의존성만 사용하므로 hidden import/exclude/data 추가 수정이 필요하지 않았다.
- `.gitignore`는 빌드 직후 `git status --ignored` 기준으로 다시 확인했으며, `build/`, `dist/`, `.pytest_tmp/`, 로그/캐시 산출물을 계속 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `228 passed, 5 subtests passed`, `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드 성공이며, `pyright`는 로컬 환경에서 `PyQt6`/`requests` import source 미해결과 일부 optional/member 타입 이슈 때문에 `74 errors, 5 warnings, 0 informations` 상태다.

## 0. 2026-04-13 구현 리스크 후속 정합화 / 문서 재검증

이번 재검증에서는 2026-04-13 구현 리스크 후속 정합화 패스와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- `core.database.DatabaseWriteError`가 추가되었고 `core._db_mutations.upsert_news(...)`는 더 이상 `sqlite3.Error`를 `(0, 0)`으로 삼키지 않는다.
- `core.workers.ApiWorker`는 `get_existing_links_for_query(...)` 실패와 `upsert_news(...)` 실패를 각각 DB error 경로로 올리며, 상위 UI는 이를 fetch 성공 완료와 분리해 처리한다.
- `ui._main_window_fetch.on_fetch_error(...)`는 DB 오류와 API/네트워크 오류를 구분해 다른 제목/안내 문구를 보여준다.
- `core._db_schema.init_db()`는 `title_hash IS NULL` / `pubDate_ts IS NULL` backfill을 반복 배치 루프로 수행해 대용량 legacy DB에서도 startup migration 잔여분이 남지 않게 한다.
- `ui._settings_dialog_tasks.py`의 API 키 검증은 이제 `HttpClientConfig` 기반 공용 session과 현재 `spn_api_timeout` 값을 사용하고, timeout/network/http failure를 구분해 반환한다.
- 저장소에 남아 있던 mojibake UI/테스트 문자열이 정리되었고, `tests/test_encoding_smoke.py`는 단일 토큰이 아니라 다중 suspicious token/정규식 패턴을 감시한다.
- `news_scraper_pro.spec`는 2026-04-13 기준 다시 재검토되었고, 이번 패스의 DB write failure 승격, 반복 backfill, 설정 검증 HTTP 정책 통합, 인코딩 가드 강화는 기존 번들 의존성만 사용하므로 hidden import/exclude/data 추가 수정이 필요하지 않았다.
- `.gitignore`는 build/dist/runtime/test 산출물을 이미 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `209 passed, 5 subtests passed`, `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드 성공이며, `pyright`는 로컬 환경에서 `PyQt6`/`requests` import source 미해결과 기존 타입 이슈 때문에 `55 errors, 5 warnings, 0 informations` 상태다.

## 0. 2026-04-09 구현 리스크 개선 전면 반영 / 문서 재검증

이번 재검증에서는 2026-04-09 구현 리스크 개선 패스와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- `core.http_client.HttpClientConfig`가 도입되어 `ApiWorker`는 이제 메인 윈도우의 mutable shared session이 아니라 worker-owned `requests.Session`을 중앙 HTTP 설정에서 생성해 사용한다.
- `ApiWorker.last_error_meta`와 `MainApp` 전역 fetch cooldown이 연결되어 429/quota 성격 오류 후 수동 refresh, 자동 refresh, 순차 refresh, `더 불러오기`가 동일한 차단/재개 규칙을 따른다.
- CSV export는 `DatabaseManager.iter_news_snapshot_batches(...)`로 한 read snapshot 안에서 `count + paged fetch`를 끝까지 순회하므로 export 중 DB 변화가 있어도 결과가 시작 시점 기준으로 고정된다.
- `DBWorker`는 일반 pool connection 대신 `open_read_connection(...)`으로 연 dedicated read connection을 사용하고 `stop()` 시 `interrupt_connection(...)`을 요청해 종료/유지보수 시 취소 성공률을 높인다.
- 통계/언론사 분석은 메인 스레드 동기 DB 조회가 아니라 `AsyncJobWorker` 기반 비동기 로딩으로 전환되었고, 다이얼로그 close/탭 변경 후 stale 결과를 버리는 가드가 추가됐다.
- `news_fts` FTS5 가상 테이블, 동기화 trigger, `app_meta` 기반 백필 상태 저장, UI 초기화 후 incremental backfill worker가 추가됐다. 다만 검색 의미의 진실 원본은 계속 기존 `LIKE/NOT LIKE` SQL이고, FTS는 backfill 완료 후 positive token filter의 candidate pruning에만 사용된다.
- `news_scraper_pro.spec`는 2026-04-09 기준 다시 재검토되었고, 이번 패스의 HTTP 구성 계층/FTS5/backfill/async analysis는 기존 번들 의존성만 사용하므로 hidden import/exclude/data 추가 수정이 필요하지 않았다.
- `.gitignore`는 build/dist/runtime/test 산출물을 이미 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `203 passed, 5 subtests passed`, `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드 성공이며, `pyright`는 로컬 환경에서 `PyQt6`/`requests` import source 미해결과 기존 타입 이슈 때문에 `55 errors, 5 warnings, 0 informations` 상태다.

## 0. 2026-04-05 구현 리스크 감사 반영 / 문서 재검증

이번 재검증에서는 2026-04-05 구현 리스크 감사 반영 패스와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- 유지보수 모드는 이제 fetch 계열뿐 아니라 탭 DB 재조회, 필터/정렬/기간 변경 reload, CSV export, 통계/분석, `모두 읽음`, import 직후 선택 refresh까지 DB 작업 전반을 차단한다.
- `core.database.DatabaseQueryError`가 도입되어 조회/집계 실패가 `[]`/`0`으로 묻히지 않고, `DBWorker -> NewsTab/MainApp` 경로에서 상태바/토스트/명시적 경고로 surfaced된다.
- 키워드 그룹 저장 실패는 더 이상 `KeywordGroupManager` 내부에서 로그만 남기고 삼키지 않으며, `KeywordGroupDialog`는 실패 시 닫히지 않아 사용자가 수정 내용을 유지한 채 재시도할 수 있다.
- `AutoBackup.create_backup()`는 payload 기록 직후 self-verify를 수행하고, 실패한 백업도 폴더를 보존한 채 목록에서 `복원 불가` 항목으로 남겨 후속 진단이 가능하다.
- 설정 import는 새 탭 추가 후 곧바로 묻지 않고, 실제 refresh 가능 여부(유지보수 중 아님, 순차 새로고침 미실행 중, API 자격증명 유효)를 먼저 확인한 뒤에만 선택 새로고침 프롬프트를 띄운다.
- `news_scraper_pro.spec`는 2026-04-05 기준 다시 재검토되었고, 이번 패스의 유지보수 경계 강화/실패 표면화/self-verify 추가 이후에도 hidden import/exclude/data 추가 수정은 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `196 passed, 5 subtests passed`, `pyright` => `0 errors, 0 warnings, 0 informations`, `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드 성공이다.

## 0. 2026-04-02 구현 감사 전면 반영 / 문서 재검증

이번 재검증에서는 2026-04-02 구현 감사 전면 반영 패스와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- CSV export, 설정 export/import, 백업 create/restore/delete는 이제 `ui.dialog_adapters.QtDialogAdapter`를 통해 Qt static dialog 의존성을 얇게 감싼다.
- 설정 import는 새로 추가된 탭 목록을 추적하고, 사용자가 동의하면 `refresh_selected_tabs(...)`로 새 탭만 순차 새로고침한다.
- 백업 생성은 `core.backup.AutoBackup.validate_create_backup_prerequisites(...)` 기준으로 restorable payload 여부를 먼저 검사하며, 설정 파일이 없으면 manual backup은 실패하고 startup auto-backup은 조용히 skip한다.
- 앱 종료는 `MainApp._perform_real_close()`에서 열린 `NewsTab` cleanup을 먼저 수행하고, `NewsTab.cleanup()`은 timer/DB worker/job worker/request state를 idempotent하게 정리한다.
- `news_scraper_pro.spec`는 2026-04-02 기준 다시 재검토되었고, dialog adapter, 종료 cleanup, backup preflight, selective refresh 추가 이후에도 hidden import/exclude/data 추가 수정은 필요하지 않았다.
- `.gitignore`는 build/dist/runtime/test 부산물을 이미 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `python -m pytest -q` => `196 passed, 5 subtests passed`이며, `pyinstaller --noconfirm --clean news_scraper_pro.spec`도 2026-04-02 기준 다시 성공했다.

## 0. 2026-03-27 UI/UX 하드닝/문서 재검증

이번 재검증에서는 2026-03-27 UI/UX 하드닝 패스와 문서/패키징 기준이 실제 저장소 상태와 계속 일치하는지 다시 확인했다.

- `SettingsDialog`는 `help_mode` / `initial_tab`을 지원하고, 도움말은 저장 가능한 설정 창이 아니라 read-only 도움말 다이얼로그로 열린다.
- `NewsTab`은 기간 필터를 즉시 반영형에서 `적용`/`해제` 흐름으로 바꿨고, 외부 기사 열기 실패 시 읽음 처리하지 않으며, unread 카운트는 현재 로드된 slice가 아니라 현재 DB scope 전체를 기준으로 유지한다.
- 자동 새로고침 카운트다운은 전용 상태바 라벨로 분리되었고, 자동 새로고침 완료 알림은 트레이 미지원 환경에서도 desktop fallback을 유지한다.
- `KeywordGroupDialog`는 staged save/cancel 모델로 바뀌었고, `LogViewerDialog`는 debounce 검색을 사용한다.
- 백업 목록은 quick metadata를 먼저 보여주고, 무거운 SQLite integrity/sidecar 검사는 사용자가 직접 시작하는 on-demand verification으로 전환됐다.
- `news_scraper_pro.spec`는 2026-03-27 기준 다시 재검토되었고, help/read-only dialog, on-demand backup verification, unread count bookkeeping, tray fallback 알림 추가 이후에도 hidden import/exclude/data 추가 수정은 필요하지 않았다.
- `.gitignore`는 build/dist/runtime/test 부산물을 이미 충분히 무시하고 있어 이번 패스에서도 추가 규칙이 필요하지 않았다.
- 문서 기준 현재 검증선은 `pytest -q` => `188 passed, 5 subtests passed`이며, `pyinstaller --noconfirm --clean news_scraper_pro.spec`도 2026-03-27 기준 다시 성공했다.

## 0. 2026-03-25 운영 안정화/문서 재검증

이번 재검증에서는 2026-03-25 운영 안정화 패스가 실제 저장소 구조, 문서, 패키징 기준과 계속 일치하는지 다시 확인했다.

- CSV export는 이제 `IterativeJobWorker`를 통해 UI 스레드 밖에서 청크 기반으로 DB를 순회하고, `*.tmp`에 저장한 뒤 atomic rename으로 마무리된다.
- 백업 목록은 quick metadata 이후 background full verification을 수행하며, config JSON parse, DB payload 존재 여부, SQLite integrity check, sidecar 정책 검사까지 포함한다.
- 자동 시작은 단순 on/off가 아니라 `StartupManager.get_startup_status()` 기준의 health 상태(`정상/수리 필요/비활성화`)를 가지며, 설정 창에서 repair를 직접 수행할 수 있다.
- 설정 저장은 main config와 `.backup` 회전을 모두 atomic하게 수행하고, SQLite emergency connection은 상한과 rejection logging을 갖는다.
- `news_scraper_pro.spec`는 2026-03-25 기준 다시 재검토되었고, `IterativeJobWorker`, backup verification, startup health/repair, config rotation, DB emergency cap 추가 이후에도 hidden import/exclude/data 추가 수정은 필요하지 않았다.
- `.gitignore`는 기존 build/dist/runtime 산출물 외에 로컬 회귀 테스트용 `.pytest_tmp/`를 명시적으로 무시하도록 보강했다.
- 문서 기준 현재 검증선은 `pytest -q` => `180 passed, 5 subtests passed`이며, `pyinstaller --noconfirm --clean news_scraper_pro.spec`도 2026-03-25 기준 다시 성공했다.

## 0. 2026-03-24 문서/패키징 재검증

이번 재검증에서는 성능 리팩토링 이후 패키징/문서 기준이 실제 저장소 상태와 계속 일치하는지 다시 점검했다.

- `news_scraper_pro.spec`는 2026-03-24 기준 재검토되었고, `DBQueryScope`, append skip-count, fragment cache/coalesced render, 복합 인덱스 추가 이후에도 hidden import/exclude/data 추가 수정은 필요하지 않았다.
- `.gitignore`는 `build/`, `dist/`, 런타임 DB 파일, 복원 스테이징 잔여물을 이미 무시하고 있어 이번 배치에서도 추가 규칙이 필요하지 않았다.
- `README.md`, `claude.md`, `gemini.md`, `update_history.md`의 검증 기준/패키징 메모를 다시 대조해 현재 아키텍처 설명과 맞췄다.
- 2026-03-24 기준 클린 빌드 명령 `pyinstaller --noconfirm --clean news_scraper_pro.spec`가 다시 성공했고, 산출물은 `dist/NewsScraperPro_Safe.exe`다.

## 0. 2026-03-18 실행형 리스크 전면 수정 반영

이번 배치에서는 2026-03-16 기준선을 다시 한 번 확장해, 실행 중 경합과 대용량 탭 동작까지 실제 구현 기준으로 보정했다.

- 로컬 탭 조회는 "전체 적재 후 클라이언트 필터"가 아니라 `DBWorker -> count_news(...) + fetch_news(..., limit, offset)` 기반의 DB 페이지네이션으로 동작한다.
- append 경로는 `DBQueryScope + known_total_count`를 사용해 `count_news(...)`를 다시 호출하지 않고 `fetch_news(..., limit, offset)`만 수행한다.
- HTML 내부 `더 보기`는 메모리 slice 확장이 아니라 다음 DB 페이지 append로 동작한다.
- `filtered_data_cache`는 현재 로드된 slice 의미만 가지며, CSV export와 `현재 표시 결과만` 읽음 처리는 현재 탭 필터 조건 전체 결과를 DB에서 다시 조회하는 별도 경로를 사용한다.
- `NewsTab.render_html()`은 fragment cache와 event-loop coalesced flush를 사용해 연속 상태 변경/append/빠른 필터 입력에서 `setHtml()` 호출 수를 줄인다.
- `DatabaseManager.mark_query_as_read(...)`는 단일 SQL update 경로로 바뀌었고, `filter_txt`, `hide_duplicates`, 날짜 범위, bookmark scope, `query_key`를 함께 반영한다.
- 설정 export/import는 `1.2` 기준이며 API 자격증명은 제외하고 `settings.auto_start_enabled`는 포함한다.
- 설정 창 데이터 정리 전에는 앱 전역 유지보수 모드가 활성화되며, active fetch 취소와 새 fetch 진입 차단이 함께 적용된다.
- 백업 목록은 이제 `is_restorable`, `restore_error` 메타를 포함해 UI에서 복원 가능 여부를 사전 표시한다.
- 현재 검증 기준은 `python -m pytest -q` 기준 `180 passed, 5 subtests passed`, `python -m pyright` 기준 `0 errors, 0 warnings, 0 informations`다.

## 0. 2026-03-16 기능 감사 후속 반영

이번 후속 반영으로 구조적으로 중요한 동작이 몇 가지 더 명확해졌다.

- 기사 단건 상태(`읽음/안읽음`, `북마크`, `메모`, `삭제`)는 현재 탭 로컬 캐시에만 머무르지 않고 열린 뉴스 탭과 북마크 탭 전체에 `link` 기준으로 즉시 동기화된다.
- `모두 읽음` 같은 bulk 작업은 증분 반영보다 안전성을 우선해 DB 유지보수 완료와 같은 full refresh 경로를 재사용한다.
- 알림 키워드는 fetch 응답 전체가 아니라 이번 요청에서 새로 추가된 기사(`new_items`)에만 적용된다.
- 탭 dedupe, 탭 리네임 충돌 판정, 설정 import dedupe, 검색 이력 dedupe는 모두 `canonical query` 기준으로 통일되었다.
- CSV 내보내기는 2026-03-16 시점의 visible-only 경로를 거쳐, 현재는 "현재 탭 필터 조건 전체 결과"를 DB에서 다시 조회해 저장하는 방식으로 정착되었다.
- 시작 시 자동 백업은 계속 설정만 저장하며, DB 복원 지점은 수동 백업(DB 포함)으로 만들도록 UI/문서가 맞춰졌다.
- 현재 검증 기준은 최신 배치 기준 `python -m pytest -q` => `180 passed, 5 subtests passed`, `python -m pyright` => `0 errors, 0 warnings, 0 informations`이다.

## 0. 2026-03-12 리팩토링 반영 상태

초기 분석 이후 실제 분할 리팩토링이 반영됐다.

- `ui.main_window.MainApp`은 facade / composition root로 유지된다.
- `core.database.DatabaseManager`는 facade로 축소되고, 실제 책임은 `core/_db_*.py`로 분리됐다.
- `ui.settings_dialog.SettingsDialog`는 facade로 유지되고, UI 조립/문서 HTML/비동기 작업이 `ui/_settings_dialog_*.py`로 분리됐다.
- 공개 import 경로는 그대로 유지된다.

## 1. 한눈에 보는 현재 구조

이 프로젝트는 **PyQt6 기반 데스크톱 뉴스 수집/관리 앱**이며, 현재 구조는 크게 아래 4층으로 나뉜다.

```text
사용자 입력 / 시스템 이벤트
    ↓
ui.main_window.MainApp
    ↓
ui.news_tab.NewsTab / ui.dialogs.* / ui.settings_dialog.SettingsDialog
    ↓
core.workers / core.database / core.config_store / core.backup / core.startup
    ↓
Naver News API / SQLite / JSON 설정 / Windows 레지스트리 / 파일 백업
```

핵심 특징은 다음과 같다.

- 루트 파일은 대부분 **호환성 유지용 얇은 래퍼**다.
- 실제 런타임 로직은 `core/`와 `ui/`에 모여 있다.
- `MainApp`이 사실상 전체 앱 상태를 조율하는 **오케스트레이터** 역할을 한다.
- 데이터 저장의 중심은 SQLite이며, 설정/복원/백업은 JSON + 파일 복사 기반이다.
- 최근 버전(`v32.7.x`)에서 안정화 작업이 크게 진행되어, 단일 인스턴스, 백업 복원, 워커 수명, 타입/인코딩 가드가 강화됐다.

## 2. 루트 디렉터리의 의미

### 핵심 루트 파일

| 경로 | 역할 |
|---|---|
| `news_scraper_pro.py` | 실제 엔트리포인트이자, 과거 import 경로를 유지하기 위한 re-export 레이어 |
| `news_scraper_pro.spec` | PyInstaller onefile 빌드 설정 |
| `README.md` | 사용자/개발자 관점의 공식 구조 요약 |
| `claude.md`, `gemini.md` | AI 작업 지침이지만, 실제로는 아키텍처 메모와 수정 규칙 문서 역할도 겸함 |
| `update_history.md` | 버전별 변경 이력의 단일 기준 문서 |
| `pytest.ini` | 테스트 진입점 고정 |
| `pyrightconfig.json` | 타입 검사 범위 및 Windows/Python 3.14 기준 고정 |

### 호환성 래퍼

루트의 아래 파일들은 새 기능을 직접 구현하는 위치가 아니라, **기존 import 경로를 깨지 않기 위한 compatibility layer**다.

- `query_parser.py`
- `config_store.py`
- `database_manager.py`
- `backup_manager.py`
- `worker_registry.py`
- `workers.py`
- `styles.py`

새 기능은 가능하면 이 래퍼가 아니라 `core/` 또는 `ui/` 쪽 본체에 추가하는 편이 맞다.

## 3. 실제 런타임 흐름

### 3-1. 앱 시작

1. `news_scraper_pro.py`가 HiDPI 환경 변수를 세팅하고 `core.bootstrap.main`으로 진입한다.
2. `core.bootstrap.main()`이 다음을 수행한다.
   - 로깅 초기화
   - 전역 예외 훅 등록
   - `pending_restore.json` 기반 복원 적용
   - `QLockFile` + `QLocalServer`로 단일 인스턴스 보장
   - `QApplication` 생성
   - `ui.main_window.MainApp` 생성 및 표시
3. `MainApp.__init__()`이 다음을 초기화한다.
   - `DatabaseManager`
   - `HttpClientConfig`
   - `WorkerRegistry`
   - `ToastQueue`
   - `KeywordGroupManager`
   - `AutoBackup`
   - 설정 로드, UI 구성, 타이머/트레이 설정, FTS incremental backfill kickoff

### 3-2. 뉴스 가져오기

1. 사용자가 탭을 만들거나 새로고침을 누른다.
2. `MainApp.fetch_news()`가 탭 쿼리를 파싱한다.
   - `parse_search_query()` = API 검색용, 양(+) 키워드 전체
   - `parse_tab_query()` = DB 그룹 키, 첫 번째 양(+) 키워드
3. `ApiWorker`가 별도 `QThread`에서 worker-owned `requests.Session`으로 Naver API를 호출한다.
4. 응답 결과는 `core.database.DatabaseManager.upsert_news()`로 저장된다.
5. `MainApp.on_fetch_done()`이 완료 콜백을 받아 탭 재로딩, 배지 업데이트, 토스트/트레이 알림을 처리한다.
6. `NewsTab.load_data_from_db()`는 다시 `DBWorker`를 돌려 DB에서 탭 목록을 비동기로 읽는다.
7. `NewsTab.render_html()`은 실제 flush를 스케줄링하고, `_flush_render()`가 `QTextBrowser` 기반 카드 HTML을 coalesced render로 반영한다.

### 3-3. 설정/백업/복원

- 설정은 `core.config_store`가 스키마 정규화와 원자 저장을 담당한다.
- 백업은 `core.backup.AutoBackup`이 폴더 단위로 생성한다.
- 복원은 즉시 덮어쓰기보다 `pending_restore.json`을 먼저 기록하고, 다음 시작 시 적용하는 모델이다.
- Windows에서 `client_secret`은 DPAPI 암호화 저장을 우선 사용한다.

## 4. 디렉터리별 책임 분석

### `core/`

앱의 비UI 로직이 모여 있는 영역이다.

### 중요한 모듈

| 모듈 | 실제 책임 |
|---|---|
| `core/bootstrap.py` | 앱 시작, 단일 인스턴스, 예외 처리, 복원 적용 |
| `core/constants.py` | 앱 경로, 파일명, 버전 상수 |
| `core/config_store.py` | 설정 TypedDict, 로드 정규화, 원자 저장/.backup 회전, import 보정, DPAPI |
| `core/database.py` | `DatabaseManager` facade, 연결 풀 수명 주기 |
| `core/_db_schema.py` | DB 초기화, 마이그레이션, 무결성 검사, 복구 |
| `core/_db_duplicates.py` | 제목 해시, 중복 플래그 계산/복구 |
| `core/_db_queries.py` | 조회, count, unread 집계 |
| `core/_db_mutations.py` | upsert, 상태 변경, 삭제, mark-read |
| `core/_db_analytics.py` | 통계, 언론사별 집계 |
| `core/http_client.py` | 중앙 HTTP 설정, session factory |
| `core/workers.py` | `ApiWorker`, `DBWorker`, `AsyncJobWorker`, `IterativeJobWorker`, `InterruptibleReadWorker`, `DBQueryScope` |
| `core/worker_registry.py` | 요청 ID 기반 워커 활성 상태 관리 |
| `core/query_parser.py` | 검색어 파싱 정책의 단일 기준 |
| `core/backup.py` | 백업 생성, 검증, 복원 예약, pending restore staging/rollback |
| `core/startup.py` | 자동 시작 상태 진단 + Windows 시작프로그램 레지스트리 제어 |
| `core/keyword_groups.py` | 키워드 그룹 저장/병합/마이그레이션 |
| `core/text_utils.py` | 날짜 파싱, HTML/강조, LRU 캐시, perf timer |
| `core/validation.py` | API 키/키워드 입력 검증 |
| `core/notifications.py` | 플랫폼별 알림 소리 |
| `core/protocols.py` | 타입 계약용 Protocol |

### 구조적으로 중요한 관찰

- `core.database.py`는 133줄 수준의 facade로 축소됐고, 실제 책임은 `core/_db_*.py`로 분리됐다.
- `core.config_store.py`는 단순 설정 저장 모듈이 아니라, **호환성/보안/정규화 레이어**다.
- `core.query_parser.py`는 작지만 의미상 매우 중요하다. 탭 의미, API 질의, 페이지네이션 키가 여기 정책에 묶여 있다.
- `core.backup.py`는 파일 복사 유틸이 아니라, **복원 무결성 보장 모듈**에 가깝다.
- `core.workers.DBWorker`는 탭 raw keyword를 다시 파싱하지 않고, `NewsTab`이 계산한 `DBQueryScope`를 그대로 소비한다.

### `ui/`

PyQt 위젯과 사용자 상호작용의 대부분이 여기에 있다.

### 중요한 모듈

| 모듈 | 실제 책임 |
|---|---|
| `ui/main_window.py` | `MainApp` facade, 공용 helper, 초기화/설정/기본 UI 조립 |
| `ui/_main_window_tabs.py` | 탭 추가/닫기/리네임/컨텍스트 메뉴/그룹 연결 |
| `ui/_main_window_fetch.py` | fetch orchestration, pagination, worker 수명 주기 |
| `ui/_main_window_settings_io.py` | 설정 import/export, 도움말/설정창, DB 유지보수 동기화 |
| `ui/_main_window_tray.py` | 시스템 트레이, close/minimize, 실제 종료 처리 |
| `ui/_main_window_analysis.py` | 통계/언론사 분석 UI |
| `ui/news_tab.py` | 개별 탭의 목록 필터링, 링크 인덱스 캐시, HTML fragment cache, coalesced render |
| `ui/dialog_adapters.py` | export/import/backup 경로의 QFileDialog/QMessageBox adapter |
| `ui/settings_dialog.py` | `SettingsDialog` facade, orchestration, public contract |
| `ui/_settings_dialog_content.py` | 설정/도움말/단축키 탭 조립 |
| `ui/_settings_dialog_docs.py` | 도움말 / 단축키 HTML |
| `ui/_settings_dialog_tasks.py` | API 검증, 데이터 정리, worker lifecycle |
| `ui/dialogs.py` | 메모/로그/그룹/백업 등 보조 다이얼로그 |
| `ui/widgets.py` | `NewsBrowser`, `NoScrollComboBox` |
| `ui/styles.py` | 색상 상수, 전체 QSS, HTML 템플릿 |
| `ui/toast.py` | 토스트 메시지 큐 |
| `ui/protocols.py` | UI 간 capability contract |

### 구조적으로 중요한 관찰

- `ui.main_window.py`는 940줄 수준의 facade로 축소됐고, 도메인별 책임은 private helper module로 나뉘었다.
- `ui.news_tab.py`는 여전히 `QTextBrowser`용 HTML 렌더링까지 담당하지만, 현재는 `_item_by_link` 인덱스와 fragment cache/coalesced render로 대용량 탭 비용을 낮춘 상태다.
- export/import/backup 경로는 `ui.dialog_adapters.py`를 통해 Qt static dialog 의존성을 분리해 테스트에서는 fake adapter를 주입한다.
- `ui.settings_dialog.py`는 117줄 수준의 facade로 축소됐다. 설정 항목 확장은 `ui/_settings_dialog_content.py` 쪽이 주 수정 지점이다.
- `ui/widgets.NewsBrowser`는 `app://...` 내부 URL 스키마를 이용한 액션 전달 구조를 갖고 있어, 카드 액션 확장이 상대적으로 쉽다.

### `tests/`

테스트는 단순 유닛 테스트라기보다 **회귀 방지용 계약 테스트 세트**에 가깝다.
일부는 실제 동작 검증이고, 일부는 AST/source-string 기반 가드 테스트다.

대략 아래 범주로 나뉜다.

- 엔트리포인트/호환성: `test_entrypoint_bootstrap.py`, `test_symbol_resolution.py`, `test_refactor_compat.py`
- 설정/정규화: `test_settings_roundtrip.py`, `test_import_settings_*`, `test_config_secret_storage.py`
- 검색/페이지네이션: `test_query_parser_search_policy.py`, `test_pagination_state_persistence.py`, `test_load_more_total_guard.py`
- 단일 인스턴스/시작: `test_single_instance_guard.py`, `test_start_minimized_guard.py`, `test_startup_registry_command.py`
- 백업/복원: `test_backup_*`, `test_pending_restore_strict.py`, `test_stabilization_round1.py`
- 워커/수명/안정성: `test_worker_cancellation.py`, `test_news_tab_ext_read_policy.py`, `test_news_tab_performance.py`, `test_settings_dialog_maintenance.py`, `test_stabilization_round1.py`
- 문서/버전/인코딩 가드: `test_version_history_guard.py`, `test_encoding_smoke.py`

즉, 새 기능 추가 시 테스트를 처음부터 새로 짜는 것보다, **기존 계약을 안 깨뜨리는 테스트를 같이 확장**하는 방식이 맞다.

## 5. 상태 저장 구조

### 설정 파일

`news_scraper_config.json`

주요 필드:

- `app_settings`
- `tabs`
- `search_history`
- `keyword_groups`
- `pagination_state`
- `pagination_totals`

특징:

- 로드 시 정규화된다.
- 저장 시 원자적으로 교체된다.
- `search_history`는 `canonical query` 기준으로 dedupe된다.
- 손상 시 `.backup` fallback 복구가 있다.
- Windows에서는 `client_secret_enc` + `client_secret_storage=dpapi` 경로를 지원한다.

### 데이터베이스

핵심 테이블은 2개다.

- `news`
- `news_keywords`

설계 의도는 다음과 같다.

- `news`는 기사 자체의 단일 원본 저장소
- `news_keywords`는 "어떤 탭 의미(키워드 그룹)에 이 기사가 속하는가"를 표현하는 매핑
- 중복 여부는 기사 전체가 아니라 **키워드 맥락별**로 계산할 수 있게 `news_keywords.is_duplicate`에 반영

즉, 앞으로 "태그", "커스텀 분류", "보관함", "소스 차단 규칙" 같은 기능을 넣을 때도 이 매핑 구조를 확장하는 방향이 자연스럽다.

### 백업/복원

백업 폴더:

- `backups/backup_YYYYMMDD_HHMMSS_microseconds/`

중요 특징:

- 설정만 또는 설정+DB 백업 지원
- 자동 백업과 수동 백업 보존 정책 분리
- 복원은 즉시 강행하지 않고 pending restore로 예약
- 적용 중 실패하면 rollback
- 메타 손상 백업도 목록에서 완전히 숨기지 않고 `손상됨` 상태로 노출

## 6. 비동기 / 스레드 구조

현재 앱은 PyQt 메인 스레드 블로킹을 줄이기 위해 역할별 워커를 나눴다.

| 구성요소 | 역할 |
|---|---|
| `ApiWorker(QObject)` | 외부 API 호출 + DB 저장 |
| `DBWorker(QThread)` | DB 조회 전용 |
| `AsyncJobWorker(QThread)` | 가벼운 단발성 작업(API 검증 등) |
| `IterativeJobWorker(QThread)` | 취소 가능한 반복형 장시간 작업(CSV export, 탭 전체 읽음, DB 유지보수 등) |
| `InterruptibleReadWorker(QThread)` | SQLite read interruption을 지원하는 분석/집계 전용 워커 |
| `WorkerRegistry` | 탭별 활성 요청 추적, stale callback 차단 |
| `DatabaseManager` | WAL + 연결 풀 + busy timeout |

이 구조의 장점은 분명하다.

- UI 프리징을 줄인다.
- stale callback 문제를 많이 줄였다.
- 설정창 종료 후 늦게 도착하는 콜백 문제를 방어하고 있다.

하지만 확장 시 반드시 주의해야 할 점도 있다.

- 워커 추가 시 `MainApp.cleanup_worker()` 같은 정리 루틴과 함께 설계해야 한다.
- DB 업데이트 성공 전에는 UI 캐시를 먼저 바꾸지 않는 현재 원칙을 유지해야 한다.
- 장시간 작업을 UI에서 직접 실행하면 지금까지 쌓아둔 안정화 이점을 잃는다.

## 7. 현재 구조의 강점

### 강점 1. 문서와 테스트가 생각보다 잘 맞물려 있다

`README.md`, `claude.md`, `gemini.md`, `update_history.md`가 최근 변경사항을 꽤 충실히 반영하고 있다. 또 `test_version_history_guard.py`, `test_encoding_smoke.py` 같은 문서/자산 가드도 존재한다.

### 강점 2. 설정/복원/백업의 안정성에 신경을 많이 썼다

단순 CRUD 앱이 아니라, 사용자 데이터가 실제로 쌓이는 앱이라는 전제에서 **복원 실패 시 보존**, **손상 백업 표시**, **설정 자동 복구**까지 고려돼 있다.

### 강점 3. 검색 의미를 분리해 둔 점이 좋다

`parse_search_query()`와 `parse_tab_query()`를 분리한 덕분에, "검색어 전체"와 "DB 그룹 키"가 서로 다른 의미를 가질 수 있다. 앞으로 탭 기능이 복잡해져도 이 분리는 계속 중요하다.

### 강점 4. Windows 중심 사용자 시나리오가 명확하다

트레이, 자동 시작, DPAPI, PyInstaller, 단일 인스턴스 IPC까지 Windows 사용 시나리오가 분명하게 잡혀 있다.

## 8. 기능 추가 전에 반드시 알아야 할 병목

라인 수 기준으로 큰 파일은 아래와 같다.

| 파일 | 대략 라인 수 | 해석 |
|---|---:|---|
| `ui/_main_window_fetch.py` | 551 | fetch/worker/pagination 도메인의 주된 병목 |
| `ui/main_window.py` | 940 | facade이지만 초기화/설정/배지 로직이 여전히 많음 |
| `ui/news_tab.py` | 983 | 탭 UI + 액션 + 렌더링이 한 파일에 집중 |
| `core/_db_mutations.py` | 392 | 쓰기/삭제/mark-read 책임이 가장 넓음 |
| `ui/_main_window_tabs.py` | 359 | 탭 상태/키워드/그룹 연결이 집중됨 |
| `ui/styles.py` | 746 | 스타일/QSS/HTML 템플릿이 매우 큼 |
| `core/config_store.py` | 647 | 설정 스키마와 보안/정규화 로직이 집중 |

### 실무적으로 중요한 결론

앞으로 기능을 계속 추가할 예정이라면, 가장 먼저 경계해야 할 것은 **facade 파일(`ui/main_window.py`, `core/database.py`, `ui/settings_dialog.py`)에 다시 구현을 되돌려 얹는 것**이다.

특히 아래 성격의 기능은 분리 모듈을 먼저 만드는 편이 낫다.

- 분석/대시보드
- 고급 필터/검색 조건 저장
- 새 외부 연동
- 대량 데이터 유지보수
- 추가 설정 탭

## 9. 기능 유형별 추천 진입점

### A. 새 설정 항목 추가

수정 지점이 거의 항상 같이 움직인다.

1. `core/config_store.py`
2. `ui/settings_dialog.py`
3. `ui/main_window.py`
4. `README.md`, `claude.md`, `gemini.md`
5. 관련 테스트

체크 포인트:

- TypedDict 스키마 추가
- load/save 정규화 추가
- SettingsDialog 위젯 추가
- `get_data()` 반환값 추가
- `MainApp.load_config()`, `save_config()`, `open_settings()` 반영
- import/export JSON 반영

### B. 탭별 필터/목록 기능 추가

추천 진입점:

- `ui/news_tab.py`
- `core/_db_queries.py`
- `core/_db_mutations.py`
- 필요 시 `core/query_parser.py`

예:

- 출처 필터
- 날짜 프리셋
- 읽음/북마크 조합 필터
- 태그 필터
- 저장된 검색 조건

주의:

- `NewsTab`은 일부 필터를 DB 조회 단계에서, 일부 필터를 메모리 단계에서 처리한다.
- 새 필터가 데이터량에 민감하면 메모리 후처리보다 SQL로 넣는 편이 낫다.

### C. 새 카드 액션 추가

추천 진입점:

- `ui/news_tab.py`
- `ui/widgets.py`
- `core/_db_mutations.py` 또는 새 서비스 모듈

현재 액션 전달 방식:

- HTML 링크: `app://open/...`, `app://note/...`, `app://bm/...`
- 우클릭 메뉴: `NewsBrowser.contextMenuEvent()`
- 실제 처리: `NewsTab.on_link_clicked()` / `on_browser_action()`

즉, 기사 카드에 "태그", "공유 템플릿", "출처 차단", "나중에 보기" 같은 기능을 넣기 쉽다.

### D. 새 통계/분석 기능 추가

추천 진입점:

- `ui/_main_window_analysis.py`
- `core/_db_analytics.py`

하지만 이 영역은 이미 `MainApp` 비대화가 진행된 상태라, 새 분석이 많아질 경우 아래처럼 분리하는 편이 좋다.

- `core/analytics.py`
- `ui/analysis_dialog.py`

### E. 새로운 백그라운드 작업 추가

추천 진입점:

- 단발성: `AsyncJobWorker` (가벼운 검증/단건 job)
- 장시간 반복형: `IterativeJobWorker`
- 조회 전용 + close/cancel 친화: `InterruptibleReadWorker`
- API/네트워크성: `ApiWorker` 패턴 복제 또는 분리
- 조회 전용: `DBWorker`

주의:

- 워커 시작과 정리 루틴을 세트로 작성해야 한다.
- UI가 닫힌 뒤 콜백이 늦게 오는 상황을 반드시 고려해야 한다.

### F. DB 스키마를 바꾸는 기능 추가

추천 진입점:

- `core/_db_schema.py:init_db()`
- 관련 CRUD 메서드
- export/import/backups/tests

주의:

- 이 프로젝트는 별도 마이그레이션 툴 없이 `init_db()` 내부 `ALTER TABLE` 패턴으로 진화해 왔다.
- 새 컬럼/테이블을 추가하면 인덱스, 복원, 삭제, 통계 경로를 함께 검토해야 한다.
- 기사 삭제 시 중복 플래그 재계산 규칙에 영향이 없는지 확인해야 한다.

## 10. 지금 구조에서 특히 잘 맞는 추가 기능 후보

아래 기능들은 현재 구조를 크게 깨지 않고 넣기 좋다.

### 1. 기사 태그/라벨 기능

이유:

- 기사 단위 액션 구조가 이미 있음
- DB 중심 구조라 태그 테이블 추가가 자연스러움
- `NewsTab`의 badge 렌더링과 잘 맞음

영향 파일 예상:

- `core/database.py`
- `ui/news_tab.py`
- `ui/dialogs.py` 또는 새 태그 다이얼로그
- CSV export 경로

### 2. 출처 차단 / 선호 언론사 필터

이유:

- 이미 `publisher`가 정규화되어 저장됨
- 분석 기능과 연결 가능
- `count_news()`, `fetch_news()` 확장으로 자연스럽게 구현 가능

### 3. 탭별 개별 자동 새로고침 정책

이유:

- 현재는 앱 전체 interval 중심
- `pagination_state`와 fetch state 구조가 이미 있어 탭별 상태 보존과 잘 맞음

필요:

- 설정 스키마 확장
- `MainApp` 타이머 정책 분리

### 4. 사용자 정의 저장 검색

이유:

- 검색 히스토리와 탭 구조가 이미 존재
- `keyword_groups`와 함께 쓰면 조직화 가치가 큼

### 5. 분석 대시보드 확장

예:

- 시간대별 기사 수
- 키워드별 증가량
- 중복률 추이
- 북마크 전환율

이 기능은 유용하지만, 추가 구현 전 `MainApp`에서 UI 일부를 분리하는 것이 좋다.

## 11. 기능 추가 전 다음 정리 우선순위

큰 기능을 여러 개 붙일 계획이라면, 선행 정리를 권장한다.

### 완료 1. `ui/main_window.py` 분리

현재 분리 상태:

- 탭 관리
- fetch/worker 관리
- 설정 import/export
- 트레이/종료 처리
- 통계/분석 UI

### 완료 2. `core/database.py` 분리

현재 분리 상태:

- 조회/검색
- 쓰기/상태 변경
- 통계/분석
- 백필/중복 복구
- 스키마 초기화

### 완료 3. `ui/settings_dialog.py` 분리

현재 분리 상태:

- 일반 설정
- 도움말/단축키
- 데이터 관리
- 비동기 워커 관리 헬퍼

### 다음 우선순위 후보

- `ui/news_tab.py` 분리: 목록 렌더링 / 카드 액션 / 필터 UI / DB 로드 콜백
- `core/config_store.py` 분리: 기본값 / 정규화 / 저장 / secret storage
- `ui/styles.py` 분리: QSS / HTML 템플릿 / 상수

## 12. 변경 시 반드시 같이 확인할 것

### 문서 동기화 규칙

이 저장소는 최근 변경에서 문서 동기화를 중요하게 보고 있다.

- 버전 변경 시 `core/constants.py`와 `update_history.md`를 같이 수정
- 구조/기능 변경 시 `README.md`, `claude.md`, `gemini.md` 반영 검토
- 텍스트 자산은 UTF-8 유지

### 테스트/검증 기본 세트

최소 권장:

```bash
pytest -q
pyright
```

변경 유형별로 특히 봐야 할 테스트:

- 설정: `test_settings_roundtrip.py`, `test_import_settings_*`
- 백업/복원: `test_backup_*`, `test_pending_restore_strict.py`
- 검색 정책: `test_query_parser_search_policy.py`
- 워커/취소: `test_worker_cancellation.py`
- 시작/트레이: `test_single_instance_guard.py`, `test_start_minimized_guard.py`
- 문서/버전: `test_version_history_guard.py`, `test_encoding_smoke.py`

## 최종 결론

현재 프로젝트는 이미 단순 스크립트 수준을 넘어, **Windows 데스크톱 앱으로서 꽤 안정화된 구조**를 갖추고 있다. 다만 구조의 중심이 `MainApp`, `DatabaseManager`, `NewsTab`에 강하게 몰려 있기 때문에, 앞으로 다양한 기능을 붙이려면 "기능을 추가하는 일"과 "책임을 분리하는 일"을 같이 가져가는 것이 좋다.

안전한 확장 전략은 아래 한 줄로 정리할 수 있다.

> 새 기능은 `core/`와 `ui/`의 새 모듈로 추가하고, 루트 래퍼와 대형 파일에는 연결 지점만 최소한으로 남기는 방향이 가장 유지보수성이 좋다.
