# Upstream source and distribution

- Original repository: https://github.com/K-Dense-AI/scientific-agent-skills
- Original skill name: `peer-review`
- Upstream path: `skills/peer-review`
- Selected reference: `main`
- Fixed commit: `330c8e764435a731eff571e3efdda70b363d0792`
- Skill directory Git tree: `5521fbe04d1868847f76765c08edfc9d7632f7f7`
- Source: https://github.com/K-Dense-AI/scientific-agent-skills/tree/330c8e764435a731eff571e3efdda70b363d0792/skills/peer-review
- Source query (or original acquisition for retained snapshots): `2026-09-21T04:23:41.048943+00:00`
- Acquired into this distribution from the verified local snapshot: `2026-09-21T11:49:46.619987+00:00`
- Upstream declared skill version: `2.2`
- Distribution name: `peer-review`; directory: `peer-review`; distribution version: `2.2.0`
- License: MIT; retain all bundled third-party notices. See [LICENSE.md](LICENSE.md) and all component notices.

Previously adopted upstream snapshot retained. This operation restores the original name; it does not update the upstream content.

Historical distribution: `peer-review-curated`. Existing `peer-review-curated-v2.2.0` tags/releases remain immutable. Current installations are not migrated by this repository change.

## Preservation and changes

All 24 upstream skill files are retained, including scripts, references, assets, templates, tests, attribution, and output capabilities. Original package directory names are preserved, including `nature-proposal-writer` (invocation name `researchwrite`), so sibling references retain their original layout.

SKILL.md: restore original frontmatter name; all other upstream bytes retained.
Repository license notices and this source record are distribution additions. KNOWN_ISSUES.md, when present, records observations only; it is not evidence of repair or comprehensive validation. Existing known-issue records are retained unchanged.

## Validation and update boundary

Acquired archive files were checked against Git blob identities at the fixed commit. Distribution scope, names, source records, licenses and archive contents are checked locally. No model workflow, scientific task, external service, dependency installation or host installation was executed. The repository has no CI validation workflow; local checks are not CI or scientific acceptance.

System quick_validate.py: same rejection as upstream: Unexpected key(s) in SKILL.md frontmatter: compatibility. Allowed properties are: allowed-tools, description, license, metadata, name. Unchanged upstream fields are preserved; a strict creator-schema rejection is not presented as successful host loading.

Compare the selected upstream skill tree and its dependencies with a future release before adopting changes. A repository-wide release number is not the skill's own version. No automatic update or CC Switch migration is performed. Repository Git history and immutable release assets preserve this distribution.
