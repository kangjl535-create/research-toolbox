# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.5.1`
- Fixed commit: `0b262d3cd806e17d708f491430f25dfcb72c02ae`
- Skill directory Git tree: `c27048e8af11c4242db39422f4263d8920a720de`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/0b262d3cd806e17d708f491430f25dfcb72c02ae/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-11-24T03:35:42+00:00`
- Acquisition timestamp: `2026-11-24T03:35:42+00:00`
- Upstream declared skill version: `0.5.1`
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.5.1`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.5.1](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.5.1) (2026-11-24).

## Preservation and changes

All 11 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and seven scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (305 checks) passed locally and in the upstream CI on the release commit, and 426 offline and read-only live checks passed with Zotero 10. This release finds a paper's notes by its Zotero item in any vault folder and adds to each of them with `--update`; 0.5.0 skipped papers whose note was not in the folder mirroring the PDF's. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
