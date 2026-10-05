"""paper-library-maintenance: housekeeping for a Zotero-managed Paper Library.

relocate: after a PDF was moved or renamed (for example by Zotero Attanger), put its converted Markdown, the Markdown's
assets folder and its Obsidian note back where they belong. Unambiguous moves are applied; everything else is reported.

  conversion  Paper.md (+ Paper.assets) with no Paper.pdf beside it. A mineru-/marker-batch-convert marker identifies
              the PDF by size and SHA-256; Markdown without a marker by an identical file name. Only a PDF that has no
              Markdown or assets of its own can receive it. When the PDF was renamed, the files are renamed with it and
              the marker's sourcePdf/assetsDirectory and the image links are updated, so both converters still report
              the conversion as current.
  note        @citekey.md in the vault folder that mirrors the PDF's folder (found through the Better BibTeX export
              that BibNotes reads). A note elsewhere is moved there; duplicates and conflicts are reported.

Nothing is overwritten or deleted. usage:
  library_maintenance.py relocate --library-root <Paper Library> [--vault <vault>] [--dry-run] [--report <file.json>]
"""
import argparse, datetime, hashlib, json, os, pathlib, re, sys
from urllib.parse import quote, unquote

VERSION = "0.1.0"
MARKER = re.compile(r"^<!--\s*(mineru|marker)-batch-convert\s+(\{.*\})\s*-->")
IMG_MD = re.compile(r"(!\[(?:[^\[\]\\]|\\.|\[[^\[\]]*\])*\]\(\s*)(<[^>\n]+>|[^\s()<>]+(?:\([^\s()]*\)[^\s()<>]*)*)((?:\s+\"[^\"]*\")?\s*\))")
IMG_HTML = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(.*?)\2", re.I | re.S)
REF_DEF = re.compile(r"(?m)^(\s{0,3}\[[^\]\r\n]+\]:[ \t]*)(<[^>\r\n]+>|\S+)")


def linked(p):
    try:
        return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
    except OSError:
        return True


def walk(root, skip=()):
    """Files under root, not following links or entering hidden folders or those in skip."""
    skip = {os.path.normcase(str(s)) for s in skip}
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if not x.startswith(".") and x.lower() != "$recycle.bin"
                   and os.path.normcase(os.path.join(d, x)) not in skip and not linked(pathlib.Path(d, x))]
        for f in files:
            yield pathlib.Path(d, f)


def file_size(p):
    try:
        return p.stat().st_size
    except OSError:  # moved or removed while the library was being scanned (sync, a move in progress)
        return None


def sha256(p, cache):
    if p not in cache:
        h = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            cache[p] = h.hexdigest()
        except OSError:
            cache[p] = None
    return cache[p]


def first_line(p):
    with open(p, "rb") as f:
        return f.readline().decode("utf-8", "replace")


# ---------- conversions ----------

def retarget(text, old_assets, new_assets, pdf_name):
    """Marker and image links of a conversion whose PDF was renamed: sourcePdf, assetsDirectory and every image
    destination that starts with the old assets folder (kept plain, <...> or percent-encoded as it was)."""
    nl = "\r\n" if text.split("\n", 1)[0].endswith("\r") else "\n"
    head, body = text.split(nl, 1) if nl in text else (text, "")
    m = MARKER.match(head)
    data = json.loads(m.group(2))
    data["sourcePdf"] = pdf_name
    if data.get("assetsDirectory"):
        data["assetsDirectory"] = new_assets
    head = f"<!-- {m.group(1)}-batch-convert {json.dumps(data, ensure_ascii=False, separators=(',', ':'))} -->"
    changed = []

    def dest(raw):
        wrapped = raw.startswith("<") and raw.endswith(">")
        inner = raw[1:-1] if wrapped else raw
        seg, sep, rest = inner.partition("/")
        if not sep or unquote(seg) != old_assets:
            return raw
        encode = seg != unquote(seg) or (not wrapped and re.search(r"[\s()<>%]", new_assets))
        new = (quote(new_assets, safe="") if encode else new_assets) + "/" + rest
        changed.append(unquote(rest))
        return f"<{new}>" if wrapped else new

    body = IMG_MD.sub(lambda m: m.group(1) + dest(m.group(2)) + m.group(3), body)
    body = IMG_HTML.sub(lambda m: m.group(1) + m.group(2) + dest(m.group(3)) + m.group(2), body)
    body = REF_DEF.sub(lambda m: m.group(1) + dest(m.group(2)), body)
    return head + nl + body, changed


def plan_conversions(root, vault, cache):
    pdfs, mds, assets = {}, [], []
    for p in walk(root, skip=[vault]):
        s = p.suffix.lower()
        if s == ".pdf":
            pdfs[p] = None
        elif s == ".md":
            mds.append(p)
    for d, dirs, _ in os.walk(root):
        for x in dirs:
            if x.endswith(".assets"):
                assets.append(pathlib.Path(d, x))
    has = lambda pdf: pdf.with_suffix(".md").exists() or (pdf.parent / (pdf.stem + ".assets")).exists()
    free = [p for p in pdfs if not has(p)]
    items, claimed = [], {}
    for md in sorted(mds):
        if (md.with_suffix(".pdf").exists() or vault in md.parents
                or any(x.name.endswith(".assets") for x in md.parents)):
            continue
        a = md.parent / (md.stem + ".assets")
        item = {"kind": "conversion", "from": str(md), "assets": str(a) if a.is_dir() else None}
        if linked(md) or (a.exists() and linked(a)):
            items.append(dict(item, status="review", reason="symlink or junction")); continue
        m = MARKER.match(first_line(md))
        data = None
        if m:
            try:
                data = json.loads(m.group(2))
                if str(data.get("sourcePdf", "")).lower() != (md.stem + ".pdf").lower():
                    raise ValueError("marker names another PDF")
                if int(data.get("assetCount") or 0) > 0 and not a.is_dir():
                    raise ValueError("assets folder missing")
            except (ValueError, TypeError) as e:
                items.append(dict(item, status="review", reason=f"conversion marker: {e}")); continue
        size = data.get("sourceLength") if data else None
        cands = [p for p in free if size is None or file_size(p) == int(size)]
        if data and data.get("sourceSha256"):
            want = str(data["sourceSha256"]).lower()
            how = "SHA-256"
            cands = [p for p in cands if sha256(p, cache) == want]
        else:
            how = "file name"
            cands = [p for p in cands if p.stem.casefold() == md.stem.casefold()]
        item.update(match=how, converter=m.group(1) if m else None)
        if not cands:
            if m:  # Markdown without a marker and without a same-named PDF is just a document (README, notes ...)
                items.append(dict(item, status="no-pdf", reason=f"no unconverted PDF in the library matches by {how}"))
        elif len(cands) > 1:
            items.append(dict(item, status="ambiguous", candidates=[str(c) for c in cands]))
        else:
            items.append(dict(item, status="planned", to=str(cands[0].with_suffix(".md")), pdf=str(cands[0])))
            claimed.setdefault(cands[0], []).append(items[-1])
    for pdf, its in claimed.items():  # two conversions for one PDF: move neither
        if len(its) > 1:
            for it in its:
                it.update(status="ambiguous", reason="several conversions match this PDF", candidates=[str(pdf)])
    for a in sorted(assets):
        if not (a.parent / (a.name[:-7] + ".md")).exists() and not (a.parent / (a.name[:-7] + ".pdf")).exists() \
                and vault not in a.parents:
            items.append({"kind": "conversion", "from": str(a), "status": "review", "reason": "assets folder without Markdown or PDF"})
    return items


def move_conversion(item, dry):
    md, pdf = pathlib.Path(item["from"]), pathlib.Path(item["pdf"])
    a = pathlib.Path(item["assets"]) if item["assets"] else None
    new_md, new_a = pdf.with_suffix(".md"), pdf.parent / (pdf.stem + ".assets")
    rename = md.stem != pdf.stem
    text = None
    if rename:
        raw = md.read_bytes().decode("utf-8")
        if MARKER.match(raw.split("\n", 1)[0].rstrip("\r")):
            text, refs = retarget(raw, md.stem + ".assets", new_a.name, pdf.name)
            missing = [r for r in refs if a is None or not (a / r).is_file()]
            if missing:
                return dict(item, status="review", reason=f"{len(missing)} image link(s) point to missing files, e.g. {missing[0]}")
        else:  # untracked Markdown is matched by name only, so a rename cannot happen here
            return dict(item, status="review", reason="untracked Markdown with a different name")
    item = dict(item, renamed=rename, to=str(new_md), assetsTo=str(new_a) if a else None)
    if dry:
        return item
    done = []
    try:
        if a:
            os.rename(a, new_a); done.append((a, new_a))
        os.rename(md, new_md); done.append((md, new_md))
        if text is not None:
            tmp = new_md.with_name(new_md.name + ".relocate-tmp")
            tmp.write_bytes(text.encode("utf-8"))
            os.replace(tmp, new_md)
    except OSError as e:
        for src, dst in reversed(done):
            try:
                os.rename(dst, src)
            except OSError:
                pass
        return dict(item, status="failed", reason=f"{type(e).__name__}: {e}")
    return dict(item, status="moved")


# ---------- notes ----------

def library_rel(root, path):
    """Path relative to the library root from an absolute path on any drive or a Zotero 'attachments:' path."""
    s = str(path)
    if s.startswith("attachments:"):
        s = s[len("attachments:"):]
    parts = pathlib.PureWindowsPath(s.replace("/", "\\")).parts
    return pathlib.Path(*parts[parts.index(root.name) + 1:]) if root.name in parts else None


def plan_notes(root, vault):
    cfg = vault / ".obsidian" / "plugins" / "bibnotes" / "data.json"
    if not cfg.exists():
        return [], f"no BibNotes settings at {cfg}; notes were not checked"
    s = json.loads(cfg.read_text(encoding="utf-8"))
    bbt = vault / s["bibPath"]
    if not bbt.exists():
        return [], f"no Better BibTeX export at {bbt}; notes were not checked"
    title = s.get("exportTitle", "@{{citeKey}}")
    pre, _, post = re.sub(r"\{\{cite[Kk]ey\}\}", "\0", title).partition("\0")
    pat = re.compile(re.escape(pre) + r"(.+)" + re.escape(post) + r"\.md$")
    entries = {e.get("citationKey"): e for e in json.loads(bbt.read_text(encoding="utf-8")).get("items", [])}
    images = vault / s.get("imagesPath", "Linked files")
    notes = {}
    for p in walk(vault, skip=[images]):
        m = pat.fullmatch(p.name)
        if m and m.group(1) in entries:
            notes.setdefault(m.group(1), []).append(p)
    items = []
    for ck, ps in sorted(notes.items()):
        rels = [library_rel(root, a.get("path") or "") for a in entries[ck].get("attachments", [])
                if (a.get("path") or "").lower().endswith(".pdf")]
        rels = [r for r in rels if r is not None]
        on_disk = [r for r in rels if (root / r).exists()]
        item = {"kind": "note", "citekey": ck, "from": [str(p) for p in ps]}
        folders = {r.parent for r in on_disk}
        if not on_disk:
            if rels:
                items.append(dict(item, status="review", reason="the Better BibTeX export names a PDF that is not on disk (export not updated yet?)"))
            continue
        if len(folders) > 1:
            items.append(dict(item, status="ambiguous", reason="the item has PDFs in several folders", candidates=[str(f) for f in folders]))
            continue
        want = vault / folders.pop()
        if any(p.parent == want for p in ps):
            if len(ps) > 1:
                items.append(dict(item, status="review", reason="duplicate notes; the one in the right folder was kept, others left as they are"))
            continue
        if len(ps) > 1:
            items.append(dict(item, status="ambiguous", reason="several notes for this item, none in the right folder"))
            continue
        dest = want / ps[0].name
        if dest.exists():
            items.append(dict(item, status="conflict", to=str(dest)))
            continue
        items.append(dict(item, status="planned", **{"from": str(ps[0]), "to": str(dest)}))
    return items, None


def move_note(item, dry):
    if dry:
        return item
    src, dst = pathlib.Path(item["from"]), pathlib.Path(item["to"])
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dst)
    except OSError as e:
        return dict(item, status="failed", reason=f"{type(e).__name__}: {e}")
    return dict(item, status="moved")


# ---------- command ----------

def relocate(a):
    root = pathlib.Path(a.library_root).resolve()
    vault = pathlib.Path(a.vault).resolve() if a.vault else root / "Zoteronotes"
    if not root.is_dir():
        sys.exit(f"library root not found: {root}")
    started = datetime.datetime.now(datetime.timezone.utc)
    cache, warnings = {}, []
    items = [move_conversion(i, a.dry_run) if i["status"] == "planned" else i for i in plan_conversions(root, vault, cache)]
    notes, warn = plan_notes(root, vault) if vault.is_dir() else ([], f"vault not found: {vault}; notes were not checked")
    if warn:
        warnings.append(warn)
    items += [move_note(i, a.dry_run) if i["status"] == "planned" else i for i in notes]
    counts = {}
    for i in items:
        counts[f"{i['kind']} {i['status']}"] = counts.get(f"{i['kind']} {i['status']}", 0) + 1
    report = {"action": "relocate", "skillVersion": VERSION, "dryRun": a.dry_run, "libraryRoot": str(root), "vault": str(vault),
              "startedUtc": started.isoformat(timespec="seconds"), "pdfsHashed": len(cache), "counts": counts,
              "warnings": warnings, "items": items}
    path = pathlib.Path(a.report) if a.report else (pathlib.Path(os.environ.get("LOCALAPPDATA") or pathlib.Path.home())
                                                    / "paper-library-maintenance" / "reports"
                                                    / f"relocate-{started:%Y%m%d-%H%M%S}{'-dry' if a.dry_run else ''}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print(f"{'DRY RUN: nothing moved. ' if a.dry_run else ''}{json.dumps(counts, ensure_ascii=False)}; {len(cache)} PDF(s) hashed")
    for w in warnings:
        print("warning:", w)
    for i in items:
        if i["status"] in ("moved", "planned"):
            print(f"  {i['status']}: {i['from']}\n        -> {i['to']}{' (renamed)' if i.get('renamed') else ''}")
    for i in items:
        if i["status"] not in ("moved", "planned"):
            print(f"  {i['status']}: {i['from']}  {i.get('reason', '')} {i.get('candidates', '') or ''}".rstrip())
    print("report:", path)
    return 1 if any(i["status"] == "failed" for i in items) else 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("relocate", help="put conversions and notes back beside moved or renamed PDFs")
    r.add_argument("--library-root", required=True)
    r.add_argument("--vault", help="Obsidian vault (default <library root>/Zoteronotes)")
    r.add_argument("--dry-run", action="store_true", help="report what would move; change nothing")
    r.add_argument("--report", help="report path (default %%LOCALAPPDATA%%/paper-library-maintenance/reports/)")
    a = p.parse_args(argv)
    return relocate(a)


if __name__ == "__main__":
    sys.exit(main())
