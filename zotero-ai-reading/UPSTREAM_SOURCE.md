# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.3.0`
- Fixed commit: `6cb6ff9cb0006266adb9613b7252cf9dfca90ec8`
- Skill directory Git tree: `7a3ade35c8c36faa4bfc6610e4aa58693e61becc`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/6cb6ff9cb0006266adb9613b7252cf9dfca90ec8/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-10-08T08:44:11+00:00`
- Acquisition timestamp: `2026-10-08T08:44:11+00:00`
- Upstream declared skill version: `0.3.0`
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.3.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.3.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.3.0) (2026-10-08).

## Preservation and changes

All 11 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and seven scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (85 checks) passed locally and in the upstream CI on the release commit; this release writes to Zotero 10 through its local API instead of pasted scripts and builds the annotation note itself (new scripts/note_html.py). This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
