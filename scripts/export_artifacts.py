#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_artifacts.py — SVG 导出 PNG/PDF，自动探测可用工具并如实记录
探测顺序: cairosvg(py) > rsvg-convert > inkscape > convert(ImageMagick)
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

MAGIC = {'png': b'\x89PNG\r\n\x1a\n', 'pdf': b'%PDF-'}


def tool_version(cmd, args=('--version',)):
    try:
        out = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        return 'unknown'


def detect_backend():
    try:
        import cairosvg  # noqa
        return {'name': 'cairosvg', 'version': getattr(cairosvg, '__version__', 'unknown')}
    except Exception:
        pass
    for cmd in ('rsvg-convert', 'inkscape', 'convert'):
        if shutil.which(cmd):
            return {'name': cmd, 'version': tool_version(cmd)}
    return None


def render(backend, svg_path, out_path, fmt, scale):
    name = backend['name']
    if name == 'cairosvg':
        import cairosvg
        if fmt == 'png':
            cairosvg.svg2png(url=svg_path, write_to=out_path, scale=scale)
        else:
            cairosvg.svg2pdf(url=svg_path, write_to=out_path)
        return True, ''
    if name == 'rsvg-convert':
        cmd = ['rsvg-convert']
        if fmt == 'png':
            cmd += ['-f', 'png', '-z', str(scale)]
        else:
            cmd += ['-f', 'pdf']
        cmd += ['-o', out_path, svg_path]
    elif name == 'inkscape':
        cmd = ['inkscape', svg_path, f'--export-type={fmt}', f'--export-filename={out_path}']
    else:  # ImageMagick
        cmd = ['convert', '-background', 'white', '-density', str(96 * scale // 2), svg_path, out_path]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout)[:500]
    return True, ''


def verify(path, fmt):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False, '文件不存在或为空'
    with open(path, 'rb') as f:
        head = f.read(len(MAGIC[fmt]))
    if not head.startswith(MAGIC[fmt]):
        return False, f'文件头与 {fmt.upper()} 格式不符'
    return True, ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--svg', required=True)
    ap.add_argument('--outdir', required=True)
    ap.add_argument('--formats', default='png,pdf')
    ap.add_argument('--scale', type=float, default=2.0)
    ap.add_argument('--report', default='')
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    backend = detect_backend()
    report = {'svg': os.path.abspath(args.svg), 'backend': backend,
              'scale': args.scale, 'artifacts': [], 'status': 'success'}
    if not backend:
        report['status'] = 'failed'
        report['message'] = '未找到任何 SVG 导出后端（cairosvg/rsvg-convert/inkscape/convert），仅保留 SVG 源文件'
    else:
        base = os.path.splitext(os.path.basename(args.svg))[0]
        for fmt in [f.strip() for f in args.formats.split(',') if f.strip()]:
            out_path = os.path.join(args.outdir, f'{base}.{fmt}')
            ok, err = render(backend, args.svg, out_path, fmt, args.scale)
            verified, verr = (False, err)
            size = 0
            if ok:
                verified, verr = verify(out_path, fmt)
                size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
            report['artifacts'].append({
                'format': fmt, 'path': os.path.abspath(out_path),
                'bytes': size, 'render_ok': ok, 'verified': verified,
                'error': verr if not (ok and verified) else '',
            })
            if not (ok and verified):
                report['status'] = 'partial'
    out = args.report or os.path.join(args.outdir, 'export_report.json')
    with open(out, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(0 if report['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
