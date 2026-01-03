# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for 뉴스 스크래퍼 Pro v32.1
# 경량화 최적화 버전

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 제외할 모듈 (경량화)
excludes = [
    # 불필요한 PyQt6 모듈
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
    'PyQt6.QtQuick3D',
    'PyQt6.QtQuickWidgets',
    'PyQt6.QtRemoteObjects',
    'PyQt6.QtSensors',
    'PyQt6.QtSerialPort',
    'PyQt6.QtSpatialAudio',
    'PyQt6.QtSql',
    'PyQt6.QtSvg',
    'PyQt6.QtSvgWidgets',
    'PyQt6.QtTest',
    'PyQt6.QtWebChannel',
    'PyQt6.QtWebEngineCore',
    'PyQt6.QtWebEngineQuick',
    'PyQt6.QtWebEngineWidgets',
    'PyQt6.QtWebSockets',
    'PyQt6.QtXml',
    'PyQt6.Qt3DAnimation',
    'PyQt6.Qt3DCore',
    'PyQt6.Qt3DExtras',
    'PyQt6.Qt3DInput',
    'PyQt6.Qt3DLogic',
    'PyQt6.Qt3DRender',
    'PyQt6.QtPdf',
    'PyQt6.QtPdfWidgets',
    'PyQt6.QtCharts',
    'PyQt6.QtDataVisualization',
    # 기타 불필요한 모듈
    'unittest',
    'test',
    'distutils',
    'setuptools',
    'pip',
    'wheel',
    'numpy',
    'pandas',
    'matplotlib',
    'scipy',
    'PIL',
    'tkinter',
    '_tkinter',
    'tk',
    'tcl',
]

a = Analysis(
    ['news_scraper_pro.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 아이콘 파일 포함 (있는 경우)
        # ('news_icon.ico', '.'),
        # ('news_icon.png', '.'),
    ],
    hiddenimports=[
        'PyQt6.sip',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 중복 바이너리 제거
a.binaries = a.binaries - TOC([
    ('opengl32sw.dll', None, None),  # 소프트웨어 OpenGL 제거
    ('d3dcompiler_47.dll', None, None),  # DirectX 컴파일러 (선택적)
])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='뉴스 스크래퍼 Pro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,  # Windows에서는 strip 비활성화
    upx=True,  # UPX 압축 활성화 (UPX 설치 필요)
    upx_exclude=[
        'vcruntime140.dll',
        'python*.dll',
        'Qt*.dll',
    ],
    runtime_tmpdir=None,
    console=False,  # GUI 앱이므로 콘솔 비활성화
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='news_icon.ico',  # 아이콘 파일이 있으면 주석 해제
)
