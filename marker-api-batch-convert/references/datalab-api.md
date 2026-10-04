# Datalab Convert API Notes

Checked against the Datalab conversion documentation on 2026-10-04: https://documentation.datalab.to/docs/recipes/conversion/conversion-api-overview

## Requests

- Submit: `POST https://www.datalab.to/api/v1/convert`, header `X-API-Key`, multipart `file`. Response: `success`, `request_id`.
- Poll: `GET /api/v1/convert/{request_id}` with the same header until `status` is `complete`. The result carries `markdown`, `images` (`{filename: base64}`), `page_count`, `parse_quality_score` (0-5), `cost_breakdown.final_cost_cents`, `metadata.failed_pages`. An EU-region `result_url` is downloaded without the key, only from a public HTTPS host.
- Fixed parameters: `output_format=markdown`, `paginate=false` (no page delimiters, like MinerU), `disable_image_extraction=false`, `disable_image_captions=true`. `mode` is `fast`, `balanced` (default here), or `accurate`.
- Limits: 200 MB per file. Large page counts are allowed by the service; the skill's `--max-pages` (default 200) is a local cost guard.
- Not used: `merge_cross_page` merges only across pages and adds a variable charge; the observed split sentences were column breaks within a page, which local normalization rejoins. Paid extras such as chart understanding generate content and stay off.
- `parse_quality_score` is often still null when the job completes and appears later; the report records what was returned at completion.

## Failure Classification

| Situation | Handling |
|---|---|
| DNS failure, refused or timed-out connection | Nothing uploaded; checkpoint removed; `Failed`. |
| Read error, reset, HTTP 408 or 5xx after the upload began | Job may exist and be billed; checkpoint kept as `submitting`; `UncertainSubmission`. |
| HTTP 429 on submit | Not accepted; retried 3 times with backoff, then `Failed`. |
| HTTP 401/403 | Key rejected; all remaining uploads stop. |
| Other 4xx, or `success: false` | Definite rejection; checkpoint removed; a later rerun uploads again. |
| Poll 404 | Job unknown or expired; checkpoint removed; next run uploads again. |
| Poll network error, 408, 429, 5xx | Retried until `--poll-timeout`, then `Pending`. |
| Completed with `success: false` or empty Markdown | `Failed`; a rerun uploads again. |

Error messages are shortened and stripped of URLs before they reach a report.

## Local State

Everything machine-local is under `%LOCALAPPDATA%\AI-Config\marker-api-batch-convert\`, never beside papers or in OneDrive:

- `checkpoints\<key>.json`: source path and hash, parameters, status (`submitting`, `submitted`, `downloaded`, `failed`), request id. The key hashes the PDF path and content, so a changed PDF never reuses an old job. A resumed job keeps the parameters it was submitted with; if the current run asked for others, the item gets a `notice`.
- `payloads\<key>.json`: the downloaded result until publication. Checkpoint and payload are deleted after a successful publication.
- `reports\marker-<action>-<time>.json`: one report per run.
- `convert.lock`: one convert run per computer at a time.

## Publication

Before writing, the PDF hash must match the uploaded one and neither output may exist. Images are decoded and verified; only referenced images are written, and the marker records `assetsSha256` (SHA-256 over sorted `name<TAB>sha256` lines of the asset files). `scan` and `convert` recheck existence, decodability, file count, and that digest; markers from rc.1 without a digest get the other checks. Every image reference must point at a returned image and is rewritten to `<stem>.assets/<name>` with each segment URI-encoded. Files are written under `.marker-partial-<token>` names and renamed into place; a rename never replaces an existing path, and a failed attempt removes only what it created.

## Coexistence With MinerU

Both converters skip each other's outputs (`MinerUOutput` here; `ExistingUntracked` in mineru-api-batch-convert). Once MinerU works again, either may convert new PDFs; neither replaces the other's results.

## Test Overrides

`MARKER_API_BASE` (a loopback mock) and `MARKER_BATCH_LOCAL_DATA` exist for the offline tests. With `MARKER_API_BASE` set, the Windows user-environment key is never read; do not point either at real services or synchronized folders.
