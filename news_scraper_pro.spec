# -*- mode: python ; coding: utf-8 -*-
"""
뉴스 스크래퍼 Pro v32.1 - 경량화 PyInstaller Spec File
빌드 명령어: pyinstaller news_scraper_pro.spec

경량화 전략:
1. 불필요한 모듈 제외 (tkinter, numpy, pandas 등)
2. UPX 압축 활성화
3. strip 옵션으로 디버그 심볼 제거
4. 단일 실행 파일 (onefile) 모드
"""

import sys
import os

block_cipher = None

# 메인 스크립트
main_script = 'news_scraper_pro.py'

# 추가 데이터 파일 (아이콘 등)
datas = []

# 아이콘 파일이 있으면 포함
if os.path.exists('news_icon.ico'):
    datas.append(('news_icon.ico', '.'))
if os.path.exists('news_icon.png'):
    datas.append(('news_icon.png', '.'))

# 숨겨진 임포트 (필수 모듈만)
hiddenimports = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.sip',
    'sqlite3',
    'requests',
    'email.utils',
]

# 제외할 모듈 (경량화 핵심)
excludes = [
    # GUI 프레임워크
    'tkinter', '_tkinter', 'Tkinter',
    
    # 과학 계산
    'numpy', 'scipy', 'pandas', 'matplotlib',
    
    # 이미지/비디오
    'PIL', 'Pillow', 'cv2', 'opencv',
    
    # 머신러닝
    'tensorflow', 'torch', 'keras', 'sklearn',
    
    # 웹 프레임워크
    'flask', 'django', 'fastapi',
    
    # 테스트
    'pytest', 'unittest', 'nose',
    
    # 개발 도구
    'IPython', 'jupyter', 'notebook',
    
    # PyQt 불필요 모듈
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

# 불필요한 바이너리 제거 (경량화)
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
    name='뉴스스크래퍼Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # 디버그 심볼 제거 (경량화)
    upx=True,    # UPX 압축 활성화
    upx_exclude=[
        'vcruntime140.dll',
        'python*.dll',
        'Qt6Core.dll',  # Qt DLL은 UPX 제외 (안정성)
        'Qt6Gui.dll',
        'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI 애플리케이션
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='news_icon.ico' if os.path.exists('news_icon.ico') else None,
)
