# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.4.0`
- Fixed commit: `055483be993e96f0e167e722d75a0cada881aa6f`
- Skill directory Git tree: `50ca87cc034e1a34bfcd67a3e698f17bef89f360`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/055483be993e96f0e167e722d75a0cada881aa6f/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-11-17T19:12:49+00:00`
- Acquisition timestamp: `2026-11-17T19:12:49+00:00`
- Upstream declared skill version: `0.4.0`
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.4.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.4.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.4.0) (2026-11-17).

## Preservation and changes

All 11 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and seven scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (190 checks) passed locally and in the upstream CI on the release commit, and 294 read-only live checks passed with Zotero 10; this release adds `prepare --update`, which adds AI annotations and dated field additions to papers read before or with the user's own note without changing the note's existing lines. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
