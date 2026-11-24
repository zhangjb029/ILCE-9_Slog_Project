import io
import json
import os
import struct
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


class R15NHTests(unittest.TestCase):
    def setUp(self):
        from a9tool import r15nh_deploy
        self.m = r15nh_deploy

    def _test_image(self):
        value=os.environ.get('R15NH_TEST_IMAGE_PATH')
        if not value:self.skipTest('R15NH_TEST_IMAGE_PATH is required for the external formal-image fixture')
        raw=Path(value).read_bytes()
        self.assertEqual(len(raw),self.m.PARTITION_BYTES)
        self.assertEqual(self.m._sha(raw),self.m.TARGET_SHA)
        return raw

    def test_guard_only_allows_one_complete_partition_write(self):
        transport = mock.Mock()
        guard = self.m.PartitionGuard(transport, allow_write=True)
        def packet(path, body=b'', command=1):
            raw = path.encode(); raw += bytes(4-len(raw)%4)
            return struct.pack('<hh', command, len(raw))+raw+body
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0xff01, packet('/usr/lib/a9fl.so', b'bad'))
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0xff01, packet(self.m.PARTITION, b'bad'))
        payload = bytes(self.m.PARTITION_BYTES)
        guard.sendSenserPacket(0xff01, packet(self.m.PARTITION, payload))
        with self.assertRaises(ValueError):
            guard.sendSenserPacket(0xff01, packet(self.m.PARTITION, payload))
        self.assertEqual(transport.sendSenserPacket.call_count, 1)

    def test_preload_active_v8_blocks_rollback_and_comments_do_not(self):
        for text, blocked in ((b'/etc/A9V71MT/V71MT.SO\n', True),
                              (b'# /etc/A9V71MT/V71MT.SO\n/other.so\n', False),
                              (None, False)):
            camera = mock.Mock()
            with mock.patch.object(self.m, '_read_preload', return_value=text):
                if blocked:
                    with self.assertRaisesRegex(ValueError, 'V8'):
                        self.m.check_v8_inactive(camera)
                else:
                    self.m.check_v8_inactive(camera)

    def test_rollback_requires_paired_identity_bound_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises((OSError, ValueError)):
                self.m.load_rollback(Path(tmp))

    def test_offline_check_never_connects(self):
        with mock.patch('a9tool.usbdev.connect') as connect:
            result = self.m.execute('r15.check', {})
        connect.assert_not_called()
        self.assertTrue(result['installation_enabled'])
        self.assertEqual(result['transport'], 'FF01_FULL_PARTITION')
        self.assertTrue({'stock','R8','R9','R9.1','R10','R11','R12','R15 NAME HELP'} <= set(result['supported_sources']))

    def test_real_target_accepts_only_named_metadata_differences(self):
        from a9tool import release_a9p
        m=self.m;raw=self._test_image();rt=m.runtime()
        configs={path:None for path in rt.guarded_config.PATHS}
        tables=dict(zip(rt.guarded_config.LUT_IDS,release_a9p.stock()))
        self.assertTrue(m.classify(raw,configs,tables)['r15nh_current'])
        changed=bytearray(raw);changed[1068]^=1
        self.assertTrue(m.classify(bytes(changed),configs,tables)['r15nh_current'])
        changed=bytearray(raw);changed[-1]^=1
        with self.assertRaisesRegex(ValueError,'outside'):
            m.classify(bytes(changed),configs,tables)

    def test_real_rollback_snapshot_and_wrong_body_rejected_before_write(self):
        from a9tool import release_a9p
        m=self.m;raw=self._test_image();rt=m.runtime()
        identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        class Device:
            def sendSenserPacket(self,function,packet,oData=None):
                block,code=struct.unpack_from('<HH',packet)
                return (0,bytes(4)) if code==0x4002 else (0,struct.pack('<I',rt.guarded_config.MISSING))
        class Camera:
            dev=Device()
            def readBackup(self,pid):return release_a9p.stock()[rt.guarded_config.LUT_IDS.index(pid)]
            def readFile(self,path,stream):stream.write(raw)
        camera=Camera()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);capture=root/'original';capture.mkdir()
            m._capture(camera,identity,capture)
            payload,configs,tables,owner=m.load_rollback(capture)
            self.assertEqual(payload,raw);self.assertEqual(owner,identity)
            handle=mock.Mock(camera=camera,identity=dict(identity,serial_sha256='b'*64))
            with mock.patch('a9tool.usbdev.connect',return_value=handle):
                with self.assertRaisesRegex(ValueError,'identity differs'):
                    m.execute('r15.rollback',dict(session_root=str(root),source=str(capture)))
            handle.close.assert_called_once()
            (capture/'partition/preimage.bin').write_bytes(b'damaged')
            with self.assertRaisesRegex(ValueError,'checksum'):
                m.load_rollback(capture)

    def test_r9_only_schema4_accepts_published_a7_tag(self):
        import zlib
        m=self.m;rt=m.runtime();manifest=m.package()
        raw=bytearray(128);raw[:8]=b'A7FLP001'
        struct.pack_into('<4I',raw,8,128,1,4,1)
        packed=sum(1<<((bank*15+6)*5) for bank in range(3))
        raw[24:53]=packed.to_bytes(29,'little')
        raw[56:88]=bytes.fromhex(manifest['pair_sha256'])
        raw[88:112]=manifest['build'].encode().ljust(24,b'\0')
        struct.pack_into('<I',raw,124,zlib.crc32(raw[:124]))
        configs={p:bytes(raw) if i==0 else None for i,p in enumerate(rt.guarded_config.PATHS)}
        rt.config_records.validate(configs,manifest)
        struct.pack_into('<I',raw,16,1);struct.pack_into('<I',raw,124,zlib.crc32(raw[:124]))
        configs[rt.guarded_config.PATHS[0]]=bytes(raw)
        with self.assertRaisesRegex(ValueError,'Foreign'):
            rt.config_records.validate(configs,manifest)

    def test_complete_install_uses_one_ff01_write_and_keeps_paired_rollback(self):
        from a9tool import release_a9p
        m=self.m;rt=m.runtime();target=self._test_image();original=bytearray(target);original[1068]^=1
        class Transport:
            def __init__(self):
                self.image=bytes(original);self.writes=[]
                self.tables=dict(zip(rt.guarded_config.LUT_IDS,release_a9p.stock()))
            def sendSenserPacket(self,function,packet,oData=None):
                if function==0xff01:
                    command,n=struct.unpack_from('<hh',packet);path=packet[4:4+n].rstrip(b'\0').decode()
                    self.assert_partition(path)
                    if command==2:oData.write(self.image)
                    elif command==1:self.writes.append(path);self.image=packet[4+n:]
                    return 0,b''
                block,code=struct.unpack_from('<HH',packet)
                if block==0x1001:
                    return (0,bytes(4)) if code==0x4002 else (0,struct.pack('<I',rt.guarded_config.MISSING))
                if block==0x603 and code==1:
                    return 0,self.tables[struct.unpack_from('<I',packet,4)[0]]
                raise AssertionError('Unexpected packet')
            def assert_partition(self,path):
                if path!=m.PARTITION:raise AssertionError('Unexpected file write')
        transport=Transport()
        guard=m.make_guard(transport,True)
        class Camera:
            dev=guard
            def readBackup(self,pid):return self.dev.sendSenserPacket(0x40,struct.pack('<HHI',0x603,1,pid))[1]
            def file(self,command,path,payload=b'',sink=None):
                name=path.encode();name+=bytes(4-len(name)%4)
                return self.dev.sendSenserPacket(0xff01,struct.pack('<hh',command,len(name))+name+payload,sink)
            def readFile(self,path,stream):return self.file(2,path,sink=stream)
            def writeFile(self,path,payload):return self.file(1,path,payload)
        identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        camera=Camera()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'backup';folder.mkdir()
            config,configs,tab,tables,_,_=m._capture(camera,identity,folder)
            result=m._write_once(camera,identity,folder,target,config,configs,tab,tables)
            self.assertEqual(transport.writes,[m.PARTITION])
            self.assertTrue(result['verified'])
            self.assertEqual(m._sha(transport.image),m.TARGET_SHA)
            saved,configs,tables,owner=m.load_rollback(folder)
            self.assertEqual(saved,bytes(original));self.assertTrue(all(x is None for x in configs.values()))
            self.assertEqual(tables,transport.tables);self.assertEqual(owner,identity)

    def test_native_baseline_connect_signature_and_receipt_resume(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        handle=mock.Mock(identity=identity)
        capture=(mock.Mock(),{},mock.Mock(),{},b'current',dict(label='R12',r15nh_current=False))
        with tempfile.TemporaryDirectory() as tmp:
            saved_receipt=Path(tmp)/'native-identity-receipt.json'
            with mock.patch('a9tool.usbdev.load_current_receipt',return_value=saved_receipt) as receipt, \
                 mock.patch('a9tool.usbdev.connect',autospec=True,return_value=handle) as connect, \
                 mock.patch.object(m,'_capture',return_value=capture):
                m.execute('r15.status',dict(session_root=tmp))
            receipt.assert_called_once_with()
            self.assertEqual(connect.call_args.kwargs['receipt'],saved_receipt)
            self.assertEqual(set(connect.call_args.kwargs),{'receipt','guard_factory','response_timeout','progress'})
            self.assertEqual(connect.call_args.kwargs['response_timeout'],900)
        handle.close.assert_called_once()

    def test_release_contains_only_small_r12p_deltas(self):
        m=self.m;manifest=m.package()
        self.assertNotIn('target.bin.xz',manifest['files'])
        self.assertFalse((m.ROOT/'target.bin.xz').exists())
        for row in manifest['sources']:
            if row['label']=='R15 NAME HELP':
                self.assertNotIn('patch',row)
                continue
            self.assertLess(row['patch_statistics']['changed_bytes'],m.PARTITION_BYTES//10)
            self.assertLess(row['patch_statistics']['compressed_patch_bytes'],1024*1024)
            self.assertEqual(len(m._patch_runs(row)),row['patch_statistics']['offset_runs'])

    def test_install_without_identify_and_patch_never_connects(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        material=(b'backup',{},{},identity)
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch('a9tool.usbdev.connect') as connect, \
             mock.patch.object(m,'load_rollback',return_value=material), \
             mock.patch.object(m,'classify',return_value=dict(label='R12',r15nh_current=False)):
            with self.assertRaisesRegex(ValueError,'Identify'):
                m.execute('r15.install',dict(source=tmp,session_root=tmp))
            m.execute('r15.identify',dict(source=tmp))
            with self.assertRaisesRegex(ValueError,'Patch'):
                m.execute('r15.install',dict(source=tmp,session_root=tmp))
        connect.assert_not_called()

    def test_identify_and_patch_are_offline_and_existing_evidence_is_not_overwritten(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        material=(b'backup',{},{},identity)
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch('a9tool.usbdev.connect') as connect, \
             mock.patch.object(m,'load_rollback',return_value=material), \
             mock.patch.object(m,'classify',return_value=dict(label='R12',r15nh_current=False)), \
             mock.patch.object(m,'prepare_image',return_value=(b'candidate',dict(target_sha256=m.TARGET_SHA))):
            with self.assertRaisesRegex(ValueError,'Identify'):
                m.execute('r15.patch',dict(source=tmp))
            m.execute('r15.identify',dict(source=tmp))
            result=m.execute('r15.patch',dict(source=tmp))
            self.assertEqual(Path(result['session']),Path(tmp).resolve())
            m.execute('r15.prepare',dict(source=tmp))
            self.assertEqual((Path(tmp)/'prepared-partition.bin').read_bytes(),b'candidate')
            (Path(tmp)/'prepared-partition.bin').write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'overwrite'):
                m.execute('r15.patch',dict(source=tmp))
        connect.assert_not_called()

    def test_install_rejects_stale_live_backup_before_write(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        material=(b'old',{},{},identity);handle=mock.Mock(identity=identity)
        rt=types.SimpleNamespace(readback_rules=types.SimpleNamespace(compare_complete=mock.Mock(side_effect=ValueError('stale partition'))))
        capture=(mock.Mock(),{},mock.Mock(),{},b'changed',dict(label='R12',r15nh_current=False))
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(m,'_load_prepared',return_value=(b'candidate',material,dict(target_sha256=m.TARGET_SHA))), \
             mock.patch.object(m,'_capture',return_value=capture), \
             mock.patch.object(m,'runtime',return_value=rt), \
             mock.patch.object(m,'check_v8_inactive'), \
             mock.patch.object(m,'_write_once') as write, \
             mock.patch('a9tool.usbdev.load_current_receipt',return_value=None), \
             mock.patch('a9tool.usbdev.connect',autospec=True,return_value=handle):
            with self.assertRaisesRegex(ValueError,'stale'):
                m.execute('r15.install',dict(source=tmp,session_root=tmp))
        write.assert_not_called()

    def test_inspect_session_is_local_and_invalid_material_never_unlocks(self):
        m=self.m
        with tempfile.TemporaryDirectory() as tmp, mock.patch('a9tool.usbdev.connect') as connect:
            result=m.inspect_session(tmp)
        self.assertFalse(result['backup_valid']);self.assertFalse(result['identified']);self.assertFalse(result['patched'])
        self.assertTrue(result['reason']);connect.assert_not_called()

    def test_prepared_session_unlocks_only_with_matching_candidate_and_paired_evidence(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        material=(b'backup',{'cfg':b'record'},{1:b'table'},identity);candidate=b'candidate'
        row=next(r for r in m.package()['sources'] if r['label']=='R12')
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch('a9tool.usbdev.connect') as connect, \
             mock.patch.object(m,'load_rollback',return_value=material), \
             mock.patch.object(m,'classify',return_value=dict(label='R12',r15nh_current=False)), \
             mock.patch.object(m,'PARTITION_BYTES',len(candidate)), \
             mock.patch.object(m,'TARGET_SHA',m._sha(candidate)):
            source=Path(tmp)
            m._record_verified(source/'identified.json',m._identified(source,material))
            m._write_verified(source/'prepared-partition.bin',candidate)
            m._record_verified(source/'prepared.json',dict(target_sha256=m._sha(candidate),patch=row['patch'],
                              patch_statistics=row['patch_statistics'],**m._material_identity(*material)))
            checked=m.inspect_session(source)
            self.assertTrue(checked['backup_valid'] and checked['identified'] and checked['patched'])
            (source/'prepared-partition.bin').write_bytes(b'tampered!')
            checked=m.inspect_session(source)
            self.assertTrue(checked['backup_valid'] and checked['identified']);self.assertFalse(checked['patched'])
        connect.assert_not_called()

    def test_external_package_and_manifest_mismatch_never_connect(self):
        m=self.m
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'manifest.json').write_text('{}')
            for args in (dict(package=tmp),dict(manifest=str(root/'manifest.json'))):
                with mock.patch('a9tool.usbdev.connect') as connect, self.assertRaises(ValueError):
                    m.execute('r15.install',args)
                connect.assert_not_called()

    def _mini_write(self, mode):
        m=self.m;original=b'a'*64;payload=b'b'*64
        config=mock.Mock();tab=mock.Mock();camera=mock.Mock();calls=[]
        def read(camera_arg,path,partition):
            calls.append(path.name)
            raw=(b'c'*64 if mode=='changed' else original) if path.name=='prewrite.bin' else payload
            path.write_bytes(raw)
            return dict(bytes=len(raw),sha256=m._sha(raw))
        def compare(a,b):
            if a!=b:raise ValueError('Partition differs')
            return dict(verified=True,whole_partition_match=True,match_kind='EXACT')
        rt=types.SimpleNamespace(partition_core=types.SimpleNamespace(read_to_file=read),
                                 readback_rules=types.SimpleNamespace(compare_complete=compare))
        if mode=='timeout':camera.writeFile.side_effect=TimeoutError('write acknowledgement lost')
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);(folder/'partition').mkdir();(folder/'partition/preimage.bin').write_bytes(original)
            with mock.patch.object(m,'PARTITION_BYTES',64),mock.patch.object(m,'runtime',return_value=rt),mock.patch.object(m,'check_v8_inactive'):
                if mode in ('changed','timeout'):
                    with self.assertRaises((ValueError,TimeoutError)):
                        m._write_once(camera,{},folder,payload,config,{},tab,{})
                else:
                    result=m._write_once(camera,{},folder,payload,config,{},tab,{})
                    self.assertTrue(result['verified'])
                self.assertEqual((folder/'partition/preimage.bin').read_bytes(),original)
        self.assertEqual(camera.writeFile.call_count,0 if mode=='changed' else 1)
        self.assertEqual(calls,['prewrite.bin'] if mode in ('changed','timeout') else ['prewrite.bin','readback.bin'])

    def test_write_once_requires_full_readback(self):self._mini_write('success')
    def test_write_timeout_never_retries_and_retains_original(self):self._mini_write('timeout')
    def test_partition_changed_before_write_is_rejected(self):self._mini_write('changed')

    def test_rollback_restores_exact_four_records_and_two_tables(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        cfg={p:bytes([i])*128 for i,p in enumerate(m.runtime().guarded_config.PATHS)}
        tables={pid:bytes([i])*1280 for i,pid in enumerate(m.runtime().guarded_config.LUT_IDS)}
        configuration=mock.Mock();table=mock.Mock();handle=mock.Mock(identity=identity)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'original';source.mkdir()
            capture=(configuration,{},table,{},b'current',dict(label='R15 NAME HELP',r15nh_current=True))
            with mock.patch.object(m,'load_rollback',return_value=(b'original',cfg,tables,identity)), \
                 mock.patch.object(m,'_capture',return_value=capture), \
                 mock.patch.object(m,'_write_once',return_value=dict(write_attempted=True)), \
                 mock.patch.object(m,'classify',return_value=dict(r15nh_current=False)), \
                 mock.patch.object(m,'check_v8_inactive'), \
                 mock.patch('a9tool.usbdev.connect',return_value=handle):
                result=m.execute('r15.rollback',dict(session_root=tmp,source=str(source)))
            self.assertEqual(configuration.restore.call_args.args[0],cfg)
            self.assertEqual(table.restore.call_args.args[0],tables)
            self.assertFalse(result['r15nh_current'])

    def test_v8_active_rejects_rollback_before_partition_write(self):
        m=self.m;identity=dict(model='ILCE-9',firmware='6.00',serial_sha256='a'*64)
        handle=mock.Mock(identity=identity)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'original';source.mkdir()
            capture=(mock.Mock(),{},mock.Mock(),{},b'current',dict(label='R15 NAME HELP',r15nh_current=True))
            with mock.patch.object(m,'load_rollback',return_value=(b'original',{},{},identity)), \
                 mock.patch.object(m,'_capture',return_value=capture), \
                 mock.patch.object(m,'_write_once') as write, \
                 mock.patch.object(m,'check_v8_inactive',side_effect=ValueError('V8 is active')), \
                 mock.patch('a9tool.usbdev.connect',return_value=handle):
                with self.assertRaisesRegex(ValueError,'V8') as raised:
                    m.execute('r15.rollback',dict(session_root=tmp,source=str(source)))
            write.assert_not_called()
            self.assertEqual(raised.exception.session,str(source.resolve()))
            self.assertNotEqual(raised.exception.failure_session,str(source))

    def test_four_cfg_restore_preserves_native_bounded_transport(self):
        m=self.m;rt=m.runtime();paths=rt.guarded_config.PATHS
        class Transport:
            def __init__(self):
                self.configs={p:b'a'*128 for p in paths};self.writes=[]
            def sendSenserPacket(self,function,packet,oData=None):
                if function==0x40:
                    block,code=struct.unpack_from('<HH',packet)
                    if code==0x4002:return 0,bytes(4)
                    path=packet[10:-1].decode()
                    value=self.configs[path]
                    return (0,struct.pack('<I',rt.guarded_config.MISSING)) if value is None else (0,bytes(4)+value)
                command,n=struct.unpack_from('<hh',packet)
                path=packet[4:4+n].rstrip(b'\0').decode()
                self.writes.append(path)
                self.configs[path]=None if command==3 else packet[4+n:]
                return 0,b''
        transport=Transport();guard=m.make_guard(transport,True)
        class Camera:
            dev=guard
            def writeFile(self,path,raw):
                name=path.encode();name+=bytes(4-len(name)%4)
                return self.dev.sendSenserPacket(0xff01,struct.pack('<hh',1,len(name))+name+raw)
        targets={path:bytes([i])*128 for i,path in enumerate(paths)}
        configuration=rt.guarded_config.Configuration(Camera())
        with tempfile.TemporaryDirectory() as tmp:
            configuration.restore(targets,Path(tmp)/'restore')
        self.assertEqual(transport.configs,targets)
        self.assertEqual(transport.writes,list(paths))
        self.assertEqual(guard.native_send,transport.sendSenserPacket)


if __name__ == '__main__':
    unittest.main()
