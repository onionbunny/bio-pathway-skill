#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
inspect_svg.py — 导出既有 SVG 的结构清单，用于“源保留编辑”任务
输出: 图层、节点/边/区室组、文本、标记、渐变与画布尺寸（JSON）
"""
import argparse
import json
import xml.etree.ElementTree as ET

SVG_NS = 'http://www.w3.org/2000/svg'


def text_of(el):
    return ''.join(el.itertext()).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('svg')
    args = ap.parse_args()
    tree = ET.parse(args.svg)
    root = tree.getroot()
    data = {
        'width': root.get('width'), 'height': root.get('height'),
        'viewBox': root.get('viewBox'),
        'layers': [], 'nodes': [], 'edges': [], 'compartments': [],
        'texts': [], 'markers': [], 'gradients': [],
    }
    for g in root.iter(f'{{{SVG_NS}}}g'):
        gid = g.get('id') or ''
        if gid.startswith('layer-'):
            data['layers'].append(gid)
        elif gid.startswith('node-'):
            t = next((x for x in g.iter(f'{{{SVG_NS}}}text')), None)
            data['nodes'].append({'id': gid, 'label': text_of(t) if t is not None else ''})
        elif gid.startswith('edge-'):
            data['edges'].append(gid)
        elif gid.startswith('comp-'):
            data['compartments'].append(gid)
    for t in root.iter(f'{{{SVG_NS}}}text'):
        data['texts'].append({'id': t.get('id'), 'text': text_of(t)})
    for m in root.iter(f'{{{SVG_NS}}}marker'):
        data['markers'].append(m.get('id'))
    for gr in root.iter(f'{{{SVG_NS}}}linearGradient'):
        data['gradients'].append(gr.get('id'))
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
