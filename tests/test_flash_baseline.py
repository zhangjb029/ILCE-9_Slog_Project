import tempfile
import unittest
from pathlib import Path
from unittest import mock

from a9tool import flash_baseline, journal
from tests.flash_av_fakes import IDENTITY, av_data, backup
from tests.flash_fakes import config


class TestFlashBaseline(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        patcher = mock.patch.object(journal, 'sessions_root', return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_then_load_round_trips(self):
        path = flash_baseline.save(backup(config(1), av_data(0)), IDENTITY)
        self.assertTrue(path.exists())
        loaded = flash_baseline.load()
        self.assertEqual(loaded['record']['menu_value'], 1)
        self.assertEqual(loaded['record']['av_value'], 0)
        self.assertEqual(loaded['menu'], config(1))
        self.assertEqual(loaded['av'], av_data(0))

    def test_save_never_overwrites_the_first_read(self):
        first = flash_baseline.save(backup(config(1), av_data(0)), IDENTITY)
        second = flash_baseline.save(backup(config(0), av_data(1)), IDENTITY)
        self.assertEqual(first, second)
        self.assertEqual(flash_baseline.load()['record']['menu_value'], 1)

    def test_missing_baseline_returns_none(self):
        self.assertIsNone(flash_baseline.load())

    def test_damaged_blob_returns_none(self):
        flash_baseline.save(backup(config(1), av_data(0)), IDENTITY)
        (flash_baseline.root() / flash_baseline.MENU_FILE).write_bytes(b'x')
        self.assertIsNone(flash_baseline.load())

    def test_truncated_record_returns_none(self):
        flash_baseline.save(backup(config(1), av_data(0)), IDENTITY)
        flash_baseline.record_path().write_text('{ not json', encoding='utf-8')
        self.assertIsNone(flash_baseline.load())

    def test_belongs_to_compares_the_serial_fingerprint(self):
        flash_baseline.save(backup(config(1), av_data(0)), IDENTITY)
        loaded = flash_baseline.load()
        self.assertTrue(flash_baseline.belongs_to(loaded, IDENTITY))
        other = dict(IDENTITY, serial_sha256='b' * 64)
        self.assertFalse(flash_baseline.belongs_to(loaded, other))


if __name__ == '__main__':
    unittest.main()
