import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

from a9tool import core, fnmap, gui, journal
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
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(journal, 'sessions_root', return_value=Path(self._tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = gui.App(self.root)

    def tearDown(self):
        self.root.destroy()
        self._tmp.cleanup()

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

    # -- electronic-shutter flash tab --------------------------------------
    def test_flash_tab_exists(self):
        self.assertEqual(len(self.app.notebook.tabs()), 2)
        self.assertEqual(self.app.notebook.tab(1, 'text'), '电子快门引闪')

    def test_flash_buttons_disabled_before_reading(self):
        for button in (self.app.flash_menu_btn, self.app.flash_av_btn):
            self.assertEqual(str(button['state']), 'disabled')
        self.assertEqual(str(self.app.flash_status_btn['state']), 'normal')

    def _baseline(self, menu=1, av=0):
        return dict(
            record={'created': '2026-11-11T00:00:00+00:00', 'menu_value': menu, 'av_value': av,
                    'identity': {'serial_sha256': 'a' * 64}},
            menu=b'\x01' * 1024, av=b'\x00' * 256)

    def _set_flash(self, menu, av, baseline=True):
        """Drive the widget state directly; the camera lane is covered elsewhere."""
        self.app.flash_baseline = self._baseline(menu=menu, av=av) if baseline else None
        self.app.flash_menu_value = menu
        self.app.flash_av_value = av
        self.app._update_flash_baseline_text()
        self.app._refresh_flash()

    def test_flash_menu_button_offers_the_first_step(self):
        self._set_flash(1, 0)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'normal')
        self.assertEqual(str(self.app.flash_av_btn['state']), 'disabled')

    def test_flash_av_button_requires_menu_already_open(self):
        self._set_flash(0, 0)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'disabled')
        self.assertEqual(str(self.app.flash_av_btn['state']), 'normal')

    def test_flash_buttons_idle_when_both_gates_open(self):
        self._set_flash(0, 1)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'disabled')
        self.assertEqual(str(self.app.flash_av_btn['state']), 'disabled')

    def test_flash_read_failure_leaves_values_unknown(self):
        self.app._flash_status_done(None, RuntimeError('boom'))
        self.assertIsNone(self.app.flash_menu_value)
        self.assertIsNone(self.app.flash_av_value)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'disabled')

    # -- the write path is gated on a saved baseline -----------------------
    def test_flash_write_buttons_stay_disabled_without_a_baseline(self):
        self._set_flash(1, 0, baseline=False)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'disabled')
        self.assertEqual(str(self.app.flash_av_btn['state']), 'disabled')
        self.assertEqual(str(self.app.flash_restore_btn['state']), 'disabled')
        self.assertIn('尚未保存', self.app.flash_restore_var.get())

    def test_flash_write_buttons_enable_once_the_baseline_exists(self):
        self._set_flash(1, 0)
        self.assertEqual(str(self.app.flash_menu_btn['state']), 'normal')
        self.assertEqual(str(self.app.flash_restore_btn['state']), 'normal')
        self.assertIn('初始备份', self.app.flash_restore_var.get())

    def test_flash_restore_restores_the_baseline_without_a_file_picker(self):
        self._set_flash(0, 1)
        self.assertEqual(self.app.flash_restore_btn.cget('text'), '恢复到初始备份')

if __name__ == '__main__':
    unittest.main()
