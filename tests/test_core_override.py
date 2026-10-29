import tempfile
import unittest
from pathlib import Path

from a9tool import core, fnmap
from tests.fakecamera import FakeCamera


def _enabled_override() -> bytes:
    raw = bytearray(1024)
    for off in fnmap.OVERRIDE_OFFSETS:
        raw[off] = 2
    return bytes(raw)


class TestEnableOverride(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_writes_only_five_offsets(self):
        cam = FakeCamera(override=bytes(1024))
        session = core.enable_override(cam, core.read_state(cam), self.root)
        written = cam.written[fnmap.OVERRIDE]
        self.assertEqual({i for i, b in enumerate(written) if b == 2}, set(fnmap.OVERRIDE_OFFSETS))
        self.assertEqual(session.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(cam.saves, 1)

    def test_preserves_other_bytes(self):
        raw = bytearray(1024)
        raw[0x10] = 0x7e
        cam = FakeCamera(override=bytes(raw))
        core.enable_override(cam, core.read_state(cam), self.root)
        written = cam.written[fnmap.OVERRIDE]
        self.assertEqual(written[0x10], 0x7e)
        self.assertEqual({i for i, b in enumerate(written) if b != raw[i]},
                         set(fnmap.OVERRIDE_OFFSETS))

    def test_never_touches_any_fn_slot(self):
        cam = FakeCamera()
        core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(set(cam.written) & set(fnmap.SLOT_PIDS), set())

    def test_refuses_mixed_state(self):
        raw = bytearray(1024)
        raw[0xa2] = 2
        cam = FakeCamera(override=bytes(raw))
        with self.assertRaises(ValueError):
            core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(cam.written, {})
        self.assertEqual(cam.saves, 0)

    def test_already_enabled_writes_nothing(self):
        cam = FakeCamera(override=_enabled_override())
        session = core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(session.state, 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertNotIn(fnmap.OVERRIDE, cam.written)
        self.assertEqual(cam.saves, 0)

    def test_failed_write_leaves_a_review_state(self):
        cam = FakeCamera(override=bytes(1024))
        cam.fail_on_write = fnmap.OVERRIDE
        with self.assertRaises(IOError):
            core.enable_override(cam, core.read_state(cam), self.root)
        sessions = list(self.root.iterdir())
        self.assertEqual(len(sessions), 1)
        self.assertIn('FAILED_REVIEW_REQUIRED', (sessions[0] / 'journal.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
