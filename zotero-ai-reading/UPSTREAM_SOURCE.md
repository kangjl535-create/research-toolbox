# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.1.0`
- Fixed commit: `193c8cdc886e42daa1348da88f1c4869ee347e09`
- Skill directory Git tree: `31c265582ad319847ead98c39d6a435e5e3341ff`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/193c8cdc886e42daa1348da88f1c4869ee347e09/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-10-03T16:21:30+00:00`
- Acquisition timestamp: `2026-10-03T16:21:30+00:00`
- Upstream declared skill version: `0.1.0` (SKILL.md "Release")
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.1.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.1.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.1.0) (2026-10-03).

## Preservation and changes

All 10 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and six scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (54 checks) passed in the upstream CI on the release commit; the full suite (86 checks, including the maintainer's Zotero library and Obsidian vault) passed locally. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
