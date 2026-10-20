# Upstream source and distribution

- Maintained source repository: https://github.com/kangjl535-create/custom-agent-skills
- Original skill name: `homemade-skill-lifecycle` (formerly `codex-skill-lifecycle`, distributed here under that name until retained-skills v1.1.1)
- Upstream path: `skill-development-tools/homemade-skill-lifecycle`
- Selected reference: tag `homemade-skill-lifecycle-v2.1.0`
- Fixed commit: `36d425896d60d12fe6925cf83bf708623a1627bb`
- Skill directory Git tree: `5ada8e29e9a428fbe9ed5e61bbcaba0403906dae`
- Source: https://github.com/kangjl535-create/custom-agent-skills/tree/36d425896d60d12fe6925cf83bf708623a1627bb/skill-development-tools/homemade-skill-lifecycle
- Source-query timestamp: `2026-10-20T03:20:52+00:00`
- Acquisition timestamp: `2026-10-20T03:20:52+00:00`
- Upstream declared skill version: `2.1.0` (release record and SKILLS_MANIFEST.md)
- Distribution name: `homemade-skill-lifecycle`; directory: `homemade-skill-lifecycle`; distribution version: `2.1.0`
- License: MIT. See [LICENSE](LICENSE).

Latest stable upstream release: [homemade-skill-lifecycle v2.1.0](https://github.com/kangjl535-create/custom-agent-skills/releases/tag/homemade-skill-lifecycle-v2.1.0) (2026-10-20).

## Preservation and changes

All 14 upstream skill files are retained byte-for-byte (verified against the upstream Git blob IDs): SKILL.md, agents/openai.yaml, seven references and five scripts. Tests stay in the upstream repository. LICENSE and this source record are distribution additions. The former `codex-skill-lifecycle` directory was removed when 2.0.0 was adopted (retained-skills v1.1.1). CC Switch does not migrate installations, so install `homemade-skill-lifecycle` and remove the old installation.

## Validation and update boundary

Upstream: the lifecycle behavior suite (19 tests) and the repository validator passed in the upstream CI on the release commit and locally. This distribution copy was checked by blob comparison (`Update-DistributedSkill.ps1`) and quick_validate.py only. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

Compare the selected upstream skill tree with a future release before adopting changes. No automatic update or CC Switch migration is performed.
