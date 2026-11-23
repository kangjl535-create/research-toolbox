# Reading a paper: what to write in `reading.json`

Read the whole converted Markdown (MinerU or Marker), not just the abstract. To check something in the PDF (a garbled equation, a figure), extract or render only that page; opening the whole PDF costs tens of thousands of tokens. The note's metadata, abstract and author list come from Zotero through BibNotes; the agent writes the annotations, the six fields and the tags.

## Read with the question, record more than the question

Every run has a question: the research task in `batch.json` (`task`), e.g. "permeability measurements of hydrogels". The topic folders of the paper's note (`note_path`) name the project the paper was collected for.

- **Focus on the question.** Annotate in detail everything in the paper that the question needs: values with their conditions, methods, figures, tables, models.
- **Do not stop at the question.** Also annotate the paper's other important content, so that a later question does not need another full reading: a paper read for permeability that also measures diffusivity gets its diffusivity results annotated as well, and a tag says the paper has them.
- **The note is the paper's evidence record.** The user and later agents read the note instead of the PDF, for example to write a review; `--update` adds what a later question finds missing. Keep in the annotations, their comments and the detail bullets, with page links:
  - every classification, regime or limiting case the paper states, with its criterion or threshold and its source (the paper's own, or the cited work);
  - for each reported quantity: what exactly it is, the method, the material and conditions, the values and their range;
  - for each data figure or table: what is plotted against what, and where compiled data come from (author, year);
  - for each model: its assumptions, inputs and the range it was validated over;
  - the limitations the authors state;
  - in a review: which statements are the reviewers' own and which are reported from cited work.
- **Cover every main section** (introduction, method, results, discussion, conclusion; in a review each of its sections, which are separate topics). `place` lists pages without any annotation: a section left out there needs a reason in your report.
- **No target number.** Annotate by importance: one annotation per point; a figure or table is framed once, not quoted sentence by sentence; nothing is annotated to fill a page.

## Colours (the user's meanings)

| colour | what it marks |
|---|---|
| `green` | **Background:** the important literature of the field and the work this paper builds on directly. Name the cited work (author, year) in the comment. Not the paper's own aim or contribution. |
| `orange` | **Methods:** the important equations, boundary and initial conditions, assumptions and experimental set-ups; the main methods the paper uses to reach its results. Frame key equations rather than quoting the words around them. |
| `yellow` | **Results:** the main results and conclusions, especially the paper's innovations (`AI：创新——…`); the sentence stating the paper's aim or main contribution (`AI：主旨——…`). Frame the key result figures and tables. |
| `red` | **Doubtful or an opportunity:** a statement that may be wrong or incomplete, or that could be a research opportunity for the user. Say why, or what the opportunity is. |
| `blue` | **Inspiring:** a method, idea or structure that could serve the user's research (the question and the project). Say how. Leave it out when nothing fits. |

## The six fields

Chinese. Each is `{"text": "...", "details": ["...", ...]}` or just a string (text only). The fields describe the paper itself; the question shows in what the annotations cover and in `Inspiration`.

| field | what it holds |
|---|---|
| `Summary` | An overview of the whole paper: what the authors did and what they found, so that the user grasps the paper from this field alone. |
| `Objective` | The problem the paper sets out to solve and the goal it wants to reach. |
| `Method` | First the kind of method (experiment, simulation, analysis or theory, review), then the details: techniques, equipment, materials, models, key parameters. Enough to decide whether the method can be used or needs a close reading. |
| `Conclusion` | The main results, quantitative where the paper is, with the conditions under which they hold. |
| `Gap` | The paper's limitations: those the authors state, and the agent's own analysis, kept apart; written to point to possible future research. |
| `Inspiration` | The paper's innovations (in method, modelling, design or anything else) and how they could inspire the user's research. |

- **`text`:** one to three concise sentences, with no page links.
- **`details` (optional):** bullets with the important specifics only (in Method the numbered governing equations, boundary conditions, set-up and parameters; in Conclusion the quantitative results). Write no bullet just to have one.
- **Page links:** a bullet about a specific equation, figure or result cites its page as `{p.N}`, using the PDF page index N (1-based, not the printed page number) from `pagemap --run-dir <run>`. `note` turns it into a link that opens the PDF at that page, labelled with the printed page number. A range is allowed only for a derivation over at most 3 consecutive pages (`{p.4-5}`).
- **Labels:** mark the agent's own analysis `AI 分析：` and suggestions `AI 建议／待验证：`.
- **About the paper only:** notes on the reading process or the tools go into the chat report, not the fields.
- **Characters:** math with `$...$` is fine; write comparisons as math (`$L/D<1$`) or words, never a bare `<` in text.

## Highlights

- `quote` is copied **verbatim** from the Markdown (the script rejects anything else) and is one sentence or a clause, usually 60–300 characters: the whole statement that carries the point, not a fragment (`place` lists quotes under 40 characters). Do not quote across a page break, figure, table or footer (the Markdown hides page breaks: if a sentence starts at the bottom of a column, quote only one part).
- No `<`, `>`, `$` or LaTeX in a quote: BibNotes writes the quote raw inside `<mark>` and Obsidian stops rendering the note at a bare `<`. Frame the equation or figure instead, or quote the part without them.
- `comment` starts with `AI：`, is Chinese, names the role and says why it matters: `AI：背景——…（作者, 年份）`, `AI：方法——…`, `AI：关键结果——…`, `AI：创新——…`, `AI：主旨——…`, `AI：存疑——…（理由）`, `AI：机会——…`, `AI：启发——…（如何用于你的研究）`. Keep facts and interpretation apart; mark speculation. The highlight carries its page; the comment needs no page link.

## Frames (image annotations)

`{"kind": "figure"|"equation"|"table", "n": 7, "color": ..., "comment": "AI：..."}`, with `n` as printed: `7`, `"2.5"`, `"A1"`, `"B.1"`, `"12a"`, or a Roman table number such as `"IV"`.

- Frame key equations and conditions (usually orange) and key result figures and tables (usually yellow). In a review, a figure or table that compiles a quantity across materials or studies is a key result: frame it in yellow, say what is plotted against what and name its sources (author, year).
- `place` puts the number and the caption's title in front of the comment (`AI：【Fig. 7. Permeability of agarose gels versus concentration】关键结果——…`), so the comment need not repeat them: say what the figure or table shows and what matters in it. A figure frame covers all its panels; name the panel the comment is about.
- Figures need the figure image in the Markdown, equations their printed number in the PDF (or `\tag{n}` in the Markdown), tables their caption and the table. When the converter dropped or garbled the caption's label ("Table 1" missing before the caption text), add `"caption": "<the first words of the caption as the Markdown has them, at least 15 characters>"`.
- `place` drops a frame it cannot locate or would place wrongly, and says why. When the Markdown garbles an important equation, frame it (the frame shows the PDF) instead of quoting it.

## Tags

`"tags": ["#渗透率测量", "#扩散系数测量"]`: searchable labels of what the paper contains, so that a later question finds the paper even where an earlier reading left the details out. `write` adds them to the Zotero item; the note shows them in its `tags:`.

- Each names one kind of content someone may search for later: a measured quantity with its values, a data set or compilation, a model or theory, a method or technique, a material system (`#渗透率测量`, `#渗透率数据汇编`, `#双相模型`, `#PDMS键合`).
- Chinese, starting with `#`, as short as it can be while precise; letters, digits and `-` only (no spaces or other punctuation, which Obsidian does not index); a standard abbreviation is fine.
- For the paper's important content, whether or not the question needs it; usually 2–6.
- Reuse a tag from `existing_tags` in `batch.json` (the user's `#` tags with their counts) when it means the same; make a new one only when none fits.

## Adding to a paper read before (`--update`)

The paper has annotations (AI-tagged, the user's, or stored in the PDF file) and usually a note, an AI draft or the user's own. Before writing anything, read the note (`note_path` in `batch.json`; its `ai_updates` lists the questions it was read for) and `<run>/<citekey>/existing-annotations.json` (every annotation on the PDF: who made it, colour, page, text, comment). Then read the whole Markdown again with the new question.

- **Add what the note lacks:** what the new question needs, and the paper's own content the note does not have yet (a field of the user's note that is empty, a section no annotation covers).
- **Annotations** are the main place for new content: highlight the original sentences and frame the figures, tables and equations. `place` drops a new highlight or frame of which half or more lies under existing ones of the same kind (or under an earlier item of the same reading): a new point about an annotated sentence or figure goes into a field addition instead.
- **`fields` holds only additions**, any subset of the six: what is new relative to the note's fields, never a restatement of them; a field the note leaves empty gets its full content. `note` puts each below that field's text as `- **AI 补充（<date> · <task>）**：…`. A paper with no note yet needs all six fields, as a new note does; when its annotations already cover it, the reading may consist of the fields and tags alone.
- **Tags:** only those the paper does not have yet.
- The user's text stays as it is: do not contradict it in an addition without saying so (`AI 分析：…与笔记中……不同，因为……`).

## Format

```json
{
  "fields": {
    "Summary": {"text": "…"},
    "Objective": {"text": "…"},
    "Method": {"text": "实验：……", "details": ["控制方程 Eq. (3)：… {p.2}", "边界条件：… Eq. (5) {p.3}"]},
    "Conclusion": {"text": "…", "details": ["Fig. 7：… {p.6}"]},
    "Gap": {"text": "作者指出……。AI 分析：……"},
    "Inspiration": {"text": "创新：……。AI 建议／待验证：……"}
  },
  "tags": ["#渗透率测量", "#Forchheimer方程"],
  "highlights": [
    {"color": "green", "quote": "A popular method for representing the postlinear regime is to exchange Darcy's Law with Forchheimer's equation",
     "comment": "AI：背景——后线性区常用 Forchheimer 方程代替 Darcy 定律（Forchheimer, 1901）。"},
    {"color": "orange", "quote": "We assume that the fluid velocity u within the permeable rock is given by Darcy's law:",
     "comment": "AI：方法——刚性多孔介质中的不可压缩 Darcy 流。"}
  ],
  "regions": [
    {"color": "yellow", "kind": "figure", "n": 7, "comment": "AI：关键结果——……"}
  ]
}
```
