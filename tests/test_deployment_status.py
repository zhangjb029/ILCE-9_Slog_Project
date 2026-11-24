import unittest
from a9tool import deployment_status as status


class DeploymentStatusTests(unittest.TestCase):
    def test_r15_distinguishes_stock_legacy_and_installed(self):
        self.assertIn('原厂 6.00', status.r15_text(dict(state='stock', label='stock')))
        self.assertIn('未安装；当前版本 R12', status.r15_text(dict(state='legacy', label='R12')))
        text = status.r15_text(dict(state='current', label='R15 NAME HELP', state_validated=True))
        self.assertIn('R15NH：已安装', text)
        self.assertIn('未验证', text)

    def test_bad_r15_records_are_not_reported_as_uninstalled_or_current(self):
        text = status.r15_text(dict(state='conflict', label='R15 NAME HELP', reason='bad CRC'))
        self.assertIn('校验冲突', text)
        self.assertIn('bad CRC', text)
        self.assertNotIn('已安装', text)

    def test_v8_installed_and_dependency_are_explicit(self):
        text = status.v8_text(dict(r15nh_current=True,
            r15=dict(state='current', label='R15 NAME HELP', state_validated=True),
            menu=dict(state='current', label='V8', payload_state='complete',
                      payloads_present=3, payloads_expected=3, preload_state='v8', installable=True)))
        self.assertIn('R15NH：已安装', text)
        self.assertIn('V8：已部署', text)
        self.assertIn('3/3', text)
        self.assertIn('入口已启用', text)
        self.assertIn('运行生效未验证', text)

    def test_inactive_v8_files_are_not_called_absent(self):
        text = status.v8_text(dict(r15nh_current=False, r15=dict(state='legacy', label='R12'),
            menu=dict(state='stock', payload_state='complete', payloads_present=3,
                      payloads_expected=3, preload_state='inactive', installable=True)))
        self.assertIn('文件完整', text)
        self.assertIn('入口未启用', text)
        self.assertIn('暂不允许部署 V8', text)

    def test_incomplete_and_conflicting_v8_are_explicit(self):
        for menu, wanted in (
            (dict(state='partial', payload_state='partial', payloads_present=1,
                  payloads_expected=3, preload_state='v8'), '部署不完整'),
            (dict(state='conflict', reason='payload changed', payload_state='different'), '校验冲突'),
            (dict(state='stock', payload_state='absent', payloads_present=0,
                  payloads_expected=3, preload_state='inactive'), '未部署'),
        ):
            with self.subTest(wanted=wanted):
                self.assertIn(wanted, status.v8_text(dict(menu=menu, r15nh_current=False)))

    def test_older_menu_version_is_named(self):
        text = status.v8_text(dict(r15nh_current=True,
            menu=dict(state='legacy', label='V7.1', payload_state='absent', preload_state='v71')))
        self.assertIn('当前悬浮菜单为 V7.1', text)
