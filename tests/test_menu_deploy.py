import hashlib
import io
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
        self.fail_write = False
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
        if self.fail_write:
            raise IOError('simulated write failure')
        self.data = bytearray(data)
        return 0


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / 'sessions'
        self.image_bytes = fake_partition(0x22)
        self.image_path = Path(self._tmp.name) / 'candidate.bin'
        self.image_path.write_bytes(self.image_bytes)
        self.sha = hashlib.sha256(self.image_bytes).hexdigest()
        for patcher in (
            mock.patch.object(md, 'PARTITION_BYTES', SMALL),
            mock.patch.dict(md.KNOWN_IMAGES, {self.sha: 'menu_inplace'}, clear=True),
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
        payload = struct.pack('<hh', md.FILE_WRITE, len(md.PARTITION)) + md.PARTITION.encode() + bytes(SMALL)
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


class TestImageInspection(Base):
    def test_known_image_is_identified(self):
        info = md.inspect_image(self.image_path)
        self.assertEqual(info['kind'], 'menu_inplace')
        self.assertEqual(info['sha256'], self.sha)

    def test_unknown_hash_is_refused(self):
        other = fake_partition(0x33)
        path = Path(self._tmp.name) / 'other.bin'
        path.write_bytes(other)
        with self.assertRaises(ValueError):
            md.inspect_image(path)

    def test_wrong_size_is_refused(self):
        path = Path(self._tmp.name) / 'short.bin'
        path.write_bytes(b'\x00' * 100)
        with self.assertRaises(ValueError):
            md.inspect_image(path)

    def test_sanity_rejects_non_ext2(self):
        with self.assertRaises(ValueError):
            md.sanity(bytes(SMALL))


class TestDeploy(Base):
    def test_deploy_backs_up_then_writes(self):
        original = fake_partition(0x11)
        cam = FakeCamera(original)
        result = md.deploy(cam, IDENTITY, self.image_path, self.root)
        self.assertEqual(result['state'], 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(cam.writes, 1)
        self.assertEqual((result['directory'] / 'preimage.bin').read_bytes(), original)
        self.assertEqual(bytes(cam.data), self.image_bytes)

    def test_baseline_is_the_first_preimage(self):
        cam = FakeCamera(fake_partition(0x11))
        md.deploy(cam, IDENTITY, self.image_path, self.root)
        info = md.baseline_info(self.root)
        self.assertEqual(info['bytes'], SMALL)
        self.assertEqual((self.root / 'baseline' / 'preimage.bin').read_bytes(), fake_partition(0x11))

    def test_incomplete_backup_blocks_the_write(self):
        cam = FakeCamera(fake_partition(0x11))
        cam.truncate_read = True
        with self.assertRaises(ValueError):
            md.deploy(cam, IDENTITY, self.image_path, self.root)
        self.assertEqual(cam.writes, 0)

    def test_already_at_target_writes_nothing(self):
        cam = FakeCamera(self.image_bytes)
        result = md.deploy(cam, IDENTITY, self.image_path, self.root)
        self.assertEqual(result['state'], 'ALREADY_AT_TARGET_NO_WRITE')
        self.assertEqual(cam.writes, 0)


class TestRestore(Base):
    def test_restore_writes_the_baseline_back(self):
        original = fake_partition(0x11)
        cam = FakeCamera(original)
        md.deploy(cam, IDENTITY, self.image_path, self.root)
        result = md.restore(cam, IDENTITY, self.root)
        self.assertEqual(result['state'], 'SAVED_AND_READBACK_VERIFIED')
        self.assertEqual(bytes(cam.data), original)

    def test_restore_without_baseline_is_refused(self):
        cam = FakeCamera(fake_partition(0x11))
        with self.assertRaises(ValueError):
            md.restore(cam, IDENTITY, self.root)
        self.assertEqual(cam.writes, 0)

    def test_corrupt_baseline_is_refused(self):
        cam = FakeCamera(fake_partition(0x11))
        md.deploy(cam, IDENTITY, self.image_path, self.root)
        baseline = self.root / 'baseline' / 'preimage.bin'
        baseline.write_bytes(b'\x00' * SMALL)
        with self.assertRaises(ValueError):
            md.restore(cam, IDENTITY, self.root)


if __name__ == '__main__':
    unittest.main()
