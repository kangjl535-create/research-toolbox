"""zotero-ai-reading: AI annotations in Zotero + BibNotes-compatible Obsidian notes for unread papers.

Steps (each reads and writes files in one run directory):
  prepare        select papers, check them, run OCR for scans                 -> batch.json
  (agent)        write <citekey>/reading.json for each ready paper (see references/reading.md)
  place          validate readings, place highlights/regions on the PDF pages  -> <citekey>/payload.json, previews
  write          write the AI annotations and the item tag ai-draft to Zotero  -> zotero-write-result.json, undo-plan.json
  verify         compare Zotero (read-only) with what was sent
  note           make the annotation note HTML, write and check the Obsidian notes -> report.md
  undo           (on request) move this run's AI annotations to the Zotero trash, remove the ai-draft tags it added
Only write and undo change Zotero, through the Zotero 10 local API (POST only: trashing is `deleted: 1`, never DELETE).
"""
import argparse, base64, datetime, difflib, hashlib, json, pathlib, re, secrets, shutil, subprocess, sys, tempfile, unicodedata, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import yaml
import pymupdf, PIL.Image, PIL.ImageDraw
from zar_common import (Library, api, api_all, api_status, zotero_available, mineru_markdown, ZoteroWriter, WriteError,
                        zotero_prefs, note_format_problem,
                        COLORS, FIELDS, KEY_CHARS)
import note_html as nh
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


def cmd_write(a, writer=None):
    run = pathlib.Path(a.run_dir).resolve()
    batch = load(run / "batch.json")
    rows = placed_rows(run, batch)
    if not rows:
        die("nothing placed yet (run place first)")
    if len(rows) > MAX_BATCH:
        die(f"{len(rows)} papers; write at most {MAX_BATCH} per run")
    if (run / "zotero-write-result.json").exists():
        die("this run has already written to Zotero (zotero-write-result.json); verify it, or undo it and use a new run directory for another write")
    plan, undo = [], []
    for row in rows:  # every check before any change
        ck = row["citekey"]
        payload = [{k: v for k, v in p.items() if not k.startswith("_")} for p in load(run / ck / "payload.json")]
        item, att = api(f"items/{row['item_key']}")["data"], api(f"items/{row['pdf_key']}")["data"]
        if item["title"] != row["title"]:
            die(f"{ck}: the Zotero title differs from the one prepare saw ({item['title'][:60]!r}): run prepare again")
        if att.get("parentItem") != row["item_key"] or att.get("contentType") != "application/pdf":
            die(f"{ck}: {row['pdf_key']} is no longer this item's PDF attachment")
        live = [x["data"] for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation") if not x["data"].get("deleted")]
        if live and not batch.get("alongside"):
            die(f"{ck}: the PDF has annotations now ({len(live)}); use --alongside only on request")
        if any(t["tag"] == AI_TAG for x in live for t in x.get("tags", [])):
            die(f"{ck}: AI annotations already exist on this PDF")
        used = [p["key"] for p in payload if api_status(f"items/{p['key']}") != 404]
        if used:
            die(f"{ck}: annotation keys already in use in Zotero: {used}")
        kids = [c["data"] for c in api_all(f"items/{row['item_key']}/children")]
        save(run / ck / "before.json", {"item": item, "children": kids})
        had = any(t["tag"] == DRAFT_TAG for t in item.get("tags", []))
        plan.append((ck, row, payload, item, had))
        undo.append({"citekey": ck, "item": row["item_key"], "pdf": row["pdf_key"], "keys": [p["key"] for p in payload], "hadDraftTag": had})
    entries, owner = [], []
    for ck, row, payload, item, had in plan:
        for p in payload:
            entries.append(annotation_entry(p, row["pdf_key"])); owner.append((ck, p["key"]))
        if not had:  # the item's own tags are sent back as read (with their types), plus ai-draft
            entries.append({"key": row["item_key"], "version": item["version"], "tags": item.get("tags", []) + [{"tag": DRAFT_TAG}]})
            owner.append((ck, None))
    save(run / "undo-plan.json", undo)  # before the change: undo works even if the write is interrupted
    writer = writer or ZoteroWriter()
    try:
        outcome = writer.post_items(entries)
    except WriteError as e:
        die(str(e))
    result = {"written": datetime.datetime.now().isoformat(timespec="seconds"), "items": []}
    for ck, row, payload, item, had in plan:
        mine = [(k, o) for (c, k), o in zip(owner, outcome) if c == ck]
        created = [k for k, o in mine if k and o[0] == "ok"]
        failed = [{"key": k or row["item_key"], **o[1]} for k, o in mine if o[0] == "failed"]
        tag_added = (not had) and any(k is None and o[0] == "ok" for k, o in mine)
        result["items"].append({"citekey": ck, "created": created, "tagAdded": tag_added, "failed": failed})
        print(f"{ck}: {len(created)}/{len(payload)} annotations written, ai-draft tag {'added' if tag_added else 'already there' if had else 'NOT added'}")
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
    entries, owner = [], []
    for it in plan:
        for k in it["keys"]:
            if api_status(f"items/{k}?includeTrashed=1") != 200:
                continue  # never written
            d = api(f"items/{k}?includeTrashed=1")["data"]
            if d.get("parentItem") != it["pdf"] or AI_TAG not in [t["tag"] for t in d.get("tags", [])]:
                print(f"{it['citekey']}: {k} is not this run's AI annotation any more, left alone"); continue
            if not d.get("deleted"):
                entries.append({"key": k, "version": d["version"], "deleted": 1}); owner.append(it["citekey"])
        item = api(f"items/{it['item']}")["data"]
        tags = item.get("tags", [])
        if not it["hadDraftTag"] and any(t["tag"] == DRAFT_TAG for t in tags):
            entries.append({"key": it["item"], "version": item["version"], "tags": [t for t in tags if t["tag"] != DRAFT_TAG]})
            owner.append(it["citekey"])
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
        left = [k for k in it["keys"] if api_status(f"items/{k}?includeTrashed=1") == 200
                and not api(f"items/{k}?includeTrashed=1")["data"].get("deleted")]
        still = any(t["tag"] == DRAFT_TAG for t in api(f"items/{it['item']}")["data"].get("tags", []))
        print(f"{it['citekey']}: {len(it['keys']) - len(left)}/{len(it['keys'])} AI annotations in the Zotero trash (restorable there)"
              + (f", NOT trashed: {left}" if left else "") + ("" if it["hadDraftTag"] else f", ai-draft tag {'still on the item' if still else 'removed'}"))
        note = next((r.get("note_written") for r in batch["items"] if r["citekey"] == it["citekey"] and r.get("note_written")), None)
        if note and pathlib.Path(note).exists():
            print(f"   the note {note} and its pictures stay in the vault: move them out (do not delete) if they should go")


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
        if not any(t["tag"] == DRAFT_TAG for t in now.get("tags", [])):
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
def annotation_note(run, row):
    """annotation-note.html as Zotero's "Add Note from Annotations" without saving (createNoteFromAnnotations,
    noSave) would make it now, from the PDF's live annotations; frame pictures rendered from the PDF.
    Returns (html, annotations in note order)."""
    item = api(f"items/{row['item_key']}")
    lib_id = item.get("library", {}).get("id")
    if not lib_id:
        raise RuntimeError("Zotero reports no user library ID (signed out of Zotero sync?): annotation links need it")
    csl = api(f"items/{row['item_key']}?format=csljson")
    csl = (csl.get("items") or [csl])[0] if isinstance(csl, dict) else csl[0]
    parent_uri = f"http://zotero.org/users/{lib_id}/items/{row['item_key']}"
    written = [p["key"] for p in load(run / row["citekey"] / "payload.json")]
    anns = nh.note_order([nh.annotation_json(x["data"]) for x in api_all(f"items/{row['pdf_key']}/children?itemType=annotation")
                          if not x["data"].get("deleted")], created=written)
    doc = pymupdf.open(row["pdf"])
    for x in anns:
        if x["type"] == "image":
            x["image"] = nh.data_uri(nh.render_frame(doc, x))
    html = nh.build_note(anns, f"http://zotero.org/users/{lib_id}/items/{row['pdf_key']}", parent_uri, {**csl, "id": parent_uri})
    return html, anns


def note_problems(text, anns, written, pdf_key):
    """Every AI annotation linked in the rendered note, every frame with its picture, no broken placeholders."""
    probs = []
    keys = {x["id"] for x in anns}
    gone = [k for k in written if k not in keys]
    if gone:
        probs.append(f"AI annotations no longer in Zotero: {gone}")
    unlinked = [k for k in written if k in keys and not re.search(rf"items/{pdf_key}\?page=\d+&annotation={k}\b", text)]
    if unlinked:
        probs.append(f"annotations without their link in the note: {unlinked}")
    images = re.findall(r"!\[\[([^\]]+\.png)\]\]", text)
    no_pic = [x["id"] for x in anns if x["type"] == "image" and not any(x["id"] in i for i in images)]
    if no_pic:
        probs.append(f"frames without their picture in the note: {no_pic}")
    for bad in ("[Image not available]", "page=undefined", "annotation=)"):
        if bad in text:
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
        if row.get("note_written") and note_path.exists() and not a.replace_ai_draft:
            lines.append(f"- {ck}: note written by an earlier `note` run: {note_path.relative_to(lib.vault)}"); continue
        if note_path.exists() and not (a.replace_ai_draft and re.search(r'^note_status: "?AI draft', note_path.read_text(encoding="utf-8")[:3000], re.M)):
            lines.append(f"- {ck}: STOP, a note appeared at {note_path}"); continue
        if not lib.wait_for_tag(ck, DRAFT_TAG, timeout=a.wait):
            lines.append(f"- {ck}: Better BibTeX export does not show the ai-draft tag yet; rerun `note` in a minute"); continue
        reading = load(run / ck / "reading.json")
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
    for name in ("write", "verify", "undo"):
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
    {"prepare": cmd_prepare, "pagemap": cmd_pagemap, "place": cmd_place, "write": cmd_write,
     "verify": cmd_verify, "note": cmd_note, "undo": cmd_undo}[a.cmd](a)


if __name__ == "__main__":
    main()
