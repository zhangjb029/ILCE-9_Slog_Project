import tempfile
import unittest
from pathlib import Path

from a9tool import core, fnmap
from tests.fakecamera import FakeCamera

FN7 = fnmap.FN_SLOTS[7]


def _enabled_override() -> bytes:
    raw = bytearray(1024)
    for off in fnmap.OVERRIDE_OFFSETS:
        raw[off] = 2
    return bytes(raw)


class TestWriteSlot(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_one_byte_in_one_slot(self):
        cam = FakeCamera(override=_enabled_override())
        session = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertEqual(cam.written, {FN7: b'\x36'})
        self.assertEqual(session.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(cam.saves, 1)

    def test_refuses_when_override_not_enabled(self):
        cam = FakeCamera(override=bytes(1024))
        with self.assertRaises(ValueError) as ctx:
            core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertIn('放行', str(ctx.exception))
        self.assertEqual(cam.written, {})

    def test_refuses_when_override_is_mixed(self):
        raw = bytearray(1024)
        raw[0xa2] = 2
        cam = FakeCamera(override=bytes(raw))
        with self.assertRaises(ValueError):
            core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertEqual(cam.written, {})

    def test_refuses_out_of_range_value(self):
        cam = FakeCamera(override=_enabled_override())
        with self.assertRaises(ValueError):
            core.write_slot(cam, core.read_state(cam), 7, fnmap.VALUE_LIMIT + 1, self.root)
        self.assertEqual(cam.written, {})

    def test_refuses_unknown_value(self):
        cam = FakeCamera(override=_enabled_override())
        with self.assertRaises(ValueError):
            core.write_slot(cam, core.read_state(cam), 7, 0x00, self.root)

    def test_records_original_before_write(self):
        cam = FakeCamera(override=_enabled_override(), slots={n: 0x06 for n in fnmap.FN_SLOTS})
        session = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertEqual(session.payload['original'], '06')
        self.assertEqual(session.payload['target'], '36')

    def test_journal_records_verification_note_for_pixel_shift(self):
        cam = FakeCamera(override=_enabled_override())
        session = core.write_slot(cam, core.read_state(cam), 12, 0x64, self.root)
        self.assertEqual(session.payload['status'], 'known_bad')
        self.assertTrue(session.payload['confirmation_text'])

    def test_second_write_records_written_by(self):
        cam = FakeCamera(override=_enabled_override())
        first = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        second = core.write_slot(cam, core.read_state(cam), 7, 0x3A, self.root)
        self.assertEqual(second.payload['written_by'], first.directory.name)


if __name__ == '__main__':
    unittest.main()
