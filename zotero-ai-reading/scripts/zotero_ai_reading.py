"""zotero-ai-reading: AI annotations in Zotero + BibNotes-compatible Obsidian notes for unread papers.

Steps (each reads and writes files in one run directory):
  prepare        select papers, check them, run OCR for scans                 -> batch.json
  (agent)        write <citekey>/reading.json for each ready paper (see references/reading.md)
  place          validate readings, place highlights/regions on the PDF pages  -> <citekey>/payload.json, previews
  zotero-script  write the import and undo scripts the user pastes into Zotero -> import-ai-annotations.js, undo-ai-annotations.js
  verify         compare Zotero (read-only local API) with what was sent
  note           make, write and check the Obsidian notes                     -> report.md
Zotero is only read here; all Zotero changes happen in the pasted scripts.
"""
import argparse, base64, datetime, difflib, hashlib, json, pathlib, re, secrets, shutil, subprocess, sys, tempfile, unicodedata, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import yaml
import pymupdf, PIL.Image, PIL.ImageDraw
from zar_common import Library, api, api_all, zotero_available, mineru_markdown, COLORS, FIELDS, KEY_CHARS
import text_locator as tl
from page_regions import Pages, render_for_ocr, LABEL

sys.stdout.reconfigure(encoding="utf-8")
MAX_BATCH = 10
AI_TAG, DRAFT_TAG = "AI", "ai-draft"
LOCATOR = "0.1.0-rc.7"  # part of place's input hash: a new locator re-places papers placed by an older one
SHORT_QUOTE = 40  # characters; shorter highlights show the user only a fragment


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


def cmd_prepare(a):
    lib = Library(a.library_root, a.vault)
    run = pathlib.Path(a.run_dir)
    if not zotero_available():
        die("Zotero is not running or its local API is off (Zotero settings > Advanced > allow other applications).")
    probs = lib.bibnotes_problems()
    if probs:
        die("BibNotes set-up differs from what the notes rely on:\n  - " + "\n  - ".join(probs))
    if a.folder:
        f = pathlib.Path(a.folder)
        rel = lib.rel(f) if f.is_absolute() else f
        pairs = lib.bbt_items_in_folder(rel)
        if not pairs:
            die(f"no Zotero item with a PDF directly in {rel}")
    else:
        pairs = []
        for k in (a.citekey or []) + (a.item or []):
            e = lib.bbt_entry(citekey=k) or lib.bbt_entry(item_key=k)
            if not e:
                die(f"{k} is not in the Better BibTeX export")
            att = next((x for x in e.get("attachments", []) if (x.get("path") or "").lower().endswith(".pdf")), None)
            pairs.append((e, att))
    items, ready = [], 0
    for e, att in sorted(pairs, key=lambda p: p[0].get("citationKey", "")):
        ck = e["citationKey"]
        row = {"citekey": ck, "item_key": e["itemKey"], "title": e.get("title", "")}
        items.append(row)
        if att is None:
            row.update(status="skip", reason="no PDF attachment"); continue
        pdf_rel = lib.rel(att["path"])
        pdf = lib.root / pdf_rel if pdf_rel else None
        row.update(pdf_key=att["uri"].rsplit("/", 1)[-1], pdf=str(pdf), pdf_rel=str(pdf_rel))
        if pdf is None or not pdf.exists():
            row.update(status="skip", reason="PDF not found under the library root"); continue
        try:
            anns = [x for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")]
        except Exception as ex:
            row.update(status="skip", reason=f"Zotero API: {ex}"); continue
        if anns and not a.alongside:
            row.update(status="skip", reason=f"already annotated ({len(anns)} annotations); use --alongside only on request"); continue
        md, md_status = mineru_markdown(pdf)
        row.update(md=str(md) if md else None, md_status=md_status)
        if md is None or md_status.startswith("stale"):
            row.update(status="skip", reason=f"Markdown {md_status}: convert with mineru-api-batch-convert (or marker-api-batch-convert "
                                             "when MinerU is unavailable) first"); continue
        note = lib.note_path(pdf_rel, ck)
        row["note_path"] = str(note)
        if note.exists():
            head = note.read_text(encoding="utf-8", errors="replace")[:3000]
            if not (a.replace_ai_draft and re.search(r'^note_status: "?AI draft', head, re.M)):
                row.update(status="skip", reason="an Obsidian note already exists"); continue
        if ready >= a.limit:
            row.update(status="later", reason=f"batch limit {a.limit}"); continue
        doc = pymupdf.open(pdf)
        chars = tl.text_chars(doc)
        row["pages"] = doc.page_count
        row["kind"] = "text" if sum(chars) / max(1, doc.page_count) >= 200 else "scan"
        if row["kind"] == "scan":
            ocr = run / ck / "ocr.json"
            if not ocr.exists():
                run_ocr(pdf, ocr, run / ck / "ocr_pages")
            row["ocr"] = str(ocr)
        row["status"] = "ready"
        ready += 1
    batch = {"created": datetime.datetime.now().isoformat(timespec="seconds"), "library_root": str(lib.root),
             "vault": str(lib.vault), "alongside": bool(a.alongside), "items": items}
    save(run / "batch.json", batch)
    for r in items:
        extra = f"{r.get('kind', '')} {r.get('md_status', '')}" if r["status"] == "ready" else r.get("reason", "")
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
    """Quote (compacted) occurs in the Markdown, allowing tiny conversion slips (MinerU drops letters of ligatures,
    e.g. "efficiency" -> "eficiency"); blocks invented or paraphrased quotes."""
    if quote_c in md_c:
        return True
    m = difflib.SequenceMatcher(None, md_c, quote_c, autojunk=False).find_longest_match(0, len(md_c), 0, len(quote_c))
    if m.size < 12:
        return False
    start = max(0, m.a - m.b)
    window = md_c[start:start + len(quote_c) + 5]
    return difflib.SequenceMatcher(None, window, quote_c, autojunk=False).ratio() >= min_ratio


def validate_reading(rd, md_text):
    errs = []
    f = rd.get("fields", {})
    for k in FIELDS:
        v = f.get(k)
        text = v.get("text") if isinstance(v, dict) else v
        if not text or not str(text).strip():
            errs.append(f"field {k} is empty")
        for a, b in re.findall(r"\{p\.\s*(\d+)\s*[-–]\s*(\d+)\}", json.dumps(v, ensure_ascii=False)):
            if not 0 < int(b) - int(a) <= 2:
                errs.append(f"field {k}: page range {{p.{a}-{b}}}: cite the specific page, or a derivation over at most 3 pages")
    md_c = compact_norm(re.sub(r"\$[^$]*\$", " ", md_text))
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
    if not rd.get("highlights") and not rd.get("regions"):
        errs.append("no highlights or regions")
    return errs


def new_key(used):
    while True:
        k = "".join(secrets.choice(KEY_CHARS) for _ in range(8))
        if k not in used:
            used.add(k)
            return k


def place_inputs(rp, row):
    """Hash of everything a placement depends on: the reading, Markdown, PDF, OCR and the locator version."""
    h = hashlib.sha256(LOCATOR.encode())
    for p in (rp, row["md"], row["pdf"], row.get("ocr")):
        if p and pathlib.Path(p).exists():
            h.update(pathlib.Path(p).read_bytes())
    return h.hexdigest()


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
    for row in batch["items"]:
        if row["status"] != "ready" or (a.citekey and row["citekey"] not in a.citekey):
            continue  # with --citekey only those papers' files are written
        ck = row["citekey"]
        rp = run / ck / "reading.json"
        if not rp.exists():
            print(f"{ck}: reading.json missing"); continue
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
        errs = validate_reading(rd, md_text)
        if errs:
            print(f"{ck}: reading.json needs fixing:\n  - " + "\n  - ".join(errs)); continue
        doc = pymupdf.open(row["pdf"])
        pages = Pages(row["pdf"], row["md"], row.get("ocr"))
        payload, dropped, previews = [], [], {}
        for h in rd["highlights"]:
            loc, how = tl.place(doc, h["quote"]) if row["kind"] == "text" else pages.place_quote(h["quote"])
            if not loc:
                dropped.append({"quote": h["quote"][:120], "why": how}); continue
            page = doc[loc["page"]]
            label = (page.get_label() or str(loc["page"] + 1)) if row["kind"] == "text" else str(loc["page"] + 1)
            payload.append({"key": new_key(used), "type": "highlight", "text": nfc(h["quote"]), "comment": nfc(h["comment"]),
                            "color": COLORS[h["color"]], "pageLabel": label,
                            "sortIndex": tl.sort_index(page, loc["glyph_offset"], loc["rects"][0]),
                            "position": {"pageIndex": loc["page"], "rects": tl.to_zotero(page, loc["rects"])},
                            "_placed": how, "_pdf_text": loc["text"][:200]})
            previews.setdefault(loc["page"], []).append((loc["rects"], h["color"]))
        for g in rd.get("regions", []):
            r = getattr(pages, g["kind"])(g["n"])
            if not r:
                dropped.append({"region": f"{g['kind']} {g['n']}", "why": "not located"}); continue
            page = doc[r["page"]]
            label = (page.get_label() or str(r["page"] + 1)) if row["kind"] == "text" else str(r["page"] + 1)
            payload.append({"key": new_key(used), "type": "image", "text": "", "comment": nfc(g["comment"]), "color": COLORS[g["color"]],
                            "pageLabel": label, "sortIndex": r["sortIndex"],
                            "position": {"pageIndex": r["page"], "rects": r["zotero_rects"]},
                            "_placed": f"{g['kind']} {g['n']}", "_check": {k: v for k, v in r.items() if k not in ("page", "rect", "zotero_rects", "sortIndex")}})
            previews.setdefault(r["page"], []).append(([r["rect"]], g["color"]))
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
            for rects, c in its:
                for r in rects:
                    dr.rectangle([v * 90 / 72 for v in (r.x0, r.y0, r.x1, r.y1)], fill=rgba[c], outline=rgba[c][:3] + (255,), width=2)
            im.save(run / ck / f"preview_p{pi + 1}.png")
        snapped = sum(1 for p in payload if str(p["_placed"]).startswith("snapped"))
        print(f"{ck}: placed {len(payload)} (snapped {snapped}), dropped {len(dropped)}; previews in {run / ck}")
        for d in dropped:
            print("   dropped:", d)
        print("   " + coverage_line(rd, payload, doc.page_count))
        short = [h["quote"] for h in rd["highlights"] if len(h["quote"]) < SHORT_QUOTE]
        if short:
            print(f"   short quotes (the user sees only this fragment highlighted; quote the whole clause where it carries the point): {short}")


def coverage_line(rd, payload, n_pages):
    """Information for the agent, never a rule: annotations by colour, frames by kind, pages covered."""
    by = {c: 0 for c in COLORS}
    for x in rd["highlights"] + rd.get("regions", []):
        by[x["color"]] += 1
    kinds = {}
    for g in rd.get("regions", []):
        kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
    pages = sorted({p["position"]["pageIndex"] + 1 for p in payload})
    line = (f"coverage: {', '.join(f'{c} {n}' for c, n in by.items())}; frames: "
            f"{', '.join(f'{k} {n}' for k, n in kinds.items()) or 'none'}; pages {pages} of {n_pages}")
    missing = [m for c, m in (("green", "background"), ("orange", "methods"), ("yellow", "results")) if not by[c]]
    if missing:
        line += f" (no {'/'.join(missing)} annotation: check that the paper really has none)"
    return line


# ---------------------------------------------------------------- zotero-script
IMPORT_JS = r"""// zotero-ai-reading import (__STAMP__). Paste into Zotero: Tools > Developer > Run JavaScript, tick
// "Run as async function", click Run. Creates AI annotations (tag "AI") and the item tag "ai-draft" for the papers
// below; never edits or deletes existing items. "Add Note from Annotations" is built WITHOUT saving a note; its HTML
// is written to the run folder, together with this script's result. Checks every paper before changing anything.
const RUN_DIR = __RUN_DIR__;
const ALONGSIDE = __ALONGSIDE__;
const ITEMS = __ITEMS__;
const lib = Zotero.Libraries.userLibraryID;
const get = (k) => Zotero.Items.getByLibraryAndKeyAsync(lib, k);
const sep = RUN_DIR.includes("\\") ? "\\" : "/";
const writeText = (p, s) => typeof IOUtils !== "undefined" ? IOUtils.writeUTF8(p, s) : Zotero.File.putContentsAsync(p, s);
for (const it of ITEMS) {
  const item = await get(it.item), att = await get(it.pdf);
  if (!item || item.getField("title") !== it.title) return {status: "abort", reason: `${it.citekey}: item/title mismatch`};
  if (!att || att.parentID !== item.id || !att.isPDFAttachment()) return {status: "abort", reason: `${it.citekey}: PDF attachment mismatch`};
  if (!ALONGSIDE && att.getAnnotations().length) return {status: "abort", reason: `${it.citekey}: the PDF already has annotations`};
  if (att.getAnnotations().some(a => a.hasTag("AI"))) return {status: "abort", reason: `${it.citekey}: AI annotations already exist`};
  for (const a of it.annotations) if (await get(a.key)) return {status: "abort", reason: `${it.citekey}: key ${a.key} already in use`};
}
const result = {status: "created", items: []};
for (const it of ITEMS) {
  const item = await get(it.item), att = await get(it.pdf);
  const created = [];
  for (const a of it.annotations) {
    const ann = await Zotero.Annotations.saveFromJSON(att, Object.assign({authorName: "", isExternal: false, tags: [{name: "AI"}]}, a));
    created.push(ann.key);
  }
  const tagAdded = !item.hasTag("ai-draft");
  if (tagAdded) { item.addTag("ai-draft"); await item.saveTx(); }
  const anns = att.getAnnotations().filter(x => x.annotationType != "ink");
  const note = await Zotero.EditorInstance.createNoteFromAnnotations(anns, {parentID: item.id, noSave: true});
  const out = RUN_DIR + sep + it.citekey + sep + "annotation-note.html";
  let writeError = null;
  try { await writeText(out, note.getNote()); } catch (e) { writeError = String(e); }
  result.items.push({citekey: it.citekey, created, tagAdded, noteHtml: writeError ? null : out, writeError});
}
try { await writeText(RUN_DIR + sep + "zotero-import-result.json", JSON.stringify(result, null, 1)); }
catch (e) { result.resultFileError = String(e); }
return result;
"""

UNDO_JS = r"""// zotero-ai-reading UNDO (__STAMP__). Paste into Zotero: Tools > Developer > Run JavaScript, tick
// "Run as async function", click Run. Moves the annotations created by the matching import to the Zotero trash
// (restorable there) and removes the item tag "ai-draft" where that import added it. Nothing else is touched.
const ITEMS = __ITEMS__;
const lib = Zotero.Libraries.userLibraryID;
const get = (k) => Zotero.Items.getByLibraryAndKeyAsync(lib, k);
const report = [];
for (const it of ITEMS) {
  const att = await get(it.pdf), item = await get(it.item);
  const trashed = [];
  for (const k of it.keys) {
    const a = await get(k);
    if (a && a.parentID === att.id && a.hasTag("AI") && !a.deleted) { a.deleted = true; await a.saveTx(); trashed.push(k); }
  }
  let tagRemoved = false;
  if (!it.hadDraftTag && item.hasTag("ai-draft")) { item.removeTag("ai-draft"); await item.saveTx(); tagRemoved = true; }
  report.push({citekey: it.citekey, trashed, tagRemoved});
}
return {status: "moved to trash", report};
"""


def build_scripts(items, undo, run, alongside):
    """(import script, undo script) for Zotero's Run JavaScript; one annotation per line keeps them pasteable."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    items_js = "[\n" + ",\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n]"
    js = (IMPORT_JS.replace("__STAMP__", stamp).replace("__RUN_DIR__", json.dumps(str(run)))
          .replace("__ALONGSIDE__", "true" if alongside else "false").replace("__ITEMS__", items_js))
    undo_js = UNDO_JS.replace("__STAMP__", stamp).replace("__ITEMS__", json.dumps(undo, ensure_ascii=False, indent=1))
    return js, undo_js


def cmd_zotero_script(a):
    run = pathlib.Path(a.run_dir).resolve()
    batch = load(run / "batch.json")
    items, undo = [], []
    stale = [row["citekey"] for row in batch["items"] if row["status"] == "ready" and (run / row["citekey"] / "payload.json").exists()
             and load(run / row["citekey"] / "placement.json").get("inputs") != place_inputs(run / row["citekey"] / "reading.json", row)]
    if stale:
        die(f"reading.json changed after the last successful place for {stale}: run place again and fix what it reports")
    owner = {}
    for row in batch["items"]:  # parallel place runs could draw the same key; a batch place gives the duplicates new keys
        pp = run / row["citekey"] / "payload.json"
        for p in (load(pp) if row["status"] == "ready" and pp.exists() else []):
            if p["key"] in owner:
                die(f"annotation key {p['key']} appears twice ({owner[p['key']]}, {row['citekey']}): run place --run-dir <run> "
                    "once for the whole batch, which places such papers again with new keys")
            owner[p["key"]] = row["citekey"]
    for row in batch["items"]:
        pp = run / row["citekey"] / "payload.json"
        if row["status"] != "ready" or not pp.exists():
            continue
        payload = [{k: v for k, v in p.items() if not k.startswith("_")} for p in load(pp)]
        item = api(f"items/{row['item_key']}")["data"]
        kids = [c["data"] for c in api_all(f"items/{row['item_key']}/children")]
        save(run / row["citekey"] / "before.json", {"item": item, "children": kids})
        had = any(t["tag"] == DRAFT_TAG for t in item.get("tags", []))
        items.append({"citekey": row["citekey"], "item": row["item_key"], "pdf": row["pdf_key"], "title": item["title"],
                      "annotations": payload})
        undo.append({"citekey": row["citekey"], "item": row["item_key"], "pdf": row["pdf_key"],
                     "keys": [p["key"] for p in payload], "hadDraftTag": had})
    if not items:
        die("nothing placed yet (run place first)")
    if len(items) > MAX_BATCH:
        die(f"{len(items)} papers; keep one pasted script to {MAX_BATCH}")
    js, undo_js = build_scripts(items, undo, run, batch.get("alongside"))
    (run / "import-ai-annotations.js").write_text(js, encoding="utf-8")
    (run / "undo-ai-annotations.js").write_text(undo_js, encoding="utf-8")
    print(f"import script for {len(items)} papers ({sum(len(i['annotations']) for i in items)} annotations): {run / 'import-ai-annotations.js'}")
    print(f"undo script: {run / 'undo-ai-annotations.js'}")


# ---------------------------------------------------------------- verify
def cmd_verify(a):
    run = pathlib.Path(a.run_dir)
    batch = load(run / "batch.json")
    rp = run / "zotero-import-result.json"
    if not rp.exists():
        die("zotero-import-result.json not found: has the import script been run in Zotero?")
    res = {r["citekey"]: r for r in load(rp)["items"]}
    ok_all = True
    for row in batch["items"]:
        ck = row["citekey"]
        if ck not in res:
            continue
        sent = {p["key"]: p for p in load(run / ck / "payload.json")}
        live = {x["data"]["key"]: x["data"] for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")}
        problems = []
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
        if not any(t["tag"] == DRAFT_TAG for t in now.get("tags", [])):
            problems.append("item tag ai-draft missing")
        kids_before = {c["key"] for c in before["children"] if not c.get("deleted")}
        kids_now = {c["data"]["key"] for c in api_all(f"items/{row['item_key']}/children") if not c["data"].get("deleted")}
        if kids_now != kids_before:
            problems.append(f"child items changed: {sorted(kids_now ^ kids_before)}")
        if not res[ck].get("noteHtml"):
            problems.append(f"annotation-note HTML not written: {res[ck].get('writeError')}")
        row["verified"] = not problems
        ok_all &= not problems
        print(f"{ck}: {'OK' if not problems else 'PROBLEMS'} ({len(sent)} annotations)")
        for p in problems:
            print("   -", p)
    save(run / "batch.json", batch)
    if not ok_all:
        sys.exit(1)


# ---------------------------------------------------------------- note
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


def headless(lib, tmp_vault, citekey, storage=None, note_html=None, existing=None):
    cmd = ["node", str(HERE / "bibnotes_headless.js"), "--plugin-dir", str(lib.plugin), "--bbt-json", str(lib.bbt_path),
           "--vault", str(tmp_vault), "--citekey", citekey]
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


def merge_inserts(lib, tmp, name, ck, storage, html, existing):
    """Simulate Ctrl+P "Update Current Note" on `existing`; return the merged note and the inserted lines."""
    p = pathlib.Path(tmp) / f"{name}.md"
    p.write_text(existing, encoding="utf-8", newline="\n")
    merged, _ = headless(lib, pathlib.Path(tmp) / name, ck, storage, html, p)
    return merged, [l[2:] for l in difflib.ndiff(existing.splitlines(), merged.splitlines()) if l.startswith("+ ")]


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
    text = re.sub(r"(\*\*open pdf\*\*: \[[^\]]+\])\((?:file:///|zotero://)[^)]*\)", rf"\1(zotero://open-pdf/library/items/{pdf_key})", text)
    return text if text.endswith("\n") else text + "\n"


def cmd_note(a):
    run = pathlib.Path(a.run_dir).resolve()
    batch = load(run / "batch.json")
    lib = library_of(batch)
    img_dir = lib.settings.get("imagesPath", "Linked files")
    lines = [f"# zotero-ai-reading run {run.name}", ""]
    for row in batch["items"]:
        ck = row["citekey"]
        if row["status"] != "ready":
            lines.append(f"- {ck}: skipped ({row.get('reason')})"); continue
        if not row.get("verified"):
            lines.append(f"- {ck}: not verified in Zotero yet"); continue
        note_path = pathlib.Path(row["note_path"])
        if row.get("note_written") and note_path.exists() and not a.replace_ai_draft:
            lines.append(f"- {ck}: note written by an earlier `note` run: {note_path.relative_to(lib.vault)}"); continue
        if note_path.exists() and not (a.replace_ai_draft and re.search(r'^note_status: "?AI draft', note_path.read_text(encoding="utf-8")[:3000], re.M)):
            lines.append(f"- {ck}: STOP, a note appeared at {note_path}"); continue
        if not lib.wait_for_tag(ck, DRAFT_TAG, timeout=a.wait):
            lines.append(f"- {ck}: Better BibTeX export does not show the ai-draft tag yet; rerun `note` in a minute"); continue
        reading = load(run / ck / "reading.json")
        storage = run / ck / "storage"
        conv = convert_note_html((run / ck / "annotation-note.html").read_text(encoding="utf-8"), storage)
        (run / ck / "annotation-note-for-bibnotes.html").write_text(conv, encoding="utf-8")
        with tempfile.TemporaryDirectory() as td:
            text, notices = headless(lib, pathlib.Path(td) / "render", ck, storage, run / ck / "annotation-note-for-bibnotes.html")
            bad_notices = [n for n in notices if not n.startswith("Imported")]
            text = fill_note(text, reading, row["pdf_key"], a.agent)
            problems = []
            if yaml_problem(text):
                problems.append(yaml_problem(text))
            if any(re.search(r"[<>]", m) for m in re.findall(r"<mark[^>]*>(.*?)</mark>", text)):
                problems.append("< or > inside <mark>")
            images = re.findall(r"!\[\[([^\]]+\.png)\]\]", text)
            missing = [i for i in images if not (pathlib.Path(td) / "render" / img_dir / i).exists()]
            if missing or bad_notices:
                problems.append(f"images missing {missing} {bad_notices}")
            html = run / ck / "annotation-note-for-bibnotes.html"
            again, inserted = merge_inserts(lib, td, "merge", ck, storage, html, text)
            always = [l for l in inserted if len(bibnotes_key(l)) <= 1]  # BibNotes quirk; the user's own notes show it too
            once = [l for l in inserted if re.match(r"- \*\*open pdf\*\*: \[[^\]]*\]\(file:///", l)]  # short PDF title
            other = [l for l in inserted if l not in always and l not in once]
            if once:  # BibNotes's own PDF line comes in once; a second update must add nothing new
                _, inserted2 = merge_inserts(lib, td, "merge2", ck, storage, html, again)
                other += [l for l in inserted2 if len(bibnotes_key(l)) > 1]
            if other or yaml_problem(again):
                problems.append(f"re-update not clean: {len(other)} inserted lines {[l[:60] for l in other[:3]]}, {yaml_problem(again)}")
            notes = []
            if any(bibnotes_key(l) for l in always):
                shown = sorted({bibnotes_key(l) for l in always if bibnotes_key(l)})
                notes.append(f"each Ctrl+P update re-adds the one-character line(s) {shown}, a BibNotes quirk"
                             + (" (the Zotero abstract is empty)" if re.search(r"^> \[!Abstract\]\n> ?\n(?!>)", text, re.M) else ""))
            if once:
                notes.append("the first Ctrl+P update adds BibNotes's own file:/// 'open pdf' line (the PDF's Zotero title is short)")
            if problems:
                (run / ck / "note-rejected.md").write_text(text, encoding="utf-8", newline="\n")
                lines.append(f"- {ck}: NOT written ({'; '.join(problems)}); draft in {run / ck / 'note-rejected.md'}"); continue
            for i in images:
                dst = lib.vault / img_dir / i
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(pathlib.Path(td) / "render" / img_dir / i, dst)
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(text, encoding="utf-8", newline="\n")
        placement = load(run / ck / "placement.json")
        row["note_written"] = str(note_path)
        lines.append(f"- {ck}: note written ({placement['placed']} annotations, {len(images)} pictures, "
                     f"{len(placement['dropped'])} dropped): {note_path.relative_to(lib.vault)}"
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
    s.add_argument("--alongside", action="store_true", help="also annotate papers that already have annotations (only on request)")
    s.add_argument("--replace-ai-draft", action="store_true", help="allow replacing an earlier AI-draft note")
    for name in ("zotero-script", "verify"):
        sub.add_parser(name).add_argument("--run-dir", required=True)
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
    s.add_argument("--replace-ai-draft", action="store_true")
    a = p.parse_args()
    if getattr(a, "limit", MAX_BATCH) > MAX_BATCH:
        die(f"batches are limited to {MAX_BATCH} papers")
    {"prepare": cmd_prepare, "pagemap": cmd_pagemap, "place": cmd_place, "zotero-script": cmd_zotero_script,
     "verify": cmd_verify, "note": cmd_note}[a.cmd](a)


if __name__ == "__main__":
    main()
