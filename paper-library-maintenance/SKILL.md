---
name: paper-library-maintenance
description: Keep a Zotero-managed Paper Library consistent after papers are moved or renamed. Puts converted Markdown (from mineru-api-batch-convert or marker-api-batch-convert), its assets folder and the paper's Obsidian note back beside the moved PDF. Use when the user moved or renamed papers (for example with Zotero Attanger) or asks to relocate, tidy or check orphaned conversions and notes; not for converting PDFs or writing reading notes.
---

# Paper Library Maintenance

Release: **0.1.0**. Zotero (with Attanger) moves and renames only the PDF. The converted `Paper.md`, its `Paper.assets\` folder and the Obsidian note `@citekey.md` stay behind; the converters then see the paper as unconverted and AI reading may write a second note. `relocate` puts them back.

## Relocate

Run from this skill's `scripts\` folder with the shared science environment (never a bare `python` on Windows):

```powershell
& "$env:LOCALAPPDATA\AI-Config\bin\run-science.ps1" library_maintenance.py relocate --library-root "<Paper Library>" [--dry-run]
```

- **Conversions:** a `Paper.md` with no `Paper.pdf` beside it is matched to its PDF: by size and SHA-256 when it has a `mineru-batch-convert` or `marker-batch-convert` marker, by identical file name otherwise. Only a PDF without Markdown or assets of its own can receive it. When the PDF was renamed too, the Markdown and assets folder take its name, and the marker's `sourcePdf`/`assetsDirectory` and the image links are updated, so both converters still report the conversion as current. Only size-matched PDFs are hashed, which downloads them if they are OneDrive cloud-only files.
- **Notes:** `@citekey.md` (BibNotes `exportTitle`) belongs in the vault folder that mirrors its PDF's folder, found through the Better BibTeX export BibNotes reads (`--vault` if the vault is not `<library root>\Zoteronotes`).
- **Unambiguous moves are applied automatically**; `--dry-run` only reports. The JSON report (default `%LOCALAPPDATA%\paper-library-maintenance\reports\`, or `--report`) lists every move for reversal.

Report to the user what moved and every item that was not moved, with what they can do:

| Status | Meaning and next step |
|---|---|
| `ambiguous` | several identical PDFs, several conversions for one PDF, PDFs of one item in several folders, or several notes: the user decides; nothing was moved |
| `conflict` | the destination already has a note of that name: the user compares them |
| `no-pdf` | a tracked conversion whose PDF is no longer in the library (deleted or outside it): leave it, or recycle it with `mineru-api-batch-convert` orphan review |
| `review` | odd input (marker naming another PDF, missing assets, links, an export naming a PDF not on disk yet, duplicate notes): explain the reason given |
| `failed` | a move was rolled back (file in use, permissions): retry after closing the file |

## Rules

- Run only when the user asks for it: the Paper Library forbids moving files without a request. Prefer to run after a move session has finished and Better BibTeX has re-exported (notes follow the export).
- Never overwrite or delete. Folders left empty stay; mention them only if the user asks.
- PDFs, Zotero, the converters' outputs other than the relocated files, and plugin settings are not changed.

## Recording Defects

When real use (not a test) shows a defect in this skill (a script error, a check that let a wrong result through, a result you had to correct or work around, a correction from the user, or instructions that proved wrong), write one note per defect to `%OneDrive%\AI-Config\Skills\feedback\paper-library-maintenance\<YYYY-MM-DD>-<slug>.md`: front matter `skill`, `version`, `date`, `reporter` (agent and model), `status: open`; then what happened, what was expected, evidence (command, input identifiers, a short output excerpt; paths relative to `%OneDrive%`), and the workaround. No credentials or long source text; never edit an existing note. Expected outcomes (documented skips, missing inputs, user decisions) are not defects. If `%OneDrive%\AI-Config\Skills` does not exist, skip this and say so. List written notes in the final report. Here that includes a file moved to the wrong place, a move that broke a link or made a converter report the conversion as stale or incomplete, or an unambiguous case reported as ambiguous.
