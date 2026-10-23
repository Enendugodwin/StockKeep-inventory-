# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the StockKeep desktop executable.

Build with:  .venv\\Scripts\\pyinstaller.exe --clean --noconfirm StockKeep.spec
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tzdata")

a = Analysis(
    ["run.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pytestqt", "PySide6.QtWebEngineCore"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="StockKeep",
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
    icon="assets/stockkeep.ico",
)
