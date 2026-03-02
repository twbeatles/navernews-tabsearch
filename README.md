# 뉴스 스크래퍼 Pro v32.7.2

네이버 뉴스 검색 API를 기반으로 동작하는 탭형 뉴스 수집/관리 도구입니다.

## 문서 인코딩

이 문서는 UTF-8로 작성되어 있습니다.

## 주요 기능

- 탭 기반 키워드 검색 및 독립 관리
- 제외어(`-키워드`)와 날짜 조건을 포함한 고급 검색
- 자동 새로고침(10분~6시간) 및 수동 전체 새로고침
- 기사 북마크/읽음 처리/메모 작성
- 검색 결과 CSV 내보내기
- 키워드 그룹 관리
- 시스템 트레이 동작(최소화/닫기 동작 커스터마이징)
- 단일 인스턴스 실행 보장(중복 실행 방지)
- 설정/DB 자동 백업 및 재시작 적용형 복원(pending restore)

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
- 단일 인스턴스 stale lock 복구(`notify -> stale 제거 -> 재시도`) 및 상태 로깅 강화
- 트레이 미지원 환경에서 `--minimized`/`start_minimized` 요청 시 숨김 시작 차단
- 검색어 정책 분리: API 검색어(`parse_search_query`)와 DB 그룹 키(`parse_tab_query`) 분리 적용
- 설정 창 닫힘 시 백그라운드 워커 정리(콜백 안전 가드)
- PyInstaller spec 동기화: `PyQt6.QtNetwork` 포함 보장(단일 인스턴스 IPC 런타임 안정화)

## 프로젝트 구조

```text
navernews-tabsearch/
├── news_scraper_pro.py          # 엔트리포인트 + 호환 re-export 레이어
├── news_scraper_pro.spec        # PyInstaller 빌드 설정
├── pytest.ini                   # pytest 진입점/수집 경로 고정
├── core/                        # 코어 로직 패키지
│   ├── __init__.py
│   ├── bootstrap.py             # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py             # 경로/버전/앱 상수
│   ├── config_store.py          # 설정 스키마 정규화 + 원자 저장
│   ├── database.py              # DatabaseManager (연결 풀, CRUD)
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
│   ├── main_window.py           # MainApp (메인 윈도우)
│   ├── news_tab.py              # NewsTab (개별 뉴스 탭)
│   ├── settings_dialog.py       # SettingsDialog
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
│   ├── test_load_more_total_guard.py
│   ├── test_news_tab_ext_read_policy.py
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

## PyInstaller 빌드 (onefile)

현재 스펙(`news_scraper_pro.spec`)은 onefile 기준으로 구성되어 있습니다.

```bash
pyinstaller --noconfirm --clean news_scraper_pro.spec
```

- 산출물: `dist/NewsScraperPro_Safe.exe`
- 아이콘 리소스: `news_icon.ico`, `news_icon.png` 포함
- v32.7.2 핵심 안정화 1차(2026-02-25)는 런타임 로직/스키마 변경만 포함하며 `.spec` 추가 수정은 필요하지 않습니다.
- v32.7.2 핵심+테스트 보강 2차(2026-02-28)도 런타임/테스트/문서 변경만 포함하며 `.spec` 수정은 필요하지 않습니다.
- v32.7.2 감사 반영(2026-03-02)에서는 단일 인스턴스 IPC(`QLocalServer/QLocalSocket`) 경로 보호를 위해 `PyQt6.QtNetwork`를 `.spec`에 명시 반영했습니다.

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
| `Ctrl+S` | CSV 내보내기 |
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

예시:

```json
{
  "pagination_state": {
    "<fetch_key>": 301
  }
}
```

공개 API 참고:
- `DatabaseManager.delete_link(link: str) -> bool`가 추가되어 UI 삭제 경로에서 중복 플래그 재계산을 일원화합니다.

## 키워드 입력 규칙

- 최소 1개 이상의 일반 키워드가 필요합니다.
- 제외어-only 입력(예: `-광고 -코인`)은 탭 추가/이름 변경/설정 가져오기에서 차단됩니다.
- API 검색어는 모든 양(+) 키워드를 공백 결합해 사용합니다. 예: `인공지능 AI -광고` → API query: `인공지능 AI`
- DB 저장/조회 그룹 키는 첫 번째 양(+) 키워드를 사용합니다. 예: `인공지능 AI -광고` → DB key: `인공지능`

## 트레이/시작 최소화 규칙

- `--minimized` 또는 `start_minimized=true`는 시스템 트레이를 사용할 수 있을 때만 적용됩니다.
- 시스템 트레이를 사용할 수 없는 환경에서는 앱이 숨겨지지 않고 일반 창으로 시작합니다.
- 트레이 미지원 환경에서는 설정 창의 `시작 시 최소화 상태로 시작` 옵션이 비활성화됩니다.

## 라이선스

MIT License

