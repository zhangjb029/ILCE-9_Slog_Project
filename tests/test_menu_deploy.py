import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import menu_deploy as md

SMALL = 8192
IDENTITY = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}
LEGACY_SHA = 'f' * 64


def fake_partition(fill: int = 0x11, size: int = SMALL) -> bytes:
    raw = bytearray([fill] * size)
    raw[:1024] = bytes(1024)
    raw[1080:1082] = b'\x53\xef'
    return bytes(raw)


class FakeCamera:
    def __init__(self, data: bytes):
        self.data = bytearray(data)
        self.reads = 0
        self.writes = 0
        self.truncate_read = False

    def readFile(self, path, out):
        assert path == md.PARTITION
        self.reads += 1
        blob = bytes(self.data)
        if self.truncate_read:
            blob = blob[:1000]
        out.write(blob)
        return 0

    def writeFile(self, path, data):
        assert path == md.PARTITION
        self.writes += 1
        self.data = bytearray(data)
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        # Identify-on-backup reads an ext2 image; the fakes here are not one.
        patcher = mock.patch.object(md.versions, 'identify_file',
                                    return_value={'readable': False, 'matched': False,
                                                  'label': None, 'note': 'fake', 'mismatch': []})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(self._tmp.name) / 'sessions'

        self.factory = fake_partition(0x11)
        candidate = bytearray(self.factory)
        candidate[2000:2002] = b'\xaa\xbb'
        candidate[5000] = 0x5a
        self.candidate = bytes(candidate)
        self.patch = ((2000, b'\xaa\xbb'), (5000, b'\x5a'))
        lut_sha = hashlib.sha256(self.candidate).hexdigest()

        for patcher in (
            mock.patch.object(md, 'PARTITION_BYTES', SMALL),
            mock.patch.object(md, 'FACTORY_SHA', hashlib.sha256(self.factory).hexdigest()),
            mock.patch.object(md, 'LUT_SHA', lut_sha),
            mock.patch.object(md, 'TARGETS', {'lut': (lut_sha, 'LUT')}),
            mock.patch.object(md, 'LEGACY_SHAS', {LEGACY_SHA: '旧版「菜单修改」'}),
            mock.patch.object(md, 'load_patch', new=lambda: self.patch),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()


class TestGuard(unittest.TestCase):
    def test_rejects_non_file_control(self):
        guard = md.PartitionGuard(object(), allow_write=True)
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0x40, b'\x00' * 8)

    def test_rejects_write_when_not_armed(self):
        guard = md.PartitionGuard(object())
        payload = struct.pack('<hh', md.FILE_WRITE, len(md.PARTITION)) + md.PARTITION.encode() + bytes(md.PARTITION_BYTES)
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(md.PFUNC_FILE_CONTROL, payload)

    def test_rejects_wrong_size(self):
        guard = md.PartitionGuard(object(), allow_write=True)
        payload = struct.pack('<hh', md.FILE_WRITE, len(md.PARTITION)) + md.PARTITION.encode() + bytes(10)
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(md.PFUNC_FILE_CONTROL, payload)

    def test_rejects_other_path(self):
        guard = md.PartitionGuard(object(), allow_write=True)
        name = '/dev/nflasha14'
        payload = struct.pack('<hh', md.FILE_WRITE, len(name)) + name.encode() + bytes(md.PARTITION_BYTES)
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(md.PFUNC_FILE_CONTROL, payload)


class TestBuildCandidate(Base):
    def test_factory_partition_becomes_the_candidate(self):
        self.assertEqual(md.build_candidate(self.factory), self.candidate)

    def test_partition_already_at_target_is_refused(self):
        with self.assertRaises(ValueError):
            md.build_candidate(self.candidate)

    def test_legacy_build_is_refused_with_a_way_forward(self):
        legacy = fake_partition(0x22)
        with mock.patch.object(md, 'LEGACY_SHAS',
                               {hashlib.sha256(legacy).hexdigest(): '旧版「菜单修改」'}):
            with self.assertRaises(ValueError) as ctx:
                md.build_candidate(legacy)
        self.assertIn('旧版', str(ctx.exception))
        self.assertIn('回退', str(ctx.exception))

    def test_unknown_partition_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            md.build_candidate(fake_partition(0x33))
        self.assertIn('原厂', str(ctx.exception))

    def test_unknown_target_is_refused(self):
        with self.assertRaises(ValueError):
            md.build_candidate(self.factory, 'nonsense')

    def test_a_patch_that_misses_the_target_hash_is_refused(self):
        with mock.patch.object(md, 'load_patch', new=lambda: ((2000, b'\xaa\xbb'),)):
            with self.assertRaises(ValueError) as ctx:
                md.build_candidate(self.factory)
        self.assertIn('哈希', str(ctx.exception))

    def test_sanity_rejects_non_ext2(self):
        with self.assertRaises(ValueError):
            md.sanity(bytes(SMALL))


class TestBackup(Base):
    def test_backup_saves_the_partition_without_writing(self):
        cam = FakeCamera(self.factory)
        info = md.backup(cam, IDENTITY, self.root)
        self.assertEqual(info['bytes'], SMALL)
        self.assertEqual((self.root / 'baseline' / 'preimage.bin').read_bytes(), self.factory)
        self.assertEqual(cam.writes, 0)

    def test_backup_never_overwrites(self):
        md.backup(FakeCamera(self.factory), IDENTITY, self.root)
        with self.assertRaises(ValueError):
            md.backup(FakeCamera(self.factory), IDENTITY, self.root)

    def test_incomplete_backup_leaves_no_baseline(self):
        cam = FakeCamera(self.factory)
        cam.truncate_read = True
        with self.assertRaises(ValueError):
            md.backup(cam, IDENTITY, self.root)
        self.assertFalse((self.root / 'baseline' / 'preimage.bin').exists())

    def test_a_sink_that_received_nothing_is_reported_as_such(self):
        """Zero bytes means the file channel never worked, not a short read."""
        class SilentCamera(FakeCamera):
            def readFile(self, path, out):
                return 0          # the bytes went to the return value instead
        target = Path(self._tmp.name) / 'silent.bin'
        with self.assertRaises(ValueError) as ctx:
            md.read_partition(SilentCamera(self.factory), target)
        self.assertIn('没有收到任何字节', str(ctx.exception))

    def test_an_interrupted_read_records_how_far_it_got(self):
        """The failure report must say where the transfer stopped."""
        class DyingCamera(FakeCamera):
            def readFile(self, path, out):
                out.write(bytes(self.data[:4096]))
                raise OSError('Invalid or empty service response')
        target = Path(self._tmp.name) / 'partial.bin'
        with self.assertRaises(OSError) as ctx:
            md.read_partition(DyingCamera(self.factory), target)
        notes = '\n'.join(getattr(ctx.exception, '__notes__', []))
        self.assertIn('4,096', notes)
        self.assertIn(str(target.parent), notes)
        self.assertTrue(target.exists())

    def test_backup_announces_where_its_session_lands(self):
        """So "sessions is empty" can be answered without guessing."""
        seen = []
        md.backup(FakeCamera(self.factory), IDENTITY, self.root, progress=seen.append)
        joined = '\n'.join(seen)
        self.assertIn('会话目录：', joined)
        self.assertIn('backup_', joined)


class TestIdentify(Base):
    def _backup(self):
        with mock.patch.object(md.versions, 'identify_file',
                               return_value={'label': 'x', 'matched': True}):
            return md.backup(FakeCamera(self.factory), IDENTITY, self.root)

    def test_backup_alone_does_not_claim_a_version(self):
        info = self._backup()
        self.assertNotIn('version', info)

    def test_identify_records_what_it_found(self):
        self._backup()
        with mock.patch.object(md.versions, 'identify_file',
                               return_value={'label': '原厂 6.00', 'matched': True}) as spy:
            result = md.identify(self.root)
        self.assertEqual(result['label'], '原厂 6.00')
        self.assertEqual(spy.call_count, 1)
        self.assertEqual(md.baseline_info(self.root)['version']['label'], '原厂 6.00')

    def test_identify_works_on_a_backup_taken_before_it_existed(self):
        self._backup()
        record = md.baseline_path(self.root).with_suffix('.json')
        meta = json.loads(record.read_text(encoding='utf-8'))
        meta.pop('version', None)
        record.write_text(json.dumps(meta), encoding='utf-8')
        with mock.patch.object(md.versions, 'identify_file',
                               return_value={'label': 'R12', 'matched': True}):
            md.identify(self.root)
        self.assertEqual(md.baseline_info(self.root)['version']['label'], 'R12')

    def test_identify_needs_a_backup_first(self):
        with self.assertRaises(ValueError):
            md.identify(Path(self._tmp.name) / 'nothing-here')

    def test_identify_still_answers_when_the_record_cannot_be_rewritten(self):
        self._backup()
        record = md.baseline_path(self.root).with_suffix('.json')
        record.chmod(0o444)
        try:
            with mock.patch.object(md.versions, 'identify_file',
                                   return_value={'label': 'R12', 'matched': True}):
                self.assertEqual(md.identify(self.root)['label'], 'R12')
        finally:
            record.chmod(0o666)

    def test_retaking_a_backup_needs_permission(self):
        self._backup()
        with self.assertRaises(ValueError):
            md.backup(FakeCamera(self.factory), IDENTITY, self.root)
        with mock.patch.object(md.versions, 'identify_file',
                               return_value={'label': 'x', 'matched': True}):
            info = md.backup(FakeCamera(self.factory), IDENTITY, self.root, replace=True)
        self.assertEqual(info['bytes'], SMALL)

    def test_the_partition_hash_is_not_recomputed_for_an_unchanged_file(self):
        self._backup()
        baseline = md.baseline_path(self.root)
        md._HASH_CACHE.clear()
        with mock.patch.object(md.hashlib, 'file_digest',
                               wraps=md.hashlib.file_digest) as spy:
            md.file_sha256(baseline)
            md.file_sha256(baseline)
        self.assertEqual(spy.call_count, 1)


class TestPatch(Base):
    def setUp(self):
        super().setUp()
        md.backup(FakeCamera(self.factory), IDENTITY, self.root)

    def test_patch_from_baseline(self):
        meta = md.patch_from_baseline(self.root)
        self.assertEqual(meta['sha256'], md.TARGETS['lut'][0])
        self.assertEqual((md.pending_dir(self.root) / 'candidate.bin').read_bytes(), self.candidate)

    def test_patch_requires_a_baseline(self):
        empty = Path(self._tmp.name) / 'no-baseline'
        with self.assertRaises(ValueError):
            md.patch_from_baseline(empty, 'lut')


class TestWrite(Base):
    def setUp(self):
        super().setUp()
        md.backup(FakeCamera(self.factory), IDENTITY, self.root)
        md.patch_from_baseline(self.root, 'lut')

    def test_write_sends_the_patched_image(self):
        cam = FakeCamera(self.factory)
        result = md.write_candidate(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(bytes(cam.data), self.candidate)
        self.assertEqual(cam.writes, 1)

    def test_write_requires_a_patched_image(self):
        empty = Path(self._tmp.name) / 'no-pending'
        with self.assertRaises(ValueError):
            md.write_candidate(FakeCamera(self.factory), IDENTITY, empty)

    def test_already_at_target_writes_nothing(self):
        cam = FakeCamera(self.candidate)
        result = md.write_candidate(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'ALREADY_AT_TARGET_NO_WRITE')
        self.assertEqual(cam.writes, 0)

    def test_write_still_refuses_an_incomplete_live_read(self):
        cam = FakeCamera(self.factory)
        cam.truncate_read = True
        with self.assertRaises(ValueError):
            md.write_candidate(cam, IDENTITY, self.root)
        self.assertEqual(cam.writes, 0)


class TestRestore(Base):
    def test_restore_writes_the_baseline_back(self):
        cam = FakeCamera(self.factory)
        md.backup(cam, IDENTITY, self.root)
        md.patch_from_baseline(self.root, 'lut')
        md.write_candidate(cam, IDENTITY, self.root)
        result = md.restore(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(bytes(cam.data), self.factory)

    def test_restore_without_baseline_is_refused(self):
        cam = FakeCamera(self.factory)
        with self.assertRaises(ValueError):
            md.restore(cam, IDENTITY, self.root)
        self.assertEqual(cam.writes, 0)

    def test_corrupt_baseline_is_refused(self):
        cam = FakeCamera(self.factory)
        md.backup(cam, IDENTITY, self.root)
        (self.root / 'baseline' / 'preimage.bin').write_bytes(b'\x00' * SMALL)
        with self.assertRaises(ValueError):
            md.restore(cam, IDENTITY, self.root)


class TestShippedPatch(unittest.TestCase):
    """The packed patch itself: real file, real format, real size."""

    def test_the_bundled_patch_parses(self):
        runs = md.load_patch()
        self.assertEqual(len(runs), 66319)
        offsets = [offset for offset, _ in runs]
        self.assertEqual(offsets, sorted(offsets))
        self.assertTrue(all(len(data) for _, data in runs))

    def test_every_run_lands_inside_the_partition(self):
        for offset, data in md.load_patch():
            self.assertLessEqual(offset + len(data), md.PARTITION_BYTES)


if __name__ == '__main__':
    unittest.main()
