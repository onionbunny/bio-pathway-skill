#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py — 机制图 IR 与导出 SVG 的独立校验
输出 JSON 报告；存在 error 级问题时退出码 1。
"""
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True   # 禁止在提交目录生成 __pycache__
sys.path.insert(0, SCRIPT_DIR)
try:
    from svg_render import GLYPH, Mappings  # 复用同一套关系与映射逻辑
except Exception:
    GLYPH, Mappings = None, None

SVG_NS = 'http://www.w3.org/2000/svg'
NS = {'s': SVG_NS}


class Report:
    def __init__(self):
        self.findings = []

    def add(self, severity, fid, target, message):
        self.findings.append({'severity': severity, 'id': fid, 'target': target, 'message': message})

    def err(self, *a):
        self.add('error', *a)

    def warn(self, *a):
        self.add('warning', *a)

    @property
    def n_error(self):
        return sum(1 for f in self.findings if f['severity'] == 'error')

    @property
    def n_warn(self):
        return sum(1 for f in self.findings if f['severity'] == 'warning')


def validate_ir(ir, vocab, pal, rep):
    # 基本字段
    for key in ('case_id', 'sources', 'compartments', 'entities', 'edges'):
        if key not in ir:
            rep.err('E100', key, f'缺少顶层必需字段 {key}')
    if rep.n_error:
        return

    src_ids = {s['id'] for s in ir['sources']}
    comp_ids = {c['id'] for c in ir['compartments']}
    comp_kind = {c['id']: c['kind'] for c in ir['compartments']}

    # 重复 ID
    ent_ids = [e['id'] for e in ir['entities']]
    edge_ids = [x['id'] for x in ir['edges']]
    for group, name in ((ent_ids, 'entity'), (edge_ids, 'edge'), (list(src_ids), 'source'), (list(comp_ids), 'compartment')):
        dup = {i for i in group if group.count(i) > 1}
        for d in dup:
            rep.err('E102', f'{name}:{d}', f'{name} ID 重复')

    ent_set = set(ent_ids)
    organism = (ir.get('organism') or '').lower()
    is_human = 'sapiens' in organism or '人' in (ir.get('organism') or '')
    is_mouse = 'musculus' in organism or 'mouse' in organism or '小鼠' in (ir.get('organism') or '')

    rel_map = {r['relation']: r for r in vocab['relations']}
    for ent in ir['entities']:
        # 来源引用
        for ref in ent.get('sources', []):
            if ref.split('#')[0] not in src_ids:
                rep.err('E106', ent['id'], f'实体来源引用 {ref} 不在 sources 中')
        for d in ent.get('data', []) or []:
            if d.get('source', '').split('#')[0] not in src_ids:
                rep.err('E107', ent['id'], f'数据 {d.get("variable")} 的来源无效')
        for xid in ent.get('external_ids', []) or []:
            if xid.get('source') and xid['source'].split('#')[0] not in src_ids:
                rep.warn('E107', ent['id'], f'外部 ID {xid.get("db")} 的来源引用无效')
        # 区室
        if ent['compartment'] not in comp_ids:
            rep.err('E108', ent['id'], f'区室 {ent["compartment"]} 不存在')
        # 命名启发式
        if ent['kind'] == 'gene':
            if not ent.get('italic'):
                rep.warn('W201', ent['id'], '基因实体应设置 italic=true')
            if is_human and not re.fullmatch(r'[A-Z0-9\-]+', ent['label']):
                rep.warn('W201', ent['id'], f'人基因符号应为大写斜体，当前标签 {ent["label"]}')
            if is_mouse and not re.fullmatch(r'[A-Z][a-z0-9A-Z]*', ent['label']):
                rep.warn('W201', ent['id'], f'小鼠基因符号应仅首字母大写，当前标签 {ent["label"]}')
        if ent['kind'] == 'protein' and ent.get('italic'):
            rep.warn('W201', ent['id'], '蛋白实体应为正体（italic=false）')
        # 膜定位启发式
        role = (ent.get('role') or '') + ' ' + (ent.get('note') or '')
        if any(k in role for k in ('受体', '通道', '转运', 'receptor', 'channel', 'transporter')):
            if comp_kind.get(ent['compartment']) != 'membrane':
                rep.warn('W206', ent['id'], '受体/通道/转运蛋白应位于 membrane 区室')
        if comp_kind.get(ent['compartment']) == 'membrane' and not any(
                k in role for k in ('受体', '通道', '转运', '膜', 'receptor', 'channel', 'transporter', 'membrane')):
            rep.warn('W206', ent['id'], '膜区室中的实体缺少受体/通道/转运等角色说明')

    for edge in ir['edges']:
        if edge['source'] not in ent_set:
            rep.err('E103', edge['id'], f'边起点 {edge["source"]} 不存在')
        if edge['target'] not in ent_set:
            rep.err('E103', edge['id'], f'边终点 {edge["target"]} 不存在')
        if edge['relation'] not in rel_map:
            rep.err('E104', edge['id'], f'未知关系类型 {edge["relation"]}')
        ev = edge.get('evidence', {})
        if not ev.get('source') or ev.get('source', '').split('#')[0] not in src_ids:
            rep.err('E105', edge['id'], '证据来源缺失或无效')
        if not ev.get('quote'):
            rep.err('E105', edge['id'], '证据原文 quote 缺失')
        if ev.get('strength') not in vocab['strength_levels']:
            rep.err('E105', edge['id'], '证据强度字段缺失或非法')
        if ev.get('strength') == 'conflicting' and not (edge.get('note') or ir.get('uncertainty')):
            rep.warn('W207', edge['id'], '证据不一致的边应在 note/uncertainty 说明矛盾点')
        # 引用句与触发词核对
        quote = (ev.get('quote') or '').lower()
        rspec = rel_map.get(edge['relation'])
        if rspec and quote:
            cues = [c.lower() for c in rspec.get('cues_en', [])] + rspec.get('cues_zh', [])
            if not any(c in quote for c in cues):
                rep.warn('W202', edge['id'], '证据句中未出现该关系的典型触发词，需人工复核语义')
        # 反馈环标注
        if edge['source'] in ent_set and edge['target'] in ent_set:
            s_comp = next((e['compartment'] for e in ir['entities'] if e['id'] == edge['source']), None)
            t_comp = next((e['compartment'] for e in ir['entities'] if e['id'] == edge['target']), None)
            rank = {c['id']: c['rank'] for c in ir['compartments']}
            if s_comp in rank and t_comp in rank and rank[t_comp] < rank[s_comp] and not edge.get('feedback'):
                rep.warn('W205', edge['id'], '边指向上游区室，疑似反馈环但未标 feedback=true')

    # 数据映射覆盖与图例一致性
    mappings = ir.get('data_mappings', {}) or {}
    for ch, spec in mappings.items():
        variable = spec['variable']
        if ch.startswith('edge'):
            pool = ir['edges']
        else:
            pool = ir['entities']
        missing = [p['id'] for p in pool if not any(d.get('variable') == variable for d in p.get('data', []) or [])]
        if missing:
            rep.warn('W203', ch, f'变量 {variable} 在 {len(missing)} 个元素上无数据，将回退默认样式：{missing[:5]}')
        if spec.get('source') and spec['source'].split('#')[0] not in src_ids:
            rep.err('E107', ch, f'映射 {ch} 的来源无效')

    # 图面密度
    lay = ir.get('layout', {}) or {}
    W, H = lay.get('width', 1280), lay.get('height', 880)
    area = W * H
    density = len(ir['entities']) / area * 100000
    if density > 9:
        rep.warn('W204', 'layout', f'节点密度 {density:.1f} 个/10万px²，存在拥挤风险，建议增大画布或拆图')

    # 显式坐标：越界检查
    positions = lay.get('positions', {}) or {}
    for eid, p in positions.items():
        px, py = p.get('x'), p.get('y')
        if px is None or py is None:
            rep.err('E110', eid, '显式坐标缺少 x/y')
            continue
        if not (0 <= px <= W and 0 <= py <= H):
            rep.warn('W302', eid, f'显式坐标 ({px},{py}) 超出画布 {W}x{H}，节点可能不可见')

    # 显式坐标：两两重叠检查（按默认半宽 62/半高 24 估算）
    pos_items = list(positions.items())
    for i in range(len(pos_items)):
        for j in range(i + 1, len(pos_items)):
            (id1, p1), (id2, p2) = pos_items[i], pos_items[j]
            if abs(p1.get('x', 0) - p2.get('x', 0)) < 110 and abs(p1.get('y', 0) - p2.get('y', 0)) < 40:
                rep.warn('W303', f'{id1}/{id2}', '显式坐标导致节点重叠，需调整 positions')

    # 分类映射：值不在 categories 中；连续映射：非数值检查
    for ch, spec in mappings.items():
        pool = ir['edges'] if ch.startswith('edge') else ir['entities']
        cats = spec.get('categories', [])
        for item in pool:
            for d in item.get('data', []) or []:
                if d.get('variable') != spec['variable']:
                    continue
                val = d.get('value')
                if spec.get('type') == 'categorical':
                    if val not in cats:
                        rep.warn('W208', item['id'], f'分类值 {val} 不在 categories，将显示未知灰色')
                else:
                    try:
                        float(val)
                    except (TypeError, ValueError):
                        rep.warn('W209', item['id'], f'连续变量 {spec["variable"]} 的值 "{val}" 非数值，将显示未知灰色')


def validate_svg(svg_path, ir, pal, rep):
    if not svg_path or not os.path.exists(svg_path):
        rep.warn('W300', 'svg', '未提供 SVG，跳过图面校验')
        return None
    try:
        tree = ET.parse(svg_path)
    except Exception as e:
        rep.err('E300', 'svg', f'SVG 不是合法 XML: {e}')
        return None
    root = tree.getroot()

    # 图层
    layer_ids = {g.get('id') for g in root.iter(f'{{{SVG_NS}}}g')}
    for need in ('layer-00-background', 'layer-10-compartments', 'layer-20-edges', 'layer-30-entities', 'layer-50-legend'):
        if need not in layer_ids:
            rep.err('E301', need, f'缺少命名图层 {need}')

    # 所有 url(#...) 引用必须有定义
    defined = set()
    for el in root.iter():
        if el.get('id'):
            defined.add(el.get('id'))
    ref_re = re.compile(r'url\(#([^)]+)\)')
    for el in root.iter():
        for attr, val in el.attrib.items():
            for rid in ref_re.findall(val or ''):
                if rid not in defined:
                    rep.err('E302', rid, f'引用 url(#{rid}) 无对应定义')

    # 文本：每个实体标签必须是真实 <text>
    label_ids = {t.get('id') for t in root.iter(f'{{{SVG_NS}}}text')}
    for ent in ir['entities']:
        if f'label-{ent["id"]}' not in label_ids:
            rep.err('E303', ent['id'], '实体标签不是可编辑文本节点')
    texts = list(root.iter(f'{{{SVG_NS}}}text'))
    no_font = [t.get('id') for t in texts if not t.get('font-family')]
    if no_font:
        rep.warn('W301', 'text', f'{len(no_font)} 个文本节点未声明 font-family')
    families = ' '.join(t.get('font-family', '') for t in texts)
    if 'sans-serif' not in families and 'serif' not in families:
        rep.warn('W301', 'text', '未使用通用字体族，跨环境字体替换风险')

    # 节点填色与 IR/调色板自洽交叉检查
    if Mappings is not None:
        maps = Mappings(ir, pal)
        allowed = {v['fill'].lower() for v in pal['entity_kind'].values()}
        allowed.add(pal.get('unknown', '#d9d9d9').lower())
        for ent in ir['entities']:
            computed, _ok = maps.node_fill(ent)
            if computed is None:
                computed = pal['entity_kind'].get(ent['kind'], pal['entity_kind']['other'])['fill']
            allowed.add(computed.lower())
        for g in root.iter(f'{{{SVG_NS}}}g'):
            if not (g.get('id') or '').startswith('node-'):
                continue
            for shape in g:
                if shape.tag == f'{{{SVG_NS}}}text':
                    continue
                fill = (shape.get('fill') or '').lower()
                if fill and fill not in allowed and fill != 'none':
                    rep.err('E304', g.get('id'), f'节点填色 {fill} 不在调色板/数据映射输出中，图例无法解释')

    # 边端点标记与关系一致
    edge_groups = {g.get('id'): g for g in root.iter(f'{{{SVG_NS}}}g') if (g.get('id') or '').startswith('edge-')}
    for edge in ir['edges']:
        g = edge_groups.get(f'edge-{edge["id"]}')
        if g is None:
            rep.err('E305', edge['id'], 'SVG 中缺少该边的图元组')
            continue
        path = next((el for el in g if el.tag == f'{{{SVG_NS}}}path'), None)
        if path is None:
            rep.err('E305', edge['id'], '边缺少 path 元素')
            continue
        if not path.get('marker-end'):
            rep.err('E305', edge['id'], '边缺少端点标记，语义不可区分')
        if edge.get('direction') == 'bidirectional' and not path.get('marker-start'):
            rep.err('E306', edge['id'], '双向边缺少起点标记 marker-start')
        if edge['source'] == edge['target'] and len(path.get('d', '')) < 12:
            rep.err('E307', edge['id'], '自环边未正确渲染为环形路径')
    return root


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ir', required=True)
    ap.add_argument('--svg', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--vocab', default=os.path.join(SCRIPT_DIR, '..', 'vocab', 'relations.json'))
    ap.add_argument('--palette', default=os.path.join(SCRIPT_DIR, '..', 'templates', 'palette.json'))
    args = ap.parse_args()

    with open(args.ir, encoding='utf-8') as f:
        ir = json.load(f)
    with open(args.vocab, encoding='utf-8') as f:
        vocab = json.load(f)
    with open(args.palette, encoding='utf-8') as f:
        pal = json.load(f)

    rep = Report()
    validate_ir(ir, vocab, pal, rep)
    validate_svg(args.svg, ir, pal, rep)

    report = {
        'case_id': ir.get('case_id'),
        'status': 'passed' if rep.n_error == 0 else 'failed',
        'errors': rep.n_error,
        'warnings': rep.n_warn,
        'findings': rep.findings,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if rep.n_error else 0)


if __name__ == '__main__':
    main()
