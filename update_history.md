# Update History

## v32.7.2 (Unreleased)
- **Risk Remediation + Docs Alignment (2026-02-20)**:
  - Added refresh lock recovery contract: `refresh_all()` now returns bool start status and `_safe_refresh_all()` restores lock on early-exit paths.
  - Fixed load-more keyword binding after tab rename by using live tab state instead of creation-time closure value.
  - Added positive-keyword validation path (`has_positive_keyword`) and blocked exclude-only tab inputs across add/rename/import flows.
  - Introduced per-tab pagination state (`TabFetchState`) and request start-index tracking for more reliable incremental fetch.
  - Unified keyword group storage into `news_scraper_config.json` (`keyword_groups`) with legacy `keyword_groups.json` migration support.
  - Wired `minimize_to_tray` to actual minimize event handling and exposed it in settings export/import roundtrip.
  - Normalized auto-refresh interval options to include `2시간` (replacing `3시간` in UI/runtime mapping).
  - Added regression tests: `test_risk_fixes.py`, `test_keyword_groups_storage.py` and expanded existing guard tests.
  - Synchronized docs (`README.md`, `claude.md`) with current runtime behavior and settings schema.

## v32.7.1 (Current)
- **Stability + UX Hardening (2026-02-19)**:
  - Added single-instance guard at startup; second launch now shows "already running" message and exits.
  - Fixed startup registry command for source mode to target `news_scraper_pro.py` instead of `core/startup.py`.
  - Re-applies startup registry entry when only `start_minimized` option changes while auto-start is enabled.
  - Added missing settings plumbing for `sound_enabled` and `api_timeout` across settings dialog, apply flow, import/export JSON.
  - Added API timeout setting UI (5~60 seconds).
  - Switched API key validation in settings dialog to async worker to avoid UI freeze.
  - Switched long-running data cleanup actions in settings dialog to async workers.
  - Fixed settings import tab merge to dedupe against both existing tabs and duplicates inside imported list.
  - Hardened fatal MainApp init path to re-raise after critical error dialog.
  - Unified crash log path to app directory in bootstrap.

## v32.7.0
- **Full Code Split Refactor (2026-02-18)**:
  - Split monolithic runtime into `core/` and `ui/` packages.
  - Converted `news_scraper_pro.py` to thin entrypoint + re-export compatibility layer.
  - Preserved public compatibility (`import news_scraper_pro as app`, direct script launch).
  - Added compatibility wrapper modules at root for legacy import paths.
  - Added backup guard utility (`core/backup_guard.py`) and regression tests for wrappers/entrypoint/backup validation.
  - Updated tests to validate behavior and contracts against the new module layout.

## v32.6.0
- **One-shot Stability + Modular Refactor (2026-02-18)**:
  - **Worker Lifecycle**: Migrated fetch worker lifecycle to request-id aware registry to avoid stale callback cleanup races.
  - **No Force Terminate**: Removed forceful thread termination path from app shutdown and standardized graceful stop/quit/wait cleanup.
  - **Fetch Dedupe Key**: Dedupe now uses `(search_keyword + exclude_words)` composite key.
  - **Restore Flow Hardening**: Backup restore UI now schedules pending restore for next startup instead of in-process file overwrite.
  - **Startup Pending Restore**: `main()` applies pending restore before app initialization.
  - **Config Consistency**: Unified config load/save schema handling and switched writes to atomic save helper.
  - **Filter UX Fix**: Date filter toggle now triggers immediate reload for both ON and OFF.
  - **Module Split Added**: `query_parser.py`, `config_store.py`, `backup_manager.py`, `worker_registry.py`, `workers.py`.
- **Repository Cleanup (2026-02-18)**:
  - Moved obsolete helper files and generated artifacts into `backups/repo_cleanup_20260218_222833/`.
  - Cleanup scope: `find_classes*.py`, `classes_list*.txt`, legacy `news_scraper.spec`, root/test `__pycache__`, and `build/`.
  - Kept runtime paths stable (`news_scraper_pro.py`, config/db/log locations unchanged).

## v32.5.0
- **Stability Patch (2026-02-12)**:
  - **Thread/Tab Lifecycle**: Ensured `NewsTab.cleanup()` runs on tab close and removed forceful `QThread.terminate()` usage in favor of `stop -> quit -> wait`.
  - **UI Freeze Mitigation**: Replaced unbounded DB worker waits with bounded waits and warning logs.
  - **Keyword Parsing Unification**: Added `parse_tab_query(raw)` and applied it across fetch/query/badge/rename paths while keeping legacy "first token DB key" policy.
  - **Rename Consistency Fix**: Tab rename now updates `news_keywords.keyword` first, then syncs `news.keyword` for backward compatibility.
  - **Backup/Restore Integrity**: Added SQLite backup API-based snapshot flow with fallback copy and explicit `-wal`/`-shm` sidecar handling.
  - **Config Save Hardening**: Switched config writes to temp file + `os.replace` atomic swap.
- **UI/UX Refactoring**: Major overhaul of the user interface with a modern, flat design inspired by Tailwind CSS.
- **Modularization**: Extracted style definitions (Colors, AppStyle, UIConstants) into a separate `styles.py` module to improve code maintainability and readability.
- **Dark Mode Improvements**: Enhanced dark mode color palette for better contrast and visual appeal.
- **Toast Notifications**: Replaced standard message boxes with non-intrusive toast notifications for success/error messages.
- **Code Optimization**: Implemented `lru_cache` for regex patterns and optimized `DatabaseManager` with connection pooling.
- **Spec Update**: Updated `news_scraper_pro.spec` for optimized PyInstaller builds, excluding unnecessary libraries to reduce file size.

## v32.1
- **PyInstaller**: Initial PyInstaller support.
- **Bug Fixes**: Addressed minor stability issues.
