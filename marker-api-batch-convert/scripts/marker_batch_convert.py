"""Convert authorized PDFs to same-directory Markdown + image assets through the Datalab (Marker) Convert API.

Actions:
  environment                       report the executing copy, dependencies and whether a key is configured
  scan     (--pdf ... | --root ...) classify outputs next to each PDF; no upload, no key needed
  convert  (--pdf ... | --root ...) upload Missing PDFs, resume recorded jobs, publish Paper.md + Paper.assets/

Output contract (same as mineru-api-batch-convert): Paper.pdf unchanged, Paper.md whose first line is an
ownership marker, and Paper.assets/ holding only the images the Markdown references. Existing outputs are never
overwritten. Checkpoints, payloads and reports live in machine-local storage, never beside the papers.
The API key (MARKER_API_KEY or DATALAB_API_KEY, process or Windows user environment) is never printed or stored.
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import io
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import requests
from PIL import Image

SKILL_VERSION = "0.1.0"
DEFAULT_API = "https://www.datalab.to/api/v1"
MARKER_RE = re.compile(r"<!--\s*marker-batch-convert\s+(\{.*\})\s*-->")
MINERU_RE = re.compile(r"<!--\s*mineru-batch-convert\s+(\{.*\})\s*-->")
PARTIAL = ".marker-partial-"
KEY_NAMES = ("MARKER_API_KEY", "DATALAB_API_KEY")


class Fail(Exception):
    """Definite failure for one PDF; the message is safe to report."""


class Uncertain(Exception):
    """The upload may have reached Datalab; the 'submitting' checkpoint is kept to prevent a duplicate job."""


class Pending(Exception):
    """Accepted job still running at the deadline; rerun to resume it without uploading again."""


class Review(Exception):
    """Something next to the paper needs a person to look before anything is written."""


class AuthError(Exception):
    """Datalab rejected the key; stop all API work."""


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, data):
    tmp = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def safe_text(value, limit=300):
    """A short, single-line API message with any URL removed (signed URLs must never reach a log)."""
    text = re.sub(r"https?://\S+", "<url>", str(value or ""))
    return " ".join(text.split())[:limit]


# ---------- configuration ----------

def api_base():
    return os.environ.get("MARKER_API_BASE", DEFAULT_API).rstrip("/")


def test_mode():
    return api_base() != DEFAULT_API


def data_dir():
    override = os.environ.get("MARKER_BATCH_LOCAL_DATA")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AI-Config" / "marker-api-batch-convert"
    base.mkdir(parents=True, exist_ok=True)
    return base


def load_key():
    """(key, source name). Process environment first, then the Windows user environment (only for the real API)."""
    for name in KEY_NAMES:
        value = os.environ.get(name, "").strip()
        if value:
            return value, f"process:{name}"
    if os.name == "nt" and not test_mode():
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as env:
                for name in KEY_NAMES:
                    try:
                        value = str(winreg.QueryValueEx(env, name)[0]).strip()
                    except FileNotFoundError:
                        continue
                    if value:
                        return value, f"user:{name}"
        except OSError:
            pass
    return None, None


# ---------- outputs next to a PDF ----------

def outputs(pdf):
    return pdf.with_suffix(".md"), pdf.parent / (pdf.stem + ".assets")


def is_linked(path):
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


IMG_MD = re.compile(r"(!\[(?:[^\[\]\\]|\\.|\[[^\[\]]*\])*\]\(\s*)(<[^>\n]+>|[^\s()<>]+(?:\([^\s()]*\)[^\s()<>]*)*)((?:\s+\"[^\"]*\")?\s*\))")
IMG_HTML = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(.*?)\2", re.I | re.S)


def image_targets(markdown):
    return [m.group(2).strip("<>") for m in IMG_MD.finditer(markdown)] + [m.group(3) for m in IMG_HTML.finditer(markdown)]


def classify(pdf):
    """Status of the outputs beside one PDF (no network)."""
    md, assets = outputs(pdf)
    row = {"pdf": str(pdf), "markdown": str(md)}
    if is_linked(pdf) or is_linked(pdf.parent) or is_linked(md) or is_linked(assets):
        return dict(row, status="Linked", reason="symlink or junction in the output path; review manually")
    if not md.exists():
        if assets.exists():
            return dict(row, status="AssetsWithoutMarkdown", reason="an assets folder exists without Markdown; review")
        return dict(row, status="Missing")
    with md.open(encoding="utf-8", errors="replace") as f:
        first = f.readline()
    if MINERU_RE.search(first):
        return dict(row, status="MinerUOutput", reason="converted by mineru-api-batch-convert; left as it is")
    m = MARKER_RE.search(first)
    if not m:
        return dict(row, status="ExistingUntracked", reason="Markdown without a conversion marker; left as it is")
    try:
        marker = json.loads(m.group(1))
        expected_hash = marker["sourceSha256"].lower()
        asset_count = int(marker.get("assetCount") or 0)
        if marker.get("sourcePdf") != pdf.name:
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        return dict(row, status="InvalidMarker", reason="malformed or mismatched marker; review")
    if sha256_file(pdf) != expected_hash:
        return dict(row, status="Stale", reason="PDF changed since conversion; replacement needs the user's consent")
    text = md.read_text(encoding="utf-8", errors="replace")
    local = [unquote(t) for t in image_targets(text) if not re.match(r"(?i)(https?:|data:)", t)]
    missing = [t for t in local if not (md.parent / t).is_file()]
    files = {p.relative_to(assets).as_posix(): p.read_bytes() for p in assets.rglob("*") if p.is_file()} if assets.is_dir() else {}
    if missing or len(files) != asset_count:
        return dict(row, status="IncompleteAssets", reason=f"{len(missing)} missing image(s); {len(files)} of {asset_count} asset files")
    broken = [t for t in local if not image_ok((md.parent / t).read_bytes())]
    if broken:
        return dict(row, status="IncompleteAssets", reason=f"{len(broken)} undecodable image(s), e.g. {Path(broken[0]).name}")
    if marker.get("assetsSha256") and assets_digest(files) != marker["assetsSha256"]:
        return dict(row, status="IncompleteAssets", reason="asset files changed since conversion")
    return dict(row, status="Current")


def resolve_scope(pdfs, roots, recurse):
    found, seen = [], set()
    for p in pdfs or []:
        path = Path(p).expanduser().resolve()
        if not path.is_file() or path.suffix.lower() != ".pdf":
            raise SystemExit(f"Not a PDF file: {path}")
        found.append(path)
    for r in roots or []:
        root = Path(r).expanduser().resolve()
        if not root.is_dir():
            raise SystemExit(f"Not a directory: {root}")
        for path in sorted(root.rglob("*.pdf") if recurse else root.glob("*.pdf")):
            if path.is_file() and not any(part.endswith(".assets") for part in path.relative_to(root).parts[:-1]):
                found.append(path)
    out = []
    for path in found:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def page_count(pdf):
    try:
        import pymupdf
        with pymupdf.open(pdf) as doc:
            return doc.page_count
    except Exception:
        return None


# ---------- Markdown normalization (representation only; recorded in the marker) ----------

CAPTION_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<mark>\*\*|__)(?P<text>(?:Supplementary\s+)?(?:Fig\.?|Figure|FIG\.?|FIGURE|Table|TABLE|Scheme|SCHEME)"
    r"\s*S?\d+[A-Za-z]?\b.*?)(?P=mark)", re.M)
DISPLAY_RE = re.compile(r"\$\$(.+?)\$\$", re.S)
_SPACE = r"\s*(?:\\qquad|\\quad|\\hfill|\\hspace\*?\{[^{}]*\}|\\[,;:!]|~)"
_DOTS = r"\s*(?:\\[lc]?dots|\.{3,})"  # leader dots, as in "\quad \dots \dots (A-1)"
EQNUM_RE = re.compile(
    rf"^(?P<body>.*?\S)(?:(?:{_SPACE})+(?:{_DOTS})*|(?:{_DOTS}){{2,}})\s*"
    r"\(\s*(?P<num>(?:[A-Za-z]{1,2}-?)?\d+(?:\.\d+)?[a-z]?'?)\s*\)\s*[.,]?\s*$", re.S)
SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")


def unbold_captions(md):
    """'**Fig. 1.** Text' -> 'Fig. 1. Text' so caption lines start with the label, as in MinerU output."""
    return CAPTION_RE.subn(lambda m: m.group("indent") + m.group("text"), md)


def tag_equations(md):
    """'$$ ... \\quad (3)$$' -> '$$ ... \\tag{3}$$' (the printed equation number, kept as a LaTeX tag)."""
    count = 0

    def fix(m):
        nonlocal count
        body = m.group(1)
        e = None if "\\tag" in body else EQNUM_RE.match(body)
        if not e:
            return m.group(0)
        count += 1
        return "$$" + e.group("body") + " \\tag{" + e.group("num") + "}$$"

    return DISPLAY_RE.sub(fix, md), count


def split_row(line):
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    cells, cur, i = [], [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s) and s[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if s[i] == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(s[i])
        i += 1
    cells.append("".join(cur).strip())
    return cells


INLINE_MATH = re.compile(r"(\$[^$\n]+\$)")


def cell_html(text):
    """Inline Markdown inside a table cell as HTML (Markdown is not rendered inside an HTML block); $math$ untouched."""
    parts = INLINE_MATH.split(text)
    for i in range(0, len(parts), 2):
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', parts[i])
        s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"<b>\2</b>", s)
        s = re.sub(r"(?<![\\*\w])\*(?=\S)(.+?)(?<=[^\s\\])\*(?![*\w])", r"<i>\1</i>", s)
        parts[i] = re.sub(r"\\([*_\[\]#`])", r"\1", s)
    return "".join(parts)


def tables_to_html(md):
    """GFM pipe tables -> one-line HTML <table> as MinerU writes them. Cell text (incl. <br>, <sup>, $math$) is kept,
    inline Markdown becomes HTML; a table whose rows do not all have the header's cell count is left untouched."""
    lines, out, i, converted, left = md.split("\n"), [], 0, 0, 0
    while i < len(lines):
        if i + 1 < len(lines) and lines[i].lstrip().startswith("|") and "|" in lines[i + 1] and SEP_RE.match(lines[i + 1]):
            header, j, rows = split_row(lines[i]), i + 2, []
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            if len(split_row(lines[i + 1])) == len(header) and all(len(r) == len(header) for r in rows):
                body = "".join("<tr>" + "".join(f"<td>{cell_html(c)}</td>" for c in r) + "</tr>" for r in [header] + rows)
                out.append(f"<table>{body}</table>")
                converted += 1
            else:
                out.extend(lines[i:j])
                left += 1
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), converted, left


BLOCK_START = re.compile(r"^(?:#|\||<|!\[|\$\$|>|[-*+]\s|\d+[.)]\s|\[\d+\]|(?:Supplementary\s+)?"
                         r"(?:Fig\.?|Figure|FIG\.?|FIGURE|Table|TABLE|Scheme|SCHEME)\s*S?\d)")


def join_split_paragraphs(md):
    """Rejoin a sentence that a column or page break split into two paragraphs: the first ends mid-sentence (a lowercase
    letter, comma or semicolon; a lowercase letter plus line-break hyphen, which is dropped) and the next starts with a
    lowercase letter. Headings, lists, tables, math, images, captions and reference entries are never joined."""
    out, joins = [], 0

    def plain(s):
        return bool(s) and not BLOCK_START.match(s) and "$$" not in s and "<table" not in s and "![" not in s

    for para in md.split("\n\n"):
        prev = out[-1].rstrip() if out else ""
        nxt = para.lstrip()
        if plain(prev.lstrip()) and plain(nxt) and re.match(r"[a-z]", nxt):
            if re.search(r"[a-z]-$", prev):
                out[-1], joins = prev[:-1] + nxt, joins + 1
                continue
            if re.search(r"[a-z,;]$", prev):
                out[-1], joins = prev + " " + nxt, joins + 1
                continue
        out.append(para)
    return "\n\n".join(out), joins


def normalize(md):
    md, captions = unbold_captions(md)
    md, tags = tag_equations(md)
    md, tables, left = tables_to_html(md)
    md, joins = join_split_paragraphs(md)
    return md, {"captionLabels": captions, "equationTags": tags, "tables": tables, "tablesLeftAsPipe": left,
                "paragraphJoins": joins}


# ---------- images ----------

WINDOWS_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.I)


def image_ok(raw):
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.verify()
        return True
    except Exception:
        return False


def assets_digest(files):
    """One SHA-256 over {relative name: bytes} of an assets folder, recorded at publication and checked by scan."""
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(f"{name}\t{hashlib.sha256(files[name]).hexdigest()}\n".encode())
    return h.hexdigest()


def decode_images(images):
    if not isinstance(images, dict):
        raise Fail("unexpected image payload shape")
    decoded = {}
    for name, value in images.items():
        if (not isinstance(name, str) or not name or name in {".", ".."} or name != Path(name).name
                or any(c in name for c in '\\/:*?"<>|\x00') or WINDOWS_RESERVED.match(name) or name.endswith((" ", "."))):
            raise Fail("unsafe image filename in result")
        if not isinstance(value, str):
            raise Fail("image payload is not base64 text")
        if value.startswith("data:"):
            value = value.split(";base64,", 1)[1] if ";base64," in value else ""
        try:
            raw = base64.b64decode(value, validate=True)
            with Image.open(io.BytesIO(raw)) as im:
                size = im.size
                im.verify()
        except Exception:
            raise Fail(f"undecodable image {name}")
        decoded[name] = (raw, size)
    return decoded


def link_images(markdown, names, assets_name):
    """Point every reference to a returned image at Paper.assets/<name> (each segment URI-encoded); return the new
    Markdown and the referenced names. Any other local reference is an error."""
    encoded = {n: quote(assets_name, safe="") + "/" + quote(n, safe="") for n in names}
    used = set()

    def target(raw):
        clean = unquote(raw.strip().strip("<>"))
        if clean in encoded:
            used.add(clean)
            return encoded[clean]
        return raw

    markdown = IMG_MD.sub(lambda m: m.group(1) + target(m.group(2)) + m.group(3), markdown)
    markdown = IMG_HTML.sub(lambda m: m.group(1) + m.group(2) + target(m.group(3)) + m.group(2), markdown)
    for t in image_targets(markdown):
        if re.match(r"(?i)data:", t):
            continue
        if unquote(t) not in {unquote(v) for v in encoded.values()}:
            raise Fail("image reference that is not a returned image")
    for n in names:  # a reference the patterns could not parse (odd alt text) must not survive unrewritten
        if re.search(r"\]\(\s*<?" + re.escape(n) + r"|src\s*=\s*[\"']" + re.escape(n), markdown):
            raise Fail(f"unrewritten reference to {n}")
    return markdown, used


# ---------- machine-local state ----------

class Store:
    def __init__(self, root):
        self.ck = root / "checkpoints"
        self.pl = root / "payloads"
        self.ck.mkdir(parents=True, exist_ok=True)
        self.pl.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(pdf, sha):
        return hashlib.sha256(f"{os.path.normcase(str(pdf))}|{sha}".encode()).hexdigest()[:32]

    def load(self, key):
        p = self.ck / f"{key}.json"
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            raise Review(f"corrupt checkpoint {p}")

    def save(self, key, data):
        save_json(self.ck / f"{key}.json", data)

    def save_payload(self, key, payload):
        save_json(self.pl / f"{key}.json", payload)

    def load_payload(self, key):
        return json.loads((self.pl / f"{key}.json").read_text(encoding="utf-8"))

    def clear(self, key):
        for p in (self.ck / f"{key}.json", self.pl / f"{key}.json"):
            p.unlink(missing_ok=True)


# ---------- Datalab API ----------

_local = threading.local()


def session():
    if not hasattr(_local, "s"):
        _local.s = requests.Session()
    return _local.s


def never_sent(error):
    """True when the request certainly did not reach the server (DNS failure, refused or timed-out connection)."""
    if isinstance(error, requests.ConnectTimeout):
        return True
    reason = getattr(error.args[0], "reason", None) if error.args else None
    return type(reason).__name__ in {"NewConnectionError", "NameResolutionError", "ConnectTimeoutError"}


def check_result_url(url):
    parsed = urlparse(url)
    if test_mode() and parsed.hostname in {"127.0.0.1", "localhost"}:
        return
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise Fail("unsafe result URL")
    for info in socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise Fail("non-public result URL")


def download_result(url):
    check_result_url(url)
    with session().get(url, stream=True, timeout=(15, 120), allow_redirects=False) as r:  # never send the key here
        if not r.ok or r.is_redirect:
            raise Fail(f"result download HTTP {r.status_code}")
        chunks, size = [], 0
        for block in r.iter_content(1 << 20):
            size += len(block)
            if size > 1 << 30:
                raise Fail("result exceeds the 1 GB safety limit")
            chunks.append(block)
    try:
        obj = json.loads(b"".join(chunks))
    except ValueError:
        raise Fail("downloaded result is not JSON")
    if not isinstance(obj, dict):
        raise Fail("unexpected downloaded result shape")
    return obj


def submit(pdf, sha, key, ctx):
    ck = {"schemaVersion": 1, "skillVersion": SKILL_VERSION, "sourcePath": str(pdf), "sourceSha256": sha,
          "parameters": ctx.params, "status": "submitting", "submittedUtc": now()}
    ctx.store.save(key, ck)
    started = time.monotonic()
    for attempt in range(4):
        try:
            with pdf.open("rb") as f:
                r = session().post(f"{api_base()}/convert", headers={"X-API-Key": ctx.key}, data=ctx.params,
                                   files={"file": (pdf.name, f, "application/pdf")}, timeout=(20, 600), allow_redirects=False)
        except requests.RequestException as e:
            if never_sent(e):
                ctx.store.clear(key)
                raise Fail("could not connect to Datalab; nothing was uploaded")
            raise Uncertain(f"{type(e).__name__} during upload; the job may exist at Datalab")
        if r.status_code == 429 and attempt < 3:
            time.sleep(10 * (attempt + 1))
            continue
        if r.status_code in (401, 403):
            ctx.store.clear(key)
            raise AuthError(f"HTTP {r.status_code}: the API key was rejected")
        if r.status_code == 408 or r.status_code >= 500:
            raise Uncertain(f"HTTP {r.status_code} during upload; the job may exist at Datalab")
        try:
            obj = r.json()
        except ValueError:
            obj = {}
        if not r.ok:
            ctx.store.clear(key)
            raise Fail(f"HTTP {r.status_code}: {safe_text(obj.get('error') or obj.get('detail'))}")
        request_id = obj.get("request_id")
        if obj.get("success") is False or not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", request_id):
            if obj.get("success") is False:
                ctx.store.clear(key)
                raise Fail(f"rejected: {safe_text(obj.get('error'))}")
            raise Uncertain("upload answered without a usable request id")
        ck.update(status="submitted", requestId=request_id, acceptedUtc=now(),
                  uploadSeconds=round(time.monotonic() - started, 1))
        ctx.store.save(key, ck)
        return ck
    ctx.store.clear(key)
    raise Fail("rate limited by Datalab (HTTP 429); rerun later")


def poll(key, ck, ctx):
    started = time.monotonic()
    deadline, delay, polls, throttled = started + ctx.poll_timeout, 2.0, 0, 0
    url = f"{api_base()}/convert/{ck['requestId']}"
    while time.monotonic() < deadline:
        if ctx.stop.is_set():
            raise Pending("run stopped; rerun to resume the accepted job")
        polls += 1
        try:
            r = session().get(url, headers={"X-API-Key": ctx.key}, timeout=(15, 60), allow_redirects=False)
        except requests.RequestException:
            time.sleep(delay)
            continue
        if r.status_code in (408, 429) or r.status_code >= 500:
            throttled += r.status_code == 429
            time.sleep(max(delay, 5))
            continue
        if r.status_code in (401, 403):
            raise AuthError(f"HTTP {r.status_code}: the API key was rejected")
        if r.status_code == 404:
            ctx.store.clear(key)
            raise Fail("job not found at Datalab (expired?); the next run will upload again")
        try:
            obj = r.json()
        except ValueError:
            obj = None
        if not r.ok or not isinstance(obj, dict):
            raise Fail(f"HTTP {r.status_code} while polling; checkpoint kept for review")
        status = obj.get("status")
        if status == "complete" or (status not in (None, "processing") and obj.get("success") is not None):
            if obj.get("result_url"):
                obj = {**download_result(obj["result_url"]), **{k: v for k, v in obj.items() if v is not None and k != "result_url"}}
            if obj.get("success") is False or status == "failed":
                ck.update(status="failed", failedUtc=now(), error=safe_text(obj.get("error")))
                ctx.store.save(key, ck)
                raise Fail(f"conversion failed at Datalab: {ck['error']}")
            markdown = obj.get("markdown")
            if not isinstance(markdown, str) or not markdown.strip():
                ck.update(status="failed", failedUtc=now(), error="empty Markdown")
                ctx.store.save(key, ck)
                raise Fail("Datalab returned empty Markdown")
            payload = {k: obj.get(k) for k in ("markdown", "images", "page_count", "parse_quality_score", "cost_breakdown", "runtime")}
            payload["failed_pages"] = (obj.get("metadata") or {}).get("failed_pages")
            ctx.store.save_payload(key, payload)
            ck.update(status="downloaded", completedUtc=now(), waitSeconds=round(time.monotonic() - started, 1),
                      polls=polls, throttled=throttled)
            ctx.store.save(key, ck)
            return ck
        time.sleep(delay)
        delay = min(delay * 1.5, 6.0)
    raise Pending("still processing at the deadline; rerun to resume without uploading again")


# ---------- publication ----------

def publish(pdf, key, ck, ctx):
    md_path, assets_path = outputs(pdf)
    if md_path.exists() or assets_path.exists():
        raise Review("Markdown or assets appeared during conversion; nothing written")
    if sha256_file(pdf) != ck["sourceSha256"]:
        ctx.store.clear(key)
        raise Fail("PDF changed during conversion; nothing written")
    payload = ctx.store.load_payload(key)
    markdown, norm = normalize(payload["markdown"].replace("\r\n", "\n"))
    decoded = decode_images(payload.get("images") or {})
    markdown, used = link_images(markdown, list(decoded), assets_path.name)
    cost = (payload.get("cost_breakdown") or {}).get("final_cost_cents")
    marker = {
        "schemaVersion": 1, "skillVersion": SKILL_VERSION, "provider": "datalab-marker-api",
        "sourcePdf": pdf.name, "sourceLength": pdf.stat().st_size, "sourceSha256": ck["sourceSha256"],
        "assetsDirectory": assets_path.name if used else None, "assetCount": len(used),
        "assetsSha256": assets_digest({n: decoded[n][0] for n in used}) if used else None,
        "mode": ck["parameters"].get("mode"), "requestId": ck.get("requestId"),
        "pageCount": payload.get("page_count"), "parseQualityScore": payload.get("parse_quality_score"),
        "costCents": cost, "normalizations": norm, "convertedUtc": now(),
    }
    text = f"<!-- marker-batch-convert {json.dumps(marker, ensure_ascii=False, separators=(',', ':'))} -->\n" + markdown.lstrip("\n")
    token = uuid.uuid4().hex[:12]
    tmp_md = md_path.with_name(md_path.name + PARTIAL + token)
    tmp_assets = assets_path.with_name(assets_path.name + PARTIAL + token)
    created = []
    try:
        if used:
            tmp_assets.mkdir()
            created.append(tmp_assets)
            for name in used:
                (tmp_assets / name).write_bytes(decoded[name][0])
        with tmp_md.open("x", encoding="utf-8", newline="\n") as f:
            f.write(text)
        created.append(tmp_md)
        if used:
            os.rename(tmp_assets, assets_path)  # fails if a folder appeared meanwhile: never overwrite
            created[created.index(tmp_assets)] = assets_path
        os.rename(tmp_md, md_path)
        created[created.index(tmp_md)] = md_path
    except Exception as e:
        for p in reversed(created):  # only what this attempt created
            if p.is_dir():
                for child in p.iterdir():
                    child.unlink()
                p.rmdir()
            else:
                p.unlink(missing_ok=True)
        if isinstance(e, (FileExistsError, PermissionError)):
            raise Review(f"could not publish beside the PDF ({type(e).__name__}); nothing kept")
        raise
    ctx.store.clear(key)
    return {"markdown": str(md_path), "assetCount": len(used), "unreferencedImagesDropped": len(decoded) - len(used),
            "pages": payload.get("page_count"), "costCents": cost, "parseQualityScore": payload.get("parse_quality_score"),
            "failedPages": payload.get("failed_pages"), "normalizations": norm, "requestId": ck.get("requestId"),
            "timing": {"uploadSeconds": ck.get("uploadSeconds"), "serverRuntimeSeconds": round(payload.get("runtime") or 0, 1) or None,
                       "waitSeconds": ck.get("waitSeconds"), "polls": ck.get("polls"), "throttled": ck.get("throttled")}}


# ---------- actions ----------

class Context:
    pass


def process(pdf, ctx):
    started = time.monotonic()
    result = _process(pdf, ctx)
    result["seconds"] = round(time.monotonic() - started, 1)
    return result


def _process(pdf, ctx):
    row = {"pdf": str(pdf)}
    try:
        sha = sha256_file(pdf)
        key = ctx.store.key(pdf, sha)
        ck = ctx.store.load(key)
        if ck and ck.get("status") == "submitting" and not ctx.retry_uncertain:
            return dict(row, status="UncertainSubmission", reason=(
                f"an earlier upload ({ck.get('submittedUtc')}) has an unknown outcome; check Datalab usage, then rerun "
                "with --retry-uncertain to upload again"))
        if ck is None or ck.get("status") in ("failed", "submitting"):
            if ctx.stop.is_set():
                return dict(row, status="NotAttempted", reason="run stopped before this PDF")
            pages = page_count(pdf)
            if pages and pages > ctx.max_pages:
                return dict(row, status="SkippedTooManyPages", reason=f"{pages} pages > --max-pages {ctx.max_pages}")
            ck = submit(pdf, sha, key, ctx)
        elif ck.get("parameters") != ctx.params:  # resuming avoids a second bill, but say what was actually run
            old, new = (ck.get("parameters") or {}).get("mode"), ctx.params.get("mode")
            row["notice"] = (f"resumed the earlier {old}-mode job; --mode {new} was not applied" if old != new
                             else "resumed an earlier job submitted with different parameters")
        if ck["status"] == "submitted":
            ck = poll(key, ck, ctx)
        if ck["status"] != "downloaded":
            raise Review(f"checkpoint in state {ck.get('status')!r}; review")
        return dict(row, status="Converted", **publish(pdf, key, ck, ctx))
    except AuthError as e:
        ctx.stop.set()
        return dict(row, status="Failed", reason=str(e))
    except Uncertain as e:
        return dict(row, status="UncertainSubmission", reason=str(e))
    except Pending as e:
        return dict(row, status="Pending", reason=str(e))
    except Review as e:
        return dict(row, status="ReviewRequired", reason=str(e))
    except Fail as e:
        return dict(row, status="Failed", reason=str(e))
    except Exception as e:  # unexpected: keep checkpoints; URLs are stripped from the message
        return dict(row, status="Failed", reason=f"unexpected {type(e).__name__}: {safe_text(e, 200)}")


def run_lock(root):
    handle = open(root / "convert.lock", "a+")
    if os.name == "nt":
        import msvcrt
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            raise SystemExit("Another convert run is active on this computer; wait for it to finish.")
    return handle


def write_report(report, report_dir, action):
    folder = Path(report_dir) if report_dir else data_dir() / "reports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"marker-{action}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.json"
    report["reportPath"] = str(path)
    save_json(path, report)
    return path


def counts(rows):
    out = {}
    for r in rows:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def action_environment(_args):
    import platform
    key, source = load_key()
    try:
        import pymupdf
        mupdf = pymupdf.VersionBind
    except Exception:
        mupdf = None
    info = {"skillVersion": SKILL_VERSION, "skillPath": str(Path(__file__).resolve().parent.parent),
            "python": platform.python_version(), "requests": requests.__version__, "pillow": Image.__version__,
            "pymupdf": mupdf, "apiBase": api_base(), "keyConfigured": bool(key), "keySource": source,
            "localData": str(data_dir())}
    print(json.dumps(info, indent=2))
    return 0


def action_scan(args):
    started, started_utc = time.monotonic(), now()
    rows = [classify(p) for p in resolve_scope(args.pdf, args.root, args.recurse)]
    missing_pages = 0
    for r in rows:
        if r["status"] == "Missing":
            r["pages"] = page_count(Path(r["pdf"]))
            missing_pages += r["pages"] or 0
    report = {"action": "scan", "skillVersion": SKILL_VERSION, "startedUtc": started_utc, "counts": counts(rows),
              "missingPages": missing_pages, "items": rows, "totalSeconds": round(time.monotonic() - started, 1)}
    path = write_report(report, args.report_dir, "scan")
    print(json.dumps({k: report[k] for k in ("counts", "missingPages", "totalSeconds")} | {"reportPath": str(path)}, indent=2))
    return 0


def action_convert(args):
    started, started_utc = time.monotonic(), now()
    root = data_dir()
    lock = run_lock(root)
    try:
        ctx = Context()
        ctx.store = Store(root)
        ctx.params = {"output_format": "markdown", "mode": args.mode, "paginate": "false",
                      "disable_image_extraction": "false", "disable_image_captions": "true"}
        ctx.poll_timeout, ctx.max_pages, ctx.retry_uncertain = args.poll_timeout, args.max_pages, args.retry_uncertain
        ctx.stop = threading.Event()
        rows = [classify(p) for p in resolve_scope(args.pdf, args.root, args.recurse)]
        todo = [Path(r["pdf"]) for r in rows if r["status"] == "Missing"]
        ctx.key = None
        if todo:
            ctx.key, _ = load_key()
            if not ctx.key:
                raise SystemExit("No API key: set MARKER_API_KEY (Windows user environment) and rerun. Never paste it in chat.")
        results = {}
        with cf.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 8))) as pool:
            futures = {pool.submit(process, p, ctx): p for p in todo}
            for fut in cf.as_completed(futures):
                r = fut.result()
                results[r["pdf"]] = r
                print(f"[{r['status']}] {Path(r['pdf']).name}" + "".join(f" - {r[k]}" for k in ("reason", "notice") if r.get(k)),
                      flush=True)
        items = [results.get(r["pdf"], r) for r in rows]
        conv = [i for i in items if i["status"] == "Converted"]
        report = {
            "action": "convert", "skillVersion": SKILL_VERSION, "startedUtc": started_utc, "parameters": ctx.params,
            "scan": counts(rows), "counts": counts(items),
            "pagesConverted": sum(i.get("pages") or 0 for i in conv),
            "costCents": round(sum(i.get("costCents") or 0 for i in conv), 3),
            "items": items, "totalSeconds": round(time.monotonic() - started, 1),
        }
        path = write_report(report, args.report_dir, "convert")
        print(json.dumps({k: report[k] for k in ("scan", "counts", "pagesConverted", "costCents", "totalSeconds")}
                         | {"reportPath": str(path)}, indent=2))
        attention = {"Failed", "Pending", "UncertainSubmission", "ReviewRequired", "NotAttempted"}
        return 1 if any(i["status"] in attention for i in items) else 0
    finally:
        lock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("environment")
    for name in ("scan", "convert"):
        p = sub.add_parser(name)
        p.add_argument("--pdf", nargs="+", help="explicit PDF files")
        p.add_argument("--root", nargs="+", help="folders whose PDFs are in scope")
        p.add_argument("--recurse", action="store_true", help="include subfolders of --root")
        p.add_argument("--report-dir", help="where to write the JSON report (default: local data folder)")
        if name == "convert":
            p.add_argument("--mode", choices=["fast", "balanced", "accurate"], default="balanced")
            p.add_argument("--workers", type=int, default=4, help="concurrent PDFs (1-8)")
            p.add_argument("--max-pages", type=int, default=200, help="skip PDFs with more pages (cost guard)")
            p.add_argument("--poll-timeout", type=int, default=1800, help="seconds to wait for each accepted job")
            p.add_argument("--retry-uncertain", action="store_true",
                           help="upload again a PDF whose earlier upload has an unknown outcome (may bill twice)")
    args = parser.parse_args(argv)
    if args.action != "environment" and not (args.pdf or args.root):
        parser.error("give --pdf or --root")
    return {"environment": action_environment, "scan": action_scan, "convert": action_convert}[args.action](args)


if __name__ == "__main__":
    sys.exit(main())
