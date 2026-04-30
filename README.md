# gh-actions-glab

GitHub Actions codebase for syncing public or same-instance GitLab repositories
into private GitLab targets. Runtime credentials and branch names still come
from Bitwarden Secrets Manager, but the fork inventory now comes from a checked
out public config repository.

## What this repository does

This repository owns the workflow logic directly. It does not wrap
`gh-actions-shared` because the source-of-truth model here is GitLab-to-GitLab,
not GitHub-fork-to-GitLab.

It provides:

- `external-sync.yml`: runs at `0 * * * *` and inspects
  `shared-common/gh-actions-cfg@main:gh-actions-glab/gl_forks_ext.json`
- `internal-sync.yml`: runs at `30 * * * *` and inspects
  `shared-common/gh-actions-cfg@main:gh-actions-glab/gl_forks_int.json`
- `reconcile-target.yml`: reusable workflow that checks out both this repo and
  `shared-common/gh-actions-cfg`, then plans and reconciles one sync mode on a
  single runner

The scheduled workflows call `reconcile-target.yml` once per mode. The reusable
workflow plans first, writes a local redacted reconcile queue, and only runs the
reconcile phase when one or more targets are missing, when managed branches or
tags are missing, when tracked refs drift from their declared sources, or
when protected branch or tag settings need repair.

Workflow job names and rendered step summaries use redacted stable target ids
instead of the actual target project path or target URL.

## Managed branches and tags

The branch names come from Bitwarden secrets:

- `GIT_BRANCH_PREFIX`
- `GIT_BRANCH_MAIN`
- `GIT_BRANCH_STAGING`
- `GIT_BRANCH_RELEASE`
- `GIT_BRANCH_REV`

Managed branches are:

- `gitlab/<prefix>/<main>`: tracked from the source default branch,
  force-syncable, protected, and enforced as the GitLab project default branch
- `gitlab/<prefix>/<staging>`: tracked, force-syncable, protected
- `gitlab/<prefix>/<release>`: tracked, force-syncable, protected
- `gitlab/<prefix>/<rev>`: optional per-target tracked branch created from a
  target entry's `branch_rev` source branch, always protected, always updated
- `gitlab/<prefix>/<branch-name>`: optional per-target branch from the
  `branches` array; these always use the source branch name from the target
  entry and always add the `gitlab/<prefix>/` target prefix
- `<tag-name>`: optional per-target tag from the `tags` array; tags keep their
  original names and are not prefixed

## Required GitHub repository variables

- `BWS_VERSION`
- `BWS_SHA256`

## Required GitHub repository secrets

- `BWS_PROJECT_ID`
- `BWS_ACCESS_TOKEN`

## Required Bitwarden secrets

Common:

- `GL_BASE_URL`
- `GIT_BRANCH_PREFIX`
- `GIT_BRANCH_MAIN`
- `GIT_BRANCH_STAGING`
- `GIT_BRANCH_RELEASE`
- `GIT_BRANCH_REV`

External mode:

- `GL_PAT_FORK_GLAB_SVC`
- `GL_BRIDGE_FORK_USER_GLAB`

## Shared config checkout

`reconcile-target.yml` checks out the public repository
`shared-common/gh-actions-cfg` at ref `main` into `.sync-config/`.

The workflow reads:

- `.sync-config/gh-actions-glab/gl_forks_ext.json` for external mode
- `.sync-config/gh-actions-glab/gl_forks_int.json` for internal mode

## Target mapping formats

Both config files use the same top-level structure:

```json
{
  "version": 1,
  "targets": [
    {
      "target_project_path": "ghgl-forks/mainline/keepsecret",
      "source_url": "https://invent.kde.org/utilities/keepsecret",
      "git_lfs": true,
      "git_timeout_seconds": 900,
      "branch_rev": "",
      "branches": [],
      "tags": []
    }
  ]
}
```

External entries use `source_url` and may omit `.git`; the workflow normalizes
them to Git remote URLs before inspection and sync.

When a target in either `gl_forks_ext.json` or `gl_forks_int.json` sets
`target_mirror_path`, the follow-up mirror configuration workflow creates the
target mirror project if needed, ensures the push mirror exists on the source
`target_project_path`, and force-triggers a push mirror sync with
`POST /projects/:id/remote_mirrors/:mirror_id/sync` when the mirror target
project or remote mirror configuration was newly created.

Internal entries use `source_project_path` and resolve them against
`GL_BASE_URL`.

When an internal target project does not exist yet, the workflow first creates
an empty private project with `shared_runners_enabled` forced to `false` and
then reconciles only the declared managed refs from the config.

If a target sets `source_import: true`, the workflow seeds that target with a
full-project `import_url` import before it reconciles the managed refs. Those
opt-in import targets do not prune unmanaged imported refs.

```json
{
  "version": 1,
  "targets": [
      {
        "target_project_path": "glab-forks/system/yodl",
        "target_mirror_path": "workyard/glab-forks/system/yodl",
        "source_project_path": "fbb-git/yodl",
        "source_import": false,
      "git_lfs": false,
      "git_timeout_seconds": 600,
      "branch_rev": "",
      "branches": [],
      "tags": []
    }
  ]
}
```

Every target entry supports:

- `target_project_path`: full target project path on `GL_BASE_URL`
- `source_url` or `source_project_path`: source project location for that mode
- `target_mirror_path`: optional mirror project path used by the follow-up
  target-mirror workflow
- `source_import`: optional boolean; when `true`, seed the target with a
  full-project import before managed-ref reconciliation
- `git_lfs`: optional boolean override; when omitted the workflow inspects the
  fetched source refs and enables Git LFS only when the target declares LFS
  usage in `.gitattributes` or `.lfsconfig`
- `git_timeout_seconds`: optional integer override for long-running fetch and
  push operations; defaults to `300` and must be between `60` and `7200`
- `branch_rev`: optional source branch name that syncs into
  `gitlab/<prefix>/<rev>`
- `branches`: optional array of objects with `name`, `protected`, and
  `upstream`
- `tags`: optional array of objects with `name`, `protected`, and `upstream`

For `branches`:

- `name` is the source branch name
- the target branch is always `gitlab/<prefix>/<name>`
- `upstream: true` means an existing target branch is force-updated from the
  source branch
- `upstream: false` means the target branch is created once if missing and then
  only its presence and protection state are enforced

For `tags`:

- `name` is both the source tag name and the target tag name
- tags are never prefixed
- `upstream: true` means an existing target tag is force-updated from the
  source tag
- `upstream: false` means the target tag is created once if missing and then
  only its presence and protection state are enforced

Both `gl_forks_ext.json` and `gl_forks_int.json` must be valid versioned JSON
documents with a non-empty `targets` array.

## Security model

- Bitwarden secrets are written to files under the runner temp directory
- Every Bitwarden-fetched secret value is masked with `::add-mask::` before
  later steps run
- The fork inventory is public config checked out from
  `shared-common/gh-actions-cfg`, not a masked Bitwarden secret blob
- PATs are never echoed back into logs
- Git and API calls use bounded retries and explicit timeouts
- Project, branch, and tag names are validated before use
- Workflow permissions default to `{}` and are narrowed per job
- Branch and tag protection are repaired only for refs declared by the target
  inventory

## Local validation

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q .github/scripts tests
```
