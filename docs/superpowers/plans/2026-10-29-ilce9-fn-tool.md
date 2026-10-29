# ILCE-9 功能槽位工具 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把已验证的 Python 命令行脚本变成普通用户双击就能用的 Windows exe，配一套中英双语图文教程站，发布到 GitHub。

**Architecture:** 从 `a9_pp_live.py` 移植 USB 连接、白名单守卫、写前落盘、回读校验四层机制，泛化成「写任意一个属性」的事务引擎。tkinter 单窗口只做流程编排与文案，所有相机操作走 `core.py`。第三方代码 vendored 进仓库，PyInstaller 打成单文件 exe。

**Tech Stack:** Python 3.11+、tkinter、pyusb 1.3.1、libusb-1.0、ma1co PMCA（vendored）、PyInstaller、unittest

**Spec:** `docs/superpowers/specs/2026-10-29-ilce9-fn-tool-design.md`

## Global Constraints

- 只支持 `ILCE-9` + 固件 `6.00`；型号或版本不符时拒绝一切读写。
- 一次运行 = 一次写入 = 一次 `SAVE(0)` = 断开。写入成功后禁用全部写入入口。
- 写入前必须先把 `Backup-original.bin` + `journal.json` 落盘并 fsync，再发 WRITE。
- Fn 槽位属性：Fn1=`0x01070be8`、Fn2=`0x01070bec`、Fn3=`0x01070bed`、Fn4=`0x01070bee`、Fn5=`0x01070bef`、Fn6=`0x01070bf0`、Fn7=`0x01070bf1`、Fn8=`0x01070bf2`、Fn9=`0x01070bf3`、Fn10=`0x01070be9`、Fn11=`0x01070bea`、Fn12=`0x01070beb`；全部 1 字节、`attr 0x50`。
- PP 放行属性 `0x00880000`（1024 字节），只有偏移 `0xa2, 0xa3, 0xa5, 0xa7, 0xab` 允许改为 `0x02`，其余字节必须保持机身原值。
- 写入白名单：快照读取、指定属性的 READ、已武装的那一个 WRITE、`SAVE(0)`。其余一律拒绝。
- 失败不自动重试、不自动回滚；journal 保持 `FAILED_REVIEW_REQUIRED` 状态。
- `0x64`（像素转换）保留可选，但界面标 ⛔ 并二次确认。
- 界面文案中文；教程站中英双语。界面里不出现「属性」「偏移」「保存值」「journal」这些词。
- `sessions/` 与 `baseline/` 落在 `Path(sys.executable).parent`（打包后）或项目根（源码运行），**不得**落在 `_MEIPASS` 临时目录。

## Review Focus

1. **相机没连 / 连了两台 / 连的是 A9 II。** 用户期望：一句话说清楚现在该怎么办，而不是异常栈。→ Task 4 测试 `test_connect_rejects_multiple_cameras`、`test_identity_gate_rejects_wrong_model`。
2. **服务模式切换后新设备没装驱动。** 用户期望：窗口里直接给「重试」，不用翻文件路径。→ Task 4 测试 `test_service_not_found_yields_resume_hint`。
3. **恢复时槽位值既不是原值也不是目标值**（用户中途在相机上手动改过）。用户期望：拒绝并说明，不猜。→ Task 8 测试 `test_restore_refuses_when_value_is_third_state`。
4. **链式恢复退不回出厂。** 用户期望：界面明确告诉他这条记录的原值来自上一次写入。→ Task 3 测试 `test_journal_marks_chained_original`。
5. **PyInstaller onefile 下 sessions 落进临时目录。** 用户期望：重启软件后还能看到自己的备份。→ Task 12 验证步骤 `test_sessions_root_is_executable_dir`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `src/a9tool/data.py` | 从 `src/data/*.json` 加载值表与中文名，打包后路径兼容 |
| `src/a9tool/fnmap.py` | 槽位表、功能项、✅/⬜/⛔ 状态判定 |
| `src/a9tool/errors.py` | 异常 → 面向用户的一句话 + 下一步 |
| `src/a9tool/journal.py` | Session 目录、journal 读写、链式标记、列表 |
| `src/a9tool/usbdev.py` | PMCA 封装：枚举、身份读取、服务模式切换、收据 |
| `src/a9tool/core.py` | 事务引擎：快照、状态判定、写放行位、写槽位、恢复 |
| `src/a9tool/gui.py` | tkinter 单窗口 |
| `src/a9tool/vendor/` | pmca / pyusb / libusb |
| `tests/` | unittest，全部离线（FakeCamera） |

---

### Task 1: 项目骨架、vendored 依赖与数据表

**Files:**
- Create: `ILCE-9_Slog_Project/.gitignore`, `LICENSE`, `NOTICE`, `src/a9tool/__init__.py`, `pyproject.toml`
- Copy: `src/vendor/pmca/`、`src/vendor/usb/`、`src/vendor/libusb_package/`、`src/data/*.json`

**Interfaces:**
- Produces: 可 import 的 `a9tool` 包；`src/data/a9_fn_functions.json` 与 `src/data/a9_fn_chinese_names.json` 原样存在。

- [ ] **Step 1: 建目录并初始化 git**

```powershell
Set-Location -LiteralPath 'F:\固件\ILCE-9_Slog_Project'
git init
New-Item -ItemType Directory -Force src/a9tool, src/data, src/vendor, build, tests, docs/assets/img
```

- [ ] **Step 2: 复制 vendored 依赖与数据表**

```powershell
Copy-Item -Recurse 'F:\固件\analysis\pmca_update_auth_source\a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0\pmca' src/vendor/pmca
Copy-Item -Recurse 'F:\固件\analysis\a9_live_deps\usb' src/vendor/usb
Copy-Item -Recurse 'F:\固件\analysis\a9_live_deps\libusb_package' src/vendor/libusb_package
Copy-Item 'F:\固件\analysis\a9_fn_functions.json','F:\固件\analysis\a9_fn_chinese_names.json' src/data/
```

`src/vendor/` 本身就是一个 `sys.path` 条目，所以 `import pmca` / `import usb` / `import libusb_package` 都从这里解析。

只保留 `src/vendor/pmca/` 下的 `usb/`、`util/__init__.py`、`backup.py`、`__init__.py`；删掉其余子包（camera、network、dd 等），避免把无关代码带进发布物。

- [ ] **Step 3: 写 `src/a9tool/__init__.py`，把 vendored 目录挂到 `sys.path`**

```python
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / 'vendor'
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))
```

打包后 `VENDOR` 会落在 `_MEIPASS/vendor`，同样有效。后续所有子模块直接 `import pmca...` / `import usb...`，不再各自改 `sys.path`。

- [ ] **Step 4: 写 `.gitignore`**

```
__pycache__/
*.pyc
dist/
build/output/
sessions/
baseline/
*.exe
.pytest_cache/
```

- [ ] **Step 5: 验证包可导入且数据表完整**

Run: `python -c "import sys; sys.path[:0]=['src','src/vendor']; import a9tool, pmca.backup, usb.core, libusb_package, json; d=json.load(open('src/data/a9_fn_functions.json',encoding='utf8')); assert d['distinct_bytes']==77; print('OK')"`
Expected: `OK`

- [ ] **Step 6: 提交**

```bash
git add -A && git commit -m "chore: scaffold project with vendored deps and firmware tables"
```

---

### Task 2: fnmap.py — 槽位表、功能项、状态标记

**Files:**
- Create: `src/a9tool/data.py`, `src/a9tool/fnmap.py`, `tests/test_fnmap.py`

**Interfaces:**
- Produces:
  - `data.resource_json(name: str) -> dict`
  - `fnmap.FN_SLOTS: dict[int, int]`（槽号 1–12 → 属性号）
  - `fnmap.SLOT_PIDS: tuple[int, ...]`
  - `fnmap.OVERRIDE: int = 0x00880000`
  - `fnmap.OVERRIDE_OFFSETS: tuple[int, ...] = (0xa2, 0xa3, 0xa5, 0xa7, 0xab)`
  - `@dataclass FunctionItem(value:int, symbol:str, chinese:str, status:str)`，`status ∈ {'verified','untested','known_bad'}`
  - `fnmap.load_functions() -> list[FunctionItem]`（按 value 升序，77 项）
  - `fnmap.status_of(value:int) -> str`
  - `fnmap.slot_label(n:int) -> str` → `'Fn1'`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_fnmap -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a9tool'`

- [ ] **Step 3: 实现 `data.py` 与 `fnmap.py`**

`data.resource_json` 用 `sys._MEIPASS` 存在时指向它，否则指向 `Path(__file__).parent.parent / 'data'`。`load_functions` 把 `a9_fn_functions.json` 的 `rows` 按 `in_range` 过滤、按 `value` 去重，中文名从 `a9_fn_chinese_names.json` 取，缺失时回退到符号名。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_fnmap -v`
Expected: 6 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/data.py src/a9tool/fnmap.py tests/test_fnmap.py
git commit -m "feat(fnmap): firmware Fn value table with verification status"
```

---

### Task 3: journal.py — 会话目录与链式标记

**Files:**
- Create: `src/a9tool/journal.py`, `tests/test_journal.py`

**Interfaces:**
- Produces:
  - `journal.sessions_root() -> Path`（`sys.executable` 目录下 `sessions/`）
  - `journal.baseline_root() -> Path`
  - `@dataclass Session(directory: Path, journal: dict)`，属性 `state: str`、`action: str`、`created: str`、`summary: str`
  - `journal.create(root: Path, action: str, payload: dict, snapshot: bytes) -> Session` — 先写 `Backup-original.bin`（`'xb'` + fsync）再写 `journal.json`（`'x'` + fsync）。`journal.json` 结构固定为 `{schema, action, payload, snapshot_sha256, state, created}`；`payload` 由调用方定义
  - `journal.load(path: Path) -> Session`
  - `journal.list_sessions(root: Path) -> list[Session]`（按时间倒序）
  - `journal.mark_chained(session: Session) -> bool` — 判断该 session 的「原值」是否来自更早一次写入

- [ ] **Step 1: 写失败测试**

```python
class TestJournal(unittest.TestCase):
    def test_create_writes_snapshot_before_journal(self):
        s = journal.create(self.root, 'write_slot', {'slot': 7}, b'\x01\x02')
        self.assertEqual((s.directory / 'Backup-original.bin').read_bytes(), b'\x01\x02')
        self.assertEqual(json.loads((s.directory / 'journal.json').read_text())['action'], 'write_slot')

    def test_two_creates_get_distinct_directories(self):
        a = journal.create(self.root, 'a', {}, b'x')
        b = journal.create(self.root, 'a', {}, b'x')
        self.assertNotEqual(a.directory, b.directory)
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_list_sessions_newest_first(self):
        a = journal.create(self.root, 'a', {}, b'x')
        b = journal.create(self.root, 'b', {}, b'y')
        self.assertEqual([s.action for s in journal.list_sessions(self.root)], ['b', 'a'])
        _ = a, b

    def test_journal_marks_chained_original(self):
        first = journal.create(self.root, 'write_slot', {'slot': 7, 'original': '06'}, b'x')
        second = journal.create(self.root, 'write_slot', {'slot': 7, 'original': '36',
                                                          'written_by': str(first.directory)}, b'y')
        self.assertTrue(journal.mark_chained(second))
        self.assertFalse(journal.mark_chained(first))

    def test_load_rejects_tampered_snapshot(self):
        s = journal.create(self.root, 'a', {}, b'original')
        (s.directory / 'Backup-original.bin').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            journal.load(s.directory / 'journal.json')
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_journal -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 `journal.py`**

目录名用 `datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ-') + uuid.uuid4().hex[:10]`。`journal.json` 里存 `snapshot_sha256`；`load` 校验哈希不符就抛 `ValueError('Original snapshot is missing or changed')`。`mark_chained` 读 `payload.get('written_by')` 是否存在且指向另一个 session 目录。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_journal -v`
Expected: 5 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/journal.py tests/test_journal.py
git commit -m "feat(journal): session directories with chained-original detection"
```

---

### Task 4: usbdev.py — 身份门、连接、服务模式收据

**Files:**
- Create: `src/a9tool/usbdev.py`, `src/a9tool/errors.py`, `tests/test_usbdev.py`, `tests/test_errors.py`
- Reference (只读移植来源): `F:\固件\analysis\a9_pp_live.py:364-460`

**Interfaces:**
- Consumes: `fnmap`, `journal`
- Produces:
  - `errors.user_message(exc: BaseException) -> str`（一句话 + 下一步）
  - `usbdev.check_identity(identity: dict) -> None` — 不符抛 `ValueError('Only ILCE-9 with firmware 6.00 is supported')`
  - `@dataclass CameraHandle(device, driver, senser, identity: dict)`
  - `usbdev.connect(receipt: Path | None = None) -> CameraHandle`
  - `usbdev.save_receipt(identity: dict, usb_port: dict) -> Path`（写 `sessions/_receipt.json`）
  - `usbdev.load_current_receipt() -> Path | None`（存在且未满 1 小时才返回）
  - `usbdev.disconnect(handle: CameraHandle) -> None`

- [ ] **Step 1: 写失败测试**

```python
class TestIdentityGate(unittest.TestCase):
    def test_identity_gate_rejects_wrong_model(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity({'model': 'ILCE-9M2', 'firmware': '3.20', 'serial_sha256': 'a'*64})

    def test_identity_gate_rejects_wrong_firmware(self):
        with self.assertRaises(ValueError):
            usbdev.check_identity({'model': 'ILCE-9', 'firmware': '5.00', 'serial_sha256': 'a'*64})

    def test_identity_gate_accepts_a9_600(self):
        usbdev.check_identity({'model': 'ILCE-9', 'firmware': '6.00', 'serial_sha256': 'a'*64})


class TestErrorMessages(unittest.TestCase):
    def test_service_not_found_yields_resume_hint(self):
        msg = errors.user_message(RuntimeError('Service device not found'))
        self.assertIn('Zadig', msg)
        self.assertIn('重试', msg)

    def test_busy_identity_yields_power_cycle_hint(self):
        msg = errors.user_message(RuntimeError('Camera busy during identity request'))
        self.assertIn('关机', msg)

    def test_unknown_error_still_gives_next_step(self):
        msg = errors.user_message(ValueError('something odd'))
        self.assertTrue(msg.strip())
        self.assertIn('日志', msg)

    def test_connect_rejects_multiple_cameras(self):
        with self.assertRaises(RuntimeError) as ctx:
            usbdev._select_single([object(), object()])
        self.assertIn('一台', errors.user_message(ctx.exception))
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_usbdev tests.test_errors -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现**

`_select_single(devices)` 是纯函数，列表长度不为 1 就抛 `RuntimeError('Connect exactly one camera')`，便于离线测试。`connect()` 移植 `connect_service` 的设备枚举、`QueryDevice` 扩展命令、`BoundedSenser`（含 30 秒预算与补零排空）与认证流程；把 `print('Connection phase:', ...)` 换成可选 `progress: Callable[[str], None]` 回调。`errors.user_message` 用与 `a9_pp_fn_slot_live.FAILURE_HINTS` 相同的子串匹配，返回中文文案，未命中时返回「遇到未预期的问题。请把窗口下方日志整段复制下来。相机可能已经发生部分改动，请保留 sessions 目录。」

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_usbdev tests.test_errors -v`
Expected: 8 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/usbdev.py src/a9tool/errors.py tests/test_usbdev.py tests/test_errors.py
git commit -m "feat(usbdev): identity gate, service-mode connection, user-facing error text"
```

---

### Task 5: core.py — 快照与机身状态判定

**Files:**
- Create: `src/a9tool/core.py`, `tests/test_core_state.py`, `tests/fakecamera.py`

**Interfaces:**
- Consumes: `fnmap`, `journal`
- Produces:
  - `@dataclass CameraState(snapshot: bytes, override: bytes, slots: dict[int, int])`
  - `core.read_state(camera) -> CameraState`
  - `core.override_status(state) -> str`，返回 `'enabled' | 'disabled' | 'mixed'`
  - `core.Guard(transport)` — `arm(pid: int, data: bytes)`、`allow_reads(pids: Iterable[int])`
  - `core.READ_PIDS: tuple[int, ...]` = `(0x00880000, 0x0107146D, 0x01070316) + SLOT_PIDS`

- [ ] **Step 1: 写失败测试**

```python
class TestOverrideStatus(unittest.TestCase):
    def test_all_two_is_enabled(self):
        raw = bytearray(1024)
        for off in fnmap.OVERRIDE_OFFSETS: raw[off] = 2
        self.assertEqual(core.override_status(core.CameraState(b'', bytes(raw), {})), 'enabled')

    def test_all_one_is_disabled(self):
        raw = bytearray(1024)
        for off in fnmap.OVERRIDE_OFFSETS: raw[off] = 1
        self.assertEqual(core.override_status(core.CameraState(b'', bytes(raw), {})), 'disabled')

    def test_mixed_is_mixed_and_blocks_writes(self):
        raw = bytearray(1024)
        raw[0xa2] = 2
        state = core.CameraState(b'', bytes(raw), {})
        self.assertEqual(core.override_status(state), 'mixed')

    def test_factory_ff_is_disabled(self):
        raw = bytearray(b'\xff' * 1024)
        self.assertEqual(core.override_status(core.CameraState(b'', bytes(raw), {})), 'disabled')


class TestGuard(unittest.TestCase):
    def test_guard_blocks_unarmed_write(self):
        g = core.Guard(FakeTransport())
        g.arm(0x01070bf1, b'\x36')
        with self.assertRaises(ValueError):
            g.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 2, 0x01070be8) + b'\x3a')

    def test_guard_allows_one_armed_write_then_save(self):
        g = core.Guard(FakeTransport())
        g.arm(0x01070bf1, b'\x36')
        g.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 2, 0x01070bf1) + b'\x36')
        with self.assertRaises(ValueError):
            g.sendSenserPacket(0x40, struct.pack('<HHI', 0x603, 2, 0x01070bf1) + b'\x36')  # 不能重发
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_core_state -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'a9tool.core'`

- [ ] **Step 3: 实现**

`read_state` 调 `camera.getBackupPresetData(True)` 取整份快照，用 PMCA 的 `BackupFile` 解析出 `0x00880000` 与 12 个槽位，再逐项 `camera.readBackup(pid)` 与快照比对，不一致就抛 `ValueError('Live properties differ from the snapshot; no writes performed')`。`Guard` 移植自 `a9_pp_live.PacketGuard`，把「只允许 OVERRIDE + FN1」改成「只允许 `self.armed_pid` 一次」，`arm` 后该 pid 的 WRITE 只能成功一次。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_core_state -v`
Expected: 6 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/core.py tests/test_core_state.py tests/fakecamera.py
git commit -m "feat(core): snapshot reading, override state classification, write guard"
```

---

### Task 6: core.py — 开启 PP 放行位

**Files:**
- Modify: `src/a9tool/core.py`
- Create: `tests/test_core_override.py`

**Interfaces:**
- Consumes: `core.read_state`、`core.Guard`、`journal.create`
- Produces: `core.enable_override(camera, state: CameraState, root: Path, progress=None) -> journal.Session`

- [ ] **Step 1: 写失败测试**

```python
class TestEnableOverride(unittest.TestCase):
    def test_writes_only_five_offsets(self):
        cam = FakeCamera(override=bytes(1024))
        s = core.enable_override(cam, core.read_state(cam), self.root)
        written = cam.written[fnmap.OVERRIDE]
        self.assertEqual({i for i, b in enumerate(written) if b == 2}, set(fnmap.OVERRIDE_OFFSETS))
        self.assertEqual(sum(1 for i, b in enumerate(written) if b != 0), 5)
        self.assertEqual(s.state, 'SAVED_AND_READBACK_VERIFIED')

    def test_preserves_other_bytes(self):
        raw = bytearray(1024); raw[0x10] = 0x7e
        cam = FakeCamera(override=bytes(raw))
        core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(cam.written[fnmap.OVERRIDE][0x10], 0x7e)

    def test_never_touches_any_fn_slot(self):
        cam = FakeCamera()
        core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(set(cam.written) & set(fnmap.SLOT_PIDS), set())

    def test_refuses_mixed_state(self):
        raw = bytearray(1024); raw[0xa2] = 2
        cam = FakeCamera(override=bytes(raw))
        with self.assertRaises(ValueError):
            core.enable_override(cam, core.read_state(cam), self.root)

    def test_already_enabled_writes_nothing(self):
        raw = bytearray(1024)
        for off in fnmap.OVERRIDE_OFFSETS: raw[off] = 2
        cam = FakeCamera(override=bytes(raw))
        s = core.enable_override(cam, core.read_state(cam), self.root)
        self.assertEqual(s.state, 'ALREADY_AT_TARGET_NO_SAVE')
        self.assertNotIn(fnmap.OVERRIDE, cam.written)
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_core_override -v`
Expected: FAIL — `AttributeError: module 'a9tool.core' has no attribute 'enable_override'`

- [ ] **Step 3: 实现**

流程：`state` 为 `'mixed'` → 抛 `ValueError('放行位状态不一致，请先用「恢复全部原厂」')`；`'enabled'` → 记 `ALREADY_AT_TARGET_NO_SAVE` 并不写；`'disabled'` → `journal.create(root, 'enable_override', payload, state.snapshot)` → `guard.arm(OVERRIDE, new_bytes)` → `camera.writeBackup` → 回读比对 → 校验其余 1019 字节与快照一致 → `saveBackup(0)` → 再回读。payload 记 `{'original': state.override.hex(), 'target': new.hex(), 'changed_offsets': list(OVERRIDE_OFFSETS)}`。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_core_override -v`
Expected: 5 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/core.py tests/test_core_override.py
git commit -m "feat(core): enable PP override — five offsets only, no slot touched"
```

---

### Task 7: core.py — 写 Fn 槽位

**Files:**
- Modify: `src/a9tool/core.py`
- Create: `tests/test_core_slot.py`

**Interfaces:**
- Consumes: `core.read_state`、`core.Guard`、`fnmap`、`journal.create`
- Produces: `core.write_slot(camera, state: CameraState, slot: int, value: int, root: Path, progress=None) -> journal.Session`

- [ ] **Step 1: 写失败测试**

```python
class TestWriteSlot(unittest.TestCase):
    def test_writes_one_byte_in_one_slot(self):
        cam = FakeCamera()
        state = core.read_state(cam)
        s = core.write_slot(cam, state, 7, 0x36, self.root)
        self.assertEqual(cam.written[0x01070bf1], b'\x36')
        self.assertEqual(len(cam.written), 1)
        self.assertEqual(s.state, 'SAVED_AND_READBACK_VERIFIED')

    def test_refuses_when_override_not_enabled(self):
        cam = FakeCamera(override=bytes(1024))
        with self.assertRaises(ValueError) as ctx:
            core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertIn('放行', str(ctx.exception))
        self.assertEqual(cam.written, {})

    def test_refuses_out_of_range_value(self):
        cam = FakeCamera()
        with self.assertRaises(ValueError):
            core.write_slot(cam, core.read_state(cam), 7, 0x6F, self.root)

    def test_records_original_before_write(self):
        cam = FakeCamera(slots={7: 0x06})
        s = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        self.assertEqual(s.journal['payload']['original'], '06')

    def test_journal_records_verification_note_for_pixel_shift(self):
        cam = FakeCamera()
        s = core.write_slot(cam, core.read_state(cam), 12, 0x64, self.root)
        self.assertEqual(s.journal['payload']['status'], 'known_bad')
        self.assertTrue(s.journal['payload']['confirmation_text'])
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_core_slot -v`
Expected: FAIL — `AttributeError: module 'a9tool.core' has no attribute 'write_slot'`

- [ ] **Step 3: 实现**

`value` 不在 `fnmap` 表内或 `> 0x6E` → 抛 `ValueError`。`override_status(state) != 'enabled'` → 抛 `ValueError('请先开启 PP 放行，再写入功能槽位')`。否则 `journal.create(root, 'write_slot', payload, state.snapshot)` → `guard.arm(pid, bytes([value]))` → 写 → 回读到目标 → 其余 11 槽与放行位与快照一致 → `saveBackup(0)` → 再回读。payload 含 `slot`、`property`（hex 字符串）、`original`（hex）、`target`（hex）、`symbol`、`status`、`confirmation_text`（`known_bad` 时为二次确认框原文，否则 `''`）、`written_by`（若 journal 列表里同槽位有更早 session，取其目录名；否则 `None`）。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_core_slot -v`
Expected: 5 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/core.py tests/test_core_slot.py
git commit -m "feat(core): write one Fn slot byte behind the override gate"
```

---

### Task 8: core.py — 恢复（单条与全部原厂）

**Files:**
- Modify: `src/a9tool/core.py`
- Create: `tests/test_core_restore.py`

**Interfaces:**
- Consumes: `core.read_state`、`journal.load`、`journal.baseline_root`
- Produces:
  - `core.restore_session(camera, session: journal.Session, root: Path, progress=None) -> journal.Session`
  - `core.save_baseline(state: CameraState) -> Path` — 写到 `journal.baseline_root()/baseline.json` + `Backup-baseline.bin`，已存在则原样返回不覆盖。`baseline.json` 结构：`{schema, created, snapshot_sha256, override (hex 字符串), slots: {"1": int, … "12": int}}`
  - `core.restore_baseline(camera, root: Path, progress=None) -> journal.Session`

- [ ] **Step 1: 写失败测试**

```python
class TestRestore(unittest.TestCase):
    def test_restore_returns_slot_to_original(self):
        cam = FakeCamera(slots={7: 0x06})
        s = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        core.restore_session(cam, s, self.root)
        self.assertEqual(cam.slots[7], 0x06)

    def test_restore_refuses_when_value_is_third_state(self):
        cam = FakeCamera(slots={7: 0x06})
        s = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        cam.slots[7] = 0x10  # 用户在相机上手动改过
        with self.assertRaises(ValueError) as ctx:
            core.restore_session(cam, s, self.root)
        self.assertIn('冲突', str(ctx.exception))

    def test_restore_refuses_tampered_snapshot(self):
        cam = FakeCamera()
        s = core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        path = s.directory / 'Backup-original.bin'
        path.write_bytes(bytes(len(path.read_bytes())))
        with self.assertRaises(ValueError):
            core.restore_session(cam, s, self.root)

    def test_restore_baseline_reverts_everything_tool_touched(self):
        cam = FakeCamera(slots={7: 0x06, 12: 0x06})
        core.enable_override(cam, core.read_state(cam), self.root)
        core.save_baseline(core.read_state(cam))
        core.write_slot(cam, core.read_state(cam), 7, 0x36, self.root)
        core.write_slot(cam, core.read_state(cam), 12, 0x3A, self.root)
        core.restore_baseline(cam, self.root)
        self.assertEqual(cam.slots[7], 0x06)
        self.assertEqual(cam.slots[12], 0x06)

    def test_baseline_is_written_once(self):
        cam = FakeCamera()
        p1 = core.save_baseline(core.read_state(cam))
        cam.slots[7] = 0x36
        p2 = core.save_baseline(core.read_state(cam))
        self.assertEqual(p1, p2)
        self.assertEqual(json.loads(p1.read_text())['slots']['7'], 0x06)
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -m unittest tests.test_core_restore -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: 实现**

`restore_session` 从 session 的 `Backup-original.bin` 里取出该 action 碰过的属性原值；当前值必须等于原值或目标值之一，否则抛 `ValueError('恢复冲突：槽位当前值既不是记录的原值也不是写入值。可能你在相机上手动改过，请先确认。')`。`save_baseline` 把整份快照与 12 槽/放行位原值写到 `baseline/`，已存在则不覆盖。`restore_baseline` 把工具碰过的属性一次性写回，走同一条落盘 → 写入 → 回读 → SAVE 路径。

- [ ] **Step 4: 运行，确认通过**

Run: `python -m unittest tests.test_core_restore -v`
Expected: 5 tests OK

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/core.py tests/test_core_restore.py
git commit -m "feat(core): per-session and factory-baseline restore"
```

---

### Task 9: gui.py — 窗口骨架、连接区、状态区

**Files:**
- Create: `src/a9tool/gui.py`, `src/a9tool/__main__.py`

**Interfaces:**
- Consumes: `usbdev`、`core`、`errors`、`journal`
- Produces: `python -m a9tool` 打开窗口

- [ ] **Step 1: 写窗口骨架**

单窗口 `ttk`，从上到下四个 `LabelFrame`：`① 连接相机`、`② 检测结果`、`③ 选择功能`、`④ 恢复`，底部常驻 `Text` 日志区。连接按钮触发后台线程，所有 UI 更新经 `queue.Queue` 回主线程（`root.after(100, drain)`）。

- [ ] **Step 2: 接上连接与检测**

点「连接并检查」→ 禁用按钮 → 线程里 `usbdev.connect(usbdev.load_current_receipt())` → `core.read_state` → **立刻 `core.save_baseline(state)`**（首次使用时落盘出厂基线，之后每次连接都会调用但只在第一次真正写入）→ 主线程填 `②`：机型、固件、序列号前 4 位、放行状态。

失败时日志写 `errors.user_message(exc)`。若消息含 `Service device not found`，在日志下方显示一段固定提示和一个「重试」按钮：

> 相机切到了服务模式，但 Windows 还没给这个新设备装驱动。请打开 Zadig → Options → List All Devices，选带 `(Interface 1)` 的那个 Sony 设备 → 安装 libusb-win32 → 装好后点下面的「重试」。相机不要拔线。

「重试」调 `usbdev.connect(receipt_path)`，`receipt_path` 来自 `usbdev.save_receipt` 在切换前返回的路径；凭据超过 1 小时则改为提示「把相机拔掉重插，回到大容量存储模式，再点连接」。

- [ ] **Step 3: 手动验证**

Run: `python -m a9tool`
Expected: 窗口打开，`②` `③` `④` 均为禁用态，日志显示「尚未连接相机」

- [ ] **Step 4: 提交**

```bash
git add src/a9tool/gui.py src/a9tool/__main__.py
git commit -m "feat(gui): window skeleton with connect and detection panes"
```

---

### Task 10: gui.py — 功能卡片、全部功能列表、写入

**Files:**
- Modify: `src/a9tool/gui.py`

**Interfaces:**
- Consumes: `fnmap.load_functions`、`core.write_slot`、`core.enable_override`

- [ ] **Step 1: 实现两个推荐卡片**

Picture Profile（`0x3A`）与 SLog 显示辅助（`0x36`），各带槽位下拉（Fn1–Fn12）和「写入」按钮。放行状态不是 `enabled` 时卡片禁用，同时 `②` 的「开启 PP 放行」按钮启用。

- [ ] **Step 2: 实现折叠的完整列表**

「全部功能（77 项，多数未验证）」按钮展开 `ttk.Treeview`，列：中文名 / 符号名 / 值 / 状态。状态列用 ✅ ⬜ ⛔。

- [ ] **Step 3: 实现写入与确认**

`known_bad` 项点击写入先弹 `messagebox.askyesno`：「像素转换多重拍摄实测会在拍摄第一张后卡死，需要拔电池才能恢复。确定继续吗？」，`default='no'`。写入成功后：禁用 `③` 全部按钮，`②` 显示「已写入，请关机重启相机」，日志打印 session 目录与回滚提示。

- [ ] **Step 4: 手动验证（无相机）**

Run: `python -m a9tool`
Expected: 未连接时卡片禁用；展开列表显示 77 行；`0x64` 行显示 ⛔

- [ ] **Step 5: 提交**

```bash
git add src/a9tool/gui.py
git commit -m "feat(gui): function cards, full list, guarded write flow"
```

---

### Task 11: gui.py — 恢复区与日志

**Files:**
- Modify: `src/a9tool/gui.py`

**Interfaces:**
- Consumes: `core.restore_session`、`core.restore_baseline`、`journal.list_sessions`、`journal.mark_chained`

- [ ] **Step 1: 实现会话列表**

「从备份恢复到原状」展开 `Treeview`：时间 / 做了什么 / 原值→新值 / 备注。被 `mark_chained` 判定为链式的行，备注列写「原值来自上一次写入，不是出厂状态」。

- [ ] **Step 2: 实现两种恢复**

选中一行点恢复 → 后台调 `core.restore_session` → 成功后禁用 `③`，提示重启。`恢复全部原厂` 先确认「会把本工具改过的地方都恢复到第一次使用前」，再调 `core.restore_baseline`。

- [ ] **Step 3: 手动验证**

Run: `python -m a9tool`
Expected: 无相机会话时列表为空并显示「还没有写入记录」

- [ ] **Step 4: 提交**

```bash
git add src/a9tool/gui.py
git commit -m "feat(gui): session list and two restore paths"
```

---

### Task 12: 构建脚本与 exe 冒烟验证

**Files:**
- Create: `build/a9tool.spec`, `build/build_exe.ps1`, `tests/test_paths.py`

**Interfaces:**
- Produces: `dist/ILCE-9_Slog_Project.exe`

- [ ] **Step 1: 写路径测试**

```python
class TestPaths(unittest.TestCase):
    def test_sessions_root_is_executable_dir(self):
        with mock.patch.object(sys, 'executable', r'C:\somewhere\tool.exe'):
            self.assertEqual(journal.sessions_root(), Path(r'C:\somewhere\sessions'))

    def test_sessions_root_never_uses_meipass(self):
        with mock.patch.object(sys, 'executable', r'C:\somewhere\tool.exe'), \
             mock.patch.object(sys, '_MEIPASS', r'C:\Temp\_MEI123', create=True):
            self.assertEqual(journal.sessions_root(), Path(r'C:\somewhere\sessions'))
```

- [ ] **Step 2: 运行，确认通过（若失败则修 `journal.sessions_root`）**

Run: `python -m unittest tests.test_paths -v`
Expected: 2 tests OK

- [ ] **Step 3: 写 spec 与构建脚本**

`a9tool.spec` 用 `collect_data_files` 收 `src/data`，`binaries` 显式加入 `src/vendor/libusb_package/libusb-1.0.dll`，`pathex` 含 `src` 与 `src/vendor`，`hiddenimports` 含 `usb.core`、`usb.util`、`pmca.usb.sony`、`pmca.backup`。`build_exe.ps1`：清 `dist/` → `pyinstaller build/a9tool.spec --clean --noconfirm` → 打印产物路径与大小。

- [ ] **Step 4: 构建并冒烟**

Run: `powershell -File build/build_exe.ps1; .\dist\ILCE-9_Slog_Project.exe`
Expected: 窗口正常打开；在 exe 同目录出现 `sessions/`；关闭后重新打开，日志仍显示「尚未连接相机」

- [ ] **Step 5: 提交**

```bash
git add build/ tests/test_paths.py
git commit -m "build: PyInstaller spec and onefile smoke test"
```

---

### Task 13: 教程站 — 中文

**Files:**
- Create: `docs/zh-CN/index.html`, `docs/assets/style.css`

**Interfaces:**
- Produces: 可在浏览器直接打开的静态页，无外部依赖

- [ ] **Step 1: 写样式**

单文件 CSS，系统字体栈，最大宽度 760px，代码块与提示框（`<div class="warn">` 红框、`<div class="note">` 蓝框）。

- [ ] **Step 2: 写正文十一节，覆盖设计文档 §9 的九个坑**

1. 开始之前（机型/版本自检、会改什么、不会改什么）
2. 下载与解压（Releases 在哪，为什么没有安装程序）
3. Windows 拦截了这个程序（SmartScreen → 更多信息 → 仍要运行）
4. 杀毒软件报毒（为什么会被报：要直接访问 USB 设备；给源码链接）
5. 给相机装驱动（第一次，Zadig，大容量存储设备）
6. 连接并检查（点按钮，看到什么算成功）
7. 给相机装驱动（第二次，切服务模式后新出现的设备）
8. 开启 PP 放行，然后重启（解释为什么要重启）
9. 把功能写进 Fn 槽位，然后重启
10. 在相机上确认——**以及「菜单里出现了 ≠ 功能能用」**
11. 改回去：单条恢复、全部恢复原厂、卸掉驱动让 Windows 恢复正常相机访问

每节配「你会看到什么」和「不对的话怎么办」。截图位置留 `<img src="../assets/img/xxx.png" alt="...">`，文件名先定死：`zadig-1.png`、`zadig-2.png`、`smartscreen.png`、`window-connected.png`、`camera-fn.png`。

- [ ] **Step 3: 写首页警告**

页面顶部固定一个红框：本工具只支持 ILCE-9 / 6.00；会改机身备份参数；77 项里 74 项从未在实机上试过；`0x64` 已知会卡死；风险自负。

- [ ] **Step 4: 验证**

Run: 浏览器打开 `docs/zh-CN/index.html`
Expected: 无控制台报错，所有外部资源均为相对路径，断网可读

- [ ] **Step 5: 提交**

```bash
git add docs/zh-CN docs/assets/style.css
git commit -m "docs(zh-CN): nine-section tutorial with safety banner"
```

---

### Task 14: 教程站 — 英文与语言切换

**Files:**
- Create: `docs/index.html`

**Interfaces:**
- Produces: 英文页，顶部与中文页互相链接

- [ ] **Step 1: 写英文正文**

与中文页一一对应的九节，术语用 Sony 官方英文菜单名（Picture Profile、S-Log Display Assist）。

- [ ] **Step 2: 加语言切换**

两页顶部各放一行 `English | 简体中文` 链接。

- [ ] **Step 3: 验证**

Run: 浏览器打开 `docs/index.html`，点「简体中文」→ 回到中文页，再点回来
Expected: 双向跳转正常

- [ ] **Step 4: 提交**

```bash
git add docs/index.html docs/zh-CN/index.html
git commit -m "docs: English tutorial and language switcher"
```

---

### Task 15: README、许可与发布准备

**Files:**
- Create: `README.md`, `README.zh-CN.md`, `NOTICE`, `LICENSE`

- [ ] **Step 1: 写两份 README**

都包含：一句话说明、支持机型限制、下载链接（指向 Releases）、教程站链接、风险声明、构建方法、许可证。英文版在前。

- [ ] **Step 2: 写 NOTICE**

列出 PMCA（MIT，链接上游）、pyusb（BSD）、libusb（LGPL-2.1，动态链接，链接上游）；并注明 `a9_fn_chinese_names.json` 中 64 个字符串摘自 Sony 固件界面资源，仅用于与相机菜单对应，本项目不主张其权利。

- [ ] **Step 3: 跑完整测试**

Run: `python -m unittest discover -s tests -v`
Expected: 全部通过（约 41 项）

- [ ] **Step 4: 提交**

```bash
git add README.md README.zh-CN.md NOTICE LICENSE
git commit -m "docs: README, third-party notices, MIT license"
```

---

## 依赖顺序

Task 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 串行（每个都改 `core.py`）。9 → 10 → 11 串行。12、13、14 可并行。15 最后。

## 不在本计划内

- 实机测试。所有任务只在 `FakeCamera` 上验证；真机验证由用户在设计文档批准后自行执行。
- 截图素材（设计文档 §11 已列为遗留项）。
- CI 配置与 GitHub Pages 启用（发布时手动操作）。
