import hashlib
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class NativePackagingTests(unittest.TestCase):
    def test_native_usb_stack_matches_released_182(self):
        raw = (ROOT/'src/a9tool/usbdev.py').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
            '107086bd70bcc752508088bffc5a224ae6bb1002b693a4b49b68c6eb327941e0')

    def test_entry_and_sources_use_native_gui(self):
        self.assertIn('from a9tool.gui import main', (ROOT/'build/entry.py').read_text())
        self.assertFalse(list((ROOT/'src/a9tool').glob('wsl*.py')))
        spec = (ROOT/'build/a9tool.spec').read_text()
        self.assertIn("tree(os.path.join(SRC, 'data'), 'data')", spec)
        self.assertIn("(DLL, 'libusb_package')", spec)

    def test_offline_deployment_checks_never_enumerate_devices(self):
        program = '''
import sys
sys.path.insert(0,'src')
from unittest.mock import patch
from a9tool import r15nh_deploy, v8_deploy, release_assets
with patch('a9tool.usbdev.connect',side_effect=AssertionError('no device')):
    r15=r15nh_deploy.execute('r15.check',{})
    assert r15['installation_enabled'] and r15['contains_full_image'] is False
    assert set(r15['patch_sources'])=={'stock','R8','R9','R9.1','R10','R11','R12'}
    assert v8_deploy.execute('v8.check',{})['installation_enabled']
assert release_assets.verify()['files']>=24
assert not (release_assets.ROOT/'r15nh/target.bin.xz').exists()
assert not any(x.startswith('a9tool.wsl') for x in sys.modules)
'''
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', '-c', program],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
