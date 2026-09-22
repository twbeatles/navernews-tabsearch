# Contract: Scope Cleanup

`DatabaseManager`에 추가되는 공개 API 2종의 계약이다. facade import 경로(`core.database.DatabaseManager`)는 그대로이며, 신규 타입은 `core.db_mutations_support.scope_cleanup`에서 정의한다.

## `preview_scope_cleanup(keep_query_keys) -> ScopeCleanupPreview`

- 입력: 열린 탭의 정규형 fetch key 컬렉션. 비어 있으면 `ValueError`.
- 출력 (`ScopeCleanupPreview`, frozen):
  - `dead_scopes: Tuple[DeadScope, ...]` — `DeadScope(query_key: str, keyword_label: str, membership_count: int)`, `membership_count` 내림차순.
  - `removable_memberships: int` — 삭제될 멤버십 총합 (soft-delete 제외 후).
  - `orphaned_articles: int` — 정리 시 소속이 0건이 될 기사 수 (data-model 정의와 동일).
- 부작용 없음. 실패는 `DatabaseQueryError`.

## `cleanup_unused_scopes(keep_query_keys) -> ScopeCleanupResult`

- 입력: 상동. 비어 있으면 `ValueError` (삭제 전 검증).
- 동작 (단일 트랜잭션):
  1. 삭제 대상 멤버십의 title_hash 집합 확보.
  2. 삭제 대상 삭제 (soft-delete 행 제외).
  3. title_hash가 겹치는 live 범위에 `_recalculate_duplicates_for_affected`.
- 출력 (`ScopeCleanupResult`, frozen):
  - `removed_memberships: int`
  - `remaining_scopes: int` — 정리 후 `DISTINCT query_key` 수.
  - `orphaned_articles: int`
  - `recalculated_groups: int` — 재계산이 닿은 (query_key, title_hash) 그룹 수.
- 동일 keep으로 즉시 재실행하면 `removed_memberships=0`인 결과가 나온다 (멱등성).
- 실패는 `DatabaseWriteError` (트랜잭션 롤백 후).

## UI 계약 (사용자 가시 행위)

- 통계 저장소 지표에 `storage_unused_scopes` 행 표시 (FR-001).
- 미리보기에는 범위별 이름·건수, 총 삭제 예상, 고아 예상을 표시 (FR-002).
- 결과에는 삭제·잔여·고아 실측을 표시 (FR-008).
- 키워드 탭 0개: 정리 진입 불가 + 안내 (FR-004).
- 수집/유지보수 중: `begin_database_maintenance` 실패 사유 표시 (FR-007).
