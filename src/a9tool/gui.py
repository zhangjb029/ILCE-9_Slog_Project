"""Single-window GUI. Camera work runs in a worker thread; the UI never blocks.

The window is deliberately linear: connect, look at what was detected, pick a
function, and if something went wrong, put it back. There is no settings page
and no menu bar, because the people this is for should not have to configure
anything. Write buttons disable permanently after one successful write — one
run of the program does exactly one transaction.
"""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import (aspect_params, core, data, errors, flash_av, flash_baseline, flash_service,
               fnmap, journal, menu_deploy, usbdev)

PICTURE_PROFILE = 0x3A
SLOG_DISPLAY_ASSIST = 0x36

STATUS_MARKS = {
    fnmap.STATUS_VERIFIED: '✅ 已验证',
    fnmap.STATUS_UNTESTED: '⬜ 未验证',
    fnmap.STATUS_KNOWN_BAD: '⛔ 已知会出问题',
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title('ILCE-9 功能槽位工具')
        self.root.geometry('820x780')
        self.root.minsize(760, 640)
        self.queue: queue.Queue = queue.Queue()
        self.handle = None
        self.state = None
        self.busy = False
        self.locked = False
        self.selected_session = None
        self._build()
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.root.after(100, self._drain)
        self.log('尚未连接相机。请用 USB 线连接相机，把 USB 连接模式设为「大容量存储」，然后点「连接并检查」。')

    # -- plumbing ---------------------------------------------------------
    def log(self, message: str) -> None:
        self.log_box.configure(state='normal')
        self.log_box.insert('end', message + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def _post(self, callback, *args) -> None:
        self.queue.put((callback, args))

    def _drain(self) -> None:
        while True:
            try:
                callback, args = self.queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
        self.root.after(100, self._drain)

    def _background(self, work, done) -> None:
        def run():
            try:
                result = work()
            except BaseException as error:  # reported to the user, never swallowed
                self._post(done, None, error)
            else:
                self._post(done, result, None)
        threading.Thread(target=run, daemon=True).start()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self._refresh()

    def on_close(self) -> None:
        if self.handle is not None:
            self.handle.close()
        self.root.destroy()

    # -- layout -----------------------------------------------------------
    def _build(self) -> None:
        pad = dict(padx=10, pady=6)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=(8, 0))
        self.tab_fn = ttk.Frame(self.notebook)
        self.tab_flash = ttk.Frame(self.notebook)
        self.tab_menu = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_fn, text='Fn 功能')
        self.notebook.add(self.tab_flash, text='电子快门引闪')
        self.notebook.add(self.tab_menu, text='菜单移植与创意外观')

        connect = ttk.LabelFrame(self.tab_fn, text='① 连接相机')
        connect.pack(fill='x', **pad)
        ttk.Label(connect, text='相机 USB 连接模式设为「大容量存储」，只连这一台相机。').pack(anchor='w', padx=10, pady=(8, 4))
        row = ttk.Frame(connect)
        row.pack(anchor='w', padx=10, pady=(0, 10))
        self.connect_btn = ttk.Button(row, text='连接并检查', command=self.on_connect)
        self.connect_btn.pack(side='left')
        self.retry_btn = ttk.Button(row, text='重试', command=self.on_connect)
        self.retry_btn.pack(side='left', padx=8)
        self.retry_btn.pack_forget()

        status = ttk.LabelFrame(self.tab_fn, text='② 检测结果')
        status.pack(fill='x', **pad)
        self.status_var = tk.StringVar(value='尚未连接')
        self.override_var = tk.StringVar(value='')
        ttk.Label(status, textvariable=self.status_var, justify='left').pack(anchor='w', padx=10, pady=(8, 2))
        ttk.Label(status, textvariable=self.override_var, justify='left').pack(anchor='w', padx=10)
        self.override_btn = ttk.Button(status, text='开启 PP 放行', command=self.on_enable_override)
        self.override_btn.pack(anchor='w', padx=10, pady=(6, 10))

        cards = ttk.LabelFrame(self.tab_fn, text='③ 选择功能')
        cards.pack(fill='x', **pad)
        row = ttk.Frame(cards)
        row.pack(fill='x', padx=10, pady=(8, 4))
        self.card_buttons = []
        self._build_card(row, 'Picture Profile', '图片配置文件', PICTURE_PROFILE, 'Fn1')
        self._build_card(row, 'SLog 显示辅助', 'S-Log 显示辅助', SLOG_DISPLAY_ASSIST, 'Fn7')

        self.all_open = False
        self.all_btn = ttk.Button(cards, text='▸ 全部功能（77 项，多数未验证）', command=self.on_toggle_all)
        self.all_btn.pack(anchor='w', padx=10, pady=(4, 4))
        self.all_frame = ttk.Frame(cards)
        self._build_all_list(self.all_frame)
        self.all_row = ttk.Frame(cards)
        self.all_value_var = tk.StringVar()
        self.all_slot_var = tk.StringVar(value='Fn12')
        self.all_name_var = tk.StringVar(value='未选择')
        ttk.Label(self.all_row, textvariable=self.all_name_var).pack(side='left', padx=(0, 10))
        ttk.Combobox(self.all_row, textvariable=self.all_slot_var, width=6, state='readonly',
                     values=[fnmap.slot_label(n) for n in sorted(fnmap.FN_SLOTS)]).pack(side='left')
        self.all_write_btn = ttk.Button(self.all_row, text='写入所选功能', command=self.on_write_selected)
        self.all_write_btn.pack(side='left', padx=8)
        self.all_row.pack(anchor='w', padx=10, pady=(0, 10))
        self.all_row.pack_forget()

        restore = ttk.LabelFrame(self.tab_fn, text='④ 恢复')
        restore.pack(fill='both', expand=False, **pad)
        self.sessions_tree = ttk.Treeview(restore, columns=('time', 'what', 'note'), show='headings', height=4)
        for column, title, width in (('time', '时间', 150), ('what', '做了什么', 320), ('note', '备注', 240)):
            self.sessions_tree.heading(column, text=title)
            self.sessions_tree.column(column, width=width, anchor='w')
        self.sessions_tree.pack(fill='x', padx=10, pady=(8, 4))
        self.sessions_tree.bind('<<TreeviewSelect>>', self.on_session_selected)
        row = ttk.Frame(restore)
        row.pack(anchor='w', padx=10, pady=(0, 10))
        self.restore_btn = ttk.Button(row, text='从备份恢复到原状', command=self.on_restore)
        self.restore_btn.pack(side='left')
        self.baseline_btn = ttk.Button(row, text='恢复全部原厂', command=self.on_restore_baseline)
        self.baseline_btn.pack(side='left', padx=8)
        self.refresh_btn = ttk.Button(row, text='刷新列表', command=self.reload_sessions)
        self.refresh_btn.pack(side='left')

        log_frame = ttk.LabelFrame(self.root, text='日志')
        log_frame.pack(fill='x', expand=False, padx=10, pady=6)
        self.log_box = tk.Text(log_frame, height=8, wrap='word', state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=10, pady=8)

        self._build_flash_tab(self.tab_flash)
        self._build_menu_tab(self.tab_menu)
        self.reload_sessions()
        self._refresh()

    def _build_card(self, parent, symbol: str, chinese: str, value: int, default_slot: str) -> None:
        card = ttk.LabelFrame(parent, text=symbol)
        card.pack(side='left', fill='both', expand=True, padx=(0, 10))
        ttk.Label(card, text=chinese).pack(anchor='w', padx=8, pady=(6, 2))
        ttk.Label(card, text=f'保存值 0x{value:02X} · {STATUS_MARKS[fnmap.status_of(value)]}').pack(anchor='w', padx=8)
        slot_var = tk.StringVar(value=default_slot)
        combo = ttk.Combobox(card, textvariable=slot_var, width=6, state='readonly',
                             values=[fnmap.slot_label(n) for n in sorted(fnmap.FN_SLOTS)])
        combo.pack(anchor='w', padx=8, pady=4)
        button = ttk.Button(card, text='写入', command=lambda: self.on_write(value, _slot_number(slot_var.get())))
        button.pack(anchor='w', padx=8, pady=(0, 8))
        self.card_buttons.append(button)

    def _build_all_list(self, parent) -> None:
        self.all_tree = ttk.Treeview(parent, columns=('name', 'symbol', 'value', 'status'),
                                     show='headings', height=8)
        for column, title, width in (('name', '名称', 220), ('symbol', '固件名', 200),
                                     ('value', '保存值', 80), ('status', '状态', 140)):
            self.all_tree.heading(column, text=title)
            self.all_tree.column(column, width=width, anchor='w')
        for item in fnmap.load_functions():
            self.all_tree.insert('', 'end', iid=str(item.value),
                                 values=(item.chinese, item.symbol, f'0x{item.value:02X}',
                                         STATUS_MARKS[item.status]))
        self.all_tree.bind('<<TreeviewSelect>>', self.on_all_selected)
        scroll = ttk.Scrollbar(parent, orient='vertical', command=self.all_tree.yview)
        self.all_tree.configure(yscrollcommand=scroll.set)
        self.all_tree.pack(side='left', fill='both', expand=True, padx=(10, 0), pady=(0, 6))
        scroll.pack(side='left', fill='y', pady=(0, 6))

    # -- state ------------------------------------------------------------
    def _refresh(self) -> None:
        connected = self.state is not None
        status = core.override_status(self.state) if connected else None
        writable = connected and not self.locked
        cards_on = writable and status == core.STATUS_ENABLED
        normal = lambda ok: 'normal' if ok else 'disabled'

        self.connect_btn.configure(state=normal(not self.busy and not self.locked))
        self.retry_btn.configure(state=normal(not self.busy and not self.locked))
        self.override_btn.configure(state=normal(writable and status == core.STATUS_DISABLED))
        for button in self.card_buttons:
            button.configure(state=normal(cards_on))
        self.all_btn.configure(state=normal(writable))
        self.all_write_btn.configure(state=normal(cards_on))
        self.restore_btn.configure(state=normal(writable and self.selected_session is not None))
        self.baseline_btn.configure(state=normal(writable))
        self.refresh_btn.configure(state=normal(not self.busy))
        self._refresh_flash()
        self._refresh_menu()

    def _show_status(self) -> None:
        identity = self.handle.identity
        self.status_var.set(
            f'机型：{identity["model"]}      固件：{identity["firmware"]}\n'
            f'序列号指纹：{identity["serial_sha256"][:8]}…（只用于确认是同一台相机）')
        status = core.override_status(self.state)
        if status == core.STATUS_ENABLED:
            self.override_var.set('PP 放行：✓ 已开启')
        elif status == core.STATUS_DISABLED:
            self.override_var.set('PP 放行：✗ 未开启 —— 请先点「开启 PP 放行」，然后重启相机')
        else:
            self.override_var.set('PP 放行：⚠ 状态异常 —— 请先用「恢复全部原厂」或从备份恢复')

    def _lock_after_write(self) -> None:
        self.locked = True
        self.state = None
        if self.handle is not None:
            self.handle.close()
            self.handle = None
        self._refresh()
        self.status_var.set('已写入。请关机重启相机，然后在相机上按 Fn 键确认。')
        self.override_var.set('要再改另一个功能，请关掉本窗口重新打开。')

    # -- actions ----------------------------------------------------------
    def on_connect(self) -> None:
        if self.busy or self.locked:
            return
        self._set_busy(True)
        self.log('正在连接相机…')

        def work():
            # Everything that can raise belongs in here: an exception on the Tk
            # thread would leave busy=True and every button disabled forever.
            receipt = usbdev.load_current_receipt()
            handle = usbdev.connect(receipt, progress=lambda message: self._post(self.log, message))
            state = core.read_state(handle.camera)
            core.save_baseline(state)
            return handle, state

        self._background(work, self._connected)

    def _connected(self, result, error) -> None:
        self._set_busy(False)
        if error is not None:
            self.log(errors.user_message(error))
            if 'Service device not found' in str(error):
                self.log('驱动装好后点「重试」，相机不要拔线。')
                self.retry_btn.pack(side='left', padx=8)
            return
        self.handle, self.state = result
        self.retry_btn.pack_forget()
        self._show_status()
        self.reload_sessions()
        self._refresh()
        self.log('已连接，机身信息已读取，原值已保存。')

    def on_enable_override(self) -> None:
        if self.busy or self.state is None:
            return
        if not messagebox.askyesno('开启 PP 放行',
                                   '这会修改相机的功能放行位，然后自动保存。\n'
                                   '保存后需要关机重启相机才生效。\n\n继续吗？'):
            return
        self._set_busy(True)
        state = self.state

        def work():
            return core.enable_override(self.handle.camera, state, journal.sessions_root(),
                                        progress=lambda message: self._post(self.log, message),
                                        identity=self.handle.identity)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                self.log(errors.user_message(error))
                return
            self.log(f'PP 放行已开启（{result.state}）。请关机重启相机。')
            self._lock_after_write()

        self._background(work, done)

    def on_write(self, value: int, slot: int) -> None:
        if self.state is None or self.locked:
            return
        name = next((item.chinese for item in fnmap.load_functions() if item.value == value), f'0x{value:02X}')
        if fnmap.status_of(value) == fnmap.STATUS_KNOWN_BAD:
            if not messagebox.askyesno('这个功能有已知问题', core.PIXEL_SHIFT_CONFIRMATION, default='no'):
                return
        elif not messagebox.askyesno('确认写入',
                                     f'把「{name}」写入 {fnmap.slot_label(slot)}？\n'
                                     '写入后需要关机重启相机才生效。\n\n'
                                     '写入前的原值会自动保存，可以恢复。'):
            return
        self._set_busy(True)
        state = self.state

        def work():
            return core.write_slot(self.handle.camera, state, slot, value, journal.sessions_root(),
                                   progress=lambda message: self._post(self.log, message),
                                   identity=self.handle.identity)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                self.log(errors.user_message(error))
                return
            self.log(f'已写入 {fnmap.slot_label(slot)} → {name}（{result.state}）。请关机重启相机。')
            self.log(f'原值备份：{result.directory}')
            self._lock_after_write()

        self._background(work, done)

    def on_toggle_all(self) -> None:
        self.all_open = not self.all_open
        if self.all_open:
            self.all_frame.pack(fill='x', padx=10, pady=(0, 4))
            self.all_row.pack(anchor='w', padx=10, pady=(0, 10))
            self.all_btn.configure(text='▾ 全部功能（77 项，多数未验证）')
        else:
            self.all_frame.pack_forget()
            self.all_row.pack_forget()
            self.all_btn.configure(text='▸ 全部功能（77 项，多数未验证）')

    def on_all_selected(self, _event=None) -> None:
        selection = self.all_tree.selection()
        if not selection:
            return
        item = next(i for i in fnmap.load_functions() if i.value == int(selection[0]))
        self.all_name_var.set(f'已选：{item.chinese}（0x{item.value:02X}，{STATUS_MARKS[item.status]}）')

    def on_write_selected(self) -> None:
        selection = self.all_tree.selection()
        if not selection:
            messagebox.showinfo('还没有选择', '请先在列表里点一个功能。')
            return
        self.on_write(int(selection[0]), _slot_number(self.all_slot_var.get()))

    def on_session_selected(self, _event=None) -> None:
        selection = self.sessions_tree.selection()
        self.selected_session = self._session_by_iid(selection[0]) if selection else None
        self._refresh()

    def _session_by_iid(self, iid):
        for session in self._sessions:
            if session.directory.name == iid:
                return session
        return None

    def reload_sessions(self) -> None:
        self._sessions = journal.list_sessions(journal.sessions_root())
        self.sessions_tree.delete(*self.sessions_tree.get_children())
        for session in self._sessions:
            note = '原值来自上一次写入，不是出厂状态' if journal.mark_chained(session) else ''
            self.sessions_tree.insert('', 'end', iid=session.directory.name,
                                      values=(session.created.replace('T', ' ')[:19],
                                              _describe(session), note))
        self.selected_session = None

    def on_restore(self) -> None:
        if self.state is None or self.selected_session is None or self.locked:
            return
        session = self.selected_session
        if not messagebox.askyesno('恢复', f'把这一次改动恢复回去？\n\n{_describe(session)}\n\n继续吗？'):
            return
        self._set_busy(True)
        state = self.state

        def work():
            return core.restore_session(self.handle.camera, session, journal.sessions_root(),
                                        progress=lambda message: self._post(self.log, message),
                                        identity=self.handle.identity)

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                self.log(errors.user_message(error))
                return
            self.log(f'已恢复（{result.state}）。请关机重启相机。')
            self._lock_after_write()

        self._background(work, done)

    def on_restore_baseline(self) -> None:
        if self.state is None or self.locked:
            return
        if not messagebox.askyesno('恢复全部原厂',
                                   '会把本工具改过的所有位置都恢复到第一次使用之前。\n'
                                   '你在相机上手动改过的设置也会被覆盖。\n\n继续吗？'):
            return
        self._set_busy(True)
        state = self.state

        def work():
            return core.restore_baseline(self.handle.camera, journal.sessions_root(),
                                         progress=lambda message: self._post(self.log, message))

        def done(result, error):
            self._set_busy(False)
            if error is not None:
                self.log(errors.user_message(error))
                return
            self.log(f'已恢复到第一次使用前的状态（{result.state}）。请关机重启相机。')
            self._lock_after_write()

        self._background(work, done)


    # -- electronic-shutter flash tab -------------------------------------
    def _build_flash_tab(self, parent) -> None:
        self.flash_menu_value = None
        self.flash_av_value = None

        warn = ttk.LabelFrame(parent, text='使用前必读')
        warn.pack(fill='x', padx=10, pady=8)
        ttk.Label(warn, justify='left', wraplength=720, text=(
            '开启电子快门引闪要改两处配置，分两次写入，每次写完都要关机重启。\n'
            '· 两项都开启后，电子快门单张可以引闪（已确认）。\n'
            '· 电子快门连拍仍只有第一张引闪，尚未解决。\n'
            '· 快于 1/160 s 的照片有黑边，慢于它（如 1/125 s）可用。\n'
            '· 硬件安全、TTL 精度、HSS、无线引闪均未验证。\n'
            '操作前务必在相机和闪光灯都关机时拆下热靴附件。'
        )).pack(anchor='w', padx=10, pady=8)

        state = ttk.LabelFrame(parent, text='当前配置')
        state.pack(fill='x', padx=10, pady=8)
        self.flash_menu_var = tk.StringVar(value='上层索引 45：未读取')
        self.flash_av_var = tk.StringVar(value='AV 偏移 AD：未读取')
        ttk.Label(state, textvariable=self.flash_menu_var).pack(anchor='w', padx=10, pady=(8, 2))
        ttk.Label(state, textvariable=self.flash_av_var).pack(anchor='w', padx=10, pady=(0, 6))
        self.flash_status_btn = ttk.Button(state, text='连接并读取状态', command=self.on_flash_status)
        self.flash_status_btn.pack(anchor='w', padx=10, pady=(0, 10))

        steps = ttk.LabelFrame(parent, text='分两步开放')
        steps.pack(fill='x', padx=10, pady=8)
        ttk.Label(steps, justify='left', wraplength=720, text=(
            '① 上层规则：单独开放只让菜单恢复可选，不会引闪。\n'
            '② AV 资格：要求 ① 已完成，并且重启过相机。'
        )).pack(anchor='w', padx=10, pady=(8, 6))
        row = ttk.Frame(steps)
        row.pack(anchor='w', padx=10, pady=(0, 10))
        self.flash_menu_btn = ttk.Button(row, text='① 开放上层规则（45：1 → 0）',
                                         command=self.on_flash_menu_apply)
        self.flash_menu_btn.pack(side='left')
        self.flash_av_btn = ttk.Button(row, text='② 开放 AV 资格（AD：0 → 1）',
                                       command=self.on_flash_av_apply)
        self.flash_av_btn.pack(side='left', padx=8)

        restore = ttk.LabelFrame(parent, text='恢复')
        restore.pack(fill='x', padx=10, pady=8)
        self.flash_baseline = flash_baseline.load()
        self.flash_restore_var = tk.StringVar()
        ttk.Label(restore, textvariable=self.flash_restore_var, wraplength=720,
                  justify='left').pack(anchor='w', padx=10, pady=(8, 4))
        self.flash_restore_btn = ttk.Button(restore, text='恢复到初始备份',
                                            command=self.on_flash_restore)
        self.flash_restore_btn.pack(anchor='w', padx=10, pady=(0, 10))
        self._update_flash_baseline_text()

    def _update_flash_baseline_text(self) -> None:
        baseline = self.flash_baseline
        if baseline is None:
            self.flash_restore_var.set(
                '初始备份：尚未保存。\n'
                '第一次写入之前必须点「连接并读取状态」，那一步会把当前两项值存成初始备份；'
                '没有初始备份时，下面的写入按钮是灰的。')
            return
        record = baseline['record']
        self.flash_restore_var.set(
            f'初始备份：{record["created"]} 保存 —— 上层索引 45 = {record["menu_value"]}，'
            f'AV 偏移 AD = {record["av_value"]}。\n'
            '「恢复到初始备份」会把两项都写回这组值。')

    def _refresh_flash(self) -> None:
        def normal(ok):
            return 'normal' if ok else 'disabled'

        busy = self.busy
        menu, av = self.flash_menu_value, self.flash_av_value
        has_baseline = self.flash_baseline is not None
        self.flash_status_btn.configure(state=normal(not busy))
        self.flash_menu_btn.configure(state=normal(not busy and has_baseline and menu == 1))
        self.flash_av_btn.configure(state=normal(not busy and has_baseline and menu == 0 and av == 0))
        self.flash_restore_btn.configure(state=normal(not busy and has_baseline))

    def _close_main_handle(self) -> None:
        """Both flash guards forbid the PP/Fn properties, so they need their own
        connection. Drop the Fn session first - one camera, one session."""
        if self.handle is not None:
            self.handle.close()
            self.handle = None
            self.state = None

    def _flash_root(self, which: str) -> Path:
        return journal.sessions_root() / which

    def _confirm_flash(self, title: str, message: str) -> bool:
        return messagebox.askyesno(
            title,
            message + '\n\n确认相机和闪光灯都已关机、热靴附件已拆下，然后继续？',
            default='no')

    def _flash_progress(self, message: str) -> None:
        self._post(self.log, message)

    def on_flash_status(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._close_main_handle()
        self.log('正在连接相机读取闪光配置（会切换服务模式）…')

        def work():
            handle = usbdev.connect(usbdev.load_current_receipt(),
                                    progress=self._flash_progress,
                                    guard_factory=flash_av.AVGuard)
            try:
                session = flash_av.status(handle.camera, handle.identity, self._flash_root('flash_av'))
                # First successful read is the only moment the untouched values
                # are guaranteed to be on the camera; capture them here, before
                # any write is possible.
                snapshot = (session.directory / 'Backup-original.bin').read_bytes()
                flash_baseline.save(snapshot, handle.identity)
                return dict(session.payload)
            finally:
                handle.close()

        self._background(work, self._flash_status_done)

    def _flash_status_done(self, payload, error) -> None:
        self._set_busy(False)
        if error is not None:
            self.log(errors.user_message(error))
            self._refresh_flash()
            return
        menu = payload.get('menu_restriction')
        av = payload.get('av_eligibility')
        self.flash_menu_value = menu
        self.flash_av_value = av
        self.flash_menu_var.set(f'上层索引 45：{menu}（0 = 不施加该项限制）')
        self.flash_av_var.set(f'AV 偏移 AD：{av}（0 = 仍否决，1 = 通过此项检查）')
        before = self.flash_baseline is not None
        self.flash_baseline = flash_baseline.load()
        self._update_flash_baseline_text()
        self.log('状态已读取。' if before else '状态已读取，并已保存初始备份。')
        self._refresh_flash()

    def on_flash_menu_apply(self) -> None:
        if self.busy:
            return
        if not self._confirm_flash('开放上层规则',
                                   '这会改写 00020008 的索引 45（1 → 0），然后保存。\n'
                                   '单独做这一步不会引闪，只是让菜单恢复可选。'):
            return
        self._set_busy(True)
        self._close_main_handle()
        root = self._flash_root('flash')

        def work():
            handle = usbdev.connect(usbdev.load_current_receipt(),
                                    progress=self._flash_progress,
                                    guard_factory=flash_service.FlashGuard)
            try:
                return flash_service.apply(handle.camera, handle.guard, handle.identity, root,
                                           progress=self._flash_progress)
            finally:
                handle.close()

        self._background(work, self._flash_apply_done)

    def on_flash_av_apply(self) -> None:
        if self.busy:
            return
        if not self._confirm_flash('开放 AV 资格',
                                   '这会改写 0003000B 的偏移 AD（0 → 1），然后保存。\n'
                                   '原厂回调可能在保存或重启之前就生效。'):
            return
        self._set_busy(True)
        self._close_main_handle()
        root = self._flash_root('flash_av')

        def work():
            handle = usbdev.connect(usbdev.load_current_receipt(),
                                    progress=self._flash_progress,
                                    guard_factory=flash_av.AVGuard)
            try:
                return flash_av.apply(handle.camera, handle.guard, handle.identity, root,
                                      progress=self._flash_progress)
            finally:
                handle.close()

        self._background(work, self._flash_apply_done)

    def _flash_apply_done(self, session, error) -> None:
        self._set_busy(False)
        if error is not None:
            self.log(errors.user_message(error))
            return
        self.log(f'事务结果：{session.state}')
        self.log(f'日志：{session.directory}')
        self.flash_menu_value = None
        self.flash_av_value = None
        self.flash_menu_var.set('上层索引 45：已写入，请重启后重新读取')
        self.flash_av_var.set('AV 偏移 AD：已写入，请重启后重新读取')
        self._refresh_flash()
        self.log('请保持热靴空置，关机、拔 USB、再开机，然后重新读取状态核对。')

    def on_flash_restore(self) -> None:
        if self.busy or self.flash_baseline is None:
            return
        baseline = self.flash_baseline
        record = baseline['record']
        if not self._confirm_flash(
                '恢复到初始备份',
                '会把两项闪光配置写回第一次读取时的值：\n'
                f'  上层索引 45 = {record["menu_value"]}\n'
                f'  AV 偏移 AD = {record["av_value"]}'):
            return
        self._set_busy(True)
        self._close_main_handle()

        def work():
            done = []
            handle = usbdev.connect(usbdev.load_current_receipt(),
                                    progress=self._flash_progress,
                                    guard_factory=flash_av.AVGuard)
            try:
                if not flash_baseline.belongs_to(baseline, handle.identity):
                    raise ValueError('这份初始备份属于另一台相机，不能写到现在这台')
                menu_now, av_now = flash_av.current(handle.camera)
                if av_now != record['av_value']:
                    done.append(flash_av.restore_baseline(
                        handle.camera, handle.guard, handle.identity,
                        self._flash_root('flash_av'), baseline['av'],
                        progress=self._flash_progress))
            finally:
                handle.close()

            if menu_now != record['menu_value']:
                handle = usbdev.connect(usbdev.load_current_receipt(),
                                        progress=self._flash_progress,
                                        guard_factory=flash_service.FlashGuard)
                try:
                    done.append(flash_service.restore_baseline(
                        handle.camera, handle.guard, handle.identity,
                        self._flash_root('flash'), baseline['menu'],
                        progress=self._flash_progress))
                finally:
                    handle.close()
            return done

        self._background(work, self._flash_restore_done)

    def _flash_restore_done(self, results, error) -> None:
        self._set_busy(False)
        if error is not None:
            self.log(errors.user_message(error))
            self._refresh_flash()
            return
        if not results:
            self.log('两项配置已经是初始值，没有写入。')
        else:
            for session in results:
                self.log(f'恢复结果：{session.state}（{session.directory}）')
        self.flash_menu_value = None
        self.flash_av_value = None
        self.flash_menu_var.set('上层索引 45：已请求恢复，请重启后重新读取')
        self.flash_av_var.set('AV 偏移 AD：已请求恢复，请重启后重新读取')
        self._refresh_flash()
        self.log('请保持热靴空置，关机、拔 USB、再开机，然后重新读取状态核对。')

    # -- menu deployment tab ----------------------------------------------
    PREVIEW = {
        'menu': ('menu-1.png', 'menu-2.png'),
        'fl': ('fl-1.png', 'fl-2.png', 'fl-3.png'),
    }

    def _build_menu_tab(self, parent) -> None:
        self.menu_root = journal.sessions_root() / 'menu'
        self.menu_preview = []

        warn = ttk.LabelFrame(parent, text='使用前必读')
        warn.pack(fill='x', padx=10, pady=8)
        ttk.Label(warn, justify='left', wraplength=720, text=(
            '这不是改参数，是把 /dev/nflasha15 整个 300 MiB 分区换掉。\n'
            '· 曾经有一个不同布局的版本让相机按 MENU 毫无反应并整机冷启动，那个版本已停用。\n'
            '· 分四步：先做一次初始备份，再在本地修补出目标镜像，然后才写入；回退只在有初始备份时可用。\n'
            '· 不下载、不分发任何镜像文件：修补用的补丁内置在程序里。\n'
            '· 写入后必须正常关机、完整断电、冷启动。\n'
            '· 本地至少需要 1.2 GB 空闲空间。'
        )).pack(anchor='w', padx=10, pady=8)

        backup = ttk.LabelFrame(parent, text='① 初始备份')
        backup.pack(fill='x', padx=10, pady=8)
        self.menu_baseline_var = tk.StringVar()
        ttk.Label(backup, textvariable=self.menu_baseline_var, wraplength=720,
                  justify='left').pack(anchor='w', padx=10, pady=(8, 4))
        self.menu_backup_btn = ttk.Button(backup, text='执行初始备份', command=self.on_menu_backup)
        self.menu_backup_btn.pack(anchor='w', padx=10, pady=(0, 10))

        patch = ttk.LabelFrame(parent, text='② 修改')
        patch.pack(fill='x', padx=10, pady=8)
        self.menu_target_var = tk.StringVar(value='menu')
        row = ttk.Frame(patch)
        row.pack(anchor='w', padx=10, pady=(8, 4))
        ttk.Radiobutton(row, text='菜单修改', value='menu', variable=self.menu_target_var,
                        command=self._refresh_menu_preview).pack(side='left')
        ttk.Radiobutton(row, text='创意外观 FL（实验版）', value='fl', variable=self.menu_target_var,
                        command=self._refresh_menu_preview).pack(side='left', padx=12)
        self.menu_preview_frame = ttk.Frame(patch)
        self.menu_preview_frame.pack(anchor='w', padx=10, pady=(0, 4))
        ttk.Label(patch, justify='left', wraplength=720, text=(
            '菜单修改：PP / S-Log / 四比例 + 复古衣橱，已实机确认。\n'
            '创意外观 FL：在上面基础上增加创意外观入口和 10 条菜单文字，'
            '文字已实机确认全部显示；整分区回读有 9 字节文件系统计数差异，不影响使用，尚未修复。'
        )).pack(anchor='w', padx=10, pady=(0, 4))
        self.menu_pending_var = tk.StringVar(value='尚未修补')
        ttk.Label(patch, textvariable=self.menu_pending_var, wraplength=720,
                  justify='left').pack(anchor='w', padx=10, pady=(0, 4))
        self.menu_patch_btn = ttk.Button(patch, text='修补', command=self.on_menu_patch)
        self.menu_patch_btn.pack(anchor='w', padx=10, pady=(0, 10))

        write = ttk.LabelFrame(parent, text='③ 写入')
        write.pack(fill='x', padx=10, pady=8)
        self.menu_write_btn = ttk.Button(write, text='写入相机', command=self.on_menu_write)
        self.menu_write_btn.pack(anchor='w', padx=10, pady=8)

        aspect = ttk.LabelFrame(parent, text='④ 4:3 保存参数')
        aspect.pack(fill='x', padx=10, pady=8)
        ttk.Label(aspect, justify='left', wraplength=720, text=(
            '四项比例菜单在分区里，但选 4:3 要真的能保存，还需要写 51 项出图尺寸／像素数／'
            'JPEG 容量参数到 /setting/Backup.bin（nflasha2）。\n'
            '这一步是参数写入，不替换分区；写前会记录当前值。'
        )).pack(anchor='w', padx=10, pady=(8, 4))
        self.aspect_btn = ttk.Button(aspect, text='写入 4:3 保存参数',
                                     command=self.on_menu_aspect)
        self.aspect_btn.pack(anchor='w', padx=10, pady=(0, 10))

        rollback = ttk.LabelFrame(parent, text='⑤ 回退')
        rollback.pack(fill='x', padx=10, pady=8)
        self.menu_restore_btn = ttk.Button(rollback, text='回退到初始备份',
                                           command=self.on_menu_restore)
        self.menu_restore_btn.pack(anchor='w', padx=10, pady=8)

        self._update_menu_texts()
        self._refresh_menu_preview()
        self._refresh_menu()

    def _refresh_menu_preview(self) -> None:
        for widget in self.menu_preview_frame.winfo_children():
            widget.destroy()
        self.menu_preview = []
        for name in self.PREVIEW.get(self.menu_target_var.get(), ()):
            path = data.data_root() / 'preview' / name
            try:
                image = tk.PhotoImage(file=str(path)).subsample(3)
            except Exception:
                continue
            self.menu_preview.append(image)
            ttk.Label(self.menu_preview_frame, image=image).pack(side='left', padx=4)

    def _update_menu_texts(self) -> None:
        info = menu_deploy.baseline_info(self.menu_root)
        if info is None:
            self.menu_baseline_var.set('尚未备份。点「执行初始备份」，程序会完整读出当前分区并存档。')
        else:
            self.menu_baseline_var.set(
                f'已备份：{info.get("bytes", menu_deploy.PARTITION_BYTES):,} 字节，'
                f'{info.get("created", "")}，SHA256 {info.get("sha256", "")[:16]}…')
        pending = menu_deploy.pending_info(self.menu_root)
        if pending is None:
            self.menu_pending_var.set('尚未修补。选好目标后点「修补」，会在本地生成目标镜像。')
        else:
            self.menu_pending_var.set(
                f'已修补：{pending["label"]}，{pending["bytes"]:,} 字节，'
                f'SHA256 {pending["sha256"][:16]}…（{pending["created"]}）')

    def _refresh_menu(self) -> None:
        def normal(ok):
            return 'normal' if ok else 'disabled'

        busy = self.busy
        has_baseline = menu_deploy.baseline_info(self.menu_root) is not None
        has_pending = menu_deploy.pending_info(self.menu_root) is not None
        self.menu_backup_btn.configure(state=normal(not busy and not has_baseline))
        self.menu_patch_btn.configure(state=normal(not busy and has_baseline))
        self.menu_write_btn.configure(state=normal(not busy and has_pending))
        self.aspect_btn.configure(state=normal(not busy))
        self.menu_restore_btn.configure(state=normal(not busy and has_baseline))

    def _menu_progress(self, message: str) -> None:
        self._post(self.log, message)

    def _menu_connect(self, work, done) -> None:
        handle = usbdev.connect(
            usbdev.load_current_receipt(),
            progress=self._menu_progress,
            guard_factory=lambda transport: menu_deploy.PartitionGuard(transport, allow_write=True),
            response_timeout=menu_deploy.TRANSFER_TIMEOUT_SECONDS)
        try:
            usbdev.check_identity(handle.identity)
            return work(handle)
        finally:
            handle.close()

    def on_menu_backup(self) -> None:
        if self.busy or menu_deploy.baseline_info(self.menu_root) is not None:
            return
        if not messagebox.askyesno(
                '执行初始备份',
                '会完整读出相机 /dev/nflasha15 分区（300 MiB）并存档。\n\n'
                '这一步只读，不写入相机。之后的修补和回退都以这份备份为准。\n\n继续吗？'):
            return
        self._set_busy(True)
        self._close_main_handle()

        def work():
            return self._menu_connect(
                lambda handle: menu_deploy.backup(handle.camera, handle.identity,
                                                  self.menu_root, progress=self._menu_progress),
                None)

        self._background(work, self._menu_done)

    def on_menu_patch(self) -> None:
        if self.busy or menu_deploy.baseline_info(self.menu_root) is None:
            return
        target = self.menu_target_var.get()
        self._set_busy(True)

        def work():
            return menu_deploy.patch_from_baseline(self.menu_root, target,
                                                   progress=self._menu_progress)

        self._background(work, self._menu_done)

    def on_menu_write(self) -> None:
        if self.busy or menu_deploy.pending_info(self.menu_root) is None:
            return
        pending = menu_deploy.pending_info(self.menu_root)
        if not messagebox.askyesno(
                '写入相机',
                f'目标：{pending["label"]}\n\n'
                '这会替换相机 /dev/nflasha15 的整个 300 MiB 分区。\n'
                '写入前会再完整读一次现场并存档。\n\n'
                '写入后必须正常关机、完整断电、冷启动。\n'
                '这个操作曾经导致过整机无法显示菜单。确定继续吗？',
                default='no'):
            return
        if not messagebox.askyesno(
                '最后确认',
                '确认相机型号是 ILCE-9、固件 6.00，且电池电量充足、USB 连接稳定？',
                default='no'):
            return
        self._set_busy(True)
        self._close_main_handle()

        def work():
            return self._menu_connect(
                lambda handle: menu_deploy.write_candidate(handle.camera, handle.identity,
                                                           self.menu_root, progress=self._menu_progress),
                None)

        self._background(work, self._menu_done)

    def on_menu_aspect(self) -> None:
        if self.busy:
            return
        if not messagebox.askyesno(
                '写入 4:3 保存参数',
                f'会写入 {len(aspect_params.PIDS)} 项参数到 /setting/Backup.bin，然后保存。\n\n'
                '写入前会记录当前值。这是参数写入，不替换分区。\n\n继续吗？'):
            return
        self._set_busy(True)
        self._close_main_handle()

        def work():
            handle = usbdev.connect(
                usbdev.load_current_receipt(),
                progress=self._menu_progress,
                guard_factory=lambda transport: aspect_params.AspectGuard(transport))
            try:
                usbdev.check_identity(handle.identity)
                return aspect_params.apply(handle.camera, handle.identity,
                                           self.menu_root, progress=self._menu_progress)
            finally:
                handle.close()

        self._background(work, self._menu_done)

    def on_menu_restore(self) -> None:
        if self.busy or menu_deploy.baseline_info(self.menu_root) is None:
            return
        if not messagebox.askyesno(
                '回退到初始备份',
                '会把初始备份的整个 300 MiB 分区写回相机。\n\n'
                '确认相机型号是 ILCE-9、固件 6.00，且电池电量充足？',
                default='no'):
            return
        self._set_busy(True)
        self._close_main_handle()

        def work():
            return self._menu_connect(
                lambda handle: menu_deploy.restore(handle.camera, handle.identity,
                                                   self.menu_root, progress=self._menu_progress),
                None)

        self._background(work, self._menu_done)

    def _menu_done(self, result, error) -> None:
        self._set_busy(False)
        if error is not None:
            self.log(errors.user_message(error))
            self._update_menu_texts()
            self._refresh_menu()
            return
        if isinstance(result, dict) and 'state' in result:
            self.log(f'事务结果：{result["state"]}')
            self.log(f'会话目录：{result["directory"]}')
            self.log('请正常关机、完整断电、冷启动，然后再连接确认菜单。')
        elif isinstance(result, dict) and 'label' in result:
            self.log(f'已修补：{result["label"]}，SHA256 {result["sha256"]}')
            self.log('确认无误后点「写入相机」。')
        elif isinstance(result, dict) and 'sha256' in result:
            self.log(f'初始备份完成：{result["bytes"]:,} 字节，SHA256 {result["sha256"]}')
        self._update_menu_texts()
        self._refresh_menu()

def _slot_number(label: str) -> int:
    return int(label.replace('Fn', ''))


def _describe(session: journal.Session) -> str:
    payload = session.payload
    if session.action == 'enable_override':
        return '开启 PP 放行'
    if session.action == 'write_slot':
        slot = payload.get('slot')
        return f'{fnmap.slot_label(slot)} → {payload.get("symbol", "?")} (0x{payload.get("target", "??")})'
    if session.action == 'restore':
        return f'恢复 {payload.get("property", "")}'
    if session.action == 'restore_baseline':
        return '恢复全部原厂'
    return session.action


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
