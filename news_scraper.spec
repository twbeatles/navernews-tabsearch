# -*- mode: python ; coding: utf-8 -*-
"""
뉴스 스크래퍼 Pro v32.1 - PyInstaller Spec File
빌드 명령어: pyinstaller news_scraper.spec
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 메인 스크립트
main_script = 'news_scraper_pro.py'

# 추가 데이터 파일 (아이콘 등)
datas = []

# 아이콘 파일이 있으면 포함
import os
if os.path.exists('news_icon.ico'):
    datas.append(('news_icon.ico', '.'))
if os.path.exists('news_icon.png'):
    datas.append(('news_icon.png', '.'))

# 숨겨진 임포트 (PyQt6 관련)
hiddenimports = [
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.sip',
    'sqlite3',
    'requests',
    'json',
    'csv',
    'hashlib',
    'logging',
    'email.utils',
    'urllib.parse',
    'html',
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
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'tensorflow',
        'torch',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

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
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 애플리케이션
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # 아이콘 설정 (있는 경우)
    icon='news_icon.ico' if os.path.exists('news_icon.ico') else None,
    # 버전 정보
    version_info=None,
)

# 빌드 후 정리할 파일 목록 (선택사항)
# coll = COLLECT(
#     exe,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     name='뉴스스크래퍼Pro',
# )
