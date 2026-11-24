import hashlib
import unittest
from unittest.mock import patch
from a9tool import state_fingerprints as sf


class FingerprintsTests(unittest.TestCase):
    def test_index_covers_every_requested_major_and_intermediate_version(self):
        index = sf.index()
        labels = {r['label'] for r in index['r15']}
        self.assertTrue({'stock','R8','R9','R9.1','R10','R11','R12','R13','R14','R14 FIX1','R15','R15 NAME HELP'} <= labels)
        self.assertTrue({'V3','V3.1','V4','V5','V5.1','V5.2','V5.3','V5.4','V5.5','V6','V6.1','V6.1.1','V7'} <=
                        {label for r in index['menus'] for label in [r['label'],*r.get('aliases',[])]})

    def test_missing_read_is_not_absence(self):
        result = sf.classify_r15({})
        self.assertEqual(result['state'], 'unknown')
        self.assertFalse(result['upgrade_enabled'])

    def test_real_current_prefix_allows_user_object_changes_but_not_code(self):
        from a9tool import release_assets as ra
        manifest = ra.r15()
        files = {row['path']: ra.asset('r15/'+row['file']) for row in manifest['initial_files']}
        changed = bytearray(files['/usr/lib/a9fl.so']); changed[-1] = 17
        files['/usr/lib/a9fl.so'] = bytes(changed)
        result = sf.classify_r15(files)
        self.assertEqual(result['label'], 'R15 NAME HELP')
        self.assertEqual(result['state'], 'current')
        self.assertFalse(result['upgrade_enabled'])
        changed[100] ^= 1; files['/usr/lib/a9fl.so'] = bytes(changed)
        self.assertNotEqual(sf.classify_r15(files)['state'], 'current')

    def test_stock_and_mixed_lut_are_distinct(self):
        raw = {path: b'file'+bytes([i]) for i,path in enumerate(sf.R15_PATHS)}
        row = dict(label='stock', files={p:hashlib.sha256(v).hexdigest() for p,v in raw.items()}, object_layout=None,source='fake')
        with patch.object(sf, 'index', return_value={'r15':[row],'menus':[]}):
            self.assertEqual(sf.classify_r15(raw)['state'], 'stock')
            raw[sf.R15_PATHS[0]] = None
            self.assertEqual(sf.classify_r15(raw)['state'], 'partial')

    def test_menu_hook_and_complete_inventory_required(self):
        hook='/etc/a9-autoexec-v7.so'
        row = dict(label='V7', files={hook:hashlib.sha256(b'hook').hexdigest()}, hook=hook,source='fake')
        raw = dict.fromkeys(sf.MENU_PATHS)
        raw[hook] = b'hook'; raw['/etc/ld.so.preload'] = (hook+'\n').encode()
        with patch.object(sf, 'index', return_value={'r15':[],'menus':[row]}):
            self.assertEqual(sf.classify_v7(raw)['state'], 'current')
            raw['/etc/ld.so.preload'] = b'/etc/a9-unknown.so\n'
            self.assertEqual(sf.classify_v7(raw)['state'], 'conflict')
            del raw[sf.MENU_PATHS[0]]
            self.assertEqual(sf.classify_v7(raw)['state'], 'unknown')

    def test_menu_stock_requires_all_probed_files_absent(self):
        raw = dict.fromkeys(sf.MENU_PATHS)
        self.assertEqual(sf.classify_v7(raw)['state'], 'stock')
        raw['/etc/ld.so.preload'] = b'/other-owner.so\n'
        self.assertEqual(sf.classify_v7(raw)['state'], 'stock')

    def test_every_menu_profile_with_real_hook_and_external_preload_can_match(self):
        for original in sf.index()['menus']:
            with self.subTest(label=original['label']):
                row=dict(original);row['files']={p:hashlib.sha256(p.encode()).hexdigest() for p in original['files']}
                raw=dict.fromkeys(sf.MENU_PATHS)
                raw.update({p:p.encode() for p in row['files']})
                if row['label'] in ('V3','V3.1'):
                    raw['/etc/A9BOOT/A9BOOT.SO']=raw['/tmp/A9BOOT/A9BOOT.SO']
                raw['/etc/ld.so.preload']=('/lib/unrelated.so # preserved\n'+row['hook']+'\n').encode()
                with patch.object(sf,'index',return_value={'r15':[],'menus':[row]}):
                    result=sf.classify_v7(raw)
                self.assertIn(result['state'],('current','legacy'))
                self.assertEqual(result['label'],row['label'])

    def test_config_schema_1_4_5_6_7_8_9_are_decoded_strictly(self):
        import struct,zlib
        from a9tool import r15_files,release_a9p
        for schema in (1,4,5,6,7,8,9):
            n=2048 if schema>=8 else 512 if schema>=5 else 128
            count={1:1,4:3,5:20,6:23,7:27,8:43,9:43}[schema]
            raw=bytearray(n);raw[:8]=b'A9FLP001'
            struct.pack_into('<4I',raw,8,n,1,schema,0)
            raw[56:88]=release_a9p.SHA;raw[88:112]=release_a9p.BUILD
            if schema==1:
                struct.pack_into('<8i',raw,24,0,0,0,0,0,0,1,0)
            else:
                width=15 if schema<6 else 16;begin=24 if schema==4 else 128
                packed=sum(1<<(5*(bank*width+6)) for bank in range(count))
                raw[begin:begin+(count*width*5+7)//8]=packed.to_bytes((count*width*5+7)//8,'little')
            struct.pack_into('<I',raw,n-4,zlib.crc32(raw[:-4]))
            with self.subTest(schema=schema):
                self.assertEqual(r15_files.decode_record('A9FL0.CFG',bytes(raw))['schema'],schema)
                raw[-1]^=1
                with self.assertRaises(ValueError):
                    r15_files.decode_record('A9FL0.CFG',bytes(raw))

    def test_real_released_r14_r15_and_name_help_preserve_mutable_identity(self):
        from a9tool import release_assets as ra
        manifest=ra.r15()
        for profile,label in [('R14-SD','R14 FIX1'),('R15-ORIGINAL','R15'),('R15-SD','R15 NAME HELP')]:
            with self.subTest(profile=profile):
                row=next(r for r in manifest['sources'] if r['profile']==profile)
                files={r['path']:ra.asset('r15/'+r['file']) for r in manifest['initial_files']}
                module=bytearray(ra.asset('r15/'+row['fixture']))
                module[-80] ^= 31
                files['/usr/lib/a9fl.so']=bytes(module)
                result=sf.classify_r15(files)
                self.assertEqual(result['label'],label)
                self.assertFalse(result['state_validated'])
                self.assertTrue(result['preparation_supported'])

    def test_r9_known_identity_does_not_claim_r8_config_compatibility(self):
        import struct,zlib
        from a9tool import release_a9p
        raw=bytearray(128); raw[:8]=b'A9FLP001'
        struct.pack_into('<4I',raw,8,128,1,1,0)
        struct.pack_into('<8i',raw,24,0,0,0,0,0,0,1,0)
        raw[56:88]=release_a9p.SHA;raw[88:112]=release_a9p.BUILD
        struct.pack_into('<I',raw,124,zlib.crc32(raw[:124]))
        files={p:b'fixture'+bytes([i]) for i,p in enumerate(sf.R15_PATHS)}
        row=dict(label='R9',files={p:hashlib.sha256(v).hexdigest() for p,v in files.items()},
                 config_schema=4,source='fake',object_layout=None)
        with patch.object(sf,'index',return_value={'r15':[row],'menus':[]}):
            result=sf.classify_r15(files,[bytes(raw),None,None,None])
            upgrade=sf.classify_r15(files,[bytes(raw),None,None,None],partition_upgrade=True)
        self.assertEqual(result['state'],'conflict')
        self.assertIn('R9',result['reason'])
        self.assertEqual(upgrade['state'],'legacy')
        self.assertTrue(upgrade['config_records_validated'])
