import unittest

from a9tool import fnmap


class TestFnMap(unittest.TestCase):
    def test_seventy_seven_distinct_values(self):
        items = fnmap.load_functions()
        self.assertEqual(len(items), 77)
        self.assertEqual(len({i.value for i in items}), 77)

    def test_verified_values(self):
        self.assertEqual(fnmap.status_of(0x3A), 'verified')
        self.assertEqual(fnmap.status_of(0x36), 'verified')

    def test_pixel_shift_is_known_bad(self):
        self.assertEqual(fnmap.status_of(0x64), 'known_bad')

    def test_untested_default(self):
        self.assertEqual(fnmap.status_of(0x01), 'untested')

    def test_slots_are_not_linear(self):
        self.assertEqual(fnmap.FN_SLOTS[10], 0x01070be9)
        self.assertEqual(fnmap.FN_SLOTS[2], 0x01070bec)
        self.assertEqual(len(set(fnmap.FN_SLOTS.values())), 12)

    def test_chinese_name_present_for_every_value(self):
        for item in fnmap.load_functions():
            self.assertTrue(item.chinese, msg=f'0x{item.value:02X} missing name')


if __name__ == '__main__':
    unittest.main()
