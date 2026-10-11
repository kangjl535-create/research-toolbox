# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.3.1`
- Fixed commit: `c3ee408e9d3a94a189fa0f5cac119d91fffe1d97`
- Skill directory Git tree: `b11eead9a1dd236830f6130d56348b6c9aa75662`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/c3ee408e9d3a94a189fa0f5cac119d91fffe1d97/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-10-11T09:21:38+00:00`
- Acquisition timestamp: `2026-10-11T09:21:38+00:00`
- Upstream declared skill version: `0.3.1`
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.3.1`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.3.1](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.3.1) (2026-10-11).

## Preservation and changes

All 11 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and seven scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (130 checks) passed locally and in the upstream CI on the release commit, and 198 read-only live checks passed with Zotero 10; this release corrects highlight and frame placement and scan detection (place, prepare). This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
