# Update History

## v32.10.0 (2026-09-22)

### 사용하지 않는 검색 범위 정리

- 닫은 탭이 남긴 검색 범위의 소속 정보를 통계 화면(`관리 → 통계 → 저장소`)에서 미리보기 후 정리할 수 있습니다.
- 열린 탭의 범위와 공유 기사는 그대로 두며, 정리 후 소속이 없어진 기사의 본문·읽음·북마크·메모·태그는 보관함에 유지됩니다.
- 삭제 기록(휴지통) 기사의 소속은 건드리지 않으며, 남은 범위의 중복 표시는 스코프 한정 재계산으로 정확히 유지됩니다.
- 수집 실행 중이거나 유지보수 중에는 정리가 거부되고 사유가 안내됩니다.

### 업데이트 안정성

- 업데이트 다운로드 후 설치 확인에 "예"를 눌러도 프로그램이 다시 열리지 않던 문제를 수정했습니다. (Windows 종료 대기 방식을 프로세스 핸들 기반으로 변경)
- "업데이트 발견" 팝업의 버튼 글자가 잘릴 수 있던 문제를 수정했습니다. (버튼 최소 너비 보장)

## v32.9.0 (2026-09-20)

### 감사 후속: 아카이브 확장성·삭제 기록 회수

- 기사 1건 삭제가 아카이브 전체의 중복 플래그를 UI 스레드에서 재계산하던 문제를 수정했습니다. 영향받는 검색 범위만 재계산하며, 12만 행 기준 0.80초에서 0.2ms로 줄었습니다.
- 삭제한 기사를 복구할 때 중복 플래그가 갱신되지 않아 같은 제목의 다른 기사에 잘못된 값이 남던 문제를 수정했습니다.
- 매 실행마다 실행되던 keyword membership backfill과 전체 중복 재계산을 스키마 변경 시 1회만 수행하도록 바꿨습니다.
- 정상 종료 여부를 기록해 평시에는 `PRAGMA quick_check`만 수행하고, 비정상 종료 이후에만 전체 `integrity_check`로 확대합니다. 12만 건 기준 시작 시간이 2.3초에서 0.4초로 줄었습니다.
- DB 준비 중 스플래시를 표시해 창이 뜨기 전 무반응 구간을 없앴습니다.
- 목록에서 삭제한 기사(삭제 기록)가 어떤 정리 작업으로도 회수되지 않던 문제를 수정했습니다. 설정에 **삭제 기록 보존** 기간(기본 90일)을 추가했고, 기간이 지난 기록은 데이터 정리에서 실제로 제거됩니다. 정리 실행 전 몇 건이 회수·유지되는지 안내합니다.
- 통계 화면에 `💾 저장소` 항목(DB 크기, 보관 기사, 삭제 기록, 검색 범위 행/수)을 추가했습니다.

### 안정성·호환성

- 어떤 검색 경로도 사용하지 않는 FTS5 인덱스의 백그라운드 backfill을 기본 비활성화했습니다. 스키마는 유지되며 `NEWS_SCRAPER_ENABLE_FTS_BACKFILL=1`로 다시 켤 수 있습니다.
- 설정 내보내기를 다른 모든 파일 쓰기와 동일한 원자적 쓰기로 통일했습니다.
- 비상 DB 연결 상한 검사의 경합을 제거해 동시 요청에서도 상한을 초과하지 않습니다.
- Markdown 내보내기에서 제목의 대괄호와 URL의 괄호가 링크를 깨뜨리지 않도록 이스케이프합니다.
- 백업 경로 검사에 `realpath` 확인을 추가해 백업 폴더 안의 junction이 삭제 대상을 밖으로 돌리지 못하게 했습니다.

### 문서·테스트

- PyQt6/cryptography가 없는 환경에서 테스트 수집이 전체 중단되던 문제를 수정했습니다. 해당 모듈은 이제 skip 처리되고 이유가 요약에 표시됩니다.
- 전체 재계산 API를 `_recalculate_duplicate_flags_for_entire_database`로 이름을 바꿔 per-article/startup 경로에서의 오용을 막았습니다.
- 위 수정에 대한 회귀 테스트 21건을 추가했습니다(비용 회귀 포함).
- README의 "FTS 전문 검색 인덱싱 지원" 문구를 실제 동작에 맞게 정정하고, 누락된 `LICENSE` 파일을 추가했습니다.

## v32.8.0 (2026-08-23)

### 감사 후속 안정성 강화

- 클라우드 snapshot의 구조적 손상과 일시적 DB/파일 오류를 분리해 유효한 원본이 자동 격리되는 문제를 수정하고, 격리 목록·재검증·복구·삭제 기능을 추가했습니다.
- 실행 중인 DB-writing worker의 단순 분리를 종료로 간주하지 않아 유지보수 작업과 fetch가 겹치지 않도록 했습니다.
- CSV formula를 중화하고 bookmark/note 가져오기를 기사 단위 transaction으로 묶었으며, 변경 없음·누락·실패·부분 반영 위치를 보고합니다.
- 검증된 Windows/Python 3.14 dependency contract와 QtNetwork/entrypoint CI smoke를 추가하고 runtime 파일명 문서를 실제 상수와 일치시켰습니다.

## v32.7.9 (2026-08-16)

### Update Check Feedback Fix

- Fixed the GitHub Release update button passing Qt's `clicked(bool)` value as the `interactive` argument. Manual checks now always show progress and a latest-version, update, or error message.

이 파일은 현재 릴리스에서 유지해야 할 변경 요약만 기록합니다. 과거 날짜별 누적 로그는 문서 본문에서 제거했으며, 필요하면 Git history와 이전 태그를 기준으로 확인합니다.

## v32.7.8 (2026-08-16)

### GitHub Release 자동 업데이트

- GitHub Release의 서명된 매니페스트를 검증해 업데이트를 확인하고, SHA-256·파일 크기 검증 뒤 안전하게 설치합니다.
- 설치 전 기존 종료 경로로 worker·DB·설정을 정리하며, 별도 helper가 실행 파일을 교체하고 smoke 점검 실패 시 이전 버전으로 복구합니다.
- 설치 성공/실패/복구 결과는 다음 실행에서 안내하고, 오래된 staging/helper 파일은 정리합니다.
- 태그 기반 GitHub Actions workflow와 `NEWS_SCRAPER_UPDATE_PRIVATE_KEY_B64` repository secret을 통해 Release와 매니페스트 발행을 자동화합니다.

### Validation

- `python -m pytest -q` => `404 passed`, 7 warnings, 5 subtests passed
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`
- `python -m PyInstaller --noconfirm --clean news_scraper_pro.spec` => 성공

## v32.7.7 (2026-08-14)

### Resource Management & Reliability (PROJECT_AUDIT)

- `ApiWorker`의 `requests.Session` 수명주기 관리를 강화하여 정상 완료/오류/취소 시 무조건 세션을 닫도록(`session.close()`) 보장했습니다.
- 네이버 뉴스 검색 API 1,000건 페이징 한계 도달 시 사용자 안내 대화상자를 통해 페이징 커서를 1페이지로 즉시 초기화할 수 있는 UX를 구현했습니다.
- 탭 컨텍스트 메뉴에 `⏮ 페이징 커서 초기화` 액션 및 `reset_tab_fetch_cursor` 메서드를 추가했습니다.
- 단일 인스턴스 잠금 충돌 시 무한 루프 대신 최대 3회 재시도 제한 및 안전 종료 안내를 적용했습니다.
- 클라우드 동기화 스냅샷 가져오기 시 30분 이상의 시간 오차를 감지하는 Clock Skew 경고 로직을 추가했습니다.

### Features & Export

- 기사 데이터 내보내기에 **JSON 형식(`*.json`)** 지원을 추가했습니다 (`export_items_to_json`, `export_scope_to_json`).
- 대용량 데이터 JSON 내보내기를 백그라운드 워커에서 원자적으로 처리합니다.

### Tests

- `tests/test_api_worker_session_lifecycle.py` (신규): `ApiWorker` 세션 수명주기 및 정상/오류/비소유 세션 정리 검증.
- `tests/test_json_export.py` (신규): 기사 목록 및 쿼리 스쿱의 JSON 파일 내보내기 검증.

### Validation

- `python -m pytest -q` => `393 passed`, 7 warnings, 5 subtests passed
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`

## v32.7.6 (2026-07-16)

### NAVER API HUB 이관

- 뉴스 검색 호출을 레거시 Developers Center(`openapi.naver.com`, `X-Naver-Client-*`)에서 **NAVER API HUB**로 전환했습니다.
- 신규 엔드포인트: `https://naverapihub.apigw.ntruss.com/search/v1/news`
- 인증 헤더: `X-NCP-APIGW-API-KEY-ID` / `X-NCP-APIGW-API-KEY`
- 공통 모듈 `core/naver_api.py` 추가 (`naver_auth_headers`, `parse_naver_api_error`, `format_naver_http_error`)
- `ApiWorker`와 설정 화면 API 키 검증이 동일 URL/헤더/오류 파서를 사용합니다.
- Search API 평면 오류와 API Gateway 중첩 오류를 모두 파싱합니다. 401/403은 `auth_error`로 안내합니다.
- 설정 UI/도움말/첫 실행 안내를 API HUB 발급 기준으로 갱신했습니다.
- **기존 네이버 개발자센터 키는 더 이상 동작하지 않습니다.** NCP 콘솔에서 API HUB Application을 등록하고 새 키를 입력해야 합니다.

### Docs

- README, claude.md, gemini.md, project_structure_analysis.md를 API HUB 기준으로 전면 갱신했습니다.

### Tests

- `tests/test_naver_api_hub.py` (신규): URL/헤더/오류 파싱 계약
- `tests/test_settings_validation_http_policy.py` (보강): API HUB URL·헤더·Gateway nested error

### Validation

- `python -m pytest -q` => `388 passed`, 7 warnings, 5 subtests passed
- `python -m pyright` => `0 errors`

## v32.7.5 (2026-07-11)

### PROJECT_AUDIT Follow-up (3.1~3.5)

- `HttpClientConfig.user_agent`를 `core.constants.VERSION`에서 자동 파생하도록 변경 (3.1). 구버전 `32.7.3` 하드코딩 제거.
- cloud snapshot 병합/프리뷰(`merge_cloud_snapshot_db`, `preview_cloud_snapshot_db`)에 빈 `snapshot_id` 거부 가드 추가 (3.3, defense-in-depth). README 클라우드 동기화 절에 same-machine 스킵·빈 id 거부 정책 명시.
- `_check_integrity`의 예외 필터를 `except Exception`으로 넓혀 처리 일관성 확보 (3.4). 연결 누출은 기존 `finally` 가드로 이미 방어됨.
- `cleanup_worker()` timeout 누적 5회 도달 시 최초 1회 재시작 권장 안내(status bar + warning toast) 추가 (3.5). `_worker_cleanup_diag_shown` 플래그로 중복 방지.

### Tests

- `tests/test_http_client_user_agent_version.py` (신규): User-Agent가 VERSION과 일치 + 세션 헤더 전파.
- `tests/test_retain_qthread_until_finished.py` (신규): `_DETACHED_WORKERS` 등록·해제·즉시 release·None no-op 검증.
- `tests/test_cloud_snapshot_empty_id_quarantine.py` (신규): 빈/whitespace snapshot_id 거부 (manifest + merge/preview).
- `tests/test_integrity_check_unexpected_exception.py` (신규): RuntimeError/ValueError 등도 `unreadable` 처리.
- `tests/test_fetch_cooldown.py` (보강): cleanup timeout 임계치 도달 진단 알림 트리거, 중복 방지, 미만 미표시.

### Validation

- `python -m pytest -q` => `381 passed`, 7 warnings, 5 subtests passed
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`

## v32.7.4 (2026-06-25)

### Audit Follow-up (PROJECT_AUDIT.md)

- Worker cleanup timeout 시 `force` detach로 탭 닫기/이름 변경/유지보수가 막히지 않도록 복구 경로를 추가했습니다.
- `DatabaseConnectionError`와 `db_pool_exhausted` 오류 종류로 DB 연결 풀 고갈을 사용자에게 명확히 표시합니다.
- DB 시작 시 integrity unreadable 상태에 대해 짧은 재시도(backoff)와 시작 안내 토스트를 추가했습니다.
- 비-Windows 환경에서 API secret 평문 저장 시 경고를 표시합니다.
- `request_id=None` fetch 콜백은 stale로 거부하고, 레거시 `self.workers` dict를 `WorkerRegistry` 단일 추적으로 정리했습니다.

### Validation

- `python -m pytest -q` => `360 passed`, 7 warnings, 5 subtests passed
- `python -m pyright` => `0 errors`

## v32.7.3 (2026-06-10)

### Current State

- Python 3.14, PyQt6, SQLite, requests, PyInstaller onefile 기준입니다.
- `news_scraper_pro.py`는 실행 진입점과 legacy re-export를 유지합니다.
- `core.database.DatabaseManager`, `core.workers`, `ui.main_window.MainApp`, `ui.news_tab.NewsTab` facade 경로는 호환성을 위해 유지합니다.
- 내부 구현은 `core/*_support`와 `ui/*_support` 패키지로 분리되어 있습니다.

### UI

- 메인 툴바의 `통계`, `태그`, `규칙`, `Alias` 버튼을 `관리` 드롭다운 메뉴로 통합했습니다.
- 좁은 창에서도 상단 툴바가 과도하게 길어지지 않도록 보조 관리 기능을 별도 메뉴로 분류했습니다.

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
- `python -m pytest -q` => `339 passed, 7 warnings, 5 subtests passed`
- `python -m pyright` => `0 errors, 0 warnings, 0 informations`
- `python -m PyInstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)
- Temp DB benchmark: initial detailed upsert `833.44ms`, repeated identical detailed upsert `169.46ms`, `count_news_states` `6.44ms`, first page fetch `9.99ms`, offset-1000 fetch `17.66ms`

## Earlier Versions

이전 버전의 상세 변경 로그는 저장소 이력에 보존되어 있습니다. 현재 문서는 유지보수자가 실제 코드 구조, 공개 API, 검증 계약을 빠르게 확인하는 것을 우선합니다.
