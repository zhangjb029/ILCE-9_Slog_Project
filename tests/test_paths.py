import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

from a9tool import journal


@contextmanager
def _frozen(exe: str):
    """Pretend to run as a onefile exe. sys is a builtin module, so
    mock.patch.object cannot add attributes to it."""
    had = hasattr(sys, 'frozen')
    old = getattr(sys, 'frozen', None)
    old_exe = sys.executable
    sys.frozen = True
    sys.executable = exe
    try:
        yield
    finally:
        sys.executable = old_exe
        if had:
            sys.frozen = old
        else:
            del sys.frozen


@contextmanager
def _not_frozen():
    had = hasattr(sys, 'frozen')
    old = getattr(sys, 'frozen', None)
    if had:
        del sys.frozen
    try:
        yield
    finally:
        if had:
            sys.frozen = old


class TestPaths(unittest.TestCase):
    def test_sessions_root_is_executable_dir(self):
        with _frozen(r'C:\somewhere\tool.exe'):
            self.assertEqual(journal.sessions_root(), Path(r'C:\somewhere') / 'sessions')

    def test_sessions_root_never_uses_meipass(self):
        had = hasattr(sys, '_MEIPASS')
        old = getattr(sys, '_MEIPASS', None)
        sys._MEIPASS = r'C:\Temp\_MEI123'
        try:
            with _frozen(r'C:\somewhere\tool.exe'):
                self.assertEqual(journal.sessions_root(), Path(r'C:\somewhere') / 'sessions')
        finally:
            if had:
                sys._MEIPASS = old
            else:
                del sys._MEIPASS

    def test_baseline_root_follows_the_same_rule(self):
        with _frozen(r'D:\tools\app.exe'):
            self.assertEqual(journal.baseline_root(), Path(r'D:\tools') / 'baseline')

    def test_source_run_uses_project_root(self):
        with _not_frozen():
            self.assertEqual(journal.sessions_root().parent,
                             Path(journal.__file__).resolve().parent.parent.parent)


if __name__ == '__main__':
    unittest.main()
