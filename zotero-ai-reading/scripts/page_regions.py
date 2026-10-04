"""Page words in reading order, quote placement on scans, and figure/equation/table regions (validated in test T5).

Words come either from Windows OCR (`ocr_windows.ps1` on 300-dpi renders; scanned PDFs) or from the PDF text
layer (text PDFs). On scans, quotes are matched like text_locator.py and snapped to the OCR wording.
Figures: the MinerU figure crops (all panels of the figure) are template-matched on the page image, on the
caption's page first. Numbered equations: the ink between the nearest body-text lines, located from the equation
number or, when OCR missed it, from the Markdown text around the equation. Tables: from the caption to the text
after the table. Labels are as printed: 7, "2.5", "A1", "12a"; Roman numerals for tables.
Rectangles are PyMuPDF page points (top-left origin); text_locator.to_zotero converts them for Zotero.
"""
import difflib, json, pathlib, re, urllib.parse
import numpy as np, pymupdf, PIL.Image
from skimage.feature import match_template
from skimage.transform import rescale

from text_locator import norm_char, norm_text, clean_needle, compact, to_zotero, sort_index, WATERMARK

OCR_DPI = 300
S = 72 / OCR_DPI  # OCR pixel -> page point
LABEL = re.compile(r"[A-Z]?\d{1,3}(?:\.\d{1,3})?[a-z]?'?|[IVXLC]{1,6}")  # 7, 2.5, A1, 12a, 55', IV
NUM_TOKEN = r"[(�ð][A-Z]?\d{1,3}(?:\.\d{1,3})?[a-z]?'?[)�Þ]"  # any printed equation number, "(4)" also read as �4� or ð4Þ
MATH_WORDS = {"cos", "sin", "tan", "cot", "sec", "csc", "exp", "log", "erf", "erfc", "sinh", "cosh", "tanh", "coth",
              "sech", "csch", "max", "min", "lim", "sup", "inf", "arg", "det", "div", "grad", "curl"}
GAP_PT = 13  # a blank band this tall ends an equation frame (inside the 90 equations of the rc tests: at most 11.5 pt)


def is_roman(n):
    return bool(re.fullmatch(r"[IVXLC]+", str(n)))


def num_re(n):
    """A printed label in the PDF text: OCR reads 1 as I or l and 0 as O; a Roman numeral is not cut short."""
    if is_roman(n):
        return f"{n}(?![IVXLC])"
    return "".join({"1": "[1Il]", "0": "[0Oo]"}.get(c, re.escape(c)) for c in str(n))


def md_label(n):
    """A label in the Markdown, not followed by more of a longer label (Fig. 1 is not Fig. 12; Table V not VI)."""
    return re.escape(str(n)) + ("(?![IVXLC])" if is_roman(n) else r"(?!\d)")


def words_of(t, k, tail):
    t = re.sub(r"\$[^$]*\$", " ", t)
    w = [x for x in re.sub(r"\s+", " ", t).strip().split(" ") if x]
    return " ".join(w[-k:] if tail else w[:k])


def render_for_ocr(pdf_path, out_dir):
    """300-dpi grayscale page renders p<N>.png for ocr_windows.ps1."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(pymupdf.open(pdf_path)):
        p.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY).save(out_dir / f"p{i + 1}.png")
    return out_dir


class Pages:
    def __init__(self, pdf_path, md_path, ocr_json=None):
        self.doc = pymupdf.open(pdf_path)
        self.md_path = pathlib.Path(md_path)
        self.md = self.md_path.read_text(encoding="utf-8")
        self.ocr = {p["page"] - 1: p for p in json.load(open(ocr_json, encoding="utf-8"))} if ocr_json else None
        prose = re.sub(r"\$\$.*?\$\$|<table>.*?</table>|!\[[^\]]*\]\([^)]*\)|\$[^$]*\$", " ", self.md, flags=re.S)
        self.prose_words = set(re.findall(r"[a-z]{3,}", prose.lower())) - MATH_WORDS
        self._stream, self._ink, self._gray, self._onecol = {}, {}, {}, {}
        self._scale = None  # MinerU crop pixels per page point: one value per document, found with the first figure

    # ---------- words per line ----------
    def raw_lines(self, pi):
        if self.ocr is not None:
            return [[(w["text"], pymupdf.Rect(w["x"] * S, w["y"] * S, (w["x"] + w["w"]) * S, (w["y"] + w["h"]) * S))
                     for w in l["words"]] for l in self.ocr[pi]["lines"] if l["words"]]
        lines = []
        raw = self.doc[pi].get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
        for b in raw["blocks"]:
            for l in b.get("lines", []):
                chars = [(ch["c"], pymupdf.Rect(ch["bbox"])) for s in l["spans"] for ch in s["chars"]]
                if not chars or l.get("dir", (1, 0))[1] != 0 or WATERMARK.search("".join(c for c, _ in chars)):
                    continue
                words, cur, box = [], "", None
                for c, bb in chars + [(" ", None)]:
                    if c.isspace():
                        if cur:
                            words.append((cur, box))
                        cur, box = "", None
                    else:
                        cur += c
                        box = pymupdf.Rect(bb) if box is None else box | bb
                if words:
                    lines.append(words)
        return lines

    def ordered_lines(self, pi):
        W = self.doc[pi].rect.width
        lines = []
        for ws in self.raw_lines(pi):
            cur = [ws[0]]
            for a, b in zip(ws, ws[1:]):  # split a line that jumps across the column gap
                if b[1].x0 - a[1].x1 > 20:
                    lines.append(cur); cur = []
                cur.append(b)
            lines.append(cur)
        boxed = []
        for ws in lines:
            r = pymupdf.Rect(ws[0][1])
            for _, b in ws[1:]:
                r |= b
            boxed.append((r, ws))
        full = [b for b in boxed if b[0].x0 < 0.45 * W and b[0].x1 > 0.55 * W]
        cuts = sorted(b[0].y0 for b in full)
        order, used = [], set()
        for lo, hi in zip([-1] + cuts, cuts + [1e9]):  # full-width lines cut the page; left column, then right
            band = [b for i, b in enumerate(boxed) if lo < b[0].y0 <= hi and i not in used]
            used |= {i for i, b in enumerate(boxed) if lo < b[0].y0 <= hi}
            fw = [b for b in band if any(b is f for f in full)]
            rest = [b for b in band if not any(b is f for f in full)]
            order += sorted(fw, key=lambda b: b[0].y0)
            order += sorted([b for b in rest if b[0].x0 + b[0].x1 < W], key=lambda b: b[0].y0)
            order += sorted([b for b in rest if b[0].x0 + b[0].x1 >= W], key=lambda b: b[0].y0)
        return order

    def stream(self, pi):
        """(text, char boxes, line index per char, glyph offset per char, lines); char height = its line's extent."""
        if pi in self._stream:
            return self._stream[pi]
        lines = self.ordered_lines(pi)
        ch, bx, li_, off = [], [], [], []
        g = 0
        for li, (lr, ws) in enumerate(lines):
            if ch:
                ch.append(" "); bx.append(None); li_.append(li); off.append(g)
            for wi, (t, r) in enumerate(ws):
                if wi:
                    ch.append(" "); bx.append(None); li_.append(li); off.append(g)
                nt = "".join(norm_char(c) for c in t).replace(" ", "")
                for k, c in enumerate(nt):
                    ch.append(c); li_.append(li); off.append(g); g += 1
                    bx.append(pymupdf.Rect(r.x0 + r.width * k / len(nt), lr.y0, r.x0 + r.width * (k + 1) / len(nt), lr.y1))
        self._stream[pi] = ("".join(ch), bx, li_, off, lines)
        return self._stream[pi]

    # ---------- quotes on scans ----------
    def span(self, pi, s, e, mode):
        text, bx, lid, off, _ = self.stream(pi)
        rects, rl = [], []
        for b, l in zip(bx[s:e], lid[s:e]):
            if b is None:
                continue
            if rl and rl[-1] == l:
                rects[-1] |= b
            else:
                rects.append(pymupdf.Rect(b)); rl.append(l)
        rects = [r + (-0.8, 0, 0.8, 0) for r in rects]  # OCR word boxes are tight; avoid clipping the end glyphs
        return {"page": pi, "rects": rects, "lines": rl, "glyph_offset": off[s], "mode": mode, "text": text[s:e]}

    def locate(self, needle, pages=None):
        n = norm_text(clean_needle(needle))
        pages = range(self.doc.page_count) if pages is None else pages
        hits = []
        for strategy in ("exact", "compact"):
            for pi in pages:
                text = self.stream(pi)[0]
                if strategy == "exact":
                    hits += [(pi, m.start(), m.end(), strategy) for m in re.finditer(re.escape(n), text)]
                else:
                    ct, cmap = compact(text)
                    cn, _ = compact(n)
                    if cn:
                        hits += [(pi, cmap[m.start()], cmap[m.end() - 1] + 1, strategy) for m in re.finditer(re.escape(cn), ct)]
            if hits:
                break
        if len(hits) != 1:
            return None, "not found" if not hits else f"ambiguous ({len(hits)})"
        return self.span(*hits[0]), None

    def snap(self, quote, min_ratio=0.85):
        q = norm_text(clean_needle(quote))
        best = (0, None, None, None)
        for pi in range(self.doc.page_count):
            text = self.stream(pi)[0]
            sm = difflib.SequenceMatcher(None, text, q, autojunk=False)
            for blk in sm.get_matching_blocks():
                if blk.size < 6:
                    continue
                s0 = max(0, blk.a - blk.b)
                for ln in (len(q), int(len(q) * 0.95), int(len(q) * 1.05), int(len(q) * 0.9), int(len(q) * 1.1)):
                    for d in (-2, -1, 0, 1, 2):
                        a = max(0, s0 + d)
                        r = difflib.SequenceMatcher(None, text[a:a + ln], q, autojunk=False).ratio()
                        if r > best[0]:
                            best = (r, pi, a, a + ln)
        r, pi, a, b = best
        if r < min_ratio:
            return None, r
        text = self.stream(pi)[0]
        while a > 0 and text[a - 1] != " ":  # widen to whole words
            a -= 1
        while b < len(text) and text[b - 1] != " " and text[b] != " ":
            b += 1
        ratio = lambda a, b: difflib.SequenceMatcher(None, text[a:b].strip(), q, autojunk=False).ratio()
        while True:  # drop a stray first or last word (e.g. an equation number) while that does not lower similarity
            a2, b2 = text.find(" ", a, b) + 1, text.rfind(" ", a, b)
            opts = [(ratio(x, y), x, y) for x, y in ((a2, b), (a, b2)) if 0 < x < y]
            best2 = max(opts, default=None)
            if not best2 or best2[0] < ratio(a, b):
                break
            _, a, b = best2
        r = ratio(a, b)
        return self.span(pi, a, b, f"snapped {r:.3f}"), r

    def place_quote(self, quote, min_ratio=0.85):
        loc, why = self.locate(quote)
        if loc:
            return loc, "direct"
        loc, r = self.snap(quote, min_ratio)
        return loc, (f"snapped {r:.3f}" if loc else f"unplaced ({why}; best similarity {r:.2f})")

    # ---------- geometry ----------
    def one_column(self, pi):
        """True when most body-text lines of the page cross its centre (a single-column layout)."""
        if pi not in self._onecol:
            W = self.doc[pi].rect.width
            wide = [lr for lr, ws in self.stream(pi)[4] if lr.width > 0.3 * W and self.is_prose(ws)]
            self._onecol[pi] = bool(wide) and sum(lr.x0 < W / 2 - 10 and lr.x1 > W / 2 + 10 for lr in wide) >= len(wide) / 2
        return self._onecol[pi]

    def same_col(self, pi, a, b):
        W = self.doc[pi].rect.width
        spans = lambda r: r.x0 < W / 2 - 10 and r.x1 > W / 2 + 10  # a full-width line (abstract, wide caption)
        return self.one_column(pi) or spans(a) or spans(b) or (a.x0 + a.x1 < W) == (b.x0 + b.x1 < W)

    def split_y(self, pi, c0, c1, ya, yb):
        """A y between ya < yb where no ink crosses the column [c0, c1], nearest their middle (else the middle)."""
        m = self.ink(pi)
        r0, r1 = int(ya / S), int(yb / S)
        rows = m[r0:r1, max(0, int(c0 / S)):int(c1 / S)].any(1)
        blank = np.where(~rows)[0]
        if not len(blank):
            return (ya + yb) / 2
        return (r0 + blank[np.argmin(abs(blank - (r1 - r0) / 2))]) * S

    def gap_bounds(self, pi, c0, c1, ya, yb, y):
        """Shrink [ya, yb] to the ink around y: stop at the first blank band of GAP_PT or more above and below y in the
        column [c0, c1] (a table or header above an equation is not part of it)."""
        r0 = int(ya / S)
        rows = self.ink(pi)[r0:int(yb / S), max(0, int(c0 / S)):int(c1 / S)].any(1)
        if not len(rows):
            return ya, yb
        g, i = int(GAP_PT / S), min(max(int(y / S) - r0, 0), len(rows) - 1)
        run = 0
        for k in range(i, -1, -1):
            run = 0 if rows[k] else run + 1
            if run >= g:
                ya = (r0 + k) * S
                break
        run = 0
        for k in range(i, len(rows)):
            run = 0 if rows[k] else run + 1
            if run >= g:
                yb = (r0 + k + 1) * S
                break
        return ya, yb

    def offset_at(self, pi, rect):
        text, bx, lid, off, lines = self.stream(pi)
        for li, (lr, _) in enumerate(lines):
            if self.same_col(pi, lr, rect) and lr.y0 >= rect.y0 - 2:
                return off[lid.index(li)]
        return off[-1] if off else 0

    def ink(self, pi):
        if pi not in self._ink:
            pix = self.doc[pi].get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
            m = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width) < 150
            m[:, int((self.doc[pi].rect.width - 25) / S):] = False  # drop a vertical download stamp in the right margin
            self._ink[pi] = m
        return self._ink[pi]

    def tighten(self, pi, r, pad=2.0):
        m = self.ink(pi)
        y0, y1, x0, x1 = (int(v / S) for v in (r.y0, r.y1, r.x0, r.x1))
        sub = m[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        rows, cols = np.where(sub.any(1))[0], np.where(sub.any(0))[0]
        if not len(rows):
            return None
        return pymupdf.Rect((x0 + cols[0]) * S - pad, (y0 + rows[0]) * S - pad, (x0 + cols[-1] + 1) * S + pad,
                            (y0 + rows[-1] + 1) * S + pad) & self.doc[pi].rect

    def column(self, pi, r, robust=True):
        """Edges of the column holding r. robust: start from the most common line start and end (4-pt bins) and
        widen only by lines within 15 pt of them, so a centred stamp or a line spanning both columns does not
        widen the column; a protruding '=' or equation number still counts. robust=False: outermost lines.
        Running headers and footers (top 10 %, bottom 8 % of the page) are left out."""
        W, H = self.doc[pi].rect.width, self.doc[pi].rect.height
        xs = [lr for lr, _ in self.stream(pi)[4]
              if lr.width > 0.3 * W / 2 and lr.y0 > 0.1 * H and lr.y1 < 0.92 * H and self.same_col(pi, lr, r)]
        if not xs:
            return 30.0, W - 30.0
        x0s, x1s = [l.x0 for l in xs], [l.x1 for l in xs]
        if not robust:
            return min(x0s) - 4, max(x1s) + 4

        def mode(vals, prefer):
            bins = {}
            for v in vals:
                bins.setdefault(round(v / 4), []).append(v)
            top = max(len(b) for b in bins.values())
            return prefer(prefer(b) for b in bins.values() if len(b) == top)

        m0, m1 = mode(x0s, min), mode(x1s, max)
        return min(v for v in x0s if v >= m0 - 15) - 4, max(v for v in x1s if v <= m1 + 15) + 4

    def find_line(self, pattern):
        for pi in range(self.doc.page_count):
            for lr, ws in self.stream(pi)[4]:
                if re.match(pattern, " ".join(t for t, _ in ws)):
                    return pi, lr
        return None, None

    def caption_line(self, word, n):
        """The caption line "Fig. 7." / "FIG. 7 —" / "TABLE IV." / "Table 1" (page, rect), not a sentence citing it. A
        letter-spaced caption whose "FIG." the text layer splits from the rest is joined with the pieces to its right.
        A line inside a prose paragraph ("... in\\nTable 1 are within ...") is returned only when no other line matches."""
        head = rf"^(?:{word})\.?,?\s*{num_re(n)}"
        fallback = None
        for pattern in (head + r"\s*[.:—–-]", head + r"\b" if not is_roman(n) else head):
            for pi in range(self.doc.page_count):
                lines = self.stream(pi)[4]
                for lr, ws in lines:
                    text, rect = " ".join(t for t, _ in ws), pymupdf.Rect(lr)
                    if any(abs(o.y0 - lr.y0) < 2.5 and lr.x0 - 10 < o.x1 <= lr.x0 for o, _ in lines):
                        continue  # not at the start of its line: "... shown in Fig. 7. From this ..."
                    if re.match(rf"^(?:{word})\.?,?$", text):
                        for o, ows in sorted((x for x in lines if abs(x[0].y0 - lr.y0) < 2.5 and x[0].x0 > lr.x1), key=lambda x: x[0].x0):
                            if o.x0 - rect.x1 > 60:
                                break
                            text, rect = text + " " + " ".join(t for t, _ in ows), rect | o
                    m = re.match(pattern, text)
                    if m and not self.in_paragraph(pi, rect, text[m.end():]):
                        return pi, rect
                    fallback = fallback or (m and (pi, rect))
        return fallback or (None, None)

    def in_paragraph(self, pi, rect, rest):
        """A line of body text, not a caption: the words after the label go on in lower case ("Table 1 are within",
        "Fig. 7 shows"), or a prose line sits directly above it in its column with no gap."""
        if re.match(r"[\s,]*[a-z]{2,}\b", rest):
            return True
        h = rect.height / 2
        return any(o.y0 < rect.y0 - h and o.y1 > rect.y0 - h and self.is_prose(ws)
                   and min(o.x1, rect.x1) - max(o.x0, rect.x0) > 0.5 * min(o.width, rect.width)
                   for o, ws in self.stream(pi)[4])

    def is_prose(self, ws):
        w = [x for t, _ in ws for x in re.findall(r"[a-z]{3,}", t.lower())]  # "non-negative" -> non, negative
        return bool(w) and sum(x in self.prose_words for x in w) / len(w) >= 0.6

    def region(self, pi, rect, info):
        page = self.doc[pi]
        return {"page": pi, "rect": rect, "zotero_rects": to_zotero(page, [rect]),
                "sortIndex": sort_index(page, self.offset_at(pi, rect), rect), **info}

    # ---------- figures ----------
    def gray(self, pi, dpi=60):
        if pi not in self._gray:
            pix = self.doc[pi].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            self._gray[pi] = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).astype(float) / 255
        return self._gray[pi]

    def figure_images(self, n):
        """MinerU's images of figure n, all panels: the images just before its caption line(s), skipping panel labels
        such as "(a) ..." (several "Fig. 5(a)", "Fig. 5(b)" captions add up); else the images just after the caption
        (a caption above its figure). Returns (paths in Markdown order, Markdown offset of the first, whether each
        panel has its own caption)."""
        lines = self.md.split("\n")
        starts = np.cumsum([0] + [len(l) + 1 for l in lines])
        cap = re.compile(rf"^\s*(?:Fig\.?|Figure)\s*{md_label(n)}", re.I)
        img = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

        def walk(i, step):
            found, j = [], i + step
            while 0 <= j < len(lines):
                s = lines[j].strip()
                m = img.search(s)
                if m:
                    found.append((m.group(1), starts[j]))
                elif s and not (s.startswith("(") or re.match(r"[a-z]\)", s) or len(s) <= 3):
                    break
                j += step
            return found[::-1] if step < 0 else found

        caps = [i for i, l in enumerate(lines) if cap.match(l)]
        panel = re.compile(rf"^\s*(?:Fig\.?|Figure)\s*{md_label(n)}\s*\(?[a-z]\)?(?![a-z])", re.I)  # "Fig. 5(a) ...", "Fig. 5b ..."
        groups = [(i, walk(i, -1)) for i in caps]
        first = next(((i, w) for i, w in groups if w), None)
        per_panel = bool(first and panel.match(lines[first[0]]))
        if per_panel:  # one caption per panel: all panels' images
            found = [x for i, w in groups if panel.match(lines[i]) for x in w]
        elif first:  # the first captioned figure; a later "Fig. n" may belong to another article in the same PDF
            found = first[1]
        else:
            found = next((w for w in (walk(i, 1) for i in caps) if w), [])
        paths, seen = [], set()
        for p, off in found:
            path = self.md_path.parent / urllib.parse.unquote(p)
            if path not in seen and path.exists():
                seen.add(path)
                paths.append((path, off))
        return [p for p, _ in paths], (paths[0][1] if paths else 0), per_panel

    def match(self, tpl, pages, scales, dpi=60, stop=None):
        """Best template match (score, page, scale, (x, y, w, h) in dpi pixels) over pages and scales; stop scanning
        further pages once a match reaches `stop`."""
        best = (-1.0, None, None, None)
        for pi in pages:
            pg = self.gray(pi, dpi)
            for s in scales:
                t = rescale(tpl, dpi / 72 / s, anti_aliasing=True)
                if t.shape[0] >= pg.shape[0] or t.shape[1] >= pg.shape[1] or min(t.shape) < 8:
                    continue
                res = match_template(pg, t)
                iy, ix = np.unravel_index(res.argmax(), res.shape)
                if res[iy, ix] > best[0]:
                    best = (float(res[iy, ix]), pi, float(s), (ix, iy, t.shape[1], t.shape[0]))
            if stop and best[0] >= stop:
                break
        return best

    def figure(self, n, dpi=60):
        paths, md_off, per_panel = self.figure_images(n)
        if not paths:
            return None
        tpls = [np.asarray(PIL.Image.open(p).convert("L"), float) / 255 for p in paths]
        anchor = max(range(len(tpls)), key=lambda i: tpls[i].size)  # the largest panel matches most reliably
        # the caption line ("Fig. 7." / "FIG. 7 —"), not a sentence such as "Figure 7 shows ..." on another page
        cap_pi, cap = self.caption_line("Fig|FIG|Figure|FIGURE", n)
        N = self.doc.page_count
        guess = md_off / max(1, len(self.md)) * N  # other pages: nearest the figure's place in the Markdown first
        rest = sorted((p for p in range(N) if p != cap_pi), key=lambda p: abs(p + 0.5 - guess))
        ranges = ([np.arange(self._scale - 0.08, self._scale + 0.081, 0.02)] if self._scale else []) + [np.arange(1.2, 4.4, 0.04)]
        best = (-1.0, None, None, None)
        for scales in ranges:  # the scale found for an earlier figure of this paper first; MinerU uses one per document
            for pages, stop in (([cap_pi] if cap_pi is not None else []), None), (rest, 0.85):
                best = max(best, self.match(tpls[anchor], pages, scales, dpi, stop), key=lambda b: b[0])
                if best[0] >= 0.6:  # found on the caption's page; otherwise search the other pages
                    break
            if best[0] >= 0.6:
                break
        if best[1] is None:
            return None
        best = max(best, self.match(tpls[anchor], [best[1]], np.arange(best[2] - 0.04, best[2] + 0.041, 0.005), dpi), key=lambda b: b[0])
        score, pi, s, _ = best
        if score < 0.6:
            return None
        self._scale = s
        f = 72 / dpi
        box = lambda b: pymupdf.Rect(b[3][0] * f, b[3][1] * f, (b[3][0] + b[3][2]) * f, (b[3][1] + b[3][3]) * f)
        raw, panels = box(best), 1
        for i, t in enumerate(tpls):  # the other panels, on the same page and at the same scale
            if i != anchor:
                b = self.match(t, [pi], np.arange(s - 0.01, s + 0.011, 0.005), dpi)
                # separately captioned panels in the other column have body text between them: leave them out
                if b[0] >= 0.7 and (not per_panel or self.same_col(pi, box(b), box(best))):
                    raw, panels = raw | box(b), panels + 1
        rect = self.tighten(pi, raw + (-3, -3, 3, 3)) or raw
        for lr, ws in self.stream(pi)[4]:  # never cut through a text line at the top or bottom edge
            overlap = min(lr.x1, rect.x1) - max(lr.x0, rect.x0)
            if overlap < 0.3 * lr.width or not self.is_prose(ws):
                continue
            if lr.y0 < rect.y0 < lr.y1:
                rect.y0 = lr.y1 + 0.5
            elif lr.y0 < rect.y1 < lr.y1:
                rect.y1 = lr.y0 - 0.5
        info = {"match_score": round(score, 3)}
        if len(tpls) > 1:
            info["panels"] = f"{panels} of {len(tpls)}"
        if cap is not None and cap_pi == pi:
            info["caption_gap_pt"] = round(cap.y0 - rect.y1, 1)
        return self.region(pi, rect, info)

    # ---------- numbered equations ----------
    def equation(self, n):
        b = next((b for b in re.finditer(r"\$\$(.*?)\$\$", self.md, re.S)  # MinerU writes \tag{3}, \tag {3}. or \tag{3),}
                  if re.search(rf"\\tag\s*\{{\s*{re.escape(str(n))}\s*\)?[.,]*\s*\}}", b.group(1))), None)
        anchors = {"before": None, "after": None}  # no \tag (MinerU dropped it): the printed number alone must decide
        if b:
            before = ([p for p in self.md[:b.start()].split("\n\n") if p.strip()] or [""])[-1]
            after = ([p for p in self.md[b.end():].split("\n\n") if p.strip()] or [""])[0]
            for side, para, tail in (("before", before, True), ("after", after, False)):
                loc, _ = self.locate(words_of(para, 6, tail))
                if not loc:  # missing or ambiguous: more words tell repeated phrases apart
                    loc, _ = self.locate(words_of(para, 12, tail))
                if not loc:
                    loc, _ = self.snap(words_of(para, 12, tail), 0.8)
                anchors[side] = loc
        cands = []
        for pi in range(self.doc.page_count):
            for lr, ws in self.stream(pi)[4]:
                for t, r in ws:
                    if re.fullmatch(rf"[(�ð]{num_re(n)}[)�Þ]", t):  # text layers may give "(4)" as �4� or ð4Þ
                        c0, c1 = self.column(pi, r)
                        if r.x1 > c1 - 25 and (len(ws) <= 2 or lr.x0 > c0 + 30):
                            cands.append((pi, r))
        ab, aa = anchors["before"], anchors["after"]
        line = lambda loc, i: self.stream(loc["page"])[4][loc["lines"][i]][0]
        if len(cands) == 1:
            pi, ref = cands[0]
            ref_y = (ref.y0 + ref.y1) / 2
        elif ab and aa and ab["page"] == aa["page"] and self.same_col(ab["page"], line(ab, -1), line(aa, 0)):
            pi, ref = ab["page"], line(ab, -1)
            ref_y = (line(ab, -1).y1 + line(aa, 0).y0) / 2
        else:
            return None
        c0, c1 = self.column(pi, ref)
        if len(cands) == 1:
            c1 = max(c1, ref.x1 + 3)  # keep the equation number inside the frame
        anchor_lines = {li for a in (ab, aa) if a and a["page"] == pi for li in a["lines"]}
        # a line beside an equation number belongs to an equation, even when it reads as prose: the numerator and
        # denominator of "tan δ = Loss Modulus / Storage Modulus (2)". Other numbers count only standing alone at the
        # right of the column, not "... of (41) and (42)" ending a text line.
        eq_nums = [r for lr, ws in self.stream(pi)[4] if len(ws) <= 2 for t, r in ws
                   if re.fullmatch(NUM_TOKEN, t) and self.same_col(pi, r, ref) and r.x1 > c1 - 25] + ([ref] if len(cands) == 1 else [])
        beside = lambda lr: any(lr.x1 < r.x0 and min(lr.y1, r.y1) - max(lr.y0, r.y0) > 0.25 * min(lr.height, r.height) for r in eq_nums)
        body = [lr for li, (lr, ws) in enumerate(self.stream(pi)[4])
                if self.same_col(pi, lr, ref) and not beside(lr) and (self.is_prose(ws) or li in anchor_lines)]
        top = max([lr.y1 for lr in body if lr.y1 <= ref_y], default=40.0)
        bot = min([lr.y0 for lr in body if lr.y0 >= ref_y], default=self.doc[pi].rect.height - 40)
        H, lines = self.doc[pi].rect.height, self.stream(pi)[4]
        first = min((lr.y0 for lr, _ in lines), default=0)
        for lr, ws in lines:  # a running header: the page's first line, in the top margin, words or a page number
            words = [w for w in re.findall(r"[A-Za-z]{3,}", " ".join(t for t, _ in ws)) if w.lower() not in MATH_WORDS]
            if (lr.y0 < first + 3 and lr.y1 < 0.12 * H and lr.y1 < ref_y and top < lr.y1
                    and (len(words) >= 2 or re.fullmatch(r"\d{1,4}", " ".join(t for t, _ in ws)))
                    and min((o.y0 for o, _ in lines if o.y0 > lr.y1), default=H) - lr.y1 >= 8):
                top = lr.y1
        if len(cands) == 1:  # stacked equations with no text between: split at the gap next to the neighbouring numbers
            yc = lambda r: (r.y0 + r.y1) / 2
            nums = [r for lr, ws in lines for t, r in ws
                    if re.fullmatch(NUM_TOKEN, t) and r != ref
                    and self.same_col(pi, r, ref) and r.x1 > c1 - 25 and top < yc(r) < bot]
            above, below = [r for r in nums if yc(r) < ref_y], [r for r in nums if yc(r) > ref_y]
            if above:
                top = max(top, self.split_y(pi, c0, c1, max(map(yc, above)), ref_y))
            if below:
                bot = min(bot, self.split_y(pi, c0, c1, ref_y, min(map(yc, below))))
            top, bot = self.gap_bounds(pi, c0, c1, top, bot, ref_y)
        for lr, ws in lines:  # a page number: digits only, in the bottom margin, the last line of its column
            if (re.fullmatch(r"\d{1,4}", " ".join(t for t, _ in ws)) and lr.y0 > 0.88 * H and ref_y < lr.y0 < bot
                    and not any(o.y0 > lr.y1 and self.same_col(pi, o, lr) for o, _ in lines)):
                bot = lr.y0
        rect = self.tighten(pi, pymupdf.Rect(c0, top + 0.5, c1, bot - 0.5))
        if not rect or rect.height > 300:  # a band this tall means the body-text lines were not found
            return None
        return self.region(pi, rect, {"number_found": len(cands) == 1})

    # ---------- tables ----------
    def table(self, n):
        tm = re.search(rf"\n((?:Table|TABLE)\s*{md_label(n)}[.:]?[^\n]*)\n(?:[^\n]*\n)??\n?<table>.*?</table>", self.md, re.S)
        if not tm:
            return None
        pi, cap = self.caption_line("Table|TABLE", n)
        if cap is None:
            return None
        nxt = next((p for p in self.md[tm.end():].split("\n\n") if p.strip() and not p.strip().startswith(("$", "\\", "<"))), "")
        loc, _ = self.locate(words_of(nxt, 6, False)) if nxt else (None, None)
        c0, c1 = self.column(pi, cap, robust=False)  # a table may span both columns, and is at least as wide as its caption
        c0, c1 = min(c0, cap.x0 - 4), max(c1, cap.x1 + 4)
        nl = self.stream(pi)[4][loc["lines"][0]][0] if loc and loc["page"] == pi else None
        # the text after the table, unless it goes on elsewhere (the top of the next column, above the caption)
        bot = nl.y0 if nl and nl.y0 > cap.y1 and self.same_col(pi, nl, cap) else self.doc[pi].rect.height - 40
        eq = re.match(r"\s*\$\$(.*?)\$\$", self.md[tm.end():], re.S)  # a numbered equation right after the table ends it
        tag = re.search(r"\\tag\s*\{\s*([^}\s)]+)", eq.group(1)) if eq else None
        e = self.equation(tag.group(1).rstrip(".,")) if tag and LABEL.fullmatch(tag.group(1).rstrip(".,")) else None
        if e and e["page"] == pi and cap.y1 < e["rect"].y0 < bot:
            bot = e["rect"].y0
        cells = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", tm.group(0)).lower()))
        # the first wide text line below that is not a table row; pieces of one visual line are joined first (old scans
        # give every word its own piece)
        segs = sorted((x for x in self.stream(pi)[4] if cap.y1 < x[0].y0 < bot and self.same_col(pi, x[0], cap)),
                      key=lambda x: (round(x[0].y0 / 2.5), x[0].x0))
        rows = []
        for lr, ws in segs:
            if rows and abs(rows[-1][0].y0 - lr.y0) < 2.5 and lr.x0 - rows[-1][0].x1 < 30:
                rows[-1] = (rows[-1][0] | lr, rows[-1][1] + ws)
            else:
                rows.append((pymupdf.Rect(lr), list(ws)))
        for lr, ws in sorted(rows, key=lambda x: x[0].y0):
            toks = re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", " ".join(t for t, _ in ws).lower())
            if (lr.width > 0.6 * (c1 - c0) and self.is_prose(ws) and not ws[0][0][:1] in "*†‡§¶"
                    and sum(t in cells for t in toks) < 0.5 * len(toks)):
                bot = lr.y0
                break
        rect = self.tighten(pi, pymupdf.Rect(c0, cap.y0 - 1, c1, bot - 0.5))
        return self.region(pi, rect, {}) if rect else None
