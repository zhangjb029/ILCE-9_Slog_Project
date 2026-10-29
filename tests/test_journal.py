import json
import tempfile
import unittest
from pathlib import Path

from a9tool import journal


class TestJournal(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_create_writes_snapshot_before_journal(self):
        s = journal.create(self.root, 'write_slot', {'slot': 7}, b'\x01\x02')
        self.assertEqual((s.directory / 'Backup-original.bin').read_bytes(), b'\x01\x02')
        self.assertEqual(json.loads((s.directory / 'journal.json').read_text())['action'], 'write_slot')

    def test_two_creates_get_distinct_directories(self):
        a = journal.create(self.root, 'a', {}, b'x')
        b = journal.create(self.root, 'a', {}, b'x')
        self.assertNotEqual(a.directory, b.directory)
        self.assertEqual(len([p for p in self.root.iterdir() if p.is_dir()]), 2)

    def test_list_sessions_newest_first(self):
        journal.create(self.root, 'a', {}, b'x')
        journal.create(self.root, 'b', {}, b'y')
        self.assertEqual([s.action for s in journal.list_sessions(self.root)], ['b', 'a'])

    def test_journal_marks_chained_original(self):
        first = journal.create(self.root, 'write_slot', {'slot': 7, 'original': '06'}, b'x')
        second = journal.create(self.root, 'write_slot', {'slot': 7, 'original': '36',
                                                          'written_by': str(first.directory)}, b'y')
        self.assertTrue(journal.mark_chained(second))
        self.assertFalse(journal.mark_chained(first))

    def test_save_leaves_no_temporary_file(self):
        s = journal.create(self.root, 'a', {}, b'x')
        journal.save(s)
        self.assertEqual(sorted(p.name for p in s.directory.iterdir()),
                         ['Backup-original.bin', 'journal.json'])

    def test_list_sessions_skips_a_corrupt_journal(self):
        good = journal.create(self.root, 'good', {}, b'x')
        bad = journal.create(self.root, 'bad', {}, b'y')
        (bad.directory / 'journal.json').write_text('{ truncated', encoding='utf-8')
        self.assertEqual([s.directory.name for s in journal.list_sessions(self.root)],
                         [good.directory.name])

    def test_list_sessions_skips_a_directory_without_payload(self):
        good = journal.create(self.root, 'good', {}, b'x')
        (self.root / '20200101-000000000000-orphan').mkdir()
        self.assertEqual([s.directory.name for s in journal.list_sessions(self.root)],
                         [good.directory.name])

    def test_load_rejects_tampered_snapshot(self):
        s = journal.create(self.root, 'a', {}, b'original')
        (s.directory / 'Backup-original.bin').write_bytes(b'changed!')
        with self.assertRaises(ValueError):
            journal.load(s.directory / 'journal.json')


if __name__ == '__main__':
    unittest.main()
