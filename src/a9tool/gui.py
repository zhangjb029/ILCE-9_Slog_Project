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
from tkinter import messagebox, ttk

from . import core, errors, fnmap, journal, usbdev

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

        connect = ttk.LabelFrame(self.root, text='① 连接相机')
        connect.pack(fill='x', **pad)
        ttk.Label(connect, text='相机 USB 连接模式设为「大容量存储」，只连这一台相机。').pack(anchor='w', padx=10, pady=(8, 4))
        row = ttk.Frame(connect)
        row.pack(anchor='w', padx=10, pady=(0, 10))
        self.connect_btn = ttk.Button(row, text='连接并检查', command=self.on_connect)
        self.connect_btn.pack(side='left')
        self.retry_btn = ttk.Button(row, text='重试', command=self.on_connect)
        self.retry_btn.pack(side='left', padx=8)
        self.retry_btn.pack_forget()

        status = ttk.LabelFrame(self.root, text='② 检测结果')
        status.pack(fill='x', **pad)
        self.status_var = tk.StringVar(value='尚未连接')
        self.override_var = tk.StringVar(value='')
        ttk.Label(status, textvariable=self.status_var, justify='left').pack(anchor='w', padx=10, pady=(8, 2))
        ttk.Label(status, textvariable=self.override_var, justify='left').pack(anchor='w', padx=10)
        self.override_btn = ttk.Button(status, text='开启 PP 放行', command=self.on_enable_override)
        self.override_btn.pack(anchor='w', padx=10, pady=(6, 10))

        cards = ttk.LabelFrame(self.root, text='③ 选择功能')
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

        restore = ttk.LabelFrame(self.root, text='④ 恢复')
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
        log_frame.pack(fill='both', expand=True, **pad)
        self.log_box = tk.Text(log_frame, height=8, wrap='word', state='disabled')
        self.log_box.pack(fill='both', expand=True, padx=10, pady=8)

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
