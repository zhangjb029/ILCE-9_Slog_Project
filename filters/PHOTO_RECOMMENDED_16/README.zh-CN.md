# A9 拍照新增16款（排除内置重复）

本卡组补足16个导入槽：13款GlassMeter显示域sRGB胶片解释 + 3款有条件宾得相对外观。保留原先8款的槽号，新增9～16。无需更换固件；用于支持七位A9P的R15。旧库、旧卡组与内置27款全部保留。

## 导入

先备份卡槽1中原有的 PRIVATE/A9FL/LUT1.A9P～LUT16.A9P；把本包 SD_CARD 内的 PRIVATE 文件夹复制到卡槽1根目录。在创意外观子菜单第4页选择“导入”。成功后写入自定义1～16，覆盖这些槽位的旧导入内容。

A9P/ 中原件以来源名称命名，方便收藏；卡内副本按机身识别规则使用 LUT1.A9P～LUT16.A9P。两份逐字节一致，未改内嵌名称。支持名称帮助的修订版可用帮助键查看全名。

| 自定义槽 | 名称 | 用途 | 来源条件 |
|---|---|---|---|
| 1 | Kodak Gold 200 | 日光旅行、暖调日常 | 显示域sRGB |
| 2 | CineStill 800T | 夜景、混合灯光 | 显示域sRGB |
| 3 | Kodak ColorPlus 200 | 日常、旅行 | 显示域sRGB |
| 4 | Kodak Portra 800 | 人像、暖调生活 | 显示域sRGB |
| 5 | Kodak UltraMax 400 | 通用日常、旅行 | 显示域sRGB |
| 6 | Kodak Ektar 100 | 彩色风景、建筑 | 显示域sRGB |
| 7 | Pentax Reversal Film | 正片式风景、城市色彩 | Pentax Natural基底，A9未校准 |
| 8 | Pentax Bright | 明快日常、风景 | Pentax Natural基底，A9未校准 |
| 9 | CineStill 400D | 日光通用、人像、旅行 | 显示域sRGB |
| 10 | CineStill 50D | 晴天人像、风景、细节 | 显示域sRGB |
| 11 | Fujifilm Pro 400H | 柔和人像、自然色彩 | 显示域sRGB |
| 12 | Fujifilm Superia X-TRA 400 | 街拍、日常、旅行 | 显示域sRGB |
| 13 | Kodak Portra 160 | 人像、工作室、商业拍摄 | 显示域sRGB |
| 14 | Kodak Ektachrome E100 | 正片色彩、风景、人像 | 显示域sRGB |
| 15 | Fujifilm Industrial 100 | 低饱和日常、清晰反差 | 显示域sRGB |
| 16 | Pentax Landscape | 蓝天、绿叶、秋色 | Pentax Natural基底，A9未校准 |

## 来源选择与推荐依据

排除与27个内置风格同名的富士数字模拟、Portra 400，以及易混淆的Provia/Velvia/Acros胶卷解释。Portra 160/800是不同胶卷目标；Pentax Reversal Film也不是已有的理光正片配方。精确规则和全部27个内置名称见 EXCLUSIONS.json。

13款胶片来源均为 GlassMeter by Glass Works 的社区原创解释（CC BY 4.0），作者明确要求正常曝光的显示域sRGB输入／输出，适合作为A9现有照片输出后的相对调色。不是胶卷厂商发布的测量复刻LUT。色表不包含颗粒、光晕或真实胶片感光度。

3款宾得位于自定义7、8、16。来源以Pentax K-1 Natural JPEG为基底，A9未被校准成该基底，因此仅作为相对外观试用，不宣称还原宾得机身。若暂不试用条件组，可在复制前移走这三个编号文件；导入只更新剩余13槽，旧7/8/16槽内容保留。

本次未选择F-Log/F-Log2等Log输入来源，也未用要求平直基底的abpy或Log派生ProPhoto文件凑满。富士照片数字模拟继续使用既有内置表。

推荐顺序是试用槽位顺序，不是统一的人气排行榜。部分胶卷有店铺销量、社区使用记录支持；CineStill 400D/50D、E100等补充不同拍摄用途；Industrial100只获得单篇实拍好评。口碑证据针对胶卷或原厂模式，不针对本次A9P文件。SOURCES.json逐条注明范围和局限。

## 色差与浏览

16款均为原库A级拟合，双表独立测试各17343点。平均ΔE00范围0.282～0.821；P95范围0.942～2.553。完整精度数据见SLOTS.csv。数值衡量A9模型与来源CUBE目标的一致程度，不衡量与真实胶卷、富士或宾得实拍的一致程度。

index.html包括现有28项（原厂关闭 + 27内置）和本次16款，共44项，可按名称搜索及筛选。charts中有单项标准24色图、16款总览、28款现有总览。新增图左上来源目标／右下A9拟合；现有图左上原厂／右下默认外观，均为离线模型而非实拍。

## 来源与许可

- FilmProcessing：按2025年实际销量排列的35mm胶卷：https://www.filmprocessing.co.uk/post/best-35mm-films-according-to-you-in-2025/；受价格、进货和店铺客群影响，不是世界销量榜，更不是A9P下载或评价数据。
- Analog.Cafe：293位摄影者的胶卷使用记录：https://www.analog.cafe/r/top-10-film-stocks-according-to-293-photographers-wlzp；使用记录不是喜欢程度；样本不随机，部分记录受少数用户影响。只使用公开部分，不推测付费内容。
- PentaxForums：最喜欢的Custom Image模式：https://www.pentaxforums.com/forums/6-pentax-dslr-discussion/487015-favourite-custom-image-mode.html；小样本且票数会变，不外推为全体用户排名；不是A9P文件的投票。
- KEH Tilt-Shift：历史胶卷销售报告：https://www.keh.com/expert-advice/camera-gear/buying-guides/what-film-stocks-sell-the-most-the-keh-tilt-shift-report/；历史库存、供货及客群影响明显；Superia记录未细分本库X-TRA版本，不是全球或2026年排名。
- Ricoh Imaging：PENTAX Custom Image：https://www.ricoh-imaging.co.jp/english/products/custom_image/index.html；页面说明基于2022年机型；未公开偏好调查方法。原厂模式说明不代表本A9相对表已还原宾得输出。
- CineStill：四种胶卷的摄影用途指南：https://cinestill.film/blogs/news/cinestill-film-stock-primer；官方定位不等于独立人气投票；色表不模拟颗粒、光晕、胶卷感光度或曝光宽容度。
- Kodak：PORTRA 160：https://business.kodakmoments.com/product/kodak-professional-portra-160-film；说明胶卷用途，不证明GlassMeter解释或A9P的胶卷匹配度。
- Kodak：EKTACHROME E100：https://business.kodakmoments.com/product/kodak-professional-ektachrome-film-e100；说明胶卷用途，不是本A9P的独立评价。
- Parallax：Fuji Industrial 100实拍评测：https://parallaxphotographic.coop/fuji-industrial-100-film-review/；单篇好评，不能据此宣称大众热门；不把Industrial与Superia视为同一配方。

许可和原作者说明保留于provenance。原件SHA256与库一致；本次没有重新拟合、改变色表、修改固件、运行QEMU或访问相机。生产C导入解析核验见独立VERIFY_RECEIPT.json。
