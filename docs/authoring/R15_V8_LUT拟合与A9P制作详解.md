# R15／V8：LUT 拟合与 A9P 制作详解

本文面向要自己制作滤镜、复查拟合结果或继续开发的读者。依据冻结的 R15 signed7 拟合代码、227 款外部 LUT 制作代码及当前 A9P 编解码器整理。适用机型为 ILCE-9／6.00，导入后端为 R15 NAME HELP；V8 提供悬浮菜单入口及参数操作，LUT 文件仍由 R15 管理。

## 1. 输入、输出与代码位置

制作链路为：

```text
有明确输入／输出颜色编码的参考 CUBE
→ 在冻结 RGB 样本上计算目标颜色
→ 转到实验性 Y／压缩色度模型
→ 分别拟合 00030004 与 00030005 两张原生表
→ signed7 量化、亮度单调投影、保留原厂尾部
→ 独立验证和测试误差
→ A9P V2，放入 SD 卡由 R15 导入
```

| 文件 | 责任 |
|---|---|
| [`fit_a9p.py`](../../tools/media/lut/fit_a9p.py) | 便携命令入口、冻结配方、双表拟合、报告和写卡副本 |
| [`lut.py`](../../tools/media/lut/lut.py) | CUBE 读取、三线性插值、色域／传递函数转换 |
| [`a9_model.py`](../../tools/media/lut/a9_model.py) | 原生节点、压扩、反求原厂坐标、有界初拟合与量化 |
| [`fit_metrics.py`](../../tools/media/lut/fit_metrics.py) | 原厂残差锚定和独立误差统计 |
| [`refine.py`](../../tools/media/lut/refine.py) | PyTorch 感知细化，验证集选候选 |
| [`color_delta.py`](../../tools/media/lut/color_delta.py) | CIEDE2000 指标 |
| [`runtime.py`](../../tools/media/lut/runtime.py) | 从本仓库加载原厂双表和冻结颜色压扩曲线 |
| [`release_a9p.py`](../../src/a9tool/release_a9p.py) | A9P V2 封装、检查、UTF-8 名称和原生表检查 |

数学模块沿用原文件；本次新增的是路径适配与命令入口。摘要见 [SOURCE_ORIGINS.json](../../tools/media/SOURCE_ORIGINS.json)。这些代码仅在电脑上生成文件，不连接或写入相机。

## 2. A9 原生表能表达什么

R15 同时保存两份 1280 字节源属性：`0x00030004` 和 `0x00030005`。离线配方分别按名义 sRGB 与 Adobe RGB 输出编码处理，不能只拟合一份后复制到另一份。

每份前 1215 字节是三个通道各 405 个节点：

```text
405 = 5 × 9 × 9
1215 = 3 × 405
1280 = 1215 + 65 字节原厂尾部
```

源值以有符号八位字节存储，合法数值范围是 **−64～63**。例如 −1 存为 `FF`，不能擅自改成七位紧凑位流。最后 65 字节必须与对应原厂表逐字节一致；不能互换两张表的尾部，也不能填成自定校准值。

实验模型的节点输入坐标：

| 轴 | 节点 |
|---|---|
| Y | `0, 64, 128, 192, 256` |
| Cb、Cr | `−128, −96, …, 96, 128` |

单通道索引为 `a×81+b×9+c`。源数组按三个通道顺序存放，不能当作 RGB 33³ CUBE 的逐点数据。源值作用到节点后：

```text
Yout  = clamp(Ynode + correctionY, 0, 256)
Cbout = clamp(Cbnode + floor(3×correctionCb/4), −128, 128)
Crout = clamp(Crnode + floor(3×correctionCr/4), −128, 128)
```

插值使用八个角的三线性权重。所有亮度列必须保持五层输出非递减。导出器会检查范围、尾部及单调性。

这是依据原生表建立的**实验性拟合模型**，没有被证明逐位等同于完整 A9 ISP。色表不能独自生成空间颗粒、光晕、暗角或真实锐化；R15／V8 中这些功能有自己的参数和处理链。

## 3. 准备参考 LUT 与颜色编码

先记录以下输入信息：原始文件 SHA256、作者／许可、CUBE 维度、输入色域和传递函数、输出色域和传递函数、输入曝光基底。缺少这些信息时，单凭滤镜名称不能建立可靠转换。

[`source_catalog.json`](../../tools/media/lut/data/source_catalog.json) 保存既有 227 款资源的冻结编码说明和来源文件指纹。它是目录，不包含 227 份原始 CUBE 的统一再分发授权。项目已有的 A9P 原件在 [filters](../../filters/README.md)。

### 3.1 CUBE 解析规则

解析器支持纯 1D 或纯 3D CUBE，尺寸 2～129，支持 `DOMAIN_MIN/MAX` 或对应 `LUT_*D_INPUT_RANGE`。所有样本必须有限，行数必须等于 `N` 或 `N³`，域上界严格大于下界。

3D CUBE 文件为 **R 最快、G 次之、B 最慢**。NumPy 存储因此通过 `table[b,g,r]` 读取。验证轴顺序时，先使用 identity CUBE，再使用交换 RGB 通道的 CUBE；只看一张照片容易漏掉轴序错误。

输入坐标按域归一化并裁剪；3D 使用三线性插值，1D 对各通道分别插值。包含 1D shaper＋3D 的组合文件会明确拒绝，不能忽略 shaper 后继续制作。

### 3.2 转换参考颜色

对每份名义 RGB 基线样本，参考转换依次执行：

1. 从该表的名义编码解码到线性 RGB：表 0 使用 sRGB；表 1 使用 Adobe RGB 的 `563/256` 指数。
2. 按原色矩阵转到目标输入色域；白点不同时使用 Bradford 适配。
3. 乘以明确指定的 `exposure_scale`，默认 1。
4. 编码为参考 CUBE 的输入传递函数，再查 CUBE。
5. 按其输出传递函数解码，再转回该 A9 表的名义色域。
6. 编码回名义 RGB，裁剪到 0～255，作为拟合目标。

支持的色域键为 `srgb/adobe/rec2020/fgamut/vgamut/prophoto/fgamutc`。输入曲线支持 sRGB、线性、Adobe gamma、gamma 2.2／2.4、ProPhoto gamma 1.8，以及 V-Log、F-Log、F-Log2、N-Log。实现和常数直接见 `lut.py`。

例如 V-Log 线性输入 `x` 的编码为：

```text
x < 0.01：5.6x + 0.125
其他：0.241514 log10(x+0.00873) + 0.598206
```

代码测试包含 18% 灰参考值。这里的 Log 是**参考 LUT 的输入编码适配**，并不证明 A9 当前拍摄链具有相同传感器响应、曝光基准或完整 Log 管线。不能把一份以特定相机／曝光为前提的官方 LUT 默认解释为照片 sRGB 风格。

## 4. 冻结样本与原厂残差锚定

随代码提供的 [`baseline.npz`](../../tools/media/lut/data/baseline.npz) 是合成参考数据，不是用户照片或实机测试图像。共 99,372 行；`table0/table1` 都是 `(99372,3)`，另有同序的 `split/kind`：

| 集合 | 行数 | 用途 |
|---|---:|---|
| train | 64,562 | 初拟合和细化采样池 |
| valid | 17,467 | 选初始候选和量化后的最佳候选 |
| test | 17,343 | 最终独立报告，绝不用于选候选 |

基线与压扩曲线先经过 [数据摘要](../../tools/media/lut/data/SHA256SUMS.json) 校验，再以 `allow_pickle=False` 读取。更换样本内容或顺序就会改变目标数组含义，不能只保留旧报告文件名。

模型先将名义 RGB 转为实验性 Y／色度：

```text
y = 0.299r + 0.587g + 0.114b      （r,g,b 已除以 255）
Y = 256y
Cb = 1024(b−y)/(2(1−0.114))
Cr = 1024(r−y)/(2(1−0.299))
```

色度绝对值通过冻结 `expand` 的逆插值压到 0～128。反解时再由 129 点 expand 曲线展开。不要用任意对数压缩替代这条曲线。

对每张表，`inverse_stock()` 迭代 48 次：以目标压缩坐标初始化，按原厂节点模型的残差乘 0.7 更新，并裁剪坐标。随后建立插值矩阵 `W`，计算原厂残差锚点：

```text
anchor = compress(baseline_RGB) − W × stock_node_outputs
candidate_RGB = decode_compressed(W × candidate_node_outputs + anchor)
```

这样保留基线相对于简化模型的原厂残差。拟合时的目标压缩坐标也相应减去 anchor。这比完全忽略原厂残差更贴近项目原有基底，但仍不把离线模型变成完整 ISP 测量。

## 5. 初拟合、量化和感知细化

### 5.1 两套既有配方

| 项目 | 外部 227 款库 `library` | R15 内置 27 款 `builtin` |
|---|---|---|
| 初拟合普通样本 | train 中随机 12,000 行 | train 中最多 16,000 行 |
| 特殊样本 | 加上 train 中全部非 `uniform_luma` 行 | 相同规则 |
| 随机种子 | `20261121` | `20261115` |
| 细化样本 | train 中 6,144 行 | train 中 8,192 行 |
| 细化采样种子 | `20261122` | `20261116` |
| 细化步数 | 200 | 240 |
| 初始候选比较 | 原厂表与新初拟合 | 冻结旧版表与新初拟合 |

本基线的 `library` 初拟合实际共 24,064 行。不同配方不要混称为同一次重现。

### 5.2 有界最小二乘

每个通道求 405 个修正值，目标是压缩坐标误差，加上靠近原厂值与相邻变化平滑的正则项。矩阵形式：

```text
M = WᵀW/N + 2×10⁻⁵ I + 2×10⁻⁵ L
```

`L` 为 5×9×9 网格邻接的图拉普拉斯。先解无约束线性系统，再用 L-BFGS-B 在边界内搜索；最大 400 次迭代。色度通道使用 0.75 比例，最终还需恢复真实 floor 量化。

R15 的两个正式入口将源值边界明确设为完整 signed7 `[-64,63]`。基础 `a9_model.py` 中保留的旧相对边界函数不应误当作 R15 正式入口的最终边界。

连续值以绝对值半入、保留符号的规则量化，裁剪到合法范围，再投影亮度列使其单调。最后附回原厂 65 字节尾部。

### 5.3 感知细化与选候选

细化使用 CPU PyTorch、单线程，Adam 学习率 0.55。前向色度计算使用真实 `floor(0.75p)`，搜索梯度采用 straight-through 近似。主要损失为：

```text
mean(sqrt(ΔE00² + 10⁻⁴)) + 0.004 × mean(ΔE00²)
```

梯度范数限制为 5，参数每步夹到源值边界。每 40 步及末步，将候选重新量化、执行亮度单调投影，再用**验证集**评分：

```text
score = mean(ΔE00) + 0.1 × p95(ΔE00)
```

只保留验证评分改善的候选。出现非有限损失或梯度即停止搜索，保留已有最佳候选。最终 test 只用于报告。

## 6. 在仓库中制作一份 A9P

以下命令从仓库根目录执行。使用独立 Python 环境，原记录环境为 Python 3.14、NumPy 2.5.4、SciPy 1.18.1、CPU PyTorch 2.14.1；具体依赖见 [requirements.txt](../../tools/media/lut/requirements.txt)。这些依赖只用于制作素材，不用于运行已经发布的 EXE。

```sh
python -m pip install -r tools/media/lut/requirements.txt
python -B -m unittest discover -s tools/media/tests -v
python -B tools/media/lut/fit_a9p.py --cube tools/media/lut/examples/glassmeter-400d.cube --name "GM cinestill 400d d32c" --out media-output/gm400d
```

输出目录必须不存在。示例是 sRGB 输入／输出，默认参数正好适用。完成后有：

```text
media-output/gm400d/
  00030004.bin                 1280 字节
  00030005.bin                 1280 字节
  report.json                 来源、配方、样本数和误差
  CARD/PRIVATE/A9FL/LUT1.A9P    2756 字节
```

本轮已用该命令完成 200 步双表拟合，具体输出指纹及与既有滤镜的对照见 [VALIDATION.json](../../tools/media/VALIDATION.json)。

另一份已明确为 V-Gamut／V-Log 输入、Rec.709 原色 gamma 2.4 输出的 CUBE，可这样指定编码：

```sh
python -B tools/media/lut/fit_a9p.py --cube my-look.cube --name "My VLog Look" --input-gamut vgamut --input-curve vlog --output-gamut srgb --output-curve gamma24 --out media-output/my-vlog
```

这里 `srgb` 色域键也代表 Rec.709 的同一组原色／白点；曲线由单独参数指定。不要仅根据扩展名推断源编码。

若使用已冻结的 R15 内置目标：

```sh
python -B tools/media/lut/fit_a9p.py --recipe builtin --targets frozen-look.npz --prior-pair prior-look.bin --name "My Frozen Look" --out media-output/frozen-look
```

目标 NPZ 必须提供与基线行顺序完全相同的 `photo0/photo1`；旧表文件必须恰为 2560 字节，表 0 后接表 1。原 27 项的目标指纹见 [builtin_targets_manifest.json](../../tools/media/lut/data/builtin_targets_manifest.json)。本次没有把全部冻结目标与旧表数据复制进仓库，因此不能声称仅克隆仓库就能重建全部 27 个既有内置项；随附 CUBE 示例则具备完整制作输入。

## 7. 误差报告与工程分级

每张表分别报告 mean／median／p95／max ΔE00 和 RGB RMSE（0～255 标度），还记录原厂表到目标的误差、优化迭代、量化误差、边界节点和每轮验证分数。不要只看最终一个平均值。

既有滤镜库取两张表中较差的 mean 与 p95 分级：

| 等级 | 条件 |
|---|---|
| A | mean < 2 且 p95 < 5 |
| B | 未达到 A，但 mean < 4 且 p95 < 10 |
| C | 其余 |

这些是本项目工程分级，不是国际认证或相机实拍色准。现有 227 个包包含 135 个常规近似、92 个高误差实验项。色卡画出的 reference／fit 是参考映射和模型预测，不是两台相机拍摄对比。

还应检查灰阶是否染色、肤色和高饱和色是否异常、近黑及高光是否压死、边界节点是否过多。不能用 test 反复调参后继续称其为未参与选型的独立测试集。

## 8. A9P V2 二进制格式

所有多字节整数为小端。总长 **2756**，由 192 字节头、两张 1280 字节表和 4 字节 CRC 构成。

| 偏移 | 长度 | 内容 |
|---:|---:|---|
| 0 | 8 | `A9FLPK2\0` |
| 8／10 | 各 2 | 版本 2／头长 192 |
| 12 | 4 | 总长 2756 |
| 16 | 8 | `ILCE-9`，补零 |
| 24 | 24 | 固定 build `37111_13.2019091301`，补零 |
| 48 | 32 | 原厂双表连接后的 SHA256 |
| 80／84 | 各 4 | `0x30004`／`0x30005` |
| 88／90 | 各 2 | 表长 1280／1280 |
| 92 | 4 | 参数标志，0 或 1 |
| 96 | 16 | 16 个有符号参数默认值；无参数时全零 |
| 112 | 2 | 名称 UTF-8 字节数 |
| 114 | 14 | 保留零 |
| 128 | 64 | UTF-8 名称，余下补零 |
| 192 | 1280 | 表 0 |
| 1472 | 1280 | 表 1 |
| 2752 | 4 | 前 2752 字节的 zlib CRC32，小端 |

原厂双表身份 SHA 为 `d4a9a6234f6c05083716fb9cb1218d7e50ef541a0a279ac0a61b786a73822d1b`。这是原厂基底身份，不能替换成新拟合双表的 SHA。

名称为 1～64 个 UTF-8 **字节**，不是 64 个汉字；首尾空白、控制字符、双向控制及不支持的码点会被拒绝。NAME HELP 使用这个内部名称，与 SD 文件名 `LUT1.A9P` 分工不同。

16 个参数按：对比、高光、阴影、褪色、饱和度、锐度、锐度范围、清晰度、颗粒、光晕、黑位、暗部、中间调、亮部、白位、暗角。合法下界／上界为：

```text
MIN = -9 -9 -9 0 -9 -3 1 0 -9 -9 -9 -9 -9 -9 -9 -9
MAX =  9  9  9 9  9  3 5 9  9  9  9  9  9  9  9  9
```

若已有合法双表，只需封装，不需要重拟合：

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python -B -m a9tool.release_a9p export --name "My Look" --table0 table0.bin --table1 table1.bin MyLook.A9P
python -B -m a9tool.release_a9p inspect MyLook.A9P
```

默认不写参数标志时，运行默认是六个 0、锐度范围 1、其余 0。需要携带参数时，使用 `--defaults` 后给出 16 个整数。CRC、表检查和 SHA 是格式／完整性检查，不是对素材版权、色彩效果或机身安全的数字签名。

## 9. 导入、留存与排错

将制作输出 `CARD/PRIVATE` 合并到卡槽 1 根目录，最终路径为 `PRIVATE/A9FL/LUT1.A9P`～`LUT16.A9P`。先备份旧卡内槽位；同批最多 16 个，名称保存在文件内部。

先部署 R15NH，在创意外观第 4 页执行导入，检查内部名称和 HELP 全名；按原保存流程保存设置。V8 读取并操作同一个 R15 后端，不另有一套“V8 LUT”文件格式。当前 R15 创意外观二级菜单仍需使用物理按键操作，不能假定 V8 原生触摸覆盖该页。

常见拒绝原因：名称超字节数、表长度错误、值超 signed7、亮度列不单调、65 字节尾部变化、机型／build／原厂基底身份不同、保留区或 CRC 不正确。若格式通过而颜色不合理，优先核对 CUBE 轴序、输入域、色域、Log 曲线和曝光基底，再看拟合误差；不要通过删掉校验掩盖问题。

复现时保留原 CUBE、许可、编码说明、基线 SHA、软件依赖版本、配方／种子、双表、A9P 和 `report.json`。浮点库、CPU 或优化器版本不同可能影响最后几码，不承诺跨环境逐字节相同。离线成功与实机拍摄评价分别记录。
