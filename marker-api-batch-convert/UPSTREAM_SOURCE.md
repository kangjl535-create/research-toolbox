# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `marker-api-batch-convert`
- Upstream path: `paper-library-skills/marker-api-batch-convert`
- Selected reference: tag `marker-api-batch-convert-v0.1.0`
- Fixed commit: `4dd4bbefbcb7eb8258ce6a4ccd7df634c3a5a132`
- Skill directory Git tree: `042194b4e582571d4c4d3f4a806f5c018df036f4`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/4dd4bbefbcb7eb8258ce6a4ccd7df634c3a5a132/paper-library-skills/marker-api-batch-convert
- Source-query timestamp: `2026-10-04T12:40:00+00:00`
- Acquisition timestamp: `2026-10-04T12:40:00+00:00`
- Upstream declared skill version: `0.1.0`
- Distribution name: `marker-api-batch-convert`; directory: `marker-api-batch-convert`; distribution version: `0.1.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [marker-api-batch-convert v0.1.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/marker-api-batch-convert-v0.1.0) (2026-10-04).

## Preservation and changes

All 4 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, references/datalab-api.md and scripts/marker_batch_convert.py. Tests stay in the upstream repository. Skill name, code, behavior, dependencies and directory layout are unchanged. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the offline test suite (15 tests against a mock API) passed locally and in the upstream CI on the release commit. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
