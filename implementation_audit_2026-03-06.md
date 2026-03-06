# Implementation Audit (2026-03-06)

## 점검 범위
- 문서 기준: `README.md`, `claude.md`
- 코드 기준: `core/backup.py`, `core/database.py`, `ui/main_window.py`, `ui/news_tab.py`, `ui/settings_dialog.py`, `ui/dialogs.py`
- 테스트 기준: `python -m pytest -q` -> `105 passed, 5 subtests passed` (감사 시점)

## 핵심 결론
- 전체 테스트는 통과했지만, 운영 중 사용자 데이터/상태 일관성에 영향을 줄 수 있는 구현 리스크가 있었습니다.
- 2026-03-06 후속 구현으로 감사 항목 5건을 모두 코드/테스트/문서에 반영했습니다.

## 감사 항목과 반영 상태

### 1) 자동 시작 백업이 수동 백업까지 같이 밀어내는 보존 정책
- 문제:
  - 자동 생성되는 설정-only 백업이 수동 `설정+DB` 백업과 동일 retention pool을 사용했습니다.
- 조치:
  - `AutoBackup.create_backup(..., trigger=...)` 메타를 추가했습니다.
  - 자동/수동 백업 retention을 분리했습니다 (`MAX_AUTO_BACKUPS`, `MAX_MANUAL_BACKUPS`).
- 반영 위치:
  - `core/backup.py`
- 검증:
  - `tests/test_backup_restore_mode.py`

### 2) 데이터 정리/전체 삭제 후 열린 탭, 북마크 탭, 배지가 즉시 갱신되지 않음
- 문제:
  - 설정창이 별도 `DatabaseManager`로 DB를 직접 수정한 뒤 메인 UI 동기화를 하지 않았습니다.
- 조치:
  - 설정창 완료 콜백이 부모 `MainApp.on_database_maintenance_completed(...)`를 호출하도록 변경했습니다.
  - 메인 창이 열린 탭, 북마크 탭, 배지, 트레이 툴팁을 재동기화하도록 보강했습니다.
- 반영 위치:
  - `ui/settings_dialog.py`
  - `ui/main_window.py`
- 검증:
  - `tests/test_settings_dialog_maintenance.py`

### 3) `모두 읽음 -> 탭 전체`가 제외어 탭 의미를 보존하지 못함
- 문제:
  - `탭 전체` 경로가 `db_keyword`만 기준으로 읽음 처리하여 제외어가 무시됐습니다.
- 조치:
  - `DatabaseManager.mark_query_as_read(...)`를 추가했습니다.
  - `NewsTab.mark_all_read()`의 `탭 전체` 경로를 `exclude_words` 보존 방식으로 전환했습니다.
- 반영 위치:
  - `core/database.py`
  - `ui/news_tab.py`
- 검증:
  - `tests/test_db_queries.py`
  - `tests/test_risk_fixes.py`

### 4) 탭별 언론사 분석이 전체 탭 쿼리가 아니라 `db_keyword`만 사용함
- 문제:
  - `AI -광고`, `AI -코인`처럼 같은 DB 키워드를 공유하는 탭이 동일 분석 결과를 보여줄 수 있었습니다.
- 조치:
  - 분석 콤보가 raw tab query를 보존하도록 수정했습니다.
  - `DatabaseManager.get_top_publishers(..., exclude_words=...)` 확장으로 제외어 집계를 반영했습니다.
- 반영 위치:
  - `ui/main_window.py`
  - `core/database.py`
- 검증:
  - `tests/test_db_queries.py`
  - `tests/test_risk_fixes.py`

### 5) 백업 목록의 시간 표시 포맷이 생성 포맷과 맞지 않음
- 문제:
  - 백업 생성은 마이크로초를 포함했지만 목록 표시는 초 단위 포맷만 처리했습니다.
- 조치:
  - `BackupDialog.format_backup_timestamp(...)`를 추가해 마이크로초/초 단위/ISO fallback을 모두 지원하게 했습니다.
  - 목록에 `자동`/`수동` 출처 라벨도 함께 표시합니다.
- 반영 위치:
  - `ui/dialogs.py`
- 검증:
  - `tests/test_backup_restore_mode.py`

## 후속 반영 결과
- 코드 반영 완료
- 테스트 추가 완료
- `README.md`, `claude.md`, `gemini.md`, `update_history.md` 정합성 반영 완료
- `news_scraper_pro.spec` 재검토 완료: 이번 패스에서는 추가 수정 불필요

## 최종 검증
- `python -m pytest -q` -> `112 passed, 5 subtests passed`
