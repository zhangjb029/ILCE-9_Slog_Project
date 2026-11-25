"""Offline format/colour regression checks, independent of camera/USB tests."""
import importlib.util
import math
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'a9w'))
sys.path.insert(0,str(ROOT/'lut'))
import runtime
from a9tool import release_a9p
from pack_wps import build_package,FOUR_SLOT_BYTES
from inspect_a9w import inspect
from make_burst_wps import decode_sds,encode_exact


class AudioTests(unittest.TestCase):
    def test_versions_and_selected_slot_sizes(self):
        for sizes,version,total in ((FOUR_SLOT_BYTES[:3],1,73600),(FOUR_SLOT_BYTES,2,83520)):
            with self.subTest(version=version):
                report=inspect(build_package([bytes(n) for n in sizes]))
                self.assertEqual((report['version'],report['bytes']),(version,total))
                self.assertTrue(all(row['selected'] for row in report['slots']))

    def test_partial_restore_and_tamper_are_distinguished(self):
        raw=build_package([None,bytes(29760),None,None])
        self.assertEqual(inspect(raw)['mask'],2)
        self.assertEqual(inspect(build_package([None]*4))['mask'],0)
        for at in (0,20,224,512,len(raw)-1):
            with self.subTest(offset=at):
                bad=bytearray(raw);bad[at]^=1
                with self.assertRaises(ValueError):inspect(bytes(bad))

    def test_invalid_sds_frames_and_capacities_are_rejected(self):
        with self.assertRaises(ValueError):build_package([bytes(24767),None,None])
        with self.assertRaises(ValueError):build_package([b'\x20'+bytes(24767),None,None])

    def test_sds_predictor_and_padding(self):
        # Mode1, shift0, residual1: predictor is carried across frame boundaries.
        decoded=decode_sds((b'\x10'+b'\x01'*31)*2)
        previous=0;expected=[]
        for i in range(62):previous=int(previous*15/16)+1;expected.append(previous)
        self.assertEqual(decoded,expected)
        tone=[round(8000*math.sin(i*.2)) for i in range(93)]
        encoded=encode_exact(tone,4)
        self.assertEqual(len(encoded),128)
        self.assertEqual(len(decode_sds(encoded)),124)
        self.assertLess(max(abs(a-b) for a,b in zip(tone,decode_sds(encoded))),256)


class NativeLutTests(unittest.TestCase):
    def test_native_export_inspect_and_monotonicity(self):
        stock=release_a9p.stock();raw=release_a9p.encode('Example',stock)
        self.assertEqual(len(raw),2756)
        self.assertEqual(release_a9p.inspect(raw)['name'],'Example')
        bad=bytearray(stock[0]);bad[1215]^=1
        with self.assertRaises(ValueError):release_a9p.encode('Example',(bytes(bad),stock[1]))

    def test_frozen_data_identity(self):
        self.assertEqual(runtime.checked_data('baseline.npz').stat().st_size,2777295)
        runtime.checked_data('chroma_curves.json')


class CubeTests(unittest.TestCase):
    def test_red_fastest_and_domain(self):
        import numpy as np
        from lut import Cube
        source='LUT_3D_SIZE 2\n'+'\n'.join(f'{r} {g} {b}' for b in (0,1) for g in (0,1) for r in (0,1))
        x=np.random.default_rng(1).random((40,3))
        np.testing.assert_allclose(Cube.parse(source)(x),x,atol=1e-12)
        with self.assertRaises(ValueError):Cube.parse('LUT_1D_SIZE 2\n'+source)

    def test_colour_and_log_reference_points(self):
        import numpy as np
        from lut import convert_rgb,log_encode
        x=np.random.default_rng(2).random((20,3))
        np.testing.assert_allclose(convert_rgb(convert_rgb(x,'srgb','adobe'),'adobe','srgb'),x,atol=1e-6)
        np.testing.assert_allclose(log_encode(np.array([.18]),'vlog'),[.42331145],atol=1e-6)


if __name__=='__main__':unittest.main()
