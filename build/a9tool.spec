# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the onefile Windows build.

Two things about this file are load-bearing:

1. ``datas`` must be a list of ``(source, destination_dir)`` pairs. PyInstaller's
   ``Tree()`` helper yields three-element TOC entries meant for COLLECT, so it
   cannot be spliced into ``Analysis(datas=...)``.

2. ``libusb-1.0.dll`` has to land in *two* places. libusb_package resolves it via
   ``importlib_resources.files('libusb_package')``; once the package is imported
   from the PYZ that root is ``_MEIPASS/libusb_package``, not the vendored copy
   under ``_MEIPASS/vendor``. Without the second copy, get_library_path()
   returns None and the app dies on the first connect with a generic error.
"""
import os

CONSOLE = os.environ.get('A9TOOL_CONSOLE') == '1'

SRC = os.path.abspath(os.path.join(SPECPATH, '..', 'src'))
VENDOR = os.path.join(SRC, 'vendor')
DLL = os.path.join(VENDOR, 'libusb_package', 'libusb-1.0.dll')


def tree(src, prefix):
    """(source, destination directory) pairs for everything under src."""
    entries = []
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for name in files:
            if name.endswith(('.pyc', '.pyo')):
                continue
            full = os.path.join(root, name)
            relative = os.path.relpath(full, src)
            entries.append((full, os.path.join(prefix, os.path.dirname(relative)).rstrip('\\/')))
    return entries


datas = [
    (os.path.join(SRC, 'data', 'a9_fn_functions.json'), 'data'),
    (os.path.join(SRC, 'data', 'a9_fn_chinese_names.json'), 'data'),
] + tree(VENDOR, 'vendor')

binaries = [
    (DLL, 'libusb_package'),          # where importlib.resources looks
    (DLL, os.path.join('vendor', 'libusb_package')),  # where sys.path finds the package
]

a = Analysis(
    [os.path.join(SPECPATH, 'entry.py')],
    pathex=[SRC, VENDOR],
    binaries=binaries,
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
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
