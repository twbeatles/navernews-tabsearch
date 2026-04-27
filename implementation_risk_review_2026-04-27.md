# 2026-04-27 구현 리스크 계획 반영 기록

## 처리 상태

`implementation_risk_review_2026-04-27.md`에서 정리한 우선 수정 5개, 중간 우선순위 5개, 기능 후보 5개를 단일 변경 배치로 구현했다. 기존 삭제 상태인 `implementation_audit_2026-04-18.md`는 사용자 변경으로 보고 복구하지 않았다.

## 구현된 핵심 변경

- DB 단건 액션 계약:
  - `update_status()`는 대상 row가 없으면 `False`, SQLite 쓰기 실패는 `DatabaseWriteError`로 처리한다.
  - `get_note()`는 조회 실패를 `DatabaseQueryError`로 올리고, UI는 메모 다이얼로그를 열지 않는다.
  - `delete_link()`는 삭제 대상 없음과 DB 실패를 구분해 UI 메시지도 분리한다.
- 렌더링/링크 안전성:
  - 기사 카드의 publisher, date, tag, action 주변 동적 문자열을 렌더 직전에 escape한다.
  - 외부 기사 열기는 `http`와 `https` scheme만 허용한다.
- 백업/worker/export 안정성:
  - pending restore 성공 후 `pending_restore.json`을 `.applied`로 atomic rename한 뒤 best-effort 삭제한다.
  - CSV snapshot export는 iterator 생성 직후부터 `finally close()` 경로를 보장한다.
  - 429 `Retry-After`는 30초 이하만 worker 내부 sleep 재시도하고, 초과값은 cooldown meta로 넘긴다.
  - 자동 새로고침 네트워크 오류 누적은 `error_meta.kind`를 우선 사용한다.
- 기능:
  - 차단 출처는 API 결과를 DB에 저장하되 목록, count, 분석, CSV에서 숨긴다.
  - 선호 출처는 `선호 출처만` 필터가 켜진 경우에만 적용한다.
  - 자유 태그 CRUD, 카드 태그 배지, 태그 필터, CSV 태그 컬럼을 추가했다.
  - 저장된 검색과 탭별 자동 새로고침 정책을 추가했다.
  - 복원 예약 전 dry-run 요약을 추가했다.
- 설정 구조:
  - `core.config_store`는 기존 import 호환 facade로 유지한다.
  - 실제 구현은 `core.config_store_impl`, 공통 출처/태그 정규화는 `core.content_filters`로 분리했다.

## 주요 코드 위치

- DB schema/query/mutation: `core/_db_schema.py`, `core/_db_queries.py`, `core/_db_mutations.py`, `core/_db_analytics.py`, `core/database.py`
- 설정 schema/정규화: `core/config_store.py`, `core/config_store_impl.py`, `core/content_filters.py`
- worker/export/backup: `core/workers.py`, `core/backup.py`, `ui/_main_window_settings_io.py`, `ui/dialogs.py`
- UI: `ui/news_tab_support/*.py`, `ui/main_window_support/*.py`, `ui/_main_window_tabs.py`, `ui/_settings_dialog_content.py`, `ui/settings_dialog.py`
- 회귀 테스트: `tests/test_implementation_batch_20260427.py`

## 문서/패키징 정합성

- `README.md`, `claude.md`, `gemini.md`, `project_structure_analysis.md`, `update_history.md`를 새 기능과 구조에 맞게 갱신했다.
- `news_scraper_pro.spec`는 새 기능이 기존 stdlib/PyQt/requests 번들 범위 안에 있음을 재검토했고 추가 hidden import/exclude/data 변경은 필요하지 않았다.
- `.gitignore`에는 복원 적용 성공 후 남을 수 있는 `pending_restore.json.applied`를 추가했다.

## 검증

- `python -m pytest -q` => `258 passed, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`
- `python -m pytest tests/test_encoding_smoke.py -q` => `2 passed`
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success (`dist/NewsScraperPro_Safe.exe`)
