import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from a9tool import file_deploy, release_assets, r15_files, usbdev, v8_deploy
from tests.deployment_fakes import FramedCameraDriver, WireCamera, WireTransport, IDENTITY


class V8Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {row['path']: release_assets.asset('r15/' + row['file'])
                      for row in release_assets.r15()['initial_files']}
        self.files[v8_deploy.PRELOAD] = b'# original\n/etc/unrelated.so\n'
        self.wire = WireTransport(self.files, r15_files.a9p.stock())
        self.closed = []
        self.identity = dict(IDENTITY)
        self.receipt = self.root / 'native-service-receipt.json'
        def connect(**kwargs):
            self.assertEqual(kwargs['receipt'], self.receipt)
            self.assertNotIn('fresh_identity', kwargs)
            self.assertNotIn('receipt_root', kwargs)
            self.camera = WireCamera(kwargs['guard_factory'](self.wire))
            return SimpleNamespace(camera=self.camera, identity=self.identity,
                                   close=lambda: self.closed.append(True))
        self.connect = mock.patch('a9tool.usbdev.connect', autospec=True, side_effect=connect)
        self.connect.start()
        self.addCleanup(self.connect.stop)
        receipt = mock.patch('a9tool.usbdev.load_current_receipt', autospec=True, return_value=self.receipt)
        receipt.start()
        self.addCleanup(receipt.stop)

    def action(self, action='v8.install', **extra):
        return v8_deploy.execute(action, dict(session_root=str(self.root), **extra))

    def test_status_names_inactive_complete_files_and_partial_active_installation(self):
        module, payloads = v8_deploy.load_release()
        self.files.update(dict(zip(module.TARGETS, payloads.values(), strict=True)))
        result = self.action('v8.status')
        self.assertEqual(result['menu']['payload_state'], 'complete')
        self.assertEqual(result['menu']['preload_state'], 'inactive')
        self.assertEqual(result['menu']['payloads_present'], 3)
        self.files[module.PRELOAD] = module.HOOK.encode()+b'\n'
        self.files.pop(module.TARGETS[2])
        result = self.action('v8.status')
        self.assertEqual(result['menu']['payload_state'], 'partial')
        self.assertEqual(result['menu']['preload_state'], 'v8')
        self.assertEqual(result['menu']['payloads_present'], 2)
        self.assertEqual(self.wire.writes, [])

    def test_external_package_is_validated_instead_of_ignored(self):
        (self.root/'manifest.json').write_bytes(b'wrong package')
        with self.assertRaisesRegex(ValueError, 'pinned release'):
            self.action('v8.install', package=str(self.root))
        self.assertEqual(self.closed, [])
        self.assertEqual(self.wire.writes, [])

    def test_real_camera_streams_large_r15_dependencies_through_native_reply_limits(self):
        from pmca.usb import sony
        paths = ('/usr/lib/viewUnified2.so', '/usr/lib/CautionConfig.so')
        for path in paths:
            self.assertGreater(len(self.files[path]), usbdev.MAX_SERVICE_REPLY)
            self.assertLess(len(self.files[path]), file_deploy.MAX_FILE)
        for unpadded in (False, True):
            with self.subTest(unpadded=unpadded), mock.patch.object(usbdev, 'UNPADDED', unpadded):
                driver = FramedCameraDriver(self.files, self.wire.tables, padded=not unpadded)
                transport = usbdev._make_senser(sony, driver, response_timeout=15)
                guard = v8_deploy.PrerequisiteGuard(transport)
                camera = sony.SonySenserCamera(guard)
                files = file_deploy.CameraFiles(camera)
                for path in paths:
                    self.assertEqual(files.read(path), self.files[path])
                self.assertEqual(driver.overreads, 0)
                self.assertEqual(driver.wire.writes, [])
                self.assertEqual(len(driver.requests), 1+2*len(paths))

    def test_real_native_transport_retains_unstreamed_two_mib_limit(self):
        from pmca.usb import sony
        path = '/usr/lib/CautionConfig.so'
        driver = FramedCameraDriver(self.files, self.wire.tables)
        transport = usbdev._make_senser(sony, driver, response_timeout=15)
        camera = sony.SonySenserCamera(v8_deploy.PrerequisiteGuard(transport))
        with self.assertRaisesRegex(ValueError, 'framing or size'):
            camera.readFile(path)
        self.assertEqual(driver.wire.writes, [])

    def test_pinned_package_matches_formal_v8(self):
        module, payloads = v8_deploy.load_release()
        self.assertEqual(release_assets.sha(payloads[module.NAMES[0]]),
                         'a98281a5886319f1cf04848fecbc21ba79cb08d2b3bdc06deb05755e7b48d926')
        self.assertEqual(release_assets.sha(payloads[module.NAMES[2]]),
                         '563d9c072ef85e0bf7020446a04eec7e8da8822f904a7c48707260f924ead8b2')
        with mock.patch('a9tool.usbdev.connect', side_effect=AssertionError('offline')):
            self.assertTrue(self.action('v8.check')['installation_enabled'])

    def test_install_then_original_preload_rollback(self):
        original = self.files[v8_deploy.PRELOAD]
        sent = self.wire._send
        initializations = []
        def count(function, data):
            if function == 0x40 and data[:4] == struct.pack('<HH', 0x1001, 0x4002):
                initializations.append(data)
            return sent(function, data)
        self.wire._send = count
        result = self.action()
        self.assertTrue(result['r15nh_current'])
        self.assertTrue(result['requires_cold_restart'])
        self.assertFalse(result['activation_verified'])
        self.assertEqual(len(initializations), 1)
        self.assertEqual(self.wire.writes[-1], v8_deploy.PRELOAD)
        self.assertEqual(self.files[v8_deploy.PRELOAD], original + v8_deploy.TARGETS[0].encode() + b'\n')
        # Recovery remains available even after the R15 prerequisite is absent.
        self.files['/usr/lib/a9fl.so'] = b'not R15'
        rollback = self.action('v8.rollback', source=result['session'])
        self.assertEqual(self.files[v8_deploy.PRELOAD], original)
        self.assertTrue(rollback['requires_cold_restart'])
        self.assertTrue(all(path in self.files for path in v8_deploy.TARGETS))
        self.assertEqual(len(self.closed), 2)

    def test_non_r15_and_mixed_files_never_write(self):
        for path in file_deploy.R15_PATHS:
            with self.subTest(path=path):
                original = self.files[path]
                self.files[path] = b'unknown version'
                with self.assertRaisesRegex(ValueError, 'requires.*R15'):
                    self.action()
                self.assertEqual(self.wire.writes, [])
                self.files[path] = original

    def test_bad_configs_or_live_lut_never_write(self):
        self.files[file_deploy.CONFIG_PATHS[0]] = b'bad record'
        with self.assertRaisesRegex(ValueError, 'requires.*R15'):
            self.action()
        self.files.pop(file_deploy.CONFIG_PATHS[0])
        self.wire.tables = (bytes(1280), bytes(1280))
        with self.assertRaisesRegex(ValueError, 'requires.*R15'):
            self.action()
        self.assertEqual(self.wire.writes, [])

    def test_racing_prerequisite_is_rejected(self):
        sent = self.wire._send
        reads = []
        def race(function, data):
            result = sent(function, data)
            if function == 0xff01 and b'/usr/lib/a9fl.so\0' in data:
                reads.append(data)
                if len(reads) == 1:
                    self.files['/usr/lib/a9fl.so'] = b'changed owner'
            return result
        self.wire._send = race
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.action()
        self.assertEqual(self.wire.writes, [])

    def test_menu_change_between_audit_and_final_snapshot_never_writes(self):
        original = v8_deploy._capture
        def changed(camera):
            result = original(camera)
            self.files[v8_deploy.PRELOAD] = b'/etc/unknown-a9.so\n'
            return result
        with mock.patch.object(v8_deploy, '_capture', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'changed after'):
                self.action()
        self.assertEqual(self.wire.writes, [])

    def test_prerequisite_evidence_is_durable_before_first_write(self):
        sent = self.wire._send
        evidence = []
        def check(function, data):
            if function == 0xff01 and int.from_bytes(data[:2], 'little') == 1:
                folders = list(self.root.glob('v8-install-*'))
                self.assertEqual(len(folders), 1)
                self.assertTrue((folders[0]/'prerequisite.json').is_file())
                self.assertTrue((folders[0]/'snapshot.json').is_file())
                self.assertTrue((folders[0]/'intent.json').is_file())
                evidence.append(True)
            return sent(function, data)
        self.wire._send = check
        self.action()
        self.assertTrue(evidence)

    def test_rollback_rejects_other_body_before_reads_or_writes(self):
        result = self.action()
        count = len(self.wire.writes)
        self.identity['serial_sha256'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.action('v8.rollback', source=result['session'])
        self.assertEqual(len(self.wire.writes), count)

    def test_rollback_rejects_corrupt_local_backup_without_connection(self):
        result = self.action()
        backup = Path(result['session']) / 'preimage-4.bin'
        backup.write_bytes(b'corrupt')
        with mock.patch('a9tool.usbdev.connect', side_effect=AssertionError('local check')):
            with self.assertRaisesRegex(ValueError, 'checksum'):
                self.action('v8.rollback', source=result['session'])

    def test_timeout_not_retried_and_actual_install_backup_remains_usable(self):
        sent = self.wire._send
        def lose_response(function, data):
            response = sent(function, data)
            if self.wire.writes:
                raise TimeoutError('unknown completion')
            return response
        self.wire._send = lose_response
        with self.assertRaises(TimeoutError) as caught:
            self.action()
        self.assertEqual(len(self.wire.writes), 1)
        module, _ = v8_deploy.load_release()
        module.rollback_material(caught.exception.session, IDENTITY)
        self.assertEqual(self.files[v8_deploy.PRELOAD], b'# original\n/etc/unrelated.so\n')

    def test_logging_failure_does_not_mask_unknown_write(self):
        sent = self.wire._send
        unknown = TimeoutError('original unknown completion')
        def lose_response(function, data):
            response = sent(function, data)
            if self.wire.writes:
                raise unknown
            return response
        self.wire._send = lose_response
        durable = file_deploy.durable
        def disk_full(path, raw):
            if Path(path).name in ('failure.json', 'protocol.json'):
                raise OSError('disk full')
            return durable(path, raw)
        with mock.patch.object(file_deploy, 'durable', side_effect=disk_full):
            with self.assertRaises(TimeoutError) as caught:
                self.action()
        self.assertIs(caught.exception, unknown)
        self.assertEqual(len(unknown.__notes__), 2)
        self.assertEqual(len(self.wire.writes), 1)

    def test_changed_preload_requires_explicit_recover(self):
        original = self.files[v8_deploy.PRELOAD]
        result = self.action()
        self.files[v8_deploy.PRELOAD] = b'truncated'
        with self.assertRaisesRegex(ValueError, 'Current preload'):
            self.action('v8.rollback', source=result['session'])
        self.assertEqual(self.files[v8_deploy.PRELOAD], b'truncated')
        self.action('v8.rollback', source=result['session'], recover=True)
        self.assertEqual(self.files[v8_deploy.PRELOAD], original)

    def test_reinstall_reports_original_install_session_needed(self):
        first = self.action()
        writes = len(self.wire.writes)
        second = self.action()
        self.assertFalse(second['preload_changed'])
        self.assertTrue(second['deactivation_requires_original_session'])
        self.assertEqual(len(self.wire.writes), writes)
        self.action('v8.rollback', source=second['session'])
        self.assertIn(v8_deploy.TARGETS[0].encode(), self.files[v8_deploy.PRELOAD])
        self.action('v8.rollback', source=first['session'])
        self.assertNotIn(v8_deploy.TARGETS[0].encode(), self.files[v8_deploy.PRELOAD])

    def test_active_v71_requires_all_three_released_hashes(self):
        self.files[v8_deploy.PRELOAD] = v8_deploy.V71_PATHS[0].encode() + b'\n'
        for path in v8_deploy.V71_PATHS:
            self.files[path] = b'unknown v71 bytes'
        with self.assertRaisesRegex(ValueError, 'V7.1 payload'):
            self.action()
        self.assertEqual(self.wire.writes, [])
        index = v8_deploy.fingerprints.index()
        rows = [dict(row) for row in index['menus']]
        next(row for row in rows if row['label'] == 'V7.1')['files'] = {
            path: release_assets.sha(self.files[path]) for path in v8_deploy.V71_PATHS}
        with mock.patch.object(v8_deploy.fingerprints, 'index', return_value=dict(index, menus=rows)):
            result = self.action()
        self.assertTrue(result['preload_changed'])
        self.assertEqual(self.files[v8_deploy.PRELOAD], v8_deploy.TARGETS[0].encode() + b'\n')
        self.assertTrue(all(self.files[path] == b'unknown v71 bytes' for path in v8_deploy.V71_PATHS))

    def test_old_or_duplicate_unknown_owner_never_writes(self):
        for preload in (b'/etc/a9-autoexec-v7.so\n', b'/etc/unknown-a9.so\n',
                        b'/etc/a9-autoexec-v71mt.so\n/etc/a9-autoexec-v71mt.so\n'):
            with self.subTest(preload=preload):
                self.files[v8_deploy.PRELOAD] = preload
                with self.assertRaises(ValueError):
                    self.action()
                self.assertEqual(self.wire.writes, [])

    def test_readonly_guard_denies_terminal_partition_and_all_writes(self):
        guard = v8_deploy.PrerequisiteGuard(self.wire)
        for function, data in ((0xff01, WireCamera.packet(1, v8_deploy.PRELOAD, b'danger')),
                               (0xff01, WireCamera.packet(2, '/dev/nflasha15')),
                               (0x40, struct.pack('<HHI', 0x603, 2, 0x30004) + bytes(1280)),
                               (0x1234, b'')):
            with self.assertRaises(ValueError):
                guard.sendSenserPacket(function, data)
        self.assertEqual(self.wire.writes, [])

    def test_nonboolean_recover_is_rejected_offline(self):
        with mock.patch('a9tool.usbdev.connect', side_effect=AssertionError('invalid')):
            with self.assertRaisesRegex(ValueError, 'boolean'):
                self.action('v8.rollback', source=str(self.root), recover='true')
