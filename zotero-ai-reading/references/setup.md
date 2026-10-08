# Set-up the scripts rely on, and why

Read when `prepare` reports a set-up problem, when a step fails, or before changing the scripts. Findings come from the user's 2026-10-02 tests (archived in `%OneDrive%\AI-Config\Skills\records\paper-library-reorganization\2026-10-04\legacy\project-development\records\ai-annotation-tests\2026-10-02\`) and the 2026-10-08 Zotero 10 tests.

## BibNotes Formatter (Obsidian plugin `bibnotes`)

Expected settings (checked by `prepare`):
- **Template YAML** starts with the Zotero fields, then the hand-typed ones:
  `Title: "{{title}}"`, `Type`, `Author`, `Year`, `Journal: "{{publicationTitle}}"`, `DOI`, `tags: ["{{keywordsZotero}}"]`, `folder: {{collectionsParent}}`, `Affiliation: ` (no placeholder), `Keywords: {{keywordsPDF}}`.
  The body contains `*Summary*:: ` … `*Inspiration*:: ` and ends with `%% end of note %%`.
- **Multiple Entries Divider** contains a comma (the user's is `,   `), so the quoted tags form a YAML list: `tags: ["/unread",   "ObsCite",   "ai-draft"]`. The divider is shared, so Author and folder read `Last, First,   Last, First`.
- **Save Manual Edits** is "Select Section" from `Affiliation:` with an empty end.
- Image import and copy are on.

Why:
- BibNotes never replaces a line. "Update" inserts every line it cannot find; a line under 30 characters must match whole, a longer one counts as present when either half matches. A changed `tags:`/`folder:`/`Author:` line therefore became a duplicate YAML key (254 of 279 notes would have broken). With "Select Section" from `Affiliation:`, everything above it is regenerated from Zotero and everything from it on (hand-typed Affiliation, Keywords, AI keys, the body) is kept.
- Obsidian (1.13) takes a text `tags:` value as one tag and drops it from the tag index when it contains a space; the Properties panel shows it as a single chip (`/unread ai-draft`). A YAML list gives one tag per Zotero tag; unquoted, the user's `#…` tags would start YAML comments, hence the quotes. Zotero tags with spaces still appear in Properties but are not indexed. An item with no Zotero tags renders `tags: [""]` (an empty chip; ignored by the tag index). Dry run over all 286 notes on 2026-10-02: valid YAML and correct lists everywhere (`project-development/records/ai-reading/2026-10-02-tags-list/`).
- Inserting after the last line of a note without a final line break writes the whole note twice. Notes made by this skill end with `%% end of note %%` and a line break.
- Highlight text is written raw inside `<mark>`; a bare `<` there stops Obsidian rendering the rest of the note.
- BibNotes's `file:///` PDF link breaks across computers (different drive letters); notes use `zotero://open-pdf/library/items/<pdf key>`.

## Headless BibNotes (`bibnotes_headless.js`)

Runs the installed `main.js` in Node with the few Obsidian classes it touches stubbed, the real `data.json` read but never written, and output in a temporary vault. If a BibNotes update breaks it (it calls `loadSettings`, `createNote`, `settings.exportPath`, `zoteroStoragePathManual`, `imagesPath`, `exportTitle`), stop and report rather than writing notes another way.

## Zotero

Zotero 10.0.6, tested 2026-10-08 (records under `%OneDrive%\AI-Config\Skills\records\zotero-ai-reading\`).

- Local API `http://127.0.0.1:23119/api/users/0/`. Reads need no key; `items/<pdf>/children` omits annotations unless `?itemType=annotation` is added. Python `urllib` works; PowerShell `Invoke-RestMethod` does not.
- Writes (`ZoteroWriter` in `zar_common.py`) need the `Zotero-Server-ID` header (sent back from any response; a missing one gives 428, another instance's 412) and a key from `POST /api/local/authorize`, which shows Zotero's "Local API Authorization" dialog and waits for the user. "Always Allow" gives a key Zotero keeps in `<profile>/localAPIKeys.json` until Settings → Advanced → "Clear Write Authorizations"; the skill keeps its copy in `%LOCALAPPDATA%\AI-Config\zotero-ai-reading\local-api-key.json` with the server ID. "Allow" gives a key consumed by the first write (one dialog per request). On 401 or 412 the writer asks once more. A dialog answered after the client stopped waiting still stores a key nobody received; it does no harm and goes with "Clear Write Authorizations".
- `write` sends `POST <library>/items`, at most 50 objects per request: each annotation with its pre-generated key and `version: 0` (so it must not exist yet; verify and undo know the keys), `itemType: annotation`, `parentItem` = the PDF, `annotationType/Comment/Color/PageLabel/SortIndex`, `annotationPosition` as a JSON string, `annotationText` only for highlights, tag `AI`; and the item with its local `version` and its full tag list as read (tag types kept) plus `ai-draft`. Objects are applied one by one with no rollback, so every check runs before the first request and `undo-plan.json` is written before it.
- `DELETE` erases permanently (`eraseTx`). `undo` therefore POSTs `deleted: 1` (the Zotero trash) and the item's tags without `ai-draft`, each with its current version.
- Item JSON `version` is a local version, unrelated to sync versions. Zotero plugins can change an item while the user has the paper open (e.g. a tag rule on closing the tab, a metadata linter), which `verify` reports as changed fields.

### The annotation note

There is no API for "Add Note from Annotations". `note_html.py` rebuilds what `Zotero.EditorInstance.createNoteFromAnnotations(annotations, {noSave: true})` returns (Zotero 10 `editorInstance.js`): the default templates `<h1>{{title}}<br/>({{date}})</h1>`, `<p>{{highlight}} {{citation}} {{comment}}</p>`, `<p>{{citation}} {{comment}}</p>` and `<p>{{image}}<br/>{{citation}} {{comment}}</p>`; en-US strings (“…”, "and", "et al.", "p."/"pp."); `data-annotation` and `data-citation` as `encodeURIComponent(JSON.stringify(...))`; item data = the local API's `?format=csljson` with `id` set to the item URI `http://zotero.org/users/<library id>/items/<key>`; annotations in `getAnnotations()` order (sort index, ties in creation order) without ink; image size attributes `round(width pt × 96/72 × 1.25)`. A saved extra annotation note would make BibNotes place the user's later annotations out of order, so none is saved.
- Frame pictures: Zotero renders image annotations at 4 px per point (floor of the size). `render_frame` does the same with PyMuPDF; pictures differ from Zotero's only by rendering (median grey difference 3/255) and in 9 of 392 frames by 1 px.
- The note HTML embeds pictures as `data:` URIs, as Zotero's unsaved note does; but BibNotes recognises a picture only by `data-attachment-key` and copies `<storage>/<key>/image.png`. `note` therefore converts each data URI into `<run>/<citekey>/storage/<annotation key>/image.png`. When the user later makes their own annotation note, picture keys change but BibNotes still matches the line by its second half (the annotation link), so no picture is duplicated.
- Checked 2026-10-08 against 160 notes Zotero made in earlier runs (`zotero-ai-reading.tests/compare_note_html.py`, read-only): every annotation block still in Zotero (1,250) identical apart from the picture bytes, in the same order; item data and wrapper identical; the one old note where Zotero had failed to render frames ("[Image not available]") now gets them. Rerun it after a Zotero update that may change the note format, before trusting new notes.
- Custom note templates (`extensions.zotero.annotations.noteTemplates.*` in prefs.js) or a non-English `intl.locale.requested` would make the rebuilt note differ from the user's own; `note` stops on them.

### Geometry

- Rectangles are PDF user space (bottom-left origin): PyMuPDF rectangle × inverse page transformation. `annotationSortIndex` is `page(5)|offset(6)|top(5)`; the offset only orders annotations within a page.
- Scanned PDFs: Zotero accepts highlight rectangles anywhere, so scans get normal highlights placed from Windows OCR word boxes (`Windows.Media.Ocr`, en-US; local, about 2 s for 8 pages).

## Notes, pictures, links

- Note path: the PDF's folder relative to the library root, mirrored under the vault, named by BibNotes's export title (`@<citekey>.md`).
- Pictures go to BibNotes's image folder (`imagesPath`, e.g. `Linked files`); the Attachment Name Formatting plugin may later rename and move them when the note is opened.
- MarkDB-Connect links Zotero to the note by its `@citekey.md` name; "Open Note in Obsidian" appears after Zotero → MarkDB-Connect → Sync Tags (which adds the `ObsCite` tag).

## Troubleshooting

| symptom | cause and action |
|---|---|
| `note` says the export lacks `ai-draft` | Better BibTeX has not re-exported yet; rerun `note` after a minute |
| a quote is dropped | wording differs from the PDF (formula glyphs, OCR misreads): choose another sentence or a region |
| a region is not located | no MinerU figure image, no `\tag{n}`, or caption not found: drop it or frame a different element |
| OCR fails | Windows OCR en-US language missing (Settings → Language); run `ocr_windows.ps1` alone to see the error |
| report: "each Ctrl+P update re-adds the one-character line(s) ['>']" | BibNotes's merge never looks up a line that is one character after trimming (an empty abstract callout `> `, a lone `,`), so every update inserts it again, in the user's own notes too; not a note problem. Filling the Zotero abstract stops the `>` case |
| report: "the first Ctrl+P update adds BibNotes's own file:/// 'open pdf' line" | the PDF's Zotero title is short (e.g. "Full Text PDF"), so the merge cannot recognise the zotero:// line; one extra line on the first update, then stable |
| an update puts a `tags:`/`folder:` line under "Files and Links" | the note was made when Zotero had no DOI; the new `DOI:` line half-matches the Url line, so later changed YAML lines are inserted there (6 book-section notes on 2026-10-02). Delete the stray lines once; tell the user rather than editing their notes |
| `note` rejects with "re-update not clean" | a simulated update would insert other lines: open `note-rejected.md` in the paper's run folder and compare with a fresh render before changing anything |
| `write` waits and no dialog shows | the dialog may be behind other windows; the command waits up to 10 minutes. If it timed out, click Deny on the dialog still open and run `write` again |
| `write`: 403 "Local API is not enabled" | Zotero → Settings → Advanced → "Allow other applications on this computer to communicate with Zotero" |
| `write` refuses: "already written" | each run writes once. To redo a paper: `undo`, then a new run directory |
| `verify`: item fields changed | something changed the item after `write`, often a plugin while the user had the paper open; compare with `before.json` and tell the user |
| `note` stops: custom templates or language | restore Zotero's default annotation note templates / English interface, or adapt `note_html.py` and rerun `compare_note_html.py` |
| undo needed | `undo --run-dir <run>` (moves to the trash); then move the written note and its pictures out of the vault (do not delete) |
