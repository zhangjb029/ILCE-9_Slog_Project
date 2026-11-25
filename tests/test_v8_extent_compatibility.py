"""Pinned historical ELF-header compatibility, with all other gates retained."""
import json
from pathlib import Path
import struct
import unittest
from unittest import mock

from a9tool import deployment_status, file_deploy, release_assets, usbdev, v8_deploy
from tests import test_v8_deploy as fixtures
from tests.deployment_fakes import FramedCameraDriver


class V8ExtentCompatibilityTests(unittest.TestCase):
    setUp=fixtures.V8Tests.setUp
    action=fixtures.V8Tests.action

    def variant(self):
        path='/usr/lib/viewUnified2.so'
        raw=bytearray(self.files[path])
        struct.pack_into('<II',raw,0x64,0x8c7dfc,0x8c7dfc)
        self.files[path]=bytes(raw)
        self.assertEqual(release_assets.sha(self.files[path]),
            '07ffd8df517022d9e661240082170ea013023fdeb76156b5510c702bc19fed9e')

    def test_status_recognizes_exact_variant_and_names_it_without_writes(self):
        self.variant()
        result=self.action('v8.status')
        self.assertTrue(result['r15nh_current'])
        self.assertEqual(result['r15']['view_library_match'],'known-extent-variant')
        self.assertIn('已知段长度变体',deployment_status.v8_text(result))
        self.assertEqual(self.wire.writes,[])

    def test_variant_install_and_rollback_preserve_real_source_evidence(self):
        self.variant();original=self.files[v8_deploy.PRELOAD]
        result=self.action()
        self.assertTrue(result['r15nh_current'])
        self.assertEqual(self.wire.writes[-1],v8_deploy.PRELOAD)
        evidence=json.loads((Path(result['session'])/'prerequisite.json').read_text('utf-8'))
        self.assertEqual(evidence['r15']['view_library_match'],'known-extent-variant')
        self.assertEqual(evidence['files']['/usr/lib/viewUnified2.so'],
            '07ffd8df517022d9e661240082170ea013023fdeb76156b5510c702bc19fed9e')
        self.action('v8.rollback',source=result['session'])
        self.assertEqual(self.files[v8_deploy.PRELOAD],original)

    def test_nearby_variants_and_extra_changes_stay_blocked(self):
        self.variant();path='/usr/lib/viewUnified2.so';valid=self.files[path]
        for offset in (0x64,0x68,0x100,0x8c7dfc,len(valid)-1):
            with self.subTest(offset=offset):
                raw=bytearray(valid);raw[offset]^=1;self.files[path]=bytes(raw)
                with self.assertRaisesRegex(ValueError,'requires.*R15'):
                    self.action()
                self.assertEqual(self.wire.writes,[])

    def test_other_files_and_legacy_module_stay_blocked(self):
        self.variant()
        for path in file_deploy.R15_PATHS:
            if path=='/usr/lib/viewUnified2.so':continue
            with self.subTest(path=path):
                before=self.files[path];self.files[path]=b'unknown'
                with self.assertRaisesRegex(ValueError,'requires.*R15'):self.action()
                self.files[path]=before
        self.files['/usr/lib/a9fl.so']=release_assets.asset('r15/R15-ORIGINAL.so')
        with self.assertRaisesRegex(ValueError,'requires.*R15'):self.action()
        self.assertEqual(self.wire.writes,[])

    def test_config_and_lut_guards_remain_required_for_the_variant(self):
        self.variant()
        self.files[file_deploy.CONFIG_PATHS[0]]=b'bad config'
        with self.assertRaisesRegex(ValueError,'requires.*R15'):self.action()
        self.files.pop(file_deploy.CONFIG_PATHS[0])
        self.wire.tables=(bytes(1280),bytes(1280))
        with self.assertRaisesRegex(ValueError,'requires.*R15'):self.action()
        self.assertEqual(self.wire.writes,[])

    def test_canonical_menu_remains_identified(self):
        result=self.action('v8.status')
        self.assertTrue(result['r15nh_current'])
        self.assertEqual(result['r15']['view_library_match'],'canonical')

    def test_complete_native_framing_recognizes_the_variant(self):
        from pmca.usb import sony
        self.variant()
        for unpadded in (False,True):
            with self.subTest(unpadded=unpadded),mock.patch.object(usbdev,'UNPADDED',unpadded):
                driver=FramedCameraDriver(self.files,self.wire.tables,padded=not unpadded)
                camera=sony.SonySenserCamera(v8_deploy.PrerequisiteGuard(
                    usbdev._make_senser(sony,driver,response_timeout=15)))
                _,_,r15,_=v8_deploy._capture(camera)
                self.assertTrue(r15['state_validated'])
                self.assertEqual(r15['view_library_match'],'known-extent-variant')
                self.assertEqual(driver.wire.writes,[])
                self.assertEqual(driver.overreads,0)
