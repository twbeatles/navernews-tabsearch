# Tasks: Unused Search Scope Cleanup

**Input**: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `contracts/scope-cleanup.md`

## Phase 1: Foundation

- [x] T001 Add failing focused regression tests for preview/cleanup behavior in `tests/test_scope_cleanup.py`
- [x] T002 Define frozen `DeadScope`/`ScopeCleanupPreview`/`ScopeCleanupResult` contracts in `core/db_mutations_support/scope_cleanup.py` without breaking facades

## Phase 2: User Story 1 — Preview and clean dead scopes (P1)

**Independent Test**: with one live scope and two dead scopes seeded, the preview lists exactly the dead scopes with counts, cleanup deletes only dead memberships, and the report shows removed/remaining/orphan counts.

- [x] T003 [US1] Implement `preview_scope_cleanup(keep)` read query in `core/db_mutations_support/scope_cleanup.py`
- [x] T004 [US1] Implement atomic `cleanup_unused_scopes(keep)` with tombstone exclusion in `core/db_mutations_support/scope_cleanup.py`
- [x] T005 [US1] Wire `_NewsScopeCleanupMixin` into `core/db_mutations_support/mixin.py`
- [x] T006 [US1] Add "unused scope" row and cleanup entry button to the statistics storage UI in `ui/_main_window_analysis.py`
- [x] T007 [US1] Pass scope cleanup regression tests including preview accuracy and idempotent rerun

## Phase 3: User Story 2 — Open tabs and shared articles unaffected (P1)

**Independent Test**: an article shared between a live and a dead scope remains listed in the live tab with identical read/bookmark/tag state after cleanup, and live scopes never appear as targets.

- [x] T008 [US2] Recalculate duplicate flags for affected live groups only via `_collect_affected_query_key_hashes` + `_recalculate_duplicates_for_affected` in `core/db_mutations_support/scope_cleanup.py`
- [x] T009 [US2] Derive the keep set from open tabs at execution time in `ui/_main_window_analysis.py`
- [x] T010 [US2] Pass shared-article, scope-isolation, and flag-correctness regression tests in `tests/test_scope_cleanup.py`

## Phase 4: User Story 3 — Mutual exclusion with fetch/maintenance (P2)

**Independent Test**: cleanup is refused with a reason while a fetch worker runs and succeeds after the worker finishes; a second maintenance operation cannot overlap it.

- [x] T011 [US3] Add `"scope_cleanup"` operation label in `ui/main_window_support/base_support/maintenance.py`
- [x] T012 [US3] Gate the UI cleanup flow on `begin_database_maintenance("scope_cleanup")` / `end_database_maintenance()` in `ui/_main_window_analysis.py`

## Phase 5: User Story 4 — Result consistency and rerun stability (P2)

**Independent Test**: statistics numbers match the database right after cleanup, remaining scopes show correct duplicate flags, and an immediate rerun reports zero deletions.

- [x] T013 [US4] Refuse empty keep sets (`ValueError`) in `core/db_mutations_support/scope_cleanup.py` and disable entry with guidance in `ui/_main_window_analysis.py`
- [x] T014 [US4] Report removed/remaining/orphan counts and refresh statistics after cleanup in `ui/_main_window_analysis.py`
- [x] T015 [US4] Pass orphan-keep, totals-unchanged, and totals-consistency regression tests in `tests/test_scope_cleanup.py`

## Phase 6: Validation and release prep

- [x] T016 Run focused pytest suites and pyright
- [x] T017 Run the full pytest suite and document environment-only failures honestly
- [x] T018 Bump `core.constants.VERSION` and add matching `update_history.md` entry
- [x] T019 Update `PROJECT_AUDIT.md` GAP-008 status to Fixed with evidence
- [x] T020 Re-check every completed task and leave no unchecked implementation item without an explicit reason

## Dependencies & Execution Order

- T001 precedes implementation so regressions are observable.
- T003–T007 (US1) carry the DB core; T008–T010 (US2) harden the same path and are independently testable after T002.
- T011–T012 (US3) and T013–T015 (US4) need the US1 path in place.
- T016–T020 require all selected implementation tasks.

## Implementation Strategy

Implement in audit risk order: preview/cleanup core with tombstone exclusion first, then scoped duplicate recalculation and keep-set derivation, then maintenance gating and consistency polish. Validate each focused suite before proceeding.
