# Implementation Audit Follow-through (2026-04-18)

## Scope

This document records the follow-through work for the implementation audit items that were identified on 2026-04-18.

## Resolved Items

1. Maintenance completion ordering
   - `SettingsDialog` no longer calls `on_database_maintenance_completed(...)` while maintenance mode is still active.
   - The completion result is staged and flushed from `_on_data_task_finished(...)` immediately after `end_database_maintenance()`.
   - This guarantees open-tab reload, badge refresh, and tray-tooltip sync run after the maintenance guard is released.

2. Sequential refresh immediate notifications
   - Sequential refresh now shares the same success-side notification path as manual refresh.
   - Per-tab desktop notifications, tray notifications, and alert-keyword checks now run as each sequential tab finishes.

3. Canonical "new article" contract
   - `ApiWorker.finished` now exposes `new_count = len(new_items)`.
   - UI success messages and alert logic treat `new_items` / `new_count` as the source of truth for "new article" semantics.
   - Duplicate-titled but newly seen links are now included in notifications and refresh summaries.

4. HTTP 429 `Retry-After`
   - `ApiWorker` now parses `Retry-After` as either delta-seconds or HTTP-date.
   - The same computed wait value is used for retry sleep and for `last_error_meta.cooldown_seconds`.
   - Invalid or missing `Retry-After` values still fall back to the existing bounded cooldown policy.

5. Remaining pyright cleanup
   - `InterruptibleReadWorker` now uses an explicit read-connection protocol type.
   - The affected test doubles were narrowed or annotated so `pyright` returns to a clean baseline.

## Packaging / Repo Hygiene Revalidation

- `news_scraper_pro.spec` was re-reviewed for this pass.
- The 2026-04-18 changes rely on stdlib or already-bundled dependencies only, so no hidden import, exclude, or data changes were required.
- `.gitignore` was re-reviewed with `git status --ignored --short`.
- Existing rules still cover `build/`, `dist/`, `__pycache__/`, `.pytest_cache/`, local DB/config/log files, and other runtime artifacts, so no new ignore entry was required.

## Verification

- `python -m pytest -q` => `236 passed, 5 subtests passed`
- `pyright` => `0 errors, 0 warnings, 0 informations`
- `pyinstaller --noconfirm --clean news_scraper_pro.spec` => success
- Output artifact: `dist/NewsScraperPro_Safe.exe`
