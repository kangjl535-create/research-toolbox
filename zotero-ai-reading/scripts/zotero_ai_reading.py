"""zotero-ai-reading: AI annotations in Zotero + BibNotes-compatible Obsidian notes for unread papers, and (--update)
additions to papers read before or with a note of their own.

Steps (each reads and writes files in one run directory):
  prepare        select papers, check them, run OCR for scans                 -> batch.json (+ existing-annotations.json)
  (agent)        write <citekey>/reading.json for each ready paper (see references/reading.md)
  place          validate readings, place highlights/regions on the PDF pages  -> <citekey>/payload.json, previews
  write          write the AI annotations and the item tag ai-draft to Zotero  -> zotero-write-result.json, undo-plan.json
  verify         compare Zotero (read-only) with what was sent
  note           make the annotation note HTML, write (or, --update, add to) and check the Obsidian notes -> report.md
  undo           (on request) move this run's AI annotations to the Zotero trash, remove the ai-draft tags it added
Only write and undo change Zotero, through the Zotero 10 local API (POST only: trashing is `deleted: 1`, never DELETE).
An existing note is only added to, never replaced (except --replace-ai-draft): the lines BibNotes keeps on update stay.
"""
import argparse, base64, collections, datetime, difflib, hashlib, json, pathlib, re, secrets, shutil, subprocess, sys, tempfile, unicodedata, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import yaml
import pymupdf, PIL.Image, PIL.ImageDraw
from zar_common import (Library, api, api_all, api_status, zotero_available, mineru_markdown, ZoteroWriter, WriteError,
                        zotero_prefs, note_format_problem,
                        COLORS, FIELDS, KEY_CHARS)
import note_html as nh
import text_locator as tl
from page_regions import Pages, render_for_ocr, ocr_alignment, LABEL

sys.stdout.reconfigure(encoding="utf-8")
MAX_BATCH = 10
AI_TAG, DRAFT_TAG = "AI", "ai-draft"
LOCATOR = "0.4.0"  # part of place's input hash: a new locator re-places papers placed by an older one
SHORT_QUOTE = 40  # characters; shorter highlights show the user only a fragment
REPEAT = 0.5  # share of a new annotation's area an existing one of the same kind covers: a repeat, not written
COLOR_NAMES = {v: k for k, v in COLORS.items()}
FIELD_END = re.compile(r"^(---\s*$|#{1,6} |%% end of note %%|\*(?:" + "|".join(FIELDS) + r")\*::)")


def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def nfc(s):
    """Zotero stores text in Unicode NFC ("ṽ" as one character); send and compare it that way."""
    return unicodedata.normalize("NFC", s)


def save(p, obj):
    pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def die(msg):
    print("STOP:", msg)
    sys.exit(1)


def library_of(batch):
    return Library(batch["library_root"], batch["vault"])


# ---------------------------------------------------------------- prepare
def run_ocr(pdf, out_json, work):
    pngs = render_for_ocr(pdf, work)
    ps = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "ocr_windows.ps1"), str(pngs), str(out_json)]
    r = subprocess.run(ps, capture_output=True, text=True)
    shutil.rmtree(pngs, ignore_errors=True)
    if r.returncode or not pathlib.Path(out_json).exists():
        raise RuntimeError("Windows OCR failed: " + (r.stderr or r.stdout)[-300:])


def note_state(note):
    """'none', 'ai-draft' (front matter says note_status: AI draft) or 'user' (any other note at that path)."""
    if not note.exists():
        return "none"
    head = note.read_text(encoding="utf-8", errors="replace")[:3000]
    return "ai-draft" if re.search(r'^note_status: "?AI draft', head, re.M) else "user"


def note_update_problem(text):
    """Why a note cannot be added to safely, or None. BibNotes's update keeps the note from 'Affiliation:' on and
    regenerates what is above it; without that line it would copy the whole old note under a new head."""
    if "\r" in text:
        return "the note has CR line endings (Obsidian writes LF only)"
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return "no YAML front matter"
    if not re.search(r"^Affiliation:", m.group(1), re.M):
        return "no 'Affiliation:' line in the front matter (a BibNotes update would copy the note under a second head)"
    return None


def kept_hash(text):
    """SHA-256 of the part of a note BibNotes keeps on update (from 'Affiliation:' on), without the generated_sha256
    line: a record of what the skill wrote, so that --replace-ai-draft can tell an untouched AI draft from an edited one."""
    lines = [l for l in kept_part(text) if not l.startswith("generated_sha256:")]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def draft_unchanged(text):
    """The note is an AI draft exactly as the skill wrote it (0.4.0 on). Drafts without the record count as changed."""
    m = re.search(r'^generated_sha256: "?([0-9a-f]{64})"?\s*$', text, re.M)
    return bool(m) and m.group(1) == kept_hash(text)


def admission(n_ai, n_user, state, update, alongside, replace_ai_draft):
    """(mode or None, skip reason) from what the paper already has: AI-tagged annotations, the user's annotations and
    an Obsidian note. prepare and write apply the same rules, so a paper listed as ready can be written."""
    if update:
        return ("update" if n_ai or n_user or state != "none" else "new"), None
    if n_ai:
        return None, (f"already AI-read ({n_ai} AI annotations" + (f", {n_user} of the user" if n_user else "")
                      + "); add to it with --update, only on request")
    if n_user and not alongside:
        return None, f"already annotated ({n_user} annotations); use --alongside or --update only on request"
    if state != "none" and not (replace_ai_draft and state == "ai-draft"):
        who = "an AI draft" if state == "ai-draft" else "the user's"
        return None, f"an Obsidian note already exists ({who}); add to it with --update, only on request"
    return "new", None


def existing_annotation(d):
    """What place, write and the reader need of an annotation already on the PDF (local API item data)."""
    try:
        pos = json.loads(d.get("annotationPosition") or "{}")
    except ValueError:
        pos = {}
    return {"key": d["key"], "by": "AI" if AI_TAG in [t["tag"] for t in d.get("tags", [])] else "user",
            "type": d.get("annotationType"), "color": COLOR_NAMES.get((d.get("annotationColor") or "").lower(), d.get("annotationColor")),
            "page": pos.get("pageIndex", -1) + 1, "pageLabel": d.get("annotationPageLabel", ""),
            "text": d.get("annotationText") or "", "comment": d.get("annotationComment") or "", "position": pos}


def cmd_prepare(a):
    if a.update and a.replace_ai_draft:
        die("--update adds to a note and --replace-ai-draft replaces one: use one of them")
    if a.update and not (a.task or "").strip():
        die('--update needs --task "<the research task or request the new reading serves>": it labels each addition')
    if a.task and re.search(r"[\n\r*<>\[\]]", a.task):
        die("--task: one line without * < > [ ] (it is shown in the note)")
    lib = Library(a.library_root, a.vault)
    run = pathlib.Path(a.run_dir)
    notes_by_name = {}  # every note of the vault by file name: a paper's note may sit in another folder than its PDF
    for p in lib.vault.rglob("*.md"):
        if p.relative_to(lib.vault).parts[0] not in (".obsidian", ".trash"):
            notes_by_name.setdefault(p.name.lower(), []).append(p)
    if not zotero_available():
        die("Zotero is not running or its local API is off (Zotero settings > Advanced > allow other applications).")
    probs = lib.bibnotes_problems()
    if probs:
        die("BibNotes set-up differs from what the notes rely on:\n  - " + "\n  - ".join(probs))
    if a.folder:
        f = pathlib.Path(a.folder)
        rel = lib.rel(f) if f.is_absolute() else f
        pairs = [(e, att, None) for e, att in lib.bbt_items_in_folder(rel)]
        if not pairs:
            die(f"no Zotero item with a PDF directly in {rel}")
    else:
        pairs = []
        for k in (a.citekey or []) + (a.item or []):
            e = lib.bbt_entry(citekey=k) or lib.bbt_entry(item_key=k)
            if not e:
                die(f"{k} is not in the Better BibTeX export")
            pairs.append((e, *lib.pdf_attachment(e)))
    items, ready = [], 0
    for e, att, why in sorted(pairs, key=lambda p: p[0].get("citationKey", "")):
        ck = e["citationKey"]
        row = {"citekey": ck, "item_key": e["itemKey"], "title": e.get("title", "")}
        items.append(row)
        if att is None:
            row.update(status="skip", reason=why); continue
        pdf_rel = lib.rel(att["path"])
        pdf = lib.root / pdf_rel if pdf_rel else None
        row.update(pdf_key=att["uri"].rsplit("/", 1)[-1], pdf=str(pdf), pdf_rel=str(pdf_rel))
        if pdf is None or not pdf.exists():
            row.update(status="skip", reason=f"PDF not found under the library root: {att['path']}"); continue
        try:
            anns = [x["data"] for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")]
            live_path = api(f"items/{row['pdf_key']}")["data"].get("path") or ""
        except Exception as ex:
            row.update(status="skip", reason=f"Zotero API: {ex}"); continue
        live_rel = lib.rel(live_path)  # None for a file stored in Zotero's own storage
        same = lambda p, q: pathlib.PureWindowsPath(nfc(str(p))).as_posix().lower() == pathlib.PureWindowsPath(nfc(str(q))).as_posix().lower()
        if live_rel is not None and not same(live_rel, pdf_rel):
            gone = not (lib.root / live_rel).exists()
            row.update(status="skip", reason=f"Zotero's PDF attachment links {live_path}, " + ("a file that does not exist (broken link)" if gone
                       else "not the file the Better BibTeX export names") + f" ({pdf_rel}): repair the link in Zotero first"); continue
        n_ai = sum(1 for x in anns if AI_TAG in [t["tag"] for t in x.get("tags", [])])
        note = lib.note_path(pdf_rel, ck)
        state = note_state(note)
        row.update(note_path=str(note), note_state=state)
        elsewhere = [p for p in notes_by_name.get(note.name.lower(), []) if p.resolve() != note.resolve()]
        if elsewhere:
            row.update(status="skip", reason=f"a note of this paper is elsewhere in the vault ({'; '.join(str(p.relative_to(lib.vault)) for p in elsewhere)}): "
                                             "move it beside the PDF first (paper-library-maintenance)"); continue
        mode, why = admission(n_ai, len(anns) - n_ai, state, a.update, a.alongside, a.replace_ai_draft)
        if not mode:
            row.update(status="skip", reason=why); continue
        if mode == "new" and state == "ai-draft" and not draft_unchanged(note.read_text(encoding="utf-8", errors="replace")):
            row.update(status="skip", reason="the AI draft was changed after the skill wrote it, or predates 0.4.0 (no record of "
                                             "what was written): it is not replaced; add to it with --update"); continue
        md, md_status = mineru_markdown(pdf)
        row.update(md=str(md) if md else None, md_status=md_status)
        if md is None or md_status.startswith("stale"):
            row.update(status="skip", reason=f"Markdown {md_status}: convert with mineru-api-batch-convert (or marker-api-batch-convert "
                                             "when MinerU is unavailable) first"); continue
        if mode == "update" and state != "none":
            try:
                prob = note_update_problem(note.read_text(encoding="utf-8"))
            except UnicodeDecodeError:
                prob = "the note is not UTF-8 text"
            if prob:
                row.update(status="skip", reason=f"the note cannot be added to safely: {prob}"); continue
        # the item tag ai-draft marks a note that is an AI draft: added for a new note only, never to a paper whose
        # note exists (the user may have removed the tag to take the paper over)
        row.update(mode=mode, draft_tag=state == "none" or mode == "new", existing={"ai": n_ai, "user": len(anns) - n_ai})
        if ready >= a.limit:
            row.update(status="later", reason=f"batch limit {a.limit}"); continue
        doc = pymupdf.open(pdf)
        row["pages"] = doc.page_count
        kind, why = tl.text_kind(doc, md.read_text(encoding="utf-8"))
        ocr = run / ck / "ocr.json"
        if kind != "text" and not ocr.exists():
            run_ocr(pdf, ocr, run / ck / "ocr_pages")
        if kind == "check":  # a publisher's OCR layer: used only where its words lie on the printed ones
            share = ocr_alignment(doc, ocr)
            kind, why = ("text" if share >= 0.8 else "scan"), f"{why}, {share:.0%} of its words on the printed ones"
        row.update(kind=kind, **({"kind_why": why} if why else {}))
        if kind == "scan":
            row["ocr"] = str(ocr)
        if mode == "update":  # for the reader (what is there already) and for place (repeats are not written)
            save(run / ck / "existing-annotations.json", [existing_annotation(x) for x in anns])
        row["status"] = "ready"
        ready += 1
    batch = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "library_root": str(lib.root),
             "vault": str(lib.vault), "alongside": bool(a.alongside), "update": bool(a.update),
             "task": (a.task or "").strip(), "items": items}
    save(run / "batch.json", batch)
    for r in items:
        extra = (f"{r.get('kind', '')} {r.get('md_status', '')}" + (f" ({r['kind_why']})" if r.get("kind_why") else "")
                 if r["status"] == "ready" else r.get("reason", ""))
        if r["status"] == "ready" and r.get("mode") == "update":
            e = r["existing"]
            extra += (f" | update: {e['ai']} AI and {e['user']} user annotations, note: "
                      + {"none": "none yet (a new note is written)", "ai-draft": "AI draft", "user": "the user's"}[r["note_state"]])
        print(f"{r['status']:6s} {r['citekey']:45s} {extra}")
    print(f"ready {ready} | run dir {run}")


# ---------------------------------------------------------------- pagemap
def cmd_pagemap(a):
    """Where sections, figures, tables and numbered equations are, per PDF page (for {p.N} citations)."""
    batch = load(pathlib.Path(a.run_dir) / "batch.json")
    for row in batch["items"]:
        if row["status"] != "ready" or (a.citekey and row["citekey"] not in a.citekey):
            continue
        pages = Pages(row["pdf"], row["md"], row.get("ocr"))
        print(f"== {row['citekey']} ({row['kind']}, {pages.doc.page_count} pages)")
        for pi in range(pages.doc.page_count):
            lines = pages.stream(pi)[4]
            words = lambda ws: " ".join(t for t, _ in ws)
            heads = [words(ws)[:50] for lr, ws in lines if len(ws) >= 2 and words(ws).isupper() and len(words(ws)) > 6][:4]
            caps = [words(ws)[:14] for lr, ws in lines if re.match(r"^(Fig\.?|FIG\.?|Figure|FIGURE|Table|TABLE),?\s*(\d|[IVXLC]+\b)", words(ws))]
            eqs = [t for lr, ws in lines for t, _ in ws[-1:] if re.fullmatch(rf"\(({LABEL.pattern})\)", t)]
            first = words(lines[0][1])[:60] if lines else ""
            print(f"p.{pi + 1}: {first!r} | heads {heads} | {caps} | eqs {' '.join(eqs)}")


# ---------------------------------------------------------------- place
def compact_norm(s):
    return tl.compact(tl.norm_text(tl.clean_needle(s)))[0].lower()


def in_markdown(quote_c, md_c, min_ratio=0.95):
    """Quote (compacted) occurs in the Markdown, allowing only what conversion loses: one or two characters the
    Markdown lacks (MinerU drops letters of ligatures, "efficiency" -> "eficiency"; inline math such as "Δp" is
    stripped from it), one misread character, or punctuation. A changed, added or dropped word is not verbatim
    (feedback 2026-10-09: "The name ... two-phase" for "The term ... twin-phase" passed at 0.977)."""
    if quote_c in md_c:
        return True
    m = difflib.SequenceMatcher(None, md_c, quote_c, autojunk=False).find_longest_match(0, len(md_c), 0, len(quote_c))
    if m.size < 12:
        return False
    start = max(0, m.a - m.b)
    if difflib.SequenceMatcher(None, md_c[start:start + len(quote_c) + 5], quote_c, autojunk=False).ratio() < min_ratio:
        return False
    window = md_c[max(0, start - 10):start + len(quote_c) + 10]  # with Markdown text on both sides of the quote
    ops = [op for op in difflib.SequenceMatcher(None, window, quote_c, autojunk=False).get_opcodes() if op[0] != "equal"]
    if ops and ops[0][0] == "delete" and ops[0][1] == 0:
        ops = ops[1:]  # the Markdown text before the quote
    if ops and ops[-1][0] == "delete" and ops[-1][2] == len(window):
        ops = ops[:-1]  # and after it
    if ops and (ops[0][3] == 0 or ops[-1][4] == len(quote_c)):
        return False  # the quote's first or last characters are not the Markdown's: "A term" for "The term"
    blocks = []  # adjacent differences as one (Markdown part, quote part)
    for _, i1, i2, j1, j2 in ops:
        if blocks and blocks[-1][1] == i1 and blocks[-1][3] == j1:
            blocks[-1][1:4:2] = [i2, j2]
        else:
            blocks.append([i1, i2, j1, j2])
    for i1, i2, j1, j2 in blocks:
        md_part, q_part = window[i1:i2], quote_c[j1:j2]
        letters = sum(c.isalnum() for c in md_part)
        if not ((letters == 0 and len(q_part) <= 2) or (letters == 1 and len(q_part) == 1)):
            return False
    return True


def validate_reading(rd, md_text, all_fields=True):
    """Problems of a reading.json. all_fields=False (adding to an existing note): `fields` holds only additions, any
    subset of the six, and a reading may consist of field additions alone."""
    errs = []
    f = rd.get("fields") or {}
    if not isinstance(f, dict):
        errs.append("fields must be an object with the six field names as keys")
        f = {}
    unknown = [k for k in f if k not in FIELDS]
    if unknown:
        errs.append(f"unknown fields {unknown}; the six fields are {FIELDS}")
    for k in FIELDS:
        if k not in f and not all_fields:
            continue
        v = f.get(k)
        shape = f'field {k}: a string or {{"text": "...", "details": ["...", ...]}}; put bullet points into details'
        if isinstance(v, dict):
            extra = sorted(set(v) - {"text", "details"})
            if extra or not isinstance(v.get("text", ""), str):
                errs.append(shape + (f" (unknown keys {extra})" if extra else "")); continue
            text, details = v.get("text", ""), v.get("details", [])
        elif v is None or isinstance(v, str):
            text, details = v, []
        else:
            errs.append(shape); continue
        if not isinstance(details, list) or not all(isinstance(d, str) and d.strip() for d in details):
            errs.append(f"field {k}: details must be a list of non-empty strings")
        if all_fields and (not text or not str(text).strip()):
            errs.append(f"field {k} is empty")
        elif not all_fields and (not text or not str(text).strip()) and not details:
            errs.append(f"field {k}: an addition needs text or details (leave the field out otherwise)")
        for a, b in re.findall(r"\{p\.\s*(\d+)\s*[-–]\s*(\d+)\}", json.dumps(v, ensure_ascii=False)):
            if not 0 < int(b) - int(a) <= 2:
                errs.append(f"field {k}: page range {{p.{a}-{b}}}: cite the specific page, or a derivation over at most 3 pages")
    md_c = compact_norm(tl.strip_math(md_text))
    for i, h in enumerate(rd.get("highlights", [])):
        q, c = h.get("quote", ""), h.get("comment", "")
        if h.get("color") not in COLORS:
            errs.append(f"highlight {i}: colour must be one of {list(COLORS)}")
        if re.search(r"[<>$]", q):
            errs.append(f"highlight {i}: quote contains <, > or $ (use an image annotation instead)")
        if not c.startswith("AI："):
            errs.append(f"highlight {i}: comment must start with 'AI：'")
        if len(q) < 8 or not in_markdown(compact_norm(q), md_c):
            errs.append(f"highlight {i}: quote is not verbatim from the Markdown: {q[:60]!r}")
    for i, g in enumerate(rd.get("regions", [])):
        n = g.get("n")
        label_ok = (isinstance(n, int) and not isinstance(n, bool) and n >= 0) or (isinstance(n, str) and LABEL.fullmatch(n))
        if g.get("color") not in COLORS or g.get("kind") not in ("figure", "equation", "table") or not label_ok:
            errs.append(f"region {i}: needs colour, kind figure/equation/table and n as printed: 7, \"2.5\", \"A1\", \"12a\" "
                        f"or a Roman table number such as \"IV\"")
        if not str(g.get("comment", "")).startswith("AI："):
            errs.append(f"region {i}: comment must start with 'AI：'")
    if not rd.get("highlights") and not rd.get("regions") and (all_fields or not f):
        errs.append("no highlights or regions" + ("" if all_fields else " and no field additions"))
    return errs


def union_area(rects):
    """Area of the union of rectangles [x0, y0, x1, y1]: the line rectangles of one highlight overlap their neighbours,
    so their areas cannot simply be added (sweep over horizontal bands)."""
    rs = [r for r in rects if r[2] > r[0] and r[3] > r[1]]
    ys = sorted({v for r in rs for v in (r[1], r[3])})
    total = 0.0
    for y0, y1 in zip(ys, ys[1:]):
        cov, end = 0.0, None
        for a, b in sorted((r[0], r[2]) for r in rs if r[1] <= y0 and r[3] >= y1):
            if end is None or a > end:
                cov, end = cov + b - a, b
            elif b > end:
                cov, end = cov + b - end, b
        total += cov * (y1 - y0)
    return total


def covered_share(new_pos, old_positions):
    """Share of a new annotation's area (Zotero rectangles, PDF points) covered by existing annotations together."""
    new = new_pos.get("rects") or []
    old = [s for q in old_positions if q.get("pageIndex") == new_pos.get("pageIndex") for s in (q.get("rects") or [])]
    total = union_area(new)
    if total <= 0 or not old:
        return 0.0
    return min(1.0, union_area([[max(r[0], s[0]), max(r[1], s[1]), min(r[2], s[2]), min(r[3], s[3])] for r in new for s in old]) / total)


def overlaps(p, existing):
    """(share of the new annotation `p` that annotations of the same kind already cover together, [(share, annotation)]
    of each one covering part of it, largest first). Highlights/underlines count against highlights/underlines, frames
    against frames; a passage annotated before in pieces counts as covered."""
    kind = lambda t: "image" if t == "image" else "text" if t in ("highlight", "underline") else None
    same = [e for e in existing if kind(e.get("type")) == kind(p["type"])
            and (e.get("position") or {}).get("pageIndex") == p["position"].get("pageIndex")]
    parts = sorted(((covered_share(p["position"], [e["position"]]), e) for e in same), key=lambda x: -x[0])
    return covered_share(p["position"], [e["position"] for e in same]), [x for x in parts if x[0] > 0.02]


def new_key(used):
    while True:
        k = "".join(secrets.choice(KEY_CHARS) for _ in range(8))
        if k not in used:
            used.add(k)
            return k


def place_inputs(rp, row):
    """Hash of everything a placement depends on: the reading, Markdown, PDF, OCR, the locator version and, when
    adding to a paper, its mode and the annotations already on it."""
    h = hashlib.sha256(LOCATOR.encode())
    if row.get("mode") == "update":
        h.update(f"update {row.get('note_state')}".encode())
    existing = pathlib.Path(rp).parent / "existing-annotations.json" if row.get("mode") == "update" else None
    for p in (rp, row["md"], row["pdf"], row.get("ocr"), existing):
        if p and pathlib.Path(p).exists():
            h.update(pathlib.Path(p).read_bytes())
    return h.hexdigest()


def all_fields_needed(row):
    """A new note needs all six fields; adding to an existing note takes field additions only."""
    return row.get("mode") != "update" or row.get("note_state", "none") == "none"


def cmd_place(a):
    run = pathlib.Path(a.run_dir)
    batch = load(run / "batch.json")
    ready = [r["citekey"] for r in batch["items"] if r["status"] == "ready"]
    unknown = [k for k in (a.citekey or []) if k not in ready]
    if unknown:
        die(f"not ready papers of this run: {unknown}; ready: {ready}")
    # keys of every placed paper: new keys avoid them; a paper sharing a key with another (two parallel runs drew the same
    # key) is placed again even if unchanged, which gives it new keys
    keys = {f.parent.name: [p["key"] for p in load(f)] for f in run.glob("*/payload.json")}
    used = {k for ks in keys.values() for k in ks}
    written = set()  # papers this run has put into Zotero: their keys are fixed now
    if (run / "zotero-write-result.json").exists():
        written |= {it["citekey"] for it in load(run / "zotero-write-result.json")["items"]}
    elif (run / "undo-plan.json").exists():  # a write was cut off before recording: a paper counts if a key reached Zotero
        for it in load(run / "undo-plan.json"):
            try:
                if any(api_status(f"items/{k}?includeTrashed=1") == 200 for k in it["keys"]):
                    written.add(it["citekey"])
            except Exception:  # Zotero not reachable: keep the keys rather than risk new ones
                written.add(it["citekey"])
    for row in batch["items"]:
        if row["status"] != "ready" or (a.citekey and row["citekey"] not in a.citekey):
            continue  # with --citekey only those papers' files are written
        ck = row["citekey"]
        rp = run / ck / "reading.json"
        if not rp.exists():
            print(f"{ck}: reading.json missing"); continue
        if ck in written:
            print(f"{ck}: written to Zotero by this run, not placed again (new keys would no longer match Zotero); "
                  "to change it, read it again in a new run directory"); continue
        inputs = place_inputs(rp, row)
        old = load(run / ck / "placement.json") if (run / ck / "placement.json").exists() and (run / ck / "payload.json").exists() else {}
        shared = set(keys.get(ck, [])) & {k for c, ks in keys.items() if c != ck for k in ks}
        if old.get("inputs") == inputs and not shared:  # placing again would only change the annotation keys
            print(f"{ck}: unchanged since the last place: kept {old['placed']} annotations and their previews, dropped {len(old['dropped'])}")
            for d in old["dropped"]:
                print("   dropped:", d)
            continue
        rd = load(rp)
        md_text = pathlib.Path(row["md"]).read_text(encoding="utf-8")
        errs = validate_reading(rd, md_text, all_fields=all_fields_needed(row))
        if errs:
            print(f"{ck}: reading.json needs fixing:\n  - " + "\n  - ".join(errs)); continue
        doc = pymupdf.open(row["pdf"])
        pages = Pages(row["pdf"], row["md"], row.get("ocr"))
        ex_path = run / ck / "existing-annotations.json"
        existing = load(ex_path) if row.get("mode") == "update" and ex_path.exists() else []
        payload, dropped, previews, partial, own = [], [], {}, [], []

        def keep(p, what, color, rects):
            """A new annotation that mostly repeats annotations already on the PDF, or an earlier item of this reading,
            is dropped; a partial overlap is listed."""
            share, parts = overlaps(p, existing + own)
            if share >= REPEAT:
                names = ", ".join(f"{e['by']} {e['type']} {e['key']}" for _, e in parts[:4])
                top = parts[0][1] if parts else {"text": "", "comment": ""}
                dropped.append({**what, "repeat": [e["key"] for _, e in parts], "why": f"repeats {names} on p.{p['position']['pageIndex'] + 1} "
                                f"({share:.0%} of the new one covered): {(top['text'] or top['comment'])[:70]!r}"})
                return
            if share > 0.1:
                others = ", ".join("%s (%.0f%%)" % (e["key"], 100 * s) for s, e in parts)
                partial.append(f"{what.get('quote', what.get('region', ''))[:50]!r} overlaps {others}")
            payload.append(p)
            own.append({"key": p["key"], "by": "this reading's", "type": p["type"], "text": p["text"], "comment": p["comment"],
                        "position": p["position"]})
            previews.setdefault(p["position"]["pageIndex"], []).append((rects, color))

        for h in rd.get("highlights", []):
            loc, how = tl.place(doc, h["quote"]) if row["kind"] == "text" else pages.place_quote(h["quote"])
            if not loc:
                dropped.append({"quote": h["quote"][:120], "why": how}); continue
            page = doc[loc["page"]]
            label = (page.get_label() or str(loc["page"] + 1)) if row["kind"] == "text" else str(loc["page"] + 1)
            keep({"key": new_key(used), "type": "highlight", "text": nfc(h["quote"]), "comment": nfc(h["comment"]),
                  "color": COLORS[h["color"]], "pageLabel": label,
                  "sortIndex": tl.sort_index(page, loc["glyph_offset"], loc["rects"][0]),
                  "position": {"pageIndex": loc["page"], "rects": tl.to_zotero(page, loc["rects"])},
                  "_placed": how, "_pdf_text": loc["text"][:200]}, {"quote": h["quote"][:120]}, h["color"], loc["rects"])
        for g in rd.get("regions", []):
            r = getattr(pages, g["kind"])(g["n"])
            if not r:
                dropped.append({"region": f"{g['kind']} {g['n']}", "why": f"not located: {pages.why_unlocated(g['kind'], g['n'])}"}); continue
            page = doc[r["page"]]
            label = (page.get_label() or str(r["page"] + 1)) if row["kind"] == "text" else str(r["page"] + 1)
            keep({"key": new_key(used), "type": "image", "text": "", "comment": nfc(g["comment"]), "color": COLORS[g["color"]],
                  "pageLabel": label, "sortIndex": r["sortIndex"],
                  "position": {"pageIndex": r["page"], "rects": r["zotero_rects"]},
                  "_placed": f"{g['kind']} {g['n']}", "_check": {k: v for k, v in r.items() if k not in ("page", "rect", "zotero_rects", "sortIndex")}},
                 {"region": f"{g['kind']} {g['n']}"}, g["color"], [r["rect"]])
        payload.sort(key=lambda x: x["sortIndex"])
        save(run / ck / "payload.json", payload)
        save(run / ck / "placement.json", {"placed": len(payload), "dropped": dropped, "inputs": inputs})
        rgba = {"green": (95, 178, 54, 90), "orange": (241, 152, 55, 90), "yellow": (255, 212, 0, 90), "red": (255, 102, 102, 90), "blue": (46, 168, 229, 90)}
        for old in (run / ck).glob("preview_p*.png"):
            old.unlink()
        for pi, its in previews.items():
            pix = doc[pi].get_pixmap(dpi=90)
            im = PIL.Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            dr = PIL.ImageDraw.Draw(im, "RGBA")
            for e in existing:  # annotations already on the page: grey outline, no fill
                for z in (e["position"].get("rects") or []) if e["position"].get("pageIndex") == pi else []:
                    r = nh.zotero_rect_to_page(doc[pi], z)
                    dr.rectangle([v * 90 / 72 for v in (r.x0, r.y0, r.x1, r.y1)], outline=(110, 110, 110, 255), width=1)
            for rects, c in its:
                for r in rects:
                    dr.rectangle([v * 90 / 72 for v in (r.x0, r.y0, r.x1, r.y1)], fill=rgba[c], outline=rgba[c][:3] + (255,), width=2)
            im.save(run / ck / f"preview_p{pi + 1}.png")
        snapped = [p for p in payload if str(p["_placed"]).startswith("snapped")]
        print(f"{ck}: placed {len(payload)} (snapped {len(snapped)}), dropped {len(dropped)}; previews in {run / ck}")
        for p in snapped:  # matched to the PDF's wording, not found as typed: the ones to look at first in the previews
            print(f"   snapped ({p['_placed']}), check in preview_p{p['position']['pageIndex'] + 1}.png: {p['text'][:60]!r}")
        for d in dropped:
            print("   dropped:", d)
        for o in partial:
            print("   overlaps an existing annotation in part (written; keep it only if it adds something):", o)
        lost = sum(1 for d in dropped if "quote" in d and "repeat" not in d)
        if row["kind"] == "text" and lost >= 3 and lost > len(rd.get("highlights", [])) / 2:
            print("   most quotes are not in the PDF's text layer: if pagemap shows garbled or missing text, the layer is "
                  "unusable and the paper needed OCR; record that as a defect of prepare")
        print("   " + coverage_line(rd, payload, doc.page_count, existing))
        short = [h["quote"] for h in rd.get("highlights", []) if len(h["quote"]) < SHORT_QUOTE]
        if short:
            print(f"   short quotes (the user sees only this fragment highlighted; quote the whole clause where it carries the point): {short}")
        if not all_fields_needed(row) and all(k in (rd.get("fields") or {}) for k in FIELDS):
            print("   all six fields are given although the paper has a note: with --update they are added below the note's own "
                  "fields, so they must hold only what is new (a reading written for a new or replaced note must be rewritten)")


def coverage_line(rd, payload, n_pages, existing=()):
    """Information for the agent, never a rule: annotations by colour, frames by kind, pages covered, and pages with no
    annotation at all (new or, when adding to a paper, already there): a section skipped silently shows up there."""
    by = {c: 0 for c in COLORS}
    for x in rd.get("highlights", []) + rd.get("regions", []):
        by[x["color"]] += 1
    kinds = {}
    for g in rd.get("regions", []):
        kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
    pages = sorted({p["position"]["pageIndex"] + 1 for p in payload})
    line = (f"coverage: {', '.join(f'{c} {n}' for c, n in by.items())}; frames: "
            f"{', '.join(f'{k} {n}' for k, n in kinds.items()) or 'none'}; pages {pages} of {n_pages}")
    if existing:
        line += f"; {len(existing)} annotations already on the PDF"
    bare = sorted(set(range(1, n_pages + 1)) - set(pages) - {e["page"] for e in existing})
    if bare:
        line += f"; no annotation on pages {bare} (a section there not covered? say why in your report)"
    missing = [m for c, m in (("green", "background"), ("orange", "methods"), ("yellow", "results")) if not by[c]]
    if missing and not existing:
        line += f" (no {'/'.join(missing)} annotation: check that the paper really has none)"
    return line


# ---------------------------------------------------------------- write / undo
def placed_rows(run, batch):
    """Ready rows with a payload; stops on a payload older than its reading.json or a key used by two papers."""
    rows = [r for r in batch["items"] if r["status"] == "ready" and (run / r["citekey"] / "payload.json").exists()]
    stale = [r["citekey"] for r in rows
             if load(run / r["citekey"] / "placement.json").get("inputs") != place_inputs(run / r["citekey"] / "reading.json", r)]
    if stale:
        die(f"reading.json changed after the last successful place for {stale}: run place again and fix what it reports")
    owner = {}
    for r in rows:  # parallel place runs could draw the same key; a batch place gives the duplicates new keys
        for p in load(run / r["citekey"] / "payload.json"):
            if p["key"] in owner:
                die(f"annotation key {p['key']} appears twice ({owner[p['key']]}, {r['citekey']}): run place --run-dir <run> "
                    "once for the whole batch, which places such papers again with new keys")
            owner[p["key"]] = r["citekey"]
    return rows


def annotation_entry(p, pdf_key):
    """Local API JSON of one new AI annotation (pre-generated key, version 0 = must not exist yet)."""
    e = {"key": p["key"], "version": 0, "itemType": "annotation", "parentItem": pdf_key, "annotationType": p["type"],
         "annotationComment": p["comment"], "annotationColor": p["color"], "annotationPageLabel": p["pageLabel"],
         "annotationSortIndex": p["sortIndex"], "annotationPosition": json.dumps(p["position"], separators=(",", ":")),
         "tags": [{"tag": AI_TAG}]}
    if p["type"] == "highlight":
        e["annotationText"] = p["text"]
    return e


def readback(undo, why):
    """zotero-write-result.json for a write that stopped part-way: per paper, which planned keys Zotero has now."""
    result = {"written": datetime.datetime.now().isoformat(timespec="seconds"), "interrupted": why, "items": []}
    for it in undo:
        created, tag_added = [], None
        try:
            created = [k for k in it["keys"] if api_status(f"items/{k}?includeTrashed=1") == 200]
            tag_added = it.get("addsDraftTag", not it.get("hadDraftTag")) and DRAFT_TAG in [
                t["tag"] for t in api(f"items/{it['item']}")["data"].get("tags", [])]
        except Exception as e2:  # Zotero gone as well: verify and undo read the keys again later
            result["readback"] = f"incomplete ({type(e2).__name__}): run verify when Zotero answers"
        result["items"].append({"citekey": it["citekey"], "created": created, "tagAdded": tag_added,
                                "failed": [{"key": k, "code": "interrupted", "message": "not in Zotero when read back"}
                                           for k in it["keys"] if k not in created]})
        print(f"{it['citekey']}: {len(created)}/{len(it['keys'])} annotations in Zotero after the interruption")
    return result


def cmd_write(a, writer=None):
    run = pathlib.Path(a.run_dir).resolve()
    batch = load(run / "batch.json")
    if (run / "zotero-write-result.json").exists():
        die("this run has already written to Zotero (zotero-write-result.json); verify it, or undo it and use a new run directory for another write")
    if (run / "undo-plan.json").exists():  # an earlier write of this run was killed before it could record anything
        old = load(run / "undo-plan.json")
        if any(api_status(f"items/{k}?includeTrashed=1") == 200 for it in old for k in it["keys"]):
            save(run / "zotero-write-result.json", readback(old, "an earlier write of this run was cut off without a record"))
            die("an earlier write of this run reached Zotero but was cut off before it recorded anything; what it wrote is now in "
                "zotero-write-result.json. Do not write again: `verify` shows the state, `undo` moves it to the trash; then read "
                "the papers again in a new run directory")
        (run / "undo-plan.json").unlink()  # nothing of it reached Zotero: as if it had not run
    rows = placed_rows(run, batch)
    if not rows:
        die("nothing placed yet (run place first)")
    if len(rows) > MAX_BATCH:
        die(f"{len(rows)} papers; write at most {MAX_BATCH} per run")
    plan, undo = [], []
    for row in rows:  # every check before any change
        ck = row["citekey"]
        payload = [{k: v for k, v in p.items() if not k.startswith("_")} for p in load(run / ck / "payload.json")]
        item, att = api(f"items/{row['item_key']}")["data"], api(f"items/{row['pdf_key']}")["data"]
        if item["title"] != row["title"]:
            die(f"{ck}: the Zotero title differs from the one prepare saw ({item['title'][:60]!r}): run prepare again")
        if att.get("parentItem") != row["item_key"] or att.get("contentType") != "application/pdf":
            die(f"{ck}: {row['pdf_key']} is no longer this item's PDF attachment")
        if row.get("note_path") and note_state(pathlib.Path(row["note_path"])) != row.get("note_state", "none"):
            die(f"{ck}: the note {row['note_path']} is now {note_state(pathlib.Path(row['note_path']))!r}, prepare saw "
                f"{row.get('note_state', 'none')!r}: run prepare again with the same arguments, then place")
        if (row.get("mode") == "new" and row.get("note_state") == "ai-draft"
                and not draft_unchanged(pathlib.Path(row["note_path"]).read_text(encoding="utf-8", errors="replace"))):
            die(f"{ck}: the AI draft {row['note_path']} was changed after prepare; it is not replaced: add to it with prepare --update")
        live = [x["data"] for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")]
        n_ai = sum(1 for x in live if AI_TAG in [t["tag"] for t in x.get("tags", [])])
        mode, why = admission(n_ai, len(live) - n_ai, row.get("note_state", "none"), row.get("mode") == "update",
                              batch.get("alongside"), row.get("mode") == "new" and row.get("note_state") == "ai-draft")
        if not mode:  # the same rules as prepare: something was added to the PDF since
            die(f"{ck}: the PDF has {len(live)} annotations now: {why}")
        if row.get("mode") == "update":  # annotations added since prepare: a new one must not repeat them
            now = [existing_annotation(x) for x in live]
            rep = [f"{p['key']} repeats {', '.join(e['key'] for _, e in parts)}" for p in payload
                   for share, parts in [overlaps(p, now)] if share >= REPEAT]
            if rep:
                die(f"{ck}: annotations made after prepare would be repeated ({rep}): run prepare again with the same "
                    "arguments, then place, and check what it drops")
        used = [p["key"] for p in payload if api_status(f"items/{p['key']}") != 404]
        if used:
            die(f"{ck}: annotation keys already in use in Zotero: {used}")
        kids = [c["data"] for c in api_all(f"items/{row['item_key']}/children")]
        save(run / ck / "before.json", {"item": item, "children": kids})
        had = any(t["tag"] == DRAFT_TAG for t in item.get("tags", []))
        adds = row.get("draft_tag", True) and not had
        plan.append((ck, row, payload, item, had, adds))
        undo.append({"citekey": ck, "item": row["item_key"], "pdf": row["pdf_key"], "keys": [p["key"] for p in payload],
                     "hadDraftTag": had, "addsDraftTag": adds})
    entries, owner = [], []
    for ck, row, payload, item, had, adds in plan:
        for p in payload:
            entries.append(annotation_entry(p, row["pdf_key"])); owner.append((ck, p["key"]))
        if adds:  # the item's own tags are sent back as read (with their types), plus ai-draft
            entries.append({"key": row["item_key"], "version": item["version"], "tags": item.get("tags", []) + [{"tag": DRAFT_TAG}]})
            owner.append((ck, None))
    save(run / "undo-plan.json", undo)  # before the change: undo works even if the write is interrupted
    writer = writer or ZoteroWriter()
    try:
        outcome = writer.post_items(entries)
    except Exception as e:  # rejected, timed out or cut off
        if getattr(writer, "reached", 1) == 0:  # no request reached Zotero (access denied, API off, Zotero closed)
            (run / "undo-plan.json").unlink(missing_ok=True)
            die(f"nothing was written ({type(e).__name__}: {str(e)[:200]}): fix that and run write again")
        result = readback(undo, f"{type(e).__name__}: {e}")  # earlier requests may have been applied
        save(run / "zotero-write-result.json", result)
        done, total = sum(len(i["created"]) for i in result["items"]), sum(len(it["keys"]) for it in undo)
        die(f"the write was interrupted ({type(e).__name__}: {str(e)[:200]}); Zotero has {done} of the {total} annotations of this "
            "run (zotero-write-result.json; a request that timed out may still be saved by Zotero: wait a minute before "
            "`verify`). Do not run write again: `verify` shows the state, `undo` moves what was written to the trash; then "
            "read the papers again in a new run directory")
    result = {"written": datetime.datetime.now().isoformat(timespec="seconds"), "items": []}
    for ck, row, payload, item, had, adds in plan:
        mine = [(k, o) for (c, k), o in zip(owner, outcome) if c == ck]
        created = [k for k, o in mine if k and o[0] == "ok"]
        failed = [{"key": k or row["item_key"], **o[1]} for k, o in mine if o[0] == "failed"]
        tag_added = adds and any(k is None and o[0] == "ok" for k, o in mine)
        result["items"].append({"citekey": ck, "created": created, "tagAdded": tag_added, "failed": failed})
        tag = ("added" if tag_added else "already there" if had else "NOT added" if adds
               else "not added (the paper has a note: ai-draft marks new AI notes only)")
        print(f"{ck}: {len(created)}/{len(payload)} annotations written, ai-draft tag {tag}")
        for f in failed:
            print(f"   - FAILED {f['key']}: {f['code']} {f['message']}")
    save(run / "zotero-write-result.json", result)
    if any(i["failed"] for i in result["items"]):
        sys.exit(1)


def cmd_undo(a, writer=None):
    """Move this run's AI annotations to the Zotero trash and remove the ai-draft tags it added. Nothing else."""
    run = pathlib.Path(a.run_dir).resolve()
    up = run / "undo-plan.json"
    if not up.exists():
        die("undo-plan.json not found: this run has not written to Zotero")
    plan = load(up)
    if getattr(a, "citekey", None):
        unknown = [k for k in a.citekey if k not in [it["citekey"] for it in plan]]
        if unknown:
            die(f"not papers this run wrote: {unknown}")
        plan = [it for it in plan if it["citekey"] in a.citekey]
    entries, owner, state = [], [], {}
    for it in plan:
        for k in it["keys"]:
            if api_status(f"items/{k}?includeTrashed=1") != 200:
                state[k] = "never created"; continue  # the plan is saved before the write
            d = api(f"items/{k}?includeTrashed=1")["data"]
            if d.get("parentItem") != it["pdf"] or AI_TAG not in [t["tag"] for t in d.get("tags", [])]:
                state[k] = "not ours"
                print(f"{it['citekey']}: {k} is not this run's AI annotation any more, left alone"); continue
            if d.get("deleted"):
                state[k] = "already in the trash"; continue
            state[k] = "to trash"
            entries.append({"key": k, "version": d["version"], "deleted": 1}); owner.append(it["citekey"])
        item = api(f"items/{it['item']}")["data"]
        tags = item.get("tags", [])
        if it.get("addsDraftTag", not it["hadDraftTag"]) and any(t["tag"] == DRAFT_TAG for t in tags):
            entries.append({"key": it["item"], "version": item["version"], "tags": [t for t in tags if t["tag"] != DRAFT_TAG]})
            owner.append(it["citekey"])
            state[it["item"]] = "tag to remove"
    if entries:
        writer = writer or ZoteroWriter()
        try:
            outcome = writer.post_items(entries)
        except WriteError as e:
            die(str(e))
        for c, e, o in zip(owner, entries, outcome):
            if o[0] == "failed":
                print(f"{c}: FAILED {e['key']}: {o[1]['code']} {o[1]['message']}")
    batch = load(run / "batch.json") if (run / "batch.json").exists() else {"items": []}
    for it in plan:
        trashed = [k for k in it["keys"] if state.get(k) in ("to trash", "already in the trash")
                   and api(f"items/{k}?includeTrashed=1")["data"].get("deleted")]
        left = [k for k in it["keys"] if state.get(k) == "to trash" and k not in trashed]
        never = [k for k in it["keys"] if state.get(k) == "never created"]
        still = any(t["tag"] == DRAFT_TAG for t in api(f"items/{it['item']}")["data"].get("tags", []))
        adds = it.get("addsDraftTag", not it["hadDraftTag"])
        tag = "still on the item" if still else "removed" if state.get(it["item"]) else "was not on the item"
        print(f"{it['citekey']}: {len(trashed)}/{len(it['keys'])} AI annotations in the Zotero trash (restorable there)"
              + (f", {len(never)} not in Zotero (never written, or a cut-off request Zotero has not saved yet: run undo "
                 "again later)" if never else "")
              + (f", NOT trashed: {left}" if left else "") + (f", ai-draft tag {tag}" if adds else ""))
        row = next((r for r in batch["items"] if r["citekey"] == it["citekey"]), {})
        if row.get("note_written") and pathlib.Path(row["note_written"]).exists():
            print(f"   the note {row['note_written']} and its pictures stay in the vault: move them out (do not delete) if they should go")
        if row.get("note_updated"):
            print(f"   this run added to the note {row['note_updated']}; its text before is in "
                  f"{run / it['citekey'] / 'note-before.md'}: restore it by hand if wanted (the note may have been edited since)")


# ---------------------------------------------------------------- verify
def cmd_verify(a):
    run = pathlib.Path(a.run_dir)
    batch = load(run / "batch.json")
    rp = run / "zotero-write-result.json"
    if not rp.exists():
        die("zotero-write-result.json not found: run write first")
    res = {r["citekey"]: r for r in load(rp)["items"]}
    ok_all = True
    for row in batch["items"]:
        ck = row["citekey"]
        if ck not in res:
            if row["status"] == "ready" and (run / ck / "payload.json").exists():
                print(f"{ck}: PROBLEMS (placed but not in the write result)")
                ok_all = False
            continue
        sent = {p["key"]: p for p in load(run / ck / "payload.json")}
        live = {x["data"]["key"]: x["data"] for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")}
        problems = [f"write failed for {f['key']}: {f['code']} {f['message']}" for f in res[ck].get("failed", [])]
        if set(res[ck].get("created", [])) != set(sent):
            problems.append(f"write result lists {len(res[ck].get('created', []))} of {len(sent)} annotations as written")
        for k, p in sent.items():
            z = live.get(k)
            if not z:
                problems.append(f"{k} missing"); continue
            pos = json.loads(z["annotationPosition"])
            for name, ok in (("type", z["annotationType"] == p["type"]), ("text", nfc(z.get("annotationText") or "") == nfc(p["text"])),
                             ("comment", nfc(z["annotationComment"] or "") == nfc(p["comment"])), ("color", z["annotationColor"] == p["color"]),
                             ("position", pos == p["position"]), ("tag", [t["tag"] for t in z["tags"]] == [AI_TAG])):
                if not ok:
                    problems.append(f"{k} {name} differs")
        before = load(run / ck / "before.json")
        now = api(f"items/{row['item_key']}")["data"]
        changed = [k for k in set(before["item"]) | set(now) if k not in ("version", "dateModified", "tags") and before["item"].get(k) != now.get(k)]
        if changed:
            problems.append(f"item fields changed: {changed}")
        if row.get("draft_tag", True) and not any(t["tag"] == DRAFT_TAG for t in now.get("tags", [])):
            problems.append("item tag ai-draft missing")
        kids_before = {c["key"] for c in before["children"] if not c.get("deleted")}
        kids_now = {c["data"]["key"] for c in api_all(f"items/{row['item_key']}/children") if not c["data"].get("deleted")}
        if kids_now != kids_before:
            problems.append(f"child items changed: {sorted(kids_now ^ kids_before)}")
        row["verified"] = not problems
        ok_all &= not problems
        print(f"{ck}: {'OK' if not problems else 'PROBLEMS'} ({len(sent)} annotations)")
        for p in problems:
            print("   -", p)
    save(run / "batch.json", batch)
    if not ok_all:
        sys.exit(1)


# ---------------------------------------------------------------- note
def annotation_note(run, row, keep=None, now=None):
    """annotation-note.html as Zotero's "Add Note from Annotations" without saving (createNoteFromAnnotations,
    noSave) would make it now (or with the header time `now`), from the PDF's live annotations (only those in `keep`
    when given); frame pictures rendered from the PDF. Returns (html, annotations in note order)."""
    item = api(f"items/{row['item_key']}")
    lib_id = item.get("library", {}).get("id")
    if not lib_id:
        raise RuntimeError("Zotero reports no user library ID (signed out of Zotero sync?): annotation links need it")
    csl = api(f"items/{row['item_key']}?format=csljson")
    csl = (csl.get("items") or [csl])[0] if isinstance(csl, dict) else csl[0]
    parent_uri = f"http://zotero.org/users/{lib_id}/items/{row['item_key']}"
    written = [p["key"] for p in load(run / row["citekey"] / "payload.json")]
    anns = nh.note_order([nh.annotation_json(x["data"]) for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation")
                          if not x["data"].get("deleted") and (keep is None or x["data"]["key"] in keep)], created=written)
    doc = pymupdf.open(row["pdf"])
    for x in anns:
        if x["type"] == "image":
            x["image"] = nh.data_uri(nh.render_frame(doc, x))
    html = nh.build_note(anns, f"http://zotero.org/users/{lib_id}/items/{row['pdf_key']}", parent_uri, {**csl, "id": parent_uri}, now=now)
    return html, anns


def note_problems(text, anns, written, pdf_key, before=None):
    """Every AI annotation linked in the rendered note, every frame with its picture, no broken placeholders.
    Adding to a note (`before` = its old text): pictures are checked for this run's frames only (the user's picture
    files may have been renamed) and placeholders only where they are new."""
    probs = []
    keys = {x["id"] for x in anns}
    gone = [k for k in written if k not in keys]
    if gone:
        probs.append(f"AI annotations no longer in Zotero: {gone}")
    unlinked = [k for k in written if k in keys and not re.search(rf"items/{pdf_key}\?page=\d+&annotation={k}\b", text)]
    if unlinked:
        probs.append(f"annotations without their link in the note: {unlinked}")
    images = re.findall(r"!\[\[([^\]]+\.png)\]\]", text)
    no_pic = [x["id"] for x in anns if x["type"] == "image" and (before is None or x["id"] in written)
              and not any(x["id"] in i for i in images)]
    if no_pic:
        probs.append(f"frames without their picture in the note: {no_pic}")
    for bad in ("[Image not available]", "page=undefined", "annotation=)"):
        if text.count(bad) > (before or "").count(bad):
            probs.append(f"note contains {bad!r}")
    return probs


def convert_note_html(html, storage):
    """The unsaved note embeds images as data URIs; BibNotes needs data-attachment-key and <storage>/<key>/image.png."""
    def rep(m):
        tag = m.group(0)
        ann = re.search(r'data-annotation="([^"]+)"', tag)
        src = re.search(r'src="data:image/\w+;base64,([^"]+)"', tag)
        if not ann or not src:
            return tag
        key = json.loads(urllib.parse.unquote(ann.group(1)))["annotationKey"]
        (storage / key).mkdir(parents=True, exist_ok=True)
        (storage / key / "image.png").write_bytes(base64.b64decode(src.group(1)))
        return tag.replace(src.group(0), f'data-attachment-key="{key}"')
    return re.sub(r'<img [^>]*>', rep, html)


def headless(lib, tmp_vault, citekey, storage=None, note_html=None, existing=None, drop_saved=False):
    cmd = ["node", str(HERE / "bibnotes_headless.js"), "--plugin-dir", str(lib.plugin), "--bbt-json", str(lib.bbt_path),
           "--vault", str(tmp_vault), "--citekey", citekey] + (["--drop-saved-notes"] if drop_saved else [])
    for flag, v in (("--storage", storage), ("--add-note", note_html), ("--existing", existing)):
        if v:
            cmd += [flag, str(v)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError("headless BibNotes failed: " + r.stderr[-400:])
    info = json.loads(r.stdout[r.stdout.index("{"):])
    return pathlib.Path(info["output"]).read_text(encoding="utf-8"), info["notices"]


def bibnotes_key(line):
    """The part of a line that BibNotes's merge (compareOldNewNote) looks up in the old note. A key of one
    character is never looked up, so BibNotes inserts that line again on every update, in any note."""
    s = line.strip()
    for pat in (r"^- ", r"^> ", r"^=", r"^\**", r'^"', r"=$", r"\**$", r'"$'):
        s = re.sub(pat, "", s)
    return s


def merge_inserts(lib, tmp, name, ck, storage, html, existing, drop_saved=False):
    """Simulate Ctrl+P "Update Current Note" on `existing`; return the merged note and the inserted lines."""
    p = pathlib.Path(tmp) / f"{name}.md"
    p.write_text(existing, encoding="utf-8", newline="\n")
    merged, _ = headless(lib, pathlib.Path(tmp) / name, ck, storage, html, p, drop_saved)
    return merged, [l[2:] for l in difflib.ndiff(existing.splitlines(), merged.splitlines()) if l.startswith("+ ")]


def reupdate_check(lib, tmp, ck, storage, html, text, drop_saved=False):
    """(problems, report notes) of an immediate second Ctrl+P update of `text`: it may insert only BibNotes's known
    quirks (one-character lines; once, its own file:/// 'open pdf' line when the PDF's Zotero title is short)."""
    again, inserted = merge_inserts(lib, tmp, "merge", ck, storage, html, text, drop_saved)
    always = [l for l in inserted if len(bibnotes_key(l)) <= 1]  # BibNotes quirk; the user's own notes show it too
    once = [l for l in inserted if re.match(r"- \*\*open pdf\*\*: \[[^\]]*\]\(file:///", l)]  # short PDF title
    other = [l for l in inserted if l not in always and l not in once]
    if once:  # BibNotes's own PDF line comes in once; a second update must add nothing new
        _, inserted2 = merge_inserts(lib, tmp, "merge2", ck, storage, html, again, drop_saved)
        other += [l for l in inserted2 if len(bibnotes_key(l)) > 1]
    problems = []
    if other or yaml_problem(again):
        problems.append(f"re-update not clean: {len(other)} inserted lines {[l[:60] for l in other[:3]]}, {yaml_problem(again)}")
    notes = []
    if any(bibnotes_key(l) for l in always):
        shown = sorted({bibnotes_key(l) for l in always if bibnotes_key(l)})
        notes.append(f"each Ctrl+P update re-adds the one-character line(s) {shown}, a BibNotes quirk"
                     + (" (the Zotero abstract is empty)" if re.search(r"^> \[!Abstract\]\n> ?\n(?!>)", text, re.M) else ""))
    if once:
        notes.append("the first Ctrl+P update adds BibNotes's own file:/// 'open pdf' line (the PDF's Zotero title is short)")
    return problems, notes


def kept_part(text):
    """The lines BibNotes keeps on update ("Select Section" from 'Affiliation:'): from the first line starting with it."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("Affiliation:")), 0)
    return lines[start:]


def lines_lost(old, new):
    """Lines of the note `old` that `new` lacks, in order: adding to a note may only insert lines. The one-line
    ai_updates list is the skill's own and may be rewritten."""
    n, j, lost = new.split("\n"), 0, []
    for l in old.split("\n"):
        if l.startswith("ai_updates:"):
            continue
        k = j
        while k < len(n) and n[k] != l:
            k += 1
        if k == len(n):
            lost.append(l)
        else:
            j = k + 1
    return lost


def front_end(lines):
    """Index of the line after the front matter's closing '---' (0 without front matter)."""
    if not lines or lines[0] != "---":
        return 0
    return next((i + 1 for i in range(1, len(lines)) if lines[i] == "---"), 0)


def add_field_additions(text, fields, pdf_key, label):
    """Add each field addition below what its field already holds, as a marked bullet ('- **<label>**：text' with the
    details nested); nothing that is there is changed. Additions to a field whose line '*Field*:: ' the note lacks go
    into one section '## <label>' before the annotations. Returns (text, number of fields added to)."""
    lines = text.split("\n")
    body = front_end(lines)
    homeless, n = [], 0
    for f in FIELDS:
        v = fields.get(f)
        if not v:
            continue
        val, details = (v.get("text") or "", v.get("details") or []) if isinstance(v, dict) else (v, [])
        val, details = expand_pages(str(val).strip(), pdf_key), [expand_pages(d.strip(), pdf_key) for d in details]
        n += 1
        i = next((i for i in range(body, len(lines)) if lines[i].startswith(f"*{f}*::")), None)
        if i is None:
            homeless.append((f, val, details)); continue
        j = i + 1
        while j < len(lines) and not FIELD_END.match(lines[j]):
            j += 1
        k = j - 1
        while k > i and not lines[k].strip():
            k -= 1
        lines[k + 1:k + 1] = ["", f"- **{label}**" + (f"：{val}" if val else "")] + [f"  - {d}" for d in details]
    if homeless:
        at = next((i for i in range(body, len(lines)) if re.match(r"^#{1,6} .*Extracted Annotations", lines[i])
                   or lines[i].startswith("%% end of note %%")), None)
        if at is None:
            at = len(lines) - 1 if lines and lines[-1] == "" else len(lines)
        block = [f"## {label}", ""]
        for f, val, details in homeless:
            block += [f"**{f}**" + (f"：{val}" if val else "")] + [f"- {d}" for d in details] + [""]
        lines[at:at] = block + ["---", ""]
    return "\n".join(lines), n


def add_update_record(text, entry):
    """Record the addition in the front matter's list ai_updates ("date · task · agent"), after everything else there,
    so inside the part BibNotes keeps. A block list gains a line; a one-line list is rewritten."""
    lines = text.split("\n")
    end = front_end(lines) - 1  # the closing '---'
    if end < 1:
        raise ValueError("no front matter")
    i = next((i for i in range(1, end) if lines[i].startswith("ai_updates:")), None)
    item = json.dumps(entry, ensure_ascii=False)
    if i is None:
        lines[end:end] = ["ai_updates:", f"  - {item}"]
    elif lines[i][len("ai_updates:"):].strip():
        old = yaml.safe_load(lines[i][len("ai_updates:"):])
        if not isinstance(old, list):
            raise ValueError("ai_updates is not a list")
        lines[i] = "ai_updates: " + json.dumps(old + [entry], ensure_ascii=False)
    else:
        j = i + 1
        while j < end and re.match(r"^\s*-\s", lines[j]):
            j += 1
        indent = re.match(r"^(\s*)-\s", lines[j - 1]).group(1) if j > i + 1 else "  "  # as the list has it
        lines[j:j] = [f"{indent}- {item}"]
    return "\n".join(lines)


def yaml_problem(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return "no YAML front matter"
    keys = re.findall(r"^([A-Za-z_]\w*):", m.group(1), re.M)
    dups = sorted({k for k in keys if keys.count(k) > 1})
    if dups:
        return f"duplicate keys {dups}"
    try:
        yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return "invalid YAML: " + str(e).splitlines()[0]
    return None


def expand_pages(s, pdf_key):
    """{p.N} / {p.N-M} -> page link that opens the PDF in Zotero at page N (1-based page index)."""
    def rep(m):
        a, b = m.group(1), m.group(2)
        label = f"pp. {a}–{b}" if b else f"p. {a}"
        return f"[({label})](zotero://open-pdf/library/items/{pdf_key}?page={a})"
    return re.sub(r"\{p\.\s*(\d+)(?:\s*[-–]\s*(\d+))?\}", rep, s)


def fill_note(text, reading, pdf_key, agent):
    for f in FIELDS:
        v = reading["fields"][f]
        val, details = (v.get("text", ""), v.get("details", [])) if isinstance(v, dict) else (v, [])
        val, details = expand_pages(val, pdf_key), [expand_pages(d, pdf_key) for d in details]
        old = f"*{f}*:: \n"
        if old not in text:
            raise RuntimeError(f"field line {old!r} not found in the BibNotes rendering")
        new = f"*{f}*:: {val.strip()}\n" + ("\n" + "\n".join(f"- {d}" for d in details) + "\n" if details else "")
        text = text.replace(old, new, 1)
    end = text.index("\n---\n", 4)  # AI keys go after Keywords, inside the part BibNotes keeps on update
    ai = {"note_status": "AI draft", "generated_by": agent, "generated_on": datetime.date.today().isoformat()}
    text = text[:end + 1] + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in ai.items()) + text[end + 1:]
    # the whole link target, also when the file name has parentheses: "poly(dimethylsiloxane)" (feedback 2026-10-16)
    # BibNotes writes "[name](file:///" + encodeURI(path) + ")", parentheses unescaped and possibly unbalanced (a cut
    # name "poly(ethyle.pdf"): the target ends at the ')' before the next attachment ("; [") or the line end
    text = re.sub(r"(\*\*open pdf\*\*: \[[^\]\n]+\])\((?:file:///|zotero://)[^\n]*?\)(?=;\s*\[|[ \t]*$)",
                  rf"\1(zotero://open-pdf/library/items/{pdf_key})", text, flags=re.M)
    text = text if text.endswith("\n") else text + "\n"
    i = text.index("\ngenerated_on: ") + 1
    j = text.index("\n", i) + 1
    return text[:j] + f'generated_sha256: "{kept_hash(text)}"\n' + text[j:]


ANN_LINK = re.compile(r"[?&]annotation=([A-Z0-9]{8})\b")


def run_blocks(rendered, keys):
    """{key: lines} for each of `keys` in a BibNotes rendering of only these annotations: from the first line that links
    the annotation up to the first line of the next one (or the end marker), without trailing blank lines. These are
    exactly the lines BibNotes writes for them, so a later Ctrl+P update finds them."""
    lines = rendered.split("\n")
    first = {}
    for i, l in enumerate(lines):
        for k in ANN_LINK.findall(l):
            if k in keys:
                first.setdefault(k, i)
    order = sorted(first, key=first.get)
    stop_all = next((i for i in range(max(first.values(), default=0), len(lines)) if lines[i].startswith("%% end of note %%")), len(lines))
    blocks = {}
    for n, k in enumerate(order):
        b = lines[first[k]:first[order[n + 1]] if n + 1 < len(order) else stop_all]
        while b and not b[-1].strip():
            b.pop()
        blocks[k] = b
    return blocks


def insert_blocks(base, blocks, order):
    """Insert this run's annotation blocks into the note `base` (insertion only): each goes right before the first line
    of the next annotation in note order that the note links in its annotation section, or, after the last one, at the
    end of that section. Returns (text, how the blocks were placed)."""
    lines = base.split("\n")
    end = len(lines) - 1 if lines and lines[-1] == "" else len(lines)  # before the final line break
    head = next((i for i, l in enumerate(lines) if re.match(r"^#{1,6} .*Extracted Annotations", l)), None)
    start = head + 1 if head is not None else front_end(lines)
    first = {}  # annotation key -> first line of the annotation section that links it
    for i in range(start, len(lines)):
        for k in ANN_LINK.findall(lines[i]):
            first.setdefault(k, i)
    marker = next((i for i in range(start, end) if lines[i].startswith("%% end of note %%")), end)
    if head is None and not first:
        stop = marker  # no annotation section: a new one goes before the end marker
    else:  # the section ends at the end marker or the next heading after its last linked line
        last = max(first.values(), default=start - 1)
        stop = next((i for i in range(last + 1, end) if lines[i].startswith("%% end of note %%") or re.match(r"^#{1,6} ", lines[i])), end)
    at, how = {}, []
    for n, k in enumerate(order):
        if k not in blocks:
            continue
        nxt = next((j for j in order[n + 1:] if j in first and j not in blocks), None)
        if nxt is not None:  # before the next annotation, so whatever follows the previous one stays with it
            p = first[nxt]
            # its rendering may begin above its link line (a highlight over two lines: "> <mark …" then "…</mark> [link]"):
            # go up to the line that opens it, but not into the previous annotation's comment ("- …") or another element
            while (p > start and lines[p - 1].strip() and not ANN_LINK.search(lines[p - 1])
                   and not re.match(r"^(> |- |!\[\[|#{1,6} |Annotations\()", lines[p])):
                p -= 1
        elif first or head is None:  # after everything in the section
            p = stop
            while p > start and not lines[p - 1].strip():
                p -= 1
        else:  # the section links none of the PDF's annotations: at its start, after its header line
            p = start
            while p < stop and (not lines[p].strip() or lines[p].startswith("Annotations(")):
                p += 1
        at.setdefault(p, []).append(k)
    new_section = head is None and not first
    if new_section and at:
        how.append("the note had no 'Extracted Annotations' section: one was added before its end")
    elif not first and at:
        how.append("the note links none of the PDF's annotations: this run's were put at the start of 'Extracted Annotations'")
    for p in at:  # never inside an open highlight: the user's "<mark>" must close before the inserted block
        before = "\n".join(lines[:p])
        if before.count("<mark") != before.count("</mark>"):
            raise ValueError(f"no safe place for {at[p]} in the note: line {p + 1} lies inside a highlight")
    out = []
    for i in range(len(lines) + 1):
        if i in at:
            chunk = ["## Extracted Annotations", ""] if new_section else []
            for k in at[i]:
                chunk += ([""] if chunk and chunk[-1].strip() else []) + blocks[k]
            if out and out[-1].strip():
                chunk = [""] + chunk
            if i < len(lines) and lines[i].strip():
                chunk += [""]
            out += chunk
        if i < len(lines):
            out.append(lines[i])
    return "\n".join(out), how


def inserts_on_update(lib, tmp, name, ck, storage, html, text):
    """Lines a Ctrl+P update with this annotation note would insert into the part of `text` BibNotes keeps."""
    p = pathlib.Path(tmp) / f"{name}.md"
    p.write_text(text, encoding="utf-8", newline="\n")
    merged, _ = headless(lib, pathlib.Path(tmp) / name, ck, storage, html, p, drop_saved=True)
    return [l[2:] for l in difflib.ndiff(kept_part(text), kept_part(merged)) if l.startswith("+ ")]


def build_update(lib, run, row, reading, agent, task, td, before):
    """The note `before` with this run's annotations, field additions and ai_updates record inserted; nothing else of it
    changes, the front matter included. BibNotes renders the annotation lines (as its update would write them), but the
    skill places them: BibNotes's own merge would also re-insert what the user deleted and could put a new block between
    an annotation and its comment. Returns (text, problems, report notes, this run's picture files under td/fresh,
    number of fields added to). The note is not touched."""
    ck, pdf_key = row["citekey"], row["pdf_key"]
    img_dir = lib.settings.get("imagesPath", "Linked files")
    base = before if before.endswith("\n") else before + "\n"
    written = [p["key"] for p in load(run / ck / "payload.json")]
    linked = set(ANN_LINK.findall(base))
    if set(written) & linked:
        return base, [f"this run's annotations are already in the note ({sorted(set(written) & linked)[:3]}): it was added to before"], [], [], 0
    # the annotation note's header renders as the line "Annotations(<date>)": with the note's own date a later update
    # finds it instead of inserting a second header
    m = re.search(r"^Annotations\((\d{1,2}/\d{1,2}/\d{4}, \d{1,2}:\d{2}:\d{2} [AP]M)\)\s*$", base, re.M)
    now = datetime.datetime.strptime(m.group(1), "%m/%d/%Y, %I:%M:%S %p") if m else None
    storage = run / ck / "storage"
    blocks = {}
    if written:  # a reading of field additions only adds no annotation lines (BibNotes cannot render an empty note)
        new_html, _ = annotation_note(run, row, keep=set(written), now=now)
        (run / ck / "annotation-note-new.html").write_text(new_html, encoding="utf-8")
        hn = run / ck / "annotation-note-new-for-bibnotes.html"
        hn.write_text(convert_note_html(new_html, storage), encoding="utf-8")
        rendered, _ = headless(lib, pathlib.Path(td) / "fresh", ck, storage, hn, drop_saved=True)
        blocks = run_blocks(rendered, set(written))
    # the note order of everything the note will link: the annotations it links already plus this run's
    all_html, anns = annotation_note(run, row, keep=linked | set(written), now=now)
    (run / ck / "annotation-note.html").write_text(all_html, encoding="utf-8")
    ha = run / ck / "annotation-note-for-bibnotes.html"
    ha.write_text(convert_note_html(all_html, storage), encoding="utf-8")
    problems = [f"BibNotes rendered no lines for {[k for k in written if k not in blocks]}"] if set(written) - set(blocks) else []
    text, notes = insert_blocks(base, blocks, [x["id"] for x in anns])
    date = datetime.date.today().isoformat()
    text, n_fields = add_field_additions(text, reading.get("fields") or {}, pdf_key, f"AI 补充（{date} · {task}）")
    text = add_update_record(text, f"{date} · {task} · {agent}")
    problems += note_problems(text, anns, written, pdf_key, before=base)
    if yaml_problem(text) and not yaml_problem(base):
        problems.append(yaml_problem(text))
    old_marks = re.findall(r"<mark[^>]*>(.*?)</mark>", base)
    if any(re.search(r"[<>]", m) for m in re.findall(r"<mark[^>]*>(.*?)</mark>", text) if m not in old_marks):
        problems.append("< or > inside <mark>")
    lost = lines_lost(base, text)
    if lost:
        problems.append(f"the update would change or remove {len(lost)} line(s) of the note, e.g. {[l[:60] for l in lost[:2]]}")
    pictures = [i for i in re.findall(r"!\[\[([^\]]+\.png)\]\]", "\n".join(l for b in blocks.values() for l in b))]
    missing = [i for i in pictures if not (pathlib.Path(td) / "fresh" / img_dir / i).exists()]
    if missing:
        problems.append(f"pictures missing {missing}")
    # a later Ctrl+P update (with an annotation note holding these annotations) must find every line this run added
    # and must not insert anything it would not have inserted into the note as it was
    if not anns:  # nothing to render: the note links no annotation and this run adds none
        return text, problems, notes, pictures, n_fields
    after = inserts_on_update(lib, td, "after", ck, storage, ha, text)
    before_ins = inserts_on_update(lib, td, "before", ck, storage, ha, base)
    ours = {l for b in blocks.values() for l in b if l.strip()}
    again = [l for l in after if l in ours or any(k in l for k in written)]
    caused = list((collections.Counter(l for l in after if len(bibnotes_key(l)) > 1)
                   - collections.Counter(l for l in before_ins if len(bibnotes_key(l)) > 1)).elements())
    if again or caused:
        problems.append(f"a later Ctrl+P update would insert {len(again) + len(caused)} line(s) again or anew, e.g. "
                        f"{[l[:60] for l in (again + caused)[:2]]}")
    drift = [l for l in before_ins if len(bibnotes_key(l)) > 1 and l not in ours and not any(k in l for k in written)]
    if drift:
        notes.append(f"unrelated to this run, a Ctrl+P update of this note would insert {len(drift)} line(s) (comments or lines "
                     f"changed or deleted in the note since it was made, e.g. {[l[:50] for l in drift[:2]]}); they were not inserted")
    if yaml_problem(base):
        notes.append(f"the note's front matter was invalid already ({yaml_problem(base)})")
    return text, problems, notes, pictures, n_fields


def update_note(lib, run, row, reading, agent, task, img_dir):
    """Add this run's annotations and field additions to the paper's existing note (an AI draft or the user's own) and
    keep the note's previous text in the run folder. Report lines."""
    ck = row["citekey"]
    note_path = pathlib.Path(row["note_path"])
    raw = note_path.read_bytes()
    try:
        before = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [f"- {ck}: NOT updated (the note is not UTF-8 text)"]
    prob = note_update_problem(before)
    if prob:
        return [f"- {ck}: NOT updated ({prob})"]
    if (run / ck / "note-updated.json").exists():
        row["note_updated"] = str(note_path)
        return [f"- {ck}: note added to by an earlier `note` run of this run directory: {note_path.relative_to(lib.vault)}"]
    with tempfile.TemporaryDirectory() as td:
        try:
            text, problems, notes, pictures, n_fields = build_update(lib, run, row, reading, agent, task, td, before)
        except (RuntimeError, ValueError, yaml.YAMLError, OSError) as e:
            return [f"- {ck}: NOT updated ({type(e).__name__}: {e})"]
        if problems:
            (run / ck / "note-rejected.md").write_text(text, encoding="utf-8", newline="\n")
            return [f"- {ck}: NOT updated ({'; '.join(problems)}); the result it would have written is in {run / ck / 'note-rejected.md'}"]
        if note_path.read_bytes() != raw:  # edited in Obsidian meanwhile: add to the new text instead
            return [f"- {ck}: NOT updated (the note changed while this run was adding to it): run `note` again"]
        if not (run / ck / "note-before.md").exists():  # the note as it was before this run, kept once
            (run / ck / "note-before.md").write_bytes(raw)
        for i in pictures:
            dst = lib.vault / img_dir / i
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pathlib.Path(td) / "fresh" / img_dir / i, dst)
        save(run / ck / "note-updated.json", {"note": str(note_path), "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        tmp = note_path.with_name(note_path.name + ".zar-tmp")  # whole or not at all: a stopped run never leaves half a note
        tmp.write_text(text, encoding="utf-8", newline="\n")
        tmp.replace(note_path)
    row["note_updated"] = str(note_path)
    who = "an AI draft" if row.get("note_state") == "ai-draft" else "the user's note"
    return [f"- {ck}: note added to ({who}; {placed_summary(run, ck)}, {len(pictures)} pictures, {n_fields} field addition(s)): "
            f"{note_path.relative_to(lib.vault)}; the text before is in {run / ck / 'note-before.md'}"] + [f"  - note: {n}" for n in notes]


def placed_summary(run, ck):
    """'N highlights + M frames placed; dropped R repeats, D not placed' for the report."""
    pl, placement = load(run / ck / "payload.json"), load(run / ck / "placement.json")
    n_img = sum(1 for p in pl if p["type"] == "image")
    rep = sum(1 for d in placement["dropped"] if "repeat" in d)
    return (f"{len(pl) - n_img} highlights + {n_img} frames placed; dropped {rep} repeats of existing annotations, "
            f"{len(placement['dropped']) - rep} not placed")


def cmd_note(a):
    run = pathlib.Path(a.run_dir).resolve()
    batch = load(run / "batch.json")
    lib = library_of(batch)
    img_dir = lib.settings.get("imagesPath", "Linked files")
    fmt = note_format_problem(zotero_prefs())
    if fmt:
        die(f"{fmt}: the annotation note would not match Zotero's own; restore the default or update note_html.py first")
    lines = [f"# zotero-ai-reading run {run.name}", ""]
    for row in batch["items"]:
        ck = row["citekey"]
        if row["status"] != "ready":
            lines.append(f"- {ck}: skipped ({row.get('reason')})"); continue
        if not row.get("verified"):
            lines.append(f"- {ck}: not verified in Zotero yet"); continue
        note_path = pathlib.Path(row["note_path"])
        updating = row.get("mode") == "update" and row.get("note_state", "none") != "none"
        if updating:
            if row.get("note_updated"):
                lines.append(f"- {ck}: note added to by an earlier `note` run: {note_path.relative_to(lib.vault)}"); continue
            if not note_path.exists():
                lines.append(f"- {ck}: STOP, the note to add to is gone from {note_path}"); continue
        else:  # a new note, or (prepare --replace-ai-draft) one replacing the untouched AI draft prepare saw
            replace = row.get("mode") == "new" and row.get("note_state") == "ai-draft"
            if row.get("note_written") and note_path.exists():
                lines.append(f"- {ck}: note written by an earlier `note` run: {note_path.relative_to(lib.vault)}"); continue
            if note_path.exists() and not (replace and note_state(note_path) == "ai-draft"):
                lines.append(f"- {ck}: STOP, a note appeared at {note_path}"); continue
            if note_path.exists() and not draft_unchanged(note_path.read_text(encoding="utf-8", errors="replace")):
                lines.append(f"- {ck}: NOT written (the AI draft at {note_path} was changed after the skill wrote it, or predates "
                             "0.4.0: it is not replaced; add to it with prepare --update)"); continue
        if row.get("draft_tag", True) and not lib.wait_for_tag(ck, DRAFT_TAG, timeout=a.wait):
            lines.append(f"- {ck}: Better BibTeX export does not show the ai-draft tag yet; rerun `note` in a minute"); continue
        reading = load(run / ck / "reading.json")
        if updating:
            lines += update_note(lib, run, row, reading, a.agent, batch.get("task") or run.name, img_dir)
            save(run / "batch.json", batch)  # progress after each paper: a later failure must not make a rerun add twice
            continue
        storage = run / ck / "storage"
        try:
            note_html, anns = annotation_note(run, row)
        except RuntimeError as e:
            lines.append(f"- {ck}: NOT written ({e})"); continue
        (run / ck / "annotation-note.html").write_text(note_html, encoding="utf-8")
        conv = convert_note_html(note_html, storage)
        (run / ck / "annotation-note-for-bibnotes.html").write_text(conv, encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            text, notices = headless(lib, pathlib.Path(td) / "render", ck, storage, run / ck / "annotation-note-for-bibnotes.html")
            bad_notices = [n for n in notices if not n.startswith("Imported")]
            text = fill_note(text, reading, row["pdf_key"], a.agent)
            problems = note_problems(text, anns, [p["key"] for p in load(run / ck / "payload.json")], row["pdf_key"])
            if yaml_problem(text):
                problems.append(yaml_problem(text))
            if any(re.search(r"[<>]", m) for m in re.findall(r"<mark[^>]*>(.*?)</mark>", text)):
                problems.append("< or > inside <mark>")
            images = re.findall(r"!\[\[([^\]]+\.png)\]\]", text)
            missing = [i for i in images if not (pathlib.Path(td) / "render" / img_dir / i).exists()]
            if missing or bad_notices:
                problems.append(f"images missing {missing} {bad_notices}")
            again_problems, notes = reupdate_check(lib, td, ck, storage, run / ck / "annotation-note-for-bibnotes.html", text)
            problems += again_problems
            if problems:
                (run / ck / "note-rejected.md").write_text(text, encoding="utf-8", newline="\n")
                lines.append(f"- {ck}: NOT written ({'; '.join(problems)}); draft in {run / ck / 'note-rejected.md'}"); continue
            for i in images:
                dst = lib.vault / img_dir / i
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(pathlib.Path(td) / "render" / img_dir / i, dst)
            if note_path.exists() and not (run / ck / "note-before.md").exists():  # an AI draft replaced on request
                (run / ck / "note-before.md").write_bytes(note_path.read_bytes())
                notes.append(f"replaced an unchanged AI draft; its text is in {run / ck / 'note-before.md'}")
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(text, encoding="utf-8", newline="\n")
        row["note_written"] = str(note_path)
        save(run / "batch.json", batch)
        lines.append(f"- {ck}: note written ({placed_summary(run, ck)}, {len(images)} pictures): {note_path.relative_to(lib.vault)}"
                     + "".join(f"\n  - note: {n}" for n in notes))
    save(run / "batch.json", batch)
    lines += ["", "After all notes: in Zotero run MarkDB-Connect > Sync Tags so 'Open Note in Obsidian' appears."]
    (run / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--library-root", required=True)
    s.add_argument("--vault")
    s.add_argument("--run-dir", required=True)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--folder", help="PDF folder, absolute or relative to the library root")
    g.add_argument("--citekey", nargs="+")
    g.add_argument("--item", nargs="+")
    s.add_argument("--limit", type=int, default=MAX_BATCH)
    s.add_argument("--alongside", action="store_true", help="also annotate papers that have the user's annotations but no note (only on request)")
    s.add_argument("--update", action="store_true",
                   help="also take papers read before or with a note (AI draft or the user's): add new annotations beside "
                        "the existing ones and add to the note without changing it (only on request)")
    s.add_argument("--task", help="with --update: the research task or request this reading serves; labels each addition")
    s.add_argument("--replace-ai-draft", action="store_true", help="allow replacing an earlier AI-draft note (no AI annotations left)")
    for name in ("write", "verify"):
        sub.add_parser(name).add_argument("--run-dir", required=True)
    s = sub.add_parser("undo")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--citekey", nargs="+", help="undo only these papers of the run")
    s = sub.add_parser("place")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--citekey", nargs="+", help="place only these papers (a reader checking its own papers)")
    s = sub.add_parser("pagemap")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--citekey", nargs="*")
    s = sub.add_parser("note")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--agent", required=True, help='e.g. "Claude (claude-opus-5-5)"')
    s.add_argument("--wait", type=int, default=90, help="seconds to wait for the Better BibTeX export")
    s.add_argument("--replace-ai-draft", action="store_true", help="no longer needed: prepare --replace-ai-draft decides (kept for old commands)")
    a = p.parse_args()
    if getattr(a, "limit", MAX_BATCH) > MAX_BATCH:
        die(f"batches are limited to {MAX_BATCH} papers")
    {"prepare": cmd_prepare, "pagemap": cmd_pagemap, "place": cmd_place, "write": cmd_write,
     "verify": cmd_verify, "note": cmd_note, "undo": cmd_undo}[a.cmd](a)


if __name__ == "__main__":
    main()
