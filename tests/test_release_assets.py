import unittest
from a9tool import release_assets


class ReleaseTests(unittest.TestCase):
    def test_release_hashes_and_initial_inventory(self):
        release_assets.verify()
        meta = release_assets.r15()
        self.assertEqual(len(meta['initial_files']), 5)
        self.assertEqual(len(meta['sources']), 3)
        self.assertIn('R15-ORIGINAL', [x['profile'] for x in meta['sources']])

    def test_asset_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            release_assets.asset('../README.md')
