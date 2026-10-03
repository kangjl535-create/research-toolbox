"""Place a quote on a PDF page with a text layer, the way Zotero stores highlights (validated in test T1:
rectangles within 0.43 pt of the user's own Zotero highlights).

Matching runs on a normalised character stream of the page (NFKC, ligatures expanded, quotes/dashes unified).
Strategy 1 "exact": whitespace-normalised substring. Strategy 2 "compact": all whitespace and hyphens removed
from both sides (handles line-end hyphenation and spacing differences), mapped back to character boxes.
`snap` finds the closest PDF wording for a Markdown quote that does not match exactly.
"""
import difflib, re, unicodedata
import pymupdf

TRANS = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
         "\u2212": "-", "\u00a0": " ", "\u2010": "-", "\u2011": "-", "\u2032": "'"}
WATERMARK = re.compile(r"Downloaded from|Terms and Conditions|individualUser|This article is protected by copyright"
                       r"|Wiley Online Library|for rules of use", re.I)


def norm_char(c):
    return unicodedata.normalize("NFKC", TRANS.get(c, c))


def norm_text(s):
    return re.sub(r"\s+", " ", "".join(norm_char(c) for c in s)).strip()


def clean_needle(s):
    """Remove Markdown/HTML artefacts a MinerU quote may carry."""
    s = re.sub(r"</?[A-Za-z][^<>]*>", "", s)       # <sub>, <sup>, table tags (not "a < b > c")
    s = re.sub(r"\\([*_#\[\]()])", r"\1", s)        # markdown escapes
    s = re.sub(r"\[\d+(?:[,–-]\s*\d+)*\]", "", s)   # numeric citations
    return s


def compact(text):
    idx = [i for i, c in enumerate(text) if not c.isspace() and c != "-"]
    return "".join(text[i] for i in idx), idx


_cache = {}


def page_stream(page):
    """(text, boxes, glyph offsets): normalised stream with one bbox per char (None for line-break spaces);
    publisher stamps and rotated lines are skipped."""
    key = (page.parent.name, page.number)
    if key in _cache:
        return _cache[key]
    raw = page.get_text("rawdict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP)
    out_c, out_b, out_o = [], [], []
    glyph = 0
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            chars = [(ch["c"], pymupdf.Rect(ch["bbox"])) for s in l["spans"] for ch in s["chars"]]
            if not chars:
                continue
            if WATERMARK.search("".join(c for c, _ in chars)) or l.get("dir", (1, 0))[1] != 0:
                glyph += sum(1 for c, _ in chars if not c.isspace())
                continue
            if out_c and out_c[-1] != " ":
                out_c.append(" "); out_b.append(None); out_o.append(glyph)
            for c, bb in chars:
                for nc in norm_char(c):
                    if nc.isspace():
                        if out_c and out_c[-1] == " ":
                            continue
                        out_c.append(" "); out_b.append(None); out_o.append(glyph)
                    else:
                        out_c.append(nc); out_b.append(bb); out_o.append(glyph)
                if not c.isspace():
                    glyph += 1
    _cache[key] = ("".join(out_c), out_b, out_o)
    return _cache[key]


def text_chars(doc):
    """Characters of real text per page (stamps and rotated text excluded): tells text PDFs from scans."""
    return [sum(1 for c in page_stream(p)[0] if not c.isspace()) for p in doc]


def locate(doc, needle, page_hint=None, clean=True):
    """({page, rects, glyph_offset, mode, text}, None) or (None, reason). clean=False for text taken from the PDF."""
    n = norm_text(clean_needle(needle) if clean else needle)
    if len(n) < 3:
        return None, "too short"
    pages = [page_hint] if page_hint is not None else range(doc.page_count)
    hits = []
    for strategy in ("exact", "compact"):
        for pi in pages:
            text, boxes, offs = page_stream(doc[pi])
            if strategy == "exact":
                hits += [(pi, m.start(), m.end(), strategy) for m in re.finditer(re.escape(n), text)]
            else:
                ct, cmap = compact(text)
                cn, _ = compact(n)
                hits += [(pi, cmap[m.start()], cmap[m.end() - 1] + 1, strategy) for m in re.finditer(re.escape(cn), ct)]
        if hits:
            break
    if not hits:
        return None, "not found"
    if len(hits) > 1:
        return None, f"ambiguous ({len(hits)} matches)"
    pi, s, e, strategy = hits[0]
    text, boxes, offs = page_stream(doc[pi])
    rects = []
    for bb in (b for b in boxes[s:e] if b is not None):
        if rects and abs(rects[-1].y0 - bb.y0) < 2 and abs(rects[-1].y1 - bb.y1) < 2 and bb.x0 >= rects[-1].x0 - 1:
            rects[-1] |= bb
        else:
            rects.append(pymupdf.Rect(bb))
    return {"page": pi, "rects": rects, "glyph_offset": offs[s], "mode": strategy, "text": text[s:e]}, None


def snap(doc, quote, min_ratio=0.9):  # 0.9: publisher OCR text layers misread letters; previews are checked
    """Closest span of PDF text (same length +-10 %) to a Markdown quote; (pdf text, page, ratio) or (None, None, ratio)."""
    q = norm_text(clean_needle(quote))
    best = (0, None, None)
    for pi in range(doc.page_count):
        text = page_stream(doc[pi])[0]
        sm = difflib.SequenceMatcher(None, text, q, autojunk=False)
        for blk in sm.get_matching_blocks():
            if blk.size < 8:
                continue
            for d in (-2, -1, 0):
                s0 = max(0, blk.a - blk.b + d)
                for ln in (len(q), int(len(q) * 0.9), int(len(q) * 1.1)):
                    cand = text[s0:s0 + ln]
                    r = difflib.SequenceMatcher(None, cand, q, autojunk=False).ratio()
                    if r > best[0]:
                        best = (r, pi, cand)
    if best[0] >= min_ratio:
        return best[2].strip(), best[1], best[0]
    return None, None, best[0]


def place(doc, quote):
    """(location or None, how) for a quote on a text PDF: direct match, else snapped to the PDF wording."""
    loc, why = locate(doc, quote)
    if loc:
        return loc, "direct"
    snapped, pi, ratio = snap(doc, quote)
    if snapped:
        loc, why2 = locate(doc, snapped, pi, clean=False)
        if loc:
            return loc, f"snapped {ratio:.3f}"
    return None, f"unplaced ({why}; best similarity {ratio:.2f})"


def to_zotero(page, rects):
    """PyMuPDF page rectangles (top-left origin) -> Zotero annotationPosition rects (PDF user space)."""
    m = ~page.transformation_matrix
    out = []
    for r in rects:
        q = r * m
        out.append([round(min(q.x0, q.x1), 3), round(min(q.y0, q.y1), 3), round(max(q.x0, q.x1), 3), round(max(q.y0, q.y1), 3)])
    return out


def sort_index(page, offset, rect):
    """Zotero annotationSortIndex page(5)|offset(6)|top(5); the in-page offset only orders the sidebar."""
    z = to_zotero(page, [rect])[0]
    return f"{page.number:05d}|{offset:06d}|{max(0, int(page.mediabox.height - z[3])):05d}"
