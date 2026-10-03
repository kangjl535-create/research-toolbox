# Set-up the scripts rely on, and why

Read when `prepare` reports a set-up problem, when a step fails, or before changing the scripts. Findings come from the user's 2026-10-02 tests (records under `project-development/records/ai-annotation-tests/2026-10-02/`).

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

- Zotero 9's local API (`http://127.0.0.1:23119/api/users/0/`) is read-only; `items/<pdf>/children` omits annotations unless `?itemType=annotation` is added. Python `urllib` works; PowerShell `Invoke-RestMethod` does not.
- Writes happen only in pasted scripts using Zotero's own functions: `Zotero.Annotations.saveFromJSON` (keys are pre-generated, so verify and undo know them), `item.addTag`, and `Zotero.EditorInstance.createNoteFromAnnotations(annotations, {noSave: true})`, the same call as "Add Note from Annotations" without saving a note. A saved extra annotation note would make BibNotes place the user's later annotations out of order.
- The unsaved note embeds pictures as `data:` URIs, but BibNotes recognises a picture only by `data-attachment-key` and copies `<storage>/<key>/image.png`. `note` therefore converts each data URI into `<run>/<citekey>/storage/<annotation key>/image.png`. When the user later makes their own annotation note, picture keys change but BibNotes still matches the line by its second half (the annotation link), so no picture is duplicated.
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
| undo needed | the user pastes `undo-ai-annotations.js`; then move the written note and its pictures out of the vault (do not delete) |
