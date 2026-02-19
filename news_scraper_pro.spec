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

# Keep requests ecosystem explicit so runtime import fallback cannot miss.
hiddenimports = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.sip',
    'sqlite3',
    'requests',
    'email.utils',
    'charset_normalizer',
    'chardet',
]
hiddenimports += collect_submodules('requests')
hiddenimports += collect_submodules('urllib3')

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
    'PyQt6.QtNetwork',
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
    runtime_tmpdir=os.path.join(os.environ.get('LOCALAPPDATA', os.environ.get('TEMP', '.')), 'NewsScraperPro'),
)
