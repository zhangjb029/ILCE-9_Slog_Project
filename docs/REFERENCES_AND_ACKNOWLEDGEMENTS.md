# 参考文献与致谢总表（References & Acknowledgements）

本文档汇总 **ILCE-9_Slog_Project**（含 **v1.9.0 / v1.9.1 R15NH + V8 + 227 款 A9P 滤镜**子发行分支及跨机型研究阶段）所集成、借鉴、拟合依据与对比研究过的开源仓库、工具链与色彩资源，以及各自保留的许可与边界说明。

> **许可与归属边界声明**：
> 1. 列出某仓库仅代表思路参考、协议对账、离线拟合或版本对比，**不代表直接搬运其二进制或原厂固件偏移**；本项目的地址、签名与部署流程均基于 ILCE-9（固件 6.00）独立核验。
> 2. 仓库根目录的 MIT 许可**不覆盖**各第三方组件、A6400 上游源码（PolyForm Noncommercial 1.0.0）及 227 款 LUT 来源原有的署名、非商业或相同方式共享条款（另见 [`NOTICE`](../NOTICE)、[`tools/media/NOTICE.md`](../tools/media/NOTICE.md) 与 [`filters/README.md`](../filters/README.md)）。
> 3. Sony、ILCE-9、α7R III、α6400、ZV-E10、Picture Profile、S-Log 等商标归 Sony Group Corporation 或其权利人所有；本项目与原厂或上述第三方项目均无官方从属关系。

---

## 一、直接依赖、移植参考与核心上游

以下仓库直接支撑了本项目的 USB 通信、菜单注入、V8 浮层／快门声编码、5 GHz 解锁、R11–R15NH 创意外观拟合与构建打包。

| 仓库 | 许可 / 固定基准 | 在本项目中的作用与边界 |
|---|---|---|
| [PCIEARIA/A6400-Extra-Menu](https://github.com/PCIEARIA/A6400-Extra-Menu) | PolyForm Noncommercial 1.0.0 | **V8 悬浮菜单与快门声编码直接上游**。借鉴其 `nflasha10` + `preload` 浮层架构、触控交互与无终端分片安全部署思路；`tools/media/a9w/encode_sony_sds_adpcm.py` 直接沿用其冻结的 Sony 24 kHz 32-byte SDS ADPCM 编码器算法（保留原注释、算法与 PolyForm 非商业条款）。 |
| [robinshie/Sony_A7M3](https://github.com/robinshie/Sony_A7M3) | MIT（固定提交 `e6bbfafb55570a5de34e75c195e7e1c780d03340`） | **A9 原生菜单移植核心技术来源**。提供了“将菜单扩展挂载到真正的菜单创建调用而非 `DT_INIT`”的关键思路；A9 的函数地址、属性记录长度与分区布局均为独立重定位与实机验证，未复制 A7M3 偏移表或二进制。 |
| [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware) | 见原仓库说明 | **R11/R12/R15 新增创意外观配色依据与 F0 快门声对照参考**。本项目早期新增创意外观依据其公开的 LUT 与外观定义进行双源属性拟合，未直接分发原仓库文件；另在 A9 快门音调研中用于对照 F0 编码与曝光事件触发机制。 |
| [dino2048/ZV-E10-5GHz-WiFi-Unlock](https://github.com/dino2048/ZV-E10-5GHz-WiFi-Unlock) | MIT | **5 GHz Wi-Fi 解锁思路与交叉验证参考**。与 ZV-E10 对比法规配置机理；A9 实际采用自身的 `00A5000C`（`09 -> 03` / XR77）选择机制，未照搬 ZV-E10 地址或菜单库修改。 |
| [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE) | MIT | **USB 服务模式通信基础**。`src/vendor/pmca/` 打包并使用了其 `usb/`、`util/` 与 `backup/` 子包用于连接与服务模式文件通道（另有 [adamwuqwq/Sony-PMCA-RE](https://github.com/adamwuqwq/Sony-PMCA-RE) 作为 `libjit` / `system-dump` 相关社区分支参考）。 |
| [pyusb/pyusb](https://github.com/pyusb/pyusb) | BSD | Windows / 桌面端 USB 后端封装（打包于 `src/vendor/usb/`）。 |
| [libusb/libusb](https://github.com/libusb/libusb) | LGPL-2.1 | 运行时动态加载的 `libusb-1.0.dll` 共享库源码来源（`src/vendor/libusb_package/`）。 |
| [python/importlib_resources](https://github.com/python/importlib_resources) | Apache-2.0 | 资源读取兼容支持包（打包于 `src/vendor/importlib_resources/`）。 |

---

## 二、227 款 A9P 滤镜与色表拟合来源（Provenance）

R15NH 配套的 **227 款 A9P V2** 离线拟合滤镜库保留各来源原许可，完整溯源文档与原始说明存放在 [`filters/provenance/source_docs/`](../filters/provenance/source_docs/) 与 `filters/CATALOG.csv`：

| 来源仓库 / 项目 | 许可与署名要求 | 拟合覆盖内容与备注 |
|---|---|---|
| [TrondW/glassmeter-film-looks](https://github.com/TrondW/glassmeter-film-looks) | **CC BY 4.0**（署名：`Film simulations from GlassMeter by Glass Works (glass-works.ai)`） | 30 款 GlassMeter 胶片模拟解释；同时在 `tools/media/lut/examples/glassmeter-400d.cube` 提供自包含离线拟合示例。 |
| [Viyerelu23333/custom-image-luts](https://github.com/Viyerelu23333/custom-image-luts) | **CC BY-NC-SA 4.0**（允许用于照片/视频创作，禁止付费售卖或打包进付费产品） | 59 款宾得 K-1 Custom Image 相对风格与变体（以 Natural JPEG 为基底的社区拟合，非理光/宾得官方导出表）。 |
| [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles) | **CC BY-NC-SA 4.0**（另有社区转换衍生 [onepill/FujifilmCameraProfiles](https://github.com/onepill/FujifilmCameraProfiles)） | 富士相机配置文件与社区 ProPhoto/sRGB 转换 LUT（70 款富士拟合来源之一）。 |
| [pyrocat101/Fujifilm-LUTs](https://github.com/pyrocat101/Fujifilm-LUTs) | 见原仓库与 `filters/provenance/source_docs/` | 富士胶片仿真 LUT 参考资源。 |
| [DeMeerleerGilles/Lumix-film-simulation](https://github.com/DeMeerleerGilles/Lumix-film-simulation) | 见原仓库与 `filters/provenance/source_docs/` | 6 款社区 V-Log 跨品牌变换（徕卡、ARRI、RED 与电影印片模拟）。 |
| [phddy/nikon-recipes](https://github.com/phddy/nikon-recipes) & [tvgenious89/nikon-pc](https://github.com/tvgenious89/nikon-pc) | 见原仓库与 `filters/provenance/source_docs/` | 尼康 Picture Control 配方与本地 `.NP3`/`.NCP` 工具研究参考。 |
| [YahiaAngelo/Film-Luts](https://github.com/YahiaAngelo/Film-Luts) | 见原仓库声明 | 被上游 [A6400-Extra-Menu](https://github.com/PCIEARIA/A6400-Extra-Menu) 引用的开源 `.cube` 胶片查找表整理仓库。 |
| 官方参考 LUT 集合 | 保留各厂商原条款 | 富士官方 LUT、松下 VariCam（35 款 E-E 完整范围与 22 款创作者映射）、尼康官方 N-Log 与 RED 合作外观等。 |

---

## 三、跨机型逆向与工程研究参考仓库（按机型分类）

除直接集成与拟合来源外，本项目在架构演进、分区防砖、纯内存（Pure-RAM）调试、原生 UI 扩展、快门音与仿真验证研究中，深度对照了以下各机型开源项目：

### 1. Sony A7R3（`ILCE-7RM3`, FW 3.10）

#### `kan-xx` 组织（10 仓模块化常驻底座方案）
| 仓库 | 主要技术与研究方向 |
|---|---|
| [kan-xx/.github](https://github.com/kan-xx/.github) | 组织总纲、工程设计原则（零 `.text`/固件改写、Fail-Closed 原则）与合规声明 |
| [kan-xx/a7r3-usb-senser](https://github.com/kan-xx/a7r3-usb-senser) | 免拆机 USB 3.1 SuperSpeed 包对齐握手、串口节流与 `/tmp_bt` 纯内存暂存 SDK |
| [kan-xx/sony-fw-inspect](https://github.com/kan-xx/sony-fw-inspect) | 非破坏性分块固件采集、`WBI1` 解包、`ld-2.11.2.so` `DT_RELCOUNT=0` 修复与 ARM/Thumb/MIPS32 三核 Unicorn 无桩仿真 |
| [kan-xx/a7r3-boot-runtime](https://github.com/kan-xx/a7r3-boot-runtime) | `libIMDB.so` 纯数据段注册表扩展、60 秒双槽 SHA-256 自愈守护（`a7r-boot-guard`）与只读 `/usr` 原子发布器 |
| [kan-xx/a7r3-kernel-video-quarantine](https://github.com/kan-xx/a7r3-kernel-video-quarantine) | 断电即净的无符号 `.ko` 动态探针与视频编码总线 Fail-Closed 隔离门控 |
| [kan-xx/a7r3-custom-shutter](https://github.com/kan-xx/a7r3-custom-shutter) | SD 卡自定义快门音、`AudioIP` 编码、`16 ms` 曝光起点 Hook 与双队列连拍抢占调度 |
| [kan-xx/a7r3-native-ui](https://github.com/kan-xx/a7r3-native-ui) | 27 槽 C++ `View` 虚表继承、`WidgetServer` UTF-8 中文图层与原生菜单路由（`View 0xFFC`） |
| [kan-xx/a7r3-full-touch](https://github.com/kan-xx/a7r3-full-touch) | 主菜单/`Fn`/二级页全界面触控与 JPEG/RAW 回放双指捏合缩放 |
| [kan-xx/a7r3-creative-look-lut](https://github.com/kan-xx/a7r3-creative-look-lut) | 跨代 `FL2/FL3` 色彩解析、`.ARW` `SR2SubIFD` 解密与 `CamCore` `5×9×9`（8-Bank `1,620 B`）编解码 |
| [kan-xx/a7r3-experiment-diary](https://github.com/kan-xx/a7r3-experiment-diary) | 横跨 18 天的工程实验日志合订本与排障记录 |

#### Kevin（Pure-RAM 原生第 7 大类方案）与早期 A7R3 上游
| 仓库 | 主要技术与研究方向 |
|---|---|
| [Kevin2651486613/a7r3-ram-extension-menu](https://github.com/Kevin2651486613/a7r3-ram-extension-menu)（重点分支：[feat/native-tab7-a1](https://github.com/Kevin2651486613/a7r3-ram-extension-menu/tree/feat/native-tab7-a1)） | 零闪存改写的纯内存（`/tmp_bt` + `ptrace`）框架；`feat/native-tab7-a1` 实现零 `.uxc` 修改的原生第 7 大类（Tab 7）、`GEN_Icon` 缩放与 `TextSprite` UTF-8、纯内存菜单触控、电子快门 `.wav` 机内转码发声、双显 HUD 与回放对焦框；`main` 分支保留 MD3 双页自绘 UI。 |
| [Bigrabbit057/sony-a7r3-creative-studio](https://github.com/Bigrabbit057/sony-a7r3-creative-studio) | Kevin 在 `CREDITS.md` 引用的 A7R3 早期上游，涵盖双显 HUD、显存绘制与运行时内存注入辅助参考。 |

---

### 2. Sony A6400 / A6100（`ILCE-6400` / `ILCE-6100`）

| 仓库 | 主要技术与研究方向 |
|---|---|
| [PCIEARIA/A6400-Extra-Menu](https://github.com/PCIEARIA/A6400-Extra-Menu) | 见第一节；支持 A6400 2.00 与 A6100 的浮层、胶片与安全无终端分片部署参考。 |
| [ivica00/sony-a6400-research](https://github.com/ivica00/sony-a6400-research) | A6400 底层研究与早期代码基础（被 `A6400-Extra-Menu` 致谢）。 |
| [DevCrashDay/a6400](https://github.com/DevCrashDay/a6400) | A6400 homebrew 平台与「The Ritual」机内滤镜研究（被 `A6400-Extra-Menu` 致谢）。 |

---

### 3. Sony A7M3（`ILCE-7M3`）

| 仓库 | 主要技术与研究方向 |
|---|---|
| [robinshie/Sony_A7M3](https://github.com/robinshie/Sony_A7M3) | 见第一节；A7M3 固件分析与原生菜单创建时机挂载来源。 |
| [Derek2011cc/A7M3-Firmware-QEMU-Boot-Experiment](https://github.com/Derek2011cc/A7M3-Firmware-QEMU-Boot-Experiment) | A7M3 QEMU 启动仿真、OSD 与输入链路实验。 |

---

### 4. Sony ZV-E10（同代 `CXD90045` 平台）

| 仓库 | 主要技术与研究方向 |
|---|---|
| [peiyuanix/zv-e10-creators-app-patcher](https://github.com/peiyuanix/zv-e10-creators-app-patcher) | Android 版 Creators' App 3.5.0 旧机型放行与 USB/Wi-Fi 会话修复补丁，用于对照 A9 PTP/SDIO 兼容能力。 |
| [peiyuanix/zv-e10-monitor-control-patcher](https://github.com/peiyuanix/zv-e10-monitor-control-patcher) | Android 版 Monitor & Control 3.0.1 兼容分析与补丁。 |
| [Mrliujunwen/zve10-shutter-sound-tool](https://github.com/Mrliujunwen/zve10-shutter-sound-tool) | ZV-E10 快门音资源管理、24 kHz 编解码与原生音量属性操作对照。 |
| [cokeenet/zve10-qemu](https://github.com/cokeenet/zve10-qemu) | ZV-E10 QEMU 引导、原生节点插入、Hook 冲突分析、硬件恢复及菜单壳研究。 |
| [chocotan/zve10-qemu](https://github.com/chocotan/zve10-qemu) | ZV-E10 QEMU 仿真与菜单输入研究对照。 |
| [dino2048/ZV-E10-5GHz-WiFi-Unlock](https://github.com/dino2048/ZV-E10-5GHz-WiFi-Unlock) | 见第一节；ZV-E10 原生双频菜单解锁与网络路径研究。 |
| [dino2048/zv-e10-toolkit](https://github.com/dino2048/zv-e10-toolkit) | USB 服务备份、双读核验、BootROM 与 fastboot 分区恢复工具链思路参考。 |
| [qn06142/zv-e10-re](https://github.com/qn06142/zv-e10-re) | 基于 `Sony-PMCA-RE` 的 ZV-E10 服务模式、OSAL/UIPC、`.uxc` 资源工具与 USB UVC 图像缓冲研究。 |
| [nolan2628/ZVE10-Astra-Public](https://github.com/nolan2628/ZVE10-Astra-Public) | 跨架构/跨代 UI 应用框架静态兼容性与 ABI 缺口评估参考上游。 |
| [nolan2628/Sony-ZVE-10-Camtool](https://github.com/nolan2628/Sony-ZVE-10-Camtool) | 服务模式与备份设计公开资料（原 README 未授予开源复用/再分发许可，仅作技术比对记录，不作代码移植来源）。 |

---

### 5. 五代机型参考（A7M4 / A7R5 / A7C2 / A7CR / A6700，`CXD90057` / AArch64）

| 仓库 | 适用机型与研究方向 |
|---|---|
| [Erlla/sony-a7m4-custom-firmware](https://github.com/Erlla/sony-a7m4-custom-firmware) | A7M4；见第一节（Creative Look LUT 定义、F0 音频编码与异步播放链路对照）。 |
| [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE) & [DavidBuchanan314/Sony-ILCE-7M4-Linux](https://github.com/DavidBuchanan314/Sony-ILCE-7M4-Linux) | A7M4；固件认证链分析、Linux 启动与底层逆向研究。 |
| [chocotan/a7m4-qemu](https://github.com/chocotan/a7m4-qemu)、[chocotan/a7c2-qemu](https://github.com/chocotan/a7c2-qemu)、[chocotan/a7c2-re](https://github.com/chocotan/a7c2-re) | A7M4 / A7C2；QEMU 仿真、原厂 UI 链与输入链路逆向研究。 |
| [QAQLeonard/a7c2-fl23-research](https://github.com/QAQLeonard/a7c2-fl23-research) & [QAQLeonard/a7c2-tools](https://github.com/QAQLeonard/a7c2-tools) | A7C2；FL2/FL3 色彩、工具链与 USB 服务通信细节对比。 |
| [lzh2016zzz/a7cr-fl23-research](https://github.com/lzh2016zzz/a7cr-fl23-research)、[YuuLuo/a7c2-service-preload](https://github.com/YuuLuo/a7c2-service-preload)、[ChambersXDU/sony-a7c2-research](https://github.com/ChambersXDU/sony-a7c2-research)、[cjryrx/a7c2-precapture](https://github.com/cjryrx/a7c2-precapture) | A7CR / A7C2；FL23、`service-preload` 注入与预拍摄研究参考。 |
| [Hearts-Ace/sony-a7r5-custom-firmware](https://github.com/Hearts-Ace/sony-a7r5-custom-firmware) & [751K/sony-look-bridge](https://github.com/751K/sony-look-bridge) | A7R5；自定义固件与创意外观色彩桥接研究。 |
| [xyzhangxin/sony-a6700-powerful](https://github.com/xyzhangxin/sony-a6700-powerful) | A6700；五代机身功能研究参考。 |

---

## 四、通用解包工具与历史研究基石

- **固件解包与格式研究**：[ma1co/fwtool.py](https://github.com/ma1co/fwtool.py)、[DavidBuchanan314/fwtool.py](https://github.com/DavidBuchanan314/fwtool.py)、[q19032/Sony-firmware-unpacker](https://github.com/q19032/Sony-firmware-unpacker)
- **OpenMemories 系列历史项目**：[ma1co/OpenMemories-Framework](https://github.com/ma1co/OpenMemories-Framework)、[ma1co/OpenMemories-Platform](https://github.com/ma1co/OpenMemories-Platform)、[ma1co/OpenMemories-Tweak](https://github.com/ma1co/OpenMemories-Tweak)、[ma1co/OpenMemories-AppList](https://github.com/ma1co/OpenMemories-AppList)、[ma1co/PMCADemo](https://github.com/ma1co/PMCADemo)

---

感谢上述所有开源开发者、逆向研究者、实机测试贡献者与色彩社区作者公开分享工具、数据与踩坑记录。
