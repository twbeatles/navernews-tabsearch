# Data Model: Unused Search Scope Cleanup

새 테이블·스키마 변경 없음. 기존 `news` / `news_keywords` 위에 정의되는 파생 개념만 사용한다.

## Search scope (파생 개념, 저장 없음)

- `query_key`: `news_keywords.query_key`의 정규형 값 (빈 문자열·NULL 제외). 탭의 canonical fetch key와 정확 일치로만 비교한다.
- `keyword_label`: 동일 `query_key`의 대표 표시 이름 (`news_keywords.keyword`의 최빈값; 미리보기 표시용).
- `live`: 실행 시점에 열린 키워드 탭의 fetch key 집합(keep)에 포함됨.
- `dead`: keep에 없음. 정리 대상 후보 (단, soft-delete 행만 가진 범위는 삭제할 멤버십이 없어 0건).

## Membership (기존 행)

- `news_keywords(link, query_key, keyword, is_duplicate)`. 정리 기능이 삭제하는 유일한 행 종류.
- 삭제 조건: `query_key NOT IN keep` AND 연결된 `news` 행이 `COALESCE(is_deleted,0)=0`.

## Orphaned article (파생 개념, 행 유지)

- 정리 후 `news_keywords`에 소속이 0건 남은 `news` 행. 본문·읽음·북마크·메모·태그 유지.
- 건수 정의: `SELECT COUNT(*) FROM news n WHERE NOT EXISTS (SELECT 1 FROM news_keywords nk WHERE nk.link = n.link) AND COALESCE(n.is_deleted,0)=0`.
- 미리보기 시점의 예상 고아 수와 실행 후 실제 고아 수의 정의가 동일해야 한다 (멱등성·SC-005의 전제).

## Validation rules

- keep 집합이 비어 있으면 preview·cleanup 모두 `ValueError` (FR-004).
- keep 집합 원소는 strip 후 빈 문자열 제거, 중복 제거, 정렬하지 않음 (순서 무의미).
- 삭제 묶음은 단일 트랜잭션 (`with conn:`) — 전체 적용 또는 전체 롤백 (FR-010).
- 중복 플래그 재계산은 삭제와 같은 트랜잭션 안에서 스코프 한정으로만 수행 (FR-006).
