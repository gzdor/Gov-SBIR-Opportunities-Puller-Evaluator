# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec for the DSIP Opportunities Downloader desktop app.

Produces a single, self-contained Windows executable (no console window) that
bundles the Python runtime, Tkinter, gui.py, main.py, analyze.py, theme.py, and pypdf.

Build:
    pip install -r requirements-build.txt
    pyinstaller DSIP_Downloader.spec
Output:
    dist/DSIP_Downloader.exe
"""

import glob
import os
import sys

# Conda ships the Tcl/Tk 9 runtime DLLs under <env>\Library\bin, a location
# PyInstaller's dependency scanner does not search, so _tkinter fails to load
# in the frozen app. Bundle those DLLs explicitly. (The Tcl/Tk *script*
# libraries are collected automatically by the stock _tkinter hook.)
_tcltk_dlls = []
_library_bin = os.path.join(sys.base_prefix, "Library", "bin")
for _name in ("tcl90.dll", "tcl9tk90.dll", "libtommath.dll", "zlib1.dll"):
    for _match in glob.glob(os.path.join(_library_bin, _name)):
        _tcltk_dlls.append((_match, "."))

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=_tcltk_dlls,
    datas=[],
    hiddenimports=["main", "analyze", "theme", "pypdf"],
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
    name="DSIP_Downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # windowed GUI app: no console flash
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
