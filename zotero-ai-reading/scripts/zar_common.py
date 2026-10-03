"""Shared helpers for zotero-ai-reading: Zotero local API (read-only), library/vault paths, the Better BibTeX JSON
export that BibNotes reads, BibNotes settings, and MinerU Markdown lookup."""
import hashlib, json, pathlib, re, time, urllib.request

API = "http://127.0.0.1:23119/api/users/0/"
KEY_CHARS = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"  # Zotero object keys
COLORS = {"green": "#5fb236", "orange": "#f19837", "yellow": "#ffd400", "red": "#ff6666", "blue": "#2ea8e5"}
FIELDS = ["Summary", "Objective", "Method", "Conclusion", "Gap", "Inspiration"]
S2C_FIRST_KEYS = ["Title", "Type", "Author", "Year", "Journal", "DOI", "tags", "folder", "Affiliation"]


def api(path, timeout=20):
    """GET one Zotero local API path (Zotero 9 local API is read-only)."""
    with urllib.request.urlopen(API + path, timeout=timeout) as r:
        return json.loads(r.read())


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
    """(markdown path or None, status) for the MinerU output next to the PDF."""
    md = pdf.with_suffix(".md")
    if not md.exists():
        return None, "missing"
    first = md.open(encoding="utf-8").readline()
    m = re.search(r"<!-- mineru-batch-convert (\{.*\}) -->", first)
    if not m:
        return md, "untracked (no MinerU marker)"
    try:
        marker = json.loads(m.group(1))
    except json.JSONDecodeError:
        return md, "untracked (bad marker)"
    if marker.get("sourceSha256") and marker["sourceSha256"].lower() != sha256(pdf).lower():
        return md, "stale (PDF changed since conversion)"
    return md, "current"
