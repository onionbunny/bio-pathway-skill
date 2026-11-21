#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_ir.py — 从 case.json 生成 IR 骨架（不预填任何实体/边答案）
材料中声明的文件会登记为 sources，实体与关系留空，由执行 Agent 从事实材料提取。
"""
import argparse
import json
import os
from datetime import datetime, timezone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--case', default='')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    case = {}
    if args.case and os.path.exists(args.case):
        with open(args.case, encoding='utf-8') as f:
            case = json.load(f)

    sources = []
    materials = case.get('materials') or case.get('resources') or []
    for i, m in enumerate(materials, 1):
        if isinstance(m, dict):
            sources.append({
                'id': f'S{i}', 'type': m.get('type', 'other'),
                'title': m.get('title', m.get('path', f'material-{i}')),
                'locator': m.get('path', m.get('locator', '')),
                'version': m.get('version', ''),
            })
        else:
            sources.append({'id': f'S{i}', 'type': 'other', 'title': str(m), 'locator': str(m)})

    ir = {
        'schema_version': 'bio-pathway-ir/1.0',
        'case_id': case.get('case_id', case.get('id', '')),
        'title': case.get('title', ''),
        'organism': case.get('organism', ''),
        'ir_version': '0.1-draft',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'sources': sources,
        'compartments': [
            {'id': 'ext', 'label': '细胞外 Extracellular', 'kind': 'extracellular', 'rank': 0},
            {'id': 'mem', 'label': '细胞膜 Membrane', 'kind': 'membrane', 'rank': 1},
            {'id': 'cyto', 'label': '细胞质 Cytoplasm', 'kind': 'cytoplasm', 'rank': 2},
            {'id': 'nuc', 'label': '细胞核 Nucleus', 'kind': 'nucleus', 'rank': 3},
        ],
        'entities': [],
        'edges': [],
        'data_mappings': {},
        'legend': {'custom_entries': [], 'show_relations': True, 'show_kinds': True, 'show_scales': True},
        'layout': {'width': 1280, 'height': 880, 'orientation': 'columns'},
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or '.', exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(ir, f, ensure_ascii=False, indent=2)
    print(json.dumps({'ok': True, 'ir': os.path.abspath(args.out),
                      'next_steps': [
                          '1. 通读 task.md 与全部 sources，逐句提取实体与关系',
                          '2. 按 vocab/naming_rules.md 归一命名，登记 external_ids/synonyms',
                          '3. 按 vocab/relations.json 判定 relation 与证据强度',
                          '4. 数据数值登记 data+source，配置 data_mappings',
                          '5. svg_render.py 渲染 → validate.py 校验 → export_artifacts.py 导出']},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
