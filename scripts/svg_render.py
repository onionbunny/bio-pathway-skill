#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
svg_render.py — 生物机制图/通路图确定性渲染器（v2）
输入: figure_ir.json (schema bio-pathway-ir/1.0)
输出: 分层、可编辑 SVG（真实 <text>，命名图层，语义化端点，自适应布局）
仅依赖 Python 标准库。
"""
import argparse
import json
import math
import os
import xml.sax.saxutils as su

# ================================================================ 基础工具

def esc(s):
    return su.escape(str(s), {'"': '&quot;'})


def hex_to_rgb(h):
    h = h.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def lerp(a, b, t):
    return a + (b - a) * t


def sample_ramp(palette, t):
    t = max(0.0, min(1.0, t))
    colors = [hex_to_rgb(c) for c in palette]
    if len(colors) == 1:
        return rgb_to_hex(colors[0])
    pos = t * (len(colors) - 1)
    i = int(pos)
    if i >= len(colors) - 1:
        return rgb_to_hex(colors[-1])
    f = pos - i
    return rgb_to_hex(tuple(lerp(colors[i][k], colors[i + 1][k], f) for k in range(3)))


def safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_wide(ch):
    """CJK/全角字符按全宽估算。"""
    code = ord(ch)
    return code >= 0x2E80


def text_width(s, fs):
    return sum(fs if is_wide(ch) else 0.56 * fs for ch in s)


def wrap_text(label, target_w, fs):
    """贪心换行：英文按词、CJK 按字；超长 token 硬切；不丢弃内容。"""
    label = str(label)
    # 先切 token：连续 ASCII 为一个词，CJK 单字成 token
    tokens, buf = [], ''
    for ch in label:
        if is_wide(ch) or ch in ' /-':
            if buf:
                tokens.append(buf); buf = ''
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)

    lines, cur = [], ''
    for tk in tokens:
        if tk == ' ':
            cand = cur + ' '
            if text_width(cand, fs) <= target_w:
                cur = cand
                continue
            if cur.strip():
                lines.append(cur.strip()); cur = ''
            continue
        if text_width(cur + tk, fs) <= target_w:
            cur += tk
        else:
            if cur.strip():
                lines.append(cur.strip()); cur = ''
            if text_width(tk, fs) > target_w:
                # 硬切长 token
                piece = ''
                for ch in tk:
                    if text_width(piece + ch, fs) > target_w:
                        lines.append(piece); piece = ''
                    piece += ch
                cur = piece
            else:
                cur = tk
    if cur.strip():
        lines.append(cur.strip())
    return lines or [label]


# ================================================================ 映射求值

class Mappings:
    def __init__(self, ir, palette):
        self.specs = ir.get('data_mappings', {}) or {}
        self.palette = palette

    def _data_value(self, item, variable):
        for d in item.get('data', []) or []:
            if d.get('variable') == variable:
                return d.get('value')
        return None

    def _scale_t(self, value, spec):
        domain = spec.get('domain')
        fv = safe_float(value)
        if fv is None:
            return None
        if domain and len(domain) == 2 and domain[1] > domain[0]:
            t = (fv - domain[0]) / (domain[1] - domain[0])
        else:
            t = 0.5
        return max(0.0, min(1.0, t))

    def _categorical(self, spec, value):
        cats = spec.get('categories', [])
        pal = spec.get('palette') or self.palette['categorical']
        if str(value) in cats:
            return pal[cats.index(str(value)) % len(pal)], True
        return self.palette.get('unknown', '#d9d9d9'), False

    def node_fill(self, ent):
        spec = self.specs.get('node_fill')
        if not spec:
            return None, True
        val = self._data_value(ent, spec['variable'])
        if val is None:
            return None, True
        if spec['type'] == 'categorical':
            return self._categorical(spec, val)
        t = self._scale_t(val, spec)
        if t is None:
            return self.palette.get('unknown', '#d9d9d9'), False
        if spec['type'] == 'diverging':
            pal = spec.get('palette') or self.palette['diverging']
        else:
            pal = spec.get('palette') or self.palette['sequential']
        return sample_ramp(pal, t), True

    def node_scale(self, ent):
        spec = self.specs.get('node_size')
        if not spec:
            return 1.0
        val = self._data_value(ent, spec['variable'])
        t = self._scale_t(val, spec) if val is not None else None
        if t is None:
            return 1.0
        rng = spec.get('range', [0.85, 1.25])
        return lerp(float(rng[0]), float(rng[1]), t)

    def edge_width(self, edge):
        spec = self.specs.get('edge_width')
        if not spec:
            return 2.0
        val = self._data_value(edge, spec['variable'])
        t = self._scale_t(val, spec) if val is not None else None
        if t is None:
            return 2.0
        rng = spec.get('range', [1.5, 4.5])
        return lerp(float(rng[0]), float(rng[1]), t)

    def edge_color(self, edge):
        spec = self.specs.get('edge_stroke')
        if spec:
            val = self._data_value(edge, spec['variable'])
            if val is not None:
                if spec['type'] == 'categorical':
                    col, ok = self._categorical(spec, val)
                    return col
                t = self._scale_t(val, spec)
                if t is not None:
                    pal = spec.get('palette') or self.palette['sequential']
                    return sample_ramp(pal, t)
        if edge.get('feedback'):
            return self.palette['edge']['feedback']
        return self.palette['edge']['default']


# ================================================================ 关系字形

GLYPH = {
    'activates':        ('solid',  'filled_arrow',  ''),
    'inhibits':         ('solid',  't_bar',         ''),
    'binds':            ('solid',  'filled_circle', ''),
    'phosphorylates':   ('solid',  'open_diamond',  'P'),
    'dephosphorylates': ('solid',  'open_diamond',  'deP'),
    'ubiquitinates':    ('solid',  'open_diamond',  'Ub'),
    'methylates':       ('solid',  'open_diamond',  'Me'),
    'acetylates':       ('solid',  'open_diamond',  'Ac'),
    'other_modification': ('solid', 'open_diamond', 'mod'),
    'transports':       ('dashed', 'open_arrow',    ''),
    'translocates':     ('dashed', 'open_arrow',    ''),
    'recruits':         ('solid',  'open_arrow',    ''),
    'produces':         ('solid',  'filled_arrow',  ''),
    'degrades':         ('dashed', 'filled_arrow',  '降解'),
    'indirect_effect':  ('dotted', 'open_arrow',    ''),
    'regulates_unspecified': ('solid', 'open_arrow', ''),
}

REL_ZH = {
    'activates': '激活', 'inhibits': '抑制', 'binds': '结合',
    'phosphorylates': '磷酸化', 'dephosphorylates': '去磷酸化',
    'ubiquitinates': '泛素化', 'methylates': '甲基化', 'acetylates': '乙酰化',
    'other_modification': '修饰', 'transports': '转运', 'translocates': '转位',
    'recruits': '募集', 'produces': '产生', 'degrades': '降解',
    'indirect_effect': '间接作用', 'regulates_unspecified': '调控(待检验)',
}

STRENGTH_ZH = {
    'supports': '证据支持', 'partially_supports': '部分支持',
    'conflicting': '证据不一致', 'unverified': '待检验',
}

KIND_ZH = {'gene': '基因', 'rna': 'RNA', 'protein': '蛋白', 'complex': '复合物',
           'small_molecule': '小分子', 'process': '过程', 'cell_type': '细胞',
           'drug': '药物', 'phenotype': '表型', 'other': '其他'}


# ================================================================ 节点形状

def anchors(node):
    x, y, w, h = node['x'], node['y'], node['w'], node['h']
    return {'W': (x, y + h / 2), 'E': (x + w, y + h / 2),
            'N': (x + w / 2, y), 'S': (x + w / 2, y + h),
            'C': (x + w / 2, y + h / 2)}


def node_shape_svg(node, font_family):
    ent = node['ent']
    x, y, w, h = node['x'], node['y'], node['w'], node['h']
    kind = ent['kind']
    fill, stroke = node['fill'], node['stroke']
    italic = ent.get('italic') or kind == 'gene'
    fs = node['fs']
    lines = node['lines']
    line_h = fs + 2
    parts = [f'<g id="node-{esc(ent["id"])}" class="node kind-{esc(kind)}">']
    sw = 1.8
    if kind == 'protein':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    elif kind == 'gene':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    elif kind == 'rna':
        sl = 12
        pts = f'{x + sl},{y} {x + w},{y} {x + w - sl},{y + h} {x},{y + h}'
        parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    elif kind == 'complex':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
        parts.append(f'<rect x="{x + 4}" y="{y + 4}" width="{w - 8}" height="{h - 8}" rx="6" fill="none" stroke="{stroke}" stroke-width="1.2"/>')
    elif kind == 'small_molecule':
        parts.append(f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    elif kind == 'process':
        cx, cy = x + w / 2, y + h / 2
        pts = f'{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}'
        parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
    elif kind == 'drug':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-dasharray="5,3"/>')
    elif kind == 'phenotype':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-dasharray="2,3"/>')
    elif kind == 'cell_type':
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{stroke}" stroke-width="2.2"/>')
    else:
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    ty = y + h / 2 - (len(lines) - 1) * line_h / 2 + fs / 3
    font_style = 'italic' if italic else 'normal'
    parts.append(f'<text id="label-{esc(ent["id"])}" x="{x + w / 2}" y="{ty:.1f}" text-anchor="middle" '
                 f'font-family="{font_family}" font-size="{fs}" font-style="{font_style}" fill="#1a1a1a">')
    for i, ln in enumerate(lines):
        parts.append(f'<tspan x="{x + w / 2}" dy="{0 if i == 0 else line_h}">{esc(ln)}</tspan>')
    parts.append('</text>')
    if ent.get('note'):
        parts.append(f'<title>{esc(ent["id"])}: {esc(ent["note"])}</title>')
    parts.append('</g>')
    return ''.join(parts)


# ================================================================ 渲染主体

class Renderer:
    def __init__(self, ir, palette):
        self.ir = ir
        self.pal = palette
        self.font = palette['font_family']
        self.maps = Mappings(ir, palette)
        self.warnings = []
        self.markers_used = {}     # (relation,color) -> end marker id
        self.start_markers = {}    # end id -> start id
        self.gradients = {}
        self.nodes = {}
        self.comps = sorted(ir.get('compartments', []), key=lambda c: c['rank'])
        lay = ir.get('layout', {}) or {}
        self.W0 = lay.get('width', 1280)
        self.H0 = lay.get('height', 880)
        self.W, self.H = self.W0, self.H0
        self.orientation = lay.get('orientation', 'columns')
        self.margin = lay.get('margin', 34)
        self.gap = lay.get('gap', 26)
        self.node_w0 = lay.get('node_width', 132)
        self.node_h0 = lay.get('node_height', 48)

    # ---------- 节点盒测算
    def compute_box(self, ent):
        scale = self.maps.node_scale(ent)
        fs = 13
        target_w = self.node_w0 - 22
        lines = wrap_text(ent['label'], target_w, fs)
        widest = max(text_width(ln, fs) for ln in lines)
        if widest > target_w and fs > 10:
            fs = 11
            lines = wrap_text(ent['label'], self.node_w0 - 18, fs)
            widest = max(text_width(ln, fs) for ln in lines)
        line_h = fs + 2
        w = max(72, min(240, widest + 24))
        h = max(40, min(150, len(lines) * line_h + 14))
        w *= scale
        h *= scale
        return {'w': w, 'h': h, 'fs': fs, 'lines': lines}

    # ---------- 图例规划（先测高度）
    def legend_plan(self):
        items = []   # (width, kind)
        for rel in sorted({e['relation'] for e in self.ir.get('edges', [])}):
            items.append((112, 'rel', rel))
        for kd in sorted({e['kind'] for e in self.ir.get('entities', [])}):
            items.append((84, 'kind', kd))
        for ch, spec in (self.ir.get('data_mappings', {}) or {}).items():
            if spec['type'] in ('diverging', 'sequential'):
                items.append((228, 'scale', ch))
            elif spec['type'] == 'categorical':
                for cat in spec.get('categories', []):
                    items.append((74, 'cat', (ch, cat)))
        for ce in (self.ir.get('legend', {}) or {}).get('custom_entries', []) or []:
            items.append((130, 'custom', ce))
        panel_w = self.W - 2 * self.margin
        rows, cx = 1, self.margin + 16
        for w, *_ in items:
            if cx + w > self.W - self.margin - 16:
                rows += 1
                cx = self.margin + 16
            cx += w
        height = 38 + rows * 30 + 10
        return height, items

    # ---------- 布局
    def layout(self):
        legend_h, legend_items = self.legend_plan()
        self.legend_h = legend_h
        top = self.margin + 30
        bottom = self.H - legend_h - 16
        fig_h = bottom - top
        n = len(self.comps)

        by_comp = {c['id']: [] for c in self.comps}
        for ent in self.ir.get('entities', []):
            by_comp.setdefault(ent['compartment'], []).append(ent)

        positions = (self.ir.get('layout', {}) or {}).get('positions', {}) or {}
        self.comp_geom = {}

        if self.orientation == 'columns':
            band_w = (self.W - 2 * self.margin - self.gap * (n - 1)) / max(n, 1)
            for ci, comp in enumerate(self.comps):
                gx = self.margin + ci * (band_w + self.gap)
                gw = band_w
                self.comp_geom[comp['id']] = (gx, top, gw, fig_h)
                self._pack_grid(comp, by_comp[comp['id']], gx, top, gw, fig_h, positions, vertical=True)
        else:  # rows：水平带
            band_h = (fig_h - self.gap * (n - 1)) / max(n, 1)
            for ci, comp in enumerate(self.comps):
                gy = top + ci * (band_h + self.gap)
                self.comp_geom[comp['id']] = (self.margin, gy, self.W - 2 * self.margin, band_h)
                self._pack_grid(comp, by_comp[comp['id']], self.margin, gy, self.W - 2 * self.margin, band_h, positions, vertical=False)

        # 反馈车道与画布扩展
        self.feedback_edges = [e for e in self.ir.get('edges', []) if e.get('feedback')]
        if self.feedback_edges:
            base_edge = max(nd['y'] + nd['h'] for nd in self.nodes.values()) + 26
            self.feedback_lanes = {}
            for i, e in enumerate(self.feedback_edges):
                self.feedback_lanes[e['id']] = base_edge + 26 * i
            need_h = base_edge + 26 * len(self.feedback_edges) + 12
            if need_h > self.H - legend_h:
                self.H = int(need_h + legend_h + 12)

    def _pack_grid(self, comp, ents, gx, gy, gw, gh, positions, vertical):
        k = len(ents)
        if k == 0:
            return
        header = 26
        inner_w, inner_h = gw - 14, gh - header - 8
        # 先算所有盒子
        boxes = {ent['id']: self.compute_box(ent) for ent in ents}
        max_w = max(b['w'] for b in boxes.values())
        max_h = max(b['h'] for b in boxes.values())
        if vertical:
            ncols = max(1, int(inner_w // (max_w + 12)))
            nrows = math.ceil(k / ncols)
        else:
            nrows = max(1, int(inner_h // (max_h + 12)))
            ncols = math.ceil(k / nrows)
        cell_w = inner_w / ncols
        cell_h = inner_h / nrows
        # 整体缩放兜底（极端密集）
        fit = min(1.0, (cell_w - 8) / max_w, (cell_h - 8) / max_h)
        if fit < 1:
            self.warnings.append(f'区室 {comp["id"]} 空间不足，节点已按 {fit:.2f} 缩放，建议拆图或增大画布')
        for j, ent in enumerate(ents):
            b = boxes[ent['id']]
            w, h = b['w'] * fit, b['h'] * fit
            r, c = divmod(j, ncols)
            if ent['id'] in positions:
                px, py = positions[ent['id']]['x'], positions[ent['id']]['y']
                cx, cy = px, py
            else:
                cx = gx + 7 + cell_w * (c + 0.5)
                cy = gy + header + cell_h * (r + 0.5)
            fill, ok = self.maps.node_fill(ent)
            if not ok:
                self.warnings.append(f'实体 {ent["id"]} 的分类值不在 categories 中，使用未知灰色')
            if fill is None:
                fill = self.pal['entity_kind'].get(ent['kind'], self.pal['entity_kind']['other'])['fill']
            stroke = self.pal['entity_kind'].get(ent['kind'], self.pal['entity_kind']['other'])['stroke']
            self.nodes[ent['id']] = {
                'ent': ent, 'x': cx - w / 2, 'y': cy - h / 2, 'w': w, 'h': h,
                'fill': fill, 'stroke': stroke, 'fs': b['fs'], 'lines': b['lines'],
                'comp_rank': comp['rank']}

    # ---------- 标记
    def marker_id(self, relation, color):
        key = (relation, color)
        if key not in self.markers_used:
            self.markers_used[key] = f'mk-{relation}-{color.lstrip("#")}-{len(self.markers_used)}'
        return self.markers_used[key]

    def _marker_shape(self, mtype, color, reverse=False):
        if mtype == 'filled_arrow':
            d = 'M10,-4 L0,0 L10,4' if reverse else 'M0,-4 L10,0 L0,4'
            return f'<path d="{d}" fill="{color}"/>'
        if mtype == 'open_arrow':
            d = 'M9,-4 L0,0 L9,4' if reverse else 'M1,-4 L10,0 L1,4'
            return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8"/>'
        if mtype == 't_bar':
            x = 0 if reverse else 10
            return f'<path d="M{x},-8 L{x},8" stroke="{color}" stroke-width="2.4"/>'
        if mtype == 'filled_circle':
            cx = 4 if reverse else 6
            return f'<circle cx="{cx}" cy="0" r="4.5" fill="{color}"/>'
        if mtype == 'open_diamond':
            pts = '14,0 8,-5 2,0 8,5' if reverse else '2,0 8,-5 14,0 8,5'
            return f'<polygon points="{pts}" fill="#ffffff" stroke="{color}" stroke-width="1.8"/>'
        return ''

    def marker_defs(self):
        out = []
        for (relation, color), mid in self.markers_used.items():
            mtype = GLYPH[relation][1]
            vb = {'filled_arrow': ('0 -5 12 10', 10, 11, 9),
                  'open_arrow': ('0 -5 12 10', 10, 11, 9),
                  't_bar': ('0 -10 12 20', 10, 10, 16),
                  'filled_circle': ('0 -6 14 12', 10, 12, 12),
                  'open_diamond': ('0 -6 16 12', 14, 16, 11)}[mtype]
            vbx, refx, mw, mh = vb
            out.append(f'<marker id="{mid}" viewBox="{vbx}" refX="{refx}" refY="0" markerWidth="{mw}" markerHeight="{mh}" markerUnits="userSpaceOnUse" orient="auto">{self._marker_shape(mtype, color)}</marker>')
            # 反向起点标记
            smid = mid + '-s'
            sref = 0
            out.append(f'<marker id="{smid}" viewBox="{vbx}" refX="{sref}" refY="0" markerWidth="{mw}" markerHeight="{mh}" markerUnits="userSpaceOnUse" orient="auto">{self._marker_shape(mtype, color, reverse=True)}</marker>')
            self.start_markers[mid] = smid
        return ''.join(out)

    # ---------- 边
    def edge_text(self, edge):
        relation = edge['relation']
        line_style, mtype, gtag = GLYPH[relation]
        tag = edge.get('modification_label') or gtag
        if edge.get('label'):
            return edge['label']
        if relation == 'degrades':
            return tag
        if mtype == 'open_diamond' and tag:
            return f'{REL_ZH[relation]}({tag})'
        return REL_ZH[relation]

    # ---------- 障碍避让
    @staticmethod
    def _segment_hits(x1, y1, x2, y2, node, pad=7):
        nx, ny, nw, nh = node['x'] - pad, node['y'] - pad, node['w'] + 2 * pad, node['h'] + 2 * pad
        # 线段包围盒与膨胀节点盒相交即视为命中（保守策略，宁可绕行）
        bx1, by1 = min(x1, x2), min(y1, y2)
        bx2, by2 = max(x1, x2), max(y1, y2)
        return bx1 < nx + nw and bx2 > nx and by1 < ny + nh and by2 > ny

    def _free_y(self, x1, x2, preferred, avoid):
        if not any(self._segment_hits(x1, preferred, x2, preferred, nd) for nd in avoid):
            return preferred
        for step in (14, 28, 42, 56, 70):
            for cand in (preferred - step, preferred + step):
                if not any(self._segment_hits(x1, cand, x2, cand, nd) for nd in avoid):
                    return cand
        return preferred

    def edge_svg(self, edge):
        a = self.nodes.get(edge['source'])
        b = self.nodes.get(edge['target'])
        if not a or not b:
            return ''
        relation = edge['relation']
        line_style, mtype, gtag = GLYPH[relation]
        color = self.maps.edge_color(edge)
        width = self.maps.edge_width(edge)
        end_mid = self.marker_id(relation, color)
        dash = {'solid': 'none', 'dashed': '7,5', 'dotted': '2,4'}[line_style]
        aa, ba = anchors(a), anchors(b)

        # 并行边分组索引
        pair_key = tuple(sorted((edge['source'], edge['target'])))
        siblings = [x for x in self.ir['edges']
                    if tuple(sorted((x['source'], x['target']))) == pair_key]
        pidx = siblings.index(edge)
        npair = len(siblings)
        bidir = edge.get('direction') == 'bidirectional'
        start_marker = f' marker-start="url(#{end_mid}-s)"' if bidir else ''
        avoid = [nd for nid, nd in self.nodes.items() if nid not in (edge['source'], edge['target'])]

        show_label, lx, ly = True, 0, 0
        if edge['source'] == edge['target']:
            # 自环：节点上方环形路径，标记回到 N 锚点
            nx0, ny0 = aa['N']
            d = (f'M{nx0},{ny0 + 1} C {nx0 - 26},{ny0 - 30} {nx0 + 26},{ny0 - 30} {nx0},{ny0 + 1}')
            lx, ly = nx0, ny0 - 32
        elif edge.get('feedback'):
            lane_y = self.feedback_lanes[edge['id']]
            sx, sy = aa['S']
            tx, ty = ba['S']
            d = f'M{sx},{sy} L{sx},{lane_y} L{tx},{lane_y} L{tx},{ty + 8}'
            lx, ly = (sx + tx) / 2, lane_y - 6
            show_label = abs(sx - tx) >= 70
        elif a['comp_rank'] == b['comp_rank']:
            if abs(a['x'] - b['x']) < 2:
                # 同列纵向
                if a['y'] <= b['y']:
                    sx, sy = aa['S']; tx, ty = ba['N']
                else:
                    sx, sy = aa['N']; tx, ty = ba['S']
                d = f'M{sx},{sy} L{tx},{ty - 2}'
                lx, ly = (sx + tx) / 2 + 8, (sy + ty) / 2
                show_label = abs(sy - ty) >= 42
            else:
                if a['x'] < b['x']:
                    sx, sy = aa['E']; tx, ty = ba['W']
                else:
                    sx, sy = aa['W']; tx, ty = ba['E']
                preferred = sy + (pidx - (npair - 1) / 2) * 12
                free_y = self._free_y(sx, tx, preferred, avoid)
                mx = (sx + tx) / 2
                if abs(free_y - sy) < 1:
                    d = f'M{sx},{sy} L{tx},{ty}'
                else:
                    d = (f'M{sx},{sy} L{sx},{free_y} L{tx},{free_y} L{tx},{ty}')
                lx, ly = mx, free_y - 6
                show_label = abs(sx - tx) >= 76
        else:
            # 跨区室：肘形落在区间 gap
            if a['x'] < b['x']:
                sx, sy = aa['E']; tx, ty = ba['W']
            else:
                sx, sy = aa['W']; tx, ty = ba['E']
            mx = (sx + tx) / 2
            d = f'M{sx},{sy} L{mx},{sy} L{mx},{ty} L{tx},{ty}'
            lx, ly = mx, (sy + ty) / 2 - 7
            show_label = abs(sy - ty) >= 40

        parts = [f'<g id="edge-{esc(edge["id"])}" class="edge relation-{esc(relation)}">',
                 f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                 f'stroke-linejoin="round" stroke-linecap="round" stroke-dasharray="{dash}" '
                 f'marker-end="url(#{end_mid})"{start_marker}/>']
        if show_label:
            st = edge.get('evidence', {}).get('strength', 'unverified')
            st_label = STRENGTH_ZH.get(st, '待检验')
            inner = (f'{esc(self.edge_text(edge))} <tspan font-size="9" fill="{self.pal["edge"]["strength_tag"]}">'
                     f'[{esc(st_label)}]</tspan>')
            parts.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-family="{self.font}" font-size="11" '
                         f'stroke="{self.pal["edge"]["label_halo"]}" stroke-width="4">{inner}</text>')
            parts.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-family="{self.font}" font-size="11" fill="#222">{inner}</text>')
        parts.append(f'<title>{esc(edge["id"])}: {esc(edge.get("evidence", {}).get("quote", ""))}</title></g>')
        return ''.join(parts)

    # ---------- 区室
    def compartment_svg(self):
        out = ['<g id="layer-10-compartments">']
        for comp in self.comps:
            x, y, w, h = self.comp_geom[comp['id']]
            cs = self.pal['compartment'].get(comp['kind'], self.pal['compartment']['custom'])
            out.append(f'<g id="comp-{esc(comp["id"])}" class="compartment kind-{esc(comp["kind"])}">')
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{cs["fill"]}" stroke="{cs["stroke"]}" stroke-width="1.6"/>')
            if comp['kind'] == 'membrane':
                out.append(f'<rect x="{x + 5}" y="{y + 5}" width="{w - 10}" height="{h - 10}" rx="9" fill="none" stroke="{cs["stroke"]}" stroke-width="1" stroke-dasharray="6,4"/>')
            out.append(f'<text x="{x + 12}" y="{y + 20}" font-family="{self.font}" font-size="13" font-weight="700" fill="#444">{esc(comp["label"])}</text>')
            out.append('</g>')
        out.append('</g>')
        return ''.join(out)

    # ---------- 图例
    def legend_svg(self, items):
        x0 = self.margin
        y0 = self.H - self.legend_h
        out = [f'<g id="layer-50-legend">',
               f'<rect x="{x0}" y="{y0}" width="{self.W - 2 * self.margin}" height="{self.legend_h - 10}" rx="10" fill="{self.pal["legend"]["fill"]}" stroke="{self.pal["legend"]["stroke"]}"/>',
               f'<text x="{x0 + 14}" y="{y0 + 22}" font-family="{self.font}" font-size="13" font-weight="700" fill="{self.pal["legend"]["title"]}">图例 Legend</text>']
        cx, cy = x0 + 16, y0 + 46
        for w, kind, payload in items:
            if cx + w > self.W - self.margin - 16:
                cx = x0 + 16
                cy += 30
            if kind == 'rel':
                rel = payload
                color = self.pal['edge']['default']
                mid = self.marker_id(rel, color)
                line_style = GLYPH[rel][0]
                dash = {'solid': 'none', 'dashed': '7,5', 'dotted': '2,4'}[line_style]
                out.append(f'<path d="M{cx},{cy} L{cx + 32},{cy}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}" marker-end="url(#{mid})"/>')
                out.append(f'<text x="{cx + 38}" y="{cy + 4}" font-family="{self.font}" font-size="11" fill="#333">{esc(self.edge_text({"relation": rel}))}</text>')
            elif kind == 'kind':
                kd = payload
                swatch = self.pal['entity_kind'].get(kd, self.pal['entity_kind']['other'])
                out.append(f'<rect x="{cx}" y="{cy - 9}" width="18" height="16" rx="4" fill="{swatch["fill"]}" stroke="{swatch["stroke"]}" stroke-width="1.4"/>')
                out.append(f'<text x="{cx + 24}" y="{cy + 4}" font-family="{self.font}" font-size="11" fill="#333">{esc(KIND_ZH.get(kd, kd))}</text>')
            elif kind == 'scale':
                ch = payload
                spec = self.ir['data_mappings'][ch]
                pal = spec.get('palette') or (self.pal['diverging'] if spec['type'] == 'diverging' else self.pal['sequential'])
                bw = 140
                stops = ''.join(f'<stop offset="{i / (len(pal) - 1):.2f}" stop-color="{c}"/>' for i, c in enumerate(pal))
                gid = f'grad-{ch}'
                self.gradients[ch] = (gid, f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">{stops}</linearGradient>')
                out.append(f'<text x="{cx}" y="{cy - 11}" font-family="{self.font}" font-size="10.5" fill="#444">{esc(spec["legend_title"])}</text>')
                out.append(f'<rect x="{cx}" y="{cy - 5}" width="{bw}" height="11" fill="url(#{gid})" stroke="#bbb"/>')
                dom = spec.get('domain', [])
                if len(dom) == 2:
                    out.append(f'<text x="{cx}" y="{cy + 18}" font-family="{self.font}" font-size="9.5" fill="#666">{dom[0]}</text>')
                    out.append(f'<text x="{cx + bw}" y="{cy + 18}" text-anchor="end" font-family="{self.font}" font-size="9.5" fill="#666">{dom[1]}</text>')
            elif kind == 'cat':
                ch, cat = payload
                spec = self.ir['data_mappings'][ch]
                pal = spec.get('palette') or self.pal['categorical']
                idx = spec['categories'].index(cat)
                out.append(f'<rect x="{cx}" y="{cy - 8}" width="14" height="14" rx="3" fill="{pal[idx % len(pal)]}"/>')
                out.append(f'<text x="{cx + 19}" y="{cy + 3}" font-family="{self.font}" font-size="10.5" fill="#333">{esc(cat)}</text>')
            else:
                ce = payload
                out.append(f'<text x="{cx}" y="{cy + 4}" font-family="{self.font}" font-size="11" fill="#333">{esc(ce["label"])}：{esc(ce["meaning"])}</text>')
            cx += w
        out.append('</g>')
        return ''.join(out)

    # ---------- 渲染
    def render(self):
        self.layout()
        legend_h, legend_items = self.legend_plan()
        svg = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{self.W}" height="{self.H}" viewBox="0 0 {self.W} {self.H}" version="1.1">',
            f'<title>{esc(self.ir.get("title", self.ir.get("case_id", "")))}</title>',
            f'<desc>case_id={esc(self.ir.get("case_id",""))}; schema=bio-pathway-ir/1.0; 由 svg_render.py v2 生成；文字可编辑、图层按 layer-* 命名。</desc>',
            '<metadata id="trace-meta">',
        ]
        for s in self.ir.get('sources', []):
            svg.append(f'<source id="{esc(s["id"])}" type="{esc(s.get("type",""))}" locator="{esc(s.get("locator",""))}" detail="{esc(s.get("locator_detail",""))}"/>')
        svg.append('</metadata>')
        svg.append('__DEFS__')
        svg.append('<g id="layer-00-background"><rect x="0" y="0" width="%d" height="%d" fill="#ffffff"/></g>' % (self.W, self.H))
        svg.append(self.compartment_svg())
        svg.append('<g id="layer-20-edges">')
        for edge in self.ir.get('edges', []):
            svg.append(self.edge_svg(edge))
        svg.append('</g>')
        svg.append('<g id="layer-30-entities">')
        for ent in self.ir.get('entities', []):
            svg.append(node_shape_svg(self.nodes[ent['id']], self.font))
        svg.append('</g>')
        svg.append(self.legend_svg(legend_items))
        svg.append('</svg>')
        text = '\n'.join(svg)
        defs = self.marker_defs() + ''.join(g[1] for g in self.gradients.values())
        return text.replace('__DEFS__', f'<defs>{defs}</defs>'), self.warnings


def main():
    ap = argparse.ArgumentParser(description='Render bio pathway IR to layered editable SVG')
    ap.add_argument('--ir', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--palette', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates', 'palette.json'))
    args = ap.parse_args()
    ir = json.load(open(args.ir, encoding='utf-8'))
    palette = json.load(open(args.palette, encoding='utf-8'))
    r = Renderer(ir, palette)
    svg, warnings = r.render()
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(svg)
    print(json.dumps({'ok': True, 'svg': os.path.abspath(args.out),
                      'entities': len(ir.get('entities', [])), 'edges': len(ir.get('edges', [])),
                      'canvas': [r.W, r.H], 'warnings': warnings}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
