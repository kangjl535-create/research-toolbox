---
name: zotero-ai-reading
description: Read unread papers from a Zotero-managed Paper Library and annotate them in Zotero the way the user does (colour-coded highlights and figure/equation frames tagged AI, comments starting "AI："), then write a BibNotes-compatible Obsidian note in the mirrored Zoteronotes folder. Use when asked to AI-read, annotate or make notes for papers or a folder; not for papers the user already annotated (unless explicitly asked) and not for PDF conversion.
---

# Zotero AI Reading

Release: **0.1.0**. For papers the user has not read: the agent reads the MinerU Markdown, the scripts place its highlights on the PDF, the user pastes one script into Zotero, and the scripts write an Obsidian note identical to what BibNotes's "Update Current Note" would make. Later the user works on the paper with their usual flow (edit in Zotero → "Add Note from Annotations" → Ctrl+P update); the note stays merge-safe.

## Requirements

Windows; Zotero 9 running with the local API enabled; Python with `pymupdf`, `numpy`, `scikit-image`, `pillow`, `pyyaml`; Node.js; the Obsidian vault with BibNotes Formatter and the Better BibTeX JSON export it reads. `prepare` stops with the exact problem if the BibNotes set-up differs from the one the merge rules rely on; [references/setup.md](references/setup.md) explains that set-up and the Zotero/BibNotes behaviour behind every rule — read it when a check fails or before changing the scripts.

## Rules

- **Zotero is changed only by scripts the user pastes** (Tools → Developer → Run JavaScript, "Run as async function"). Never delete permanently; undo moves items to the Zotero trash.
- **Skip papers that already have annotations** unless the user explicitly asks for an AI note alongside (`--alongside`). Never overwrite an existing Obsidian note; `--replace-ai-draft` only replaces an earlier AI draft and only on request.
- Batches of up to **10 papers** per pasted script. Missing or stale MinerU Markdown: offer `mineru-api-batch-convert`; do not read the PDF instead. "Untracked" Markdown (made before MinerU markers existed) can be read as it is when it looks complete.
- PDFs, MinerU outputs, the user's notes and plugin settings are read, never edited.

## Workflow

Everything this skill needs is in its own folder, next to this file; a run needs nothing from other run folders, test records or development copies of the skill. Run all commands from this skill's `scripts/` folder with the project's Python (in the Paper Library: `& "$env:LOCALAPPDATA\AI-Config\bin\run-science.ps1" zotero_ai_reading.py ...` in PowerShell; from another shell `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<LOCALAPPDATA>\AI-Config\bin\run-science.ps1" zotero_ai_reading.py ...`). Never call a bare `python` on Windows: it may be the Microsoft Store stub, which hangs. Use one run directory per batch, by default `<library root>/project-development/records/ai-reading/<YYYY-MM-DD>-<topic>/`.

1. **Prepare:** `prepare --library-root <Paper Library> --run-dir <run> --folder "<folder relative to the library root>"` (or `--citekey ...`). It selects up to 10 ready papers, runs Windows OCR for scanned PDFs and lists every skipped paper with its reason. Report skips to the user.
2. **Read:** for each ready paper, read its whole Markdown and write `<run>/<citekey>/reading.json` following [references/reading.md](references/reading.md): the user's colour meanings, verbatim quotes, comments, and the six fields as concise text with optional detail bullets. This is the agent's real work: judge what matters in this paper, be accurate, and annotate by importance, not to a count. `pagemap --run-dir <run>` lists the PDF page of every section, figure, table and numbered equation, for the `{p.N}` links in detail bullets.
   **Check each paper here:** `place --run-dir <run> --citekey <key ...>` is the check for `reading.json`; write no validator of your own. It reports reading problems and dropped items and draws `preview_p*.png` in the paper's folder. Fix what it reports: for a dropped item pick another sentence (or the other half of one split by a page break) or another figure/equation, or delete it. Look at the paper's previews; a highlight on the wrong lines is worse than a dropped one. Repeat until nothing is dropped or misplaced, and report any item you had to give up. Its coverage line (annotations by colour, frames, pages covered) is for your own check, not a target. The first `place` of a paper can take minutes (figure search): give the command a timeout of at least 10 minutes.
   **In parallel:** papers are independent in this step. An agent that can run sub-agents in parallel may give each a share of the papers; each loads this skill, writes only its own papers' `reading.json` and runs `pagemap`/`place` only with `--citekey` for its own papers. Every other step runs once per batch, in order, in one agent.
3. **Place the batch:** `place --run-dir <run>` once. Papers already placed and checked in step 2 come back "unchanged"; only papers placed now (changed since, or never checked) need fixing and a preview check here, as in step 2. One agent working alone may skip the per-paper runs and do the whole check here. If you cannot view images, say so and ask the user to check the previews before step 4.
4. **Zotero:** `zotero-script --run-dir <run>`, then give the user `import-ai-annotations.js` to paste (show the script text in chat if the file cannot be opened) and mention `undo-ai-annotations.js`. Wait for the user.
5. **Verify:** `verify --run-dir <run>` (read-only API). Stop and report on any problem.
6. **Notes:** `note --run-dir <run> --agent "<agent and model>"`. It renders each note with the user's installed BibNotes, fills the six fields, checks YAML, pictures and that an immediate BibNotes re-update inserts nothing beyond BibNotes's known quirks (which it lists in the report), and only then writes the note and its pictures into the vault. `--agent` names the agent and model that wrote `reading.json`, with the reasoning effort when known. If the reading was delegated, name the sub-agent that did it, not the one that delegated, e.g. "opencode document (gpt-6.1-sol, medium)" or "Codex (gpt-6.1-sol, high)".
7. **Report** from `<run>/report.md`: notes written (as links), annotations placed and dropped, skipped papers, problems of the Markdown conversion you noticed (these belong here, not in the notes), and the user's remaining step: MarkDB-Connect → Sync Tags in Zotero.

When the user takes a paper over, nothing special is needed: AI annotations can be edited, recoloured or deleted like their own; removing the `ai-draft` tag in Zotero removes it from the note at the next update.
