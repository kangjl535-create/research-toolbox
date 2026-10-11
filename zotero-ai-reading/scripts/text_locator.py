"""Place a quote on a PDF page with a text layer, the way Zotero stores highlights (validated in test T1:
rectangles within 0.43 pt of the user's own Zotero highlights).

Matching runs on a normalised character stream of the page (NFKC, ligatures expanded, quotes/dashes unified).
Strategy 1 "exact": whitespace-normalised substring. Strategy 2 "compact": whitespace, hyphens and numeric citations
removed from both sides (handles line-end hyphenation, spacing and a citation one side lacks), mapped back to
character boxes. `snap` aligns a Markdown quote that does not match exactly with the closest PDF wording; its span
starts and ends at the characters matched to the quote's first and last ones, and a quote whose start or end is
missing (the rest is on another page or in another column) is not placed. Every placement is checked: the
characters under its rectangles must be the matched ones.
"""
import collections, difflib, re, unicodedata
import pymupdf

TRANS = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
         "\u2212": "-", "\u00a0": " ", "\u2010": "-", "\u2011": "-", "\u2032": "'"}
WATERMARK = re.compile(r"Downloaded from|Terms and Conditions|individualUser|This article is protected by copyright"
                       r"|Wiley Online Library|for rules of use", re.I)
TEXT_FLAGS = pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_CID_FOR_UNKNOWN_UNICODE
CITATION = re.compile(r"\[\d+(?:\s*[,-]\s*\d+)*\]")  # [53], [52-58], [32, 52-58] (dashes normalised)
END_SLACK = 3  # quote characters at either end that may differ from the PDF (a misread first or last letter)


def readable(c):
    """A character as read with TEXT_FLAGS: a character code below 32 (a math font's glyph number) is U+FFFD, as
    without the flag."""
    return "�" if ord(c) < 32 and not c.isspace() else c


def char_box(ch, size):
    """A rawdict character's box, at most 1.5 font sizes tall around its baseline: some math fonts declare an ascent
    and descent several times their size, and one θ makes its line's box four lines tall (page_regions' lines;
    highlights keep the boxes the PDF gives, as Zotero draws them, and the coverage check refuses a tall one)."""
    r = pymupdf.Rect(ch["bbox"])
    if size and r.height > 1.5 * size:
        r.y0, r.y1 = ch["origin"][1] - 0.95 * size, ch["origin"][1] + 0.3 * size
    return r


def inside(box, rect):
    """The centre of a character box lies in rect, edges included (the second glyph of a ligature has zero width)."""
    x, y = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
    return rect.x0 <= x <= rect.x1 and rect.y0 <= y <= rect.y1


def drawn_notes(page):
    """(rect, text without spaces) of the free-text annotations someone drew on the PDF (MuPDF reads their text with
    the page's)."""
    return [(a.rect, re.sub(r"\s+", "", a.info.get("content", ""))) for a in page.annots(types=[pymupdf.PDF_ANNOT_FREE_TEXT])]


def is_note(bbox, text, notes):
    """A text line that is (part of) a drawn note: inside its rectangle and part of its text."""
    t = re.sub(r"\s+", "", text)
    return bool(t) and any(inside(pymupdf.Rect(bbox), r) and t in c for r, c in notes)


def norm_char(c):
    return unicodedata.normalize("NFKC", TRANS.get(c, c))


def norm_text(s):
    return re.sub(r"\s+", " ", "".join(norm_char(c) for c in s)).strip()


def clean_needle(s):
    """Remove Markdown/HTML artefacts a MinerU quote may carry."""
    s = re.sub(r"</?[A-Za-z][^<>]*>", "", s)       # <sub>, <sup>, table tags (not "a < b > c")
    s = re.sub(r"(?<!\\)\*+", "", s)                # emphasis: "Fig. 5*E*", "**bold**"
    s = re.sub(r"(?<![\w\\])_+(?=\w)|(?<=\w)_+(?!\w)", "", s)  # emphasis: "_italic_" (not snake_case)
    s = re.sub(r"\\([*_#\[\]()])", r"\1", s)        # markdown escapes
    return s


def compact(text):
    """(text without whitespace, hyphens and numeric citations, index of each kept character in `text`)."""
    cited = {i for m in CITATION.finditer(text) for i in range(m.start(), m.end())}
    idx = [i for i, c in enumerate(text) if not c.isspace() and c != "-" and i not in cited]
    return "".join(text[i] for i in idx), idx


def strip_math(md):
    """Markdown without its math: $$...$$ blocks, then $...$ within one line. An escaped \\$ (a currency sign) never
    opens or closes math, and an unpaired $ removes nothing, so prose between two formulas is kept."""
    md = re.sub(r"(?<!\\)\$\$.*?(?<!\\)\$\$", " ", md, flags=re.S)
    return re.sub(r"(?<!\\)\$(?:\\\$|[^$\n])*?(?<!\\)\$", " ", md)


_cache = {}


def page_stream(page):
    """(text, boxes, glyph offsets): normalised stream with one bbox per char (None for line-break spaces);
    publisher stamps, rotated lines and the text of free-text notes someone drew on the PDF are skipped.
    Glyphs whose font has no Unicode mapping are read by their character code, which in old PDFs is usually the
    letter itself (Bromhead 1996), instead of U+FFFD."""
    key = (page.parent.name, page.number)
    if key in _cache:
        return _cache[key]
    raw = page.get_text("rawdict", flags=TEXT_FLAGS)
    notes = drawn_notes(page)
    out_c, out_b, out_o = [], [], []
    glyph = 0
    for b in raw["blocks"]:
        for l in b.get("lines", []):
            chars = [(readable(ch["c"]), pymupdf.Rect(ch["bbox"])) for s in l["spans"] for ch in s["chars"]]
            if not chars:
                continue
            line = "".join(c for c, _ in chars)
            if WATERMARK.search(line) or l.get("dir", (1, 0))[1] != 0 or (notes and is_note(l["bbox"], line, notes)):
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
    """Characters of real text per page (stamps and rotated text excluded)."""
    return [sum(1 for c in page_stream(p)[0] if not c.isspace()) for p in doc]


def text_kind(doc, md_text=None):
    """("text" | "scan" | "check", why): "scan" unless at least half of the pages have usable text: 150 letters
    outside lines repeated on most pages (download stamps) and, given the Markdown, mostly words that the Markdown
    has too (an undecodable or garbled text layer does not). "check": most text is invisible, an OCR layer laid over
    page images, whose position must be compared with the images (page_regions.ocr_alignment)."""
    pages = [[l.strip() for l in p.get_text("text").split("\n") if l.strip()] for p in doc]
    n = len(pages)
    seen = collections.Counter(l for ls in pages for l in set(ls) if len(l) >= 20)
    stamps = {l for l, k in seen.items() if k >= max(2, n / 2)} if n > 1 else set()
    md_words = set(re.findall(r"[a-z]{4,}", md_text.lower())) if md_text else None
    good = 0
    for ls in pages:
        body = [l for l in ls if l not in stamps]
        words = re.findall(r"[a-z]{4,}", " ".join(body).lower())
        good += (sum(c.isalpha() for l in body for c in l) >= 150
                 and (md_words is None or sum(w in md_words for w in words) >= 0.5 * len(words)))
    if good < n / 2:
        return "scan", f"usable text layer on {good} of {n} pages"
    shown = hidden = 0
    for p in doc:
        for s in p.get_texttrace():
            if s["type"] == 3:
                hidden += len(s["chars"])
            else:
                shown += len(s["chars"])
    if hidden > shown:
        return "check", "invisible OCR text layer"
    return "text", None


def align(text, q, whole=True):
    """Spans of `text` close to the quote q, compared compacted and in lower case: [(ratio, start, end, why)], with
    start and end on the characters matched to the quote's first and last ones (why None), or no span and why the
    candidate failed. Matching pieces of the quote are chained outwards from the longest one while the text between
    two pieces is about as long on both sides; a candidate that misses the quote's first or last characters (beyond
    END_SLACK) is refused, unless whole=False (only where the text is matters: the share of the quote found is then
    the ratio)."""
    ct, cmap = compact(text)
    ct, cq = ct.lower(), compact(q)[0].lower()
    if len(cq) < 8 or not ct:
        return []
    out, seen = [], []
    for blk in difflib.SequenceMatcher(None, ct, cq, autojunk=False).get_matching_blocks():
        a0 = blk.a - blk.b  # where the quote would start
        if blk.size < 8 or any(abs(a0 - x) <= 3 for x in seen):
            continue
        seen.append(a0)
        pad = len(cq) // 5 + 10
        w0 = max(0, a0 - pad)
        w = ct[w0:a0 + len(cq) + pad]
        bl = [b for b in difflib.SequenceMatcher(None, w, cq, autojunk=False).get_matching_blocks() if b.size]
        big = [i for i, b in enumerate(bl) if b.size >= 3]
        if not big:
            continue
        gaps = lambda x, y: (y.a - x.a - x.size, y.b - x.b - x.size)
        fits = lambda x, y: abs(gaps(x, y)[0] - gaps(x, y)[1]) <= 4 + 0.25 * gaps(x, y)[1]
        near = lambda x, y: max(gaps(x, y)) <= 3 and abs(gaps(x, y)[0] - gaps(x, y)[1]) <= 1
        k = max(range(len(big)), key=lambda i: bl[big[i]].size)
        lo = hi = k
        while lo > 0 and fits(bl[big[lo - 1]], bl[big[lo]]):
            lo -= 1
        while hi < len(big) - 1 and fits(bl[big[hi]], bl[big[hi + 1]]):
            hi += 1
        lo, hi = big[lo], big[hi]
        while lo > 0 and near(bl[lo - 1], bl[lo]):  # short pieces at the ends: "5E)." after "Fig."
            lo -= 1
        while hi < len(bl) - 1 and near(bl[hi], bl[hi + 1]):
            hi += 1
        head, tail = bl[lo].b, len(cq) - bl[hi].b - bl[hi].size
        found = sum(b.size for b in bl[lo:hi + 1])
        if not whole:
            out.append((found / len(cq), cmap[w0 + bl[lo].a], cmap[w0 + bl[hi].a + bl[hi].size - 1] + 1, None))
            continue
        if head > END_SLACK or tail > END_SLACK:
            out.append((found / len(cq), None, None,
                        f"only {found} of {len(cq)} characters in one piece here, without the quote's "
                        f"{'start' if head > END_SLACK else 'end'} (on another page or in another column?)"))
            continue
        s, e = max(0, bl[lo].a - head), min(len(w), bl[hi].a + bl[hi].size + tail)
        r = difflib.SequenceMatcher(None, w[s:e], cq, autojunk=False).ratio()
        out.append((r, cmap[w0 + s], cmap[w0 + e - 1] + 1, None))
    return out


def best_span(cands, min_ratio, unique=True):
    """(ratio, key, start, end, None) of the best candidate [(ratio, key, start, end, why)], or (ratio, None, None,
    None, why). With unique, a second candidate as good elsewhere (another key, or not overlapping) makes the quote
    ambiguous; without, the first of them is taken."""
    ok = sorted((c for c in cands if c[2] is not None), key=lambda c: -c[0])
    if ok and ok[0][0] >= min_ratio:
        b = ok[0]
        if unique and any(c[0] >= b[0] - 0.005 and (c[1] != b[1] or c[3] <= b[2] or c[2] >= b[3]) for c in ok[1:]):
            return b[0], None, None, None, "ambiguous"
        return b
    r, _, _, _, why = max(cands, key=lambda c: c[0], default=(0.0, None, None, None, "not found"))
    return r, None, None, None, why or "not similar enough"


def rects_of(page, s, e):
    """Rectangles of stream characters s..e, one per line piece (as Zotero stores a highlight)."""
    rects = []
    for bb in (b for b in page_stream(page)[1][s:e] if b is not None):
        if rects and abs(rects[-1].y0 - bb.y0) < 2 and abs(rects[-1].y1 - bb.y1) < 2 and bb.x0 >= rects[-1].x0 - 1:
            rects[-1] |= bb
        else:
            rects.append(pymupdf.Rect(bb))
    return rects


def covered_text(page, rects):
    """The page's characters whose centre lies inside the rectangles, in stream order: what the highlight shows.
    (page.get_textbox would also return neighbouring lines whose tall character boxes merely touch a rectangle.)"""
    text, boxes, _ = page_stream(page)
    return "".join(c for c, b in zip(text, boxes) if b is not None and any(inside(b, r) for r in rects))


def coverage_problem(matched, under):
    """Why the text under a highlight's rectangles is not the matched text, or None. A stray glyph or two (a large
    bracket or a subscript of a formula reaching into the line, overlapping boxes of an OCR layer) is tolerated;
    three or more letters or digits too many or too few are not."""
    a, b = compact(matched)[0], compact(under)[0]
    extra = missing = ""
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("insert", "replace"):
            extra += "".join(c for c in b[j1:j2] if c.isalnum())
        if op in ("delete", "replace"):
            missing += "".join(c for c in a[i1:i2] if c.isalnum())
    if len(extra) >= 3:
        return f"its rectangles would also cover other text ({extra[:40]!r})"
    if len(missing) >= 3:
        return f"its rectangles would miss part of it ({missing[:40]!r})"
    return None


def span(doc, pi, s, e, mode):
    """(location, None) for stream characters s..e of page pi, or (None, why) when its rectangles would cover
    other characters of the page or miss some of these (coverage_problem)."""
    page = doc[pi]
    text, boxes, offs = page_stream(page)
    rects = rects_of(page, s, e)
    why = coverage_problem(text[s:e], covered_text(page, rects))
    if why:
        return None, why
    return {"page": pi, "rects": rects, "glyph_offset": offs[s], "mode": mode, "text": text[s:e]}, None


def locate(doc, needle, page_hint=None, clean=True):
    """({page, rects, glyph_offset, mode, text}, None) or (None, reason). clean=False for text taken from the PDF."""
    n = norm_text(clean_needle(needle) if clean else needle)
    if len(n) < 3:
        return None, "too short"
    pages = [page_hint] if page_hint is not None else range(doc.page_count)
    hits = []
    for strategy in ("exact", "compact"):
        cn = compact(n)[0]
        for pi in pages:
            text = page_stream(doc[pi])[0]
            if strategy == "exact":
                hits += [(pi, m.start(), m.end(), strategy) for m in re.finditer(re.escape(n), text)]
            elif cn:
                ct, cmap = compact(text)
                hits += [(pi, cmap[m.start()], cmap[m.end() - 1] + 1, strategy) for m in re.finditer(re.escape(cn), ct)]
        if hits:
            break
    if not hits:
        return None, "not found"
    if len(hits) > 1:
        return None, f"ambiguous ({len(hits)} matches)"
    return span(doc, *hits[0])


def snap(doc, quote, min_ratio=0.9):  # 0.9: publisher OCR text layers misread letters; previews are checked
    """The PDF span closest to a Markdown quote that does not match exactly: (location, ratio) or (None, why)."""
    q = norm_text(clean_needle(quote))
    cands = [(r, pi, s, e, why) for pi in range(doc.page_count) for r, s, e, why in align(page_stream(doc[pi])[0], q)]
    r, pi, s, e, why = best_span(cands, min_ratio)
    if pi is None:
        return None, f"{why}; best similarity {r:.2f}"
    loc, why = span(doc, pi, s, e, f"snapped {r:.3f}")
    return (loc, r) if loc else (None, why)


def place(doc, quote):
    """(location or None, how) for a quote on a text PDF: direct match, else snapped to the PDF wording."""
    loc, why = locate(doc, quote)
    if loc:
        return loc, "direct"
    if why.startswith("its rectangles"):  # the quote is there, but a highlight would show other text
        return None, f"unplaced ({why})"
    loc, r = snap(doc, quote)
    if loc:
        return loc, loc["mode"]
    return None, f"unplaced ({why}; {r})"


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
