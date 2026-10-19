# Author profile

Authors mark mistakes, calculated versus actual amounts, emphasis and task status in their own ways. A profile holds the legends one author has confirmed, so later runs apply them without asking again and cite them in traceability. A legend belongs to its author; never apply it to another author's notes.

## Load at the start

- Use the `author_profile` path when supplied. Otherwise use `labnote-profile.md` in the template's directory when it exists, and tell the user it is being applied. Search nowhere else.
- Record it in the traceability manifest: `- Author profile: <file> (SHA-256 <hash>); legends applied: L1, L3`, or `- Author profile: none`.
- Apply a legend only within its scope. A mark outside every scope (for example arrows in prose when the legend covers recipe tables) is a question for the author, not a rule.
- A legend is an explicit author statement (evidence tier 2 in [conversion-policy.md](conversion-policy.md)). It interprets marks on the page; it never supplies content the page lacks.

## Ask once when legends are missing

If there is no profile, or it has no deletion legend, ask the author before transcribing, in one short message, about the marks that occur in this record:

- deletions: is struck text a mistake to leave out, or superseded content to keep as crossed out? What does a deletion look like (one or two short lines, a scribble, a long line)?
- arrows between values (`a → b`);
- ink colours;
- task symbols such as √, × and □.

If the author cannot answer now, continue with the default rules and queue each open legend as a `relationship` item. Answers given during the run apply at once; log them with the other author feedback and offer to save them to the profile.

## Format

One Markdown table; see the [example profile](../assets/labnote-profile.example.md). Keep the profile with the author's records, outside the skill package.

| Column | Content |
| --- | --- |
| ID | `L1`, `L2`, … stable; never reuse an ID |
| Mark | what it looks like on the page |
| Meaning | what the author means by it |
| Rule | how to transcribe it |
| Scope | where it applies: all records, recipe tables, one notebook |
| Confirmed on | records and dates on which the author confirmed it |
| Source | where the confirmation is recorded: feedback log, review item, chat date |

## Deletion legends

- **Keep** (the default without a legend): legible, relevant struck text is shown as crossed out, and illegible struck content is recorded as illegible.
- **Omit**: struck text is a writing error. Do not read or transcribe it anywhere. `final.md` leaves it out without a note, `traceability.md` records only its location (for example `[deletion]` inside the literal line), and replacement text written beside or above it is the record. Do not queue doubts about what a deletion said.

Under either rule, separate task crosses from deletion marks. Under the omit rule a deletion read as content is the most common error, so queue "deleted or content?" for every doubtful mark (see the deletion cues in [conversion-policy.md](conversion-policy.md)).

## Update after review

When the author confirms a new legend or extends a scope, append the row or add the record to `Confirmed on`, with the author's agreement. Do not delete or rewrite earlier rows; mark a withdrawn legend `withdrawn <date>` in its Rule cell. Never create or change a profile silently.

## Validation

`validate_outputs.py --profile <file>` checks the legend table columns, unique `L` IDs, non-empty mark, meaning and rule, the `- Author profile:` manifest field, and that every ID listed after `legends applied:` exists in the profile. It does not check that a legend was applied correctly.
