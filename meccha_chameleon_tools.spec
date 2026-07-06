# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

pkg = "meccha_chameleon_tools"
a = Analysis(
    [f"{pkg}/__init__.py"],
    pathex=[],
    datas=[
        (f"{pkg}/runtime-bridge.dll", pkg),
        (f"{pkg}/runtime-injector.exe", pkg),
        (f"{pkg}/translations.py", pkg),
        (f"{pkg}/camouflage.py", pkg),
        (f"{pkg}/config.py", pkg),
        (f"{pkg}/core.py", pkg),
        (f"{pkg}/ui.py", pkg),
        (f"{pkg}/camo_entry.py", pkg),
        (f"{pkg}/hypervision.py", pkg),
        (f"{pkg}/logger.py", pkg),
    ],
    hiddenimports=[
        "PyQt5", "PyQt5.QtCore", "PyQt5.QtGui", "PyQt5.QtWidgets",
        "pymem", "win32gui",
        "meccha_chameleon_tools.hypervision",
        "meccha_chameleon_tools.logger",
    ],
    excludes=["tkinter", "matplotlib", "numpy", "PIL", "pandas", "scipy", "notebook"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MecchaCamouflage",
    debug=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=True,
    icon=None,
)
