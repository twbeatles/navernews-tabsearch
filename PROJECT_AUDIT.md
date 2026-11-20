# Project Audit

감사일: 2026-11-06 (Asia/Seoul)

대상: `main`, 기준 커밋 `1575381f3576eccd7722567504524ffcef2731fb` 이후 작업 트리, 앱 버전 `32.11.6`

방식: 문서 검토 → CodeGraph MCP 구조/호출 관계 탐색 → 누락 구간 직접 확인 → 전체 테스트 및 격리 재현. 초기 감사는 리포트만 작성했으며, 이후 사용자 요청에 따라 아래 결함과 기능 공백을 수정했다. 초기 재현 근거는 유지하고 해결 상태와 남은 검증 범위를 함께 기록한다.

## 1. Executive Summary

초기 감사에서 확인한 결함 3건과 자동 백업의 기능 공백을 수정했다. 백업 실패본을 정상 복구본 quota에서 분리했고, DB 자동 백업·결과 표시·종료 대기를 추가했다. 클라우드는 빈 태그 상태를 전파하며 콘텐츠 갱신 시각, 결정적인 동률 규칙, 날짜/제목 hash 정규화를 공통 정책으로 적용한다. 현재 로컬 검증 기준 전체 평가는 **Acceptable**이다. 실제 외부 동기화 서비스와 Windows x64 고정 의존성 릴리스 검증은 별도로 남아 있다.

| 중요한 발견 | 판단 | 영향 |
|---|---|---|
| ISSUE-001: 실패본이 정상 복구본을 밀어냄 | High / Confirmed → 해결 | 정상본 quota와 실패본 정리 분리, snapshot 실패 시 raw copy 중단 |
| ISSUE-002: 마지막 태그 삭제 누락 | Medium / Confirmed → 해결 | 빈 태그 state를 포함한 preview/apply 공통 후보, 왕복 검증 |
| ISSUE-003: 오래된 콘텐츠 덮어쓰기 | Medium / Confirmed → 해결 | 콘텐츠 갱신 시각과 동률 규칙, 날짜/hash 동시 정규화 |
| GAP-001/002: DB 자동 백업·결과 가시성 | Confirmed Gap → 해결 | DB + 설정 background backup, 상태 파일/백업 창/제한된 알림 |

**데이터 손상/유실:** 초기 감사에서 SQLite 파일의 물리적 손상은 확인하지 않았으나 백업 삭제 정책과 논리적 덮어쓰기, 복구 공백을 확인했다. 해당 재현 조건은 회귀 테스트로 차단했다. 임의의 디스크 고장·시계 오차·외부 동기화 충돌까지 유실이 없음을 보장하는 평가는 아니다. 사용자 DB나 실제 백업은 변경하지 않았다.

추가 배포 판단에서는 실제 x64 CI 결과, 모든 PC의 버전 일치, DB 포함 백업의 존재 및 PC 시계 동기화를 확인해야 한다.

## 2. Project Understanding

### 목적과 실행 방식

키워드별 NAVER API HUB 뉴스를 수집하고 읽음·북마크·메모·태그·자동화 규칙으로 관리하는 PySide6 데스크톱 앱이다. README의 지원 대상은 Windows다. 소스 실행은 `python news_scraper_pro.py`, 배포본은 PyInstaller onefile `NewsScraperPro_Safe.exe`다.

`README.md`, `CLAUDE.md`, `AGENTS.md`, 의존성 파일, pytest/pyright 설정, PyInstaller spec, quality/release workflow를 확인했다. 별도 브랜치를 만들지 않았고 Spec Kit 산출물은 갱신하지 않았다.

### 핵심 구성

| 책임 | 주요 위치 |
|---|---|
| 엔트리포인트·부팅·단일 인스턴스 | `news_scraper_pro.py`, `core/bootstrap.py` |
| 메인 UI와 탭 | `ui/main_window.py`, `ui/news_tab.py`, 각 support mixin |
| 검색어 해석·검색 범위 식별 | `core/query_parser.py`, `build_fetch_key`, `DBQueryScope` |
| API URL/헤더·오류 분류 | `core/naver_api.py`, `core/workers_support/api_worker.py` |
| DB facade·연결·snapshot 읽기 | `core/database.py` |
| 스키마·질의·수정 | `core/db_schema_support/`, `core/db_queries_support/`, `core/db_mutations_support/` |
| 클라우드 ZIP·DB 병합 | `core/cloud_sync_support/`, `core/db_cloud_sync_support/` |
| 설정·비밀값 저장 | `core/config_store_support/`, `ui/main_window_support/config.py` |
| 백업·복원 | `core/backup_support/`, `ui/dialogs_support/backup_dialog/` |
| 내보내기·CSV 가져오기 | `ui/main_window_io_support/data_io.py`, `exports.py` |
| 서명 업데이트 | `core/update_manifest.py`, `core/update_installer.py`, `ui/main_window_update.py` |

### 저장과 외부 의존성

- SQLite `news_database.db`: `news`의 link 기본키, `news_keywords`의 검색 범위별 소속/중복 상태, `news_tags`, `news_tag_state`, `app_meta` 등. 연결은 WAL 및 외래키를 사용한다. 읽음/북마크/메모/삭제 상태에 갱신 시각을 저장한다.
- JSON `news_scraper_config.json`: 탭, 검색/페이지 상태, UI 설정, 규칙 등. 원자적 교체와 `.backup` 복구 경로가 있다. Windows의 Client Secret은 DPAPI를 우선 사용한다.
- 기본 Windows 데이터 경로는 `%LOCALAPPDATA%\NaverNewsScraperPro`. `NEWS_SCRAPER_DATA_DIR` override 및 portable 모드가 별도로 있다.
- 백업은 로컬 하위 디렉터리, 클라우드는 공유 폴더의 ZIP 스냅샷으로 분리한다. 실시간 SQLite를 공유 폴더에서 직접 공동 사용하려는 구조가 아니다.
- 주요 외부 라이브러리는 PySide6, requests, charset-normalizer, cryptography다. 뉴스 API, GitHub 업데이트 채널, OS 브라우저/트레이/시작 등록, 외부 폴더 동기화 프로그램에 의존한다.

### 핵심 실행 흐름과 상태 변경

1. **시작:** `news_scraper_pro.py → core.bootstrap.main → 런타임 경로/인스턴스 제어·예약 복원 → MainApp → 설정 로드 + DatabaseManager → 무결성 검사/스키마 초기화 → 탭 DB 로딩`.
2. **수집:** `탭 검색어 → fetch_news → 양키워드·자격증명·maintenance/cooldown 검증 → ApiWorker.run → API HUB → 제외어/URL 정규화 → upsert_news_detailed → SQLite transaction → finished/오류 → GUI relay → 목록·cursor·badge 갱신`.
3. **목록/필터:** `텍스트·읽음·중복·출처·태그·기간 입력 → DBQueryScope → DBWorker → 동일 읽기 transaction의 count/fetch → request ID 확인 → NewsTab 캐시/렌더링`. 기존 요청 취소와 오래된 응답 무시가 있다.
4. **기사 관리:** `기사 클릭/우클릭 → HTTP(S) URL 검증·브라우저 열기 또는 상태 액션 → DB 상태 저장 → 성공 시 로컬 캐시/표시 갱신`. 브라우저 열기 실패 시 읽음 처리를 진행하지 않는 경로가 있다.
5. **내보내기/가져오기:** `현재 scope 또는 CSV 선택 → worker → SQLite snapshot 읽기 / 기존 link 상태 import → 임시 출력·원자적 교체 또는 DB 변경 → 완료/실패/취소 및 UI 갱신`. CSV 수식 접두어 방어와 메모 길이 제한의 회귀 테스트가 있다.
6. **클라우드:** `설정된 폴더 → 경로/중복 작업/maintenance guard → 스냅샷 선택·검증·격리 → import_cloud_snapshot → merge_cloud_snapshot_db → 상태별 시각 비교·태그 교체·중복 재계산·seen ID 저장 → 새 ZIP 내보내기 → 화면 갱신`.
7. **백업/복원:** `타이머 또는 대화상자 → AutoBackup.create_backup → 설정 복사·선택적 DB snapshot → 자체 검증 → 보존 개수 정리`. 복원 UI는 검증/미리보기 후 예약하고, 재시작 경로에서 원자적 파일 교체와 예외 시 rollback을 사용한다.
8. **종료/업데이트:** `종료 요청 → 생산 타이머 중지 → background shutdown 대기/재시도 → 설정 저장·DB 종료`. 업데이트는 서명·크기·해시 확인, 실행 파일 옆 staging, helper 교체, 격리 smoke 및 실패 rollback 경로를 갖는다.

공유 상태의 주요 경계는 SQLite 기사/태그 상태, 검색 범위별 소속, MainApp의 worker registry·fetch cursor·maintenance 상태, NewsTab의 request ID·목록/읽지 않음 캐시다. DB transaction만으로 PC 간 의미적 병합 오류를 막을 수는 없다.

## 3. Audit Coverage & Limitations

### 확인 범위

위 표의 주요 파일/심볼과 CodeGraph가 연결한 production caller/callee를 확인했다. 특히 다음 관계를 추적했다.

- `fetch_news → ApiWorker.run → upsert_news_detailed`, `_ApiWorkerSignalRelay`, 순차 fetch 및 worker 정리 경계.
- `load_data_from_db → DBWorker.run → count_news_states/fetch_news → on_data_loaded/on_data_error`와 request ID/캐시 변경.
- `run_cloud_sync_now/_run_cloud_sync_once → run_cloud_sync_cycle/import_cloud_snapshot → merge_cloud_snapshot_db → _merge_cloud_news_rows/_merge_cloud_tag_rows`, preview/seen ID/rollback.
- `MainApp._run_auto_backup_once`와 대화상자 `create_backup → AutoBackup.create_backup → verify_backup_payload → _cleanup_old_backups → delete_backup`.
- `restore_backup/schedule_restore → apply_pending_restore_if_any → _apply_restore_from_backup`, backup child containment, staged rollback.
- `_perform_real_close`, 설정 atomic I/O, archive filters, chunked 정리/tombstone 보존, 서명 manifest/업데이트 staging.

### 실제 실행 결과

다음 표는 **초기 감사 시점**의 결과다. 개선 후 결과는 9절에 별도로 기록한다.

| 실행 | 결과 |
|---|---|
| `QT_QPA_PLATFORM=offscreen`으로 `python -m pytest -q -ra` | **513 passed, 1 skipped, 7 warnings, 14 subtests passed**, 44.36초, exit 0 |
| `python -m pyright` | **0 errors, 0 warnings, 0 informations**, exit 0 |
| `python news_scraper_pro.py --smoke` | 격리 MainApp 생성·북마크 DB 조회·quick_check·설정 저장·종료 성공, exit 0 |
| 작성 후 `python -m pytest tests/test_encoding_smoke.py tests/test_version_history_guard.py tests/test_spec_runtime_tmpdir.py -q` | **4 passed**, 0.21초, exit 0 |
| 임시 DB 2개와 실제 ZIP create/import를 이용한 태그 삭제/오래된 콘텐츠 병합 | ISSUE-002/003 재현, 최종 실행 exit 0 |
| 임시 정상 백업 5개와 손상 JSON으로 신규 백업 실패 유도 | ISSUE-001의 정상 백업 삭제 요청 확인. `delete_backup`은 mock으로 가로채 실제 삭제하지 않음, exit 0 |

skip은 `tests/test_live_naver_api_e2e.py:12`의 실제 인증 API 검사이며 `NAVER_API_LIVE_TEST=1` opt-in이 없어서 실행되지 않았다. warnings 7개는 legacy root wrapper import deprecation이다. 실행 시작 시 별도 pytest-asyncio fixture scope 설정 경고도 있었다. 이들을 앱 기능 결함으로 집계하지 않았다.

환경은 Windows 11 ARM64, Python 3.15.2다. 설치 버전은 PySide6 6.12.0, requests 2.34.2, charset-normalizer 3.5.2, cryptography 46.0.3, pytest 9.2.0, pyright 1.1.414다. requirements의 cryptography 50.0.2 / requirements-build의 pytest 9.1.1 및 CI 기준 Windows x64/Python 3.14와 다르다. **현재 머신의 통과 결과를 고정 의존성의 x64 배포 검증으로 대체할 수 없다.** 의존성을 설치하거나 변경하지 않았다.

### 반증과 한계

- `.codegraph/` 존재를 확인하고 **CodeGraph MCP를 실제 사용**했다. 파일/심볼 source, 호출자, 영향 범위, 동적 dispatch 후보를 먼저 조회했다. 출력이 생략한 구간은 추가 탐색 또는 직접 열람으로 보완했다. 동명 심볼/lexical match에는 관련 없는 후보도 포함되어 실제 파일과 caller를 기준으로 선별했다.
- CodeGraph는 정적 구조 정보다. Qt signal 실행 스레드, 외부 동기화 파일 도착 순서, OS lock이나 재시작을 보장하지 않는다. 경로 설명은 관련 소스와 테스트로 보완했으며 모든 런타임 조합을 실측한 것은 아니다.
- API credential guard, HTTP timeout/retry/redirect 거부, GUI relay, stale request guard, SQL parameter binding, primary key/transaction, backup 경로 검증, cloud maintenance/rollback/seen ID 등 기존 보호 장치를 확인했다. 이 장치로 반증되는 위험을 별도 결함으로 올리지 않았다.
- 기존 suite에는 DB 오류·무결성 복구, 공유 기사 제목 갱신, API 스레드 affinity, 취소/종료, 경로와 인코딩, CSV, 설정 roundtrip, update rollback 테스트가 포함된다. 전체 통과는 여기서 새로 재현한 경계 조건의 정상 동작을 의미하지 않는다.
- 초기 감사에서는 실제 NAVER 요청, 실제 OneDrive/Dropbox/NAS 동시 동기화, 실제 사용자 데이터의 migration/restore, GitHub release 게시, frozen EXE 재빌드/실제 교체를 실행하지 않았다. 후속 개선에서는 로컬 frozen 빌드와 격리 smoke를 추가 검증했다(9절). 실제 배포·전원 차단·디스크 고장·장시간 대용량 운전은 재현하지 않았다.
- Linux/macOS 실행·패키징·시작 등록은 검증하지 않았다. README상 Windows 전용이므로 이를 지원 누락 버그로 보지 않는다.
- 최초 태그 재현은 기대한 오류 상태를 출력한 뒤 임시 log 파일의 열린 handle 때문에 정리 단계에서 WinError 32로 끝났다. `logging.shutdown()`을 포함한 독립 재현을 다시 실행해 정상 종료까지 확인했다. 최초 정리 오류를 앱 production 버그로 분류하지 않았다.
- production 데이터/자격증명은 읽거나 재현에 사용하지 않았다. 테스트와 재현은 격리 runtime/임시 데이터로 실행했다. 초기 감사 결과물은 이 문서뿐이었다. 후속 개선은 소스·테스트·문서·CI에 적용했으며 실제 게시/배포는 검증 범위에 포함하지 않았다.

## 4. High-Risk Issues

이 절은 초기 결함의 재현 기록이며 세 항목 모두 현재 작업 트리에서 수정했다. 위치의 줄 번호는 초기 감사 기준이며 파일/함수 이름을 기준으로 후속 코드를 확인한다. Critical 또는 근거가 약한 Likely/Speculative 이슈는 집계하지 않았다.

### [ISSUE-001] 실패한 백업이 정상 복구본을 보존 목록에서 밀어낸다

**해결:** 검증 실패 시 정상본 pruning을 하지 않는다. 검증된 정상 자동/수동 백업은 각각 5/20개로 관리하고 실패본만 별도 5개로 제한한다. SQLite online snapshot 실패 시 live DB/WAL 복사로 우회하지 않는다. 연속 실패·검증 예외·정상 rotation 및 payload hash 보존을 회귀 검증했다.

- **위치:** `core/backup_support/auto_backup_support/create.py:100`, `:108`, `:152` — `create_backup`, `_cleanup_old_backups`; `listing.py:22` — `get_backup_list`.
- **우선순위:** High
- **신뢰도:** Confirmed
- **문제:** 자체 검증에서 `is_restorable=False`인 신규 디렉터리를 남긴 뒤에도 `_cleanup_old_backups()`를 실행한다. 정리는 trigger만 분류하고 정상/손상 여부에 관계없이 최신 N개를 보존하므로, 실패한 신규 백업이 정상 과거 백업을 밀어낸다.
- **발생 조건:** 자동 백업 5개 또는 수동 백업 20개가 있고, 다음 백업이 생성/메타데이터 저장까지 진행한 뒤 자체 검증에서 실패한다. 예를 들어 앱 실행 중 디스크의 설정 JSON이 손상되면 존재 여부만 확인하는 사전 검사와 타이머 caller를 통과한다. DB payload 검증 실패도 같은 분기다.
- **영향:** 실패를 알리는 반환값과 별개로 이전 정상 복구본을 잃는다. 반복 실패하면 정상 복구 이력이 모두 대체될 수 있다. 현재 DB가 이 함수에서 직접 삭제되는 문제는 아니다.
- **근거:** 임시 설정 `{}`로 실제 정상 자동 백업 5개를 생성한 뒤 원본 설정을 `{broken json`으로 바꿨다. 다음 호출은 `None`을 반환했지만, 가로챈 `delete_backup` 요청은 기존 정상 백업을 가리켰다. 출력: `valid_before=5`, `failed_result=None`, `deleted_candidate_was_valid=True`. 실제 삭제 API를 mock 처리했으므로 이번 감사에서 복구본을 삭제하지 않았다.
- **반증 확인:** `validate_create_backup_prerequisites`는 파일 존재만 확인한다. 자체 검증은 실패를 정확히 발견하지만 실패 분기 자체가 pruning을 호출한다. `get_backup_list`는 손상 상태를 기록해도 목록에서 제외하지 않는다. `_safe_backup_child_dir`는 삭제 위치를 보호하지만 삭제 대상의 복구 가치를 판단하지 않는다. 자동 caller도 설정을 재저장/검증한 뒤 호출하지 않는다.
- **호출/영향 범위:** CodeGraph의 production 경로는 `MainApp._run_auto_backup_once → AutoBackup.create_backup` 및 `BackupDialog.create_backup → AutoBackup.create_backup → _cleanup_old_backups → get_backup_list/delete_backup`이다. `_create_backup_legacy_unused`에만 존재하는 문제가 아니다. 자동/수동 보존 정책 모두 영향을 받는다.
- **권장 수정 방향:** 새 백업 검증 성공 전에는 정상 복구본 pruning을 하지 않는다. 실패본은 별도 격리/정리 정책으로 관리하고 정상 백업의 보존 개수를 차지하지 않게 한다. 최소 한 개 이상의 검증된 복구본 보존을 불변조건으로 둔다.
- **필요한 회귀 테스트:** 정상 자동 5개/수동 20개 상태에서 JSON 손상·DB integrity 실패·검증 예외를 각각 주입한다. 신규 실패 시 기존 정상 백업의 파일/개수/해시가 모두 유지되어야 한다. 실패 반복 후에도 유지되고, 성공한 신규 백업에서만 정상 보존 정책에 따른 rotation이 일어나야 한다.

### [ISSUE-002] 마지막 태그 삭제가 클라우드 병합에서 사라진다

**해결:** `policy.tag_candidates_sql`이 `news_tags`와 `news_tag_state`의 link 합집합을 사용한다. 빈 상태 timestamp도 병합하며 preview/apply가 같은 후보와 값 차이를 사용한다. 마지막 태그의 개별/전체/bulk 제거, 실제 ZIP 왕복, 최신 로컬 태그 보존을 검증했다.

- **위치:** `core/db_cloud_sync_support/merge_rows.py:178` — `_merge_cloud_tag_rows`, 특히 `:206`의 `FROM cloud_src.news_tags`; `core/db_cloud_sync_support/preview.py:152` — 태그 preview 계산.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 태그 교체 대상 link를 source의 `news_tags` 행에서만 뽑는다. 모든 태그를 지운 기사는 `news_tag_state`에 새 timestamp가 있어도 `news_tags` 행이 없어서 후보에 들지 않는다. 원격의 기존 태그와 오래된 timestamp가 그대로 남는다.
- **발생 조건:** A/B가 같은 기사의 태그를 공유한 후 A에서 마지막 태그를 삭제하고 새 스냅샷을 B로 병합한다. 개별 편집, 마지막 태그 일괄 제거/삭제 모두 동일한 DB 표현을 만든다.
- **영향:** 다른 PC의 태그가 지워지지 않아 태그 검색/분류 결과가 달라진다. 삭제한 PC로 오래된 태그 스냅샷이 되돌아오면 삭제가 취소될 여지도 있다. 마지막 재유입 단계는 이번 재현에서 별도 실행하지 않았다.
- **근거:** 실제 공개 API `set_tags`, `create_cloud_snapshot`, `import_cloud_snapshot`으로 재현했다. 최초 B 태그는 `['keep']`, A에서 `set_tags(link, [])` 후 A는 `[]`지만 B의 import 후에도 `['keep']`였다. 반환값은 `merged=True, tags_changed=0`으로 누락을 오류로 드러내지 않는다.
- **반증 확인:** `set_tags`는 빈 배열에서도 태그를 삭제하고 `news_tag_state` 갱신을 저장한다. ZIP은 DB snapshot을 정상 전달한다. `merge_cloud_snapshot_db`는 transaction, rollback, seen ID를 제공하지만 `_merge_cloud_tag_rows`의 잘못된 후보 집합을 수정하지 않는다. preview 역시 태그 행 기준이라 사용자 미리보기도 이를 알려주지 못한다. 최신 timestamp 비교만으로 빈 후보 문제를 막을 수 없다.
- **호출/영향 범위:** CodeGraph상 `run_cloud_sync_cycle/import_cloud_snapshot → merge_cloud_snapshot_db → _merge_cloud_tag_rows`; UI의 수동 import 및 주기 full sync가 모두 이 경로를 사용한다. `set_tags`, `delete_tag_everywhere`, `bulk_remove_tag_from_links`가 만드는 마지막 태그 제거가 영향을 받는다.
- **권장 수정 방향:** `news_tag_state`의 빈 태그 상태도 후보에 포함한다. 최신 상태 link를 먼저 결정하고 해당 link의 로컬 태그를 지운 뒤 source 태그가 존재하면 삽입한다. 빈 상태의 timestamp도 복사한다. preview와 실제 merge는 동일한 후보/변경 의미를 써야 한다.
- **필요한 회귀 테스트:** A 태그 `['x']`를 B로 전달 → A에서 `[]` → 새 ZIP import 후 B도 `[]`이고 timestamp가 A와 같아야 한다. 반대로 B의 더 최신 태그는 유지되어야 한다. 태그 전체 삭제·bulk remove·반복 import·역방향 sync와 preview 변경 수까지 검사한다.

### [ISSUE-003] 지연 도착한 오래된 스냅샷이 최신 기사와 날짜 일관성을 훼손한다

**해결:** `news.content_updated_at`을 마이그레이션으로 추가했다(기존 행은 시각을 추측하지 않고 0). API 관측으로 새 내용 또는 미기록 콘텐츠를 저장할 때 시각을 기록하며 동일 내용 재수집은 유지한다. 원본 콘텐츠 필드를 한 버전으로 선택하고 발행일 timestamp와 제목 hash는 해당 버전에서 정규화한다. 예전 snapshot은 신규 기사 추가는 허용하되 갱신 시각이 있는 로컬 콘텐츠를 덮어쓰지 않는다. 동률은 콘텐츠 값의 고정 순서를 사용한다. preview에도 `content_changed`를 표시한다.

- **위치:** `core/db_cloud_sync_support/merge_rows.py:73` — `_merge_cloud_news_rows`의 `ON CONFLICT(link) DO UPDATE`, 특히 title/description/pubDate/publisher/title_hash와 pubDate_ts 처리.
- **우선순위:** Medium
- **신뢰도:** Confirmed
- **문제:** 충돌 시 source의 비어 있지 않은 제목·요약·날짜 문자열·출처·제목 hash를 최신성 검사 없이 채택한다. 반면 `pubDate_ts`는 두 값 중 큰 값을 유지한다. 따라서 오래된 스냅샷을 가져오면 내용은 과거로 돌아가면서 날짜 문자열과 정렬용 숫자 날짜는 서로 다른 버전이 된다.
- **발생 조건:** B가 같은 link의 정정 기사/새 날짜를 API에서 수집한 뒤, A의 예전 콘텐츠가 담긴 아직 보지 않은 스냅샷이 지연 도착하거나 수동 import된다. 실제 두 PC의 온라인 시점 차이만으로 도달 가능하며 동시 실행이 필요하지 않다.
- **영향:** 정정 제목과 요약 손실, 텍스트 검색과 중복 숨김 대상 변화, 화면/내보내기의 표시 날짜와 기간 필터·정렬 결과 불일치. 읽음/메모의 최신성 보호는 별도로 동작하며 이를 모두 잃는다고 판단하지 않는다.
- **근거:** A에서 2024-01-01 `Old title` 스냅샷을 준비하고 B에 같은 link의 2024-01-02 `Corrected title`/요약을 `upsert_news`로 저장했다. A ZIP을 import하자 `Corrected title → Old title`, 날짜 문자열은 1월 1일로 되돌아갔지만 `pubDate_ts=1704153600.0`(1월 2일 UTC)이 유지됐다. 실제 SQLite와 ZIP import로 확인했다.
- **반증 확인:** link 기본키는 중복 행만 막는다. seen ID는 이미 처리한 동일 ZIP 재적용만 막고, 다른 PC의 아직 보지 않은 오래된 ZIP은 허용한다. source machine guard도 다른 PC의 스냅샷에는 적용되지 않는다. read/bookmark/notes/delete의 timestamp 비교는 콘텐츠 필드에는 없다. transaction과 전체 중복 재계산은 잘못 선택한 콘텐츠를 성공적으로 commit할 뿐이다. ZIP 생성 시각도 해당 필드 선택에 사용하지 않는다.
- **호출/영향 범위:** CodeGraph상 `import_cloud_snapshot → merge_cloud_snapshot_db → _merge_cloud_news_rows → 전체 duplicate 재계산`. 이어 탭 목록, 아카이브, 기간/텍스트 필터, export가 변경된 값을 소비한다.
- **권장 수정 방향:** 기사 콘텐츠의 관측/변경 버전과 병합 우선순위를 명시한다. source snapshot 생성 시각만으로 기사 원본의 최신성을 보장할 수 없으므로 콘텐츠별 갱신 metadata 등을 검토한다. 선택한 `pubDate`와 `pubDate_ts`, title과 title_hash는 같은 콘텐츠 버전에서 함께 적용한다. 기존 snapshot 호환 정책도 정한다.
- **필요한 회귀 테스트:** 정정 기사 저장 후 이전 source ZIP import 시 정정 내용 유지와 날짜 쌍의 일치를 검증한다. 신규 콘텐츠/빈 필드 보충/발행일이 그대로인 정정/도착 순서 역전/중복 hash 재계산/이전 schema snapshot을 별도로 검사한다.

## 5. Potential Functional Gaps

### [GAP-001] Confirmed Gap — 예약 자동 백업의 DB 보호 범위가 비어 있다

**해결:** 현재 `_run_auto_backup_once`는 GUI relay를 갖춘 전용 worker로 `include_db=True` 백업을 실행한다. 중복 작업은 차단하고 실제 thread 종료까지 앱 종료를 지연한다. 아래 내용은 초기 발견 근거다.

`ui/main_window_support/config.py:282`의 `_run_auto_backup_once`는 명시적으로 `create_backup(include_db=False, trigger="auto")`를 호출한다. `ui/main_window.py:212`는 타이머를 이 메서드에 연결한다. 따라서 현재 주기 자동 백업으로는 기사·북마크·메모·태그를 복원할 수 없다. 수동 백업의 DB 포함 옵션과 cloud ZIP 기능은 존재하므로 “DB 백업 기능 전체가 없다”는 의미는 아니다.

README가 자동으로 DB와 설정을 함께 보관한다고 약속하므로 우선 제품 계약을 정해야 한다. 실제 DB 자동 백업을 제공한다면 worker/주기/보존 정책을 포함해 구현하고, 설정 전용이 의도라면 UI와 문서에서 보호 범위를 분명히 표시해야 한다. 회귀 테스트는 타이머 callback 이후 백업 metadata의 `include_db`뿐 아니라 실제 DB payload와 복원한 메모/태그를 확인해야 한다.

### [GAP-002] Confirmed Gap — 예약 백업 실패가 사용자 상태로 전달되지 않는다

**해결:** 마지막 시도·성공 시각·DB 포함 여부·오류를 `backups/auto_backup_status.json`에 원자적으로 저장한다. 백업 창에서 상태를 확인하고 같은 실패 알림은 시간당 한 번으로 제한한다. 성공 후에는 알림 상태를 초기화하며 종료 중에는 UI 알림을 보내지 않는다. 아래 내용은 초기 발견 근거다.

같은 `_run_auto_backup_once`는 `create_backup`의 `None` 결과와 `last_create_error`를 소비하지 않는다. 예외가 아닌 자체 검증 실패도 core log에만 남는다. 오류를 일으키는 새 버그로 집계하지 않았지만, ISSUE-001 및 GAP-001을 사용자가 알아채기 어렵게 한다. 마지막 성공 시각·백업 범위·최근 실패 이유를 설정/백업 창에서 확인할 수 있도록 하고 반복 알림은 제한하는 방향을 권한다.

### [GAP-003] 추정 — PC 시계 차이/동률에 대한 충돌 정책 검증 보완

**보완 완료 / 제약 명시:** read/bookmark/note/delete/tag/content의 동률을 결정적으로 처리하고 양방향 수렴을 검증했다. 큰 시각 차이는 기존의 timestamp 우선 정책을 따르며 실제 인과관계를 추론하지 못한다. 과거 snapshot의 단순 지연을 시계 오류로 오판하지 않고, 미래 시각이 30분 이상 차이 날 때 UI에서 시계 확인을 안내한다. README에도 한계를 명시했다.

상태 병합은 `updated_at > local_updated_at` 비교를 사용한다. 시계가 크게 다른 PC나 같은 시각의 상충 편집에 대해 양방향 수렴 정책이 충분한지는 실측하지 않았다. 정상적인 최신 편집 보호 자체를 버그로 간주하지 않는다. 시계 오차/동률 입력 테스트 후 필요하면 결정적인 tie-break와 충돌 안내를 설계한다.

## 6. Documentation Mismatches

1. **해결된 불일치:** 초기 `_run_auto_backup_once`는 `include_db=False`였으나 현재 background worker가 DB + 설정을 저장한다. README와 백업 창 안내를 현재 동작에 맞췄고 예전 설정 전용 백업의 복원 한계도 표시했다.
2. **확인 범위 내 일치:** CLAUDE/AGENTS의 entrypoint, DB facade, API HUB URL/헤더, canonical scope, GUI relay, scoped duplicate 재계산, tombstone 보존, FTS 비사용 방향은 확인한 코드 및 회귀 테스트와 대체로 맞는다. README의 Windows 지원 범위와 데이터 기본 경로도 맞는다.
3. README의 미검증 Python 3.10+ 안내를 Windows x64/Python 3.14 권장 및 기타 버전 별도 검증으로 바꿨다. quality/release workflow도 x64를 명시한다.

## 7. Recommended Fix Plan

### Phase 1 — Immediate

1. **ISSUE-001:** 실패본으로 정상 복구본을 pruning하지 않도록 보존 불변조건부터 수정한다. 자동/수동 quota 경계와 연속 실패를 회귀 기준으로 삼는다.
2. **GAP-001/002:** DB 자동 백업 제공 여부를 명확히 하고 README/UI와 실제 동작을 맞춘다. 당장 사용자가 설정 전용 백업을 DB 복구본으로 믿지 않게 한다. 마지막 백업 결과/범위를 노출한다.
3. **ISSUE-002/003:** cloud merge에서 빈 태그 상태를 전파하고, 콘텐츠 최신성 및 날짜 쌍 선택 정책을 수정한다. 배포 전 두 PC 왕복 동기화로 확인한다.

### Phase 2 — Stability

- 병합 preview와 실제 변경 수의 의미를 맞추고, 태그 전체 삭제·콘텐츠 정정·역순 ZIP 도착 테스트를 추가한다.
- 파일 접근 거부·디스크 부족·WAL 활성·백업 검증 실패·앱 종료 중 sync에 대해 정상 복구본과 원본 데이터가 유지되는지 검사한다.
- 고정 의존성의 Windows x64/Python 3.14 CI와 frozen smoke 결과를 릴리스 기준으로 유지한다. 실제 API smoke는 별도 credential opt-in job으로 관리한다.

### Phase 3 — Structural

- 클라우드 preview/실제 적용에 공통의 변경 후보·최신성 규칙을 두어 빈 상태와 tie-break가 갈라지지 않게 한다.
- 정상 백업 rotation과 손상본 격리를 분리하고, 파일 삭제를 가로채 불변조건을 검증할 수 있게 유지한다.
- 현재 facade/mixin 호환성을 지키면서 기능 계약을 테스트한다. 이번 발견을 이유로 대규모 재구성이나 FTS 재활성화를 먼저 할 필요는 없다.

위 코드 개선과 공통 정책 분리는 적용했다. CI에 credentialed API smoke용 수동 opt-in job을 추가했으나 실행하거나 secret을 설정하지 않았다. 실제 NAS/외부 동기화 서비스, 전원 차단, 고정 의존성 Windows x64 job의 실행 결과는 로컬에서 대체하지 않는다.

## 8. Test Recommendations

아래는 감사 시 제안한 검증 조건이다. 새 `test_audit_cloud_backup_regressions.py`, `test_auto_backup_runtime.py`와 기존 전체 suite로 로컬 조건을 검증했다. 실제 API/동기화 서비스 및 x64 배포 환경은 실행하지 않았으며 권고로 남는다.

| 종류 | 입력/조건 | 기대 결과 |
|---|---|---|
| Unit / Regression: ISSUE-001 | 정상 자동 5개/수동 20개 + 자체 검증 실패 1회 및 반복 | 정상본 삭제 요청 0회, 정상본 hash/개수 유지, 실패 이유 제공 |
| Integration: 백업 정상 rotation | quota가 찬 상태에서 검증된 정상 신규 백업 | 오래된 정상본만 정책대로 교체, 최소 정상 복구본 유지 |
| Integration / E2E: GAP-001 | 타이머 tick 전 기사·북마크·10,000자 메모·태그 저장 → 백업을 새 임시 경로로 복원 | DB 자동 백업 계약을 선택했다면 모든 상태 일치. 설정 전용 계약이면 UI에 DB 미포함 명시 |
| Integration / Regression: ISSUE-002 | A→B 태그 `['x']` → A에서 `[]` → B import → B→A 왕복 | 두 PC 모두 빈 태그, 최신 tag state 유지, preview와 적용 변경 수 일치 |
| Unit: 태그 최신성 | B에 더 최신 `['y']`, A의 이전 빈 태그 상태 import | B의 `['y']` 유지, 동일 snapshot 재적용은 변화 없음 |
| Integration / Regression: ISSUE-003 | B의 새 제목/요약/날짜 후 A의 예전 ZIP 도착 | 새 콘텐츠 유지, 날짜 문자열/ts와 title/hash가 같은 버전을 표현 |
| Concurrency: 두 PC/순서 역전 | 동일 link의 상태를 A/B에서 상충 편집, ZIP을 AB/BA 순서로 적용, 시계 skew/동률 포함 | 문서화된 충돌 정책에 따라 수렴하며 메모/태그가 조용히 사라지지 않음 |
| Concurrency: refresh와 유지보수 | 느린 API 요청 중 sync/CSV import 시작 및 탭 rename/close | maintenance/cleanup guard대로 거절/대기, stale callback이 바뀐 탭을 오염시키지 않음 |
| E2E: 수집·재시도·페이지 | mock HTTP 401/403/429/5xx/timeout/잘못된 JSON, 이후 성공 및 API 끝 페이지 | 적절한 오류/제한 상태, 중복 저장 없음, cursor는 성공 계약대로만 전진, UI 복구 |
| E2E: 필터·export·badge | 같은 기사를 여러 탭에 공유, 읽음/북마크/중복/태그/기간 필터 후 CSV/Markdown/JSON export | 표시 범위와 count/export 일치, 관련 unread/badge 갱신, 취소 시 기존 출력 보존 |
| Integration: 복구 | 손상 설정+정상 `.backup`, 잘못된 pending restore, 파일 교체 중 예외 | 정상 fallback/rollback, 원본 유지, 실패를 성공으로 보고하지 않음 |
| Platform-specific: Windows | 한글/공백/긴 경로, junction, access denied, WAL 사용 중, 실행 파일 잠금 | 경로 containment 유지, 복원/업데이트 실패 시 원본·복구본 보존, 사용자 오류 표시 |
| Platform-specific: 배포 | Windows x64/Python 3.14 + requirements-build 고정 버전으로 clean build | source/frozen smoke 및 전체 suite 통과, QtNetwork/crypto import 성공 |
| External integration | opt-in NAVER API HUB 실제 인증/뉴스 응답 및 실제 NAS/동기화 폴더 지연 | timeout/인증 오류 전달, 부분 도착 ZIP 재시도/격리 정책 정상, 이중 병합 없음 |

기존 테스트 파일 중 `test_cloud_sync.py`, `test_backup_collision_and_restore.py`, `test_stabilization_round1.py`, `test_shared_title_updates.py`, `test_shutdown_cleanup.py` 등을 확장하는 것이 자연스럽다. 공유 기사 upsert 회귀가 통과해도 **클라우드의 오래된 콘텐츠 병합**은 별도 경로이므로 독립 조건이 필요하다.

## 9. Final Assessment

### 개선 후 최종 검증

| 검사 | 실제 결과 |
|---|---|
| 전체 `python -m pytest -q -ra` (`QT_QPA_PLATFORM=offscreen`) | **541 passed, 1 skipped, 7 warnings, 14 subtests passed**, 50.12초 |
| `python -m pyright` | **0 errors, 0 warnings, 0 informations** |
| `python news_scraper_pro.py --smoke` | 격리 UI/DB 시작·종료 성공 |
| `python -m PyInstaller --noconfirm --clean news_scraper_pro.spec` 및 최종 변경 반영 재빌드 | 성공, `dist/NewsScraperPro_Safe.exe` 생성 |
| 최종 EXE를 Hidden으로 실행한 `--smoke` | **exit 0**, 실제 사용자 데이터와 분리된 임시 runtime 사용 |
| 외부 검증 | 실제 NAVER 인증 테스트 1개 skip, GitHub Actions의 x64/고정 의존성 job 및 실제 NAS 동기화 미실행 |

독립 회귀 테스트 28개를 추가했다. 기존 sidecar 복사 fallback 테스트는 변경한 안전성 계약(백업 실패·원본 sidecar 보존)을 검증하도록 갱신했다. 빌드 산출물은 **검증 머신의 ARM64/Python 3.15 환경용**이며 x64 릴리스 파일로 간주하면 안 된다. 새 의존성 설치, 실제 업데이트 설치, 사용자 데이터 복원, 게시/배포는 수행하지 않았다.

| 항목 | 평가 | 근거 |
|---|---|---|
| Functional Correctness | Acceptable | 초기 결함 3건을 수정하고 독립 회귀 테스트 추가 |
| Runtime Stability | Acceptable | 전체 suite·정적 분석·격리 시작/종료 및 backup background/중복/종료 대기 검증 |
| Data Integrity | Acceptable | 정상 백업 보존, WAL snapshot, 빈 태그와 콘텐츠 일관성·실패 rollback 검증. 외부 장애 보증은 아님 |
| Error Resilience | Acceptable | 백업 실패 시 정상본 유지, 상태 영속화·제한된 GUI 알림, 기존 API/DB 오류 방어 유지 |
| Cross-platform Robustness | Acceptable | Windows 목적에 맞는 구현/검사 존재. 이번 ARM64 source 검증은 x64 릴리스나 Linux/macOS 보증이 아님 |
| Test Confidence | Acceptable | 새 회귀와 기존 전체 suite 통과. credentialed API skip 및 x64 기준 환경 차이는 남음 |

**우선 수정한 문제 3개:**

1. **ISSUE-001 — 실패한 신규 백업으로 정상 복구본이 삭제되지 않게 수정했다.**
2. **ISSUE-002 — 마지막 태그 삭제와 빈 태그 timestamp를 클라우드 양쪽에 전달한다.**
3. **ISSUE-003 — 오래된 스냅샷의 최신 기사 덮어쓰기를 막고 날짜/hash를 정규화했다.**

GAP-001/002도 DB 포함 background backup과 결과 표시로 해결했다. 남은 외부 검증 조건을 코드 수정 완료와 혼동하지 않는다.
