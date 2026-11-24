import unittest
import struct
import zlib
from a9tool import r15_files, release_assets


class R15Tests(unittest.TestCase):
    def test_real_sources_preserve_all_eighty_blocks(self):
        package = release_assets.r15()
        for profile in package['sources']:
            raw = release_assets.asset('r15/' + profile['fixture'])
            offset = profile['object_offset']
            objects = b''.join(bytes([i]) * 4096 for i in range(80))
            raw = raw[:offset] + objects
            prepared, report = r15_files.prepare(raw, [None]*4,
                list(r15_files.a9p.stock()), package)
            self.assertEqual(prepared[-80*4096:], objects)
            self.assertEqual(report['object_blocks_preserved'], 80)
            self.assertEqual(report['source_profile'], profile['profile'])

    def test_unknown_code_rejected(self):
        package = release_assets.r15()
        raw = bytearray(release_assets.asset('r15/a9fl.so'))
        raw[60] ^= 1
        with self.assertRaisesRegex(ValueError, 'Unsupported'):
            r15_files.prepare(bytes(raw), [None]*4, list(r15_files.a9p.stock()), package)

    def test_corrupt_config_and_live_table_rejected(self):
        package = release_assets.r15()
        raw = release_assets.asset('r15/a9fl.so')
        for configs,tables in (([b'bad',None,None,None],list(r15_files.a9p.stock())),
                               ([None]*4,[b'bad',b'bad'])):
            with self.assertRaises(ValueError):
                r15_files.prepare(raw, configs, tables, package)

    def test_install_gate_is_not_user_supplied(self):
        with self.assertRaisesRegex(RuntimeError, 'snapshot'):
            r15_files.require_replacement_protocol()

    def record(self, tables, digest, schema=8):
        raw=bytearray(2048)
        raw[:8]=b'A9FLP001'
        struct.pack_into('<4I',raw,8,2048,1,schema,28)
        raw[56:88]=r15_files.a9p.SHA
        raw[88:112]=r15_files.a9p.BUILD
        struct.pack_into('<II',raw,112,*(zlib.crc32(x) for x in tables))
        packed=0
        for bank in range(43):
            for field,value in enumerate(r15_files.a9p.DEFAULT):
                packed|=value<<(5*(bank*16+field))
        raw[128:558]=packed.to_bytes(430,'little')
        raw[558]=80;raw[559:591]=digest
        struct.pack_into('<I',raw,2044,zlib.crc32(raw[:2044]))
        return bytes(raw)

    def test_r14_schema8_refs_keep_raw_bytes_and_block_index(self):
        package=release_assets.r15(); tables=list(r15_files.a9p.stock())
        raw=bytearray(release_assets.asset('r15/R14-SD.so'))
        obj=r15_files.a9p.encode('测试 Preset',tables)
        raw[-4096:]=obj+bytes(4096-len(obj))
        digest=bytes.fromhex(r15_files.a9p.inspect(obj)['sha256_payload'])
        cfg=self.record(tables,digest)
        prepared,report=r15_files.prepare(bytes(raw),[cfg,None,None,None],tables,package)
        self.assertEqual(prepared[-4096:],raw[-4096:])
        self.assertEqual(report['config_sha256'][0],release_assets.sha(cfg))
        self.assertEqual(report['target_state']['records']['A9FL0.CFG']['schema'],8)
        self.assertEqual(report['target_state']['records']['A9FL0.CFG']['objects']['1']['block'],80)
        with self.assertRaisesRegex(ValueError,'SHA-256 mismatch'):
            r15_files.prepare(bytes(raw),[self.record(tables,bytes(32)),None,None,None],tables,package)
