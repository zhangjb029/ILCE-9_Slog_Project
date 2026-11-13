import struct
import tempfile
import unittest
from pathlib import Path

from a9tool import aspect_params as ap

IDENTITY = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}


class FakeCamera:
    def __init__(self, values=None):
        self.values = dict(values or {pid: bytes(len(ap.TARGETS[pid])) for pid in ap.PIDS})
        self.writes = []
        self.saves = 0
        self.bad_readback = False

    def readBackup(self, pid):
        data = self.values[pid]
        if self.bad_readback and pid in self.writes:
            data = bytes(len(data))
        return data

    def writeBackup(self, pid, data):
        self.values[pid] = bytes(data)
        self.writes.append(pid)

    def saveBackup(self, subsystem):
        self.saves += 1


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendSenserPacket(self, function, data, oData=None):
        self.sent.append((function, data))
        return 0, b''


class TestGuard(unittest.TestCase):
    def _packet(self, command, pid, body=b''):
        return struct.pack('<HHI', ap.CATEGORY, command, pid) + body

    def test_allows_read_of_a_listed_property(self):
        guard = ap.AspectGuard(FakeTransport())
        guard.sendSenserPacket(ap.PFUNC_ADJUST, self._packet(1, ap.PIDS[0]))

    def test_rejects_read_of_an_unlisted_property(self):
        guard = ap.AspectGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(ap.PFUNC_ADJUST, self._packet(1, 0x01070be8))

    def test_rejects_write_with_wrong_length(self):
        guard = ap.AspectGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(ap.PFUNC_ADJUST, self._packet(2, ap.PIDS[0], b'\x00'))

    def test_rejects_save_before_any_write(self):
        guard = ap.AspectGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(ap.PFUNC_ADJUST, struct.pack('<HH', ap.CATEGORY, 3) + b'\0\0')


class TestApply(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_every_differing_property(self):
        cam = FakeCamera()
        result = ap.apply(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(result['changed'], len(ap.PIDS))
        self.assertEqual(cam.saves, 1)
        for pid in ap.PIDS:
            self.assertEqual(cam.values[pid], ap.TARGETS[pid])

    def test_records_the_preimage_before_writing(self):
        cam = FakeCamera()
        result = ap.apply(cam, IDENTITY, self.root)
        record = (result['directory'] / 'preimage.json').read_text(encoding='utf-8')
        self.assertIn('/dev/nflasha2', record)
        self.assertIn('serial_sha256', record)

    def test_already_at_target_writes_nothing(self):
        cam = FakeCamera(values={pid: ap.TARGETS[pid] for pid in ap.PIDS})
        result = ap.apply(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertEqual(cam.writes, [])
        self.assertEqual(cam.saves, 0)

    def test_mismatched_readback_stops_before_save(self):
        cam = FakeCamera()
        cam.bad_readback = True
        with self.assertRaises(ValueError):
            ap.apply(cam, IDENTITY, self.root)
        self.assertEqual(cam.saves, 0)

    def test_restore_puts_the_recorded_values_back(self):
        cam = FakeCamera()
        result = ap.apply(cam, IDENTITY, self.root)
        back = ap.restore(cam, IDENTITY, self.root, result['directory'])
        self.assertEqual(back['state'], 'SAVED_AND_READBACK_VERIFIED')
        for pid in ap.PIDS:
            self.assertEqual(cam.values[pid], bytes(len(ap.TARGETS[pid])))

    def test_restore_refuses_another_camera(self):
        cam = FakeCamera()
        result = ap.apply(cam, IDENTITY, self.root)
        other = dict(IDENTITY, serial_sha256='b' * 64)
        with self.assertRaises(ValueError):
            ap.restore(cam, other, self.root, result['directory'])


if __name__ == '__main__':
    unittest.main()
