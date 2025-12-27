# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for 뉴스 스크래퍼 Pro v32.1
# 빌드: pyinstaller news_scraper.spec

import sys
import os

block_cipher = None

# 현재 디렉토리
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))

# 데이터 파일 수집 (아이콘 등)
datas = []
if os.path.exists(os.path.join(SPEC_DIR, 'news_icon.ico')):
    datas.append(('news_icon.ico', '.'))
if os.path.exists(os.path.join(SPEC_DIR, 'news_icon.png')):
    datas.append(('news_icon.png', '.'))

a = Analysis(
    ['news_scraper_pro.py'],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
        'sqlite3',
        'requests',
        'requests.adapters',
        'urllib3',
        'email.utils',
        'shutil',
        'json',
        'csv',
        'hashlib',
        'queue',
        'threading',
        'logging',
        'logging.handlers',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 모듈 제외 (경량화)
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
        'unittest',
        'test',
        'setuptools',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    console=False,  # GUI 앱이므로 콘솔 숨김 (디버깅 완료)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='news_icon.ico' if os.path.exists(os.path.join(SPEC_DIR, 'news_icon.ico')) else None,
)
