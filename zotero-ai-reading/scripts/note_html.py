"""The HTML of Zotero 10's "Add Note from Annotations" for one PDF, built without Zotero:
Zotero.EditorInstance.createNoteFromAnnotations(annotations, {noSave: true}) with the default note templates and the
en-US strings. Frame (image) pictures are rendered from the PDF at Zotero's 4 px per point and embedded as data URIs,
as in Zotero's unsaved note. Checked against 160 notes Zotero made in earlier runs (see the skill's tests)."""
import base64, datetime, io, json, math, re, urllib.parse

import pymupdf
from PIL import Image

JS_WS = "[\t\n\v\f\r    -     　﻿]"  # JavaScript \s
FORMATS = ("i", "b", "sub", "sup")
FRAME_SCALE = 4  # Zotero renders image annotations at 4 px per PDF point


def js_json(o):
    """JSON.stringify(o): no spaces, integral numbers without '.0', non-ASCII kept."""
    if isinstance(o, bool) or o is None:
        return json.dumps(o)
    if isinstance(o, float):
        return str(int(o)) if o.is_integer() else repr(o)
    if isinstance(o, (int, str)):
        return json.dumps(o, ensure_ascii=False)
    if isinstance(o, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + js_json(v) for k, v in o.items()) + "}"
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(js_json(v) for v in o) + "]"
    raise TypeError(type(o))


def enc(s):
    """encodeURIComponent."""
    return urllib.parse.quote(s, safe="-_.!~*'()")


def js_trim(s):
    return re.sub(f"^{JS_WS}+|{JS_WS}+$", "", s)


def round_js(x):
    """Math.round: halves round up."""
    return math.floor(x + 0.5)


def _escape(s):
    return s.replace("&", "&amp;").replace(" ", "&nbsp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_line(s):
    """walkFormat on one text node: the earliest <i>/<b>/<sub>/<sup> with a closing tag becomes an element."""
    low = s.lower()
    for fmt, start in sorted(((f, low.find(f"<{f}>")) for f in FORMATS), key=lambda x: x[1]):
        if start < 0:
            continue
        end = low.find(f"</{fmt}>", start)
        if end >= 0:
            return (_escape(s[:start]) + f"<{fmt}>" + _format_line(s[start + len(fmt) + 2:end]) + f"</{fmt}>"
                    + _format_line(s[end + len(fmt) + 3:]))
    return _escape(s)


def text_to_html(text):
    """EditorInstanceUtilities._transformTextToHTML: innerText (line breaks -> <br>), then the supported tags."""
    return "<br>".join(_format_line(line) for line in re.split(r"\r\n|\r|\n", text))


def citation_preview(item_data, locator):
    """EditorInstanceUtilities._formatCitationItemPreview (en-US)."""
    s = ""
    authors = item_data.get("author")
    if authors:
        name = lambda a: a.get("family") or a.get("literal")
        if len(authors) == 1:
            s = name(authors[0])
        elif len(authors) == 2:
            s = f"{name(authors[0])} and {name(authors[1])}"
        else:
            s = f"{name(authors[0])} et al."
    if not s and item_data.get("title"):
        s = f"“{item_data['title']}”"
    parts = (item_data.get("issued") or {}).get("date-parts") or []
    if parts and parts[0]:
        year = parts[0][0]
        if year and year != "0000":
            s += f", {year}"
    if locator:
        s += ", " + ("pp." if re.search(r"[\-–,]", locator) else "p.") + " " + locator
    return s


def annotation_json(data):
    """Zotero.Annotations.toJSON fields used by the note, from local API item JSON of an annotation."""
    a = {"id": data["key"], "type": data["annotationType"], "comment": data.get("annotationComment") or "",
         "pageLabel": data.get("annotationPageLabel", ""), "color": data.get("annotationColor"),
         "sortIndex": data.get("annotationSortIndex", ""), "position": json.loads(data["annotationPosition"]),
         "dateAdded": data.get("dateAdded", "")}
    if a["type"] in ("highlight", "underline"):
        a["text"] = data.get("annotationText") or ""
    return a


def note_order(annotations, created=()):
    """att.getAnnotations() order without ink annotations: SQL ORDER BY sortIndex, ties in creation order (item ID).
    The API has no item ID: ties go by dateAdded, then by the order of `created` (keys in the order they were written)."""
    rank = {k: i for i, k in enumerate(created)}
    return sorted((a for a in annotations if a["type"] != "ink"),
                  key=lambda a: (a["sortIndex"], a.get("dateAdded", ""), rank.get(a["id"], len(rank)), a["id"]))


def zotero_rect_to_page(page, rect):
    """Zotero annotationPosition rect (PDF user space) -> PyMuPDF page rectangle (inverse of text_locator.to_zotero)."""
    r = pymupdf.Rect(rect) * page.transformation_matrix
    r.normalize()
    return r


def render_frame(doc, annotation):
    """PNG of an image annotation's rectangle as Zotero renders it: 4 px per point, floor(4 x size) pixels."""
    page = doc[annotation["position"]["pageIndex"]]
    clip = zotero_rect_to_page(page, annotation["position"]["rects"][0])
    pix = page.get_pixmap(matrix=pymupdf.Matrix(FRAME_SCALE, FRAME_SCALE), clip=clip, alpha=False)
    w, h = math.floor(clip.width * FRAME_SCALE), math.floor(clip.height * FRAME_SCALE)
    # the pixmap is rounded outwards to whole pixels; keep the w x h pixels nearest to the exact rectangle
    dx, dy = round(clip.x0 * FRAME_SCALE % 1), round(clip.y0 * FRAME_SCALE % 1)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).crop((dx, dy, dx + min(w, pix.width - dx), dy + min(h, pix.height - dy)))
    out = io.BytesIO()
    im.save(out, "PNG")
    return out.getvalue()


def serialize(annotations, attachment_uri, parent_uri, item_data):
    """EditorInstanceUtilities.serializeAnnotations(annotations, skipEmbeddingItemData=true) for one attachment."""
    html = ""
    for a in annotations:
        if not a.get("text") and not a.get("comment") and not a.get("image") and a["type"] != "image":
            continue
        stored = {"attachmentURI": attachment_uri, "annotationKey": a["id"], "color": a["color"],
                  "pageLabel": a["pageLabel"], "position": a["position"]}
        citation_item = {"uris": [parent_uri], "locator": a["pageLabel"]}
        stored["citationItem"] = citation_item
        citation = {"citationItems": [citation_item], "properties": {}}
        formatted = f'(<span class="citation-item">{citation_preview(item_data, a["pageLabel"])}</span>)'
        citation_html = f'<span class="citation" data-citation="{enc(js_json(citation))}">{formatted}</span>'
        image_html = highlight_html = comment_html = ""
        if a.get("image"):
            rect = a["position"]["rects"][0]
            rw, rh = rect[2] - rect[0], rect[3] - rect[1]
            width = round_js(rw * 96.0 / 72.0 * 1.25)
            height = round_js(rh * width / rw)
            image_html = (f'<img class="{a["type"]}" src="{a["image"]}" width="{width}" height="{height}" '
                          f'data-annotation="{enc(js_json(stored))}"/>')
        elif a["type"] == "image":
            image_html = "[Image not available]"
        if a.get("text"):
            text = text_to_html(js_trim(a["text"]))
            highlight_html = f'<span class="{a["type"]}" data-annotation="{enc(js_json(stored))}">“{text}”</span>'
        if a.get("comment"):
            comment_html = text_to_html(js_trim(a["comment"]))
        if a["type"] in ("highlight", "underline"):
            t = f"<p>{highlight_html} {citation_html} {comment_html}</p>"
        elif a["type"] in ("note", "text"):
            t = f"<p>{citation_html} {comment_html}</p>"
        else:
            t = f"<p>{image_html}<br/>{citation_html} {comment_html}</p>"
        t = re.sub(f"{JS_WS}*(</p)", r"\1", t)
        html += re.sub(f"{JS_WS}{JS_WS}+", " ", t)
    return html


def en_us_now(now=None):
    """new Date().toLocaleString() in en-US: 10/3/2026, 11:39:52 AM."""
    d = now or datetime.datetime.now()
    return f"{d.month}/{d.day}/{d.year}, {(d.hour % 12) or 12}:{d.minute:02d}:{d.second:02d} {'AM' if d.hour < 12 else 'PM'}"


def build_note(annotations, attachment_uri, parent_uri, item_data, now=None):
    """createNoteFromAnnotations(..., {noSave: true}).getNote() for annotations of one PDF with a parent item.
    `annotations` are annotation_json() dicts in note order, with "image" (a data URI) set on image annotations."""
    html = f"<h1>Annotations<br/>({en_us_now(now)})</h1>\n"
    html += serialize(annotations, attachment_uri, parent_uri, item_data) + "\n"
    items = enc(js_json([{"uris": [parent_uri], "itemData": item_data}]))
    schema = 10 if any(a["type"] == "underline" for a in annotations) else 9
    return f'<div data-citation-items="{items}" data-schema-version="{schema}">{html}</div>'


def data_uri(png):
    return "data:image/png;base64," + base64.b64encode(png).decode()
