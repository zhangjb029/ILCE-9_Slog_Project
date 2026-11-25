"""Frozen-app entry point.

src/a9tool/__main__.py uses a relative import, which is correct for
``python -m a9tool`` but fatal as a PyInstaller script (there is no parent
package there). PyInstaller finds a9tool through pathex, so a plain absolute
import is what the bundle needs.

Set A9TOOL_SELFCHECK=1 to verify the bundled data tables and USB stack without
opening a window or touching a camera. That is the only way to catch a packaging
mistake (missing libusb DLL, missing JSON) before a user hits it.
"""
import os
import sys
from pathlib import Path


def selfcheck() -> int:
    from a9tool import fnmap, journal, usbdev, __version__

    print('version:', __version__)
    print('baseline: v1.8.2 / native Windows USB')
    print('functions:', len(fnmap.load_functions()))
    print('sessions root:', journal.sessions_root())
    try:
        _usb, _util, backend, *_rest = usbdev._load_dependencies()
    except Exception as error:
        print(f'SELFCHECK_FAIL: {type(error).__name__}: {error}')
        return 2
    print('libusb backend:', backend)

    from a9tool import menu_deploy
    try:
        runs = len(menu_deploy.load_patch())
    except Exception as error:
        print(f'PATCH_FAIL: {type(error).__name__}: {error}')
        return 4
    print('r12 patch runs:', runs)
    from a9tool import versions
    try:
        builds = [entry['label'] for entry in versions.table()['versions']]
    except Exception as error:
        print(f'FINGERPRINT_FAIL: {type(error).__name__}: {error}')
        return 4
    print('version fingerprints:', ', '.join(builds))
    if 'R12' not in builds:
        print('FINGERPRINT_UNEXPECTED: R12 missing')
        return 4
    if runs != 66319:
        print(f'PATCH_UNEXPECTED: {runs}')
        return 4

    from a9tool import firmware_reset
    if (firmware_reset.describe(firmware_reset.V600) != '6.00'
            or firmware_reset.describe(firmware_reset.V500) != '5.00'):
        print('RESET_UNEXPECTED: dat4 encoding')
        return 4
    print('force rollback: dat4 6.00 <-> 5.00')
    from a9tool import release_assets, r15nh_deploy, v8_deploy
    try:
        assets = release_assets.verify()
        patch_release = r15nh_deploy.execute('r15.check', {})
        r15nh_deploy.runtime()
        for source in r15nh_deploy.package()['sources']:
            if 'patch' in source:
                r15nh_deploy._patch_runs(source)
        if set(patch_release['patch_sources']) != {'stock','R8','R9','R9.1','R10','R11','R12'}:
            raise ValueError('Expected seven supported R12P source profiles')
        if (release_assets.ROOT/'r15nh/target.bin.xz').exists():
            raise ValueError('A complete R15NH partition image must not be distributed')
        print('R15NH: read -> identify -> patch -> write; FF01 full partition')
        v8_deploy.execute('v8.check', {})
        # Exercise the shipped compatibility rule without discovering USB.
        import struct
        from a9tool import file_deploy, r15_files
        content={row['path']:release_assets.asset('r15/'+row['file'])
                 for row in release_assets.r15()['initial_files']}
        content.update(dict.fromkeys(file_deploy.CONFIG_PATHS))
        for variant in (False,True):
            if variant:
                raw=bytearray(content[v8_deploy.VIEW_PATH])
                struct.pack_into('<II',raw,0x64,0x8c7dfc,0x8c7dfc)
                content[v8_deploy.VIEW_PATH]=bytes(raw)
            state=v8_deploy.r15_prerequisite(content,r15_files.a9p.stock())
            if (state['label']!='R15 NAME HELP' or not state['state_validated']
                    or state['view_library_match']!=('known-extent-variant' if variant else 'canonical')):
                raise ValueError('V8 R15NH prerequisite compatibility selfcheck failed')
        print('V8: canonical and pinned RX extent variant; R15NH/CFG/LUT required')
    except Exception as error:
        print(f'RELEASE_FAIL: {type(error).__name__}: {error}')
        return 4
    print('release assets:', assets['files'], 'verified')

    # GUI construction needs a desktop. A CI runner may not have one, so a
    # failure here is fatal only when A9TOOL_SELFCHECK_GUI=1 (which is what you
    # should set when verifying a build by hand).
    strict_gui = os.environ.get('A9TOOL_SELFCHECK_GUI') == '1'
    try:
        import tkinter as tk
        from a9tool.gui import App
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update()
        rows = len(app.all_tree.get_children())
        tabs = [app.notebook.tab(i, 'text') for i in range(len(app.notebook.tabs()))]
        root.destroy()
    except Exception as error:
        print(f'GUI_FAIL: {type(error).__name__}: {error}')
        return 3 if strict_gui else 0
    print('gui: 77-row table, 6 tabs' if rows == 77 and len(tabs) == 6
          else f'gui: UNEXPECTED rows={rows} tabs={tabs}')
    if rows != 77 or len(tabs) != 6:
        return 3
    if any('wsl' in name.lower() for name in sys.modules if name.startswith('a9tool.')):
        print('UNEXPECTED: WSL backend loaded')
        return 4

    print('SELFCHECK_OK')
    return 0


if __name__ == '__main__':
    if os.environ.get('A9TOOL_SELFCHECK') == '1':
        # A windowed build has no stdout at all — sys.stdout is None and the
        # first print() would raise. Redirect to a file next to the exe so the
        # released windowed binary can still be self-checked.
        if sys.stdout is None:
            sys.stdout = open(Path(sys.executable).parent / 'selfcheck.txt', 'w',
                              encoding='utf-8', buffering=1)
        sys.exit(selfcheck())
    from a9tool.gui import main
    sys.exit(main())
