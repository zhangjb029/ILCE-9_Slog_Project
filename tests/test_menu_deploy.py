import hashlib
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import menu_deploy as md

SMALL = 8192
IDENTITY = {'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a' * 64}


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
        self.root = Path(self._tmp.name) / 'sessions'

        self.factory = fake_partition(0x11)
        candidate = bytearray(self.factory)
        candidate[2000:2002] = b'\xaa\xbb'
        candidate[5000] = 0x5a
        self.candidate = bytes(candidate)
        self.patches = (
            (2000, self.factory[2000:2002].hex(), 'aabb'),
            (5000, self.factory[5000:5001].hex(), '5a'),
        )
        fl = bytearray(candidate)
        fl[3000] = 0xcc
        self.fl_candidate = bytes(fl)
        self.fl_patch = ((3000, b'\xcc'),)
        menu_sha = hashlib.sha256(self.candidate).hexdigest()
        fl_sha = hashlib.sha256(self.fl_candidate).hexdigest()

        for patcher in (
            mock.patch.object(md, 'PARTITION_BYTES', SMALL),
            mock.patch.object(md, 'FACTORY_SHA', hashlib.sha256(self.factory).hexdigest()),
            mock.patch.object(md, 'CANDIDATE_SHA', menu_sha),
            mock.patch.object(md, 'MENU_SHA', menu_sha),
            mock.patch.object(md, 'FL_SHA', fl_sha),
            mock.patch.object(md, 'TARGETS', {'menu': (menu_sha, '菜单'), 'fl': (fl_sha, 'FL')}),
            mock.patch.object(md, 'PATCHES', self.patches),
            mock.patch.object(md, 'load_fl_patch', new=lambda: self.fl_patch),
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

    def test_unknown_partition_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            md.build_candidate(fake_partition(0x33))
        self.assertIn('原厂', str(ctx.exception))

    def test_patch_that_does_not_match_its_bytes_is_refused(self):
        with mock.patch.object(md, 'PATCHES', ((2000, 'dead', 'beef'),)):
            with self.assertRaises(ValueError):
                md.build_candidate(self.factory)

    def test_sanity_rejects_non_ext2(self):
        with self.assertRaises(ValueError):
            md.sanity(bytes(SMALL))


class TestFlTarget(Base):
    def test_factory_can_go_straight_to_fl(self):
        self.assertEqual(md.build_candidate(self.factory, 'fl'), self.fl_candidate)

    def test_menu_can_be_upgraded_to_fl(self):
        self.assertEqual(md.build_candidate(self.candidate, 'fl'), self.fl_candidate)

    def test_menu_target_leaves_fl_out(self):
        self.assertEqual(md.build_candidate(self.factory, 'menu'), self.candidate)

    def test_unknown_target_is_refused(self):
        with self.assertRaises(ValueError):
            md.build_candidate(self.factory, 'nonsense')

    def test_unknown_partition_is_refused_for_fl_too(self):
        with self.assertRaises(ValueError):
            md.build_candidate(fake_partition(0x33), 'fl')


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


class TestPatch(Base):
    def setUp(self):
        super().setUp()
        md.backup(FakeCamera(self.factory), IDENTITY, self.root)

    def test_patch_menu_from_baseline(self):
        meta = md.patch_from_baseline(self.root, 'menu')
        self.assertEqual(meta['sha256'], md.TARGETS['menu'][0])
        self.assertEqual((md.pending_dir(self.root) / 'candidate.bin').read_bytes(), self.candidate)

    def test_patch_fl_from_baseline(self):
        meta = md.patch_from_baseline(self.root, 'fl')
        self.assertEqual(meta['sha256'], md.TARGETS['fl'][0])
        self.assertEqual((md.pending_dir(self.root) / 'candidate.bin').read_bytes(), self.fl_candidate)

    def test_patch_requires_a_baseline(self):
        empty = Path(self._tmp.name) / 'no-baseline'
        with self.assertRaises(ValueError):
            md.patch_from_baseline(empty, 'menu')


class TestWrite(Base):
    def setUp(self):
        super().setUp()
        md.backup(FakeCamera(self.factory), IDENTITY, self.root)
        md.patch_from_baseline(self.root, 'menu')

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
        md.patch_from_baseline(self.root, 'fl')
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


if __name__ == '__main__':
    unittest.main()
