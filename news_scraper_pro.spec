# -*- mode: python ; coding: utf-8 -*-
"""
?댁뒪 ?ㅽ겕?섑띁 Pro v32.7.0 - 寃쎈웾??PyInstaller Spec File
鍮뚮뱶 紐낅졊?? pyinstaller news_scraper_pro.spec

?꾩옱 鍮뚮뱶 ?꾨왂:
1. 遺덊븘?뷀븳 紐⑤뱢 ?쒖쇅 (tkinter, numpy, pandas ??
2. ?⑥씪 ?ㅽ뻾 ?뚯씪 (onefile) 紐⑤뱶
3. ?덉젙???곗꽑: strip=False, upx=False ?좎?
"""

import sys
import os

block_cipher = None

# 硫붿씤 ?ㅽ겕由쏀듃
main_script = 'news_scraper_pro.py'

# 異붽? ?곗씠???뚯씪 (?꾩씠肄???
datas = []

# ?꾩씠肄??뚯씪???덉쑝硫??ы븿
if os.path.exists('news_icon.ico'):
    datas.append(('news_icon.ico', '.'))
if os.path.exists('news_icon.png'):
    datas.append(('news_icon.png', '.'))

# ?④꺼吏??꾪룷??(?꾩닔 紐⑤뱢留?
hiddenimports = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.sip',
    'sqlite3',
    'requests',
    'email.utils',
]

# ?쒖쇅??紐⑤뱢 (寃쎈웾???듭떖)
excludes = [
    # GUI ?꾨젅?꾩썙??
    'tkinter', '_tkinter', 'Tkinter',
    
    # 怨쇳븰 怨꾩궛
    'numpy', 'scipy', 'pandas', 'matplotlib',
    
    # ?대?吏/鍮꾨뵒??
    'PIL', 'Pillow', 'cv2', 'opencv',
    
    # 癒몄떊?щ떇
    'tensorflow', 'torch', 'keras', 'sklearn',
    
    # ???꾨젅?꾩썙??
    'flask', 'django', 'fastapi',
    
    # ?뚯뒪??
    'pytest', 'unittest', 'nose',
    
    # 媛쒕컻 ?꾧뎄
    'IPython', 'jupyter', 'notebook',
    
    # PyQt 遺덊븘??紐⑤뱢
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
    pathex=[],
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

# 遺덊븘?뷀븳 諛붿씠?덈━ ?쒓굅 (寃쎈웾??
a.binaries = [x for x in a.binaries if not any(
    exclude in x[0].lower() for exclude in [
        'qpdf', 'qtpdf', 'qtwebengine', 'qtquick',
        'qml', 'qt6quick', 'qt6qml', 'qt6webengine',
    ]
)]

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

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
    strip=False,  # ?붾쾭洹??щ낵 ?좎? (?ㅻ쪟 諛⑹?)
    upx=False,    # UPX ?뺤텞 鍮꾪솢?깊솕 (?ㅻ쪟 諛⑹?)
    upx_exclude=[
        'vcruntime140.dll',
        'python*.dll',
        'Qt6Core.dll',  # Qt DLL? UPX ?쒖쇅 (?덉젙??
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI ?좏뵆由ъ??댁뀡
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='news_icon.ico' if os.path.exists('news_icon.ico') else None,
)
