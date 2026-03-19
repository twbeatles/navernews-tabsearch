# 뉴스 스크래퍼 Pro v32.7.2

네이버 뉴스 검색 API를 기반으로 동작하는 탭형 뉴스 수집/관리 도구입니다.

## 문서 인코딩

이 문서는 UTF-8로 작성되어 있습니다.

## 개발/검증 기준

- 개발/정적 분석 기준: Windows, Python 3.14, PyQt6
- 소스 실행 최소 기준: Python 3.10+
- 품질 게이트: `pyright`(`pyrightconfig.json`) + `pytest -q`

## 주요 기능

- 탭 기반 키워드 검색 및 독립 관리
- 같은 첫 키워드를 공유해도 전체 검색 의미(`query_key`) 기준으로 탭 범위 분리
- 같은 `canonical query` 탭은 중복 생성하지 않고 기존 탭으로 이동
- 제외어(`-키워드`)와 날짜 조건을 포함한 고급 검색
- 자동 새로고침(10분~6시간) 및 수동 전체 새로고침
- 기사 북마크/읽음 처리/메모 작성
- 열린 탭/북마크 탭 사이의 기사 상태 즉시 동기화
- 알림 키워드는 이번 fetch에서 새로 추가된 기사에만 적용
- 현재 표시 결과 CSV 내보내기
- 키워드 그룹 관리
- 시스템 트레이 동작(최소화/닫기 동작 커스터마이징)
- 단일 인스턴스 실행 보장(중복 실행 방지)
- 설정 자동 백업 + 수동 DB 포함 백업 및 재시작 적용형 복원(pending restore)

## 안정화 포인트 (v32.7.2+ 작업 브랜치 반영)

- 시작 시 단일 인스턴스 가드 적용
- 설정 반영 누락 보완(`sound_enabled`, `api_timeout`)
- 설정 창의 API 키 검증/정리 작업 비동기 처리
- 설정 가져오기 시 탭 중복 병합(dedupe) 강화
- 자동 시작 최소화 옵션 변경 시 레지스트리 재등록
- 자동 새로고침 조기 종료 경로에서 락 플래그 복구 보장
- 탭 이름 변경 후 `더 불러오기`가 최신 탭 키워드를 사용하도록 보정
- 제외어-only(예: `-광고 -코인`) 탭 입력 차단
- `keyword_groups` 저장 위치를 `news_scraper_config.json`으로 일원화(레거시 마이그레이션 지원)
- 최소화 시 트레이 동작(`minimize_to_tray`) 실제 반영
- 자동 새로고침 간격을 `2시간` 기준으로 정렬
- 설정 가져오기 정규화(타입/범위 보정) + 보정 항목 로그/알림
- 설정 가져오기 시 `keyword_groups`를 덮어쓰기 대신 병합+중복 제거로 처리
- 탭 리네임 시 fetch key 변경 여부에 따라 페이지네이션 상태를 안전하게 재설정
- `모두 읽음`을 `현재 표시 결과만`/`탭 전체` 2모드로 확장
- 통계의 `중복 기사` 집계를 `news_keywords.is_duplicate` 기준으로 보정
- 기사 단건/일괄 삭제 후 `news_keywords.is_duplicate`를 영향 집합 기준으로 재계산
- 컨텍스트 메뉴 삭제를 raw SQL에서 `DatabaseManager.delete_link(link)`로 일원화
- pending restore에서 `restore_db=true`인 경우 DB 백업 파일 누락 시 실패 처리 + pending 유지
- 설정 로드 정규화 강화(`theme_index`, `refresh_interval_index`, `api_timeout`, bool 계열, `alert_keywords`)
- fetch key 커서 영속화(`pagination_state`) 및 `더 불러오기` DB 건수 fallback 제거
- `pagination_totals`를 추가 저장해 재시작/필터 변경 후에도 `더 불러오기` 상태 복원
- 단일 인스턴스 stale lock 복구(`notify -> stale 제거 -> 재시도`) 및 상태 로깅 강화
- 트레이 미지원 환경에서 `--minimized`/`start_minimized` 요청 시 숨김 시작 차단
- 검색어 정책 분리: API 검색어(`parse_search_query`)와 대표 키워드(`parse_tab_query`)를 분리하고 실제 탭 범위는 `query_key`로 판정
- `news_keywords`를 `(link, query_key)` 기준으로 마이그레이션해 멀티 키워드 탭을 독립 범위로 조회/분석/배지 집계
- 설정 창 닫힘 시 백그라운드 워커 정리(콜백 안전 가드)
- PyInstaller spec 동기화: `PyQt6.QtNetwork` 포함 보장(단일 인스턴스 IPC 런타임 안정화)
- 백업 복원 예약 시 백업 메타(`include_db`) 기반으로 `설정만`/`설정+DB` 범위를 자동 판별
- 기사 `열기`/`안읽음` 처리에서 DB 반영 실패 시 UI 캐시를 갱신하지 않도록 동기화 보강
- 설정 창 워커 종료 경로 강화(종료 대기 초과 시 수명 분리 정리)
- 탭 배지 미읽음 집계를 제외어 조건까지 반영하도록 보정
- 시작 시 생성되는 자동 백업을 `auto` 메타로 구분하고 수동 백업과 보존 정책을 분리
- 백업 목록에서 마이크로초 타임스탬프를 정상 표시하고 `자동`/`수동` 출처를 함께 표기
- 설정 창의 데이터 정리/전체 삭제 완료 후 열린 탭/북마크/배지/트레이 툴팁을 즉시 동기화
- `모두 읽음 -> 탭 전체`가 제외어(`exclude_words`)를 포함한 현재 탭 의미를 유지하도록 보정
- 언론사 분석이 탭의 제외어 조건까지 반영하도록 집계 경로를 확장
- 탭 닫기/리네임 시 활성 fetch 워커를 먼저 정리하여 stale 콜백 반영을 방지
- 탭 타이틀 구성(아이콘+배지)을 `_format_tab_title(...)`로 일원화
- pending restore 적용을 스테이징+롤백 방식으로 전환하여 부분 적용을 방지
- 즉시 복원 API(`restore_backup`)와 startup pending restore가 동일한 원자적 restore helper를 사용
- 손상된 백업 메타(`backup_info.json`)가 있어도 정상 백업 항목은 계속 표시
- 손상 백업 항목은 UI에서 `손상됨`으로 표시하고 `삭제/무시` 선택 제공
- 설정의 `client_secret` 저장은 Windows에서 DPAPI 암호화(`client_secret_enc`) 우선 사용
- 설정 로드 실패 시 `news_scraper_config.json.backup` 자동 복구 fallback 지원
- 자동 정리(`delete_old_news`)는 `pubDate_ts <= 0` 레코드를 삭제 대상에서 제외
- 트레이 미읽음 수는 탭 캐시 합산 대신 DB 총계(`get_total_unread_count`) 기준으로 계산
- 트레이 미지원 환경에서도 `show_desktop_notification()`이 토스트 fallback + 알림음으로 동작
- `pyrightconfig.json`을 추가하고 `core.protocols`/`ui.protocols` 기반 타입 계약을 도입해 `pyright` 기준 0 errors를 유지
- UTF-8 인코딩 스모크 테스트를 리포지토리 주요 텍스트 자산 전체로 확장
- 단건 기사 상태 변경(`읽음/북마크/메모/삭제`) 시 열린 뉴스/북마크 탭 캐시를 `link` 기준으로 즉시 동기화
- `모두 읽음`/DB 유지보수 완료 후에는 열린 탭과 북마크 탭을 full refresh 경로로 재정렬해 정합성 보장
- 알림 키워드는 이번 fetch에서 실제로 새로 추가된 기사(`new_items`)에만 적용
- 탭 중복 방지, 설정 import dedupe, 검색 이력 dedupe를 `canonical query` 기준으로 통일
- CSV 내보내기는 현재 로드된 slice가 아니라 현재 탭 필터 조건 전체 결과를 DB에서 다시 조회해 저장
- 자동 시작 백업은 계속 `설정만` 대상으로 유지하고, UI/문서에서 DB 포함 수동 백업 필요성을 명시

## 프로젝트 구조

```text
navernews-tabsearch/
├── news_scraper_pro.py          # 엔트리포인트 + 호환 re-export 레이어
├── news_scraper_pro.spec        # PyInstaller 빌드 설정
├── pyrightconfig.json           # Pyright/Pylance 기준 설정 (Windows, Python 3.14)
├── pytest.ini                   # pytest 진입점/수집 경로 고정
├── core/                        # 코어 로직 패키지
│   ├── __init__.py
│   ├── bootstrap.py             # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py             # 경로/버전/앱 상수
│   ├── config_store.py          # 설정 스키마 정규화 + 원자 저장
│   ├── database.py              # DatabaseManager facade (연결 풀 수명 주기)
│   ├── _db_schema.py            # 스키마 초기화 / 무결성 검사 / 복구
│   ├── _db_duplicates.py        # 제목 해시 / 중복 플래그 재계산
│   ├── _db_queries.py           # 조회 / 개수 / 미읽음 집계
│   ├── _db_mutations.py         # upsert / 상태 변경 / 삭제 / 읽음 처리
│   ├── _db_analytics.py         # 통계 / 언론사 분석
│   ├── protocols.py             # lock/session capability Protocol 정의
│   ├── workers.py               # ApiWorker/DBWorker/AsyncJobWorker
│   ├── worker_registry.py       # WorkerHandle/WorkerRegistry (요청 ID 기반 관리)
│   ├── query_parser.py          # parse_tab_query/parse_search_query/build_fetch_key
│   ├── backup.py                # AutoBackup/apply_pending_restore_if_any
│   ├── backup_guard.py          # 리팩토링 백업 유틸리티
│   ├── startup.py               # StartupManager (Windows 자동 시작 레지스트리)
│   ├── keyword_groups.py        # KeywordGroupManager
│   ├── logging_setup.py         # configure_logging
│   ├── notifications.py         # NotificationSound
│   ├── text_utils.py            # TextUtils, parse_date_string, perf_timer, LRU 캐시
│   └── validation.py            # ValidationUtils
├── ui/                          # UI 로직 패키지
│   ├── __init__.py
│   ├── main_window.py           # MainApp facade / composition root
│   ├── _main_window_tabs.py     # 탭 추가/닫기/리네임/그룹 연결
│   ├── _main_window_fetch.py    # fetch orchestration / worker 수명 주기
│   ├── _main_window_settings_io.py # 설정 import/export / 유지보수 동기화
│   ├── _main_window_tray.py     # 트레이 / 종료 / closeEvent 처리
│   ├── _main_window_analysis.py # 통계 / 언론사 분석 UI
│   ├── news_tab.py              # NewsTab (개별 뉴스 탭)
│   ├── protocols.py             # 메인 윈도우/부모 capability Protocol 정의
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
│   ├── test_encoding_smoke.py
│   ├── test_entrypoint_bootstrap.py
│   ├── test_import_settings_dedupe.py
│   ├── test_import_settings_normalization.py
│   ├── test_pagination_state_persistence.py
│   ├── test_plan_regression.py
│   ├── test_pending_restore_strict.py
│   ├── test_query_parser_search_policy.py
│   ├── test_refactor_backup_guard.py
│   ├── test_refactor_compat.py
│   ├── test_settings_roundtrip.py
│   ├── test_single_instance_guard.py
│   ├── test_start_minimized_guard.py
│   ├── test_stability.py
│   ├── test_startup_registry_command.py
│   ├── test_symbol_resolution.py
│   ├── test_keyword_groups_storage.py
│   ├── test_risk_fixes.py
│   ├── test_worker_cancellation.py
│   ├── test_backup_collision_and_restore.py
│   ├── test_backup_restore_mode.py
│   ├── test_audit_followthrough.py
│   ├── test_load_more_total_guard.py
│   ├── test_news_tab_ext_read_policy.py
│   ├── test_settings_dialog_maintenance.py
│   └── test_version_history_guard.py
├── query_parser.py              # 호환 래퍼 (→ core.query_parser)
├── config_store.py              # 호환 래퍼 (→ core.config_store)
├── backup_manager.py            # 호환 래퍼 (→ core.backup)
├── worker_registry.py           # 호환 래퍼 (→ core.worker_registry)
├── workers.py                   # 호환 래퍼 (→ core.workers)
├── database_manager.py          # 호환 래퍼 (→ core.database)
├── styles.py                    # 호환 래퍼 (→ ui.styles)
├── backups/                     # 백업 디렉터리
└── dist/                        # PyInstaller 빌드 결과물
```

## 실행 방법

### 1) 패키징된 실행 파일 사용

- `dist/NewsScraperPro_Safe.exe`를 바로 실행합니다.

### 2) 소스 코드 실행

```bash
pip install PyQt6 requests
python news_scraper_pro.py
```

## 테스트 실행

기본 권장 명령:

```bash
python -m pytest -q
```

`pytest.ini`가 추가되어 아래 명령도 동일하게 수집/실행됩니다.

```bash
pytest -q
```

정적 타입 검사는 아래 명령을 사용합니다.

```bash
pyright
```

참고:
- `pyrightconfig.json`은 루트 Python 파일, `core/`, `ui/`, `tests/`를 검사 대상으로 고정합니다.
- `tests/test_encoding_smoke.py`는 저장소 주요 텍스트 자산(`.py`, `.md`, `.json`, `.ini`, `.spec`, `.txt`, `.yml`, `.yaml`)의 UTF-8 decode 실패, `\ufffd`, 알려진 깨진 토큰 재등장을 함께 감시합니다.
- facade 공개 경로(`ui.main_window.MainApp`, `core.database.DatabaseManager`, `ui.settings_dialog.SettingsDialog`)는 유지하고, 내부 구현만 private helper module로 분리했습니다.

## PyInstaller 빌드 (onefile)

현재 스펙(`news_scraper_pro.spec`)은 onefile 기준으로 구성되어 있습니다.

```bash
pyinstaller --noconfirm --clean news_scraper_pro.spec
```

- 산출물: `dist/NewsScraperPro_Safe.exe`
- 아이콘 리소스: `news_icon.ico` 포함 (`news_icon.png`는 존재할 경우 fallback으로 함께 번들)
- v32.7.2 핵심 안정화 1차(2026-02-25)는 런타임 로직/스키마 변경만 포함하며 `.spec` 추가 수정은 필요하지 않습니다.
- v32.7.2 핵심+테스트 보강 2차(2026-02-28)도 런타임/테스트/문서 변경만 포함하며 `.spec` 수정은 필요하지 않습니다.
- v32.7.2 감사 반영(2026-03-02)에서는 단일 인스턴스 IPC(`QLocalServer/QLocalSocket`) 경로 보호를 위해 `PyQt6.QtNetwork`를 `.spec`에 명시 반영했습니다.
- v32.7.2 감사 후속(2026-03-03)에서는 requests optional 경로와 정합성을 맞추기 위해 `.spec`의 강제 hidden import에서 `chardet`를 제거했습니다.
- v32.7.2 감사 후속 2차(2026-03-06)에서는 백업 정책/탭 의미 보존/문서 정합성 보강만 포함하며 `.spec` 추가 수정은 필요하지 않습니다.
- v32.7.2 감사 후속 3차(2026-03-07)에서도 `.spec`을 재검토했으며, DPAPI 비밀값 저장 전환은 표준 라이브러리 기반(`ctypes`, `base64`)이라 추가 hidden import 수정이 필요하지 않습니다.
- v32.7.2 타입/인코딩 정리(2026-03-09)에서는 개발용 `pyrightconfig.json`, 문서, `.gitignore`만 동기화했으며 `.spec` 추가 수정은 필요하지 않습니다.
- v32.7.2 감사 후속 4차(2026-03-14)에서도 `.spec`을 다시 재검토했으며, `query_key` 범위화, `pagination_totals`, restore helper 공통화, export/import 1.1 확대는 기존 번들 의존성만 사용하므로 추가 hidden import 수정이 필요하지 않습니다.
- v32.7.2 감사 후속 5차(2026-03-16)에서도 `.spec`을 다시 재검토했으며, 열린 탭 동기화/가시 결과 CSV/canonical dedupe/신규 기사 알림 분리는 기존 번들 의존성만 사용하므로 추가 hidden import 수정이 필요하지 않습니다.
- v32.7.2 실행형 리스크 전면 수정(2026-03-18)에서도 `.spec`을 다시 재검토했으며, 유지보수 모드, DB 기반 로컬 페이지네이션, 백업 복원 가능 메타, export/import 1.2는 기존 번들 의존성만 사용하므로 추가 hidden import 수정이 필요하지 않습니다.

## 네이버 API 키 설정

1. 네이버 개발자센터에서 애플리케이션을 등록합니다.
2. 검색(Search) API 권한을 활성화합니다.
3. 앱 실행 후 `설정(Ctrl+,)`에서 `Client ID`와 `Client Secret`을 입력합니다.

## 단축키

| 단축키 | 기능 |
|---|---|
| `Ctrl+R` / `F5` | 모든 탭 새로고침 |
| `Ctrl+T` | 새 탭 추가 |
| `Ctrl+W` | 현재 탭 닫기 |
| `Ctrl+F` | 검색/필터 포커스 |
| `Ctrl+S` | 현재 표시 결과 CSV 내보내기 |
| `Ctrl+,` | 설정 열기 |
| `Alt+1~9` | 탭 바로가기 |

## 데이터/설정 파일

앱은 실행 파일 기준 디렉터리(`APP_DIR`)에 아래 파일을 저장합니다.

- `news_scraper_config.json`
- `news_database.db`
- `news_scraper.log`
- `pending_restore.json`

참고:
- `keyword_groups`는 별도 파일이 아니라 `news_scraper_config.json` 내부 필드로 저장됩니다.
- `pagination_state`는 `fetch_key -> 마지막 API start index` 매핑이며, 필드가 없으면 기본값 `{}`로 로드됩니다.
- `pagination_state` 값은 `1..1000` 범위로 정규화됩니다.
- `pagination_totals`는 `fetch_key -> 마지막으로 확인한 API total` 매핑이며 `0`도 유효한 값으로 저장됩니다.
- `search_history`는 `canonical query` 기준으로 dedupe되며 공백/대소문자만 다른 변형은 별도 항목으로 누적되지 않습니다.
- 백업 복원 예약은 선택한 백업의 `include_db` 메타를 기준으로 복원 범위(`설정만`/`설정+DB`)를 자동 적용합니다.
- 백업 메타의 `trigger`는 `auto`/`manual` 값을 가지며, 자동 시작 백업은 수동 백업과 별도 보존 정책으로 관리됩니다.
- 자동 시작 백업은 `설정만` 포함합니다. DB 복원 지점이 필요하면 수동 백업에서 `데이터베이스 포함`을 선택해야 합니다.
- 알림 키워드 매칭은 fetch 결과 전체가 아니라 이번 요청에서 새로 추가된 기사 집합에만 적용됩니다.
- `app_settings`는 `client_secret_enc`, `client_secret_storage` 필드를 지원하며 Windows에서는 평문 `client_secret`를 비우고 암호문을 저장합니다.
- pending restore 실패(검증/적용 실패) 시 pending 파일은 유지되며, 적용 중 오류가 나면 변경 파일을 롤백합니다.

예시:

```json
{
  "pagination_state": {
    "<fetch_key>": 301
  },
  "pagination_totals": {
    "<fetch_key>": 542
  }
}
```

공개 API 참고:
- `DatabaseManager.connection(timeout: float = 10.0)` 컨텍스트 매니저를 제공하며, 권장 DB 접근 패턴입니다.
- `DatabaseManager.get_total_unread_count() -> int`를 통해 전체 미읽음 수를 직접 조회할 수 있습니다.
- `DatabaseManager.delete_link(link: str) -> bool`가 추가되어 UI 삭제 경로에서 중복 플래그 재계산을 일원화합니다.
- `DatabaseManager.count_news(..., exclude_words: Optional[List[str]] = None)`가 확장되어 미읽음 배지 집계 시 제외어 조건을 반영할 수 있습니다.
- `DatabaseManager.fetch_news(...)`, `count_news(...)`, `get_counts(...)`, `get_unread_count(...)`, `mark_query_as_read(...)`, `get_top_publishers(...)`는 `query_key`를 받아 대표 키워드가 같은 탭도 독립 범위로 조회할 수 있습니다.
- `DatabaseManager.get_unread_counts_by_query_keys(query_keys: List[str]) -> Dict[str, int]`가 추가되어 탭 배지를 `query_key` 기준으로 일괄 집계합니다.
- `AutoBackup.get_backup_list()`는 항목별 `is_corrupt`, `error`, `is_restorable`, `restore_error` 메타를 포함해 UI가 손상/복원 불가 항목을 분리 표시할 수 있습니다.

## 키워드 입력 규칙

- 최소 1개 이상의 일반 키워드가 필요합니다.
- 제외어-only 입력(예: `-광고 -코인`)은 탭 추가/이름 변경/설정 가져오기에서 차단됩니다.
- 같은 의미의 `canonical query`가 이미 열린 경우(예: 공백/대소문자 차이) 새 탭 대신 기존 탭으로 이동합니다.
- API 검색어는 모든 양(+) 키워드를 공백 결합해 사용합니다. 예: `인공지능 AI -광고` → API query: `인공지능 AI`
- 대표 키워드(`db_keyword`)는 첫 번째 양(+) 키워드를 사용합니다. 예: `인공지능 AI -광고` → 대표 키워드: `인공지능`
- 실제 탭 범위/배지/분석/중복 판정/페이지 상태는 `query_key = build_fetch_key(parse_search_query(raw_tab_query))` 기준으로 동작합니다.
- 기존 DB에서 마이그레이션된 멀티 키워드 탭은 각 탭을 한 번 새로고침한 뒤부터 정확히 분리됩니다.

## 설정 Export/Import

- export 포맷 버전은 `1.2`이며 `settings`, `tabs`, `keyword_groups`, `search_history`, `pagination_state`, `pagination_totals`, `window_geometry`를 포함합니다.
- API 자격증명(`client_id`, `client_secret`, `client_secret_enc`)은 export/import 대상에서 제외되고, `settings.auto_start_enabled`는 export/import 대상에 포함됩니다.
- import 시 `tabs`는 `canonical query` 기준 dedupe, `keyword_groups`는 merge, `search_history`는 `canonical query` 기준 imported-first dedupe 후 최대 10개로 정리합니다.
- `pagination_state`와 `pagination_totals`는 fetch key별로 병합하며 충돌 시 더 큰 값을 유지합니다.
- import는 `1.1`과 `1.2`를 모두 허용하며, 자동 시작/시작 최소화는 환경 가용성에 따라 안전한 값으로 보정됩니다.
- 트레이를 사용할 수 없는 환경에서 import된 `start_minimized=true`는 `False`로 강제되고 경고 토스트를 표시합니다.
- 시작프로그램 기능을 사용할 수 없는 환경에서 import된 `auto_start_enabled=true`는 `False`로 강제되고, 가능한 환경에서는 실제 레지스트리 상태까지 동기화합니다.

## 트레이/시작 최소화 규칙

- `--minimized` 또는 `start_minimized=true`는 시스템 트레이를 사용할 수 있을 때만 적용됩니다.
- 시스템 트레이를 사용할 수 없는 환경에서는 앱이 숨겨지지 않고 일반 창으로 시작합니다.
- 트레이 미지원 환경에서는 설정 창의 `시작 시 최소화 상태로 시작` 옵션이 비활성화됩니다.
- 시스템 트레이가 없더라도 `데스크톱 알림`은 토스트 fallback과 알림음으로 동작합니다.

## 라이선스

MIT License

