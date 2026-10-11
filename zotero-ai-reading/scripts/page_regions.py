"""Page words in reading order, quote placement on scans, and figure/equation/table regions (validated in test T5).

Words come either from Windows OCR (`ocr_windows.ps1` on 300-dpi renders; scanned PDFs) or from the PDF text
layer (text PDFs). On scans, quotes are matched like text_locator.py and snapped to the OCR wording.
Figures: the MinerU figure crops (all panels of the figure) are template-matched on the page image, on the
caption's page first, then widened to the ink touching them. Numbered equations: the ink between the nearest body-text
lines, located from the equation number or, when OCR missed it, from the Markdown text around the equation. Tables:
from the caption to the last rule (or the text after the table), with their footnotes. Labels are as printed: 7,
"2.5", "A1", "12a"; Roman numerals for tables.
Rectangles are PyMuPDF page points (top-left origin); text_locator.to_zotero converts them for Zotero.
"""
import json, pathlib, re, urllib.parse
import numpy as np, pymupdf, PIL.Image
from skimage.feature import match_template
from skimage.transform import rescale

from text_locator import (norm_char, norm_text, clean_needle, compact, align, best_span, strip_math, char_box, drawn_notes,
                          is_note, to_zotero, sort_index, WATERMARK)

OCR_DPI = 300
S = 72 / OCR_DPI  # OCR pixel -> page point
LABEL = re.compile(r"[A-Z]?\d{1,3}(?:\.\d{1,3})?[a-z]?'?|[IVXLC]{1,6}")  # 7, 2.5, A1, 12a, 55', IV
LEADER = r"[.…·]*"  # dot leaders set in one word with the number: "……….(8)" (de Kretser 2003)
NUM_TOKEN = LEADER + r"[(�ð][A-Z]?\d{1,3}(?:\.\d{1,3})?[a-z]?'?[)�Þ]"  # any printed equation number, "(4)" also read as �4� or ð4Þ
MATH_WORDS = {"cos", "sin", "tan", "cot", "sec", "csc", "exp", "log", "erf", "erfc", "sinh", "cosh", "tanh", "coth",
              "sech", "csch", "max", "min", "lim", "sup", "inf", "arg", "det", "div", "grad", "curl"}
GAP_PT = 13  # a blank band this tall ends an equation frame (inside the 90 equations of the rc tests: at most 11.5 pt)
NOTE_MARKS = "*∗⁎†‡§¶"  # table footnote marks


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
    t = strip_math(t)
    w = [x for x in re.sub(r"\s+", " ", t).strip().split(" ") if x]
    return " ".join(w[-k:] if tail else w[:k])


def join_pieces(lines):
    """A text layer that gives every word its own line (Shapiro 2011: justified text set word by word) hides the
    columns and the body-text lines: when most lines are a single word (68-75 % of Shapiro's lines, against 10 % on a
    page of formulas set glyph by glyph and 40 % on an old scan's OCR layer, whose tables are read piece by piece) and
    hardly any has several, join the pieces on one baseline that are at most a line height apart (a column gap or an
    equation number is wider)."""
    words = sum(len(ws) == 1 and len(re.findall(r"[A-Za-z]", ws[0][0])) >= 3 for ws in lines)
    if words < 0.5 * len(lines) or sum(len(ws) > 1 for ws in lines) > 0.1 * len(lines):
        return lines
    box = lambda ws: pymupdf.Rect(ws[0][1]).include_rect(ws[-1][1])
    rows = []
    for ws in sorted(lines, key=lambda ws: ws[0][1].x0):  # left to right: each piece goes on after the one before it
        r = box(ws)
        for row in rows:
            q = box(row[-1])
            h = min(r.height, q.height)
            if min(r.y1, q.y1) - max(r.y0, q.y0) > 0.6 * h and 0 <= r.x0 - q.x1 <= min(h, 20):
                row.append(ws)
                break
        else:
            rows.append([ws])
    return [[w for ws in row for w in ws] for row in sorted(rows, key=lambda row: box(row[0]).y0)]


def render_for_ocr(pdf_path, out_dir):
    """300-dpi grayscale page renders p<N>.png for ocr_windows.ps1."""
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(pymupdf.open(pdf_path)):
        p.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY).save(out_dir / f"p{i + 1}.png")
    return out_dir


def ocr_alignment(doc, ocr_json):
    """Share of the OCR words (4+ letters or digits) that the PDF's own text layer has at the same place. A publisher's
    invisible OCR layer can sit beside the printed words (Bradbury 1981: 16 % of words in place, the rest half a line
    higher and several words off; Kirkham 1959: 98 %), and highlights placed from it then cover other text."""
    ocr = {p["page"] - 1: p for p in json.load(open(ocr_json, encoding="utf-8"))}
    key = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    hit = n = 0
    for pi in range(doc.page_count):
        layer = {}
        for b in doc[pi].get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)["blocks"]:
            for l in b.get("lines", []):
                word, box = "", None
                for ch in [c for s in l["spans"] for c in s["chars"]] + [{"c": " "}]:
                    if ch["c"].isspace():
                        if len(key(word)) >= 4:
                            layer.setdefault(key(word), []).append(box)
                        word, box = "", None
                    else:
                        word, box = word + ch["c"], (pymupdf.Rect(ch["bbox"]) if box is None else box | pymupdf.Rect(ch["bbox"]))
        for l in ocr.get(pi, {}).get("lines", []):
            for w in l["words"]:
                if len(key(w["text"])) < 4 or key(w["text"]) not in layer:
                    continue
                o = pymupdf.Rect(w["x"] * S, w["y"] * S, (w["x"] + w["w"]) * S, (w["y"] + w["h"]) * S)
                c = min(layer[key(w["text"])], key=lambda r: abs(r.x0 + r.x1 - o.x0 - o.x1) + abs(r.y0 + r.y1 - o.y0 - o.y1))
                n += 1
                hit += abs(c.x0 + c.x1 - o.x0 - o.x1) / 2 < max(3, 0.25 * o.width) and abs(c.y0 + c.y1 - o.y0 - o.y1) / 2 < 0.35 * o.height
    return hit / n if n else 0.0


class Pages:
    def __init__(self, pdf_path, md_path, ocr_json=None):
        self.doc = pymupdf.open(pdf_path)
        self.md_path = pathlib.Path(md_path)
        self.md = self.md_path.read_text(encoding="utf-8")
        self.ocr = {p["page"] - 1: p for p in json.load(open(ocr_json, encoding="utf-8"))} if ocr_json else None
        prose = strip_math(re.sub(r"<table>.*?</table>|!\[[^\]]*\]\([^)]*\)", " ", self.md, flags=re.S))
        self.prose_words = set(re.findall(r"[a-z]{3,}", prose.lower())) - MATH_WORDS
        self._stream, self._ink, self._gray, self._onecol = {}, {}, {}, {}
        self._scale = None  # MinerU crop pixels per page point: one value per document, found with the first figure

    # ---------- words per line ----------
    def raw_lines(self, pi):
        if self.ocr is not None:
            return [[(w["text"], pymupdf.Rect(w["x"] * S, w["y"] * S, (w["x"] + w["w"]) * S, (w["y"] + w["h"]) * S))
                     for w in l["words"]] for l in self.ocr[pi]["lines"] if l["words"]]
        lines = []
        # no TEXT_CID_FOR_UNKNOWN_UNICODE here: an equation number's brackets would read as the letters their codes
        # happen to be ("(62)" as "s62d"), not as the U+FFFD that NUM_TOKEN expects
        raw = self.doc[pi].get_text("rawdict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
        notes = drawn_notes(self.doc[pi])
        for b in raw["blocks"]:
            for l in b.get("lines", []):
                line = "".join(ch["c"] for s in l["spans"] for ch in s["chars"])
                prose = self.is_prose([(w, None) for w in line.split()])  # equations keep their glyphs' full height
                chars = [(ch["c"], char_box(ch, s["size"]) if prose else pymupdf.Rect(ch["bbox"]))
                         for s in l["spans"] for ch in s["chars"]]
                if not chars or l.get("dir", (1, 0))[1] != 0 or WATERMARK.search(line) or (notes and is_note(l["bbox"], line, notes)):
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
        return join_pieces(lines)

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

    def snap(self, quote, min_ratio=0.85, whole=True):
        """The span closest to the quote, from the quote's first to its last character (text_locator.align):
        (span, ratio) or (None, why). whole=False: where most of the quote is, e.g. the text around an equation."""
        q = norm_text(clean_needle(quote))
        cands = [(r, pi, s, e, why) for pi in range(self.doc.page_count) for r, s, e, why in align(self.stream(pi)[0], q, whole)]
        r, pi, s, e, why = best_span(cands, min_ratio, unique=whole)
        if pi is None:
            return None, f"{why}; best similarity {r:.2f}"
        return self.span(pi, s, e, f"snapped {r:.3f}"), r

    def place_quote(self, quote, min_ratio=0.85):
        loc, why = self.locate(quote)
        if loc:
            return loc, "direct"
        loc, r = self.snap(quote, min_ratio)
        return loc, (loc["mode"] if loc else f"unplaced ({why}; {r})")

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

    def ink(self, pi, light=False):
        """Dark pixels of the page at OCR_DPI (light=True: anything but near-white, e.g. light-blue axis labels)."""
        if pi not in self._ink:
            pix = self.doc[pi].get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
            g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
            g[:, int((self.doc[pi].rect.width - 25) / S):] = 255  # drop a vertical download stamp in the right margin
            self._ink[pi] = (g < 150, g < 220)
        return self._ink[pi][light]

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
        Running headers and footers (top 10 %, bottom 8 % of the page) are left out, and so are lines across both
        columns of a two-column page (an abstract above the columns, Mattern 2008 p.1, outnumbers their lines)."""
        W, H = self.doc[pi].rect.width, self.doc[pi].rect.height
        spans = lambda q: q.x0 < W / 2 - 10 and q.x1 > W / 2 + 10
        xs = [lr for lr, _ in self.stream(pi)[4]
              if lr.width > 0.3 * W / 2 and lr.y0 > 0.1 * H and lr.y1 < 0.92 * H and self.same_col(pi, lr, r)
              and (self.one_column(pi) or spans(r) or not spans(lr))]
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
        and other short lines the converter wrote between them ("(a) ...", "colorbar: 4 to 20"; several "Fig. 5(a)",
        "Fig. 5(b)" captions add up); else the images just after the caption (a caption above its figure), unless
        another figure's caption follows them. Returns (paths in Markdown order, Markdown offset of the first, whether
        each panel has its own caption)."""
        lines = self.md.split("\n")
        starts = np.cumsum([0] + [len(l) + 1 for l in lines])
        cap = re.compile(rf"^\s*[*_]*(?:Fig\.?|Figure)\s*{md_label(n)}", re.I)
        any_fig = re.compile(r"^\s*[*_]*(?:Fig\.?|Figure)\s*[A-Z]?\d", re.I)
        img = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

        def walk(i, step):
            found, j = [], i + step
            while 0 <= j < len(lines):
                s = lines[j].strip()
                m = img.search(s)
                if m:
                    found.append((m.group(1), starts[j]))
                elif s and (any_fig.match(s) or re.match(r"[*_]*(?:Table|TABLE)\s*[A-Z]?\d", s)
                            or (len(s) > 100 and not (s.startswith("(") or re.match(r"[a-z]\)", s)))):  # not "(a) ..."
                    if step > 0 and found and any_fig.match(s):
                        return []  # the images of the next figure
                    break
                j += step
            return found[::-1] if step < 0 else found

        caps = [i for i, l in enumerate(lines) if cap.match(l)]
        panel = re.compile(rf"^\s*[*_]*(?:Fig\.?|Figure)\s*{md_label(n)}\s*\(?[a-z]\)?(?![a-z])", re.I)  # "Fig. 5(a) ...", "Fig. 5b ..."
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

    def text_rows(self, pi):
        """Visual text lines of page pi: pieces on one baseline less than 30 pt apart joined (old scans give every
        word its own piece). [(rect, words)] from top to bottom."""
        rows = []
        for lr, ws in sorted(self.stream(pi)[4], key=lambda x: (round(x[0].y0 / 2.5), x[0].x0)):
            if rows and abs(rows[-1][0].y0 - lr.y0) < 2.5 and lr.x0 - rows[-1][0].x1 < 30:
                rows[-1] = (rows[-1][0] | lr, rows[-1][1] + ws)
            else:
                rows.append((pymupdf.Rect(lr), list(ws)))
        return rows

    def grow(self, pi, r, reach=10.0):
        """Widen a figure frame to the ink next to it: axis labels, colour bars and parts of the figure that MinerU's
        image leaves out (feedback 2026-10-04/05: theta axis labels, a right-hand axis, a cell drawn beyond the crop).
        Each step takes the ink within `reach` points of an edge; it stops at a blank band that wide, at the page
        margins and at captions and body text (prose at least 100 pt and 60 % of the frame wide; a title inside the
        figure is narrower)."""
        m, page = self.ink(pi, light=True), self.doc[pi].rect
        lim = page + (10, 10, -10, -10)
        rows = [(lr, ws) for lr, ws in self.text_rows(pi) if lr.width >= 80 and self.is_prose(ws)]
        para = lambda lr: any(o is not lr and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0.5 * min(o.width, lr.width)
                              and -0.5 * lr.height < max(o.y0 - lr.y1, lr.y0 - o.y1) < 0.8 * lr.height for o, _ in rows)
        text = [lr for lr, ws in rows if lr.width >= 100 and (lr.width >= 0.6 * r.width or para(lr)  # body text, a caption beside
                                                             or re.match(r"(Fig\.?|FIG\.?|Figure|FIGURE|Table|TABLE)$", ws[0][0]))]
        text += [lr for lr, _ in self.stream(pi)[4] if lr.y1 < 0.08 * page.height or lr.y0 > 0.94 * page.height]  # running head, foot
        text += [lr for lr, ws in self.text_rows(pi) if not lr.intersects(r) and (lr.width >= 0.6 * r.width  # an equation beside it
                 or re.match(r"(Fig\.?|FIG\.?|Figure|FIGURE|Table|TABLE)$", ws[0][0]))]  # a caption, however short
        def rule_row(y):  # a line running on across the page on both sides, not the figure's own top or bottom line
            a, b = m[y, max(0, int((r.x0 - 12) / S)):max(0, int((r.x0 - 2) / S))], m[y, int((r.x1 + 2) / S):int((r.x1 + 12) / S)]
            return a.size > 0 and b.size > 0 and a.all() and b.all()
        r = pymupdf.Rect(r)
        for _ in range(200):
            before = tuple(r)
            for side in range(4):
                s = pymupdf.Rect(r) + ((0, 2, 0, -2) if side in (0, 2) else (2, 0, -2, 0))  # not the lines it touches
                if side == 0:
                    s.x0, s.x1 = r.x0 - reach, r.x0
                elif side == 1:
                    s.y0, s.y1 = r.y0 - reach, r.y0
                elif side == 2:
                    s.x0, s.x1 = r.x1, r.x1 + reach
                else:
                    s.y0, s.y1 = r.y1, r.y1 + reach
                s &= lim
                if s.is_empty or any(s.intersects(t) for t in text):
                    continue
                y0, x0 = int(s.y0 / S), int(s.x0 / S)
                sub = m[y0:int(s.y1 / S), x0:int(s.x1 / S)].copy()
                if side in (1, 3):
                    for i in np.where(sub.any(1))[0]:
                        if rule_row(y0 + i):
                            sub[i] = False
                rows, cols = np.where(sub.any(1))[0], np.where(sub.any(0))[0]
                if not len(rows):
                    continue
                if side == 0:
                    r.x0 = min(r.x0, float(x0 + cols[0]) * S)
                elif side == 1:
                    r.y0 = min(r.y0, float(y0 + rows[0]) * S)
                elif side == 2:
                    r.x1 = max(r.x1, float(x0 + cols[-1] + 1) * S)
                else:
                    r.y1 = max(r.y1, float(y0 + rows[-1] + 1) * S)
            if max(abs(a - b) for a, b in zip(before, r)) < 0.2:
                break
        return r

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
        on_page = lambda q: any(re.match(rf"(?:Fig|FIG|Figure|FIGURE)\.?,?\s*{num_re(n)}\b", " ".join(t for t, _ in ws))
                                for _, ws in self.stream(q)[4])
        captioned = cap is not None and re.match(rf"(?:Fig|FIG|Figure|FIGURE)\.?,?\s*{num_re(n)}\s*[.:—–-]", " ".join(
            t for lr, ws in self.stream(cap_pi)[4] if lr.intersects(cap) for t, _ in ws))  # a caption, not "(Fig. 1) d/a"
        if score < 0.6 or (captioned and pi != cap_pi and score < 0.85 and not on_page(pi)):
            return None  # off its caption's page, a close match only: not another figure's image
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
        rect = self.grow(pi, self.tighten(pi, raw + (-3, -3, 3, 3)) or raw)
        lines = self.stream(pi)[4]
        para = lambda lr: any(o is not lr and self.is_prose(ows) and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0
                              and -0.5 * lr.height < max(o.y0 - lr.y1, lr.y0 - o.y1) < 0.8 * lr.height for o, ows in lines)
        for lr, ws in lines:  # never cut through a text line at the top or bottom edge
            overlap = min(lr.x1, rect.x1) - max(lr.x0, rect.x0)
            if overlap < 0.3 * lr.width or not self.is_prose(ws):
                continue
            # a short line within the figure's width and outside any paragraph is the figure's own: an axis title
            # (de Kretser 2003 Fig. 9 "Volume Fraction Solids") is taken in, body text is left out
            own = (lr.x0 >= rect.x0 - 2 and lr.x1 <= rect.x1 + 2 and lr.width < 0.6 * rect.width and not para(lr)
                   and not re.match(r"(Fig\.?|FIG\.?|Figure|FIGURE|Table|TABLE)$", ws[0][0]))  # a short caption: "Figure 5."
            if lr.y0 < rect.y0 < lr.y1:
                rect.y0 = lr.y0 - 0.5 if own else lr.y1 + 0.5
            elif lr.y0 < rect.y1 < lr.y1:
                rect.y1 = lr.y1 + 0.5 if own else lr.y0 - 0.5
        info = {"match_score": round(score, 3)}
        if len(tpls) > 1:
            info["panels"] = f"{panels} of {len(tpls)}"
        if cap is not None and cap_pi == pi:
            info["caption_gap_pt"] = round(cap.y0 - rect.y1, 1)
        return self.region(pi, rect, info)

    # ---------- numbered equations ----------
    def number_tokens(self, n):
        """[(page, rect)] of the printed equation number (n) standing at the right of its column."""
        cands = []
        for pi in range(self.doc.page_count):
            for lr, ws in self.stream(pi)[4]:
                for t, r in ws:
                    if re.fullmatch(rf"{LEADER}[(�ð]{num_re(n)}[)�Þ]", t):  # text layers may give "(4)" as �4� or ð4Þ
                        c0, c1 = self.column(pi, r)
                        if r.x1 > c1 - 25 and (len(ws) <= 2 or lr.x0 > c0 + 30):
                            cands.append((pi, r))
        return cands

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
                    loc, _ = self.snap(words_of(para, 12, tail), 0.8, whole=False)
                anchors[side] = loc
        cands = self.number_tokens(n)
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
        # body text starts at the column's left edge or fills half of it; words set inside an equation do neither
        # ("Convection", "Diffusion" under the braces of TY007 Eq. 1)
        text_line = lambda lr: lr.x0 < c0 + 0.25 * (c1 - c0) or lr.width > 0.5 * (c1 - c0)
        body = [lr for li, (lr, ws) in enumerate(self.stream(pi)[4])
                if self.same_col(pi, lr, ref) and not beside(lr) and ((self.is_prose(ws) and text_line(lr)) or li in anchor_lines)]
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
    def rules(self, pi, y0, y1):
        """Horizontal rules between y0 and y1: Rects of thin ink bands (3 pt at most) with a run of 100 pt or more."""
        m = self.ink(pi)[max(0, int(y0 / S)):int(y1 / S)]
        hits = []
        for i, row in enumerate(m):
            if row.sum() * S < 100:
                continue
            d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
            starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
            k = np.argmax(ends - starts)
            if (ends[k] - starts[k]) * S >= 100:
                hits.append(pymupdf.Rect(starts[k] * S, y0 + i * S, ends[k] * S, y0 + (i + 1) * S))
        out = []
        for h in hits:
            if out and h.y0 - out[-1][-1].y1 < S / 2 and abs(h.x0 - out[-1][-1].x0) < 3:
                out[-1].append(h)
            else:
                out.append([h])
        return [pymupdf.Rect(min(h.x0 for h in g), g[0].y0, max(h.x1 for h in g), g[-1].y1) for g in out if g[-1].y1 - g[0].y0 <= 3]

    def md_table(self, n):
        """The Markdown caption 'Table n' and the HTML table up to 3 short lines below it (match or None)."""
        return re.search(rf"\n[*_]*((?:Table|TABLE)\s*{md_label(n)}[*_]*[.:]?[^\n]*)\n(?:[^\n<]*\n){{0,3}}?<table>.*?</table>", self.md, re.S)

    def table(self, n):
        """Frame of table n: from its caption over its rows to its last rule (when the table has rules), with the
        footnotes right below it whole; as wide as its rules or rows, which can exceed the text column."""
        tm = self.md_table(n)
        if not tm:
            return None
        pi, cap = self.caption_line("Table|TABLE", n)
        if cap is None:
            return None
        nxt = next((p for p in self.md[tm.end():].split("\n\n") if p.strip() and not p.strip().startswith(("$", "\\", "<"))), "")
        nxt = re.sub(r"^#+\s*", "", nxt.strip())  # a heading: "### **2.2. Diffusion**"
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
        toks = lambda ws: re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", " ".join(t for t, _ in ws).lower())
        is_row = lambda ws: toks(ws) and sum(t in cells for t in toks(ws)) >= 0.5 * len(toks(ws))
        limit = bot
        for lr, ws in sorted(rows, key=lambda x: x[0].y0):  # the footnotes are added whole below
            if (lr.width > 0.6 * (c1 - c0) and self.is_prose(ws) and not is_row(ws)) or ws[0][0][:1] in NOTE_MARKS:
                bot = lr.y0
                break
        # a table with rules (the first right under the caption or its continuation) ends at its last rule: rules
        # nearly as wide as the first and overlapping it, above the next caption and the next paragraph wider than the
        # table; a figure or text below it is left out. A row read differently from the Markdown does not end it.
        page, h = self.doc[pi], cap.height
        rules = self.rules(pi, cap.y1, limit)
        if any(abs(lr.y0 - cap.y0) < 3 * h and (lr.x1 < cap.x0 or lr.x0 > cap.x1)  # another table beside it: its rules can
               and re.match(r"(Table|TABLE|Fig\.?|FIG\.?|Figure|FIGURE)$", ws[0][0]) for lr, ws in self.stream(pi)[4]):  # run on
            lo, hi = self.column(pi, cap)
            rules = [pymupdf.Rect(max(r.x0, lo), r.y0, min(r.x1, hi), r.y1) for r in rules if min(r.x1, hi) - max(r.x0, lo) >= 100]
        top = [r for r in rules if r.width >= 0.6 * cap.width and r.y0 - cap.y1 < 6 * h]
        info = {}
        if top:
            first = top[0]
            under = lambda lr: min(lr.x1, first.x1) - max(lr.x0, first.x0) > 0.5 * lr.width  # below the table, not beside it
            stop = min([lr.y0 for lr, ws in self.stream(pi)[4] if first.y1 < lr.y0 < limit and under(lr) and (
                re.match(r"(Table|TABLE|Fig\.?|FIG\.?|Figure|FIGURE)\s*[A-Z]?\d", ws[0][0] + " " + (ws[1][0] if len(ws) > 1 else ""))
                or (lr.width >= 0.8 * first.width and self.is_prose(ws) and not is_row(ws) and ws[0][0][:1] not in NOTE_MARKS))],
                default=limit)
            rules = [r for r in rules if r.y0 < stop and r.width >= 0.6 * first.width
                     and min(r.x1, first.x1) - max(r.x0, first.x0) > 0.5 * r.width]
            c0, c1 = min([cap.x0] + [r.x0 for r in rules]) - 2, max([cap.x1] + [r.x1 for r in rules]) + 2  # the rules' width
            lo, hi = self.column(pi, cap)  # and the printed rows between them, in the caption's column (broken scanned rules)
            cols = np.where(self.ink(pi)[int(first.y1 / S) + 2:int(rules[-1].y0 / S) - 1].any(0))[0] * S
            cols = cols[(cols >= min(lo, c0)) & (cols <= max(hi, c1))]
            if len(rules) > 1 and len(cols):
                c0, c1 = min(c0, cols.min() - 1), max(c1, cols.max() + 1)
            # the Markdown table's last row lies above the last rule, unless rows without rules follow (a rule under the
            # header only, a table going on on the next page): then it ends at the first text line below, as without rules
            last_row = (re.findall(r"<tr[^>]*>(.*?)</tr>", tm.group(0), re.S) or [""])[-1]
            want = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", last_row).lower()))
            have = {t for lr, ws in self.text_rows(pi) if first.y0 - 1 < lr.y0 < rules[-1].y0 and under(lr) for t in toks(ws)}
            bot = rules[-1].y1 + 1 if len(want & have) >= 0.5 * len(want) else max(bot, rules[-1].y1 + 1)
            info["rules"] = len(rules)
        wide = top and first.x0 < page.rect.width / 2 - 10 < page.rect.width / 2 + 10 < first.x1  # across both columns
        pieces = [x for x in self.stream(pi)[4] if cap.y1 < x[0].y0 < bot and (wide or self.same_col(pi, x[0], cap))]
        for lr, ws in pieces:  # rows reaching beyond the text column (a table set wider than the text), anything between rules
            if is_row(ws) or (top and first.y0 < lr.y0 < rules[-1].y0):
                c0, c1 = min(c0, lr.x0 - 2), max(c1, lr.x1 + 2)
        # footnotes right below: lines starting with a note mark and the lines continuing them, all or none
        below = sorted((x for x in self.stream(pi)[4] if (x[0].y0 + x[0].y1) / 2 > bot - 1  # a raised † lifts a line's top
                        and x[0].x0 >= c0 - 10 and x[0].x1 <= c1 + 10), key=lambda x: x[0].y0)
        last = None
        for lr, ws in below:
            if last is None and not (lr.y0 - bot < 1.5 * lr.height and re.match(rf"[{NOTE_MARKS}]|Notes?\b", ws[0][0])):
                break
            if last is not None and lr.y0 - last.y1 > 0.6 * lr.height:
                break
            last = lr
            c0, c1 = min(c0, lr.x0 - 2), max(c1, lr.x1 + 2)
        if last is not None:
            bot, info["footnotes"] = last.y1 + 1, True
        rect = self.tighten(pi, pymupdf.Rect(c0, cap.y0 - 1, c1, bot - 0.5))
        return self.region(pi, rect, info) if rect else None

    # ---------- reasons ----------
    def why_unlocated(self, kind, n):
        """Why figure/table/equation n was not located, for the place report: most often the converter dropped or
        garbled the caption label in the Markdown, so nothing ties the request to its images or rows."""
        if kind == "figure":
            if not re.search(rf"^\s*[*_]*(?:Fig\.?|Figure)\s*{md_label(n)}", self.md, re.I | re.M):
                return f"the Markdown has no caption line 'Figure {n}' (the converter dropped or garbled it), so its images are unknown"
            if not self.figure_images(n)[0]:
                return f"no Markdown image next to the caption 'Figure {n}'"
            return f"the Markdown images of Figure {n} do not match its caption's page (or match another page only weakly)"
        if kind == "table":
            if not re.search(rf"^[*_]*(?:Table|TABLE)\s*{md_label(n)}", self.md, re.M):
                return f"the Markdown has no caption line 'Table {n}' (the converter dropped it), so its rows are unknown"
            if not self.md_table(n):
                return f"no HTML table within 3 lines below the Markdown caption 'Table {n}'"
            if self.caption_line("Table|TABLE", n)[1] is None:
                return f"no caption 'Table {n}' at the start of a line in the PDF text"
            return f"the frame of Table {n} came out empty"
        nums = len(self.number_tokens(n))
        tagged = re.search(rf"\\tag\s*\{{\s*{re.escape(str(n))}\s*\)?[.,]*\s*\}}", self.md)
        where = (f"the printed number ({n}) stands at a column's right edge {nums} times" if nums > 1 else
                 f"the printed number ({n}) was not found at a column's right edge" if not nums else
                 f"the band around the printed number ({n}) has no body-text lines above and below")
        return where + ("" if nums == 1 else ", and the text around the Markdown equation is not on one page" if tagged
                        else f", and the Markdown has no \\tag{{{n}}}")
