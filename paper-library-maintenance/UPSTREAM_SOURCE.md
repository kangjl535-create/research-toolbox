# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `paper-library-maintenance`
- Upstream path: `paper-library-skills/paper-library-maintenance`
- Selected reference: tag `paper-library-maintenance-v0.1.0`
- Fixed commit: `a19af5f42706baa75e7639daa16f13483c559431`
- Skill directory Git tree: `4edc14cbc95f864117ee2aff2b53fd1a3244df51`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/a19af5f42706baa75e7639daa16f13483c559431/paper-library-skills/paper-library-maintenance
- Source-query timestamp: `2026-10-05T06:22:36+00:00`
- Acquisition timestamp: `2026-10-05T06:22:36+00:00`
- Upstream declared skill version: `0.1.0` (SKILL.md "Release")
- Distribution name: `paper-library-maintenance`; directory: `paper-library-maintenance`; distribution version: `0.1.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [paper-library-maintenance v0.1.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/paper-library-maintenance-v0.1.0) (2026-10-05).

## Preservation and changes

All 3 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml and scripts/library_maintenance.py. Tests stay in the upstream repository. LICENSE and this source record are distribution additions.

## Validation and update boundary

Upstream: the behavior suite (28 checks, including MinerU's and Marker's own checks on relocated conversions) passed locally and in the upstream CI on the release commit. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
