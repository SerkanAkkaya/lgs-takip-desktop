# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all
import psycopg

datas = [('database.py', '.')]
binaries = []
hiddenimports = ['ttkbootstrap', 'ttkbootstrap.themes', 'ttkbootstrap.themes.standard', 'ttkbootstrap.themes.user', 'PIL._tkinter_finder', 'google.generativeai', 'google.ai.generativelanguage', 'openai', 'pdfplumber']
tmp_ret = collect_all('ttkbootstrap')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret2 = collect_all('google.generativeai')
datas += tmp_ret2[0]; binaries += tmp_ret2[1]; hiddenimports += tmp_ret2[2]
tmp_ret3 = collect_all('openai')
datas += tmp_ret3[0]; binaries += tmp_ret3[1]; hiddenimports += tmp_ret3[2]
tmp_ret4 = collect_all('psycopg')
datas += tmp_ret4[0]; binaries += tmp_ret4[1]; hiddenimports += tmp_ret4[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LGS_Takip',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
