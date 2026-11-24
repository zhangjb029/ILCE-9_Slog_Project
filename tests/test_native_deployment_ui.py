import tempfile
import tkinter as tk
import time
import unittest
from pathlib import Path
from unittest import mock

from a9tool import gui, journal


class NativeDeploymentTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('Tk display unavailable')
        self.root.withdraw()
        self.folder = tempfile.TemporaryDirectory()
        self.session_root = Path(self.folder.name).resolve()
        self.addCleanup(self.folder.cleanup)
        patcher = mock.patch.object(journal, 'sessions_root', return_value=self.session_root)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = gui.App(self.root)
        self.addCleanup(self.close_root)

    def close_root(self):
        for identifier in self.root.tk.call('after', 'info'):
            self.root.after_cancel(identifier)
        self.root.destroy()

    def wait(self):
        until = time.monotonic() + 3
        while self.app.busy and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertFalse(self.app.busy)

    def wait_audit(self):
        until = time.monotonic() + 3
        while self.app.r15_audit_pending and time.monotonic() < until:
            self.root.update()
            time.sleep(.01)
        self.root.update()
        self.assertFalse(self.app.r15_audit_pending)

    def test_native_tabs_keep_original_four_features_and_add_v8(self):
        labels = [self.app.notebook.tab(tab, 'text') for tab in self.app.notebook.tabs()]
        self.assertEqual(labels, ['Fn 功能', '电子快门引闪', '创意外观 LUT · R15NH',
                                  '悬浮菜单 · V8', '解锁 5GHz WiFi', '强制回退'])
        self.assertEqual(len(self.app.all_tree.get_children()), 77)
        self.assertEqual(str(self.app.connect_btn['state']), 'normal')

    def test_status_read_displays_installed_versions_and_keeps_workflow_source(self):
        original = str(self.session_root/'original')
        self.app.native_source_vars['r15'].set(original)
        r15 = dict(state='current', label='R15 NAME HELP', state_validated=True)
        self.app._native_deployment_done('v8.status', dict(state='READ_ONLY_COMPLETE',
            r15nh_current=True, r15=r15, menu=dict(state='current', label='V8',
                payload_state='complete', payloads_present=3, payloads_expected=3,
                preload_state='v8', installable=True)), None)
        text = self.app.native_device_status_vars['v8'].get()
        self.assertIn('R15NH：已安装', text)
        self.assertIn('V8：已部署', text)
        self.assertIn('入口已启用', text)
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)
        self.assertEqual(self.app.r15_work_var.get(), '')

    def test_direct_r15_status_read_names_the_current_version_without_preparing(self):
        from a9tool import native_deployment_ui
        with mock.patch.object(native_deployment_ui, 'execute_native', return_value=dict(
                state='READ_ONLY_COMPLETE', r15=dict(state='legacy', label='R12'),
                session=str(self.session_root/'read'))) as execute:
            self.app.on_native_deployment('r15.status')
            self.wait()
        self.assertIn('未安装；当前版本 R12', self.app.native_device_status_vars['r15'].get())
        self.assertEqual(execute.call_args.args[0], 'r15.status')
        self.assertEqual(self.app.r15_work_var.get(), '')
        self.assertEqual(str(self.app.native_buttons['r15.install']['state']), 'disabled')

    def test_failed_status_read_does_not_leave_a_previous_installed_message(self):
        self.app.native_device_status_vars['v8'].set('V8：已部署')
        self.app._native_deployment_done('v8.status', None, TimeoutError('read failed'))
        text = self.app.native_device_status_vars['v8'].get()
        self.assertIn('当前状态无法确认', text)
        self.assertNotIn('已部署', text)

    def test_lut_requires_backup_identification_and_patch_before_write(self):
        from a9tool import native_deployment_ui
        for action in ('r15.identify', 'r15.patch', 'r15.install'):
            self.assertEqual(str(self.app.native_buttons[action]['state']), 'disabled')
        folder = str(self.session_root/'selected-backup')
        with mock.patch.object(native_deployment_ui, 'inspect_r15_session', return_value={
                'backup_valid': True, 'identified': False, 'patched': False, 'session': folder}):
            self.app.r15_work_var.set(folder)
            self.assertEqual(str(self.app.native_buttons['r15.install']['state']), 'disabled')
            self.wait_audit()
        self.assertEqual(str(self.app.native_buttons['r15.identify']['state']), 'normal')
        self.assertEqual(str(self.app.native_buttons['r15.patch']['state']), 'disabled')
        with mock.patch.object(native_deployment_ui, 'inspect_r15_session', return_value={
                'backup_valid': True, 'identified': True, 'patched': True, 'session': folder}):
            self.app.audit_r15_work()
            self.wait_audit()
        self.assertEqual(str(self.app.native_buttons['r15.patch']['state']), 'normal')
        self.assertEqual(str(self.app.native_buttons['r15.install']['state']), 'normal')
        with mock.patch.object(native_deployment_ui.messagebox, 'askyesno', return_value=True), \
                mock.patch.object(native_deployment_ui, 'execute_native', return_value={
                    'state': 'FULL_PARTITION_READBACK_VERIFIED', 'source': folder}) as execute:
            self.app.on_native_deployment('r15.install')
            self.wait()
        self.assertEqual(execute.call_args.args[:2], ('r15.install', {
            'session_root': str(self.session_root), 'source': folder}))

    def test_a_path_without_valid_evidence_never_enables_write(self):
        from a9tool import native_deployment_ui
        with mock.patch.object(native_deployment_ui, 'inspect_r15_session', side_effect=ValueError('incomplete backup')), \
                mock.patch.object(native_deployment_ui, 'execute_native') as execute:
            self.app.r15_work_var.set(str(self.session_root))
            self.wait_audit()
            self.app.on_native_deployment('r15.install')
        execute.assert_not_called()
        self.assertEqual(str(self.app.native_buttons['r15.install']['state']), 'disabled')

    def test_native_action_closes_existing_handle_and_uses_local_sessions(self):
        from a9tool import native_deployment_ui
        closed = []
        self.app.handle = type('Handle', (), {'close': lambda handle: closed.append(True)})()
        with mock.patch.object(native_deployment_ui, 'inspect_r15_session', return_value={
                'backup_valid': True, 'identified': False, 'patched': False,
                'session': str(self.session_root/'r15-read')}), \
                mock.patch.object(native_deployment_ui, 'execute_native', return_value={
                'state': 'READ_ONLY_COMPLETE', 'session': str(self.session_root/'r15-read'),
                'rollback_available': True}) as execute:
            self.app.on_native_deployment('r15.backup')
            self.wait()
        self.assertEqual(closed, [True])
        self.assertIsNone(self.app.handle)
        self.assertEqual(execute.call_args.args[:2], ('r15.backup', {'session_root': str(self.session_root)}))
        self.assertEqual(self.app.native_source_vars['r15'].get(), str(self.session_root/'r15-read'))

    def test_offline_check_preserves_an_open_fn_connection(self):
        from a9tool import native_deployment_ui
        handle = mock.Mock()
        self.app.handle = handle
        with mock.patch.object(native_deployment_ui, 'execute_native', return_value={'state': 'VERIFIED'}):
            self.app.on_native_deployment('r15.check')
            self.wait()
        handle.close.assert_not_called()
        self.assertIs(self.app.handle, handle)

    def test_status_after_install_does_not_replace_the_original_preimage(self):
        original = str(self.session_root/'install-original')
        self.app._native_deployment_done('r15.install', {'session': original, 'rollback_available': True}, None)
        self.app._native_deployment_done('r15.backup', {
            'session': str(self.session_root/'current-r15nh'), 'rollback_available': True}, None)
        self.app._native_deployment_done('r15.patch', {
            'session': str(self.session_root/'current-prepared'), 'rollback_available': True}, None)
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)

    def test_reinstalling_current_v8_preserves_the_first_install_source(self):
        original = str(self.session_root/'first-install')
        self.app._native_deployment_done('v8.install', {'session': original}, None)
        self.app._native_deployment_done('v8.install', {
            'session': str(self.session_root/'already-active'),
            'deactivation_requires_original_session': True}, None)
        self.assertEqual(self.app.native_source_vars['v8'].get(), original)
        self.assertIn('本次会话不能卸载', self.app.log_box.get('1.0', 'end'))

    def test_reinstalling_current_r15_preserves_the_original_stock_source(self):
        original = str(self.session_root/'stock-backup')
        self.app._native_deployment_done('r15.install', {
            'session': original, 'source_label': '原厂'}, None)
        self.app._native_deployment_done('r15.install', {
            'session': str(self.session_root/'already-r15nh'), 'source_label': 'R15 NAME HELP'}, None)
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)

    def test_offline_identify_and_patch_use_audited_backup_without_closing_fn(self):
        from a9tool import native_deployment_ui
        folder = str(self.session_root/'complete-backup')
        audit = dict(backup_valid=True, identified=True, patched=True, session=folder)
        handle = mock.Mock()
        self.app.handle = handle
        with mock.patch.object(native_deployment_ui, 'inspect_r15_session', return_value=audit), \
                mock.patch.object(native_deployment_ui, 'execute_native', return_value={
                    'session': folder, 'state': 'PATCHED_READY'}) as execute:
            self.app.r15_work_var.set(folder)
            self.wait_audit()
            for action in ('r15.identify', 'r15.patch'):
                self.app.on_native_deployment(action)
                self.wait()
                self.assertEqual(execute.call_args.args[:2], (action, {
                    'session_root': str(self.session_root), 'source': folder}))
        handle.close.assert_not_called()

    def test_successful_rollback_keeps_the_original_rollback_source(self):
        original = str(self.session_root/'original')
        self.app.native_source_vars['r15'].set(original)
        self.app._native_deployment_done('r15.rollback', {
            'session': str(self.session_root/'rollback-current-preimage'), 'rollback_available': True}, None)
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)

    def test_v8_install_is_direct_and_backend_checks_the_prerequisite(self):
        from a9tool import native_deployment_ui
        with mock.patch.object(native_deployment_ui.messagebox, 'askyesno', return_value=True), \
                mock.patch.object(native_deployment_ui, 'execute_native', return_value={'state': 'DONE'}) as execute:
            self.app.on_native_deployment('v8.install')
            self.wait()
        self.assertEqual(execute.call_args.args[:2], ('v8.install', {'session_root': str(self.session_root)}))

    def test_recovery_uses_its_own_original_source_and_explicit_flag(self):
        from a9tool import native_deployment_ui
        self.app.native_source_vars['r15'].set(str(self.session_root/'r15-original'))
        self.app.native_source_vars['v8'].set(str(self.session_root/'v8-original'))
        with mock.patch.object(native_deployment_ui.messagebox, 'askyesno', return_value=True), \
                mock.patch.object(native_deployment_ui, 'execute_native', return_value={'state': 'RESTORED'}) as execute:
            self.app.on_native_deployment('v8.recover')
            self.wait()
        self.assertEqual(execute.call_args.args[:2], ('v8.rollback', {
            'session_root': str(self.session_root),
            'source': str(self.session_root/'v8-original'), 'recover': True}))

    def test_error_changes_rollback_source_only_when_complete_material_is_reported(self):
        from a9tool import native_deployment_ui
        original = str(self.session_root/'complete-original')
        self.app.native_source_vars['r15'].set(original)
        error = RuntimeError('partial capture')
        error.failure_session = str(self.session_root/'partial')
        with mock.patch.object(native_deployment_ui, 'execute_native', side_effect=error):
            self.app.on_native_deployment('r15.backup')
            self.wait()
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)
        error.session = str(self.session_root/'complete-preimage')
        with mock.patch.object(native_deployment_ui, 'execute_native', side_effect=error):
            self.app.on_native_deployment('r15.backup')
            self.wait()
        self.assertEqual(self.app.native_source_vars['r15'].get(), original)
        self.app._native_deployment_done('r15.install', None, error)
        self.assertEqual(self.app.native_source_vars['r15'].get(), error.session)

    def test_busy_disables_old_and_new_controls_and_close_waits(self):
        self.app._set_busy(True)
        for button in (self.app.connect_btn, self.app.flash_status_btn, self.app.wifi_status_btn,
                       self.app.reset_status_btn, *self.app.native_buttons.values()):
            self.assertEqual(str(button['state']), 'disabled')
        self.app.on_close()
        self.assertTrue(self.root.winfo_exists())
        self.app._set_busy(False)
        for button in (self.app.connect_btn, self.app.flash_status_btn, self.app.wifi_status_btn,
                       self.app.reset_status_btn, self.app.native_buttons['r15.backup'],
                       self.app.native_buttons['v8.status']):
            self.assertEqual(str(button['state']), 'normal')

    def test_embedded_help_works_without_connecting(self):
        self.app.show_native_help()
        window = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
        viewer = next(child for child in window.winfo_children() if isinstance(child, tk.Text))
        self.assertGreater(len(viewer.get('1.0', 'end').strip()), 500)
        self.assertEqual(str(viewer['state']), 'disabled')
        self.assertIsNone(self.app.handle)
        window.destroy()
