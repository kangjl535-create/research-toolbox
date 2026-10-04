# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `homemade-skill-lifecycle` (formerly `codex-skill-lifecycle`, distributed here under that name until retained-skills v1.1.1)
- Upstream path: `skill-development-tools/homemade-skill-lifecycle`
- Selected reference: tag `homemade-skill-lifecycle-v2.0.0`
- Fixed commit: `cf7ffb1465f0ed138200fcdf42c9e2ef79018929`
- Skill directory Git tree: `f0ecebd5cc4ba44077ebe5f813b2a9217b13065f`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/cf7ffb1465f0ed138200fcdf42c9e2ef79018929/skill-development-tools/homemade-skill-lifecycle
- Source-query timestamp: `2026-10-04T10:15:29+00:00`
- Acquisition timestamp: `2026-10-04T10:15:29+00:00`
- Upstream declared skill version: `2.0.0` (release record and SKILLS_MANIFEST.md)
- Distribution name: `homemade-skill-lifecycle`; directory: `homemade-skill-lifecycle`; distribution version: `2.0.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [homemade-skill-lifecycle v2.0.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/homemade-skill-lifecycle-v2.0.0) (2026-10-04).

## Preservation and changes

All 13 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, seven references and four scripts. Tests stay in the upstream repository. LICENSE and this source record are distribution additions. The former `codex-skill-lifecycle` directory was removed in the same commit; CC Switch does not migrate installations, so install `homemade-skill-lifecycle` and remove the old installation.

## Validation and update boundary

Upstream: the lifecycle behavior suite (9 tests) and the repository validator passed in the upstream CI on the release commit and locally. This distribution copy was checked by blob comparison and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
