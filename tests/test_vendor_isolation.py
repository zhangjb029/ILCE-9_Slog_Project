"""The bundled modules must import with nothing but the standard library.

A missing vendored dependency does not fail any unit test — it fails the first
time a user clicks "connect", with a generic error. These run in a subprocess
with site-packages disabled so the machine's own packages cannot mask a gap.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(code: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONPATH='')
    return subprocess.run([sys.executable, '-S', '-c', code], cwd=str(ROOT),
                          capture_output=True, text=True, env=env, timeout=120)


class TestVendorIsolation(unittest.TestCase):
    def test_pmca_sony_imports_without_site_packages(self):
        result = _run('import sys; sys.path[:0]=["src","src/vendor"]; '
                      'import pmca.usb.sony; print("OK")')
        self.assertIn('OK', result.stdout, result.stderr)

    def test_libusb_backend_loads_from_vendor(self):
        result = _run('import sys; sys.path[:0]=["src","src/vendor"]; '
                      'import libusb_package; '
                      'print("OK" if libusb_package.get_libusb1_backend() is not None else "NO_BACKEND")')
        self.assertIn('OK', result.stdout, result.stderr)

    def test_dependency_loader_returns_usable_objects(self):
        """connect() destructures exactly these eight values. A rename or a
        missing name here fails on the user's first click, not in any test."""
        result = _run(
            'import sys; sys.path[:0]=["src","src/vendor"]; '
            'from a9tool import usbdev; '
            'usb, util, backend, sony, G, B, C, U = usbdev._load_dependencies(); '
            'assert hasattr(usb, "find") and hasattr(usb, "USBError"); '
            'assert hasattr(util, "dispose_resources"); '
            'assert backend is not None; '
            'print("OK")')
        self.assertIn('OK', result.stdout, result.stderr)

    def test_sha256_shim_matches_hashlib(self):
        result = _run('import sys, hashlib; sys.path[:0]=["src","src/vendor"]; '
                      'from Cryptodome.Hash import SHA256; '
                      'print(SHA256.new(b"salt").digest() == hashlib.sha256(b"salt").digest())')
        self.assertIn('True', result.stdout, result.stderr)


if __name__ == '__main__':
    unittest.main()
