# 구현 감사 후속 적용 결과
작성일: 2026-03-14

## 상태

- 감사 문서에서 제안했던 기능 정합성 항목을 이번 작업에서 반영했습니다.
- 코드뿐 아니라 `README.md`, `claude.md`, `gemini.md`, `update_history.md`, `news_scraper_pro.spec`까지 함께 재검토해 설명과 실제 동작을 맞췄습니다.
- 검증 결과:
  - `pytest -q` -> `136 passed, 5 subtests passed`
  - `pyright` -> `0 errors, 0 warnings, 0 informations`

## 완료된 항목

### 1. `query_key` 기반 탭 독립화

- `news_keywords`를 `PRIMARY KEY (link, query_key)` 구조로 마이그레이션했습니다.
- 대표 키워드(`keyword` / `db_keyword`)는 호환 메타데이터로 유지하고, 실제 탭 범위/배지/분석/중복 판정은 `query_key` 기준으로 전환했습니다.
- 기존 DB는 보존되며, 멀티 키워드 탭은 새 `query_key` 범위가 비어 있을 경우 1회성 안내 후 새로고침으로 정확히 분리됩니다.

### 2. DB 공개 인터페이스 확장

- `upsert_news(...)`가 `query_key`를 받도록 확장됐습니다.
- `fetch_news`, `count_news`, `get_counts`, `get_unread_count`, `mark_query_as_read`, `get_top_publishers`가 `query_key` 지원으로 확장됐습니다.
- `get_unread_counts_by_query_keys(...)`를 추가해 탭 배지를 `query_key` 기준으로 일괄 집계합니다.
- 기존 keyword-only 호출은 하위 호환으로 유지됩니다.

### 3. `더 불러오기` 상태 영속화 보강

- 설정 스키마에 `pagination_totals`를 추가했습니다.
- `pagination_state(fetch_key -> last_start_index)`와 `pagination_totals(fetch_key -> last_api_total)`를 함께 저장합니다.
- 탭 생성, 재시작, 정렬/날짜 필터 변경, DB 재로딩 이후에도 `cursor + total` 기준으로 버튼 상태를 다시 계산합니다.
- `total`이 없으면 보수적으로 활성화하되 `next_start > 1000`이면 즉시 비활성화합니다.

### 4. 즉시 복원 API 원자성 정리

- `restore_backup()`와 `apply_pending_restore_if_any()`가 동일한 restore helper를 사용합니다.
- 순서는 `사전 검증 -> snapshot 생성 -> staged copy -> 실패 시 rollback`으로 통일했습니다.
- `restore_db=True`인데 DB 백업이 없으면 어떤 파일도 덮어쓰기 전에 바로 실패합니다.
- `-wal`, `-shm` 처리 정책도 두 경로에서 동일하게 맞췄습니다.

### 5. 설정 export/import 확장

- export 포맷 버전은 `1.1`입니다.
- export 범위:
  - `settings`
  - `tabs`
  - `keyword_groups`
  - `search_history`
  - `pagination_state`
  - `pagination_totals`
  - `window_geometry`
- API 자격증명은 계속 제외합니다.
- import 시 `tabs` dedupe, `keyword_groups` merge, `search_history` imported-first dedupe, `pagination_state`/`pagination_totals` key별 병합(큰 값 유지)을 적용합니다.
- tray가 없으면 import된 `start_minimized=true`는 `False`로 강제합니다.

### 6. 알림 fallback 정리

- `show_desktop_notification()`은 tray가 있으면 tray message를 사용합니다.
- tray가 없으면 같은 메시지를 토스트로 보여주고, `sound_enabled=True`면 알림음도 재생합니다.
- `show_tray_notification()`은 tray 전용으로 유지했습니다.

### 7. 문서 동기화

- `README.md`를 `query_key`, `pagination_totals`, export/import 1.1, 알림 fallback 기준으로 갱신했습니다.
- `claude.md`, `gemini.md`, `update_history.md`에도 2026-03-14 기준 보강 메모를 추가했습니다.
- 이 문서는 완료 상태 기준으로 다시 정리했습니다.
- `VERSION`은 올리지 않았습니다.

### 8. `.spec` / `.gitignore` 재검토

- `news_scraper_pro.spec`는 이번 패스에서도 추가 hidden import/exclude 수정이 필요하지 않음을 다시 확인했습니다.
- 이번 변경은 표준 라이브러리와 기존 번들 모듈 범위 안에서 끝나므로 `.spec` 변경은 검토 메모 보강 수준이면 충분했습니다.
- `.gitignore`는 이미 build/cache/runtime 복구 산출물까지 커버하고 있어 추가 ignore 항목은 넣지 않았습니다.

## 유지한 기본 정책

- 기사 `is_read`, `is_bookmarked`, `notes`, 삭제 상태는 계속 `news` 테이블 기준의 전역 상태입니다.
- 따라서 같은 링크가 여러 `query_key`에 동시에 속하면 읽음/북마크 상태는 모든 탭에서 같이 보입니다.
- 멀티 키워드 탭의 과거 혼합 데이터는 자동 재분배하지 않고, 각 탭을 한 번 새로고침한 뒤부터 정확히 분리됩니다.
