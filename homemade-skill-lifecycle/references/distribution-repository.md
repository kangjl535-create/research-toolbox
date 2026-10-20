# Curated Distribution Repository

## When It Applies

CCSwitch reads the repository and branch configured in its skills repository manager, which may differ from the development repository where releases are built and tested. In the current workflow, homemade skills are released in `https://github.com/kangjl535-create/custom-agent-skills` and CCSwitch installs them from the curated distribution repository `https://github.com/kangjl535-create/research-toolbox`, branch `cc-switch-compat`. That branch is a temporary copy of `main` without `ppt-master`, whose file count exceeds CCSwitch's current skill-file limit; retire it only when the user confirms CCSwitch can sync `main`. Tags and Releases are recorded on `main` only. Update `main` first, then apply the same skill commit to `cc-switch-compat`, for example by cherry-picking it, and confirm the two branches have the same skill tree and that `ppt-master` is still excluded. A release that stops at the development repository or at `main` is invisible to CCSwitch update checks.

Confirm the distribution repository from project instructions, the distribution repository README, or the installed skill's `UPSTREAM_SOURCE.md`. Do not open or edit the CCSwitch database to find it. If a skill is not yet distributed there, adding it is a curation decision; ask the user first.

## Update After The Upstream Release

Start only after the upstream commit passed CI and its tag and Release exist.

1. Use a separate device-local checkout of the distribution repository. A full checkout of a large distribution repository can fail on Windows path-length limits: clone with `--no-checkout` into a short temporary path and use a cone-mode sparse checkout of the skill directories involved. Confirm that the distributed skill matches the upstream commit recorded in its `UPSTREAM_SOURCE.md`, and inspect the repository's own conventions: README, recent commits, tags, and Releases.
2. Keep the work tree clean on the intended branch. In a partial clone (`--filter=blob:none`), `git checkout` downloads blobs and can stop halfway on a network error, leaving files deleted or modified. Switch branches only from a clean work tree. After every switch, and before cherry-picking, staging or committing, require an empty `git status --porcelain` and the intended branch from `git branch --show-current`. If the check fails, rerun `git checkout -f <branch>` once the network is back, or discard the temporary clone and clone again.
3. On the distribution default branch, run `scripts\Update-DistributedSkill.ps1 -DistributionPath <distribution-checkout>\<skill> -Branch <default-branch> -UpstreamPath <upstream-checkout>\<category>\<skill> -Tag <skill>-vX.Y.Z -ReleaseDate <YYYY-MM-DD>`. The script:
   - refuses a dirty work tree or another branch;
   - exports the skill tree of the tag's commit with line-ending conversion disabled;
   - copies it byte-for-byte over the distributed runtime files and removes files deleted upstream;
   - keeps the distribution additions `LICENSE`, `UPSTREAM_SOURCE.md` and `KNOWN_ISSUES.md`;
   - verifies every file against the upstream Git blob IDs;
   - updates the release-specific fields of `UPSTREAM_SOURCE.md`: selected reference, fixed commit, skill directory Git tree, source URL, query and acquisition timestamps, declared and distribution version, latest stable release link and date, and file count.

   If a field is not found exactly once, the script stops before writing anything. Review the free text of `UPSTREAM_SOURCE.md` yourself, such as file lists and test counts.
4. Run `quick_validate.py` and confirm the staged diff touches only that skill. Commit, run the script again with `-Verify` (same paths, branch and tag) to check the committed files against the upstream blob IDs, and push. When the CCSwitch branch differs, switch to it as in step 2, cherry-pick the commit, and run `-Verify -Branch <ccswitch-branch>`. Both runs must report the same `skillTree`. Then push.
5. Record the update immutably using the distribution repository's convention. For `research-toolbox`, create an annotated incremental batch tag `retained-skills-vX.Y.Z` (PATCH for updated skills, MINOR for added skills) and a matching Release with the single-skill ZIP and `SHA256SUMS.txt`, stating which skills changed. Build both on the default branch with `Update-DistributedSkill.ps1 -DistributionPath <distribution-checkout>\<skill> -Branch <default-branch> -Package -OutputDirectory <empty-directory>`. It builds `<skill>-<version>.zip` from the committed tree, distribution additions included, and appends `<sha256> *<zip>` to `SHA256SUMS.txt`; call it once per skill in a batch. The repository has no CI; do not describe local checks as CI.
6. Verify that both branches serve the new files, the tag target, and the Release asset digest. GitHub is the only copy of the distribution repository; do not maintain synchronized local mirrors of it.

## Renamed Skills

A rename is a removal plus an addition: in one commit per branch, delete the old directory, add the new one with the distribution additions, record the former name in `UPSTREAM_SOURCE.md`, and update the README entry. Use a MINOR batch tag and state the removal in its Release. CCSwitch does not migrate installations: the user installs the new name and removes the old installation.

## Handoff

Report both repositories: the upstream release (commit, tag, Release, ZIP digest, CI) and the distribution update (repository URL, CCSwitch branch, commits on each branch, tag, Release, ZIP digest). Tell the user to check updates on the distribution repository in CCSwitch. Distribution publication, like upstream publication, does not authorize CCSwitch application control.
