# 制作工具与示例的来源和许可

- A9 原生色表、拟合模型、感知细化和参考解析代码取自本项目冻结 R15／227 款制作工作；摘要和来源项见 `SOURCE_ORIGINS.json`。固件衍生数据及继承代码遵循仓库现有 [固件声明](../../src/data/releases/NOTICE.md) 和 [PolyForm Noncommercial 1.0.0](LICENSE-PolyForm-Noncommercial.txt)，不因根目录 MIT 声明而覆盖上游条款。
- `a9w/encode_sony_sds_adpcm.py` 来自冻结的 [PCIEARIA/A6400-Extra-Menu](https://github.com/PCIEARIA/A6400-Extra-Menu)，遵循 PolyForm Noncommercial 1.0.0。原注释、算法和 A6400 槽位别名保留；A9 槽位映射由教程单独说明。`make_burst_wps.py` 中编码搜索亦沿用该编码器算法。
- `lut/examples/glassmeter-400d.cube`：Film simulation from **GlassMeter by Glass Works**，<https://glass-works.ai>；许可 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。保留原 CUBE 注释与署名。影片名称为各权利人商标；这是社区解释，不是品牌官方 LUT 或背书。派生 A9P／预览分享时继续保留来源和署名。
- 来源目录仅记录所选资源的尺寸、SHA256、输入输出编码与相对来源路径；并不授予全部原始 LUT 的统一再分发许可。其他滤镜来源分别按 `filters/provenance/source_docs` 处理。
- 不含私人音频。用自有或已获授权素材生成声音包；本工具许可不替代音频本身的许可。

数学模块和声音生成器保持原算法。便携入口新增仓库路径适配、参数界面与输出报告；SHA256 参考 C 文件仅将间接头文件替换为 `<stdint.h>`，其函数体未改动。参考 C 是格式和机制依据，不能据此声称完整 V8 模块可单独编译。
