# GitHub Publication

## Preconditions

- The user requested publication, not only a plan or local implementation.
- `git` and GitHub CLI are available, and `gh auth status` succeeds for the intended account.
- Plain `git` authenticates as that same account (`git push --dry-run` to the remote succeeds) and `git config user.name` and `user.email` are set, so commits are attributable. Another account stored in the Git credential manager makes a private repository answer "Repository not found". Device credentials and global Git settings are the user's to change (for example `gh auth setup-git`); do not store tokens or rewrite them yourself.
- The device-local checkout points to the intended repository and branch.
- Before anything is copied, the synchronized repository tree (for example `%OneDrive%\AI-Config\Skills\custom-agent-skills`) and the checkout differ only in the files this release changes. Check with `Compare-InstalledSkill.ps1 -SourcePath <synchronized repository> -InstalledPath <checkout> -AllowedExtraFile @()`, which skips `.git`, reads CRLF as LF, and lists every difference. Any other difference means an earlier release left records behind or something was edited in only one place. Resolve it first.
- The authoritative source, checkout copy, manifest, release record, and ZIP version agree.
- Behavior tests, skill validation, release validation, repository validation, and `git diff --check` pass.
- The staged diff contains only the reviewed release files and contains no credentials or local state.

## Publish

1. Copy reviewed runtime files and public tests from the authoritative source into the device-local checkout.
2. Update the repository manifest, release record, and README in the synchronized source, only where the release changes them, and copy them into the checkout too. The synchronized tree is authoritative for repository records as well as skill files.
3. Stage the skill and build the ZIP from the staged tree: `Build-HomemadeSkillRelease.ps1 -SkillPath <checkout-skill> -GitRevision (git -C <checkout> write-tree) ...`. Write its SHA-256 into the records, in the synchronized source first and then the checkout, and stage them.
4. Run local validation and inspect `git status`, the exact diff, and staged file list.
5. Commit. Confirm that the ZIP equals the commit with `Test-HomemadeSkillRelease.ps1 -ZipPath <zip> -SourcePath <checkout-skill> -GitRevision HEAD`, then push the configured default/update branch.
6. Require the validation workflow for that commit to pass before tagging.
7. Create and push the immutable annotated tag `<skill-name>-vX.Y.Z`.
8. Create the matching GitHub Release, attach the already validated ZIP, and include material changes and SHA-256.
9. Verify repository visibility, default branch, tag target, Release asset, and digest.
10. Run the tree comparison from the preconditions again; it must report no difference.

Do not store `gh` credentials in project files. Use device-local authentication. Do not force-push shared release history.

## Completion Boundary

If CCSwitch uses a separate curated distribution repository, update it first as described in `distribution-repository.md`; the upstream release alone is not visible to CCSwitch. Successful publication to the repository CCSwitch uses is the default stopping boundary. Report the exact CCSwitch handoff fields defined in `ccswitch.md` and wait for the user. GitHub publication alone does not grant permission to open CCSwitch, remove an existing installation, or run an update.

Records written after the release commit, such as the distribution commits or the CCSwitch result, follow the same path. Write them in the synchronized source, copy them to the checkout, commit and push, and run the tree comparison again. The release is not complete while the two trees differ.
