import tkinter as tk
import unittest

from a9tool import core, fnmap, gui
from tests.fakecamera import FakeCamera


def _tk_available() -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


TK_OK = _tk_available()


def _override(fill: int) -> bytes:
    raw = bytearray([fill] * 1024)
    if fill == 1:
        return bytes(raw)
    for off in fnmap.OVERRIDE_OFFSETS:
        raw[off] = 2
    return bytes(raw)


@unittest.skipUnless(TK_OK, 'no display for tkinter')
class TestGui(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)

    def tearDown(self):
        self.root.destroy()

    def _connect(self, override: bytes):
        self.app.handle = type('Handle', (), {'identity': {'model': 'ILCE-9', 'firmware': '6.00',
                                                           'serial_sha256': 'a' * 64},
                                              'close': lambda _self: None})()
        self.app.state = core.read_state(FakeCamera(override=override))
        self.app._show_status()
        self.app._refresh()

    def test_starts_disconnected(self):
        self.assertEqual(len(self.app.all_tree.get_children()), 77)
        self.assertEqual(str(self.app.connect_btn['state']), 'normal')
        self.assertEqual(str(self.app.override_btn['state']), 'disabled')
        for button in self.app.card_buttons:
            self.assertEqual(str(button['state']), 'disabled')

    def test_cards_disabled_until_override_enabled(self):
        self._connect(_override(1))
        self.assertIn('未开启', self.app.override_var.get())
        self.assertEqual(str(self.app.override_btn['state']), 'normal')
        for button in self.app.card_buttons:
            self.assertEqual(str(button['state']), 'disabled')

    def test_cards_enabled_once_override_on(self):
        self._connect(_override(2))
        self.assertIn('已开启', self.app.override_var.get())
        self.assertEqual(str(self.app.override_btn['state']), 'disabled')
        for button in self.app.card_buttons:
            self.assertEqual(str(button['state']), 'normal')

    def test_mixed_override_offers_no_write(self):
        raw = bytearray(1024)
        raw[0xa2] = 2
        self._connect(bytes(raw))
        self.assertIn('状态异常', self.app.override_var.get())
        self.assertEqual(str(self.app.override_btn['state']), 'disabled')
        for button in self.app.card_buttons:
            self.assertEqual(str(button['state']), 'disabled')

    def test_lock_after_write_disables_everything(self):
        self._connect(_override(2))
        self.app._lock_after_write()
        for button in self.app.card_buttons:
            self.assertEqual(str(button['state']), 'disabled')
        self.assertEqual(str(self.app.connect_btn['state']), 'disabled')
        self.assertIn('重启', self.app.status_var.get())

    def test_known_bad_row_is_marked(self):
        values = self.app.all_tree.item(str(0x64))['values']
        self.assertIn('⛔', str(values))

    def test_verified_rows_are_marked(self):
        for value in (0x3A, 0x36):
            self.assertIn('✅', str(self.app.all_tree.item(str(value))['values']))


if __name__ == '__main__':
    unittest.main()
