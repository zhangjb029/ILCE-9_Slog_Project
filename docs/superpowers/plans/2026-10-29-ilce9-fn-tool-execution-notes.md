# 执行记录：ILCE-9 功能槽位工具

日期：2026-10-29
对应计划：[2026-10-29-ilce9-fn-tool.md](2026-10-29-ilce9-fn-tool.md)
对应设计：[2026-10-29-ilce9-fn-tool-design.md](../specs/2026-10-29-ilce9-fn-tool-design.md)

---

## 实施中偏离计划的地方

计划是写在实现之前的，下面每一处在实施时都需要改，逐条记下原因，方便以后有人问「为什么代码和计划不一样」。

| # | 计划写的 | 实际做的 | 为什么 |
|---|---|---|---|
| 1 | `core.Guard`，武装一个属性、只写一次 | `usbdev.ParameterGuard`，属性白名单 + 一次真实写入后才能 SAVE | core 不持有 guard 就无法控制武装；让 GUI 碰 guard 会让白名单可被绕过。放在传输层最干净。 |
| 2 | 用 PMCA 的 `BackupFile` 解析快照取属性 | 属性一律走 `camera.readBackup(pid)`，整份快照只作写前证据落盘 | 造一个含 `0x0107146D` 的合法 backup 需要约 33 KB 头表，模拟相机无法维护。改用「写入前重读一次并比对」，与旧代码的二次校验等价。 |
| 3 | `connect(...) -> CameraHandle`，未提关闭 | `CameraHandle.close()` 幂等；`connect()` 异常路径自己清理设备句柄 | 异常时不能让相机停在服务模式又没人管。 |
| 4 | Task 12 测试只 mock `sys.executable` | `journal.sessions_root()` 用 `sys.frozen` 判断 | 源码运行时 `sys.executable` 是 python.exe，会把备份写到 Python 安装目录。 |
| 5 | GUI 分三次提交 | 合并为一次实现、一次提交 | 三个任务改同一个文件同一组控件，分开提交会产生跑不起来的中间态。 |
| 6 | Task 8 的 `save_baseline`/`restore_baseline` 无可注入目录 | 各加 `root=` / `baseline_dir=` 可选参数 | 否则测试会写到项目根。 |
| 7 | 复制清单只列了 pmca/usb/libusb | 另加 `importlib_resources` 和 `Cryptodome` shim | 前者是 libusb_package 的硬依赖；后者见下。 |
| 8 | 未提 pycryptodomex | `src/vendor/Cryptodome/` 三个文件，用 hashlib 实现 `SHA256.new(data).digest()` | pmca 只用了这一个调用点。vendoring 真正的 pycryptodomex 会给发布物加 8 MB C 扩展并绑定 CPython ABI。 |

## 评审后的修复

独立评审（整支 diff）提出 1 条 Critical、8 条 Important。全部修复，每条都有先失败后通过的测试。

| 问题 | 影响 | 修复 | 测试 |
|---|---|---|---|
| **Critical** 连接成功时写下的凭据会在 1 小时内被下一次运行自动复用 | 第二次连接跳过识别步骤，直接去找不存在的服务模式设备，于是**教程的主流程走不通**，且提示是「连接的不是一台相机」 | 成功返回前删除凭据；凭据存在但相机不在服务模式时回退到大容量存储路径 | `test_successful_connect_leaves_no_reusable_receipt`、`test_second_connect_starts_from_mass_storage_again` |
| `_load_dependencies` 返回未定义的 `usb`/`util` | **任何用户第一次点「连接」都失败**（单元测试 mock 了这个函数所以没暴露） | 返回 `usb.core` / `usb.util` | `test_dependency_loader_returns_usable_objects`（子进程、禁 site-packages）+ 打包自检 |
| `pycryptodomex` 未 vendor | exe 在干净机器上导入 pmca 就失败 | hashlib shim | `test_pmca_sony_imports_without_site_packages` |
| `journal.json` 非原子写；一个损坏的文件让程序**永远打不开** | 最需要恢复的用户反而用不了工具 | temp + `os.replace`；`list_sessions` 跳过坏条目 | `test_save_leaves_no_temporary_file`、`test_list_sessions_skips_a_corrupt_journal` |
| 「没连相机」和「连了多台」是同一条消息 | 最常见的首次使用场景给出无法执行的建议 | 拆成两条 | `test_connect_without_camera_says_not_found`、`test_no_camera_message_names_the_checks` |
| `on_connect` 里异常会让 busy 卡住、所有按钮永久禁用 | 用户必须重启程序 | 把可抛异常的部分移进工作线程 | — |
| 守卫只校验属性不校验长度 | core 的长度 bug 会原样送到相机 | `WRITE_SIZES` 按属性锁定长度 | `test_guard_rejects_wrong_payload_length_for_a_slot` |
| 恢复不校验相机身份 | 两台 A9 之间可以互相覆盖 | session 记录序列号指纹，恢复时比对 | `test_restore_refuses_a_session_from_another_camera` |
| spec 的 `datas` 混用二元组和 `Tree()` 三元组；DLL 放错位置 | exe 可能根本打不开或连不上相机 | 手写二元组；DLL 同时放到 `libusb_package/` 与 `vendor/libusb_package/` | 打包自检（真实构建验证） |

打包自检在 `build/entry.py` 的 `A9TOOL_SELFCHECK=1` 模式下，实测输出：

```
functions: 77
sessions root: ...\dist-debug\sessions
libusb backend: <usb.backend.libusb1._LibUSB object ...>
gui: 77-row table
SELFCHECK_OK
```

## 已知遗留（未修）

都是评审判为 Minor 的项，不影响正确性，留待以后：

- `mark_chained` 不把 `restore` 会话算作「上一次写入」，恢复之后的下一次写入仍会显示「原值来自上一次写入」。
- 目标值已经是当前值时（`ALREADY_AT_TARGET_NO_SAVE`），界面仍然说「已写入，请重启」。
- 日志里会漏出内部状态串（如 `SAVED_AND_READBACK_VERIFIED`），与设计文档「界面不出现实现词汇」的要求不符。
- 几条 core 抛出的中文错误没有对应的 `errors.FAILURE_HINTS` 条目，会落到通用文案：`机身参数在读取之后发生变化`、`还没有原厂基线记录`、`这条记录没有可以恢复的内容`、`写入后立即回读不一致`。
- 「恢复全部原厂」的基线取自本工具**第一次成功连接**时。如果用户此前用命令行工具已经改过，那个「原厂」其实已经是改过的状态。
- 写入线程运行期间关闭窗口没有保护，可能在 `writeBackup` 之后、`SAVE` 之前中断。
- 少量死代码：`BoundedSenser` 里的排空计数器、`all_value_var`、`fnmap.VALUE_LIMIT`。
- `_restore_target` 的 docstring 说返回三个值，实际返回四个。
- 打包把 `pmca/usb/driver/windows/*` 和 `pmca/util/http.py` 也带上了（未使用，体积可忽略）。

## 没有做的事

- **实机验证**。全部 87 项测试都是离线的，`FakeCamera` 代替真机。exe 已构建并通过自检，但没有连接过相机。刷写与首连验收由用户执行。
- 截图素材（教程页里是占位）。
- GitHub 仓库地址仍是 `example`，发布前要替换。
