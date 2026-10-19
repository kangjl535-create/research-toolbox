# Evidence-first conversion policy

## Evidence hierarchy

Use this order:

1. Visible original source page.
2. Explicit user correction or supplementation, clearly attributed.
3. OCR draft as a navigation and candidate-reading aid.
4. Scientific context only to notice possible errors, never to replace source evidence.

Agreement between two OCR systems does not make a value reliable when the page disagrees. Pay special attention to identical OCR errors in exponents, decimal points, subscripts, and units.

## Page inspection

Inspect every page at sufficient resolution. Re-render or crop a region when needed. For each page, account for:

- prose and headings;
- numbers, ranges, decimal points, signs, and exponents;
- variables, subscripts, superscripts, formulas, and units;
- arrows, braces, grouping, spatial reading order, and diagram labels;
- deletions, overwrites, insertions, and revised calculations;
- tables, sketches, and references to external files.

Do not infer text hidden by a strike-through. If it remains legible and is relevant, mark it as crossed out; otherwise record that crossed-out content is illegible. A confirmed omit legend in the author profile overrides this rule: struck text is not read or transcribed, and traceability records only its location ([author-profile.md](author-profile.md)).

## Faithful representation

- Preserve the original language and terminology.
- Convert formulas to LaTeX only when the symbols and structure are clear.
- Preserve ranges and approximate signs; do not turn `~`, `≈`, or an arrow into equality.
- Preserve original units. Do not convert units unless the source itself does so.
- Preserve the writer's conclusion strength. A question remains a question; a possibility remains tentative.
- Do not silently repair scientifically implausible content. Flag it for review.
- When a sketch shows structure (grouping, assignment, flow, layout, timeline), re-express what it means as a Markdown table or a Mermaid graph: every label becomes a cell or node, and every drawn link becomes a cell position or an edge. Do not walk through the drawing in prose ("on the left…", "the arrow points to…"). Add no link that is not drawn; queue an ambiguous arrow, bracket or grouping as a `relationship` item instead of resolving it. Record in traceability which diagram elements became which rows, columns or edges. Use prose only for a drawing with no structure to extract (for example a freehand picture of a device), as a short caption that points to its page and region. See the example in [review-files.md](review-files.md).

## Confidence decisions

Use three operational states:

- **Confirmed:** clearly visible on the page and safe to place in `final.md`.
- **Uncertain:** present on the page but one or more characters, numbers, structures, or relationships are ambiguous. Place the best literal reading only when useful, attach `⟦U###⟧`, and list alternatives without choosing by context.
- **Absent:** no supporting source content. Leave the template value blank and do not create an uncertainty.

Use a fourth routing status in `traceability.md`:

- **Unmapped:** visible content that cannot be assigned to a template field without interpretation. Preserve it in the evidence map and flag it for manual placement when important.

## Mapping without invention

Map semantically rather than by exact wording, but require direct support. Typical safe mappings include a visibly written date into a date field, an explicitly named material concentration into actual conditions, or a written next-step instruction into a next-step field.

Unsafe mappings include:

- inferring an objective from a calculation when none is written;
- creating a sample count from several measurements;
- identifying an operator from file ownership;
- assigning a device version from a familiar setup;
- converting a speculative note into an observed result;
- completing a formula or unit from scientific convention.

If a single note item could fit multiple fields and the choice changes meaning, keep it unmapped and request review.

## OCR use

When an OCR draft exists, compare it against the page rather than polishing it in isolation. Copying a cleaner OCR string is acceptable only after visual confirmation. Preserve the raw OCR separately when it materially aids audit, but never propagate its unsupported prose into `final.md`.

## Dates, colors, arrows and recipe tables

- Segment by visible date headings within a page. A later date on the same page must not be silently assigned to the file-name date. Preserve month/day-only dates when the year is not supported. An undated opening block remains undated.
- Color changes may indicate theoretical versus actual quantities, annotations, different recording times, or corrections. An arrow is not sufficient evidence of replacement. Retain both endpoints and mark the relationship uncertain until the source or author establishes it.
- For recipes, first transcribe a literal grid including row labels, column labels, units, colors, missing cells and arrows. If column alignment or association is unclear, retain the row fragment with an uncertainty rather than silently binding values to reagents.
- Keep calculated amounts separate from actual added amounts. Do not copy an unannotated theoretical value into an actual-amount cell. If a later annotation omits its unit, preserve that omission unless inheritance is established; document any author confirmation.
- Do not change a concentration, pressure, exponent, coefficient, range endpoint or total merely to make arithmetic or physics consistent. Such checks can flag possible source issues only. Distinguish a transcription uncertainty (queue type `reading`) from a clearly read but possibly incorrect source statement (`source-check`).
- Preserve checkbox, tick and cross symbols without inventing an execution outcome when their semantics are unclear. Keep tasks, estimates, hypotheses, and questions visibly labeled if placed alongside observations.
- Once the author supplies a symbol legend, apply it and attribute it; offer to save a reusable one to the author profile. Keep completed tasks in the plan inventory with their status; never silently reclassify the task itself as an operation. Distinguish task crosses from deletion marks.
- Preserve manual indentation as ownership evidence. Child parameter lines belong under their visibly indicated object, not as peers of that object. Inspect image layout before flattening OCR text into bullets.
- Treat explicit problem and hypothesis blocks as substantive scientific content. Retain every numbered item and the distinction between observation, possible cause and proposed validation, including colored/marginal continuations. See [guided-template.md](guided-template.md) for the final completeness audit.
- Preserve readable marginal errands in unmapped evidence. Do not treat invoice amounts, page numbers or product codes as experiment measurements. Avoid guessing whether a numeric identifier is a catalog number or a lot number.

## Two-pass high-risk check

First read the full page with spatial context. Then revisit each number-unit pair, exponent, sign, formula structure, table alignment and deletion at detail scale. The second pass uses the image, not only the first-pass text.

Light deletions are easy to read as content. Treat these as possible deletion marks:

- a short stroke that crosses a glyph's outline at an angle or position unlike the glyph's own strokes;
- one or two short parallel lines over a character or digit, even when faint or blended with a horizontal stroke;
- an extra or duplicated glyph, or a word that reads naturally only without one glyph;
- a glyph whose reading requires ignoring one of its strokes;
- a dense or overwritten glyph next to a clean rewrite.

Queue each one as a `reading` item that asks "deleted or content?" and lists "possibly deleted" among the alternatives, never only alternative readings of the glyph. Use the deletion form described in the author profile to calibrate, not to skip the question. Record unresolved exact spans, not whole paragraphs marked vaguely uncertain. Previous model output, two agreeing OCR services and apparently sensible calculations cannot replace the page or explicit author feedback.
