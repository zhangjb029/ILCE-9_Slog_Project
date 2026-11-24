"""R15NH and V8 presentation for the released native USB application."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import data, errors, journal, deployment_status
from . import __version__


ROWS = {
    'r15': (
        ('r15.backup', '① 初始备份（完整分区及配套配置）'),
        ('r15.identify', '② 识别备份版本（离线）'),
        ('r15.patch', '③ 从备份修补 R15NH（离线）'),
        ('r15.install', '④ 写入 R15NH 整分区'),
        ('r15.rollback', '⑥ 从原始会话回退 R15NH'),
        ('r15.status', '辅助：读取机身 R15NH 状态（只读）'),
        ('r15.check', '辅助：检查内置差分补丁（离线）')),
    'v8': (
        ('v8.check', '① 检查内置 V8（离线）'),
        ('v8.status', '② 读取 V8 与 R15NH 状态'),
        ('v8.install', '③ 部署 V8（须先有 R15NH）'),
        ('v8.rollback', '④ 从原始会话回退 V8'),
        ('v8.recover', '恢复 V8 中断事务')),
}
WRITE_ACTIONS = {'r15.install', 'r15.rollback', 'v8.install', 'v8.rollback', 'v8.recover'}
OFFLINE_ACTIONS = {'r15.check', 'r15.identify', 'r15.patch', 'v8.check'}


def execute_native(action, arguments, progress):
    """Use the native backends; no host transport or WSL process is involved."""
    if action.startswith('r15.'):
        from . import r15nh_deploy
        return r15nh_deploy.execute(action, arguments, progress)
    if action.startswith('v8.'):
        from . import v8_deploy
        return v8_deploy.execute(action, arguments, progress)
    raise ValueError('Unknown native deployment action')


def inspect_r15_session(source):
    """Authenticate local backup and preparation evidence outside the Tk thread."""
    from . import r15nh_deploy
    return r15nh_deploy.inspect_session(source)


class NativeDeploymentMixin:
    def _build_native_lut_tab(self, parent):
        self.menu_root = journal.sessions_root() / 'menu'
        self.native_buttons = {}
        self.native_inputs = []
        self.native_source_vars = {name: tk.StringVar() for name in ROWS}
        self.native_status_vars = {name: tk.StringVar(value='尚未执行；默认使用内置且摘要固定的发布资源。') for name in ROWS}
        self.native_device_status_vars = {
            'r15': tk.StringVar(value='R15NH：尚未读取机身状态。'),
            'v8': tk.StringVar(value='R15NH / V8：尚未读取机身状态。')}
        self.r15_work_var = tk.StringVar()
        self.r15_audit = {}
        self.r15_audit_source = ''
        self.r15_audit_pending = False
        self._r15_audit_generation = 0
        self._r15_audit_timer = None
        self._r15_setting_work = False
        self._build_native_page(parent, 'r15')
        self.r15_work_var.trace_add('write', self.audit_r15_work)

    def _build_native_v8_tab(self, parent):
        self._build_native_page(parent, 'v8')

    def _build_native_page(self, parent, module):
        is_lut = module == 'r15'
        device = ttk.LabelFrame(parent, text='当前机身状态（最近一次读取）')
        device.pack(fill='x', padx=10, pady=8)
        ttk.Label(device, textvariable=self.native_device_status_vars[module], wraplength=740,
                  justify='left').pack(anchor='w', padx=10, pady=8)
        intro = ttk.LabelFrame(parent, text='使用前必读')
        intro.pack(fill='x', padx=10, pady=8)
        text = (
            'R15NH：27 款内置 LUT、16 个自定义槽位及 NAME / HELP。\n'
            '沿用 R12 六步：完整备份 → 识别 → 从备份离线修补 → 写入 → 4:3 参数 → 回退。\n'
            '只内置差分补丁，不分发完整镜像；通过 FF01 读写完整 nflasha15（300 MiB）。\n'
            '支持已完整识别的原厂 / R8 / R9 / R9.1 / R10 / R11 / R12，未知或混合来源拒绝；四 CFG、两 LUT 配置原样保留。'
            if is_lut else
            '先安装 R15NH → 冷重启 → 读取状态核对 → 单独部署 V8。后端在每次部署前重新检查 R15NH。\n'
            'V8 使用 nflasha10 的 /etc、/tmp，先写载荷并回读，最后切换 preload。\n'
            '回退只恢复原 preload，保留载荷；中断恢复需先读现场、核对原会话并明确确认。')
        ttk.Label(intro, text=text, wraplength=740, justify='left').pack(anchor='w', padx=10, pady=8)
        help_button = ttk.Button(intro, text='完整操作说明（内置）', command=self.show_native_help)
        help_button.pack(anchor='w', padx=10, pady=(0, 8))
        self.native_inputs.append(help_button)
        operations = ttk.LabelFrame(parent, text='原生 USB 部署与恢复')
        operations.pack(fill='x', padx=10, pady=8)
        ttk.Label(operations, textvariable=self.native_status_vars[module], wraplength=740,
                  justify='left').pack(anchor='w', padx=10, pady=8)
        if is_lut:
            ttk.Label(operations, text='当前工作备份 / 修补会话（选择后后台审核证据）').pack(anchor='w', padx=10)
            row = ttk.Frame(operations)
            row.pack(fill='x', padx=10, pady=8)
            entry = ttk.Entry(row, textvariable=self.r15_work_var)
            entry.pack(side='left', fill='x', expand=True)
            choose = ttk.Button(row, text='选择已有备份…', command=self._choose_r15_work)
            choose.pack(side='left', padx=(8, 0))
            self.native_inputs.extend((entry, choose))
        for action, label in ROWS[module]:
            if action == 'r15.rollback':
                self.aspect_btn = ttk.Button(operations, text='⑤ 写入 4:3 保存参数（原有功能）', command=self.on_menu_aspect)
                self.aspect_btn.pack(anchor='w', padx=10, pady=4)
                self.native_inputs.append(self.aspect_btn)
            button = ttk.Button(operations, text=label, command=lambda name=action: self.on_native_deployment(name))
            button.pack(anchor='w', padx=10, pady=4)
            self.native_buttons[action] = button
        restore = ttk.LabelFrame(parent, text='同机原始回滚来源（两个模块分别保存）')
        restore.pack(fill='x', padx=10, pady=8)
        ttk.Label(restore, text=('R15NH 使用完整分区备份及配套配置会话；已安装 V8 时先回退 V8，再回退 R15NH。'
                              if is_lut else '选择原始 V8 部署会话；状态读取会话不能代替部署备份。'),
                  wraplength=740).pack(anchor='w', padx=10, pady=8)
        row = ttk.Frame(restore)
        row.pack(fill='x', padx=10, pady=(0, 10))
        entry = ttk.Entry(row, textvariable=self.native_source_vars[module])
        entry.pack(side='left', fill='x', expand=True)
        choose = ttk.Button(row, text='选择会话…', command=lambda: self._choose_native_source(module))
        choose.pack(side='left', padx=(8, 0))
        self.native_inputs.extend((entry, choose))
        self.native_source_vars[module].trace_add('write', lambda *unused: self._refresh_native_deployment())

    def _choose_native_source(self, module):
        value = filedialog.askdirectory(parent=self.root, title='选择同机原始会话',
                                        initialdir=str(journal.sessions_root()))
        if value:
            self.native_source_vars[module].set(value)

    def _choose_r15_work(self):
        value = filedialog.askdirectory(parent=self.root, title='选择完整 R15NH 工作备份会话',
                                        initialdir=str(journal.sessions_root()))
        if value:
            self.r15_work_var.set(value)

    def audit_r15_work(self, *unused):
        if self._r15_setting_work:
            return
        self._r15_audit_generation += 1
        generation = self._r15_audit_generation
        if self._r15_audit_timer is not None:
            self.root.after_cancel(self._r15_audit_timer)
            self._r15_audit_timer = None
        self.r15_audit = {}
        self.r15_audit_source = ''
        source = self.r15_work_var.get().strip()
        self.r15_audit_pending = bool(source and Path(source).is_absolute())
        self._refresh_native_deployment()
        if not self.r15_audit_pending:
            self.native_status_vars['r15'].set('先初始备份，或选择完整会话；识别、修补和写入需要本地证据通过审核。')
            return
        self.native_status_vars['r15'].set('正在后台审核完整备份及 identified / prepared 证据；暂不允许后续步骤。')
        def start():
            self._r15_audit_timer = None
            self._background(lambda: inspect_r15_session(source),
                             lambda value, error: self._r15_audited(generation, source, value, error))
        self._r15_audit_timer = self.root.after(100, start)

    def _r15_audited(self, generation, source, value, error):
        if generation != self._r15_audit_generation or source != self.r15_work_var.get().strip():
            return
        audit = value if isinstance(value, dict) else {}
        if error is not None:
            audit = {'reason': str(error)}
        self.r15_audit_pending = False
        self.r15_audit = audit
        self.r15_audit_source = source
        valid = audit.get('backup_valid') is True
        if valid and not self.native_source_vars['r15'].get().strip():
            self.native_source_vars['r15'].set(source)
        if valid:
            self.native_status_vars['r15'].set('备份完整；识别：' + ('通过' if audit.get('identified') is True else '未完成')
                + '；修补：' + ('通过' if audit.get('patched') is True else '未完成')
                + '；来源：' + str(audit.get('source_label') or '待识别'))
        else:
            reason = str(audit.get('reason') or '未通过完整备份审核')
            self.native_status_vars['r15'].set('工作会话不可用：' + reason)
            self.log('R15NH 本地会话审核：' + reason)
        self._refresh_native_deployment()

    def _r15_use_work_result(self, source, audit=None):
        if audit is None:
            self.r15_work_var.set(source)
            return
        self._r15_audit_generation += 1
        if self._r15_audit_timer is not None:
            self.root.after_cancel(self._r15_audit_timer)
            self._r15_audit_timer = None
        self._r15_setting_work = True
        try:
            self.r15_work_var.set(source)
        finally:
            self._r15_setting_work = False
        self._r15_audited(self._r15_audit_generation, source, audit, None)

    def _native_action_allowed(self, action):
        if self.busy:
            return False
        module, operation = action.split('.')
        if operation in ('rollback', 'recover'):
            return bool(self.native_source_vars[module].get().strip())
        if module == 'r15' and operation in ('identify', 'patch', 'install'):
            source = self.r15_work_var.get().strip()
            if self.r15_audit_pending or not source or source != self.r15_audit_source:
                return False
            if self.r15_audit.get('backup_valid') is not True:
                return False
            if operation in ('patch', 'install') and self.r15_audit.get('identified') is not True:
                return False
            return operation != 'install' or self.r15_audit.get('patched') is True
        return True

    def _refresh_native_deployment(self):
        if not hasattr(self, 'native_buttons'):
            return
        for action, button in self.native_buttons.items():
            button.configure(state='normal' if self._native_action_allowed(action) else 'disabled')
        for widget in self.native_inputs:
            widget.configure(state='disabled' if self.busy else 'normal')

    def on_native_deployment(self, action):
        if self.busy:
            return
        if action not in self.native_buttons:
            raise ValueError('Unknown native deployment action')
        if not self._native_action_allowed(action):
            self.log('请按初始备份 → 识别 → 离线修补 → 写入顺序执行，或先选择原始回滚会话。')
            return
        module, operation = action.split('.')
        arguments = {'session_root': str(journal.sessions_root().resolve())}
        if module == 'r15' and operation in ('identify', 'patch', 'install'):
            arguments['source'] = self.r15_work_var.get().strip()
        if operation in ('rollback', 'recover'):
            source = self.native_source_vars[module].get().strip()
            if not source or not Path(source).is_absolute():
                self.log('请先选择同机、对应模块的原始会话绝对路径。')
                return
            arguments['source'] = source
        if action in WRITE_ACTIONS:
            detail = {
                'r15.install': '将使用已识别备份离线修补生成的候选；先核验本地候选，再读取现场比对，通过 FF01 写入完整 nflasha15（300 MiB）并完整回读。写入按钮不会现场自动生成目标。完成后冷重启。',
                'r15.rollback': '将写回所选同机完整分区及配套配置。若已部署 V8，先回退 V8。恢复的是备份时状态。',
                'v8.install': '必须先部署 R15NH、冷重启并核对。后端重新检查 R15NH 后才写载荷，最后切换 preload。',
                'v8.rollback': '将恢复所选同机原始 V8 会话的 preload；保留已部署载荷，不删除载荷或恢复其他原文件。',
                'v8.recover': '仅用于 V8 安装或回退中断后的原 preload 恢复。先读现场、核对会话；恢复原备份可能覆盖之后的 preload 修改。',
            }[action]
            if not messagebox.askyesno('确认机身写入', detail + '\n\n结果未知时不自动重发。确定继续？',
                                      parent=self.root, default='no'):
                return
        if operation == 'recover':
            request = 'v8.rollback'
            arguments['recover'] = True
        else:
            request = action
        if action not in OFFLINE_ACTIONS:
            self._close_main_handle()
            self.native_device_status_vars['r15'].set('R15NH：本次操作后需读取状态确认。')
            self.native_device_status_vars['v8'].set('V8：本次操作后需读取状态确认。')
            self.native_device_status_vars[module].set('正在读取机身或执行操作，当前状态尚未确认。')
        self._set_busy(True)
        self.native_status_vars[module].set('正在执行 ' + action)
        self.log(('离线操作：' if action in OFFLINE_ACTIONS else '原生 USB 操作：') + action + '；会话目录：' + arguments['session_root'])
        progress = lambda message: self._post(self.log, str(message))
        def work():
            result = execute_native(request, arguments, progress)
            if action in ('r15.backup', 'r15.identify', 'r15.patch') and isinstance(result, dict):
                source = str(result.get('session') or arguments.get('source') or '')
                try:
                    audit = inspect_r15_session(source)
                except Exception as error:
                    audit = {'reason': str(error)}
                result = dict(result, _ui_session_audit=audit)
            return result
        self._background(work,
                         lambda result, error: self._native_deployment_done(action, result, error))

    def _native_deployment_done(self, action, result, error):
        module = action.split('.')[0]
        if error is not None:
            if action not in OFFLINE_ACTIONS:
                self.native_device_status_vars[module].set(
                    ('R15NH' if module == 'r15' else 'V8') + '：操作失败，当前状态无法确认；原因：' + str(error))
            source = getattr(error, 'session', None)
            if source and (action in ('r15.install', 'r15.rollback', 'v8.install', 'v8.rollback', 'v8.recover')
                           or not self.native_source_vars[module].get().strip()):
                self.native_source_vars[module].set(str(source))
                self.log('可恢复的原始会话：' + str(source))
            failure = getattr(error, 'failure_session', None)
            if failure:
                self.log('失败记录（保留全部完整或部分材料）：' + str(failure))
            self.native_status_vars[module].set('失败；先核对现场及原始记录，不直接重发写入。')
            self.log(errors.user_message(error))
        else:
            result = dict(result) if isinstance(result, dict) else {'result': str(result)}
            if action in ('r15.status', 'r15.backup'):
                record = result.get('r15') or dict(label=result.get('source_label'),
                    state='current' if result.get('r15nh_current') else 'unknown',
                    state_validated=result.get('r15nh_current') is True)
                self.native_device_status_vars['r15'].set(deployment_status.r15_text(record))
            elif action == 'v8.status':
                self.native_device_status_vars['v8'].set(deployment_status.v8_text(result))
                self.native_device_status_vars['r15'].set(deployment_status.r15_text(result.get('r15')))
            elif action in WRITE_ACTIONS:
                name = 'R15NH' if module == 'r15' else 'V8'
                detail = '写入与回读通过' if action.endswith('.install') else '已恢复所选备份入口或分区'
                self.native_device_status_vars[module].set(name + '：' + detail + '；请冷重启后重新读取确认。')
            audit = result.pop('_ui_session_audit', None)
            self.log(json.dumps(result, ensure_ascii=False, indent=2, default=str))
            source = result.get('session')
            preserve_empty_capture = (action == 'r15.backup'
                                      and not self.native_source_vars[module].get().strip()
                                      and result.get('rollback_available'))
            existing = self.native_source_vars[module].get().strip()
            current_r15 = (result.get('source_label') or self.r15_audit.get('source_label')) == 'R15 NAME HELP'
            if action == 'v8.install' and result.get('deactivation_requires_original_session'):
                self.log('本次会话不能卸载，需最初安装会话；保留已有原始回滚来源。')
            elif action == 'r15.install' and existing and current_r15:
                self.log('本次来源已是 R15NH；保留此前原始备份用于回退，不改为重装快照。')
            elif action == 'r15.install':
                original = result.get('source') or self.r15_work_var.get().strip() or source
                if original:
                    self.native_source_vars[module].set(str(original))
            elif source and (action == 'v8.install' or preserve_empty_capture):
                self.native_source_vars[module].set(str(source))
            self.native_status_vars[module].set('结果：' + str(result.get('state', '见日志')))
            if action in ('r15.backup', 'r15.identify', 'r15.patch') and source:
                self._r15_use_work_result(str(source), audit)
            if result.get('requires_cold_restart'):
                self.log('请正常关机、完整断电、冷启动，再读状态并验证实际菜单与拍摄；回读通过不等于实机功能验收。')
        self._set_busy(False)

    def show_native_help(self):
        try:
            content = (data.data_root() / 'help' / 'operations.md').read_text(encoding='utf-8')
        except (OSError, UnicodeError) as error:
            self.log('无法打开内置操作说明：' + str(error))
            return
        window = tk.Toplevel(self.root)
        window.title(f'ILCE-9 v{__version__} · 内置操作说明')
        window.geometry('850x650')
        window.minsize(650, 420)
        viewer = tk.Text(window, wrap='word', padx=16, pady=12)
        scrollbar = ttk.Scrollbar(window, orient='vertical', command=viewer.yview)
        viewer.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        viewer.pack(side='left', fill='both', expand=True)
        viewer.insert('1.0', content)
        viewer.configure(state='disabled')
