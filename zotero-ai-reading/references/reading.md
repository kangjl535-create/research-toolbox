# Reading a paper: what to write in `reading.json`

Read the whole MinerU Markdown, not just the abstract. To check something in the PDF (a garbled equation, a figure), extract or render only that page; opening the whole PDF costs tens of thousands of tokens. The note's metadata, abstract and author list come from Zotero through BibNotes; the agent writes only the annotations and the six fields. The user reads these notes to decide what to study closely and to find material for their own research.

**The user's research:** the topic folders of the paper's note (`note_path` in `batch.json`, e.g. `…\Cerebral fluid transport\Exponential decay in tissue K measurement\…`) name the project the paper was collected for. Aim blue annotations, red opportunities and `Inspiration` at that project, and say concretely how the idea would serve it.

## What to annotate (the user's colour meanings)

| colour | what it marks |
|---|---|
| `green` | **Background:** the important literature of the field and the work this paper builds on directly. Name the cited work (author, year) in the comment. The paper's own aim, approach or contribution is *not* green. |
| `orange` | **Methods:** the important equations, boundary and initial conditions, assumptions and experimental set-ups; the main methods the paper uses to reach its results. Frame key equations rather than quoting the words around them. |
| `yellow` | **Results:** the main results and conclusions, especially the paper's innovations (comment `AI：创新——…`). Frame the key result figures and tables. |
| `red` | **Doubtful or an opportunity:** a statement of the paper that may be wrong or incomplete, or that could be a research opportunity for the user. Say why, or what the opportunity is. |
| `blue` | **Inspiring:** any method, idea or structure that could serve the user's research. Say how. Best effort; leave it out when nothing fits. |

Coverage, not counting:
- Cover the background, methods and results the paper actually has, drawn from the whole paper (introduction, method, results, discussion, conclusion), not only the abstract and the conclusion.
- Decide each annotation on its importance. There is no target number. For orientation only, a typical research paper has needed roughly 12–20 annotations including frames; a long, important paper needs more, and a short reply or a weak paper a few. Never add an annotation to reach a number, and never stop at one.

## Highlights

- `quote` is copied **verbatim** from the Markdown (the script rejects anything else) and is one sentence or a clause, usually 60–300 characters. The highlight is what the user sees in the PDF, so quote the whole statement that carries the point, not a fragment of a few words (`place` lists quotes under 40 characters). Do not quote across a page break, figure, table or footer (the Markdown hides page breaks: if a sentence starts at the bottom of a column, quote only one part).
- No `<`, `>`, `$` or LaTeX in a quote: BibNotes writes the quote raw inside `<mark>` and Obsidian stops rendering the note at a bare `<`. For a statement that needs them, frame the equation or figure instead, or quote the part without them.
- `comment` starts with `AI：`, is Chinese, names the role and says why it matters: `AI：背景——…（作者, 年份）`, `AI：方法——…`, `AI：关键结果——…`, `AI：创新——…`, `AI：存疑——…（理由）`, `AI：机会——…`, `AI：启发——…（如何用于你的研究）`. Keep facts and interpretation apart; mark speculation.
- The highlight itself carries its page; the comment needs no page link.

## Frames (image annotations)

`{"kind": "figure"|"equation"|"table", "n": 7, "color": ..., "comment": "AI：..."}`, with `n` as printed: `7`, `"2.5"`, `"A1"`, `"12a"`, or a Roman table number such as `"IV"`. Frame key equations and conditions (usually orange) and key result figures and tables (usually yellow). A figure frame covers all its panels; name the panel the comment is about. Figures need MinerU's figure image in the Markdown, equations their printed number in the PDF (or `\tag{n}` in the Markdown), and tables a `Table n.` caption followed by the table. The script reports what it could not locate. When the Markdown garbles an important equation, frame it (the frame shows the PDF) instead of quoting it.

## The six fields

`Summary`, `Objective`, `Method`, `Conclusion`, `Gap`, `Inspiration`, in Chinese. Each is `{"text": "...", "details": ["...", ...]}` or just a string (text only).

- **`text`:** one to three concise sentences, with no page links.
- **`details` (optional):** bullets with the important specifics only. They suit Method best (the numbered governing equations and boundary conditions, the set-up, key parameters) and Conclusion (quantitative results, the innovation, the conditions under which they hold). Use bullets elsewhere only when something important would otherwise be lost, and write no bullet just to have one.
- **Page links:** a bullet about a specific equation, figure or result cites its page as `{p.N}`, using the PDF page index N (1-based, not the printed page number) from `pagemap --run-dir <run>`. `note` turns it into a link that opens the PDF at that page. A range is allowed only for a derivation over at most 3 consecutive pages (`{p.4-5}`); the script rejects wider ranges.
- **Labels:** mark the agent's own analysis `AI 分析：` and suggestions `AI 建议／待验证：`; in `Gap`, keep the authors' stated limitations apart from the agent's.
- **About the paper only:** notes on the reading process or the tools (what was read, page mapping, equations garbled by the conversion) go into the chat report, not the fields.
- **Characters:** math with `$...$` is fine; write comparisons as math (`$L/D<1$`) or words, never a bare `<` in text.

## Format

```json
{
  "fields": {
    "Summary": {"text": "…"},
    "Objective": {"text": "…"},
    "Method": {"text": "…", "details": ["控制方程 Eq. (3)：… {p.2}", "边界条件：… Eq. (5) {p.3}"]},
    "Conclusion": {"text": "…", "details": ["Fig. 7：… {p.6}"]},
    "Gap": {"text": "作者指出……。AI 分析：……"},
    "Inspiration": {"text": "AI 建议／待验证：……"}
  },
  "highlights": [
    {"color": "green", "quote": "A popular method for representing the postlinear regime is to exchange Darcy's Law with Forchheimer's equation",
     "comment": "AI：背景——后线性区常用 Forchheimer 方程代替 Darcy 定律（Forchheimer, 1901）。"},
    {"color": "orange", "quote": "We assume that the fluid velocity u within the permeable rock is given by Darcy's law:",
     "comment": "AI：方法——刚性多孔介质中的不可压缩 Darcy 流。"}
  ],
  "regions": [
    {"color": "yellow", "kind": "figure", "n": 7, "comment": "AI：关键结果——Fig. 7 …"}
  ]
}
```
