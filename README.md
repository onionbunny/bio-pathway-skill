# bio-mechanism-pathway-figure

面向科研场景的生物机制图 / 信号通路图 Skill：从真实材料（PDF、文本、表格、既有 SVG）
生成或编辑**分层可编辑 SVG**，并导出 PNG/PDF 预览；全部图元带证据来源，图例与数据映射自洽。

## 目录结构

```
bio_pathway_skill/
├── SKILL.md                     # Skill 主文档（含运行时契约与工作流）
├── README.md                    # 本文件
├── GITHUB_URL.txt               # GitHub 链接位（当前构建环境未提供，见文件说明）
├── scripts/
│   ├── init_ir.py               # case.json → IR 骨架
│   ├── svg_render.py            # IR → 分层可编辑 SVG（纯标准库）
│   ├── validate.py              # IR + SVG 独立校验
│   ├── export_artifacts.py      # SVG → PNG/PDF（后端自动探测）
│   └── inspect_svg.py           # 既有 SVG 结构清单
├── schemas/
│   └── figure_ir.schema.json    # IR JSON Schema (draft-07)
├── vocab/
│   ├── relations.json           # 关系触发词、证据强度四档、端点字形
│   └── naming_rules.md          # 基因/蛋白命名与消歧规则
├── templates/
│   ├── palette.json             # 字体/配色/色标
│   └── ir_skeleton.json         # 空白 IR
└── examples/
    ├── example_ir.json          # 合成教学示例（非真实案例）
    └── walkthrough.md           # 最小调用示例说明
```

## 依赖与安装

- 必需：Python 3.9+（脚本仅用标准库，无需 pip 安装）。
- 导出后端按以下顺序自动探测，取第一个可用者，并把名称/版本写入报告：
  1. Python 包 `cairosvg`（推荐，PNG/PDF 均支持，标记与渐变渲染完整）；
  2. `rsvg-convert`（librsvg）；
  3. `inkscape`；
  4. `convert`（ImageMagick；注意部分 Debian 策略默认禁用 PDF coder，
     其 MSVG 渲染器对 marker/渐变支持弱，仅作兜底）。
- 中文字体：建议环境内有 Noto Sans CJK / 文泉驿等；缺失时导出预览可能出现方框，
  结果文件会如实记录字体环境。SVG 本身不依赖字体文件，可在本机替换字体后再导出。

## 快速开始

```bash
# 1. 从案例初始化 IR（正式运行时 /input/case.json）
python3 scripts/init_ir.py --case /input/case.json --out work/figure_ir.json

# 2. 按材料手工/Agent 填充 IR 后渲染
python3 scripts/svg_render.py --ir work/figure_ir.json --out output/figure.svg

# 3. 校验（有 error 必须修复后重跑）
python3 scripts/validate.py --ir work/figure_ir.json --svg output/figure.svg --out work/validation.json

# 4. 导出 PNG/PDF
python3 scripts/export_artifacts.py --svg output/figure.svg --outdir output --formats png,pdf
```

## 方法说明

1. **单一事实中间表示（IR）**：实体、区室、关系、证据原句、数据映射全部显式结构化，
   与渲染解耦；同一 IR 可重复渲染、版本化、diff 复核。
2. **确定性渲染（v2）**：不依赖黑盒模型出图，图层/ID/配色/端点由规则生成；关系语义
   （激活三角、抑制 T 杠、结合圆点、修饰菱形、转运虚线空心箭头）在图面与图例中保持同一约定；
   文本测量自动撑盒、区室网格打包、障碍自动绕行、短边标签抑制、反馈车道与画布自适应。
3. **独立校验闭环**：引用完整性、命名启发式、膜定位、证据触发词、坐标越界/重叠、
   图例颜色集合交叉检查、双向/自环标记、SVG 结构与可编辑文本检查，输出机器可读报告。
4. **诚实导出**：后端探测、格式魔校验、失败原因全部留痕；部分失败保留可用产物并标注。

## 适用范围与限制

- 适用：信号通路、机制示意、受体—胞内—核内层级、分支与反馈环、数据驱动的颜色/大小编码、
  既有矢量图的源保留修改。
- 不覆盖：统计分析与显著性结论、实验方案设计、论文写作与版式美化；本 Skill 只如实映射
  材料给出的数值，不做统计推断。
- 命名启发式规则为提示性检查，不能替代权威库核对；外部 ID 缺失时不会自动联网补全。

## 维护信息

- IR schema 版本：`bio-pathway-ir/1.0`；渲染器版本 v2；升级需同步渲染器、校验器与 schema。
- 所有脚本设计为无状态、可重复执行；重复运行同一 IR 输出字节级一致。
