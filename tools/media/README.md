# R15 / V8 离线素材制作代码

两份完整教程：

- [LUT 拟合与 A9P 制作](../../docs/authoring/R15_V8_LUT拟合与A9P制作详解.md)
- [快门声 SDS 编码与 A9W 制作](../../docs/authoring/R15_V8_快门声A9W制作详解.md)

目录均为电脑端制作、校验和参考代码，不调用 USB，不部署固件。

| 目录 | 用途 |
|---|---|
| `lut/fit_a9p.py` | 原 227 款／R15 配方的便携入口，输出双表、A9P 和误差报告 |
| `lut/{a9_model,color_delta,fit_metrics,refine,lut}.py` | 冻结数学实现；算法字节沿用原项目 |
| `lut/runtime.py` | 使用仓库固定原厂表和冻结曲线，代替旧工作区路径 |
| `lut/data` | 合成基线、颜色压扩曲线、来源目录和原 27 款目标输入指纹 |
| `lut/examples` | 一份带 CC BY 4.0 署名的 GlassMeter CUBE 示例 |
| `a9w/` | V8 原编码器、三槽／四槽生成器、封包及只读检查工具 |
| `a9w/reference` | V8 实际 C 解包、双槽存储、调度参考和 PC 解析器入口 |
| `tests` | 独立离线检查，不加入主程序运行依赖 |

在仓库根目录运行：

```sh
python -m pip install -r tools/media/lut/requirements.txt
python -B -m unittest discover -s tools/media/tests -v
```

声音工具仅使用 Python 标准库；非 24 kHz 单声道 PCM16 WAV 的输入还需要系统已有 `ffmpeg`。LUT 拟合使用独立 NumPy／SciPy／CPU PyTorch 环境，不是 A9Tool EXE 的依赖。

来源与逐文件摘要见 [SOURCE_ORIGINS.json](SOURCE_ORIGINS.json)，验证结果见 [VALIDATION.json](VALIDATION.json)。原 27 款的冻结目标 NPZ 与旧版双表不在本次小型制作代码集中；若重拟合这些内置项，需自备与清单匹配的原输入。随附 CUBE 示例可以在仓库内完成自包含的拟合、封装及检查。

算法、参考代码、曲线和素材各自的许可见 [NOTICE.md](NOTICE.md)。没有打包私人声音、固件整分区、相机配置或实机日志。本次只更新仓库文档和制作工具，不修改软件版本，也不创建 Release。
