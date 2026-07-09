# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['meccha_chameleon_tools/__init__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('meccha_chameleon_tools/native', 'native'),
        ('meccha_chameleon_tools/mesh-profiles', 'mesh-profiles'),
    ],
    hiddenimports=[
        'pymem',
        'pymem.memory',
        'pymem.process',
        'pymem.ptypes',
        'pymem.ressources',
        'pymem.ressources.kernel32',
        'pymem.ressources.structure',
        'PyQt5',
        'PyQt5.QtWidgets',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        'ctypes',
        'ctypes.wintypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Meccha Chameleon Tools',
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
    icon=None,
)
