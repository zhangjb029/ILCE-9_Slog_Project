"""The one-byte 5 GHz change: guard, state machine, and what restore accepts.

Backup parsing is mocked here — the real parser is pmca's and its behaviour is
pinned by the vendored source. What these tests protect is everything around
it: the packet allowlist, the requirement that the preimage match, the ordering
of write/readback/save, and the refusal paths.

Each transaction gets its own guard, exactly as a fresh service connection does;
a guard is deliberately single-use.
"""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import journal, wifi_5ghz as wifi

IDENTITY = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}
OTHER = dict(IDENTITY, serial_sha256='b' * 64)


SAVE_PACKET = struct.pack('<HH', 0x603, 3) + bytes(2)


def packet(command, pid, body=b''):
    return struct.pack('<HH', 0x603, command) + struct.pack('<I', pid) + body


class FakeTransport:
    """Fixed replies, for exercising the guard on its own."""

    def __init__(self, reply=b'\x09', response=0):
        self.sent = []
        self.reply = reply
        self.response = response

    def sendSenserPacket(self, function, data, oData=None):
        self.sent.append((function, data))
        return self.response, self.reply


class FakeWifiCamera:
    def __init__(self, values=None, fail_on_write: int | None = None):
        baseline = {pid: wifi.COMPANIONS.get(pid, wifi.ORIGINAL) for pid in wifi.READ_IDS}
        self.values = dict(values or baseline)
        self.written = {}
        self.saves = 0
        self.fail_on_write = fail_on_write

    def getBackupPresetData(self, _padding=False):
        return b'BACKUP-PLACEHOLDER'

    def readBackup(self, pid):
        return self.values[pid]

    def writeBackup(self, pid, data):
        if self.fail_on_write is not None and pid == self.fail_on_write:
            raise IOError('simulated write failure')
        self.values[pid] = bytes(data)
        self.written[pid] = bytes(data)

    def saveBackup(self, subsystem):
        self.saves += 1


class LiveTransport:
    """Answers reads from the fake camera, and records everything sent."""

    def __init__(self, camera):
        self.camera = camera
        self.sent = []

    def sendSenserPacket(self, function, data, oData=None):
        self.sent.append((function, data))
        if function == 0x40 and len(data) >= 8:
            category, command = struct.unpack_from('<HH', data)
            if category == 0x603 and command == 1:
                pid = struct.unpack_from('<I', data, 4)[0]
                return 0, self.camera.values[pid]
        return 0, b''


class GuardedCamera:
    """The part of SonySenserCamera these modules use, framed through the guard.

    The real chain is camera -> guard -> transport, and the guard only arms
    itself on a read it has actually seen. Routing the fake through the same
    chain keeps that contract under test instead of bypassing it.
    """

    def __init__(self, inner, guard):
        self.inner = inner
        self.guard = guard

    def getBackupPresetData(self, padding=False):
        return self.inner.getBackupPresetData(padding)

    def readBackup(self, pid):
        response, reply = self.guard.sendSenserPacket(
            0x40, struct.pack('<HH', 0x603, 1) + struct.pack('<I', pid))
        if response != 0:
            raise IOError('read refused')
        return reply

    def writeBackup(self, pid, data):
        response, _ = self.guard.sendSenserPacket(
            0x40, struct.pack('<HH', 0x603, 2) + struct.pack('<I', pid) + bytes(data))
        if response != 0:
            raise IOError('write refused')
        self.inner.writeBackup(pid, data)

    def saveBackup(self, subsystem):
        self.guard.sendSenserPacket(
            0x40, struct.pack('<HH', 0x603, 3) + struct.pack('<H', subsystem))
        self.inner.saveBackup(subsystem)


class TestGuard(unittest.TestCase):
    def _guard(self, **kwargs):
        return wifi.WifiGuard(FakeTransport(**kwargs))

    def test_rejects_a_non_backup_channel(self):
        with self.assertRaises(ValueError):
            self._guard().sendSenserPacket(0x1F, b'\x00' * 8)

    def test_rejects_a_property_outside_the_six(self):
        with self.assertRaises(ValueError):
            self._guard().sendSenserPacket(0x40, packet(1, 0x00A5000D))

    def test_rejects_the_pre_post_read(self):
        """command 5 with anything but 0x01 is how the camera ends a session."""
        with self.assertRaises(ValueError):
            self._guard().sendSenserPacket(0x40, packet(5, 0, b'\x02'))

    def test_allows_reading_any_of_the_six(self):
        guard = self._guard()
        for pid in wifi.READ_IDS:
            guard.sendSenserPacket(0x40, packet(1, pid))

    def test_refuses_a_write_before_it_is_armed(self):
        with self.assertRaises(ValueError):
            self._guard().sendSenserPacket(0x40, packet(2, wifi.PID, wifi.TARGET))

    def test_arming_needs_the_exact_preimage(self):
        guard = self._guard()
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))     # reply is b'\x09'
        guard.arm(wifi.ORIGINAL, wifi.TARGET)
        with self.assertRaises(ValueError):
            guard.arm(wifi.ORIGINAL, wifi.TARGET)             # one write per session

    def test_arming_refuses_a_value_that_is_not_09_or_03(self):
        guard = self._guard(reply=b'\x01')
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        with self.assertRaises(ValueError):
            guard.arm(b'\x01', wifi.TARGET)

    def test_save_needs_a_verified_write(self):
        guard = self._guard()
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        guard.arm(wifi.ORIGINAL, wifi.TARGET)
        with self.assertRaises(ValueError):
            guard.allow_save()

    def test_a_failed_write_never_unlocks_save(self):
        transport = FakeTransport(response=0, reply=wifi.ORIGINAL)
        guard = wifi.WifiGuard(transport)
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        guard.arm(wifi.ORIGINAL, wifi.TARGET)
        transport.response = 1                      # the camera refuses the write
        guard.sendSenserPacket(0x40, packet(2, wifi.PID, wifi.TARGET))
        transport.response, transport.reply = 0, wifi.TARGET
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        with self.assertRaises(ValueError):
            guard.allow_save()

    def test_save_is_allowed_only_once(self):
        transport = FakeTransport(response=0, reply=wifi.ORIGINAL)
        guard = wifi.WifiGuard(transport)
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        guard.arm(wifi.ORIGINAL, wifi.TARGET)
        guard.sendSenserPacket(0x40, packet(2, wifi.PID, wifi.TARGET))
        transport.reply = wifi.TARGET
        guard.sendSenserPacket(0x40, packet(1, wifi.PID))
        guard.allow_save()
        guard.sendSenserPacket(0x40, SAVE_PACKET)
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, SAVE_PACKET)


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'sessions'
        self.cam = FakeWifiCamera()
        patcher = mock.patch.object(wifi, 'parse_snapshot',
                                    side_effect=lambda _snapshot: dict(self.cam.values))
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def connect(self):
        """A fresh guard and camera pairing, as a new service session gives."""
        guard = wifi.WifiGuard(LiveTransport(self.cam))
        return guard, GuardedCamera(self.cam, guard)

    def apply(self):
        guard, camera = self.connect()
        return wifi.apply(camera, guard, IDENTITY, self.root)

    def restore(self, source, identity=IDENTITY):
        guard, camera = self.connect()
        return wifi.restore(camera, guard, identity, self.root, source)


class TestStatus(Base):
    def test_status_reads_and_never_writes(self):
        guard, camera = self.connect()
        session = wifi.status(camera, IDENTITY, self.root)
        self.assertEqual(session.state, 'READ_ONLY_COMPLETE')
        self.assertEqual(self.cam.written, {})
        self.assertEqual(self.cam.saves, 0)

    def test_status_keeps_the_full_backup(self):
        guard, camera = self.connect()
        session = wifi.status(camera, IDENTITY, self.root)
        self.assertTrue((session.directory / 'Backup-original.bin').exists())


class TestApply(Base):
    def test_apply_writes_one_byte_and_saves(self):
        session = self.apply()
        self.assertEqual(session.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(list(self.cam.written), [wifi.PID])
        self.assertEqual(self.cam.written[wifi.PID], wifi.TARGET)
        self.assertEqual(self.cam.saves, 1)

    def test_apply_leaves_the_other_five_properties_alone(self):
        self.apply()
        for pid, value in wifi.COMPANIONS.items():
            self.assertEqual(self.cam.values[pid], value)

    def test_apply_is_a_no_op_when_already_at_03(self):
        self.cam.values[wifi.PID] = wifi.TARGET
        session = self.apply()
        self.assertEqual(session.state, 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertEqual(self.cam.written, {})
        self.assertEqual(self.cam.saves, 0)

    def test_apply_refuses_an_unexpected_c_index(self):
        self.cam.values[wifi.PID] = b'\x01'
        with self.assertRaises(ValueError) as ctx:
            self.apply()
        self.assertIn('00A5000C', str(ctx.exception))
        self.assertEqual(self.cam.written, {})

    def test_apply_refuses_when_a_companion_has_moved(self):
        self.cam.values[0x00A50009] = b'\x01'
        with self.assertRaises(ValueError) as ctx:
            self.apply()
        self.assertIn('00a50009', str(ctx.exception).lower())
        self.assertEqual(self.cam.written, {})

    def test_a_failed_write_leaves_a_journal_behind(self):
        self.cam.fail_on_write = wifi.PID
        with self.assertRaises(IOError):
            self.apply()
        sessions = journal.list_sessions(self.root)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].state, 'FAILED_REVIEW_REQUIRED')
        self.assertIn('error', sessions[0].journal)


class TestRestore(Base):
    def _applied(self):
        return self.apply().directory / 'journal.json'

    def test_restore_puts_the_recorded_value_back(self):
        source = self._applied()
        session = self.restore(source)
        self.assertEqual(session.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(self.cam.values[wifi.PID], wifi.ORIGINAL)
        self.assertEqual(self.cam.saves, 2)

    def test_restore_leaves_other_properties_where_they_are(self):
        source = self._applied()
        self.cam.values[0x00A5000B] = b'\x09'
        self.restore(source)
        self.assertEqual(self.cam.values[0x00A5000B], b'\x09')

    def test_restore_refuses_another_camera(self):
        source = self._applied()
        with self.assertRaises(ValueError):
            self.restore(source, identity=OTHER)

    def test_restore_refuses_a_journal_from_another_action(self):
        session = journal.create(self.root, 'write_slot', {'property': '0x1070be8'}, b'\x00')
        with self.assertRaises(ValueError):
            self.restore(session.directory / 'journal.json')

    def test_restore_when_already_original_does_not_save(self):
        source = self._applied()
        self.cam.values[wifi.PID] = wifi.ORIGINAL
        saves = self.cam.saves
        session = self.restore(source)
        self.assertEqual(session.state, 'ALREADY_AT_ORIGINAL_NO_SAVE')
        self.assertEqual(self.cam.saves, saves)

    def test_restore_refuses_a_third_value(self):
        source = self._applied()
        self.cam.values[wifi.PID] = b'\x01'
        with self.assertRaises(ValueError) as ctx:
            self.restore(source)
        self.assertIn('恢复冲突', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
