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


def selfcheck() -> int:
    from a9tool import fnmap, journal, usbdev

    print('functions:', len(fnmap.load_functions()))
    print('sessions root:', journal.sessions_root())
    try:
        _usb, _util, backend, *_rest = usbdev._load_dependencies()
    except Exception as error:
        print(f'SELFCHECK_FAIL: {type(error).__name__}: {error}')
        return 2
    print('libusb backend:', backend)

    try:
        import tkinter as tk
        from a9tool.gui import App
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update()
        rows = len(app.all_tree.get_children())
        root.destroy()
    except Exception as error:
        print(f'GUI_FAIL: {type(error).__name__}: {error}')
        return 3
    print('gui: 77-row table' if rows == 77 else f'gui: UNEXPECTED rows={rows}')

    print('SELFCHECK_OK')
    return 0


if __name__ == '__main__':
    if os.environ.get('A9TOOL_SELFCHECK') == '1':
        sys.exit(selfcheck())
    from a9tool.gui import main
    sys.exit(main())
