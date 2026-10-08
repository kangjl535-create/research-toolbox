"""Shared helpers for zotero-ai-reading: Zotero 10 local API (reads, and writes with a local API key), library/vault
paths, the Better BibTeX JSON export that BibNotes reads, BibNotes settings, and MinerU/Marker Markdown lookup."""
import hashlib, json, os, pathlib, re, time, urllib.error, urllib.request

BASE = "http://127.0.0.1:23119"
API = BASE + "/api/users/0/"
APP_NAME = "zotero-ai-reading"
MAX_WRITE = 50  # objects per local API write request
KEY_CHARS = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # Zotero object keys
COLORS = {"green": "#5fb236", "orange": "#f19837", "yellow": "#ffd400", "red": "#ff6666", "blue": "#2ea8e5"}
FIELDS = ["Summary", "Objective", "Method", "Conclusion", "Gap", "Inspiration"]
S2C_FIRST_KEYS = ["Title", "Type", "Author", "Year", "Journal", "DOI", "tags", "folder", "Affiliation"]


def api(path, timeout=20):
    """GET one Zotero local API path (reads need no key)."""
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read())


def api_status(path):
    """HTTP status of a GET, e.g. 404 for an unused item key."""
    try:
        with urllib.request.urlopen(API + path, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def http(method, path, body=None, headers=None, timeout=30):
    """(status, headers, text) of one local API request; JSON body; errors are returned, not raised."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    h = {"Zotero-API-Version": "3", **({"Content-Type": "application/json"} if data else {}), **(headers or {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, method=method, headers=h), timeout=timeout) as r:
            return r.status, r.headers, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode("utf-8", "replace")


def key_file():
    """Where the "Always Allow" key is kept: this machine's local app data, never OneDrive or the skill."""
    base = os.environ.get("LOCALAPPDATA") or str(pathlib.Path.home() / "AppData" / "Local")
    return pathlib.Path(base) / "AI-Config" / "zotero-ai-reading" / "local-api-key.json"


class WriteError(RuntimeError):
    pass


class ZoteroWriter:
    """POSTs to <library>/items through the Zotero 10 local API. Writes need the Zotero-Server-ID header and a key
    from POST /api/local/authorize, which shows a dialog in Zotero and waits for the user: "Always Allow" gives a key
    kept in key_file() and reused; "Allow" a key that Zotero discards after one write. The key is never printed.
    Only POST is used: DELETE would erase permanently, so moving to the trash is a POST with `deleted: 1`."""

    def __init__(self, request=http, path=None, say=lambda m: print(m, flush=True)):
        self.request, self.path, self.say = request, pathlib.Path(path) if path else key_file(), say
        self.server_id, self.key, self.remember = None, None, False

    def _server_id(self):
        s, h, _ = self.request("GET", "/api/")
        sid = h.get("Zotero-Server-ID") if h else None
        if s != 200 or not sid:
            raise WriteError(f"Zotero local API not reachable or older than Zotero 10 (HTTP {s}, no Zotero-Server-ID)")
        return sid

    def _load(self):
        try:
            k = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if k.get("serverID") == self.server_id and k.get("key"):
            self.key, self.remember = k["key"], True

    def _forget(self):
        self.key, self.remember = None, False
        try:
            self.path.unlink()
        except OSError:
            pass

    def _authorize(self):
        self.say('Zotero shows "Local API Authorization" for zotero-ai-reading: click "Always Allow" (the key is kept '
                 'on this computer; "Allow" works for one write only). Waiting up to 10 minutes...')
        s, _, b = self.request("POST", "/api/local/authorize", {"appName": APP_NAME}, {"Zotero-Server-ID": self.server_id}, timeout=600)
        if s != 200:
            raise WriteError(f"Zotero did not grant write access (HTTP {s}: {b[:200]})")
        grant = json.loads(b)
        self.key, self.remember = grant["key"], bool(grant.get("remember"))
        if self.remember:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"serverID": self.server_id, "key": self.key, "appName": APP_NAME,
                                             "created": time.strftime("%Y-%m-%dT%H:%M:%S")}), encoding="utf-8")
        self.say("write access granted" + ("" if self.remember else " for one write"))

    def _post(self, chunk):
        return self.request("POST", "/api/users/0/items", chunk, {"Zotero-Server-ID": self.server_id, "Zotero-API-Key": self.key})

    def post_items(self, entries):
        """Write all entries (at most MAX_WRITE per request); returns one (status, info) per entry: ("ok", saved JSON),
        ("unchanged", key) or ("failed", {code, message})."""
        if self.server_id is None:
            self.server_id = self._server_id()
            self._load()
        out = []
        for i in range(0, len(entries), MAX_WRITE):
            chunk = entries[i:i + MAX_WRITE]
            if not self.key:
                self._authorize()
            s, _, b = self._post(chunk)
            if s in (401, 412):  # key unknown to this Zotero (cleared, or another instance): authorize again, once
                if s == 412:
                    self.server_id = self._server_id()
                self._forget()
                self._authorize()
                s, _, b = self._post(chunk)
            if s != 200:
                raise WriteError(f"write rejected (HTTP {s}: {b[:300]}); {len(out)} of {len(entries)} objects written before")
            if not self.remember:
                self.key = None  # consumed by this write
            res = json.loads(b)
            for j in range(len(chunk)):
                if str(j) in res.get("successful", {}):
                    out.append(("ok", res["successful"][str(j)]))
                elif str(j) in res.get("unchanged", {}):
                    out.append(("unchanged", res["unchanged"][str(j)]))
                else:
                    f = res.get("failed", {}).get(str(j), {})
                    out.append(("failed", {"code": f.get("code"), "message": f.get("message", "no result for this object")}))
        return out


def api_all(path):
    out, start = [], 0
    sep = "&" if "?" in path else "?"
    while True:
        page = api(f"{path}{sep}limit=100&start={start}")
        out += page
        if len(page) < 100:
            return out
        start += 100


def zotero_available():
    try:
        api("items?limit=1", timeout=5)
        return True
    except Exception:
        return False


def zotero_prefs():
    """Text of the default Zotero profile's prefs.js (user-changed settings only), or "" when it cannot be found."""
    base = pathlib.Path(os.environ.get("APPDATA", "")) / "Zotero" / "Zotero"
    try:
        ini = (base / "profiles.ini").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    profiles = [dict(re.findall(r"^(\w+)=(.*)$", sec, re.M)) for sec in re.split(r"^\[Profile\d+\]$", ini, flags=re.M)[1:]]
    p = next((x for x in profiles if x.get("Default") == "1"), profiles[0] if profiles else None)
    if not p or "Path" not in p:
        return ""
    d = base / p["Path"] if p.get("IsRelative", "1") == "1" else pathlib.Path(p["Path"])
    try:
        return (d / "prefs.js").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def note_format_problem(prefs):
    """The annotation note is rebuilt with Zotero's default note templates and en-US strings; a changed template or
    interface language would make it differ from the user's own "Add Note from Annotations" notes."""
    if re.search(r'user_pref\("extensions\.zotero\.annotations\.noteTemplates\.', prefs):
        return "Zotero uses custom annotation note templates (Settings > Advanced > Config Editor: annotations.noteTemplates)"
    m = re.search(r'user_pref\("intl\.locale\.requested",\s*"([^"]*)"\)', prefs)
    if m and m.group(1) and not m.group(1).lower().startswith("en"):
        return f"Zotero's interface language is {m.group(1)!r}; the note is built with Zotero's en-US strings"
    return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Library:
    """Paper Library root (PDFs + MinerU Markdown) and its Obsidian vault (default <root>/Zoteronotes)."""

    def __init__(self, root, vault=None):
        self.root = pathlib.Path(root).resolve()
        self.vault = pathlib.Path(vault).resolve() if vault else self.root / "Zoteronotes"
        self.plugin = self.vault / ".obsidian" / "plugins" / "bibnotes"
        self.settings = json.loads((self.plugin / "data.json").read_text(encoding="utf-8"))
        self.bbt_path = self.vault / self.settings["bibPath"]
        self._bbt = None

    # --- paths ---
    def rel(self, path):
        """Path relative to the library root, from an absolute path of any drive or a Zotero 'attachments:' path."""
        s = str(path)
        if s.startswith("attachments:"):
            s = s[len("attachments:"):]
        parts = pathlib.PureWindowsPath(s.replace("/", "\\")).parts
        if self.root.name not in parts:
            return None
        return pathlib.Path(*parts[parts.index(self.root.name) + 1:])

    def note_path(self, pdf_rel, citekey):
        title = self.settings.get("exportTitle", "@{{citeKey}}").replace("{{citeKey}}", citekey).replace("{{citekey}}", citekey)
        return self.vault / pdf_rel.parent / f"{title}.md"

    # --- Better BibTeX export ---
    def bbt(self, reload=False):
        if self._bbt is None or reload:
            self._bbt = json.loads(self.bbt_path.read_text(encoding="utf-8"))
        return self._bbt

    def bbt_entry(self, citekey=None, item_key=None, reload=False):
        for e in self.bbt(reload)["items"]:
            if (citekey and e.get("citationKey") == citekey) or (item_key and e.get("itemKey") == item_key):
                return e
        return None

    def wait_for_tag(self, citekey, tag, timeout=90):
        """Better BibTeX re-exports after Zotero changes; wait until the entry shows `tag`."""
        deadline = time.time() + timeout
        while True:
            e = self.bbt_entry(citekey, reload=True)
            if e and any(t.get("tag") == tag for t in e.get("tags", [])):
                return True
            if time.time() > deadline:
                return False
            time.sleep(3)

    def bbt_items_in_folder(self, folder_rel):
        """(entry, pdf attachment) pairs whose PDF lies directly in folder_rel (relative to the library root)."""
        out = []
        for e in self.bbt()["items"]:
            for a in e.get("attachments", []):
                p = a.get("path") or ""
                r = self.rel(p) if p.lower().endswith(".pdf") else None
                if r is not None and r.parent == pathlib.Path(folder_rel):
                    out.append((e, a))
                    break
        return out

    # --- BibNotes set-up expected by the merge-safety rules ---
    def bibnotes_problems(self):
        s, t = self.settings, self.settings.get("templateContent", "")
        probs = []
        m = re.match(r"^---\n(.*?)\n---\n", t, re.S)
        keys = [re.match(r"^([A-Za-z_]\w*):", l).group(1) for l in (m.group(1).split("\n") if m else [])
                if re.match(r"^([A-Za-z_]\w*):", l)]
        if keys[:len(S2C_FIRST_KEYS)] != S2C_FIRST_KEYS:
            probs.append(f"template YAML should start with {S2C_FIRST_KEYS} (Zotero fields first), found {keys}")
        if '\ntags: ["{{keywordsZotero}}"]\n' not in t or "," not in s.get("multipleFieldsDivider", ""):
            probs.append('tags should be a YAML list: template line tags: ["{{keywordsZotero}}"] and a Multiple Entries '
                         'Divider with a comma, e.g. ",   " (otherwise Obsidian sees one tag "/unread ai-draft")')
        if s.get("saveManualEdits") != "Select Section" or s.get("saveManualEditsStart") != "Affiliation:" or s.get("saveManualEditsEnd"):
            probs.append("Save Manual Edits should be 'Select Section' from 'Affiliation:' with an empty end")
        if not t.rstrip().endswith("%% end of note %%"):
            probs.append("template should end with the line '%% end of note %%'")
        for f in FIELDS:
            if f"*{f}*:: " not in t:
                probs.append(f"template lacks the field line '*{f}*:: '")
        if not (s.get("imagesImport") and s.get("imagesCopy")):
            probs.append("BibNotes image import and copy should be on")
        return probs


def mineru_markdown(pdf):
    """(markdown path or None, status) for the converted Markdown next to the PDF: mineru-api-batch-convert or its
    substitute marker-api-batch-convert, whose first-line markers both carry the PDF's sourceSha256."""
    md = pdf.with_suffix(".md")
    if not md.exists():
        return None, "missing"
    first = md.open(encoding="utf-8").readline()
    m = re.search(r"<!-- (?:mineru|marker)-batch-convert (\{.*\}) -->", first)
    if not m:
        return md, "untracked (no converter marker)"
    try:
        marker = json.loads(m.group(1))
    except json.JSONDecodeError:
        return md, "untracked (bad marker)"
    if marker.get("sourceSha256") and marker["sourceSha256"].lower() != sha256(pdf).lower():
        return md, "stale (PDF changed since conversion)"
    return md, "current"
