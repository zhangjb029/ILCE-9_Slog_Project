"""Real archived source bytes, simulated camera boundary, no USB access."""
import hashlib
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from a9tool import r15nh_deploy as deploy, release_a9p


class R12WorkflowTests(unittest.TestCase):
    def test_read_identify_patch_write_and_paired_rollback(self):
        source = os.environ.get('R15NH_TEST_SOURCE_PATH')
        if not source:
            self.skipTest('Set R15NH_TEST_SOURCE_PATH to the archived R12 partition; no image is bundled')
        original = bytearray(Path(source).read_bytes())
        self.assertEqual(len(original), deploy.PARTITION_BYTES)
        original[1068] ^= 1  # explicitly accepted ext2 lifecycle metadata
        original = bytes(original)
        rt = deploy.runtime()
        identity = dict(model='ILCE-9', firmware='6.00', serial_sha256='a'*64)
        class Transport:
            image = original
            writes = []
            saves = []
            tables = dict(zip(rt.guarded_config.LUT_IDS, release_a9p.stock()))
            def sendSenserPacket(self, function, packet, oData=None):
                if function == 0xff01:
                    command, n = struct.unpack_from('<hh', packet)
                    path = packet[4:4+n].rstrip(b'\0').decode()
                    if path != deploy.PARTITION:
                        raise AssertionError('Unexpected file mutation: '+path)
                    if command == 2:
                        oData.write(self.image)
                    elif command == 1:
                        self.writes.append(path)
                        self.image = packet[4+n:]
                    else:
                        raise AssertionError('Unexpected FF01 command')
                    return 0, b''
                block, code = struct.unpack_from('<HH', packet)
                if block == 0x1001:
                    return (0, bytes(4)) if code == 0x4002 else (0, struct.pack('<I', rt.guarded_config.MISSING))
                if block == 0x603 and code == 1:
                    return 0, self.tables[struct.unpack_from('<I', packet, 4)[0]]
                if block == 0x603 and code == 3:
                    self.saves.append(packet[4:])
                    return 0, b''
                raise AssertionError('Unexpected service packet')
        wire = Transport()
        class Camera:
            def readBackup(self, pid):
                return self.dev.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 1, pid))[1]
            def readFile(self, path, stream):
                return self.file(2, path, sink=stream)
            def writeFile(self, path, payload):
                return self.file(1, path, payload)
            def saveBackup(self, mode):
                return self.dev.sendSenserPacket(0x40, struct.pack('<HHH', 0x603, 3, mode))
            def file(self, command, path, payload=b'', sink=None):
                name = path.encode(); name += bytes(4-len(name)%4)
                return self.dev.sendSenserPacket(0xff01, struct.pack('<hh', command, len(name))+name+payload, sink)
        closed = []
        def connect(receipt=None, progress=None, *, guard_factory=None, response_timeout=None, identity_check=None):
            camera = Camera(); camera.dev = guard_factory(wire)
            return SimpleNamespace(camera=camera, identity=identity, close=lambda: closed.append(True))
        with tempfile.TemporaryDirectory() as folder, \
             mock.patch('a9tool.usbdev.load_current_receipt', return_value=None), \
             mock.patch('a9tool.usbdev.connect', autospec=True, side_effect=connect) as connection:
            backup = deploy.execute('r15.backup', dict(session_root=folder))
            session = backup['session']
            self.assertFalse(deploy.inspect_session(session)['identified'])
            identified = deploy.execute('r15.identify', dict(source=session))
            self.assertEqual(identified['source_label'], 'R12')
            deploy.execute('r15.patch', dict(source=session))
            self.assertEqual(connection.call_count, 1, 'identify and patch must stay offline')
            self.assertTrue(deploy.inspect_session(session)['patched'])
            candidate = Path(session)/'prepared-partition.bin'
            self.assertEqual(hashlib.sha256(candidate.read_bytes()).hexdigest(), deploy.TARGET_SHA)
            deployed = deploy.execute('r15.install', dict(session_root=folder, source=session))
            self.assertTrue(deployed['requires_cold_restart'])
            self.assertEqual(wire.writes, [deploy.PARTITION])
            self.assertEqual(hashlib.sha256(wire.image).hexdigest(), deploy.TARGET_SHA)
            deploy.execute('r15.rollback', dict(session_root=folder, source=session))
            self.assertEqual(wire.image, original)
            self.assertEqual(wire.writes, [deploy.PARTITION, deploy.PARTITION])
            self.assertEqual(wire.saves, [b'\0\0'])
            self.assertEqual(closed, [True, True, True])
