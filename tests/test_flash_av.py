import contextlib
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import journal, usbdev
from pmca.usb.sony import SonySenserCamera
from tests.flash_av_fakes import AV_PID, MENU_PID, IDENTITY, Transport, av_data, backup, config

HAS_MODULE = importlib.util.find_spec('a9tool.flash_av') is not None
if HAS_MODULE:
    from a9tool import flash_av as av


class TestAVEntryExists(unittest.TestCase):
    def test_separate_experimental_entry_exists(self):
        self.assertTrue(HAS_MODULE, 'Missing isolated AV eligibility experiment')


@unittest.skipUnless(HAS_MODULE, 'Implementation not present yet')
class TestFlashAV(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.transport = Transport()
        self.connect()

    def connect(self):
        self.guard = av.AVGuard(self.transport)
        self.camera = SonySenserCamera(self.guard)

    def apply(self):
        return av.apply(self.camera, self.guard, IDENTITY, self.root)

    def records(self):
        return [journal.load(p) for p in self.root.glob('*/journal.json')]

    def test_byte_change_round_trip_and_unknown_values_rejected(self):
        before = av_data()
        after = av.with_eligibility(before, 1)
        self.assertEqual([i for i in range(256) if before[i] != after[i]], [0xAD])
        self.assertEqual(av.with_eligibility(after, 0), before)
        for data in (b'', before[:-1], before + b'\0', av_data(2), av_data(255)):
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                av.with_eligibility(data, 1)
        with self.assertRaises(ValueError):
            av.with_eligibility(before, 2)

    def test_snapshot_metadata_and_checksum(self):
        menu, data = av.from_backup(backup(config(0), av_data()))
        self.assertEqual((menu, data), (config(0), av_data()))
        for flags in (0, 1, 9, 0x18):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                av.from_backup(backup(config(0), av_data(), flags))
        bad = bytearray(backup(config(0), av_data()))
        bad[-1] ^= 1
        with self.assertRaises(ValueError):
            av.from_backup(bytes(bad))

    def test_status_reads_both_but_never_writes(self):
        s = av.status(self.camera, IDENTITY, self.root)
        self.assertEqual(s.state, 'READ_ONLY_COMPLETE')
        self.assertEqual((s.payload['menu_restriction'], s.payload['av_eligibility']), (0, 0))
        self.assertEqual((self.transport.writes, self.transport.saves), ([], 0))

    def test_apply_only_changes_av_and_backups_exist_before_write(self):
        original = dict(self.transport.data)
        def check():
            s, = self.records()
            self.assertEqual(s.state, 'WRITE_PENDING')
            self.assertEqual(av.from_backup((s.directory/'Backup-original.bin').read_bytes()),
                             (original[MENU_PID], original[AV_PID]))
        self.transport.before_write = check
        s = self.apply()
        self.assertEqual(s.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(self.transport.data[MENU_PID], original[MENU_PID])
        self.assertEqual(self.transport.writes, [(AV_PID, av.with_eligibility(original[AV_PID], 1))])
        self.assertEqual(self.transport.saves, 1)
        self.assertFalse(s.journal['physical_trigger_verified'])
        self.assertFalse(s.journal['hardware_safety_verified'])

    def test_apply_refuses_closed_menu_without_writes(self):
        self.transport.data[MENU_PID] = config(1)
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual((self.transport.writes, self.transport.saves), ([], 0))

    def test_already_enabled_no_write_or_save(self):
        self.transport.data[AV_PID] = av_data(1)
        self.assertEqual(self.apply().state, 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertEqual((self.transport.writes, self.transport.saves), ([], 0))

    def test_bad_identity_prevents_all_access(self):
        for identity in ({}, dict(IDENTITY, firmware='5.00'), dict(IDENTITY, model='ILCE-9M2')):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                av.apply(self.camera, self.guard, identity, self.root)
        self.assertEqual(self.transport.packets, [])

    def test_snapshot_disagreement_and_wrong_attr_stop(self):
        for which in ('attr', 'snapshot'):
            self.transport.attr = 1 if which == 'attr' else 8
            self.transport.snapshot_override = backup(config(0), av_data(1)) if which == 'snapshot' else None
            with self.assertRaises(ValueError):
                self.apply()
        self.assertEqual(self.transport.writes, [])

    def test_rechecks_both_properties_after_backup(self):
        for pid in (MENU_PID, AV_PID):
            self.transport = Transport()
            self.connect()
            def change(read_pid, count):
                if count >= 3 and read_pid == pid:
                    raw = bytearray(self.transport.data[pid]); raw[-1] ^= 1
                    self.transport.data[pid] = bytes(raw)
            self.transport.before_read = change
            with self.subTest(pid=pid), self.assertRaises(ValueError):
                self.apply()
            self.assertEqual((self.transport.writes, self.transport.saves), ([], 0))

    def test_snapshot_failure_prevents_writes(self):
        with mock.patch.object(journal, '_write_snapshot', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.apply()
        self.assertEqual(self.transport.writes, [])

    def test_ambiguous_write_no_retry_no_save(self):
        self.transport.write_error = True
        with self.assertRaises(IOError):
            self.apply()
        self.assertEqual((len(self.transport.writes), self.transport.saves), (1, 0))
        self.assertEqual(self.records()[0].state, 'FAILED_REVIEW_REQUIRED')
        with self.assertRaises(ValueError):
            self.camera.writeBackup(AV_PID, av_data(1))

    def test_readback_mismatches_leave_failure_and_never_retry(self):
        for saved in (False, True):
            self.transport = Transport(); self.connect()
            self.transport.bad_readback = not saved
            self.transport.bad_saved_readback = saved
            with self.subTest(saved=saved), self.assertRaises(ValueError):
                self.apply()
            self.assertEqual(len(self.transport.writes), 1)
            self.assertEqual(self.transport.saves, int(saved))

    def test_restore_exact_original_even_if_menu_was_restored_separately(self):
        s = self.apply()
        self.transport.data[MENU_PID] = config(1)
        self.connect()
        restored = av.restore(self.camera, self.guard, IDENTITY, self.root, s.directory/'journal.json')
        self.assertEqual(restored.state, 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(self.transport.data, {MENU_PID:config(1), AV_PID:av_data(0)})

    def test_restore_rejects_other_body_before_access(self):
        s = self.apply(); self.connect()
        count = len(self.transport.packets)
        with self.assertRaises(ValueError):
            av.restore(self.camera, self.guard, dict(IDENTITY,serial_sha256='b'*64), self.root, s.directory/'journal.json')
        self.assertEqual(len(self.transport.packets), count)

    def test_restore_conflict_does_not_overwrite(self):
        s = self.apply(); self.connect()
        data = bytearray(self.transport.data[AV_PID]); data[-1] ^= 1
        self.transport.data[AV_PID] = bytes(data)
        with self.assertRaises(ValueError):
            av.restore(self.camera, self.guard, IDENTITY, self.root, s.directory/'journal.json')
        self.assertEqual(len(self.transport.writes), 1)

    def test_restore_rejects_modified_journal(self):
        s = self.apply()
        p = s.directory/'journal.json'
        record = json.loads(p.read_text(encoding='utf-8'))
        record['payload']['original'] = av_data(1).hex()
        p.write_text(json.dumps(record),encoding='utf-8')
        with self.assertRaises(ValueError):
            av.load_source(p)

    def test_guard_rejects_menu_and_arbitrary_writes(self):
        for pid,data in ((MENU_PID, config(0)),(AV_PID,av_data(1)),(0x880000,b'\0'*1024)):
            with self.assertRaises(ValueError):
                self.camera.writeBackup(pid,data)
        for function,data in ((0x40,struct.pack('<HHB',0x603,15,0)),(0x41,bytes(12)),
                              (0x42,bytes(12)),(0x40,struct.pack('<HH',0x603,4)+bytes(8))):
            with self.assertRaises(ValueError):
                self.guard.sendSenserPacket(function,data)
        self.assertEqual(self.transport.packets,[])

    def test_guard_exact_single_write_and_save_with_both_readbacks(self):
        menu = self.camera.readBackup(MENU_PID)
        before = self.camera.readBackup(AV_PID)
        target = av.with_eligibility(before,1)
        self.guard.arm(menu,before,target)
        with self.assertRaises(ValueError):
            self.camera.writeBackup(AV_PID,target[:-1])
        self.camera.writeBackup(AV_PID,target)
        with self.assertRaises(ValueError):
            self.camera.writeBackup(AV_PID,target)
        with self.assertRaises(ValueError):
            self.guard.allow_save()
        self.camera.readBackup(AV_PID)
        with self.assertRaises(ValueError):
            self.guard.allow_save()
        self.camera.readBackup(MENU_PID)
        self.guard.allow_save(); self.camera.saveBackup(0)
        with self.assertRaises(ValueError):
            self.camera.saveBackup(0)

    def test_guard_rejects_unobserved_original_or_extra_byte(self):
        with self.assertRaises(ValueError):
            self.guard.arm(config(0),av_data(0),av_data(1))
        self.camera.readBackup(MENU_PID); self.camera.readBackup(AV_PID)
        raw=bytearray(av_data(1)); raw[-1]^=1
        with self.assertRaises(ValueError):
            self.guard.arm(config(0),av_data(0),bytes(raw))

    def test_cli_help_and_invalid_restore_do_not_connect(self):
        with mock.patch.object(usbdev,'connect',side_effect=AssertionError('USB access')):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as r:
                av.main(['--help'])
            self.assertEqual(r.exception.code,0)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                av.main(['restore'])

    def test_cli_write_requires_detachment_declaration_before_connection(self):
        with mock.patch.object(usbdev,'connect',side_effect=AssertionError('USB access')):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as result:
                av.main(['apply'])
        self.assertEqual(result.exception.code,2)

    def test_cli_default_readonly_and_closes(self):
        closed=[]
        def connect(*args,guard_factory,**kwargs):
            g=guard_factory(self.transport)
            return type('Handle',(),dict(camera=SonySenserCamera(g),guard=g,identity=IDENTITY,
                         close=lambda _self:closed.append(True)))()
        with mock.patch.object(usbdev,'connect',side_effect=connect),contextlib.redirect_stdout(io.StringIO()):
            result=av.main(['--sessions-root',str(self.root)])
        self.assertEqual(result,0)
        self.assertEqual((self.transport.writes,self.transport.saves,closed),([],0,[True]))
