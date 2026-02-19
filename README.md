# 뉴스 스크래퍼 Pro v32.7.1

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

## 안정화 포인트 (v32.7.1)

- 시작 시 단일 인스턴스 가드 적용
- 설정 반영 누락 보완(`sound_enabled`, `api_timeout`)
- 설정 창의 API 키 검증/정리 작업 비동기 처리
- 설정 가져오기 시 탭 중복 병합(dedupe) 강화
- 자동 시작 최소화 옵션 변경 시 레지스트리 재등록

## 프로젝트 구조

```text
navernews-tabsearch/
├── news_scraper_pro.py          # 엔트리포인트 + 호환 re-export 레이어
├── news_scraper_pro.spec        # PyInstaller 빌드 설정
├── core/                        # 코어 로직 패키지
│   ├── __init__.py
│   ├── bootstrap.py             # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py             # 경로/버전/앱 상수
│   ├── config_store.py          # 설정 스키마 정규화 + 원자 저장
│   ├── database.py              # DatabaseManager (연결 풀, CRUD)
│   ├── workers.py               # ApiWorker/DBWorker/AsyncJobWorker
│   ├── worker_registry.py       # WorkerHandle/WorkerRegistry (요청 ID 기반 관리)
│   ├── query_parser.py          # parse_tab_query/build_fetch_key
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
│   ├── test_entrypoint_bootstrap.py
│   ├── test_import_settings_dedupe.py
│   ├── test_plan_regression.py
│   ├── test_refactor_backup_guard.py
│   ├── test_refactor_compat.py
│   ├── test_settings_roundtrip.py
│   ├── test_single_instance_guard.py
│   ├── test_stability.py
│   ├── test_startup_registry_command.py
│   └── test_symbol_resolution.py
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

## PyInstaller 빌드 (onefile)

현재 스펙(`news_scraper_pro.spec`)은 onefile 기준으로 구성되어 있습니다.

```bash
pyinstaller --noconfirm --clean news_scraper_pro.spec
```

- 산출물: `dist/NewsScraperPro_Safe.exe`
- 아이콘 리소스: `news_icon.ico`, `news_icon.png` 포함

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

## 라이선스

MIT License
