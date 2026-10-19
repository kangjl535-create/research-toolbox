#!/usr/bin/env python3
"""Prepare color page previews, a source manifest, and reproducible detail crops.

Requires pypdfium2. No OCR, network calls, or scientific interpretation.
Cache keys include source bytes, render settings, renderer version and schema.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import platform
import re
import time
from importlib.metadata import version
from pathlib import Path

SCHEMA = 2
NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}')
RESERVED_RE = re.compile(r'(?i)(con|prn|aux|nul|com\d|lpt\d)(\..*)?')

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def cache_key(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

def positive(value):
    value = int(value)
    if not 36 <= value <= 600:
        raise argparse.ArgumentTypeError('DPI must be between 36 and 600')
    return value

def crop_box(value):
    try:
        box = tuple(float(x) for x in value.split(','))
        if len(box) != 4 or not all(math.isfinite(x) for x in box):
            raise ValueError
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError
        return box
    except ValueError:
        raise argparse.ArgumentTypeError('Use normalized x0,y0,x1,y1 within 0..1')

def check_name(name):
    if not (isinstance(name, str) and NAME_RE.fullmatch(name)) or name.endswith('.') or RESERVED_RE.fullmatch(name):
        raise ValueError(f'Invalid crop name {name!r}: use 1-64 letters, digits, ".", "_" or "-"')
    return name

def crop_spec(value):
    """Parse [NAME[@PAGE]=]x0,y0,x1,y1 into (name, page, box)."""
    name = page = None
    if '=' in value:
        label, value = value.split('=', 1)
        name, at, page_text = label.partition('@')
        try:
            check_name(name)
            if at:
                page = int(page_text)
                if page < 1:
                    raise ValueError(f'Invalid crop page: {page_text}')
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc))
    return name, page, crop_box(value)

def read_stamp(dest):
    try:
        saved = json.loads(dest.with_suffix('.json').read_text(encoding='utf-8'))
        return saved if isinstance(saved, dict) else None
    except (ValueError, OSError):
        return None

def reusable(saved, dest):
    try:
        return (dest.is_file() and saved['sha256'] == digest(dest)
                and all(type(saved[k]) is int and saved[k] > 0 for k in ('width', 'height')))
    except (KeyError, TypeError, OSError):
        return False

def save(im, dest, key=None):
    im.save(dest)
    saved = {'sha256': digest(dest), 'width': im.width, 'height': im.height}
    if key:
        saved['key'] = key
    dest.with_suffix('.json').write_text(json.dumps(saved), encoding='utf-8')
    return saved

def render(page, dpi):
    bitmap = page.render(scale=dpi / 72)
    try:
        return bitmap.to_pil().convert('RGB')
    finally:
        bitmap.close()

def page_scan(page):
    """Embedded raster size and effective dpi when the page holds exactly one image."""
    import pypdfium2.raw as pdfium_c
    images = list(page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))
    scan = {'image_objects': len(images), 'native_px': None, 'effective_dpi': None}
    if len(images) == 1:
        meta = images[0].get_metadata()
        if meta.width > 0 and meta.height > 0:
            scan['native_px'] = [meta.width, meta.height]
            scan['effective_dpi'] = [round(meta.horizontal_dpi, 1), round(meta.vertical_dpi, 1)]
    return scan

def entry(page_number, dest, output, saved, cached, scan, **extra):
    return {'page': page_number, **extra, 'image': dest.relative_to(output).as_posix(),
            'sha256': saved['sha256'], 'width': saved['width'], 'height': saved['height'],
            'cache_hit': cached, **scan}

def render_pages(doc, sha, settings, output):
    cache = output / 'pages' / cache_key(sha, settings)
    cache.mkdir(parents=True, exist_ok=True)
    pages = []
    for i in range(len(doc)):
        page = doc[i]
        try:
            dest = cache / f'p{i+1:04}.png'
            saved = read_stamp(dest)
            cached = saved is not None and reusable(saved, dest)
            if not cached:
                im = render(page, settings['dpi'])
                try:
                    saved = save(im, dest)
                finally:
                    im.close()
            pages.append(entry(i + 1, dest, output, saved, cached, page_scan(page)))
        finally:
            page.close()
    return pages

def render_crops(doc, sha, settings, crops, output):
    folder = output / 'crops'
    plan, names = [], set()
    # Check every name, page and existing file before writing anything.
    for name, page_number, box in crops:
        if not 1 <= page_number <= len(doc):
            raise ValueError(f'Page out of range: {page_number}')
        key = cache_key(sha, settings, page_number, list(box))
        name = check_name(name or f'p{page_number:04}-{key[:12]}')
        if name.lower() in names:
            raise ValueError(f'Duplicate crop name: {name}')
        names.add(name.lower())
        dest = folder / f'{name}.png'
        saved = read_stamp(dest)
        if saved is not None and saved.get('key') not in (None, key):
            raise ValueError(f'Crop name {name!r} already holds a different crop in {folder}; choose another name')
        cached = saved is not None and saved.get('key') == key and reusable(saved, dest)
        plan.append((name, page_number, box, key, dest, saved if cached else None))
    folder.mkdir(parents=True, exist_ok=True)
    by_page, results = {}, {}
    for item in plan:
        by_page.setdefault(item[1], []).append(item)
    for page_number, items in by_page.items():
        page = doc[page_number - 1]
        im = None
        try:
            scan = page_scan(page)
            for name, _, box, key, dest, saved in items:
                cached = saved is not None
                if not cached:
                    if im is None:
                        im = render(page, settings['dpi'])
                    x0, y0, x1, y1 = box
                    part = im.crop((int(x0*im.width), int(y0*im.height),
                                    math.ceil(x1*im.width), math.ceil(y1*im.height)))
                    try:
                        saved = save(part, dest, key)
                    finally:
                        part.close()
                results[name] = entry(page_number, dest, output, saved, cached, scan,
                                      name=name, crop=list(box))
        finally:
            if im is not None:
                im.close()
            page.close()
    return [results[item[0]] for item in plan]

def prepare(sources, output, dpi=144, page_number=None, box=None, crops=None):
    """Render overview pages, or the given crops as (name or None, page or None, box)."""
    import pypdfium2 as pdfium
    crops = list(crops or [])
    if box is not None:
        crops.append((None, None, box))
    if page_number is not None and not crops:
        raise ValueError('--page requires at least one --crop')
    if crops and len(sources) != 1:
        raise ValueError('Detail mode requires exactly one source')
    crops = [(name, page or page_number, b) for name, page, b in crops]
    if any(page is None for _, page, _ in crops):
        raise ValueError('Each crop needs --page or NAME@PAGE')
    sources = [Path(p).resolve(strict=True) for p in sources]
    output = Path(output).resolve()
    if any(p.suffix.lower() != '.pdf' for p in sources):
        raise ValueError('This helper accepts PDF files; inspect image inputs directly')
    output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    settings = {'schema': SCHEMA, 'renderer': version('pypdfium2'), 'dpi': dpi,
                'color': 'RGB', 'format': 'PNG'}
    records = []
    for order, source in enumerate(sources, 1):
        t = time.perf_counter()
        sha = digest(source)
        doc = pdfium.PdfDocument(str(source))
        try:
            count = len(doc)
            if crops:
                pages = render_crops(doc, sha, settings, crops, output)
            else:
                pages = render_pages(doc, sha, settings, output)
        finally:
            doc.close()
        records.append({'source_id': f'S{order:03}', 'source': str(source),
                        'filename': source.name, 'sha256': sha, 'page_count': count,
                        'pages': pages, 'seconds': time.perf_counter()-t})
    return {'schema': SCHEMA, 'settings': settings, 'python': platform.python_version(),
            'sources': records, 'seconds': time.perf_counter()-started,
            'notice': 'Rendered pages are prepared, NOT visually inspected or transcribed.'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--dpi', type=positive, default=144)
    parser.add_argument('--page', type=int, help='Default page for --crop')
    parser.add_argument('--crop', type=crop_spec, action='append', metavar='[NAME[@PAGE]=]X0,Y0,X1,Y1',
                        help='Detail crop as page fractions; repeat for several crops; writes crops/NAME.png')
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args.source, args.output_dir, args.dpi, args.page, crops=args.crop)
        manifest = args.manifest or args.output_dir / 'manifest.json'
        if manifest.resolve() in [p.resolve() for p in args.source]:
            raise ValueError('Manifest must not overwrite a source')
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'manifest': str(manifest), 'seconds': result['seconds'],
                          'pages': sum(len(s['pages']) for s in result['sources']),
                          'cache_hits': sum(p['cache_hit'] for s in result['sources'] for p in s['pages'])}))
        return 0
    except (OSError, ValueError, ImportError) as exc:
        parser.error(str(exc))

if __name__ == '__main__':
    raise SystemExit(main())
