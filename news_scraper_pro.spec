# -*- mode: python ; coding: utf-8 -*-
"""News Scraper Pro - PyInstaller onefile spec."""

import sys
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

# Current packaging contract:
# - Runtime code uses stdlib, PySide6, SQLite, requests, and charset_normalizer.
# - QLocalServer/QLocalSocket require PySide6.QtNetwork.
# - requests/urllib3 submodules are collected for onefile runtime safety.
# - urllib3.contrib.emscripten is browser/Emscripten-only and excluded.
# - Cloud snapshots, DB/config files, logs, backups, and analysis caches are
#   runtime data; they are not bundled as datas.
hiddenimports = [
    'PySide6.QtWidgets',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtNetwork',
    'sqlite3',
    'requests',
    'email.utils',
    'charset_normalizer',
    'cryptography',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
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
    'PySide6.QtBluetooth',
    'PySide6.QtDBus',
    'PySide6.QtDesigner',
    'PySide6.QtHelp',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtNfc',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtPositioning',
    'PySide6.QtPrintSupport',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtRemoteObjects',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtSql',
    'PySide6.QtSvg',
    'PySide6.QtSvgWidgets',
    'PySide6.QtTest',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebSockets',
    'PySide6.QtXml',
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

# Python 3.15 abi3t: cryptography _rust.pyd links python3t.dll
# (<prefix>\abi3t-compat), which PyInstaller does not auto-collect.
# Without it the frozen exe dies with "DLL load failed while importing _rust".
_py3t_dll = os.path.join(sys.base_prefix, 'abi3t-compat', 'python3t.dll')
_py3t_dest = 'python3t.dll'
if os.path.isfile(_py3t_dll) and not any(
        (b[0] or '').lower() == _py3t_dest for b in a.binaries):
    a.binaries.append((_py3t_dest, _py3t_dll, 'BINARY'))

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
    # Let PyInstaller resolve the target machine's temp directory at runtime.
    runtime_tmpdir=None,
)
