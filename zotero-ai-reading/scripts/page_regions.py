"""Page words in reading order, quote placement on scans, and figure/equation/table regions (validated in test T5).

Words come either from Windows OCR (`ocr_windows.ps1` on 300-dpi renders; scanned PDFs) or from the PDF text
layer (text PDFs). On scans, quotes are matched like text_locator.py and snapped to the OCR wording.
Figures: the MinerU (or Marker) figure crops (all panels of the figure) are template-matched on the page image, on
the caption's page first, then widened to the ink touching them and to the PDF image they lie in. Numbered equations:
the ink between the nearest body-text lines, located from the equation number or, when OCR missed it, from the Markdown
text around the equation. Tables: from the caption to the last rule (or the text after the table), with their
footnotes; a table printed above its caption from its first row to the caption. Labels are as printed: 7, "2.5",
"A1", "B.1", "12a", "[3]"; Roman numerals for tables. A caption whose label the converter dropped can be named by its
Markdown text (caption=...).
A frame that would be wrong (panels missing, another caption or body text inside, an equation cut or spanning both
columns, a table going on beyond it) is not returned; why_unlocated then says why: a missing frame is better than a
wrong one.
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
_CORE = r"(?:[A-Z]\.?)?\d{1,3}(?:\.\d{1,3})?[a-z]?'?|[IVXLC]{1,6}"
LABEL = re.compile(rf"{_CORE}|\[(?:{_CORE})\]")  # 7, 2.5, A1, B.1, 12a, 55', IV; [3] as PNAS prints equation numbers
LEADER = r"[.…·]*"  # dot leaders set in one word with the number: "……….(8)" (de Kretser 2003)
_NUM = r"(?:[A-Z][.:]?)?\d{1,3}(?:[.:]\d{1,3})?[a-z]?'?"
NUM_TOKEN = LEADER + rf"[(�ð]{_NUM}[)�Þ]"  # any printed equation number, "(4)" also read as �4� or ð4Þ
NUM_TOKEN_SQ = LEADER + rf"[\[(�ð]{_NUM}[\])�Þ]"  # ... in a paper whose equation numbers are bracketed: [2a]
IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
CHART = re.compile(r"\bx\d?:\s.*;\s*y\d?:\s")  # Marker's chart description: "panel (a) x: t (s), 0 to 250; y: F (N), ..."


def spaced(word):
    """A word as converters and text layers write it letter-spaced: "F I G U R E", "TAB L E"."""
    return r"\s?".join(re.escape(c) for c in word)


FIG_MD = rf"(?:{spaced('Fig')}[.,]?|{spaced('Figure')})"  # with re.I: Fig., FIG., Fig, (garbled), Figure, F I G U R E (not "Figs. 5")
TAB_MD = rf"(?:{spaced('Table')}|{spaced('TABLE')})"
FIG_PDF = rf"(?i:{spaced('fig')}(?:{spaced('ure')})?)"  # caption words in the PDF text: any case, letter-spaced
TAB_PDF = rf"(?i:{spaced('table')})"  # an old scan's text layer may read "table i;"
CAP_WORD = rf"(?:{FIG_PDF}|{TAB_PDF})"


def norm_label(n):
    """The label as the locator uses it: "[3]" (PNAS) -> "3"; ints -> str."""
    s = str(n).strip()
    m = re.fullmatch(r"\[\s*(.+?)\s*\]", s)
    return m.group(1) if m else s


def caption_title_text(t):
    """A caption (label removed) cut to its title: the first sentence (up to the first ". " before an upper-case letter
    or a panel label such as "(a)"), at most 150 characters cut at a word and ending "…", < and > as ＜ and ＞."""
    t = re.sub(r"^[\s*_.:;,|—–-]+", "", t).strip()
    m = re.search(r"\.\s+(?=[A-Z]|\([a-zA-Z](?:\s*[,–-]\s*[a-zA-Z])*\))", t)
    t = re.sub(r"[\s.]*\^[a-z*∗†‡§¶]\s*$", "", (t[:m.start()] if m else t).strip())  # a footnote mark: "Brain. ^a"
    t = t.rstrip(".").strip()
    if len(t) > 150:
        t = t[:149]
        t = (t[:t.rfind(" ")] if " " in t else t).rstrip(" ,;:(") + "…"
    return t.replace("<", "＜").replace(">", "＞")


class MdTable:
    """A Markdown table caption and its HTML table (above: the table stands before the caption)."""

    def __init__(self, md, c0, c1, t0, t1, above, by_text, cap_line):
        self.md, self.c0, self.c1, self.t0, self.t1 = md, c0, c1, t0, t1
        self.above, self.by_text, self.cap_line = above, by_text, cap_line

    def start(self):
        return min(self.c0, self.t0)

    def end(self):
        return max(self.c1, self.t1)

    def group(self, k=0):
        return self.md[self.start():self.end()]


def gap(r, q):
    """Distance between two rectangles (0 when they touch or overlap): the larger of the horizontal and vertical gaps."""
    return max(0.0, q.x0 - r.x1, r.x0 - q.x1, q.y0 - r.y1, r.y0 - q.y1)


def centre_in(lr, r):
    x, y = (lr.x0 + lr.x1) / 2, (lr.y0 + lr.y1) / 2
    return r.x0 <= x <= r.x1 and r.y0 <= y <= r.y1


def is_body(rest):
    """The words after a label at the start of a Markdown line go on as a sentence, so the line is body text, not a
    caption: "Fig. 5a, b displayed ...", "Fig. 5c and d presented ...", "Figure 3 shows ..." (a caption: "Fig. 5(a) A
    second ...", "Fig. 1 a Schematic ...", "Figure 3. ...", "Fig. 3 pH dependence ...")."""
    r = re.sub(r"^[*_]+", "", rest)
    if re.match(r"[a-zA-Z]?\)", r):  # "(Fig. 2g), supporting ..." wrapped onto a new line
        return True
    r = re.sub(r"^[A-Z](?=[\s,–-]|$)", "", r)  # a panel letter right after the number: "Fig. 3A shows"
    r = re.sub(r"^(?:[\s,]*(?:and\s+|&\s*)?(?:\([a-zA-Z](?:\s*[,–-]\s*[a-zA-Z])*\)|[a-z](?:\s*[–-]\s*[a-z])?)(?=[\s,)]|$))*", "", r)
    return bool(re.match(r"[\s,]*[a-z]{2,}\b", r))


GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε", "varepsilon": "ε", "zeta": "ζ", "eta": "η",
         "theta": "θ", "vartheta": "θ", "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
         "rho": "ρ", "varrho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ",
         "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
         "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "times": "×", "pm": "±", "mp": "∓", "cdot": "·", "approx": "≈",
         "sim": "~", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "neq": "≠", "ne": "≠", "infty": "∞", "circ": "°",
         "degree": "°", "partial": "∂", "nabla": "∇", "to": "→", "rightarrow": "→", "leftarrow": "←", "prime": "′",
         "ldots": "…", "dots": "…", "cdots": "…", "propto": "∝", "ell": "ℓ", "AA": "Å", "%": "%", "&": "&", "#": "#"}
SUP = str.maketrans("0123456789+-−=()n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻⁼⁽⁾ⁿ")
SUB = str.maketrans("0123456789+-−=()", "₀₁₂₃₄₅₆₇₈₉₊₋₋₌₍₎")


def _script(t, table, mark):
    t = t.strip()
    return t.translate(table) if t and all(c in "0123456789+-−=()" + ("n" if mark == "^" else "") for c in t) else t


def latex_text(m):
    """Inline LaTeX as readable text: Greek letters and symbols as characters, \\frac{a}{b} as a/b, digits raised or
    lowered as Unicode super- and subscripts, other commands and braces dropped."""
    m = re.sub(r"\\(?:text|textrm|mathrm|mathit|mathbf|mathsf|mathcal|mathbb|rm|it|bf|operatorname)\s*\{([^{}]*)\}",
               lambda x: x.group(1).strip().replace(" ", "\u00a0"), m)
    m = re.sub(r"\\([A-Za-z]+)(?![A-Za-z])", lambda x: GREEK.get(x.group(1), x.group(0) + "\x00"), m)  # before spaces go
    m = re.sub(r"\s+", "", m)  # spacing inside math is the converter's, not the author's
    for _ in range(3):
        m = re.sub(r"\\[dt]?frac\x00\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2", m)
        m = re.sub(r"\\sqrt\x00\{([^{}]*)\}", r"√\1", m)
        m = re.sub(r"\^\{([^{}]*)\}|\^([^\\{}\x00])", lambda x: "^" + _script(x.group(1) or x.group(2), SUP, "^"), m)
        m = re.sub(r"_\{([^{}]*)\}|_([^\\{}\x00])", lambda x: "_" + _script(x.group(1) or x.group(2), SUB, "_"), m)
    m = re.sub(r"\\([A-Za-z]+\x00?|[%&#])", lambda x: GREEK.get(x.group(1).rstrip("\x00"), ""), m)
    m = re.sub(r"[{}\x00]|\\[,;:!> ]", "", m)
    m = re.sub(r"\^(?=[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ°′])|_", "", m)  # k_D -> kD, 37^° -> 37°; e^x keeps its caret
    m = re.sub(r"\s*([=<>≤≥≈≠×±])\s*", r" \1 ", m)
    return m.replace("\u00a0", " ").strip()


def clean_caption(s):
    """Caption text from the Markdown without its markup: images, HTML tags (<sup>2</sup> as ²), emphasis (**, _),
    Markdown escapes and $...$ math (as readable text, latex_text)."""
    s = IMG.sub(" ", s)
    s = re.sub(r"<sup>([^<]*)</sup>", lambda x: _script(x.group(1), SUP, "^"), s, flags=re.I)
    s = re.sub(r"<sub>([^<]*)</sub>", lambda x: _script(x.group(1), SUB, "_"), s, flags=re.I)
    s = re.sub(r"</?[A-Za-z][^<>]*>", "", s)
    s = re.sub(r"(?<!\\)\$\$?((?:\\\$|[^$])*?)(?<!\\)\$\$?", lambda x: latex_text(x.group(1)), s)
    s = re.sub(r"(?<!\\)\*+|(?<![\w\\])_+(?=\S)|(?<=\S)_+(?!\w)", "", s)
    s = re.sub(r"\\([*_#\[\]()$%&])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()
MATH_WORDS = {"cos", "sin", "tan", "cot", "sec", "csc", "exp", "log", "erf", "erfc", "sinh", "cosh", "tanh", "coth",
              "sech", "csch", "max", "min", "lim", "sup", "inf", "arg", "det", "div", "grad", "curl"}
GAP_PT = 13  # a blank band this tall ends an equation frame (inside the 90 equations of the rc tests: at most 11.5 pt)
NOTE_MARKS = "*∗⁎†‡§¶"  # table footnote marks


def is_roman(n):
    return bool(re.fullmatch(r"[IVXLC]+", str(n)))


def num_re(n):
    """A printed label in the PDF text: OCR reads 1 as I or l and 0 as O; a Roman numeral in either case (an old
    scan's text layer reads "Table ii") and not cut short; an appendix label's dot may be missing ("B1" for B.1)."""
    n = str(n)
    if is_roman(n):
        return "".join(f"[{c}{c.lower()}]" for c in n) + "(?![IVXLCivxlc])"
    out = ""
    for i, c in enumerate(n):  # an Elsevier math font reads the dot as a colon: "ð2:31Þ", "ðA:11Þ" (Kapellos 2007)
        if c == ".":
            out += "[.:]?" if i == 1 and n[0].isalpha() else "[.:]"
        else:
            out += {"1": "[1Il]", "0": "[0Oo]"}.get(c, re.escape(c))
    return out


def md_label(n):
    """A label in the Markdown, not followed by more of a longer label (Fig. 1 is not Fig. 12; Table V not VI)."""
    return re.escape(str(n)) + ("(?![IVXLC])" if is_roman(n) else r"(?![\d.]\d|\d)")


def tag_re(n):
    """MinerU's \\tag of equation n: \\tag{3}, \\tag {3}., \\tag{3),}, \\tag{[3]} (PNAS), \\tag{B.1}, \\tag{\\mathrm{B.1}}."""
    body = r"\s*".join(re.escape(c) for c in str(n))
    return (rf"\\tag\s*\{{\s*(?:\\(?:mathrm|text|textrm|rm)\s*\{{)?\s*[\[(]?\s*{body}\s*[\])]?\s*\}}?\s*\)?[.,]*\s*\}}")


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
        self._stream, self._ink, self._gray, self._onecol, self._rows = {}, {}, {}, {}, {}
        self._scale = None  # MinerU crop pixels per page point: one value per document, found with the first figure
        self._mdl = self._after = None
        self._why = {}  # (kind, label, caption) -> why the last attempt to locate it failed (why_unlocated)

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

    def caption_line(self, word, n, text=None):
        """The caption line "Fig. 7." / "FIG. 7 —" / "TABLE IV." / "Table 1" / "F I G U R E 1" / "table ii;" (page,
        rect), not a sentence citing it. A caption word that the text layer sets apart from the rest ("FIG.", a
        small-caps "table" on a slightly different baseline) is joined with the pieces to its right. A line inside a
        prose paragraph ("... in\\nTable 1 are within ...") is returned only when no other line matches.
        text: the caption's own words from the Markdown, for a caption whose label the converter dropped: the PDF
        line holding their start (a label printed before them is taken in)."""
        same_row = lambda a, b: abs(a.y0 - b.y0) < 2.5 or min(a.y1, b.y1) - max(a.y0, b.y0) > 0.6 * min(a.height, b.height)
        head = rf"^(?:{word})\s?\.?,?\s*{num_re(n)}"  # "F IG . 7 ." in small caps too
        fallback = None
        for pattern in (head + r"\s*[.:;—–|-]", head + r"\b" if not is_roman(n) else head):
            for pi in range(self.doc.page_count):
                lines = self.stream(pi)[4]
                for lr, ws in lines:
                    text_, rect = " ".join(t for t, _ in ws), pymupdf.Rect(lr)
                    if any(same_row(o, lr) and lr.x0 - 10 < o.x1 <= lr.x0 for o, _ in lines):
                        continue  # not at the start of its line: "... shown in Fig. 7. From this ..."
                    if re.match(rf"^(?:{word})\s?\.?,?$", text_):
                        for o, ows in sorted((x for x in lines if same_row(x[0], lr) and x[0].x0 > lr.x1), key=lambda x: x[0].x0):
                            if o.x0 - rect.x1 > 60:
                                break
                            text_, rect = text_ + " " + " ".join(t for t, _ in ows), rect | o
                    m = re.match(pattern, text_)
                    if m and not self.in_paragraph(pi, rect, text_[m.end():]):
                        return pi, rect
                    fallback = fallback or (m and (pi, rect))
        if fallback is None and text:
            return self.caption_by_text(text)
        return fallback or (None, None)

    def caption_by_text(self, text):
        """(page, rect) of the PDF line where a caption's own words (from the Markdown) start, or (None, None)."""
        words = words_of(clean_caption(text), 8, False)
        if len(words) < 12:
            return None, None
        loc, _ = self.locate(words)
        if not loc:
            loc, _ = self.snap(words, 0.85)
        if not loc:
            return None, None
        pi, lines = loc["page"], self.stream(loc["page"])[4]
        lr = pymupdf.Rect(lines[loc["lines"][0]][0])
        for o, ows in lines:  # a label printed before the words on the same line ("Table 1 Elastic moduli ...")
            if abs((o.y0 + o.y1) - (lr.y0 + lr.y1)) / 2 < 0.3 * min(o.height, lr.height) and o.x1 <= lr.x0 + 1 and lr.x0 - o.x1 < 60:
                lr |= o
        for o, ows in lines:  # or on a line of its own just above ("Table 1" over "Elastic moduli ...")
            if (0 <= lr.y0 - o.y1 < o.height and self.same_col(pi, o, lr) and o.width < 120
                    and re.match(rf"(?:{CAP_WORD})\s?\.?,?\s*[A-Z]?\d", " ".join(t for t, _ in ows))):
                lr |= o
        return pi, lr

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

    # ---------- Markdown captions ----------
    def md_lines(self):
        """Markdown lines with every image link on a line of its own (Marker writes "![](…)**Figure 18.** …" on one
        line): [(text, offset in the Markdown)]."""
        if self._mdl is None:
            out, pos = [], 0
            for l in self.md.split("\n"):
                last = 0
                for m in IMG.finditer(l):
                    if l[last:m.start()].strip():
                        out.append((l[last:m.start()], pos + last))
                    out.append((m.group(0), pos + m.start()))
                    last = m.end()
                if l[last:].strip() or last == 0:
                    out.append((l[last:], pos + last))
                pos += len(l) + 1
            self._mdl = out
        return self._mdl

    def md_cap(self, kind, s, n=None):
        """Match of a figure/table label (n, or any) at the start of Markdown line s: "Fig. 7", "**Figure 7.**",
        "F I G U R E 7", "TAB L E 3", "TABLE1Representative ..." (words run together)."""
        if kind == "figure":
            lab = md_label(n) if n is not None else r"(?:[A-Z]\.?)?\d{1,3}(?:\.\d{1,3})?[a-z]?(?![\d.]\d|\d)"
            return re.match(rf"\s*[*_]*\s*(?:{FIG_MD})\s*[*_]*\.?\s*(?:{lab})", s, re.I)
        lab = md_label(n) if n is not None else r"(?:[A-Z]\.?)?\d{1,3}(?:\.\d{1,3})?[a-z]?(?![\d.]\d|\d)|[IVXLC]{1,6}\b"
        return re.match(rf"\s*[*_]*\s*(?:{TAB_MD})\s*[*_]*\.?\s*(?:{lab})", s)

    def md_caption_at(self, kind, s, n=None):
        """The label match when Markdown line s is a caption of figure/table n (or any): the label at its start and
        no sentence going on after it ("Fig. 5a, b displayed the ...", "Figure 3 shows ..." are body text)."""
        m = self.md_cap(kind, s, n)
        return m if m and not is_body(s[m.end():]) else None

    def md_caption_by_text(self, caption, kind=None, n=None):
        """Index of the Markdown line that holds the caption text given by a reading (a verbatim start of it, at least 15
        characters; for a caption whose label the converter dropped), or None when it is missing or not unique, or when
        that line is the caption of another figure or table ("Figure 2. ..." given for Figure 1)."""
        key = compact(norm_text(clean_caption(caption or "")))[0].lower()
        if len(str(caption or "").strip()) < 15 or len(key) < 10:
            return None
        L = self.md_lines()
        hits = [i for i, (s, _) in enumerate(L)
                if not IMG.fullmatch(s.strip()) and key in compact(norm_text(clean_caption(s)))[0].lower()]
        if len(hits) != 1:
            return None
        if kind and n is not None and (self.md_cap("figure", L[hits[0]][0]) or self.md_cap("table", L[hits[0]][0])) \
                and not self.md_cap(kind, L[hits[0]][0], n):
            return None
        return hits[0]

    def _walk(self, i, step, prose=0, next_rule=True):
        """Images next to Markdown line i, walking up (step -1) or down (+1) over panel labels, short label text and
        Marker's chart descriptions ("A: x: t/T_0, 0.0-1.0; y: ..."), up to the next caption or prose line (prose:
        how many prose lines may be passed). Returns ([(path, offset)] in Markdown order, why the walk stopped:
        "figure"/"table" (a caption), "prose", "end"; next_rule: images directly followed by another figure's caption
        are that figure's and are not returned)."""
        L = self.md_lines()
        found, j, passed, stop = [], i + step, 0, "end"
        while 0 <= j < len(L):
            s = L[j][0].strip()
            m = IMG.fullmatch(s)
            if m:
                found.append((m.group(1), L[j][1]))
            elif s:
                kind = "figure" if self.md_cap("figure", s) else "table" if self.md_cap("table", s) else None
                if kind:
                    if step > 0 and found and next_rule and kind == "figure":
                        return [], "figure", j  # the images of the next figure
                    stop = kind
                    break
                if len(s) > 100 and not (s.startswith("(") or re.match(r"[a-z]\)", s) or CHART.search(s)):  # not "(a) ..."
                    if passed >= prose or found:
                        stop = "prose"
                        break
                    passed += 1
            j += step
        return (found[::-1] if step < 0 else found), stop, j

    def after_doc(self):
        """True when this Markdown mostly puts a figure's image after its caption (Tokita 2018): more captions have
        images only after them than only before them."""
        if self._after is None:
            before = after = 0
            for i, (s, _) in enumerate(self.md_lines()):
                if self.md_caption_at("figure", s):
                    up, dn = bool(self._walk(i, -1)[0]), bool(self._walk(i, 1, next_rule=False)[0])
                    before += up and not dn
                    after += dn and not up
            self._after = after > before
        return self._after

    def caption_run(self, i):
        """The Markdown lines of the figure captions standing one after the other with line i, with nothing but blank
        lines or short label text between them (Neacsu 2025: "Fig. 10 ...", "Fig. 9 ..." under one image)."""
        L, run = self.md_lines(), [i]
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(L):
                s = L[j][0].strip()
                if self.md_caption_at("figure", s):
                    run.append(j)
                elif IMG.fullmatch(s) or (s and (len(s) > 100 or self.md_cap("table", s))):
                    break
                j += step
        return sorted(run)

    def figure_images(self, n, caption=None):
        """MinerU's (or Marker's) images of figure n, all panels: the images just before its caption line(s), skipping
        panel labels, short label text and chart descriptions the converter wrote between them ("(a) ...", "colorbar:
        4 to 20", "panel (a) x: ...; y: ..."; several "Fig. 5(a)", "Fig. 5(b)" captions add up); else the images just
        after the caption (a caption above its figure), unless another figure's caption follows them; else images above
        the caption with a few prose lines between (Koens 2020). A Markdown that mostly puts images after their captions
        (Tokita 2018) is read the other way round. Unclaimed images near the caption (a panel the converter set apart
        by a paragraph, Xu 2024) are returned as extra candidates. caption: the caption's text, for a caption whose
        label the converter dropped. Returns (paths in Markdown order, Markdown offset of the first, whether each panel
        has its own caption, the caption's Markdown line index, extra candidate paths, why none were found or None)."""
        L = self.md_lines()
        caps = [i for i, (s, _) in enumerate(L) if self.md_caption_at("figure", s, n)]
        if not caps and caption:
            i = self.md_caption_by_text(caption, "figure", n)
            caps = [i] if i is not None else []
        if not caps:
            return [], 0, False, None, [], None
        after = self.after_doc()

        def num(j):  # the figure number of a caption line, without a panel letter
            m = self.md_cap("figure", L[j][0])
            k = m and re.search(r"((?:[A-Za-z]\.?)?\d+(?:\.\d+)?)[A-Za-z]?$", m.group(0))
            return k and k.group(1).upper()

        def images(i, extra=True):
            run = [j for j in self.caption_run(i) if num(j) != num(i)] if num(i) else []
            if run:  # captions of other figures directly before or after this one
                run = sorted(run + [i])
                up, dn = self._walk(run[0], -1)[0], self._walk(run[-1], 1, next_rule=not after)[0]
                if len(run) == 2 and up and dn:  # "image, caption A, caption B, image": A takes the one above
                    return (up if i == run[0] else dn), None
                if up or dn:
                    others = ", ".join(repr(L[j][0].strip()[:14]) for j in run if j != i)
                    return [], (f"the Markdown sets this caption next to {others} with no image between them, so which "
                                "image belongs to which figure is unknown")
            if after:
                w = self._walk(i, 1, next_rule=False)[0]
                if w:
                    return w, None
                w, stop, _ = self._walk(i, -1)
                return (w if stop not in ("figure", "table") else []), None  # just after another caption: its images
            w = self._walk(i, -1)[0] or self._walk(i, 1)[0]
            if w or not extra:
                return w, None
            # a few prose lines between the images and the caption (Koens 2020 Fig. 3): not the images just under a
            # table caption, nor those under a figure caption that has no images of its own above it
            w, stop, j = self._walk(i, -1, prose=6)
            if stop == "table" or (stop == "figure" and not self._walk(j, -1)[0]):
                return [], None
            return w, None

        panel = re.compile(rf"\s*[*_]*\s*(?:{FIG_MD})\s*[*_]*\.?\s*{md_label(n)}\s*\(?[a-z]\)?(?![a-z])", re.I)  # "Fig. 5(a) ...", "Fig. 5b ..."
        groups = [(i,) + images(i) for i in caps]
        first = next(((i, w) for i, w, _ in groups if w), None)
        per_panel = bool(first and panel.match(L[first[0]][0]))
        if per_panel:  # one caption per panel: all panels' images
            found = [x for i, w, _ in groups if panel.match(L[i][0]) for x in w]
        elif first:  # the first captioned figure; a later "Fig. n" may belong to another article in the same PDF
            found = first[1]
        else:
            why = next((y for _, _, y in groups if y), None)
            return [], 0, False, caps[0], [], why
        cap_i = first[0]
        # images near the caption that no caption claims: panels the converter set apart by a paragraph
        claimed = {off for j, (s, _) in enumerate(L) if self.md_caption_at("figure", s) and j != cap_i
                   for _, off in images(j)[0]} | {off for _, off in found}
        near = []
        for step in (-1, 1):
            j, k = cap_i + step, 0
            while 0 <= j < len(L) and k < 40:
                s = L[j][0].strip()
                if s and not IMG.fullmatch(s) and (self.md_cap("figure", s) or self.md_cap("table", s)):
                    break
                m = IMG.fullmatch(s)
                if m and L[j][1] not in claimed:
                    near.append((m.group(1), L[j][1]))
                j, k = j + step, k + 1

        def existing(items):
            paths, seen = [], set()
            for p, off in items:
                path = self.md_path.parent / urllib.parse.unquote(p)
                if path not in seen and path.exists():
                    seen.add(path)
                    paths.append((path, off))
            return paths

        paths = existing(found)
        extra = [p for p, _ in existing(near) if p not in {q for q, _ in paths}]
        return [p for p, _ in paths], (paths[0][1] if paths else 0), per_panel, cap_i, extra, None

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
        word its own piece). [(rect, words in reading order)] from top to bottom."""
        if pi in self._rows:
            return self._rows[pi]
        rows = []
        for lr, ws in sorted(self.stream(pi)[4], key=lambda x: (round(x[0].y0 / 2.5), x[0].x0)):
            if rows and abs(rows[-1][0].y0 - lr.y0) < 2.5 and lr.x0 - rows[-1][0].x1 < 30:
                rows[-1] = (rows[-1][0] | lr, rows[-1][1] + ws)
            else:
                rows.append((pymupdf.Rect(lr), list(ws)))
        self._rows[pi] = [(r, sorted(ws, key=lambda w: w[1].x0)) for r, ws in rows]
        return self._rows[pi]

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

    def _fail(self, key, why):
        self._why[key] = why
        return None

    def figure(self, n, caption=None, dpi=60):
        """Frame of figure n: its Markdown images (all panels) template-matched on the page, widened to the ink touching
        them. caption: a verbatim start of the caption text as it stands in the Markdown, for a caption whose label
        the converter dropped or garbled. None (with why_unlocated) when the images are unknown or the frame would be
        wrong: panels missing, other figures' captions or body text inside it (figure_problem)."""
        n = norm_label(n)
        key = ("figure", n, caption)
        self._why.pop(key, None)
        paths, md_off, per_panel, cap_i, extra, why = self.figure_images(n, caption)
        if not paths:
            return self._fail(key, why) if why else None
        tpls = [np.asarray(PIL.Image.open(p).convert("L"), float) / 255 for p in paths]
        order = sorted(range(len(tpls)), key=lambda i: -tpls[i].size)  # the largest panel matches most reliably
        anchor = order[0]
        # the caption line ("Fig. 7." / "FIG. 7 —"), not a sentence such as "Figure 7 shows ..." on another page
        L = self.md_lines()
        cap_text = None if self.md_cap("figure", L[cap_i][0], n) else L[cap_i][0]
        cap_pi, cap = self.caption_line(FIG_PDF, n, text=cap_text)
        N = self.doc.page_count
        guess = md_off / max(1, len(self.md)) * N  # other pages: nearest the figure's place in the Markdown first
        rest = sorted((p for p in range(N) if p != cap_pi), key=lambda p: abs(p + 0.5 - guess))
        ranges = ([np.arange(self._scale - 0.08, self._scale + 0.081, 0.02)] if self._scale else []) + [np.arange(1.2, 4.4, 0.04)]
        best = (-1.0, None, None, None)
        for scales in ranges:  # the scale found for an earlier figure of this paper first; MinerU uses one per document
            for pages, stop in (([cap_pi] if cap_pi is not None else []), None), (rest, 0.85):
                if pages and pages[0] == cap_pi and len(tpls) > 1:  # on the caption's page another large panel may
                    for a in order:                                 # anchor the match (Antoine 2014: the largest image
                        if a != order[0] and tpls[a].size < 0.25 * tpls[order[0]].size:  # was Fig. 9's, on another page)
                            break
                        b = self.match(tpls[a], pages, scales, dpi)
                        if b[0] > best[0] and (a == order[0] or b[0] >= 0.8):
                            best, anchor = b, a
                        if best[0] >= 0.6:
                            break
                else:
                    b = self.match(tpls[anchor], pages, scales, dpi, stop)
                    if b[0] > best[0]:
                        best = b
                if best[0] >= 0.6:  # found on the caption's page; otherwise search the other pages
                    break
            if best[0] >= 0.6:
                break
        if best[1] is None:
            return None
        best = max(best, self.match(tpls[anchor], [best[1]], np.arange(best[2] - 0.04, best[2] + 0.041, 0.005), dpi), key=lambda b: b[0])
        score, pi, s, _ = best
        def on_page(q):  # a caption of this figure on page q, not "Figure 10 provides ..." (Antoine 2014)
            for lr, ws in self.stream(q)[4]:
                t = " ".join(w for w, _ in ws)
                m = re.match(rf"(?:{FIG_PDF})\s?\.?,?\s*{num_re(n)}\b", t)
                if m and not self.in_paragraph(q, lr, t[m.end():]):
                    return True
            return False
        captioned = cap is not None and re.match(rf"(?:{FIG_PDF})\s?\.?,?\s*{num_re(n)}\s*[.:;—–|-]", " ".join(
            t for lr, ws in self.stream(cap_pi)[4] if lr.intersects(cap) for t, _ in ws))  # a caption, not "(Fig. 1) d/a"
        if score < 0.6 or (captioned and pi != cap_pi and score < 0.85 and not on_page(pi)):
            return None  # off its caption's page, a close match only: not another figure's image
        self._scale = s
        f = 72 / dpi
        box = lambda b: pymupdf.Rect(b[3][0] * f, b[3][1] * f, (b[3][0] + b[3][2]) * f, (b[3][1] + b[3][3]) * f)
        boxes, missing, small, elsewhere = {anchor: box(best)}, [], 0, 0
        near_scale = np.arange(s - 0.01, s + 0.011, 0.005)
        for i, t in enumerate(tpls):  # the other panels, on the same page and at the same scale
            if i != anchor:
                b = self.match(t, [pi], near_scale, dpi)
                # separately captioned panels in the other column have body text between them: leave them out
                if b[0] >= 0.7 and (not per_panel or self.same_col(pi, box(b), box(best))):
                    boxes[i] = box(b)
                elif not per_panel and t.size >= 0.05 * tpls[anchor].size:  # a tiny image (a logo) may be off the page
                    # an image found on another page is another figure's (Buchanan 2014: Fig. 6's panels above "FIG. 7")
                    if self.match(t, [q for q in range(N) if q != pi], near_scale, dpi, stop=0.85)[0] >= 0.85:
                        elsewhere += 1
                    else:
                        missing.append(i)
        main = max(boxes.values(), key=lambda r: r.width * r.height)
        P = self.doc[pi].rect
        margin = lambda r: (r.x0 + r.x1) / 2 < 0.1 * P.width or (r.x0 + r.x1) / 2 > 0.9 * P.width or r.y1 < 0.08 * P.height or r.y0 > 0.92 * P.height
        for i, r in list(boxes.items()):  # a publisher's logo or licence badge in the margin is not a panel (Mollenkopf
            others = [q for j, q in boxes.items() if j != i]  # 2025): far smaller than the figure, apart from it, in the margin
            if others and r.width * r.height < 0.05 * main.width * main.height and min(gap(r, q) for q in others) > 40 and margin(r):
                del boxes[i]
                small += 1
        far = 0
        rows = self.text_rows(pi)
        caps = [lr for lr, ws in rows if re.match(rf"(?:{CAP_WORD}|Scheme|SCHEME|Chart|Movie)\s?\.?,?\s*(?:[A-Z]\.?)?\d", " ".join(t for t, _ in ws))]
        cb = self.caption_block(pi, cap) if cap is not None and cap_pi == pi else None
        raw = pymupdf.Rect(main)
        for r in boxes.values():
            raw |= r
        for p in extra:  # a panel the converter set apart from the caption by a paragraph (Xu 2024 Fig. 5, Fig. 8)
            t = np.asarray(PIL.Image.open(p).convert("L"), float) / 255
            b = self.match(t, [pi], near_scale, dpi)
            if b[1] is None:  # too large or too small for the page at this scale
                continue
            e = box(b)
            # below or above a caption that it does not stand over, it is not this figure's (Mestre 2020 Fig. 3 and
            # the images of its "Movie 5" beside it; Chen 2004: Fig. 6, whose label the converter garbled)
            if cb is not None and (cb.y0 > raw.y1 - 5 or cb.y1 < raw.y0 + 5) and min(e.x1, cb.x1) - max(e.x0, cb.x0) < 0.3 * e.width:
                continue
            if b[0] >= 0.7 and min(gap(e, q) for q in boxes.values()) <= 30:
                boxes[len(tpls) + extra.index(p)] = e
            elif b[0] >= 0.85 and t.size >= 0.05 * tpls[anchor].size and not any(e.intersects(q) for q in boxes.values()) \
                    and (e & raw).get_area() < 0.5 * e.get_area():
                # on this page, but other things lie between it and the frame (Kaushik 2021 Fig. 5 panel D); not when a
                # caption or body text lies between them: then it is another figure's (Guarino 2015 Fig. 4 and Fig. 5)
                U = pymupdf.Rect(main) | e
                between = lambda lr: centre_in(lr, U) and not centre_in(lr, main) and not centre_in(lr, e)
                prose = [lr for lr, ws in rows if between(lr) and lr.width >= 100 and self.is_prose(ws)]
                if not any(between(lr) for lr in caps) and len(prose) < 2:
                    far += 1
        raw = pymupdf.Rect(main)
        for r in boxes.values():
            raw |= r
        panels = sum(1 for i in boxes if i < len(tpls))
        rect = self.grow(pi, self.tighten(pi, raw + (-3, -3, 3, 3)) or raw)
        area = lambda r: max(0.0, r.width) * max(0.0, r.height)
        for info_ in self.doc[pi].get_image_info():  # a raster figure ends where its image does, light edges included
            B = pymupdf.Rect(info_["bbox"]) & self.doc[pi].rect  # (Kobrin: a pale outline the ink test does not see)
            if area(B) < 0.6 * area(self.doc[pi].rect) and any(area(B & q) >= 0.85 * area(q) and area(B) <= 1.3 * area(q)
                                                               for q in boxes.values()):
                rect |= B
        # a running head (author, page, a rule, the journal's logo) is not the figure's, though the ink of a figure set
        # at the top of the page reaches it (Belcher 2023, Kaushik 2021, Tang 2025)
        H, top_box = self.doc[pi].rect.height, min(b.y0 for b in boxes.values())
        head = ([lr.y1 for lr, _ in self.stream(pi)[4] if lr.y0 < 0.05 * H and lr.y1 < top_box - 2]
                + [d["rect"].y1 for d in self.doc[pi].get_drawings() if d["rect"].y1 < min(0.06 * H, top_box - 2)])
        if head and rect.y0 < max(head) < top_box:
            rect.y0 = max(head) + 0.5
        lines = self.stream(pi)[4]
        cb = self.caption_block(pi, cap) if cap is not None and cap_pi == pi else None
        # a paragraph of body text; the caption below the figure is none (Anderson 1991: an axis title just above it)
        para = lambda lr: any(o is not lr and self.is_prose(ows) and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0
                              and not (cb and centre_in(o, cb)) and not re.match(rf"(?:{CAP_WORD})\s?\.?,?\s*[A-Z]?\d", ows[0][0] + " " + (ows[1][0] if len(ows) > 1 else ""))
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
        if len(tpls) > 1 or extra:
            info["panels"] = f"{panels} of {len(tpls)}" + (f" (+{len(boxes) - panels} set apart in the Markdown)" if len(boxes) > panels else "")
        if small:
            info["left_out"] = f"{small} small image(s) far from the figure (a logo?)"
        if cap is not None and cap_pi == pi:
            info["caption_gap_pt"] = round(cap.y0 - rect.y1, 1)
        if elsewhere:
            info["panels"] += f"; {elsewhere} found on other pages, left out"
        still = []
        for i in missing:  # an image matched only weakly, inside the frame anyway (a crop the converter recoloured)
            b = self.match(tpls[i], [pi], near_scale, dpi)
            if not (b[1] is not None and b[0] >= 0.45 and (box(b) & rect).get_area() >= 0.8 * box(b).get_area()):
                still.append(i)
        missing = still
        if missing:
            return self._fail(key, f"only {panels} of the {len(tpls)} Markdown images of Figure {n} were found on page {pi + 1}, so a frame "
                                   "would leave panels out (or the images belong to more than one figure)")
        if far:
            return self._fail(key, f"{far} more Markdown image(s) near the caption of Figure {n} lie on page {pi + 1} apart from the "
                                   "matched panels (with text or tables between), so a frame would leave panels out")
        why = self.figure_problem(pi, rect, list(boxes.values()), n, cap if cap_pi == pi else None)
        if why:
            return self._fail(key, why)
        return self.region(pi, rect, info)

    def other_captions(self, pi, rect, kind, n):
        """Caption lines of other figures and tables ("Fig. 6.", "Table 2") with their centre in rect."""
        out = []
        for lr, ws in self.text_rows(pi):
            t = " ".join(w for w, _ in ws)
            m = re.match(rf"(?:({FIG_PDF})|{TAB_PDF})\s?\.?,?\s*((?:[A-Z]\.?)?\d{{1,3}}(?:\.\d{{1,3}})?|[IVXLCivxlc]+\b)[a-z]?"
                         r"(?:\s*[.:;—–|-]|\s+(?=[A-Z(]))", t)  # "Fig. 6." or Springer's "Fig. 6 Transport ..."
            if not m or not centre_in(lr, rect) or self.in_paragraph(pi, lr, t[m.end():]):
                continue
            same = (kind == "figure") == bool(m.group(1)) and re.sub(r"\.", "", m.group(2)).lower() == re.sub(r"\.", "", str(n)).lower()
            if not same:
                out.append(t[:20])
        return out

    def figure_problem(self, pi, rect, boxes, n, cap):
        """Why a figure frame is wrong, or None: it takes in another figure's or a table's caption (a converter image
        holding two figures, Manneschi 2016), or body text that lies outside the matched images (panels or a logo
        joined across a paragraph, Mollenkopf 2025)."""
        caps = self.other_captions(pi, rect, "figure", n)
        if caps:
            return (f"the frame would take in the caption {caps[0]!r} of another figure or table (the converter's image "
                    "holds more than this figure, or belongs to another one)")
        rows = [lr for lr, ws in self.text_rows(pi) if centre_in(lr, rect) and lr.width >= 120 and self.is_prose(ws)
                and not any(centre_in(lr, b + (-2, -2, 2, 2)) for b in boxes)]
        body = [lr for lr in rows if any(o is not lr and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0.5 * min(o.width, lr.width)
                                          and -0.5 * lr.height < max(o.y0 - lr.y1, lr.y0 - o.y1) < 0.8 * lr.height for o in rows)]
        if len(body) >= 2:
            return f"the frame would cover {len(body)} lines of text (body text or a caption) between the images it joins"
        return None

    # ---------- numbered equations ----------
    def page_map(self, pi):
        """What page pi holds by the locator's own rules, for a page map: {"captions": ["Fig. 3", "Table 2", ...],
        "equations": ["4", "2.31", ...]}. A caption starts its line and is followed by a separator or a capitalised
        word, not by a sentence ("Fig. 1, such a ..." is a cross-reference); an equation number stands at the right edge
        of its column (a list item "(3) pseudo click ..." or a symbol "(E0)" ending a text line is none)."""
        caps, eqs = [], []
        for lr, ws in self.text_rows(pi):
            t = " ".join(w for w, _ in ws)
            m = re.match(rf"(?:({FIG_PDF})|{TAB_PDF})\s?\.?,?\s*((?:[A-Z]\.?)?\d{{1,3}}(?:\.\d{{1,3}})?[a-z]?|[IVXLCivxlc]+\b)"
                         r"(?:\s*[.:;—–|-]|\s+(?=[A-Z(])|\s*$)", t)
            if m and not self.in_paragraph(pi, lr, t[m.end():]):
                caps.append(f"{'Fig.' if m.group(1) else 'Table'} {m.group(2)}")
        o, c = ("[\\[(�ð]", "[\\])�Þ]") if self.bracketed() else ("[(�ð]", "[)�Þ]")
        for lr, ws in self.stream(pi)[4]:
            for t, r in ws:
                m = re.fullmatch(rf"{LEADER}{o}({_NUM}){c}", t)
                if m:
                    c0, c1 = self.column(pi, r)
                    if r.x1 > c1 - 25 and (len(ws) <= 2 or lr.x0 > c0 + 30):
                        eqs.append(m.group(1).replace(":", "."))
        return {"captions": caps, "equations": eqs}

    def bracketed(self):
        """True when the Markdown tags equations with square brackets, as PNAS prints them: \\tag{[2a]}."""
        return bool(re.search(r"\\tag\s*\{\s*\[", self.md))

    def number_tokens(self, n):
        """[(page, rect)] of the printed equation number (n) standing at the right of its column ("[n]" too in a paper
        whose equation numbers are bracketed)."""
        n = norm_label(n)
        o, c = ("[\\[(�ð]", "[\\])�Þ]") if self.bracketed() else ("[(�ð]", "[)�Þ]")
        cands = []
        for pi in range(self.doc.page_count):
            for lr, ws in self.stream(pi)[4]:
                for t, r in ws:
                    if re.fullmatch(rf"{LEADER}{o}{num_re(n)}{c}", t):  # text layers may give "(4)" as �4� or ð4Þ
                        c0, c1 = self.column(pi, r)
                        if r.x1 > c1 - 25 and (len(ws) <= 2 or lr.x0 > c0 + 30):
                            cands.append((pi, r))
        return cands

    def equation(self, n, caption=None):
        """Frame of the numbered equation n (caption is ignored: equations have none). None (with why_unlocated) when
        it is not found or the frame would be wrong (equation_problem)."""
        n = norm_label(n)
        key = ("equation", n, caption)
        self._why.pop(key, None)
        NUM = NUM_TOKEN_SQ if self.bracketed() else NUM_TOKEN
        b = next((b for b in re.finditer(r"\$\$(.*?)\$\$", self.md, re.S)  # MinerU writes \tag{3}, \tag {3}. or \tag{3),}
                  if re.search(tag_re(n), b.group(1))), None)
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
                   if re.fullmatch(NUM, t) and self.same_col(pi, r, ref) and r.x1 > c1 - 25] + ([ref] if len(cands) == 1 else [])
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
                    if re.fullmatch(NUM, t) and r != ref
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
        num = ref if len(cands) == 1 else None
        body = self.body_lines(pi, rect, beside, c0, c1)
        if body:  # lines of text at the frame's top or bottom edge only, such as "where: D_i = mutual diffusion
            level = lambda a, q: abs((a.y0 + a.y1) - (q.y0 + q.y1)) / 2 < 0.3 * min(a.height, q.height)  # coefficient ..."
            rest = [lr for lr, _ in self.stream(pi)[4] if centre_in(lr, rect) and not any(level(lr, q) for q in body)]  # (Gehrke
            if True:                                                                                # 1997 Eq. 7): cut off
                mid = (rect.y0 + rect.y1) / 2  # an equation set as a picture has no text lines of its own
                top_, bot_ = (min(lr.y0 for lr in rest), max(lr.y1 for lr in rest)) if rest else (mid, mid)
                above = [lr for lr in body if lr.y1 <= top_ + 1]
                below = [lr for lr in body if lr.y0 >= bot_ - 1]
                if len(above) + len(below) == len(body):
                    cut = self.tighten(pi, pymupdf.Rect(rect.x0, max([rect.y0] + [lr.y1 + 0.5 for lr in above]),
                                                        rect.x1, min([rect.y1] + [lr.y0 - 0.5 for lr in below])))
                    if cut and cut.height >= 8 and (num is None or (cut.y0 <= num.y0 + 1 and cut.y1 >= num.y1 - 1)):
                        rect = cut
        why = self.equation_problem(pi, rect, b.group(1) if b else None, num, beside, c0, c1)
        if why:
            return self._fail(key, why)
        return self.region(pi, rect, {"number_found": len(cands) == 1})

    def body_lines(self, pi, rect, beside, c0, c1):
        """Lines of body text with their centre in an equation frame (not the words beside an equation number)."""
        return [lr for lr, ws in self.stream(pi)[4] if centre_in(lr, rect) and self.is_prose(ws) and not beside(lr)
                and lr.width > 0.4 * (c1 - c0) and len(re.findall(r"[a-z]{3,}", " ".join(t for t, _ in ws).lower())) >= 4]

    def equation_problem(self, pi, rect, tex, num, beside, c0, c1):
        """Why an equation frame is wrong, or None: it covers body text or the other column's equation (a frame across
        both columns, Sykova 2008 Eqs. 13 and 14); the equation goes on beyond its edge across the column gap (an equation
        set across both columns framed on its numbered half, Su 2023 Eq. 23); the Markdown equation has several lines but
        the frame is about one text line high (Hegde 2022 Eq. 10, Urrea-Quintero 2024 Eq. 39)."""
        lines, W = self.stream(pi)[4], self.doc[pi].rect.width
        prose_h = sorted(lr.height for lr, ws in lines if self.is_prose(ws) and lr.width > 100)
        h = prose_h[len(prose_h) // 2] if prose_h else 10.0
        inside = [(lr, ws) for lr, ws in lines if centre_in(lr, rect)]
        body = self.body_lines(pi, rect, beside, c0, c1)
        if body:
            return f"the frame would cover {len(body)} line(s) of body text (a frame across both columns?)"
        mid = W / 2
        near = [lr for lr, ws in lines if not centre_in(lr, rect) and self.is_prose(ws) and lr.width > 0.25 * W
                and len(re.findall(r"[A-Za-z]{3,}", " ".join(t for t, _ in ws))) >= 4
                and rect.y0 - 4 * h < lr.y1 and lr.y0 < rect.y1 + 4 * h]
        two_col = any(lr.x1 < mid for lr in near) and any(lr.x0 > mid for lr in near)  # body text in both columns around it
        if rect.x0 < mid - 10 and rect.x1 > mid + 10 and two_col:  # two equations side by side, nothing between them
            left = [lr for lr, _ in inside if lr.x1 < mid]
            right = [lr for lr, ws in inside if lr.x0 > mid and not re.fullmatch(NUM_TOKEN_SQ, " ".join(t for t, _ in ws))]
            if left and right and not any(lr.x0 < mid < lr.x1 for lr, _ in inside):
                return "the frame would span both columns and take in what stands in the other column at the same height"
        for lr, ws in lines:  # the equation goes on across the column gap, beyond the frame
            if self.is_prose(ws) or min(lr.y1, rect.y1) - max(lr.y0, rect.y0) < 0.5 * lr.height:
                continue
            if re.fullmatch(NUM_TOKEN_SQ, " ".join(t for t, _ in ws).strip()):  # the printed number itself, a little wider
                continue                                                           # than its ink (Vrentas 1975 Eqs. 8, 10)
            cut = lr.x0 < rect.x0 - 3 < rect.x0 + 3 < lr.x1 or lr.x0 < rect.x1 - 3 < rect.x1 + 3 < lr.x1  # a line the edge cuts
            lo, hi = self.column(pi, lr)
            if cut or (not centre_in(lr, rect) and (
                    (lr.x1 <= rect.x0 + 1 and rect.x0 - lr.x1 < 12 and lr.x1 > hi + 2) or
                    (lr.x0 >= rect.x1 - 1 and lr.x0 - rect.x1 < 12 and lr.x0 < lo - 2))):
                return "the equation goes on beyond the frame's edge across the column gap (an equation set across both columns?)"
        if tex:
            body_tex = re.sub(r"\\tag\s*\{.*?\}\s*$", "", tex.strip(), flags=re.S)
            rows = 1 + len(re.findall(r"\\\\(?!\s*(?:\\end\s*\{|$))", body_tex))
            if rows >= 2 and rect.height < max(1.6, 0.85 * rows) * h:
                return (f"the Markdown equation has {rows} lines but the frame is about one text line high "
                        f"({rect.height:.0f} pt): it would show part of the equation only")
        return None

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

    def md_table(self, n, caption=None):
        """The Markdown caption of table n ('Table n', 'T A B L E n', 'TAB L E n'; or the line holding the caption text
        a reading gives) and its HTML table: below it, after at most 3 short lines (a title, Marker's '---' rule and blank
        lines between), or else directly above it (Scientific Reports prints tables above their captions). MdTable or
        None."""
        L = self.md_lines()
        idx = [i for i, (s, _) in enumerate(L) if self.md_cap("table", s, n)]
        idx = sorted(idx, key=lambda i: not self.md_caption_at("table", L[i][0], n))  # captions before body lines
        by_text = False
        if not idx and caption:
            i = self.md_caption_by_text(caption, "table", n)
            idx, by_text = ([i] if i is not None else []), True
        stop = lambda s: (self.md_cap("table", s) or self.md_cap("figure", s) or s.startswith("$$") or IMG.fullmatch(s)
                          or len(s) > 400)
        for above in (False, True):
            for i in idx:
                j, k, step = i + (-1 if above else 1), 0, -1 if above else 1
                while 0 <= j < len(L) and k <= (2 if above else 3):
                    s = L[j][0].strip()
                    if (not above and s.startswith("<table")) or (above and s.endswith("</table>")):
                        start = L[j][1] if not above else self.md.rfind("<table", 0, L[j][1] + len(L[j][0]))
                        m = re.compile(r"<table.*?</table>", re.S).match(self.md, start)
                        if m:
                            return MdTable(self.md, L[i][1], L[i][1] + len(L[i][0]), m.start(), m.end(), above, by_text, L[i][0])
                        break
                    if stop(s) or s.startswith("<"):
                        break
                    k += bool(s) and not re.fullmatch(r"[-*_ ]{3,}", s)  # Marker's '---' rules and blank lines are free
                    j += step
        return None

    def table(self, n, caption=None):
        """Frame of table n: from its caption over its rows to its last rule (when the table has rules), with the
        footnotes right below it whole; as wide as its rules or rows, which can exceed the text column. A table printed
        above its caption is framed from its first row to the caption's end. caption: a verbatim start of the caption
        text as it stands in the Markdown, for a caption whose label the converter dropped. None (with why_unlocated)
        when the frame would be wrong (table_problem)."""
        n = norm_label(n)
        key = ("table", n, caption)
        self._why.pop(key, None)
        tm = self.md_table(n, caption)
        if not tm:
            return None
        pi, cap = self.caption_line(TAB_PDF, n, text=tm.cap_line if tm.by_text else None)
        if cap is None:
            return None
        # a row: most of its words are words of the Markdown table and its caption
        cells = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", tm.group(0)).lower()))
        toks = lambda ws: re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", " ".join(t for t, _ in ws).lower())
        is_row = lambda ws: toks(ws) and sum(t in cells for t in toks(ws)) >= 0.5 * len(toks(ws))
        if tm.above:
            r = self.table_above(pi, cap, tm, is_row)
            why = r if isinstance(r, str) else self.table_problem(pi, r[0], cap, is_row, tm, n, True, r[1])
            return self._fail(key, why) if why else self.region(pi, r[0], r[1])
        r = self.table_below(pi, cap, tm, is_row, toks)
        if r is None:
            return None
        why = self.table_problem(pi, r[0], cap, is_row, tm, n, False, r[1])
        return self._fail(key, why) if why else self.region(pi, r[0], r[1])

    def caption_block(self, pi, cap):
        """The caption line cap with the lines continuing it right below (line gaps under half a line)."""
        cb = pymupdf.Rect(cap)
        for lr, _ in sorted(self.stream(pi)[4], key=lambda x: x[0].y0):
            if lr.y0 <= cb.y1 - 0.5 * lr.height or not self.same_col(pi, lr, cap) or min(lr.x1, cb.x1) - max(lr.x0, cb.x0) <= 0:
                continue
            if lr.y0 - cb.y1 > 0.5 * lr.height:
                break
            cb |= lr
        return cb

    def table_above(self, pi, cap, tm, is_row):
        """(rect, info) of a table printed above its caption line cap: its rows and rules from the caption up to the
        text before the table (the Markdown paragraph before it, or the first wide prose line that is not a row), with
        the whole caption; or why it cannot be framed."""
        lines = self.stream(pi)[4]
        cb = self.caption_block(pi, cap)
        c0, c1 = self.column(pi, cap, robust=False)
        c0, c1 = min(c0, cap.x0 - 4), max(c1, cap.x1 + 4)
        prev = ([p for p in self.md[:tm.t0].split("\n\n") if p.strip() and not p.strip().startswith(("$", "\\", "<", "!["))] or [""])[-1]
        loc = self.locate(words_of(re.sub(r"^#+\s*", "", prev.strip()), 6, True))[0] if prev.strip() else None
        lim = 0.06 * self.doc[pi].rect.height
        if loc and loc["page"] == pi:
            pl = lines[loc["lines"][-1]][0]
            if pl.y1 < cap.y0 and self.same_col(pi, pl, cap):
                lim = pl.y1
        rows = sorted((x for x in self.text_rows(pi) if x[0].y0 > lim - 1 and x[0].y1 <= cap.y0 + 1
                       and min(x[0].x1, c1) - max(x[0].x0, c0) > 0.5 * x[0].width), key=lambda x: -x[0].y0)
        got, found = None, 0
        for lr, ws in rows:  # upwards from the caption
            t = " ".join(w for w, _ in ws)
            if re.match(rf"(?:{CAP_WORD})\s?\.?,?\s*(?:[A-Z]?\d|[IVXLC]+\b)", t):
                break
            note = t[:1] in NOTE_MARKS or re.match(r"(?:[a-z]|Notes?\b)\s", t)
            if lr.width > 0.6 * (c1 - c0) and self.is_prose(ws) and not is_row(ws) and not note:
                break
            found += bool(is_row(ws))
            got = pymupdf.Rect(lr) if got is None else got | lr
        if not found:
            return f"no row of the Markdown table above its caption on page {pi + 1}"
        rules = [r for r in self.rules(pi, max(lim, got.y0 - 3 * cap.height), cap.y0)
                 if min(r.x1, got.x1) - max(r.x0, got.x0) > 0.5 * min(r.width, got.width)]
        frame = got | cb
        for r in rules:
            frame |= r
        rect = self.tighten(pi, frame + (-2, -1, 2, 1))
        return (rect, {"caption_below": True, **({"rules": len(rules)} if rules else {})}) if rect else f"the frame of the table came out empty"

    def table_problem(self, pi, rect, cap, is_row, tm, n, above=False, info=None):
        """Why a table frame is wrong, or None: no row of the Markdown table in it (the caption line found is body text
        that starts with "Table 2.", Bayat 2021)."""
        cb = self.caption_block(pi, cap)
        # (a row touching the caption line is the caption's: "TABLE 3" and its title joined across the page, Slyker 2022)
        rows = [lr for lr, ws in self.text_rows(pi) if centre_in(lr, rect) and not centre_in(lr, cb) and not lr.intersects(cap)
                and is_row(ws)]
        if not rows and not (info or {}).get("rules"):
            return (f"no row of the Markdown table lies under the caption line found on page {pi + 1} in the PDF text (a table "
                    f"set as a picture, or a line of body text that starts with 'Table {n}'?)")
        if (info or {}).get("left_out_beside"):  # Foudazi 2023 Table 3: two of three columns
            return f"the table goes on beside the frame ({info['left_out_beside']} lines of its words next to its rows), so columns would be left out"
        lines = self.stream(pi)[4]
        inside = [lr for lr, ws in lines if centre_in(lr, rect) and not centre_in(lr, cb)]
        if not inside:
            return None
        h = sorted(lr.height for lr in inside)[len(inside) // 2]
        # body text inside the frame: wide prose lines in body-text size that are no rows, below the table's first row
        # (the caption may go on beside the rows, Budday 2020), in a paragraph; a footnote's lines are smaller
        prose_h = sorted(lr.height for lr, ws in lines if self.is_prose(ws) and lr.width > 100)
        body_h = prose_h[len(prose_h) // 2] if prose_h else h
        row_y = min((lr.y0 for lr in rows), default=rect.y0)
        notes = [lr.y0 for lr, ws in self.text_rows(pi) if centre_in(lr, rect) and (ws[0][0][:1] in NOTE_MARKS or re.match(r"Notes?\b", ws[0][0]))]
        body = [lr for lr, ws in self.text_rows(pi) if centre_in(lr, rect) and not centre_in(lr, cb) and lr.width > 0.6 * rect.width
                and lr.y0 > row_y and lr.y0 < min(notes, default=1e9) - 1 and lr.height > 0.92 * body_h
                and self.is_prose(ws) and not is_row(ws)]
        if any(o is not lr and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0.5 * lr.width and abs(o.y0 - lr.y0) < 1.6 * h
               for lr in body for o in body):
            return f"the frame would cover {len(body)} lines of body text"
        # rows going on below the frame (Ozel 2021: the converter left the last rows out of the Markdown table): a line
        # just below with three or more cells standing in the frame's columns, two of them numbers, across half its width
        edges = [v for lr in inside for v in (lr.x0, lr.x1)]
        below = [(lr, " ".join(t for t, _ in ws)) for lr, ws in lines if rect.y1 - 1 < lr.y0 < rect.y1 + 1.5 * h
                 and lr.x0 >= rect.x0 - 2 and lr.x1 <= rect.x1 + 2 and lr.width < 100]
        for lr, _ in below:
            row = [(o, t) for o, t in below if abs((o.y0 + o.y1) - (lr.y0 + lr.y1)) / 2 < 0.3 * h
                   and any(abs(o.x0 - e) < 3 or abs(o.x1 - e) < 3 for e in edges)]
            if (len(row) >= 3 and sum(bool(re.fullmatch(r"[−\-+±]?[\d.,]+%?", t.strip())) for _, t in row) >= 2
                    and max(o.x1 for o, _ in row) - min(o.x0 for o, _ in row) > 0.5 * rect.width):
                return f"the table goes on below the frame (rows the Markdown table lacks), on page {pi + 1}"
        return None

    def table_below(self, pi, cap, tm, is_row, toks):
        """(rect, info) of a table below its caption line cap (see table), or None."""
        cells = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", self.md[tm.t0:tm.t1]).lower()))
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
        # a raster figure below the table ends it (Marshall 2017: the panels' edges read as rules), unless the table
        # holds pictures itself
        P = self.doc[pi].rect
        imgs = [] if "<img" in tm.group(0) else [
            B for B in (pymupdf.Rect(i["bbox"]) & P for i in self.doc[pi].get_image_info())
            if 400 < B.width * B.height < 0.6 * P.width * P.height and B.y0 > cap.y1 + 2
            and min(B.x1, c1) - max(B.x0, c0) > 0.5 * min(B.width, c1 - c0)
            and any(cap.y1 < lr.y0 and lr.y1 < B.y0 and is_row(ws) for lr, ws in self.text_rows(pi))  # not a table set as a picture
            and sum(1 for lr, ws in self.text_rows(pi) if centre_in(lr, B) and is_row(ws)) < 2]  # nor a shading behind rows (Gunko 2017)
        bot = min([bot] + [B.y0 for B in imgs])
        # the first wide text line below that is not a table row; pieces of one visual line are joined first (old scans
        # give every word its own piece)
        segs = sorted((x for x in self.stream(pi)[4] if cap.y1 < x[0].y0 < bot and self.same_col(pi, x[0], cap)),
                      key=lambda x: (round(x[0].y0 / 2.5), x[0].x0))
        rows = []
        for lr, ws in segs:  # one visual line: a small-caps "table" a little below "iii: Labeling ..." joins it (Margolis)
            q = rows[-1][0] if rows else None
            if q and (abs(q.y0 - lr.y0) < 2.5 or min(q.y1, lr.y1) - max(q.y0, lr.y0) > 0.6 * min(q.height, lr.height)) \
                    and lr.x0 - q.x1 < 30:
                rows[-1] = (q | lr, rows[-1][1] + ws)
            else:
                rows.append((pymupdf.Rect(lr), list(ws)))
        rows = [(r, sorted(ws, key=lambda w: w[1].x0)) for r, ws in rows]  # pieces in reading order ("table" "iii:" "Labeling")
        limit = bot
        cb = self.caption_block(pi, cap)
        # below the line that holds the Markdown table's last row, only the table's own words make a row: body text
        # there shares words with the caption (Greiner 2024 Table 6)
        tr = re.findall(r"<tr[^>]*>(.*?)</tr>", self.md[tm.t0:tm.t1], re.S)
        want = set(re.findall(r"[a-z]{3,}|\d+(?:\.\d+)?", re.sub(r"<[^>]+>", " ", tr[-1] if tr else "").lower()))
        strict = lambda ws: toks(ws) and sum(t in cells for t in toks(ws)) >= 0.5 * len(toks(ws))
        end_y = max([lr.y1 for lr, ws in rows if want and toks(ws) and sum(t in want for t in toks(ws)) >= 0.5 * len(toks(ws))
                     and not centre_in(lr, self.caption_block(pi, cap))], default=None)  # pieces of the last row's cells
        row_ok = lambda lr, ws: is_row(ws) if end_y is None or lr.y0 < end_y + 1 else strict(ws)
        for lr, ws in sorted(rows, key=lambda x: x[0].y0):  # the footnotes are added whole below
            if centre_in(lr, cb):  # the caption's own lines
                continue
            if ((lr.width > 0.6 * (c1 - c0) and self.is_prose(ws) and not row_ok(lr, ws)) or ws[0][0][:1] in NOTE_MARKS
                    or (re.match(rf"(?:{CAP_WORD})\s?\.?,?\s*(?:[A-Z]?\d|[IVXLCivxlc]+\b)", " ".join(t for t, _ in ws))
                        and not strict(ws))):  # a cell "Fig. 5" is none (Bork 2024 Table 1)
                bot = lr.y0  # body text, a footnote, or the next table's or figure's caption (Margolis 1975 Table II)
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
            for lr, _ in self.stream(pi)[4]:  # and the caption's lines above the first rule (Budday 2020: a caption set in
                if cap.y0 - 1 < lr.y0 and lr.y1 < first.y0 + 1 and min(lr.x1, c1) - max(lr.x0, c0) > 0:  # two columns)
                    c0, c1 = min(c0, lr.x0 - 2), max(c1, lr.x1 + 2)
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
        # a table across both columns of a two-column page without rules as wide (Tang 2025 Table 2, Foudazi 2023
        # Table 3): its rows go on in the other column, and so does its caption line
        W = page.rect.width
        wide_cap = cap.x0 < W / 2 - 10 and cap.x1 > W / 2 + 10  # a caption line across the column gap
        same_row = lambda a, b: wide_cap and abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 < 0.3 * min(a.height, b.height)
        # (not into another table or figure beside it, under its own caption: Amsden 1998 Tables 3 and 4)
        others = [lr for lr, ws in self.text_rows(pi) if not lr.intersects(cap) and lr.y0 > cap.y0 - 4 * cap.height
                  and re.match(rf"(?:{CAP_WORD})\s?\.?,?\s*(?:[A-Z]?\d|[IVXLCivxlc]+\b)", " ".join(t for t, _ in ws))]
        # (nor into body text beside it, which goes on above the caption: Bork 2024 Table 1; a running head is none:
        # Foudazi 2023 "Invited Feature Article")
        above = [lr for lr, ws in self.stream(pi)[4] if cap.y0 - 3 * cap.height < lr.y1 <= cap.y0 + 1 and self.is_prose(ws)
                 and min(lr.x1, cap.x1) - max(lr.x0, cap.x0) <= 0 and lr.width >= 100 and lr.y0 > 0.07 * page.rect.height]
        band = [(lr, ws) for lr, ws in self.stream(pi)[4] if cap.y0 - 2 < lr.y0 and lr.y1 < bot + 2
                and not any(o.y1 <= lr.y0 + 1 and min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0 for o in others)]
        blocked = lambda lr: any(min(o.x1, lr.x1) - max(o.x0, lr.x0) > 0 for o in above)
        lo, hi = self.column(pi, cap)
        level = lambda a, b: abs((a.y0 + a.y1) - (b.y0 + b.y1)) / 2 < 0.3 * min(a.height, b.height)
        strong = lambda ws: len(toks(ws)) >= 3 and sum(t in cells for t in toks(ws)) >= 0.8 * len(toks(ws))
        beside = lambda lr: (lr.x1 > c1 + 1 and lr.x0 - c1 < 40) or (lr.x0 < c0 - 1 and c0 - lr.x1 < 40)
        # on the level of a row inside the frame (not of the caption's lines: Castro 2016 "0.40 %." beside them)
        by_row = lambda lr: any(level(lr, o) and c0 <= o.x0 and o.x1 <= c1 and is_row(ows) and not centre_in(o, cb) for o, ows in band)
        grown = True
        while grown:  # a cell beside the frame on the level of a cell inside it; not a line of body text
            grown = False
            near = [(lr, ws) for lr, ws in band if beside(lr) and not blocked(lr)]
            # a cell: a few words of the table itself in a column of such cells ("Low", "Wang et al. [8]": Cheng 2026,
            # Bork 2023; one heading of the next column is none: Antoine 2014 "Polymerization pH"), or a longer line
            # nearly all of whose words are the table's; body text of the next column, which shares words with the
            # caption (Vidotto 2021 Table 2), is none
            short = [i for i, (lr, ws) in enumerate(near) if len(toks(ws)) <= 3 and strict(ws) and by_row(lr)]
            column = len({round(near[i][0].y0) for i in short}) >= 2
            for i, (lr, ws) in enumerate(near):
                cell = (strong(ws) or (column and i in short)
                        or (len(toks(ws)) >= 2 and is_row(ws) and not self.is_prose(ws))) and by_row(lr)
                if cell or (same_row(lr, cap) and not re.fullmatch(r"[\d\s]+", " ".join(t for t, _ in ws))):
                    c0, c1, grown = min(c0, lr.x0 - 2), max(c1, lr.x1 + 2), True
        # what is still beside it is the table's too, but something stood in the way: the frame would leave it out
        left_out = sum(1 for lr, ws in band if beside(lr) and strong(ws) and by_row(lr))
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
        if left_out:
            info["left_out_beside"] = left_out
        return (rect, info) if rect else None

    # ---------- reasons ----------
    def why_unlocated(self, kind, n, caption=None):
        """Why figure/table/equation n was not located, for the place report: the reason the last attempt gave (a
        frame refused as wrong), else most often the converter dropped or garbled the caption label in the Markdown, so
        nothing ties the request to its images or rows."""
        n = norm_label(n)
        if (kind, n, caption) in self._why:
            return self._why[(kind, n, caption)]
        L = self.md_lines()
        name = {"figure": "Figure", "table": "Table"}.get(kind)
        if name:
            labelled = [s for s, _ in L if self.md_cap(kind, s, n)]
            if not labelled and caption and self.md_caption_by_text(caption, kind, n) is None:
                return (f"the caption text given for {name} {n} is not in the Markdown, not on one line only, or another "
                        "figure's or table's caption (give a "
                        "verbatim start of at least 15 characters)")
            if not labelled and not caption:
                return (f"the Markdown has no caption line '{name} {n}' (the converter dropped or garbled it), so its "
                        f"{'images are' if kind == 'figure' else 'rows are'} unknown; a reading can name the caption by its Markdown text")
            if labelled and not any(self.md_caption_at(kind, s, n) for s in labelled) and not caption:
                return (f"the Markdown lines starting '{name} {n}' are body text ({labelled[0].strip()[:30]!r}), "
                        f"not its caption line")
        if kind == "figure":
            if not self.figure_images(n, caption)[0]:
                return f"no Markdown image next to the caption 'Figure {n}'"
            return f"the Markdown images of Figure {n} do not match its caption's page (or match another page only weakly)"
        if kind == "table":
            if not self.md_table(n, caption):
                return f"no HTML table within 3 lines below (or directly above) the Markdown caption 'Table {n}'"
            tm = self.md_table(n, caption)
            if self.caption_line(TAB_PDF, n, text=tm.cap_line if tm.by_text else None)[1] is None:
                return f"no caption 'Table {n}' at the start of a line in the PDF text"
            return f"the frame of Table {n} came out empty"
        nums = len(self.number_tokens(n))
        tagged = re.search(tag_re(n), self.md)
        where = (f"the printed number ({n}) stands at a column's right edge {nums} times" if nums > 1 else
                 f"the printed number ({n}) was not found at a column's right edge" if not nums else
                 f"the band around the printed number ({n}) has no body-text lines above and below")
        return where + ("" if nums == 1 else ", and the text around the Markdown equation is not on one page" if tagged
                        else f", and the Markdown has no \\tag{{{n}}}")

    # ---------- caption titles ----------
    def caption_title(self, kind, n, caption=None):
        """The title of figure/table n for a frame's comment: the first sentence of the caption the locator uses, as the
        Markdown gives it (else the PDF caption line), without its label and markup; at most 150 characters (cut at a
        word, ending "…"), with < and > as ＜ and ＞. "" for equations or when there is no caption."""
        if kind not in ("figure", "table"):
            return ""
        n = norm_label(n)
        L = self.md_lines()
        if kind == "figure":
            i = self.figure_images(n, caption)[3]
        else:
            tm = self.md_table(n, caption)
            i = next((i for i, (s, o) in enumerate(L) if o == tm.c0), None) if tm else None
        if i is None:
            i = next((i for i, (s, _) in enumerate(L) if self.md_caption_at(kind, s, n)), None)
        if i is None and caption:
            i = self.md_caption_by_text(caption, kind, n)
        text = None
        if i is not None:
            m = self.md_cap(kind, L[i][0], n)
            text = clean_caption(L[i][0][m.end():] if m else L[i][0])
            if not m:  # a label garbled by markup is readable once cleaned: "Fig<sub>.</sub> 4<sub>.</sub> Human ..."
                text = re.sub(rf"^\s*(?:{FIG_MD if kind == 'figure' else TAB_MD})\s*[.,]?\s*{md_label(n)}\s*[.:,]?\s*", "", text, flags=re.I)
            if not re.sub(r"[\s*_.:;,|—–-]", "", text):  # "Table 3" alone; its title on the next line (Marker)
                nxt = next((s.strip() for s, _ in L[i + 1:i + 5] if s.strip() and not re.fullmatch(r"[-*_ ]{3,}", s.strip())), "")
                text = "" if nxt.startswith("<") or IMG.fullmatch(nxt) or self.md_cap("figure", nxt) or self.md_cap("table", nxt) \
                    else clean_caption(nxt)
        if text is None:  # the PDF caption line and the lines continuing it
            pi, cap = self.caption_line(FIG_PDF if kind == "figure" else TAB_PDF, n)
            if cap is None:
                return ""
            cb = self.caption_block(pi, cap)
            text = " ".join(t for lr, ws in self.stream(pi)[4] if centre_in(lr, cb) for t, _ in ws)
            m = re.match(rf"(?:{FIG_PDF if kind == 'figure' else TAB_PDF})\s?\.?,?\s*{num_re(n)}", text)
            text = text[m.end():] if m else text
        return caption_title_text(text)
