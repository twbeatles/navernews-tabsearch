# Research: Unused Search Scope Cleanup

## Decision 1: DB API는 keep-집합 기반 2함수로 분리한다

- **Decision**: `preview_scope_cleanup(keep_query_keys)` (읽기 전용) + `cleanup_unused_scopes(keep_query_keys)` (원자적 쓰기). UI는 keep 집합(열린 탭의 정규형 fetch key)만 전달하고, 죽은 범위 판정은 DB가 매번 재계산한다. 미리보기 목록을 실행 시점에 재사용하지 않아 preview→execute 사이 탭 변경 TOCTOU를 없앤다.
- **Rationale**: DB는 열린 탭을 모른다. 판정 기준(keep 집합)을 호출자가 주입하면 DB는 dumb하게 유지되고, 기존 `_append_news_scope_clause`의 정규형 키 의미와 일치한다.
- **Alternatives considered**: 탭 변경 시점에 멤버십을 함께 삭제 (아카이브 전체 검색에서 과거 기사를 찾아야 한다는 감사 판단과 충돌하므로 기각). 주기적 자동 정리 (spec이 수동 실행으로 한정하므로 기각).

## Decision 2: 삭제 대상은 soft-delete되지 않은 행의 멤버십으로 한정한다

- **Decision**: `DELETE ... WHERE query_key NOT IN keep AND link IN (SELECT link FROM news WHERE COALESCE(is_deleted,0)=0)`. tombstone 행의 멤버십은 보존 기간·회수 정책(`delete_old_news_chunked`)이 관장하므로 정리 기능이 간섭하지 않는다.
- **Rationale**: 클라우드 삭제 전파가 tombstone 행에 의존한다. 멤버십을 먼저 지우면 전파 대상 추적에 구멍이 날 수 있다.
- **Alternatives considered**: tombstone 멤버십도 함께 삭제 (회수 정책과 책임이 겹쳐 기각).

## Decision 3: 중복 플래그는 삭제된 title_hash와 겹치는 live 범위에만 재계산한다

- **Decision**: 삭제 전 `_collect_affected_query_key_hashes(conn, "n.title_hash IN (...deleted hashes...)", include_deleted=False)`로 live 그룹을 수집한 뒤, 삭제 후 `_recalculate_duplicates_for_affected(conn, affected)`를 같은 트랜잭션에서 호출한다. `CROSS JOIN` 순서 힌트를 건드리지 않고 기존 헬퍼를 그대로 재사용한다.
- **Rationale**: ISSUE-001에서 확립된 스코프 한정 패턴. 전체 재계산은 수동 복구 전용이라는 repo 원칙을 유지한다.
- **Alternatives considered**: 삭제 후 live 범위 전체 재계산 (아카이브 규모에 비례해 느려지므로 기각).

## Decision 4: keep 집합이 비면 DB가 거부한다

- **Decision**: `cleanup_unused_scopes`/`preview_scope_cleanup`는 빈 keep 집합에 `ValueError`를 던진다 (프로그래머 오류 가드). UI는 키워드 탭이 없을 때 정리 버튼을 비활성화하고 안내한다 (이중 방어).
- **Rationale**: 보관 탭만 열린 상태에서 전체 멤버십이 한 번에 지워지는 사고를 원천 차단한다. FR-004.
- **Alternatives considered**: 빈 keep 허용 후 전체 삭제 (파괴적, 기각). 보관 탭의 암묵 키를 keep에 자동 포함 (암묵 동작, 기각).

## Decision 5: 실행 게이트는 기존 유지보수 진입을 재사용한다

- **Decision**: UI는 `begin_database_maintenance("scope_cleanup")` → (실패 시 사유 표시 후 종료) → 동기 실행 → `end_database_maintenance()` → 통계 새로고침. operation label 맵에 `"scope_cleanup": "사용하지 않는 범위 정리"`를 추가한다.
- **Rationale**: T008–T010에서 확립된 상호배제(실행 중 fetch가 실제 종료되어야 진입) 원칙을 그대로 따른다. 정리 대상 10,000건 단일 DELETE는 ms 단위라 워커 분리가 불필요하다.
- **Alternatives considered**: 전용 백그라운드 워커 (오버헤드 대비 이득 없음, 기각).

## Decision 6: UI 진입점은 통계 화면의 저장소 지표다

- **Decision**: `_build_storage_group`에 "사용하지 않는 범위: N개" 행을 추가하고, 렌더 영역에 "사용하지 않는 범위 정리" 버튼을 둔다. 미리보기는 `QMessageBox` (대상 범위·예상 삭제·고아 예상), 확정 후 결과도 `QMessageBox` + toast로 보고한다.
- **Rationale**: 감사 권고 12가 지목한 위치이며, 사용자가 수치를 보고 바로 행동할 수 있다.
- **Alternatives considered**: 설정 화면·DB 최적화 메뉴 (수치와 멀어 맥락이 끊기므로 기각).

## Decision 7: 결과 계약은 frozen dataclass 2종이다

- **Decision**: `ScopeCleanupPreview(dead_scopes: Tuple[DeadScope, ...], removable_memberships: int, orphaned_articles: int)`, `DeadScope(query_key, keyword_label, membership_count)`, `ScopeCleanupResult(removed_memberships: int, remaining_scopes: int, orphaned_articles: int, recalculated_groups: int)`. `NewsUpsertResult`와 동일한 frozen dataclass 관례.
- **Rationale**: T002의 구조화 결과 계약 흐름과 일치하고, UI 보고·테스트 단언이 명확해진다.
- **Alternatives considered**: dict 반환 (타입 안정성·단언 명확성이 떨어져 기각).
