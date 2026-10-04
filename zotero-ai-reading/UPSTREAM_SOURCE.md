# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.1.1`
- Fixed commit: `e745deb4f1009ba55132453333b04a64d2506c3b`
- Skill directory Git tree: `b758b10320fdc4ef2254d6d2569bdd12cefd2ebb`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/e745deb4f1009ba55132453333b04a64d2506c3b/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-10-04T09:30:48+00:00`
- Acquisition timestamp: `2026-10-04T09:30:48+00:00`
- Upstream declared skill version: `0.1.1` (SKILL.md "Release")
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.1.1`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.1.1](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.1.1) (2026-10-04).

## Preservation and changes

All 10 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and six scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (61 checks) passed in the upstream CI on the release commit; the full suite (93 checks, including the maintainer's Zotero library and Obsidian vault) passed locally. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
