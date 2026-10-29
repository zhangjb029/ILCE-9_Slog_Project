import json
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


class TestRestore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'sessions'
        self.baseline = Path(self._tmp.name) / 'baseline'

    def tearDown(self):
        self._tmp.cleanup()

    def test_restore_returns_slot_to_original(self):
        cam = FakeCamera(override=_enabled_override(), slots={n: 0x06 for n in fnmap.FN_SLOTS})
        session = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        core.restore_session(cam, session, self.root)
        self.assertEqual(cam.slots[7], 0x06)

    def test_restore_refuses_when_value_is_third_state(self):
        cam = FakeCamera(override=_enabled_override(), slots={n: 0x06 for n in fnmap.FN_SLOTS})
        session = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        cam.slots[7] = 0x10  # changed by hand on the camera
        with self.assertRaises(ValueError) as ctx:
            core.restore_session(cam, session, self.root)
        self.assertIn('恢复冲突', str(ctx.exception))

    def test_restore_refuses_tampered_snapshot(self):
        cam = FakeCamera(override=_enabled_override())
        session = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        path = session.directory / 'Backup-original.bin'
        path.write_bytes(bytes(len(path.read_bytes())))
        with self.assertRaises(ValueError):
            core.restore_session(cam, session, self.root)

    def test_restore_override_returns_original_bytes(self):
        cam = FakeCamera(override=bytes(1024))
        session = core.enable_override(cam, core.read_state(cam), self.root)
        core.restore_session(cam, session, self.root)
        self.assertEqual(bytes(cam.override), bytes(1024))

    def test_restore_baseline_reverts_everything_tool_touched(self):
        cam = FakeCamera(override=_enabled_override(), slots={n: 0x06 for n in fnmap.FN_SLOTS})
        core.save_baseline(core.read_state(cam), root=self.baseline)
        core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        core.write_slot(cam, core.read_state(cam), 12, 0x3A, self.root)
        core.restore_baseline(cam, self.root, baseline_dir=self.baseline)
        self.assertEqual(cam.slots[7], 0x06)
        self.assertEqual(cam.slots[12], 0x06)

    def test_baseline_is_written_once(self):
        cam = FakeCamera(override=_enabled_override(), slots={n: 0x06 for n in fnmap.FN_SLOTS})
        first = core.save_baseline(core.read_state(cam), root=self.baseline)
        cam.slots[7] = 0x36
        second = core.save_baseline(core.read_state(cam), root=self.baseline)
        self.assertEqual(first, second)
        self.assertEqual(json.loads(first.read_text(encoding='utf-8'))['slots']['7'], 0x06)

    def test_restore_without_baseline_is_refused(self):
        cam = FakeCamera(override=_enabled_override())
        with self.assertRaises(ValueError):
            core.restore_baseline(cam, self.root, baseline_dir=self.baseline)


if __name__ == '__main__':
    unittest.main()
