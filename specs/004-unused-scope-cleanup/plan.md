# Implementation Plan: Unused Search Scope Cleanup

**Branch**: `004-unused-scope-cleanup` | **Date**: 2026-09-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-unused-scope-cleanup/spec.md`

## Summary

GAP-008의 잔여 항목(닫힌 탭이 남긴 죽은 `query_key` 스코프의 멤버십 누적)을 해소한다. DB에 `keep 집합 기반의 미리보기·정리 API` 2개를 추가하고, 통계 화면의 저장소 지표에 사용하지 않는 범위 수와 정리 진입점을 둔다. 정리 실행은 기존 유지보수 진입 가드(`begin_database_maintenance`)를 통과해야 하며, 삭제된 멤버십과 title_hash를 공유하는 live 범위의 중복 플래그는 스코프 한정 재계산으로 정확히 유지한다. 고아 기사 행은 유지하고 건수만 보고한다.

## Technical Context

**Language/Version**: Python 3.10+ (repo convention; `X | Y` unions, `tomllib` 미사용 구간과 동일 수준)

**Primary Dependencies**: PyQt6 (UI), sqlite3 (stdlib), 기존 `core` 믹스인 구조

**Storage**: 로컬 SQLite (`news`, `news_keywords` — PK `(link, query_key)`, FK `link → news(link) ON DELETE CASCADE`)

**Testing**: pytest (`tests/test_scope_cleanup.py` 신규; `DatabaseManager(tmp, max_connections=...)` + `upsert_news_detailed` 시딩 — `test_audit_remediation_20260920.py`와 동일 패턴)

**Target Platform**: Windows 데스크톱 (PyQt6)

**Project Type**: desktop-app (PyQt6)

**Performance Goals**: 죽은 범위 50개·소속 10,000건 정리 미리보기+실행이 체감 지연 없이 완료 (단일 DELETE 문 + 스코프 한정 재계산; 전체 DB 스캔 금지)

**Constraints**: `DatabaseWriteError`/`DatabaseQueryError` 분리 유지; facade import 경로 유지 (`core.database.DatabaseManager`); `news_fts` 미사용; FTS hard prefilter 재활성화 금지; `_recalculate_duplicate_flags_for_entire_database`를 per-cleanup 경로에서 호출 금지 (수동 복구 전용)

**Scale/Scope**: 단일 사용자 아카이브; 정리 1회당 수만 membership 행 규모

## Constitution Check

`.specify/memory/constitution.md`는 미기입 템플릿이므로 advisory로만 참조한다. 대신 repo 거버넌스(`AGENTS.md`)를 gate로 적용한다:

- [x] root compatibility wrapper/facade import를 깨지 않는다 → 신규 믹스인 추가만, 기존 시그니처 변경 없음
- [x] 검색 의미는 canonical query / fetch key 기준 → keep 집합은 `_canonical_fetch_key_for_keyword`와 동일한 정규형 키로만 비교 (정확 일치, 퍼지 없음)
- [x] 중복 플래그 재계산은 스코프 한정이 기본 → `_collect_affected_query_key_hashes` + `_recalculate_duplicates_for_affected` 조합, 전체 재계산 호출 금지
- [x] `fetch_news()` 자격증명 guard와 무관한 영역 (DB 정리 전용) → 해당 없음
- [x] DB write/query 실패는 각각 `DatabaseWriteError`/`DatabaseQueryError` → preview는 query, cleanup은 write로 감쌈
- [x] 유지보수 상호배제 → `begin_database_maintenance("scope_cleanup")` 선행, 실패 시 상태 변경 없음

## Project Structure

### Documentation (this feature)

```text
specs/004-unused-scope-cleanup/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── scope-cleanup.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
core/
├── _db_duplicates.py                      # 기존 스코프 한정 재계산 헬퍼 재사용
├── database.py                            # 변경 없음 (믹스인 경유)
└── db_mutations_support/
    ├── mixin.py                           # _NewsScopeCleanupMixin 추가
    └── scope_cleanup.py                   # 신규: preview/cleanup + 결과 dataclass
tests/
└── test_scope_cleanup.py                  # 신규 포커스 회귀 테스트
ui/
├── _main_window_analysis.py               # 저장소 지표에 미사용 범위 수 + 정리 버튼
├── main_window_support/base_support/
│   └── maintenance.py                     # operation label에 scope_cleanup 추가
└── main_window_support/ (analysis mixin)  # 미리보기·확정·결과 흐름 (analysis 영역)
```

**Structure Decision**: 기존 믹스인 분해 구조(`db_mutations_support/`, `_db_duplicates.py`, `_db_analytics.py`)를 그대로 따르고, 정리 전용 신규 모듈 1개 + 테스트 1개 + UI 배선만 추가한다.

## Complexity Tracking

해당 없음 (gate 위반 없음).
