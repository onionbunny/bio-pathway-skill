# 最小调用示例（教学演示，非正式案例输出）

本示例使用合成材料 `examples/example_ir.json`，其中所有 quote 均为合成语句，
仅用于演示接口与完整流程，禁止冒充正式案例证据。

## 输入

- IR：`examples/example_ir.json`（6 实体 / 6 边，覆盖线性链路、跨膜、磷酸化、
  转位、反馈环、diverging 数据映射）。

## 调用

```bash
SKILL_DIR=.   # 正式环境为 /skills/weekly-skill
python3 $SKILL_DIR/scripts/svg_render.py --ir examples/example_ir.json --out /tmp/example.svg
python3 $SKILL_DIR/scripts/validate.py --ir examples/example_ir.json \
  --svg /tmp/example.svg --out /tmp/validation.json
python3 $SKILL_DIR/scripts/export_artifacts.py --svg /tmp/example.svg \
  --outdir /tmp --formats png,pdf
python3 $SKILL_DIR/scripts/inspect_svg.py /tmp/example.svg | head
```

## 示意输出（标明为示例）

- `example.svg`：分层可编辑源文件（layer-00/10/20/30/50，node-/edge- 稳定 ID，真实文本）。
- `validation.json`：`status=passed, errors=0`。
- `example.png` / `example.pdf`：渲染预览；export_report.json 记录后端与校验结果。
- 打开 SVG 修改任一 `label-*` 文本或在 IR 改标签后重新执行渲染，即可得到更新图，
  这是“可编辑、可复跑”的验收方式。

正式运行时，输入替换为 `/input/case.json` 与 `/input/task.md`，工作目录 `/app/work`，
最终产物写入 `/app/output`，流程与命令完全相同。
