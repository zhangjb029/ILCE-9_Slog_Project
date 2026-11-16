"""The force-rollback lane: two bytes, one write, and the gate around it."""
import struct
import tempfile
import unittest
from pathlib import Path

from a9tool import firmware_reset, journal, usbdev

DAT4 = firmware_reset.DAT4
V600 = firmware_reset.V600
V500 = firmware_reset.V500
IDENTITY = dict(model='ILCE-9', firmware='6.00', serial_sha256='a' * 64)


class FakeFileCamera:
    """Only the two FileControl calls this module makes.

    ``scripted_reads`` replays a fixed sequence of values so a readback that
    disagrees with what was written can be simulated.
    """

    def __init__(self, value: bytes = V600, scripted_reads=None):
        self.files = {DAT4: bytes(value)}
        self.writes = []
        self.reads = []
        self.scripted_reads = list(scripted_reads or [])

    def readFile(self, path, sink):
        self.reads.append(path)
        if self.scripted_reads:
            sink.write(self.scripted_reads.pop(0))
            return
        if path not in self.files:
            raise IOError(f'no such file: {path}')
        sink.write(self.files[path])

    def writeFile(self, path, data):
        self.writes.append((path, bytes(data)))
        self.files[path] = bytes(data)


class FakeTransport:
    def __init__(self):
        self.sent = []

    def sendSenserPacket(self, function, data, oData=None):
        if oData is not None:
            oData.write(b'\x00\x06')
        self.sent.append((function, data))
        return 0, b''


def file_packet(command: int, name: str, body: bytes = b'') -> bytes:
    raw = name.encode('latin1')
    return struct.pack('<hh', command, len(raw)) + raw + body


class TestEncoding(unittest.TestCase):
    def test_the_two_versions_are_named(self):
        self.assertEqual(firmware_reset.describe(V600), '6.00')
        self.assertEqual(firmware_reset.describe(V500), '5.00')

    def test_an_unknown_value_is_shown_as_its_hex(self):
        self.assertEqual(firmware_reset.describe(b'\x99\x09'), '0999')

    def test_a_wrong_length_is_not_guessed(self):
        self.assertIn('长度异常', firmware_reset.describe(b'\x00'))


class TestRelaxedIdentity(unittest.TestCase):
    def test_a_body_reporting_500_still_connects(self):
        firmware_reset.check_identity(dict(IDENTITY, firmware='5.00'))

    def test_another_model_is_still_refused(self):
        with self.assertRaises(ValueError):
            firmware_reset.check_identity(dict(IDENTITY, model='ILCE-9M2'))

    def test_a_missing_fingerprint_is_still_refused(self):
        with self.assertRaises(ValueError):
            firmware_reset.check_identity(dict(IDENTITY, serial_sha256=''))

    def test_the_strict_gate_is_untouched(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity(dict(IDENTITY, firmware='5.00'))


class TestGuard(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.guard = firmware_reset.Dat4Guard(self.transport, allow_write=True)

    def test_read_of_dat4_is_allowed(self):
        self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL, file_packet(2, DAT4))
        self.assertEqual(len(self.transport.sent), 1)

    def test_read_of_companion_is_allowed(self):
        self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                    file_packet(2, '/setting/updater/COMP'))

    def test_read_outside_the_allowlist_is_refused(self):
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                        file_packet(2, '/dev/nflasha15'))

    def test_parameter_traffic_is_refused(self):
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(0x40, struct.pack('<HH', 0x603, 1) + b'\x00' * 4)

    def test_write_without_arming_is_refused(self):
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                        file_packet(1, DAT4, V500))

    def test_write_of_a_different_value_is_refused(self):
        self.guard.arm(V500)
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                        file_packet(1, DAT4, b'\x00\x07'))

    def test_write_of_the_wrong_length_is_refused(self):
        self.guard.arm(V500)
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                        file_packet(1, DAT4, b'\x05'))

    def test_write_to_another_path_is_refused(self):
        self.guard.arm(V500)
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                        file_packet(1, '/setting/Backup.bin', V500))

    def test_exactly_one_write_per_session(self):
        self.guard.arm(V500)
        self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL, file_packet(1, DAT4, V500))
        with self.assertRaises(ValueError):
            self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL, file_packet(1, DAT4, V500))

    def test_the_sink_travels_through(self):
        sink = __import__('io').BytesIO()
        self.guard.sendSenserPacket(firmware_reset.PFUNC_FILE_CONTROL,
                                    file_packet(2, DAT4), sink)
        self.assertEqual(sink.getvalue(), V600)


class TestTransactions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _guard(self, camera, allow_write=True):
        return firmware_reset.Dat4Guard(camera, allow_write=allow_write)

    def test_status_reads_and_writes_nothing(self):
        camera = FakeFileCamera(V600)
        session = firmware_reset.status(camera, IDENTITY, self.root)
        self.assertEqual(camera.writes, [])
        self.assertEqual(session.state, 'READ_ONLY_COMPLETE')
        self.assertEqual(session.payload['version'], '6.00')

    def test_open_gate_writes_500(self):
        camera = FakeFileCamera(V600)
        session = firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertEqual(camera.writes, [(DAT4, V500)])
        self.assertEqual(session.state, 'WRITE_VERIFIED')
        self.assertEqual(session.journal['readback'], V500.hex())

    def test_open_gate_records_the_original_bytes_before_writing(self):
        camera = FakeFileCamera(V600)
        session = firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        saved = (session.directory / 'Backup-original.bin').read_bytes()
        self.assertEqual(saved, V600)
        self.assertEqual(session.payload['dat4'], V600.hex())

    def test_open_gate_is_a_no_op_when_already_open(self):
        camera = FakeFileCamera(V500)
        session = firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertEqual(camera.writes, [])
        self.assertEqual(session.state, 'ALREADY_AT_TARGET_NO_WRITE')

    def test_open_gate_refuses_an_unexpected_value(self):
        camera = FakeFileCamera(b'\x00\x07')
        with self.assertRaises(ValueError):
            firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertEqual(camera.writes, [])

    def test_close_gate_writes_600(self):
        camera = FakeFileCamera(V500)
        session = firmware_reset.close_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertEqual(camera.writes, [(DAT4, V600)])
        self.assertEqual(session.state, 'WRITE_VERIFIED')

    def test_a_readback_that_disagrees_fails_the_transaction(self):
        camera = FakeFileCamera(V600, scripted_reads=[V600, V600, b'\x00\x07'])
        with self.assertRaises(ValueError) as ctx:
            firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertIn('回读', str(ctx.exception))
        self.assertEqual(camera.writes, [(DAT4, V500)])

    def test_a_value_that_moved_after_the_snapshot_stops_the_write(self):
        camera = FakeFileCamera(V600, scripted_reads=[V600, b'\x00\x04'])
        with self.assertRaises(ValueError):
            firmware_reset.open_gate(camera, self._guard(camera), IDENTITY, self.root)
        self.assertEqual(camera.writes, [])

    def test_the_write_guard_must_be_the_dat4_one(self):
        camera = FakeFileCamera(V600)
        with self.assertRaises(ValueError):
            firmware_reset.open_gate(camera, object(), IDENTITY, self.root)
        self.assertEqual(camera.writes, [])


class TestReceiptAt500(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_500_receipt_is_skipped_by_the_strict_path(self):
        usbdev.save_receipt(dict(IDENTITY, firmware='5.00'), {'bus': 1, 'ports': [2]},
                            root=self.root)
        with self.assertRaises(ValueError):
            usbdev.load_current_receipt(root=self.root)

    def test_the_same_receipt_is_usable_by_the_rollback_tab(self):
        usbdev.save_receipt(dict(IDENTITY, firmware='5.00'), {'bus': 1, 'ports': [2]},
                            root=self.root)
        path = usbdev.load_current_receipt(root=self.root,
                                           identity_check=firmware_reset.check_identity)
        self.assertIsNotNone(path)


if __name__ == '__main__':
    unittest.main()
