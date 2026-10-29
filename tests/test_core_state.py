import struct
import unittest

from a9tool import core, fnmap, usbdev
from tests.fakecamera import FakeCamera, FakeTransport


def _override(fill: int, offsets=()) -> bytes:
    raw = bytearray([fill] * 1024)
    for off in offsets:
        raw[off] = 2
    return bytes(raw)


class TestOverrideStatus(unittest.TestCase):
    def test_all_two_is_enabled(self):
        self.assertEqual(core.override_status(core.CameraState(b'', _override(0, fnmap.OVERRIDE_OFFSETS), {})), 'enabled')

    def test_all_one_is_disabled(self):
        self.assertEqual(core.override_status(core.CameraState(b'', _override(1), {})), 'disabled')

    def test_factory_ff_is_disabled(self):
        self.assertEqual(core.override_status(core.CameraState(b'', _override(0xff), {})), 'disabled')

    def test_mixed_is_mixed_and_blocks_writes(self):
        raw = _override(1, [0xa2])
        self.assertEqual(core.override_status(core.CameraState(b'', raw, {})), 'mixed')


class TestReadState(unittest.TestCase):
    def test_reads_all_twelve_slots(self):
        state = core.read_state(FakeCamera())
        self.assertEqual(set(state.slots), set(fnmap.FN_SLOTS))
        self.assertEqual(state.slots[7], 0x06)

    def test_snapshot_is_the_whole_backup(self):
        cam = FakeCamera()
        state = core.read_state(cam)
        self.assertEqual(state.snapshot, cam.getBackupPresetData(True))


class TestParameterGuard(unittest.TestCase):
    def test_guard_blocks_non_whitelisted_property(self):
        guard = usbdev.ParameterGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 2, usbdev.MENU_SELECTOR) + b'\x4c')

    def test_guard_allows_whitelisted_write_then_one_save(self):
        guard = usbdev.ParameterGuard(FakeTransport())
        guard.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 2, 0x01070bf1) + b'\x36')
        guard.sendSenserPacket(0x40, struct.pack('<HH', 0x603, 3) + b'\0\0')
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, struct.pack('<HH', 0x603, 3) + b'\0\0')  # second save

    def test_guard_blocks_save_without_write(self):
        guard = usbdev.ParameterGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, struct.pack('<HH', 0x603, 3) + b'\0\0')

    def test_guard_allows_whitelisted_read(self):
        guard = usbdev.ParameterGuard(FakeTransport())
        guard.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 1, fnmap.OVERRIDE))

    def test_guard_blocks_read_of_unknown_property(self):
        guard = usbdev.ParameterGuard(FakeTransport())
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 1, 0x00001234))


if __name__ == '__main__':
    unittest.main()
