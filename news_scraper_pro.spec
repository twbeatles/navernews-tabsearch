# -*- mode: python ; coding: utf-8 -*-
"""News Scraper Pro - PyInstaller onefile spec."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
project_root = Path(globals().get('SPECPATH', os.getcwd())).resolve()
main_script = str(project_root / 'news_scraper_pro.py')

datas = []
for icon_name in ('news_icon.ico', 'news_icon.png'):
    icon_path = project_root / icon_name
    if icon_path.exists():
        datas.append((str(icon_path), '.'))

# 2026-03-14 review:
# - Query-key tab scoping, pagination total persistence, restore helper unification,
#   and settings export/import 1.1 rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude change is required for this pass.
# 2026-03-16 review:
# - Cross-tab state sync, visible-only CSV export, canonical-query dedupe,
#   alert gating on newly added items, and backup wording updates rely on
#   existing stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-03-18 review:
# - Maintenance-mode fetch gating, DB-backed local pagination, mark-all-read SQL
#   scoping, backup restorable metadata, and settings export/import 1.2
#   rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-03-21 review:
# - DBQueryScope-based tab scope normalization, append skip-count pagination,
#   NewsTab fragment-cache/coalesced render, and query-path composite indexes
#   rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-03-24 review:
# - Docs/build revalidation for the 2026-03-21 performance pass confirmed the
#   same dependency surface; no additional hidden import/exclude/data change is
#   required for this pass.
# 2026-03-25 review:
# - IterativeJobWorker-based CSV export / backup verification, startup health
#   diagnostics/repair, atomic config backup rotation, and DB emergency caps
#   rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-03-27 review:
# - Read-only help-mode settings dialog, explicit date-filter apply/clear UX,
#   scope-wide unread count bookkeeping, on-demand backup verification, and
#   tray-unavailable notification fallback rely on stdlib / already-bundled
#   modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-02 review:
# - Dialog adapter isolation for export/import/backup, shutdown cleanup
#   sequencing, restorable-backup preflight tightening, selective imported-tab
#   refresh, and workspace-local pytest tempdir alignment rely on stdlib /
#   already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-05 review:
# - Full maintenance-mode DB action blocking, DatabaseQueryError-based query
#   failure surfacing, keyword-group save failure propagation, backup
#   self-verification, and import-refresh prechecks rely on stdlib /
#   already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-09 review:
# - HttpClientConfig-based worker-owned sessions, global fetch cooldown
#   gating, snapshot-based CSV export, dedicated interruptible read
#   connections, async analysis loading, and SQLite FTS5 incremental
#   backfill rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-13 review:
# - DatabaseWriteError-based fetch success gating, repeated legacy backfill
#   loops, settings validation HTTP-policy unification, and stricter encoding
#   guards rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-16 review:
# - 5xx retry promotion, request-id-based hydration cancellation cleanup,
#   staged settings import/startup reconcile, legacy backup metadata
#   compatibility + persisted verification metadata, interruptible analysis
#   reads, and FTS retry scheduling rely on stdlib / already-bundled modules
#   only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-18 review:
# - Maintenance completion sync ordering, sequential per-tab notifications,
#   `new_count`-based alert semantics, and 429 `Retry-After` parsing rely on
#   stdlib / already-bundled modules only (`email.utils` is already kept
#   explicit below for onefile runtime safety).
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-22 review:
# - RuntimePaths consolidation, SQLite-safe legacy migration hardening, and the
#   support-package splits under `core/runtime_support`, `ui/main_window_support`,
#   and `ui/news_tab_support` rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-04-27 review:
# - Publisher visibility filters, article tags, saved searches, tab-level
#   auto-refresh policies, restore dry-run summaries, config_store facade split,
#   and `core.content_filters` rely on stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-05-03 review:
# - Import merge/rebase hardening, saved-search date validation, token-AND text
#   filtering, worker cleanup deleteLater calls, and API URL normalization rely on
#   stdlib / already-bundled modules only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-05-08 review:
# - Redirect blocking, private-host URL filtering, cooldown clamping, DB
#   optimize, settings export 1.3 machine identity, scheduled settings backup,
#   CSV bookmark/note import, regex alerts, tag stats, RotatingFileHandler, and
#   compatibility-wrapper warnings rely on stdlib / already-bundled modules
#   only.
# - No additional hidden import/exclude/data change is required for this pass.
# 2026-05-10 review:
# - Local DB + cloud snapshot sync uses stdlib json/zipfile/tempfile/shutil/uuid
#   plus existing SQLite backup APIs and already-bundled PyQt worker/dialog paths.
# - Snapshot ZIPs are runtime data, not bundled datas; no additional hidden
#   import/exclude/data change is required for this pass.
# 2026-05-11 review:
# - Functional risk fixes, tag manager, Markdown digest export, archive search,
#   automation rules, and publisher alias mapping use stdlib json/tempfile/os
#   plus existing PyQt/SQLite paths only.
# - The support-package refactor only moves existing code behind compatibility
#   facades (`core.workers`, `core.backup`, `ui.dialogs`, `ui.styles`, and
#   MainApp helper modules); it does not add a new dependency surface.
# - `urllib3.contrib.emscripten` is a browser/Emscripten-only optional path and
#   is excluded from urllib3 submodule collection to avoid a non-runtime `js`
#   import warning during Windows onefile builds.
# - No additional runtime hidden import/data change is required for this pass.
# 2026-05-15 review:
# - P0/P1 functional-risk closure disabled the FTS rowid hard prefilter, added
#   automation notification suppression, moved current-tab tag/automation bulk
#   apply to DBQueryScope snapshots + IterativeJobWorker maintenance mode, and
#   expanded archive/automation/alias dialogs with existing PyQt6 widgets.
# - The changes use existing stdlib/PyQt6/SQLite/runtime modules only. No new
#   hidden import, data file, or optional dependency exclusion is required.
# 2026-05-19 review:
# - Functional-risk extension added soft-delete tombstones, cloud import preview,
#   invalid snapshot quarantine, LIKE literal escaping, and transactional
#   automation action application.
# - The implementation uses existing stdlib/PyQt6/SQLite/runtime modules only.
#   Snapshot ZIPs and `.invalid/` quarantine files are runtime data, not bundled
#   datas. No new hidden import, data file, or optional dependency exclusion is
#   required.
# 2026-05-22 review:
# - The large-module split only moves existing code into support subpackages
#   behind compatibility facades: DB query/schema/cloud merge, config store,
#   cloud snapshot helpers, AutoBackup, DB mutations, dialogs, NewsTab, and
#   MainApp helper modules.
# - The split adds no dependency surface and uses no bundled data assets. No
#   hidden import/data/exclude change is required beyond existing package
#   discovery and the current urllib3 optional-path exclusion.
# 2026-05-28 review:
# - Cloud sync export-after-import ordering, settings import automation-rule
#   dedupe, public __all__ cleanup, and pyright suppression reduction use
#   existing stdlib/PyQt6/SQLite/runtime paths only.
# - No additional hidden import, data file, or optional dependency exclusion is
#   required; the urllib3 Emscripten optional-path exclusion remains intentional.
# Single-instance IPC imports QLocalServer/QLocalSocket from QtNetwork.
# Keep requests ecosystem explicit so runtime import fallback cannot miss.
hiddenimports = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtNetwork',
    'PyQt6.sip',
    'sqlite3',
    'requests',
    'email.utils',
    'charset_normalizer',
]
hiddenimports += collect_submodules('requests')
hiddenimports += collect_submodules(
    'urllib3',
    filter=lambda name: not name.startswith('urllib3.contrib.emscripten'),
)

excludes = [
    'tkinter', '_tkinter', 'Tkinter',
    'numpy', 'scipy', 'pandas', 'matplotlib',
    'PIL', 'Pillow', 'cv2', 'opencv',
    'tensorflow', 'torch', 'keras', 'sklearn',
    'flask', 'django', 'fastapi',
    'pytest', 'unittest', 'nose',
    'IPython', 'jupyter', 'notebook',
    'PyQt6.QtBluetooth',
    'PyQt6.QtDBus',
    'PyQt6.QtDesigner',
    'PyQt6.QtHelp',
    'PyQt6.QtMultimedia',
    'PyQt6.QtMultimediaWidgets',
    'PyQt6.QtNfc',
    'PyQt6.QtOpenGL',
    'PyQt6.QtOpenGLWidgets',
    'PyQt6.QtPositioning',
    'PyQt6.QtPrintSupport',
    'PyQt6.QtQml',
    'PyQt6.QtQuick',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors',
    'PyQt6.QtSerialPort',
    'PyQt6.QtSql',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets',
    'PyQt6.QtXml',
    'urllib3.contrib.emscripten',
    'urllib3.contrib.emscripten.fetch',
]

a = Analysis(
    [main_script],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.binaries = [
    item for item in a.binaries if not any(
        exclude in item[0].lower() for exclude in (
            'qpdf', 'qtpdf', 'qtwebengine', 'qtquick',
            'qml', 'qt6quick', 'qt6qml', 'qt6webengine',
        )
    )
]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon_path = str(project_root / 'news_icon.ico') if (project_root / 'news_icon.ico').exists() else None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NewsScraperPro_Safe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[
        'vcruntime140.dll',
        'python*.dll',
        'Qt6Core.dll',
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
    # Do not pin onefile extraction to a build-machine-specific absolute path.
    # Let PyInstaller resolve the target machine's temp directory at runtime.
    runtime_tmpdir=None,
)
