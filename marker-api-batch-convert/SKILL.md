---
name: marker-api-batch-convert
description: Convert authorized local or Zotero-resolved PDFs to same-directory Markdown and image assets through the Datalab Marker API on Windows; the substitute for mineru-api-batch-convert while MinerU is unavailable. Use for missing conversions, scoped batch conversion, resuming interrupted jobs, or conversion audits. Preserves PDFs and every existing output.
---

# Marker API Batch Convert

Release: **0.1.0**. One Python script, run with the shared science environment from the task's working directory:

```powershell
$run = "$env:LOCALAPPDATA\AI-Config\bin\run-science.ps1"
& $run "<skill-directory>\scripts\marker_batch_convert.py" convert --pdf "D:\Papers\A.pdf" "D:\Papers\B.pdf"
& $run "<skill-directory>\scripts\marker_batch_convert.py" convert --root "D:\Papers\Topic" [--recurse]
```

If `run-science.ps1` is blocked (execution policy, sandbox), call the same interpreter directly: `"$env:LOCALAPPDATA\AI-Config\venvs\science\Scripts\python.exe" -B <script> ...`.

## Scope And Permission

- Resolve Zotero selections to absolute PDF paths through an available connector, or use paths the user gave. Use `--root` only for authorized folders and `--recurse` only for authorized subfolders; never the whole library by default.
- Converting uploads the PDFs to Datalab and is billed per document, not at a fixed page rate: on 2026-10-04 balanced cost 0.3 to 1.2 US cents per page and accurate 0.75 to 1.2. Confirm the upload scope with the user; for large scopes run `scan` first and state the page total, budgeting about 1.2 cents per page.
- The key is read from `MARKER_API_KEY` (or `DATALAB_API_KEY`) in the process or Windows user environment. Never ask for it in chat, print it, or write it to a file. A sandboxed agent may see neither the user environment nor `%LOCALAPPDATA%\AI-Config\marker-api-batch-convert` (lock, checkpoints): run `environment` with normal local access before concluding the key is missing; only if it still reports `keyConfigured: false` does the user set the variable themselves.

## Convert

Only PDFs with neither `Paper.md` nor `Paper.assets/` beside them are uploaded. The result is `Paper.pdf` (unchanged), `Paper.md`, and `Paper.assets/` with the referenced images: the same layout as MinerU, read directly by `zotero-ai-reading`. The first Markdown line is a `<!-- marker-batch-convert {...} -->` marker with the source hash, asset digest, mode, request id, cost, and normalization counts.

Defaults: `--mode balanced`, 4 PDFs in parallel (`--workers`, at most 8; batch time scales with it), PDFs over 200 pages skipped (`--max-pages`). Datalab's generated image descriptions are always disabled: they inserted invented values and tables into the text.

| Mode | List price per 1,000 pages | Measured (2026-10-04) |
|---|---|---|
| `balanced` (default) | 4 USD | 12-page born-digital paper in 39 s Datalab runtime: body, table, equations, figures correct; 4 reference-list slips. |
| `accurate` | 10 USD | Same paper in 114 s, those slips fixed. Scanned 8-page and historic 4-page papers in 46 s and 29 s. Inline math may come as `<sub>`/`<sup>`. |
| `fast` | 4 USD | Not faster and clearly worse (names, reference numbers, swapped primes). Do not use. |

Use `accurate` when the user asks, or for scanned, old, or table-dense PDFs; otherwise `balanced`. A job resumed from a checkpoint keeps its original mode; the report then carries a `notice`.

The published Markdown is normalized for MinerU-compatible readers, representation only: bold caption labels (`**Fig. 1.**`) are unbolded; a trailing printed number `\quad (n)` in display math, also after leader dots (`\quad \dots (A-1)`), becomes `\tag{n}`; pipe tables become one-line HTML `<table>`s with cell formatting as HTML (merged cells stay as blank cells); and a sentence split into two paragraphs by a column or page break is rejoined (a line-break hyphen before a lowercase continuation is dropped). Nothing else is changed.

Conversion is good but not exact. Real tests found a dropped prime in an equation, a lost table footnote mark, and misread author names or initials, also in `accurate` mode. For derivations, table values, or citations, check the key content against the PDF.

## Statuses

| Status | Meaning and action |
|---|---|
| `Converted`, `Current` | Done. `Current` means the marker, PDF hash, every referenced image (exists and decodes), and the asset digest all check out. |
| `Pending` | Accepted job still running at `--poll-timeout`; rerun the same command, which resumes without uploading. |
| `UncertainSubmission` | An upload may have reached Datalab. Ask the user to check usage at datalab.to; rerun with `--retry-uncertain` only after they agree (may bill twice). |
| `Failed` | Definite failure with a reason; a rerun uploads again. A rejected key stops all remaining uploads. |
| `Stale`, `IncompleteAssets`, `InvalidMarker`, `ExistingUntracked`, `MinerUOutput`, `AssetsWithoutMarkdown`, `Linked`, `ReviewRequired` | Never overwritten. Report them; replacement means the user first moves the old outputs to the Recycle Bin, then the PDF is `Missing` again. |
| `SkippedTooManyPages` | Raise `--max-pages` only with the user's agreement on cost. |

`scan` (same scope options, no upload, no key) previews statuses and the page total of `Missing` PDFs. `environment` reports the executing copy (`skillVersion`, `skillPath`), dependencies, and whether a key is configured, without revealing it.

## Report

Return the absolute `reportPath`, the status counts, `pagesConverted`, `costCents`, `totalSeconds` (wall-clock, including upload and polling), each non-converted filename with its reason, and any `notice`. Mention a `parseQualityScore` below 3 (often absent: Datalab computes it after completion) or non-empty `failedPages`. Never expose the key, signed result URLs, or raw API responses. Read [references/datalab-api.md](references/datalab-api.md) for API details, local state, and failure handling.

## Recording Defects

When real use (not a test) shows a defect in this skill (a script error, a check that let a wrong result through, a result you had to correct or work around, a correction from the user, or instructions that proved wrong), write one note per defect to `%OneDrive%\AI-Config\Skills\feedback\marker-api-batch-convert\<YYYY-MM-DD>-<slug>.md`: front matter `skill`, `version`, `date`, `reporter` (agent and model), `status: open`; then what happened, what was expected, evidence (command, input identifiers, a short output excerpt; paths relative to `%OneDrive%`), and the workaround. No credentials or long source text; never edit an existing note. Expected outcomes (documented skips, missing inputs, user decisions) are not defects. If `%OneDrive%\AI-Config\Skills` does not exist, skip this and say so. List written notes in the final report. Here that includes an API or polling failure the script did not handle, Markdown or images reported as converted but incomplete or wrongly linked, or a normalization (captions, equation tags, tables) that damaged content.
