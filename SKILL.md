---
name: bio-mechanism-pathway-figure
description: >-
  生物机制图、信号通路图、流程图的生成与源保留编辑。当用户/案例要求依据论文、PDF、
  文本、表格数据或既有 SVG 绘制或修改基因、蛋白、复合物、细胞区室及其激活/抑制/结合/
  修饰/转运关系，并要求可编辑源文件与 PNG/PDF 导出时使用。输出分层可编辑 SVG、
  渲染预览、结构化 IR、实体/边证据索引与 result.json，保证每个图元可回溯、图例自洽。
  不承担统计分析、实验设计与论文写作；数值只做来源映射，不做统计推断。
---

# 生物机制图与通路图 Skill

机制图不是装饰图，而是一份可逐条质疑的机制陈述。本 Skill 把任务固化为
**“读事实材料 → 结构化 IR（实体/关系/证据/映射）→ 确定性渲染 → 独立校验 → 多格式导出 → 可复核结果包”**。

## 0. 运行时契约（Harbor / DeepSeek Harness）

- 输入：`/input/case.json`（案例元数据、材料清单、可能含 output_contract）与 `/input/task.md`（具体工单）；
  材料按 case.json 声明的路径提供，PDF 为真实文件，无预提取答案层。
- 工作目录：`/app/work`（IR、草稿、报告放这里）；最终产物：`/app/output`。
- 预算：64 次模型请求、900 秒、单次响应 16384 tokens。**先尽早落盘可诚实交付的部分结果，再增量改进。**
- 所有脚本仅依赖 Python 3 标准库；导出后端自动探测，无需联网安装。
- 禁止把预制答案、固定标签假设当输出；一切实体、关系、数值必须来自实际输入材料。

资源路径（相对本 Skill 根目录）：

| 路径 | 作用 |
|---|---|
| `scripts/init_ir.py` | 从 case.json 生成 IR 骨架（不预填答案） |
| `scripts/svg_render.py` | IR → 分层可编辑 SVG（确定性渲染） |
| `scripts/validate.py` | IR + SVG 独立校验，输出 JSON 报告 |
| `scripts/export_artifacts.py` | SVG → PNG/PDF，探测 cairosvg/rsvg/inkscape/convert |
| `scripts/inspect_svg.py` | 导出既有 SVG 结构清单，供源保留编辑 |
| `schemas/figure_ir.schema.json` | IR 的 JSON Schema（draft-07） |
| `vocab/relations.json` | 关系触发词表、证据强度四档、端点字形 |
| `vocab/naming_rules.md` | 基因/蛋白命名、物种前缀、消歧规则 |
| `templates/palette.json` | 字体、区室/实体配色、色标、边色 |
| `templates/ir_skeleton.json` | 空白 IR 模板 |
| `examples/example_ir.json` | 合成教学示例（明确标注，非真实案例） |

## 1. 标准工作流（生成类案例）

### 步骤 1 — 盘点与通读（先列目录，禁止假设内容）

```bash
ls -la /input && cat /input/case.json && cat /input/task.md
```

- 按 case.json 的材料清单逐个打开：PDF 用环境提供的 PDF 工具按页读取；表格（csv/xlsx/json）
  读取真实数值；既有 SVG 用 `inspect_svg.py` 看结构。
- 建 `work/extraction_notes.md`：逐段记录“材料说了什么、在哪个页/表/图”，不做材料外的推断。

### 步骤 2 — 初始化 IR

```bash
python3 <SKILL_DIR>/scripts/init_ir.py --case /input/case.json --out /app/work/figure_ir.json
```

### 步骤 3 — 提取实体并归一命名

- 每个生物实体一条记录：`id, label, kind, compartment, italic, synonyms, external_ids, data, sources`。
- 严格按 `vocab/naming_rules.md`：人基因大写斜体、蛋白正体；小鼠基因仅首字母大写斜体；
  中文译名进 synonyms，权威符号做 label；复合物与亚基分开；家族泛指需注明。
- 每个实体的 `sources` 必须指向真实材料（可带 `#页/表/图` 定位）。权威 ID 查不到就不填，**禁止编造**。

### 步骤 4 — 判定关系与证据强度

- 每条边：`source, target, relation, direction, evidence{source, quote, strength}`。
- 依据 `vocab/relations.json` 的中/英触发词判定关系；quote 必须是材料原句（可截取），
  并逐字保留方向信息。材料没写方向时用 `regulates_unspecified` 且 strength=`unverified`，
  不得自行补箭头方向。
- 证据强度四档（禁用“已证实/证实”等绝对化标签）：
  - `supports` 证据支持；`partially_supports` 部分支持；
  - `conflicting` 证据不一致（必须在 note/uncertainty 说明矛盾）；`unverified` 待检验。

### 步骤 5 — 布局与数据编码

- 默认四区室按 rank 分列：细胞外 → 细胞膜 → 细胞质 → 细胞核；受体/通道/转运蛋白放 membrane。
- 数据驱动编码写 `data_mappings`：`node_fill`（diverging/sequential/categorical）、
  `node_size`、`edge_width`、`edge_stroke`；每个被映射变量在数据上必须有 `source`。
- 材料未提供数据的元素不参与映射，回退 kind 默认色；缺失清单写入 uncertainty。
- 反馈环必须显式 `feedback: true`，渲染器在节点下方绕行，不与普通跨区室边混淆。

### 步骤 6 — 渲染

```bash
python3 <SKILL_DIR>/scripts/svg_render.py --ir /app/work/figure_ir.json --out /app/output/figure.svg
```

SVG 约定（可编辑性的硬指标）：

- 命名图层：`layer-00-background / 10-compartments / 20-edges / 30-entities / 50-legend`；
  节点组 `node-<id>`、标签 `label-<id>`、边组 `edge-<id>`，ID 稳定可定位。
- 全部标签为真实 `<text>`（不转曲、不栅格），统一字体族，可整体替换字体。
- `<metadata>` 内登记 case_id 与全部 sources；边 `<title>` 内嵌证据原句。
- 自适应布局（v2）：节点按文本测量自动撑盒、不截断；区室内按网格打包防重叠；
  同区室边遇中间节点自动绕行；短路径上的文字标签自动抑制（语义由箭头字形+图例承载）；
  反馈车道独立编号，空间不足时自动扩展画布并在渲染日志记录。

### 步骤 7 — 校验（门禁，不通过必须修复后重跑）

```bash
python3 <SKILL_DIR>/scripts/validate.py --ir /app/work/figure_ir.json \
  --svg /app/output/figure.svg --out /app/work/validation.json
```

- 退出码非 0 时按 findings 逐条修复 IR 并重新渲染；warning 要在 result.json 中给出处置说明。

### 步骤 8 — 导出与结果包

```bash
# 字体自查（中文材料尤其重要）
fc-list | grep -i cjk || true
python3 <SKILL_DIR>/scripts/export_artifacts.py --svg /app/output/figure.svg \
  --outdir /app/output --formats png,pdf --scale 2
```

- 后端与版本、文件字节数、格式魔校验结果均在 export_report.json；某格式失败时状态记 partial，
  保留 SVG 并在 result.json 说明，不伪造成功。
- 最后写 `/app/output/result.json`（见第 5 节）。

## 2. 关系语义与端点字形表（渲染器与图例共用同一约定）

| relation | 含义 | 线型 | 端点 | 修饰标签 |
|---|---|---|---|---|
| activates | 激活/促进 | 实线 | 实心三角箭头 | — |
| inhibits | 抑制 | 实线 | 平头 T 杠 | — |
| binds | 结合/互作 | 实线 | 实心圆点（默认 undirected） | — |
| phosphorylates | 磷酸化 | 实线 | 空心菱形 | P |
| dephosphorylates | 去磷酸化 | 实线 | 空心菱形 | deP |
| ubiquitinates | 泛素化 | 实线 | 空心菱形 | Ub |
| methylates / acetylates | 甲基化/乙酰化 | 实线 | 空心菱形 | Me / Ac |
| other_modification | 其他修饰（糖基化等） | 实线 | 空心菱形 | 自定义 |
| transports | 转运 | 虚线 | 空心箭头 | — |
| translocates | 转位/易位/入核 | 虚线 | 空心箭头 | — |
| recruits | 募集 | 实线 | 空心箭头 | — |
| produces | 产生/分泌 | 实线 | 实心三角箭头 | — |
| degrades | 降解 | 虚线 | 实心三角箭头 | 降解 |
| indirect_effect | 间接作用 | 点线 | 空心箭头 | — |
| regulates_unspecified | 调控（方向/类型未指明） | 实线 | 空心箭头 | 待检验 |

## 3. 区室与布局规则

1. 区室按 `rank` 决定阅读顺序；跨膜受体必须落在 membrane 区室（渲染为双边框带），
   禁止画到胞内或胞外；配体在 extracellular，转录事件在 nucleus。
2. 边的方向由材料决定，布局不得反转上下游；同一区室内部就近连接，跨区室走肘形连接，
   肘点落在区室间隙，避免穿过无关节点；检测到遮挡时自动搜索平行走廊绕行。
3. 分支：同一源的多条边分别建边，不合并；反馈环显式 `feedback=true`，走独立编号的
   下方车道，颜色与普通边区分；自环（source==target）渲染为节点上方环形路径。
4. 自动布局按区室网格打包，节点盒随标签文本自适应；需要精确控制时在 `layout.positions`
   给中心点坐标，未给坐标的元素仍自动排布；越界/重叠坐标会被校验 W302/W303 捕获。
5. 路径长度不足以容纳文字标签时自动抑制标签，禁止标签互相重叠；出现拥挤（W204）时
   优先增大画布或拆成子图，不得靠缩小字号硬塞。

## 4. 图例与数据编码规则

- 图例由渲染器**从 IR 确定性生成并先测高度**：关系字形（仅列实际用到的）、实体形状、
  连续色标（带 domain 数值）或分类色板、自定义条目；面板高度随条目自适应，不溢出。
- 图面出现的每种颜色/形状/线型都必须在图例可解释；校验 E304 会把节点填色与
  调色板/映射输出做集合交叉检查，出现图例外颜色即报错。
- 分类值不在 categories 或连续变量取到非数值时，渲染未知灰色并由 W208/W209 警告，
  不得静默使用近似颜色。
- 数值标注（fold change、p 值、置信度、时间点、星号）必须在 `data` 登记来源；
  材料没有的数值一律不画。

## 5. result.json 输出契约

`/app/output/result.json` 至少包含以下字段；若 case.json 声明了 `output_contract`，
必须把其要求的全部键合并进来（以案例要求为准），并原样回填 `case_id`：

```json
{
  "case_id": "案例 ID",
  "status": "success | partial | failed",
  "summary": "一句话说明完成了什么",
  "artifacts": [
    {"name": "figure.svg", "path": "/app/output/figure.svg", "kind": "svg", "editable": true, "bytes": 0, "checks": {}},
    {"name": "figure.png", "path": "/app/output/figure.png", "kind": "png", "editable": false, "bytes": 0, "checks": {"magic": true}},
    {"name": "figure.pdf", "path": "/app/output/figure.pdf", "kind": "pdf", "editable": false, "bytes": 0, "checks": {"magic": true}}
  ],
  "ir_path": "/app/work/figure_ir.json",
  "counts": {"entities": 0, "edges": 0, "compartments": 0},
  "entity_index": [{"id": "", "label": "", "kind": "", "compartment": "", "sources": []}],
  "edge_index": [{"id": "", "source": "", "target": "", "relation": "", "direction": "", "strength": "", "evidence_source": "", "quote": ""}],
  "sources": [],
  "legend_mapping": [],
  "validation": {"status": "passed", "errors": 0, "warnings": 0, "report_path": "/app/work/validation.json"},
  "export_report": {},
  "uncertainty": [{"item": "", "issue": "", "handling": ""}],
  "change_records": [{"timestamp": "ISO8601 UTC", "action": "", "detail": "", "by": "agent"}],
  "environment": {"python": "", "export_backend": "", "cjk_font": ""},
  "notes": "限制、未完成项与失败原因；partial/failed 时必须如实填写"
}
```

## 6. 源保留编辑类案例（edit）

当任务要求修改既有图（改标签、改关系、改配色、加/删节点）：

1. `python3 <SKILL_DIR>/scripts/inspect_svg.py <既有.svg>` 取结构清单，确认图层/ID 是否规范。
2. 若源 SVG 即本 Skill 产物：直接回溯其 IR，按工单改 IR（在 `edit_context.requested_changes`
   与 change_records 逐条登记），重新渲染并导出，图层与未涉及元素保持不变。
3. 若源 SVG 为外部文件：先在 IR 中重建其实体/边（证据来源指向该 SVG 与任务材料），
   再做请求的修改；保留源文件不覆盖，新文件另存，并在 notes 说明哪些层被重建。
4. 每条修改一条 change_record：时间戳、动作、细节、执行者；人工确认项标注 `by: human`。

## 7. 异常处理矩阵

| 情况 | 处置 |
|---|---|
| 材料缺方向/缺关系类型 | `regulates_unspecified` + unverified，uncertainty 显式说明，不猜方向 |
| 实体名歧义（同名基因/蛋白、跨物种同名） | 拆实体 + note 说明依据，synonyms/external_ids 消歧 |
| 材料之间表述矛盾 | strength=conflicting，列出两边 quote 与出处，不替材料裁决 |
| 图示与数据矛盾 | 以真实数据为准修正映射，矛盾点写入 uncertainty，禁止改数据迁就图 |
| 分类值越界/连续值非数值 | 渲染未知灰色，W208/W209 警告并在 notes 说明，不猜测映射 |
| 无 CJK 字体/字体缺失 | 记录字体环境，导出预览可能出现方框；在 notes 标明并给出替换字体建议 |
| 导出后端缺失或某格式失败 | 状态 partial，保留 SVG 与失败原因，不伪造文件 |
| 节点过多不可读 | 增大画布/拆子图，校验 W204 未消除前不得宣称完成 |
| 材料文件缺失/无法解析 | status=failed 或 partial，写明缺失对象与已完成部分，不补造内容 |

## 8. 交付前自查门禁（逐条打勾）

1. 每个实体、每条边、每个数值都能指回 sources 中的真实页/表/图。
2. 基因/蛋白斜体与大小写正确；受体在膜上；无悬空边、无重复 ID。
3. 激活/抑制/结合/修饰/转运的端点样式彼此可区分，方向与原句一致。
4. 图例覆盖图面全部视觉编码，E304 类颜色交叉检查通过。
5. SVG 为合法 XML、命名图层齐全、标签为可编辑文本、字体族可替换。
6. PNG/PDF 真实生成并通过魔校验；失败项有诚实说明。
7. result.json 含 case_id、真实 status、证据索引、uncertainty、change_records。

## 9. 硬性禁令

- 禁止编造实体、ID、箭头方向、数值、p 值、来源或软件状态；不依据领域标签脑补材料。
- 禁止只交位图；可编辑 SVG 源文件是必交项。
- 禁止使用“已证实/证实”等绝对化判定，统一用证据强度四档表述。
- 禁止覆盖用户/案例提供的原始材料；中间稿与最终稿分离存放。
