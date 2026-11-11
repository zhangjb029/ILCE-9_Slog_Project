import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import flash, flash_config as cfg, flash_service as service, journal, usbdev
from pmca.usb.sony import SonySenserCamera
from tests.flash_fakes import IDENTITY, PID, ServiceTransport, backup, config


def stack(transport):
    guard = service.FlashGuard(transport)
    return SonySenserCamera(guard), guard


class TestFlashConfig(unittest.TestCase):
    def test_changes_only_the_located_value_and_preserves_padding(self):
        original = config()
        target = cfg.with_policy(original, 0)
        # Index45 is record20: 20-byte header + 20*8 bytes + 4-byte key =184.
        self.assertEqual(target[184:188], b'\0\0\0\0')
        self.assertEqual([i for i in range(1024) if original[i] != target[i]], [184])
        self.assertEqual(cfg.parse(target).value, 0)
        self.assertEqual(cfg.with_policy(target, 1), original)

    def test_rejects_invalid_schema_and_ambiguous_index(self):
        mutations = [
            (0, b'BAD!'), (4, struct.pack('<I', 0)),
            (8, struct.pack('<I', 855)), (12, struct.pack('<I', 20160708)),
            (16, struct.pack('<I', 103)), (852, b'BAD!'),
            (180, struct.pack('<I', 0x44)),  # index45 missing, duplicate44
            (188, struct.pack('<I', 0x45)),  # duplicate45
            (184, struct.pack('<I', 2)),
        ]
        for offset, content in mutations:
            with self.subTest(offset=offset, content=content):
                data = bytearray(config())
                data[offset:offset+len(content)] = content
                with self.assertRaises(ValueError):
                    cfg.with_policy(bytes(data), 0)
        for raw in (b'', config()[:-1], config() + b'\0'):
            with self.assertRaises(ValueError):
                cfg.parse(raw)

    def test_backup_attribute_checksum_and_length_are_validated(self):
        self.assertEqual(cfg.from_backup(backup(config())), config())
        for attr in (1, 2, 8, 0x50):
            with self.subTest(attr=attr), self.assertRaises(ValueError):
                cfg.from_backup(backup(config(), attr))
        corrupt = bytearray(backup(config()))
        corrupt[-1] ^= 1
        for raw in (bytes(corrupt), backup(config())[:-20]):
            with self.assertRaises(ValueError):
                cfg.from_backup(raw)


class TestFlashTransactions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'flash'
        self.transport = ServiceTransport()
        self.camera, self.guard = stack(self.transport)

    def apply(self):
        return service.apply(self.camera, self.guard, IDENTITY, self.root)

    def records(self):
        return [journal.load(p) for p in self.root.glob('*/journal.json')]

    def test_status_cannot_write_or_save(self):
        session = service.status(self.camera, IDENTITY, self.root)
        self.assertEqual(session.state, 'READ_ONLY_COMPLETE')
        self.assertEqual(session.payload['restriction'], 1)
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.transport.saves, 0)

    def test_apply_persists_original_before_write_and_verifies_one_property(self):
        original = self.transport.data
        def before():
            record, = self.records()
            self.assertEqual(record.state, 'WRITE_PENDING')
            self.assertEqual(cfg.from_backup((record.directory / 'Backup-original.bin').read_bytes()), original)
        self.transport.before_write = before
        session = self.apply()
        self.assertEqual(session.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(self.transport.data[:184] + self.transport.data[188:], original[:184] + original[188:])
        self.assertEqual(self.transport.data[184:188], b'\0' * 4)
        self.assertEqual(self.transport.saves, 1)
        self.assertFalse(session.journal['physical_trigger_verified'])

    def test_already_at_target_never_writes_or_saves(self):
        self.transport.data = config(0)
        session = self.apply()
        self.assertEqual(session.state, 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.transport.saves, 0)

    def test_rejects_wrong_identity_before_any_service_request(self):
        for identity in ({}, dict(IDENTITY, model='ILCE-9M2'), dict(IDENTITY, firmware='5.00')):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                service.apply(self.camera, self.guard, identity, self.root)
        self.assertEqual(self.transport.packets, [])

    def test_rejects_protected_or_snapshot_mismatched_property(self):
        self.transport.attr = 1
        with self.assertRaises(ValueError):
            self.apply()
        self.transport.attr = 0
        self.transport.snapshot_override = backup(config(0))
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.transport.writes, [])

    def test_rechecks_baseline_immediately_before_write(self):
        self.transport.race_on_read = 2
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.transport.saves, 0)
        self.assertEqual(self.records()[0].state, 'FAILED_REVIEW_REQUIRED')

    def test_snapshot_persistence_failure_prevents_all_writes(self):
        with mock.patch.object(journal, '_write_snapshot', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(self.transport.saves, 0)

    def test_ambiguous_write_is_never_retried_or_saved(self):
        self.transport.write_error = True
        with self.assertRaises(IOError):
            self.apply()
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(self.transport.saves, 0)
        self.assertEqual(self.records()[0].state, 'FAILED_REVIEW_REQUIRED')
        with self.assertRaises(ValueError):
            self.camera.writeBackup(PID, self.transport.data)
        self.assertEqual(len(self.transport.writes), 1)

    def test_immediate_mismatch_never_saves(self):
        self.transport.bad_readback = True
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.transport.saves, 0)
        self.assertEqual(self.records()[0].state, 'FAILED_REVIEW_REQUIRED')

    def test_save_mismatch_leaves_failure_record(self):
        self.transport.bad_saved_readback = True
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(self.transport.saves, 1)
        self.assertEqual(self.records()[0].state, 'FAILED_REVIEW_REQUIRED')

    def test_restore_returns_exact_original_using_a_new_guard(self):
        original = self.transport.data
        session = self.apply()
        camera, guard = stack(self.transport)
        restored = service.restore(camera, guard, IDENTITY, self.root, session.directory / 'journal.json')
        self.assertEqual(self.transport.data, original)
        self.assertEqual(restored.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(len(self.transport.writes), 2)

    def test_restore_refuses_another_body_before_device_access(self):
        session = self.apply()
        count = len(self.transport.packets)
        camera, guard = stack(self.transport)
        with self.assertRaises(ValueError):
            service.restore(camera, guard, dict(IDENTITY, serial_sha256='b' * 64),
                            self.root, session.directory / 'journal.json')
        self.assertEqual(len(self.transport.packets), count)

    def test_restore_refuses_changes_to_other_records(self):
        session = self.apply()
        data = bytearray(self.transport.data)
        data[-1] ^= 1
        self.transport.data = bytes(data)
        camera, guard = stack(self.transport)
        with self.assertRaises(ValueError):
            service.restore(camera, guard, IDENTITY, self.root, session.directory / 'journal.json')
        self.assertEqual(len(self.transport.writes), 1)

    def test_restore_checks_payload_against_hashed_original_snapshot(self):
        session = self.apply()
        path = session.directory / 'journal.json'
        record = json.loads(path.read_text(encoding='utf-8'))
        record['payload']['original'] = config(0).hex()
        path.write_text(json.dumps(record), encoding='utf-8')
        camera, guard = stack(self.transport)
        with self.assertRaises(ValueError):
            service.restore(camera, guard, IDENTITY, self.root, path)
        self.assertEqual(len(self.transport.writes), 1)


class TestFlashGuard(unittest.TestCase):
    def setUp(self):
        self.transport = ServiceTransport()
        self.camera, self.guard = stack(self.transport)

    def arm(self):
        original = self.camera.readBackup(PID)
        self.guard.arm(original, cfg.with_policy(original, 0))

    def test_blocks_unarmed_write_and_all_non_flash_writes(self):
        for pid, data in ((PID, config(0)), (0x00880000, bytes(1024)), (0x01070be8, b'\x3a')):
            with self.assertRaises(ValueError):
                self.camera.writeBackup(pid, data)
        self.assertEqual(self.transport.packets, [])

    def test_blocks_whole_backup_protection_ram_and_terminal(self):
        for function, payload in ((0x40, struct.pack('<HH', 0x603, 4) + bytes(8)),
                                  (0x40, struct.pack('<HHB', 0x603, 15, 0)),
                                  (0x41, bytes(12)), (0x42, bytes(12))):
            with self.assertRaises(ValueError):
                self.guard.sendSenserPacket(function, payload)
        self.assertEqual(self.transport.packets, [])

    def test_arming_requires_observed_original_and_exact_policy_change(self):
        with self.assertRaises(ValueError):
            self.guard.arm(config(), config(0))
        self.camera.readBackup(PID)
        changed = bytearray(config(0))
        changed[-1] ^= 1
        with self.assertRaises(ValueError):
            self.guard.arm(config(), bytes(changed))

    def test_only_exact_payload_once_and_verified_save_once(self):
        self.arm()
        with self.assertRaises(ValueError):
            self.camera.writeBackup(PID, config(0)[:-1])
        self.camera.writeBackup(PID, config(0))
        with self.assertRaises(ValueError):
            self.camera.writeBackup(PID, config(0))
        with self.assertRaises(ValueError):
            self.camera.saveBackup(0)
        with self.assertRaises(ValueError):
            self.guard.allow_save()
        self.camera.readBackup(PID)
        self.guard.allow_save()
        with self.assertRaises(ValueError):
            self.camera.saveBackup(2)
        self.camera.saveBackup(0)
        with self.assertRaises(ValueError):
            self.camera.saveBackup(0)
        self.assertEqual(len(self.transport.writes), 1)
        self.assertEqual(self.transport.saves, 1)


class TestFlashCli(unittest.TestCase):
    def test_help_does_not_connect(self):
        with mock.patch.object(usbdev, 'connect', side_effect=AssertionError('device access')):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
                flash.main(['--help'])
        self.assertEqual(result.exception.code, 0)

    def test_default_command_is_read_only_and_closes_handle(self):
        transport = ServiceTransport()
        closed = []
        def connect(*args, guard_factory, **kwargs):
            guard = guard_factory(transport)
            return type('Handle', (), dict(camera=SonySenserCamera(guard), guard=guard,
                        identity=IDENTITY, close=lambda _self: closed.append(True)))()
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(usbdev, 'connect', side_effect=connect):
            with contextlib.redirect_stdout(io.StringIO()):
                result = flash.main(['--sessions-root', folder])
        self.assertEqual(result, 0)
        self.assertEqual(transport.writes, [])
        self.assertEqual(transport.saves, 0)
        self.assertEqual(closed, [True])


if __name__ == '__main__':
    unittest.main()
