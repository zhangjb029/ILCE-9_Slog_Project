# ILCE-9_Slog_Project

把 Picture Profile（图片配置文件）和 SLog 显示辅助放进 Sony A9（ILCE-9，固件 6.00）的 Fn 菜单——顺带还有相机里本来就有、但官方界面没给入口的另外 75 个功能。

[English](README.md) · [**图文教程**](https://example.github.io/ILCE-9_Slog_Project/zh-CN/) · [**下载**](https://github.com/example/ILCE-9_Slog_Project/releases)

---

## 它做什么

A9 里编译进了 Picture Profile 和 SLog 显示辅助，但没有菜单入口。这个工具通过索尼自己的服务模式参数接口，往十二个 Fn 槽位之一写入一个字节的保存值。相机用**自己的**函数表解析这个字节，于是入口就出现在 Fn 菜单里——**没有改固件**。

两项功能已在实机上确认可用：

| 功能 | 保存值 | 实机结果 |
|---|---|---|
| Picture Profile | `0x3A` | Fn1 出现入口，录制画面变化，重启后仍在 |
| SLog 显示辅助 | `0x36` | Fn7 出现入口，功能正常，重启后仍在 |

另外 75 个保存值来自相机自己的函数表，在程序里可以选。**这些都没有在实机上验证过。** 其中一个——像素转换多重拍摄（`0x64`）——已知会在拍完第一张后卡死、需要拔电池，界面上做了标记。

## 前提

- Sony **ILCE-9**，固件 **6.00**。其他机型和版本一概不支持，程序会在写入前拒绝。
- Windows 10 或 11。
- 需要 [Zadig](https://zadig.akeo.ie/) 装 USB 驱动，教程里有详细步骤。

## 怎么用

请先读[图文教程](https://example.github.io/ILCE-9_Slog_Project/zh-CN/)。里面讲了两次驱动安装、Windows 的拦截提示、为什么存储卡会消失，以及怎么把一切改回去。

简版：相机切到大容量存储 → 用 Zadig 把驱动换成 libusb-win32 → 打开程序 → 开启 PP 放行 → 重启相机 → 把功能写进槽位 → 再重启 → 按 Fn 键。

## 安全性

每次写入之前，程序都会在 exe 旁边存一份完整备份和事务记录，然后才碰相机；每次写入都可以在程序里撤销。「恢复全部原厂」会把相机恢复到第一次使用本工具之前的状态。

这不是索尼的工具。修改相机参数可能导致保修失效。请在自己的相机上、自担风险地使用。

## 自己构建

只对构建者需要，最终用户什么都不用装。

```powershell
pip install pyinstaller
powershell -File build/build_exe.ps1
```

产物：`dist/ILCE-9_Slog_Project.exe`（约 20 MB，单文件，未签名）。

## 测试

```powershell
python -m unittest discover -s tests -t .
```

全部离线：用 `FakeCamera` 代替真机，不需要相机也不需要 USB 后端。共 70 项，含 Tk 控件状态检查。

## 原理

Fn 槽位里的保存字节由 `viewUnified4.so` 的跳转表解析成内部节点 id，再查 Fn 运行根数组。这条路径**不经过主菜单树**，所以 Fn 能出现入口，而设置菜单里依然没有 Picture Profile 节点。解析器在查表前会拒绝任何大于 `0x6E` 的字节。

PP 功能放行属性（`0x00880000`，五个偏移置 `0x02`）必须先打开，否则依赖 PP 的条目解析不出东西。

## 许可

MIT，见 [LICENSE](LICENSE)。第三方组件和固件派生表的来源写在 [NOTICE](NOTICE) 里。
