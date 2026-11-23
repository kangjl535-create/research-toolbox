# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `zotero-ai-reading`
- Upstream path: `paper-library-skills/zotero-ai-reading`
- Selected reference: tag `zotero-ai-reading-v0.5.0`
- Fixed commit: `19b114c1f3c91840122baf867590d7dfbfc57f64`
- Skill directory Git tree: `79dac85a5c0c1e7c74d4e0982fa30b88b7c90dda`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/19b114c1f3c91840122baf867590d7dfbfc57f64/paper-library-skills/zotero-ai-reading
- Source-query timestamp: `2026-11-23T17:39:40+00:00`
- Acquisition timestamp: `2026-11-23T17:39:40+00:00`
- Upstream declared skill version: `0.5.0`
- Distribution name: `zotero-ai-reading`; directory: `zotero-ai-reading`; distribution version: `0.5.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [zotero-ai-reading v0.5.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/zotero-ai-reading-v0.5.0) (2026-11-23).

## Preservation and changes

All 11 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/reading.md, references/setup.md and seven scripts. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (295 checks) passed locally and in the upstream CI on the release commit, and 414 offline and read-only live checks passed with Zotero 10; the locator was compared with 0.4.0 on 1,708 frames of earlier runs. This release makes every reading serve a question (`--task`), adds searchable `#中文` content tags (Zotero item and note) and frame titles, and fixes 45 recorded defects. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
