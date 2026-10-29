import json
import tempfile
import time
import unittest
from pathlib import Path

from a9tool import errors, usbdev

GOOD = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}


class TestIdentityGate(unittest.TestCase):
    def test_identity_gate_rejects_wrong_model(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity({'model': 'ILCE-9M2', 'firmware': '3.20', 'serial_sha256': 'a' * 64})

    def test_identity_gate_rejects_wrong_firmware(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity({'model': 'ILCE-9', 'firmware': '5.00', 'serial_sha256': 'a' * 64})

    def test_identity_gate_accepts_a9_600(self):
        usbdev.check_identity(GOOD)

    def test_identity_gate_rejects_missing_fingerprint(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity({'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': ''})


class TestDeviceSelection(unittest.TestCase):
    def test_connect_rejects_multiple_cameras(self):
        with self.assertRaises(RuntimeError) as ctx:
            usbdev._select_single([object(), object()])
        self.assertIn('一台', errors.user_message(ctx.exception))

    def test_connect_rejects_no_camera(self):
        with self.assertRaises(RuntimeError):
            usbdev._select_single([])

    def test_select_single_returns_the_device(self):
        device = object()
        self.assertIs(usbdev._select_single([device]), device)


class TestReceipt(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_receipt_round_trips(self):
        path = usbdev.save_receipt(GOOD, {'bus': 1, 'ports': [2]}, root=self.root)
        self.assertTrue(path.exists())
        self.assertEqual(usbdev.load_current_receipt(root=self.root), path)

    def test_expired_receipt_is_not_returned(self):
        path = usbdev.save_receipt(GOOD, {'bus': 1, 'ports': [2]}, root=self.root)
        receipt = json.loads(path.read_text(encoding='utf-8'))
        receipt['created_epoch'] = time.time() - 3601
        path.write_text(json.dumps(receipt), encoding='utf-8')
        self.assertIsNone(usbdev.load_current_receipt(root=self.root))

    def test_missing_receipt_returns_none(self):
        self.assertIsNone(usbdev.load_current_receipt(root=self.root))

    def test_receipt_from_another_camera_is_rejected(self):
        path = usbdev.save_receipt({'model': 'ILCE-9M2', 'firmware': '3.20',
                                    'serial_sha256': 'b' * 64}, {'bus': 1, 'ports': [2]}, root=self.root)
        with self.assertRaises(ValueError):
            usbdev.load_current_receipt(root=self.root)


if __name__ == '__main__':
    unittest.main()
