# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the onefile Windows build.

src/vendor is copied verbatim into _MEIPASS/vendor so that the sys.path hook in
a9tool/__init__.py keeps working inside the bundle, and libusb_package can find
libusb-1.0.dll through importlib.resources exactly as it does from source.
"""
import os

from PyInstaller.building.datastruct import Tree

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))
VENDOR = os.path.join(SRC, 'vendor')

datas = [
    (os.path.join(SRC, 'data', 'a9_fn_functions.json'), 'data'),
    (os.path.join(SRC, 'data', 'a9_fn_chinese_names.json'), 'data'),
] + Tree(VENDOR, prefix='vendor')

a = Analysis(
    [os.path.join(SRC, 'a9tool', '__main__.py')],
    pathex=[SRC, VENDOR],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'usb.core', 'usb.util', 'usb.backend.libusb1',
        'libusb_package', 'importlib_resources',
        'pmca.usb.sony', 'pmca.usb.constants', 'pmca.usb.crypto',
        'pmca.usb.driver.generic', 'pmca.usb.driver.generic.libusb',
        'pmca.backup',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest', 'tkinter.test', 'test'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ILCE-9_Slog_Project',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
