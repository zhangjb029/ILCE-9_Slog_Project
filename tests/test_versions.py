"""Version identification: the table's integrity and its failure paths.

Reading a real partition is covered by hand against the release images; what CI
can protect is that the table is complete, that no two builds share a
fingerprint, and that an unreadable partition is reported rather than raised.
"""
import unittest

from a9tool import versions


class TestTable(unittest.TestCase):
    def test_every_known_build_is_present(self):
        labels = [entry['label'] for entry in versions.table()['versions']]
        for expected in ('原厂 6.00', 'R8', 'R9.1', 'R10', 'R11', 'R12'):
            self.assertIn(expected, labels)

    def test_no_two_builds_share_a_fingerprint(self):
        seen = {}
        for entry in versions.table()['versions']:
            key = tuple(sorted(entry['files'].items()))
            self.assertNotIn(key, seen,
                             f'{entry["label"]} has the same fingerprint as {seen.get(key)}')
            seen[key] = entry['label']

    def test_every_build_compares_the_same_files(self):
        table = versions.table()
        for entry in table['versions']:
            self.assertEqual(sorted(entry['files']), sorted(table['files']))

    def test_factory_has_no_creative_look_module(self):
        factory = next(e for e in versions.table()['versions'] if e['label'].startswith('原厂'))
        self.assertIsNone(factory['files']['lib/a9fl.so'])

    def test_the_shipped_target_matches_one_build(self):
        labels = [e['label'] for e in versions.table()['versions']]
        from a9tool import menu_deploy
        self.assertIn(menu_deploy.VERSION_LABEL, labels)


class TestIdentify(unittest.TestCase):
    def test_zeroes_are_reported_as_unreadable(self):
        result = versions.identify(bytes(8192))
        self.assertFalse(result['readable'])
        self.assertFalse(result['matched'])
        self.assertIsNone(result['label'])
        self.assertTrue(result['note'])

    def test_a_short_buffer_does_not_raise(self):
        result = versions.identify(b'\x00' * 16)
        self.assertFalse(result['readable'])

    def test_a_non_ext2_blob_is_reported(self):
        result = versions.identify(b'\xab' * 65536)
        self.assertFalse(result['readable'])


if __name__ == '__main__':
    unittest.main()
