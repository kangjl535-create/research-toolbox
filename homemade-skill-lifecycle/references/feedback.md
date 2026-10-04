# Defect Feedback

Daily use meets inputs and environments that tests never covered. One short note per defect, kept outside the skill and its repositories, lets the next update start from real failures instead of memory.

## Location

`%OneDrive%\AI-Config\Skills\feedback\<skill-name>\` (PowerShell `$env:OneDrive`, Git Bash `$OneDrive`). Windows sets `%OneDrive%` to each machine's OneDrive root, whose drive differs between machines, so never write a drive letter. Create the skill's folder when needed. If `%OneDrive%` is unset or `%OneDrive%\AI-Config\Skills` does not exist, write nothing and say so in the report. Notes never go into a skill directory, a Git repository, a release ZIP, or an installed copy.

## What To Record

A defect of the skill shown in real use, not in a test:

- a script error or crash;
- a check that let a wrong result through, or rejected a valid one;
- a result the agent had to correct or work around;
- the user correcting the skill's output;
- instructions that proved wrong, missing, or ambiguous.

Not defects: expected outcomes (documented skips, missing inputs, user decisions) and environment problems the skill could not reasonably detect or handle. When unsure, record it and say so in the note.

## Note Format

One file per incident, `<YYYY-MM-DD>-<short-slug>.md` (append `-2` if the name is taken). During use, never edit an existing note: a recurrence gets its own note that names the earlier file. Separate files keep OneDrive from producing sync conflicts between machines.

```markdown
---
skill: <skill-name>
version: <version from SKILL.md or the manifest>
date: <YYYY-MM-DD>
reporter: <agent and model>
status: open
---
# <one-line summary>

- What happened:
- Expected:
- Evidence: <command, input identifiers (file name, citekey, hash), a short output excerpt>
- Workaround:
- Suggested fix: <optional>
```

Write paths relative to `%OneDrive%` (for example `%OneDrive%\Academic\Paper Library\Topic\Paper.pdf`) or to the project. Keep excerpts to a few lines. Never include credentials, tokens, keys, personal data, or long passages of source documents. List the notes written in the final report.

## Standard Skill Section

Every homemade skill carries this section in its `SKILL.md`, with its own name. It must be self-contained, because an installed skill cannot read this reference.

```markdown
## Recording Defects

When real use (not a test) shows a defect in this skill (a script error, a check that let a wrong result through, a result you had to correct or work around, a correction from the user, or instructions that proved wrong), write one note per defect to `%OneDrive%\AI-Config\Skills\feedback\<skill-name>\<YYYY-MM-DD>-<slug>.md`: front matter `skill`, `version`, `date`, `reporter` (agent and model), `status: open`; then what happened, what was expected, evidence (command, input identifiers, a short output excerpt; paths relative to `%OneDrive%`), and the workaround. No credentials or long source text; never edit an existing note. Expected outcomes (documented skips, missing inputs, user decisions) are not defects. If `%OneDrive%\AI-Config\Skills` does not exist, skip this and say so. List written notes in the final report.
```

## Review During An Update

1. Before planning, read every note in `feedback\<skill-name>\` (not `resolved\`). Group duplicates; reproduce what can be reproduced, preferably as a regression test.
2. Decide per note: fix in this release, keep open, or decline with a reason.
3. After the release is published, set `status: fixed` and `fixed_in: X.Y.Z` (or `status: declined` and `reason:`), move the note to `feedback\<skill-name>\resolved\`, and name the fixed notes in the release record.
4. When a skill is renamed, move its feedback folder to the new name.

Notes are maintainer records in the synchronized workspace, not release content.
