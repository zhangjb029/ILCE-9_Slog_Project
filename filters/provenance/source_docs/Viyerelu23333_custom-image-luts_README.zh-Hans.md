# 自定义图像 LUTs (33³)

用于近似模拟宾得自定义图像的 3D LUT（`.cube`）。
输出始终为 sRGB 显示编码。借助 LLM 构建，不保证准确性。
校准基于一台 K-1 的机内 JPEG，以及与 LUMIX S9 同场拍摄的色卡样张，因此在不同机身和场景下会与机内效果有一定差异。

[English](README.md)

## 目录结构

```
{lut_type}/{source_gamut}/pentax_{tone}_{source_gamut}_srgb_33.cube     各格调的默认参数
{lut_type}/{source_gamut}/{tone}/pentax_{tone}_{variant}_{source_gamut}_srgb_33.cube
```

| `lut_type` | 输入 | 源色域 |
|---|---|---|
| `virtual_camera` | Log 素材，先渲染为“虚拟 K-1 raw” | 仅 `vlog`（V-Log / V-Gamut） |
| `tone_delta` | 以**自然**为基调的 K-1 JPEG | 仅 `srgb` |

![virtual_camera_patches](assets/chart_vlog.png)
![tone_delta_patches](assets/chart_srgb.png)

## 局限

- 请在机内正确设置白平衡，LUT 不做白平衡校正。
- 校准只使用了一台 K-1 和一台 LUMIX S9，光源为 LED、白炽灯和阴天。换用其他机身、混合光源或特殊光源时，偏差可能更大。
- `virtual_camera` 基于 S9 的 V-Log **JPEG（全范围）** 校准，视频文件（有限范围）尚未验证。
- 仅包含影调与色彩，不含锐化、降噪和 D-Range Auto 的效果。
- 高饱和颜色（例如彩色 LED 舞台光）可能被截断或偏色。
- `tone_delta` 以成品 JPEG 为输入，无法恢复原图中接近纯白（约 250 以上）的高光或已被截断的颜色。
- 33³ 的最小二乘拟合会使部分格调中非常陡的过渡变得平滑。

## 默认参数

顶层 `pentax_{tone}_...` LUT 使用的值（相机菜单数值；所有格调的饱和度和色相均为 0，无 D-Range 校正）。
高光、阴影为对比度的高光/阴影调整。`-` 表示相机上没有该参数。

| 格调 | 影调 | 对比度 | 高光 | 阴影 | 调色 / 滤镜 |
|---|---|---|---|---|---|
| 自然 | 0 | 0 | 0 | 0 | - |
| 鲜明 | 0 | +1 | 0 | 0 | - |
| 人像 | 0 | 0 | 0 | 0 | - |
| 风景 | 0 | +1 | 0 | 0 | - |
| 风雅 | 0 | 0 | 0 | 0 | - |
| 柔和 | +4 | -3 | 0 | 0 | 关 |
| 反转片 | - | - | - | - | - |
| 留银冲洗 | -4 | +4 | 0 | 0 | 绿 |
| 波普风格 | +2 | +3 | 0 | 0 | - |
| 交叉冲洗 | - | - | - | - | 预设 1 |
| 平调 | 0 | -4 | 0 | 0 | - |
| 单色 | 0 | 0 | 0 | 0 | 滤镜 无，调色 0 |
| 素朴 | 0 | +2 | 0 | 0 | - |
| 春红 | 0 | +2 | 0 | -2 | 红 |
| 夏天 | 0 | +4 | +3 | -3 | - |
| 九秋 | -1 | +1 | 0 | -1 | - |
| 冬野 | +3 | +4 | -4 | +4 | - |
| 金色 | 0 | 0 | 0 | 0 | - |

`tone_delta` LUT 的目标格调使用相同的默认值；输入假定为默认参数的自然。

### 变体（`{tone}/` 子文件夹）

| 格调 | 变体 |
|---|---|
| 单色 | 滤镜 `filter_{green,yellow,orange,red,magenta,blue,cyan,ir}`；调色 `toning_{-4..+4}` |
| 交叉冲洗 | 预设 `cross_2`、`cross_3` |
| 柔和 | 调色 `toning_{green,yellow,orange,red,magenta,purple,blue,cyan}` |
| 留银冲洗 | 调色 `toning_{off,yellow,orange,red,magenta,purple,blue,cyan}` |
| 春红 | 调色 `toning_{off,green,yellow,orange,magenta,purple,blue,cyan}` |

示例：`virtual_camera/vlog/monochrome/pentax_monochrome_filter_red_vlog_srgb_33.cube`

## 许可

LUT 文件采用 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) 许可。

**附加许可：**
你可以将这些 LUT 用于任何目的的照片和视频创作，包括付费和商业项目。
使用这些 LUT 制作的照片和视频不受本许可约束，也无需署名。
禁止出售 LUT 文件，或将其放入任何付费产品或合集（如预设包、应用）中。

## 声明

本项目与 Ricoh Imaging、Panasonic 无关，也未获其认可。
PENTAX、LUMIX、V-Log 及各格调名称为其各自所有者的商标；文中使用格调名称仅用于说明每个文件所近似的机内效果。
