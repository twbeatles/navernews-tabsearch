# 뉴스 스크래퍼 Pro v32.7.3

네이버 뉴스 검색 API를 기반으로 동작하는 탭형 뉴스 수집/관리 도구입니다.

## 문서 인코딩

이 문서는 UTF-8로 작성되어 있습니다.

## 개발/검증 기준

- 개발/정적 분석 기준: Windows, Python 3.14, PyQt6
- 소스 실행 최소 기준: Python 3.14+
- 기본 검증 명령: `pyright`(`pyrightconfig.json`) + `pytest -q`

## 주요 기능

- 탭 기반 키워드 검색 및 독립 관리
- 같은 첫 키워드를 공유해도 전체 검색 의미(`query_key`) 기준으로 탭 범위 분리
- 같은 `canonical query` 탭은 중복 생성하지 않고 기존 탭으로 이동
- 제외어(`-키워드`)와 날짜 조건을 포함한 고급 검색
- 자동 새로고침(10분~6시간) 및 수동 전체 새로고침
- 기사 북마크/읽음 처리/메모 작성
- 열린 탭/북마크 탭 사이의 기사 상태 즉시 동기화
- 알림 키워드와 새 기사 알림은 이번 fetch에서 새로 감지된 링크(`new_items` / `new_count`) 중 자동화 규칙으로 알림 억제되지 않은 항목에만 적용
- 알림 키워드는 일반 부분 문자열과 `regex:<패턴>` 정규식 접두어를 지원
- 현재 탭 필터 전체 결과 CSV/Markdown digest 내보내기
- CSV 메모/북마크 가져오기는 기존 기사 link에 대해서만 상태를 갱신하고 새 기사는 생성하지 않음
- 출처 차단/선호 필터: 차단 출처는 DB에 저장하되 목록/count/배지/트레이/분석/CSV에서 숨기고, 도메인 출처는 suffix match로 처리하며 선호 출처는 사용자가 `선호 출처만` 필터를 켠 경우에만 적용
- 기사별 자유 태그 편집, 태그 배지 표시, 태그 필터, CSV/Markdown 태그 컬럼, 태그 관리자(이름 변경/병합/삭제/현재 탭 전체 DB scope 일괄 적용)
- 전체 아카이브 검색(제목/요약, 메모, 태그, 출처 alias, 날짜, 북마크/미읽음 조건)과 결과 열기/북마크/읽음/메모/태그 액션
- 자동화 규칙(목록+폼 UI, 고급 JSON, 자동 태그/북마크/읽음/제외/알림 억제)과 출처 alias 행 기반 편집/표시/필터 매핑
- 현재 탭의 검색어/필터/정렬/기간/태그/선호 출처 조건을 이름으로 저장하고 대상 검색어 탭으로 이동/생성해 다시 적용하는 저장된 검색
- 탭별 자동 새로고침 정책: 기본은 전역 설정 상속, 탭 컨텍스트 메뉴에서 상속/끔/개별 간격 override
- 키워드 그룹 관리
- 로컬 DB + 클라우드 스냅샷 ZIP 기반 동기화(기본 30분, 수동 내보내기/병합 지원)
- 시스템 트레이 동작(최소화/닫기 동작 커스터마이징)
- 단일 인스턴스 실행 보장(중복 실행 방지)
- 설정 자동 백업 + 수동 DB 포함 백업 및 재시작 적용형 복원(pending restore), 복원 예약 전 dry-run 요약
- 설정의 시스템 테마 자동 모드, DB 최적화(`PRAGMA optimize` + 선택 VACUUM), 태그 통계와 출처 필터 시뮬레이션


## 프로젝트 구조

```text
navernews-tabsearch/
├── news_scraper_pro.py          # 엔트리포인트 + 호환 re-export 레이어
├── news_scraper_pro.spec        # PyInstaller 빌드 설정
├── pyrightconfig.json           # Pyright/Pylance 기준 설정 (Windows, Python 3.14)
├── pytest.ini                   # pytest 진입점/수집 경로 고정
├── tests/conftest.py            # pytest 임시 디렉터리/세션 공통 설정
├── core/                        # 코어 로직 패키지
│   ├── __init__.py
│   ├── bootstrap.py             # 앱 부팅(main), 전역 예외 처리, 단일 인스턴스 가드
│   ├── constants.py             # RuntimePaths facade + 경로/버전 상수 호환 export
│   ├── config_store.py          # 설정 import 호환 facade
│   ├── config_store_impl.py     # 설정 구현 호환 facade
│   ├── config_store_support/    # types / secrets / normalization / file I/O
│   ├── content_filters.py       # 출처/태그 정규화 helper
│   ├── cloud_sync.py            # 클라우드 스냅샷 호환 facade
│   ├── cloud_sync_support/      # snapshot I/O / import flow / cloud path policy
│   ├── automation_rules.py      # 규칙 기반 자동 태그/북마크/읽음 처리 helper
│   ├── publisher_aliases.py     # 출처 alias 정규화/표시/필터 확장 helper
│   ├── database.py              # DatabaseManager facade (연결 풀 수명 주기)
│   ├── http_client.py           # 중앙 HTTP 구성 + worker-owned requests.Session factory
│   ├── runtime_support/         # runtime path 계산 + 레거시 파일 마이그레이션
│   │   ├── paths.py
│   │   └── migration.py
│   ├── _db_schema.py            # DB schema 호환 facade
│   ├── db_schema_support/       # connection / tables / keyword schema / backfill
│   ├── _db_duplicates.py        # 제목 해시 / 중복 플래그 재계산
│   ├── _db_queries.py           # DB query 호환 facade
│   ├── db_queries_support/      # filter helpers / fetch / archive / count queries
│   ├── _db_mutations.py         # DB mutation 호환 facade
│   ├── db_mutations_support/    # upsert / state_tags_support / maintenance_support
│   ├── _db_analytics.py         # 통계 / 언론사 분석
│   ├── _db_cloud_sync.py        # 스냅샷 DB 병합 호환 facade
│   ├── db_cloud_sync_support/   # metadata / rollback / row merge / preview / apply
│   ├── protocols.py             # lock/session capability Protocol 정의
│   ├── workers.py               # worker API 호환 facade
│   ├── workers_support/         # lifecycle / HTTP policy / job workers / ApiWorker / DBWorker
│   ├── worker_registry.py       # WorkerHandle/WorkerRegistry (요청 ID 기반 관리)
│   ├── query_parser.py          # parse_tab_query/parse_search_query/build_fetch_key
│   ├── backup.py                # backup/restore API 호환 facade
│   ├── backup_support/          # 파일 백업 / payload 검증 / restore / AutoBackup support
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
│   │   ├── base_support/
│   │   ├── config.py
│   │   ├── ui_shell.py
│   │   └── ui_shell_support/
│   ├── _main_window_tabs.py     # 탭 추가/닫기/리네임/그룹 연결
│   ├── _main_window_fetch.py    # fetch orchestration 호환 facade
│   ├── main_window_fetch_support/ # refresh policy / fetch worker lifecycle/support
│   ├── _main_window_settings_io.py # 설정 import/export 호환 facade
│   ├── main_window_io_support/  # cloud sync / export/import / settings staging/support
│   ├── _main_window_tray.py     # 트레이 / 종료 / closeEvent 처리
│   ├── _main_window_analysis.py # 통계 / 언론사 분석 UI
│   ├── news_tab.py              # NewsTab facade / compatibility root
│   ├── news_tab_support/        # NewsTab 상태/로딩/렌더링/액션 분리
│   │   ├── state.py
│   │   ├── loading.py
│   │   ├── loading_support/
│   │   ├── rendering.py
│   │   ├── ui_controls.py
│   │   ├── ui_controls_support/
│   │   ├── actions.py
│   │   └── actions_support/
│   ├── dialog_adapters.py       # QFileDialog/QMessageBox adapter
│   ├── protocols.py             # 메인 윈도우/부모 capability Protocol 정의
│   ├── settings_dialog.py       # SettingsDialog facade
│   ├── _settings_dialog_content.py # 설정/도움말/단축키 탭 조립
│   ├── _settings_dialog_docs.py # 도움말 / 단축키 HTML
│   ├── _settings_dialog_tasks.py # API 검증 / 데이터 정리 / 워커 정리
│   ├── dialogs.py               # 보조 다이얼로그 호환 facade
│   ├── dialogs_support/         # article tool dialogs / backup_dialog / logs / keyword groups
│   ├── styles.py                # 스타일 API 호환 facade
│   ├── styles_support/          # color tokens / constants / QSS / HTML template
│   ├── toast.py                 # ToastQueue/ToastMessage
│   └── widgets.py               # NewsBrowser/NoScrollComboBox
├── tests/                       # 회귀/호환성/안정성 테스트
│   ├── test_db_queries.py
│   ├── test_encoding_smoke.py
│   ├── test_entrypoint_bootstrap.py
│   ├── test_import_settings_dedupe.py
│   ├── test_import_settings_normalization.py
│   ├── test_db_integrity_recovery.py
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
│   ├── test_cloud_sync.py
│   ├── test_audit_followthrough.py
│   ├── test_dialog_adapters_smoke.py
│   ├── test_import_refresh_prompt.py
│   ├── test_shutdown_cleanup.py
│   ├── test_stabilization_round1.py
│   ├── test_load_more_total_guard.py
│   ├── test_fetch_cooldown.py
│   ├── test_async_analysis.py
│   ├── test_fts_search_acceleration.py
│   ├── test_news_tab_ext_read_policy.py
│   ├── test_news_tab_performance.py
│   ├── test_settings_validation_http_policy.py
│   ├── test_settings_dialog_maintenance.py
│   ├── test_runtime_storage_paths.py
│   ├── test_version_history_guard.py
│   ├── test_implementation_batch_20260427.py
│   ├── test_implementation_plan_20260429.py
│   └── test_functional_risk_20260511.py
├── query_parser.py              # 호환 래퍼 (→ core.query_parser)
├── config_store.py              # 호환 래퍼 (→ core.config_store)
├── backup_manager.py            # 호환 래퍼 (→ core.backup)
├── worker_registry.py           # 호환 래퍼 (→ core.worker_registry)
├── workers.py                   # 호환 래퍼 (→ core.workers)
├── database_manager.py          # 호환 래퍼 (→ core.database)
├── styles.py                    # 호환 래퍼 (→ ui.styles)
├── backups/                     # 레거시 실행 폴더 백업(현재 런타임 백업은 DATA_DIR 하위 사용)
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
- `tests/test_encoding_smoke.py`는 저장소 주요 텍스트 자산(`.py`, `.md`, `.json`, `.ini`, `.spec`, `.txt`, `.yml`, `.yaml`)의 UTF-8 decode 실패, `\ufffd`, 알려진 깨진 토큰, 대표적인 mojibake 정규식 패턴 재등장을 함께 감시합니다.
- `tests/test_settings_validation_http_policy.py`는 설정 창 API 검증이 raw `requests.get(...)`가 아니라 공용 session + 현재 timeout 정책을 쓰는지 회귀 테스트로 검증합니다.
- facade 공개 경로(`ui.main_window.MainApp`, `core.database.DatabaseManager`, `ui.settings_dialog.SettingsDialog`, `core.workers`, `core.backup`, `ui.dialogs`, `ui.styles`)는 유지하고, 내부 구현은 support package/private helper module로 분리했습니다.

## PyInstaller 빌드 (onefile)

현재 스펙(`news_scraper_pro.spec`)은 onefile 기준으로 구성되어 있습니다.

```bash
pyinstaller --noconfirm --clean news_scraper_pro.spec
```

- 산출물: `dist/NewsScraperPro_Safe.exe`
- 아이콘 리소스: `news_icon.ico` 포함 (`news_icon.png`는 존재할 경우 fallback으로 함께 번들)
- 2026-05-22 대형 모듈 분할 리팩토링 기준 `python -m PyInstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 성공했고, 새 데이터 디렉터리 + `QT_QPA_PLATFORM=offscreen` 패키지 스모크에서 실행형이 정상 시작됨을 확인했습니다. `urllib3.contrib.emscripten`은 브라우저/Emscripten 전용 optional 경로라 submodule 수집에서 제외합니다.
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
- v32.7.2 성능 최적화 리팩토링(2026-03-21)에서도 `.spec`을 다시 재검토했으며, `DBQueryScope`, append skip-count, `NewsTab` fragment cache/coalesced render, 복합 인덱스 추가는 기존 번들 의존성만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- v32.7.3 운영 안정화 1차(2026-03-25)에서도 `.spec`을 다시 재검토했으며, `IterativeJobWorker`, 백업 full verification, 자동 시작 health/repair, config `.backup` 회전, DB emergency cap은 기존 번들 의존성만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- v32.7.3 구현 리스크 전면 반영(2026-04-09)에서도 `.spec`을 다시 재검토했으며, `HttpClientConfig`, fetch cooldown, snapshot export, dedicated read connection, async analysis, SQLite FTS5 backfill은 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- v32.7.3 구현 리스크 후속 정합화(2026-04-13)에서도 `.spec`을 다시 재검토했으며, `DatabaseWriteError`, 반복 backfill loop, 설정 검증 HTTP 정책 통합, 인코딩 가드 강화는 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- v32.7.3 구현 리스크 후속/문서 정합화(2026-04-16)에서도 `.spec`과 `.gitignore`를 다시 재검토했으며, `5xx` retry 승격, hydration cancellation hardening, staged import atomicity, legacy backup metadata compatibility, persisted verification metadata, interruptible analysis reads, FTS retry scheduler는 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- 2026-03-25 기준으로 `.gitignore`에 `.pytest_tmp/`를 명시 추가했고, 동일한 명령 `pyinstaller --noconfirm --clean news_scraper_pro.spec`로 클린 빌드가 다시 성공해 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됨을 재확인했습니다.
- 2026-03-21 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드를 다시 검증했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-03-24 기준으로도 `.spec`과 `.gitignore`를 다시 재검토했고, 동일한 명령 `pyinstaller --noconfirm --clean news_scraper_pro.spec`로 클린 빌드가 성공해 추가 packaging/ignore 수정이 필요하지 않음을 재확인했습니다.
- 2026-03-27 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, help/read-only 설정 다이얼로그, 수동 백업 검증 UX, unread count bookkeeping, 트레이 fallback 알림 추가 이후에도 별도 packaging/ignore 수정은 필요하지 않았습니다.
- 2026-03-27 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-02 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, dialog adapter 도입, 종료 cleanup 강화, 백업 restorable preflight, import 후 선택 refresh 추가 이후에도 별도 packaging/ignore 수정은 필요하지 않았습니다.
- 2026-04-02 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-05 기준으로 `.spec`을 다시 재검토했고, 유지보수 모드의 DB 작업 전면 차단, `DatabaseQueryError` 기반 조회 실패 표면화, 키워드 그룹 저장 실패 노출, 백업 self-verify, import 후 refresh 가능 여부 선검사는 기존 번들 의존성만 사용하므로 추가 hidden import/exclude/data 수정이 필요하지 않습니다.
- 2026-04-05 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-13 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, DB write failure 승격, legacy backfill 반복 처리, 설정 검증 HTTP 정책 통합, mojibake 정리/인코딩 가드 강화 이후에도 추가 packaging/ignore 수정은 필요하지 않음을 재확인했습니다.
- 2026-04-13 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-16 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, hydration late-cleanup, import staged persistence, legacy backup metadata 보정/검증 결과 영속화, interruptible analysis read, FTS retry/resume 추가 이후에도 별도 packaging/ignore 수정은 필요하지 않음을 재확인했습니다.
- 2026-04-16 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-18 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, 유지보수 완료 sync 순서 고정, 순차 새로고침 즉시 알림, `new_count` 의미 통일, `Retry-After` 지원, 남은 pyright 정리 추가 이후에도 별도 packaging/ignore 수정은 필요하지 않음을 재확인했습니다.
- 2026-04-18 기준 `git status --ignored --short`로 `build/`, `dist/`, `__pycache__/`, `.pytest_cache/`, 런타임 DB/설정/로그 산출물이 계속 무시되는 것도 확인했습니다.
- 2026-04-18 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-22 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, `RuntimePaths` 통합, SQLite-safe legacy migration hardening, `core/runtime_support` / `ui/main_window_support` / `ui/news_tab_support` 구조 분할은 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 변경이 필요하지 않음을 확인했습니다.
- 2026-04-22 기준 `.gitignore`에는 portable/legacy 실행 폴더에서 다시 생길 수 있는 `keyword_groups.json`, `news_scraper_pro.lock`을 추가로 명시했습니다.
- 2026-04-22 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-27 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, 출처 필터/자유 태그/저장된 검색/탭별 자동 새로고침/복원 dry-run/설정 facade 분리는 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 변경이 필요하지 않음을 확인했습니다.
- 2026-04-27 기준 `.gitignore`에는 복원 적용 성공 후 남을 수 있는 `pending_restore.json.applied`를 추가로 무시하도록 보강했습니다.
- 2026-04-27 기준 `pyinstaller --noconfirm --clean news_scraper_pro.spec` 클린 빌드가 다시 성공했으며, 산출물 `dist/NewsScraperPro_Safe.exe`가 정상 생성됩니다.
- 2026-04-29 기준 `.gitignore`를 `git status --ignored --short`와 runtime/test/build 산출물 기준으로 다시 확인했고, `.pytest_cache/`, `.pytest_tmp/`, `build/`, `dist/`, 로그, `__pycache__/`, runtime DB/config/backup/pending restore 잔여물이 기존 규칙으로 모두 무시되어 추가 수정은 필요하지 않았습니다.
- 2026-05-03 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, import 병합/정규화, canonical tab refresh policy key, saved search 날짜 검증, 토큰 AND 검색, worker cleanup, API URL 정규화는 기존 번들 의존성/표준 라이브러리만 사용하므로 추가 hidden import/exclude/data 변경이 필요하지 않음을 확인했습니다.
- 2026-05-03 기준 `git status --ignored --short`로 `.pytest_cache/`, `.pytest_tmp/`, `build/`, `dist/`, `__pycache__/`, runtime DB/config/log/backup/pending restore 잔여물이 계속 무시되는 것을 확인했고, `.gitignore` 추가 수정은 필요하지 않았습니다.
- 2026-05-08 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, 리다이렉트 차단, 사설 URL 필터, DB 최적화, export 1.3 machine id, 설정-only 자동 백업, CSV 메모/북마크 import, 정규식 알림, 태그 통계, 로그 회전은 표준 라이브러리/기존 번들 의존성만 사용하므로 추가 hidden import/exclude/data 변경이 필요하지 않습니다.
- 2026-05-08 기준 `git status --ignored --short`와 `git check-ignore -v build dist .pytest_tmp .pytest_cache __pycache__ dist\NewsScraperPro_Safe.exe build\news_scraper_pro\Analysis-00.toc`로 build/dist/cache/log 산출물이 기존 `.gitignore` 규칙으로 무시되는 것을 확인했습니다.
- 2026-05-11 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, 기능 리스크 수정과 support-package 리팩토링은 표준 라이브러리와 기존 PyQt/SQLite 경로만 사용하므로 별도 hidden import/exclude/data 변경은 필요하지 않습니다. `.claude/` worktree scratch는 publish 대상 소스가 아니므로 ignore합니다.
- 2026-05-10 기준 `.gitignore`에는 cloud snapshot 산출물(`news_scraper_sync_*.zip`, `.news_scraper_sync_*.zip.tmp`)을 추가로 무시하도록 보강했습니다.
- 2026-05-19 기준으로 `.spec`과 `.gitignore`를 다시 재검토했고, soft-delete tombstone, cloud import preview, snapshot 크기 검증/`.invalid/` 격리, LIKE literal escape, 자동화 transaction 적용은 기존 stdlib/PyQt/SQLite 경로만 사용하므로 hidden import/data/exclude 추가가 필요하지 않습니다. `.gitignore`에는 `.invalid/` quarantine 폴더를 추가했습니다.
- 2026-04-29 문서 정합화에서는 삭제 상태인 `implementation_risk_review_2026-04-27.md`를 되돌리지 않고 현재 작업트리 상태로 유지합니다.

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
| `Ctrl+S` | 현재 탭 필터 전체 결과 CSV 또는 Markdown 내보내기 |
| `Ctrl+Shift+F` | 전체 아카이브 검색 열기 |
| `Ctrl+Shift+T` | 태그 관리자 열기 |
| `Ctrl+Shift+A` | 자동화 규칙 열기 |
| `Ctrl+,` | 설정 열기 |
| `Alt+1~9` | 탭 바로가기 |

## 데이터/설정 파일

앱은 기본적으로 사용자 런타임 디렉터리(`DATA_DIR`)에 아래 파일을 저장합니다.

- Windows 기본값: `%LOCALAPPDATA%\NaverNewsScraperPro`
- macOS 기본값: `~/Library/Application Support/NaverNewsScraperPro`
- Linux 기본값: `$XDG_DATA_HOME/NaverNewsScraperPro` 또는 `~/.local/share/NaverNewsScraperPro`
- 예외: `NEWS_SCRAPER_DATA_DIR`로 강제 지정 가능, `NEWS_SCRAPER_PORTABLE=1`이면 `APP_DIR` 사용

- `news_scraper_config.json`
- `news_database.db`
- `news_scraper.log`
- `pending_restore.json`
- `backups/`
- `news_scraper_pro.lock`
- `crash_log.txt`

참고:
- 시작 시 실행 폴더(`APP_DIR`)에 남아 있는 레거시 런타임 파일은 비파괴적으로 `DATA_DIR`로 1회 복사 마이그레이션됩니다.
- 레거시 `pending_restore.json`는 가능하면 새 `DATA_DIR/backups` 기준으로 `backup_dir`를 재기록해 복사합니다.
- 레거시 `backups/`는 폴더 단위 merge로 옮기며, 같은 이름의 백업이 이미 있으면 `DATA_DIR` 쪽 항목을 유지합니다.
- 레거시 DB 마이그레이션은 SQLite backup API 우선, 실패 시 raw copy fallback + integrity 검증으로 수행됩니다.
- `keyword_groups`는 별도 파일이 아니라 `news_scraper_config.json` 내부 필드로 저장됩니다.
- `app_settings.blocked_publishers`와 `app_settings.preferred_publishers`는 쉼표 입력값을 trim/빈 값 제거/case-insensitive dedupe한 뒤 양쪽 충돌을 제거해 저장합니다.
- `app_settings.auto_backup_minutes`는 설정-only 자동 백업 간격이며 `0`, `30`, `60`, `180`, `360`분 값을 사용합니다. 기본값은 `60`입니다.
- `theme_index`는 `0=라이트`, `1=다크`, `2=시스템 설정 자동`입니다.
- `saved_searches`는 검색어, 텍스트 필터, 정렬, 안 읽음, 중복 숨김, 기간, 태그, 선호 출처 필터를 이름별 payload로 저장하며, 적용 시 저장된 검색어 탭으로 이동/생성하고 UI에서 삭제할 수 있습니다.
- `tab_refresh_policies`는 canonical fetch key별 자동 새로고침 override이며 값은 `inherit`, `off`, 또는 분 단위 문자열(`10`, `30`, `60`, `120`, `360`)입니다. 레거시 raw 탭 키워드 key는 로드/import 시 가능한 범위에서 canonical key로 자동 보정됩니다.
- 단일 인스턴스 잠금 파일(`news_scraper_pro.lock`)과 crash log(`crash_log.txt`)도 같은 runtime 경로 기준으로 관리됩니다.
- `pagination_state`는 `fetch_key -> 마지막 API start index` 매핑이며, 필드가 없으면 기본값 `{}`로 로드됩니다.
- `pagination_state` 값은 `1..1000` 범위로 정규화됩니다.
- `pagination_totals`는 `fetch_key -> 마지막으로 확인한 API total` 매핑이며 `0`도 유효한 값으로 저장됩니다.
- `search_history`는 `canonical query` 기준으로 dedupe되며 공백/대소문자만 다른 변형은 별도 항목으로 누적되지 않습니다.
- 클라우드 동기화는 live DB를 로컬 `DATA_DIR`에 두고, OneDrive/Google Drive 같은 폴더에는 `news_scraper_sync_*.zip` 스냅샷만 교환합니다.
- `DATA_DIR` 또는 `news_database.db`가 클라우드 동기화 폴더 안에 있는 것으로 감지되면 주기 동기화는 차단됩니다.
- 클라우드 스냅샷 ZIP에는 `manifest.json`, secret 제거 `settings.json`, SQLite backup API로 만든 `news_database.db`만 들어갑니다. API 자격증명, 자동화 규칙, 출처 alias, SQLite `-wal`/`-shm` sidecar는 포함하지 않습니다.
- 클라우드 동기화는 기사/검색범위를 `link`, `(link, query_key)` 기준으로 union 병합합니다. 읽음/북마크/메모/태그와 명시 단건 삭제/복구 tombstone은 per-field timestamp 최신 변경을 따르며, API 재수집이나 오래된 active snapshot이 더 최신 tombstone을 자동 복구하지 않습니다.
- 수동 병합은 적용 전 dry-run preview를 보여주고, 주기 동기화는 확인 없이 자동 병합하되 같은 요약 통계를 상태 메시지에 남깁니다. "주기적 클라우드 동기화 사용" 체크박스는 timer만 제어하며 수동 export/import는 폴더/runtime 검증만 통과하면 실행됩니다.
- 스냅샷 ZIP/DB는 각각 512MB, manifest/settings JSON은 각각 1MB 상한을 적용합니다. 손상되었거나 초과한 스냅샷은 동기화 폴더의 `.invalid/`로 격리됩니다.
- 백업 복원 예약은 선택한 백업의 `include_db` 메타를 우선 사용하고, legacy 백업처럼 메타가 없으면 실제 DB payload 존재 여부로 복원 범위(`설정만`/`설정+DB`)를 자동 판별합니다.
- 백업 메타의 `trigger`는 `auto`/`manual` 값을 가지며, 자동 시작 백업은 수동 백업과 별도 보존 정책으로 관리됩니다.
- 자동 시작 백업은 `설정만` 포함합니다. DB 복원 지점이 필요하면 수동 백업에서 `데이터베이스 포함`을 선택해야 합니다.
- 수동 백업은 `news_scraper_config.json`이 있어 실제로 복원 가능한 payload를 만들 수 있을 때만 성공합니다.
- 백업 생성은 payload 기록 직후 self-verify를 수행하며, 검증 실패 항목은 폴더를 지우지 않고 백업 목록에서 `복원 불가` 상태로 남깁니다.
- 수동 검증과 복원 직전 검증은 `verification_state`, `verification_error`, `is_restorable`, `restore_error`, `is_corrupt`, `error`, `last_verified_at`를 `backup_info.json`에 다시 기록합니다.
- 시작 시 자동 백업은 설정 파일이 없으면 사용자 차단 없이 skip되고 로그만 남깁니다.
- 알림 키워드 매칭은 fetch 결과 전체가 아니라 이번 요청에서 새로 추가된 기사 중 자동화 규칙으로 알림 억제되지 않은 집합에만 적용됩니다.
- `app_settings`는 `client_secret_enc`, `client_secret_storage` 필드를 지원하며 Windows에서는 평문 `client_secret`를 비우고 암호문을 저장합니다.
- pending restore 실패(검증/적용 실패) 시 pending 파일은 유지되며, 적용 중 오류가 나면 변경 파일을 롤백합니다.
- pending restore 성공 시 `pending_restore.json`을 먼저 `pending_restore.json.applied`로 atomic rename한 뒤 삭제를 시도하므로, 삭제가 실패해도 다음 시작 때 같은 복원이 반복 적용되지 않습니다.
- 기사 태그는 SQLite `news_tags(link, tag)`에 저장되며, 태그 정규화는 trim, 빈 값 제거, case-insensitive dedupe, 기사당 최대 20개, 태그당 최대 30자 제한을 적용합니다.

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
- `DatabaseManager.get_total_unread_count(blocked_publishers=None) -> int`를 통해 visibility-aware 전체 미읽음 수를 직접 조회할 수 있습니다.
- `DatabaseManager.delete_link(link: str) -> bool`는 명시 단건 삭제를 soft-delete tombstone으로 기록하고, `DatabaseManager.restore_deleted_link(link: str) -> bool`는 아카이브에서 복구할 때 사용합니다.
- `DatabaseManager.apply_automation_actions(mutations: list[dict]) -> dict`는 평가 완료된 자동화 태그/읽음/북마크 변경을 한 transaction에서 적용합니다.
- `DatabaseManager.count_news(..., exclude_words: Optional[List[str]] = None)`가 확장되어 미읽음 배지 집계 시 제외어 조건을 반영할 수 있습니다.
- `DatabaseManager.fetch_news(...)`, `count_news(...)`, `get_counts(...)`, `get_unread_count(...)`, `mark_query_as_read(...)`, `get_top_publishers(...)`는 `query_key`가 있으면 대표 keyword 문자열과 무관하게 해당 query scope만 조회합니다.
- `core.workers.DBWorker`는 `DBQueryScope + include_total + known_total_count` 계약을 사용해 append 시 total count round-trip을 생략하고, full reload에서만 `count_news(...)`를 실행합니다.
- `core.workers.ApiWorker`는 `last_error_meta(kind/status_code/cooldown_seconds/retryable)`를 남기며, `MainApp.on_fetch_error(...)`는 이를 읽어 전역 fetch cooldown을 갱신합니다.
- `core.workers.ApiWorker`는 API 응답의 `originallink`/`link` 중 `http`/`https` URL만 저장 후보로 삼고, 둘 다 유효하지 않으면 해당 item을 건너뜁니다. publisher는 유효한 URL host에서 `www.`를 제거해 산출합니다.
- `DatabaseManager.iter_news_snapshot_batches(...)`는 현재 탭 필터 전체 결과를 단일 read snapshot 위에서 순회해 CSV export 일관성을 보장합니다.
- `DatabaseManager.merge_cloud_snapshot_db(...)`는 스냅샷 DB를 단일 transaction에서 병합하고, 실패 시 사전 백업으로 rollback합니다. 이미 가져온 snapshot id와 같은 PC snapshot은 건너뜁니다.
- `core.cloud_sync.create_cloud_snapshot(...)` / `preview_cloud_snapshots_for_import(...)` / `import_cloud_snapshot(...)` / `run_cloud_sync_cycle(...)`는 클라우드 스냅샷 ZIP의 생성, 크기/무결성 검증, preview, 병합, invalid 격리, 오래된 스냅샷 정리를 담당합니다.
- `DatabaseManager.optimize_database(vacuum: bool = False)`는 설정 창의 DB 최적화 작업에서 사용됩니다.
- `DatabaseManager.get_top_tags(limit=20, ...)`는 통계 다이얼로그의 태그 통계를 제공합니다.
- `DatabaseManager.fetch_news(...)`, `count_news(...)`, `get_top_publishers(...)`, `iter_news_snapshot_batches(...)`는 `blocked_publishers`, `preferred_publishers`, `only_preferred_publishers`, `tag_filter` scope를 공유하며, 도메인 값은 `example.com`이 `example.com`/`news.example.com`에 매칭되고 `badexample.com`에는 매칭되지 않습니다.
- `DatabaseManager.get_tags(link)`, `set_tags(link, tags)`, `get_known_tags()`, `get_tag_usage()`, `rename_tag()`, `delete_tag_everywhere()`, `bulk_add_tag_to_links()`, `bulk_remove_tag_from_links()`가 기사 태그 CRUD, 태그 관리자, 태그 필터 목록을 담당합니다.
- `DatabaseManager.search_archive()` / `count_archive()`는 전체 DB 아카이브 검색을 담당하고, 출처 alias는 원본 `publisher`를 보존한 채 표시/필터/통계 매핑으로 적용됩니다. 아카이브 검색 다이얼로그는 결과 row의 link payload로 열기/북마크/읽음/메모/태그 액션을 수행합니다.
- `automation_rules`와 `publisher_aliases`는 로컬 설정 export/import에는 포함되지만 cloud snapshot settings에서는 제외됩니다.
- `DatabaseManager.open_read_connection(...)`, `close_read_connection(...)`, `interrupt_connection(...)`은 `DBWorker` 취소/종료 경로에서 사용하는 dedicated read connection helper입니다.
- `DatabaseManager.is_news_fts_backfill_complete()`와 `backfill_news_fts_chunk(...)`는 `news_fts` 증분 백필 상태를 `app_meta`에 저장합니다. 현재 텍스트 필터의 의미 기준은 FTS가 아니라 LIKE token-AND이며, FTS rowid prefilter는 false negative 방지를 위해 사용하지 않습니다.
- `ui.news_tab.NewsTab`은 scope signature별 append/replace를 구분하고, HTML 렌더는 fragment cache를 재사용하면서 event-loop tick당 한 번만 flush합니다.
- `DatabaseManager.get_unread_counts_by_query_keys(query_keys: List[str]) -> Dict[str, int]`는 호환 batch API로 유지되며, 실제 탭 배지는 `DBQueryScope` 기반 `count_news(..., only_unread=True)`로 표시 scope와 일치시킵니다.
- `AutoBackup.get_backup_list()`는 항목별 `is_corrupt`, `error`, `is_restorable`, `restore_error` 메타를 포함해 UI가 손상/복원 불가 항목을 분리 표시할 수 있습니다.
- `AutoBackup.delete_corrupt_backups()`는 백업 관리 다이얼로그의 손상 백업 일괄 삭제에서 사용됩니다.
- `core.database.DatabaseQueryError`는 조회/집계 계열 DB 실패를 빈 결과로 삼키지 않는 표준 예외 계약이며, UI는 기존 캐시를 보존한 채 실패를 노출합니다.
- `core.database.DatabaseWriteError`는 쓰기/변경 계열 DB 실패를 성공처럼 삼키지 않는 표준 예외 계약이며, `ApiWorker`와 fetch UI는 저장 실패를 성공 완료와 명확히 분리합니다.
- `DatabaseManager.update_status(link, field, value)`는 대상 row가 없거나 동일 값 no-op이면 `False`를 반환하고 SQLite 쓰기 실패는 `DatabaseWriteError`로 올립니다.
- `DatabaseManager.get_note(link)`는 조회 실패를 `DatabaseQueryError`로 올리며, UI는 이 경우 메모 다이얼로그를 열지 않습니다.
- `DatabaseManager.delete_link(link)`는 대상 없음/이미 삭제됨(`False`)과 DB 실패(`DatabaseWriteError`)를 구분하고, UI 메시지도 `삭제 대상 없음`과 `삭제 실패`로 나눕니다.

## 키워드 입력 규칙

- 최소 1개 이상의 일반 키워드가 필요합니다.
- 제외어-only 입력(예: `-광고 -코인`)은 탭 추가/이름 변경/설정 가져오기에서 차단됩니다.
- 같은 의미의 `canonical query`가 이미 열린 경우(예: 공백/대소문자 차이) 새 탭 대신 기존 탭으로 이동합니다.
- API 검색어는 모든 양(+) 키워드를 공백 결합해 사용합니다. 예: `인공지능 AI -광고` → API query: `인공지능 AI`
- 대표 키워드(`db_keyword`)는 첫 번째 양(+) 키워드를 사용합니다. 예: `인공지능 AI -광고` → 대표 키워드: `인공지능`
- 실제 탭 범위/배지/분석/중복 판정/페이지 상태는 `query_key = build_fetch_key(parse_search_query(raw_tab_query))` 기준으로 동작합니다.
- 기존 DB에서 마이그레이션된 멀티 키워드 탭은 각 탭을 한 번 새로고침한 뒤부터 정확히 분리됩니다.
- 제목/본문/메모/제외어 텍스트 필터에서 `%`, `_`, `\`는 SQL wildcard가 아니라 literal 문자로 검색됩니다. 공백으로 분리된 여러 일반 단어는 모두 포함되어야 하는 토큰 AND 의미입니다.
- 이 token-AND 의미는 FTS backfill 완료 전후 동일하게 유지됩니다. 한글 복합어/부분 문자열도 FTS rowid prefilter로 먼저 잘리지 않습니다.

## 설정 Export/Import

- export 포맷 버전은 `1.3`이며 `export_machine_id`, `settings`, `tabs`, `keyword_groups`, `search_history`, `pagination_state`, `pagination_totals`, `window_geometry`, `saved_searches`, `tab_refresh_policies`, `automation_rules`, `publisher_aliases`를 포함합니다.
- API 자격증명(`client_id`, `client_secret`, `client_secret_enc`)은 export/import 대상에서 제외되고, `settings.auto_start_enabled`와 `settings.auto_backup_minutes`는 export/import 대상에 포함됩니다.
- import 시 `tabs`는 `canonical query` 기준 dedupe, `keyword_groups`는 merge, `search_history`는 `canonical query` 기준 imported-first dedupe 후 최대 10개로 정리합니다.
- `pagination_state`와 `pagination_totals`는 fetch key별로 병합하며 충돌 시 더 큰 값을 유지합니다.
- `saved_searches`는 이름 기준으로 기존값과 import값을 병합하고, 같은 이름은 import payload를 우선합니다. 저장된 검색의 target keyword가 비어 있거나 exclude-only이면 빈 target으로 보정하고, 날짜는 유효한 `yyyy-MM-dd`만 유지하며 시작일/종료일 역전은 자동 swap합니다.
- `tab_refresh_policies`는 canonical fetch key 기준으로 저장/조회/병합합니다. import 충돌은 import payload를 우선하며, raw 탭 키워드 key는 현재 탭/검색 의미와 맞춰 canonical key로 rebasing합니다.
- import는 `1.1`, `1.2`, `1.3`을 모두 허용하며, 자동 시작/시작 최소화는 환경 가용성에 따라 안전한 값으로 보정됩니다.
- 다른 machine의 export에서 들어온 `auto_start_enabled=true`는 로컬 시작프로그램 오등록을 막기 위해 `False`로 강제됩니다.
- 트레이를 사용할 수 없는 환경에서 import된 `start_minimized=true`는 `False`로 강제되고 경고 토스트를 표시합니다.
- 시작프로그램 기능을 사용할 수 없는 환경에서 import된 `auto_start_enabled=true`는 `False`로 강제되고, 가능한 환경에서는 실제 레지스트리 상태까지 동기화합니다.
- import로 새 탭이 추가되면 해당 탭들을 지금 새로고침할지 한 번 묻고, 동의하면 새 탭만 순차 새로고침합니다.
- import로 출처 visibility 설정이 바뀌면 기존 열린 탭도 즉시 DB reload해 목록/count/배지 기준을 새 설정과 맞춥니다.
- 이 prompt는 실제 refresh가 가능한 경우에만 표시되며, 유지보수 중이거나 이미 순차 새로고침이 실행 중이거나 API 자격증명이 유효하지 않으면 이유를 먼저 안내하고 prompt는 생략합니다.

## 트레이/시작 최소화 규칙

- `--minimized` 또는 `start_minimized=true`는 시스템 트레이를 사용할 수 있을 때만 적용됩니다.
- 시스템 트레이를 사용할 수 없는 환경에서는 앱이 숨겨지지 않고 일반 창으로 시작합니다.
- 트레이 미지원 환경에서는 설정 창의 `시작 시 최소화 상태로 시작` 옵션이 비활성화됩니다.
- 시스템 트레이가 없더라도 `데스크톱 알림`은 토스트 fallback과 알림음으로 동작합니다.

## 라이선스

MIT License


