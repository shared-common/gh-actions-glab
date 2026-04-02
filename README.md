# gh-actions-glab

GitHub Actions codebase for syncing public or same-instance GitLab repositories
into a private GitLab.com top-level group using Bitwarden Secrets Manager.

## What this repository does

This repository owns the workflow logic directly. It does not wrap
`gh-actions-shared` because the source-of-truth model here is GitLab-to-GitLab,
not GitHub-fork-to-GitLab.

It provides:

- `external-sync.yml`: runs at `0 * * * *` and inspects `GL_FORKS_EXT_JSON`
- `internal-sync.yml`: runs at `30 * * * *` and inspects `GL_FORKS_INT_JSON`
- `reconcile-target.yml`: reusable workflow that creates or repairs one GitLab
  project at a time

The scheduled workflows only fan out to `reconcile-target.yml` when a target
project is missing, when managed branches are missing, when the tracked mirror
branches drift from the source default branch, or when protected branch settings
need repair.

Workflow job names and rendered step summaries use redacted stable target ids
instead of the actual target project path or target URL.

## Managed branches

The branch names come from Bitwarden secrets:

- `GIT_BRANCH_PREFIX`
- `GIT_BRANCH_MAIN`
- `GIT_BRANCH_STAGING`
- `GIT_BRANCH_SNAPSHOT`

Managed branches are:

- `gitlab/<prefix>/<main>`: tracked, force-syncable, protected
- `gitlab/<prefix>/<staging>`: tracked, force-syncable, protected
- `<prefix>/<snapshot>`: create once from the initial source default branch,
  never updated, never protected

If the snapshot branch is later protected by hand, reconciliation removes that
protection to restore the declared state.

`gitlab/<prefix>/<main>` is also enforced as the GitLab project default branch.

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
- `GIT_BRANCH_SNAPSHOT`

External mode:

- `GL_PAT_FORK_SEEDBED_SVC`
- `GL_BRIDGE_FORK_USER_SEEDBED`
- `GL_GROUP_TOP_UPSTREAM`
- `GL_GROUP_SUB_MAINLINE`
- `GL_FORKS_EXT_JSON`

Internal mode:

- `GL_PAT_FORK_GLAB_SVC`
- `GL_BRIDGE_FORK_USER_GLAB`
- `GL_FORKS_INT_JSON`

## Target mapping formats

External mode expects a JSON object whose keys are the target project names and
whose values are the full source GitLab URLs:

```json
{
  "keepsecret": "https://invent.kde.org/utilities/keepsecret",
  "switcherooctl": "https://gitlab.freedesktop.org/hadess/switcheroo-control"
}
```

The source URLs may omit `.git`; the workflow normalizes them to Git remote
URLs before inspection and sync.

Projects are created or repaired at:

`GL_GROUP_TOP_UPSTREAM/GL_GROUP_SUB_MAINLINE/<project-name>`

Internal mode expects a JSON object whose keys are the full target project paths
and whose values are the source project paths on `GL_BASE_URL`:

```json
{
  "top/sub1/sub2/project-name": "top/sub1/project-name",
  "top/sub1/project-name": "top/project"
}
```

`GL_FORKS_EXT_JSON` and `GL_FORKS_INT_JSON` must be non-empty JSON objects.
Blank values and empty objects are treated as configuration errors.

## Security model

- Bitwarden secrets are written to files under the runner temp directory
- Every Bitwarden-fetched secret value is masked with `::add-mask::` before
  later steps run
- PATs are never echoed back into logs
- Git and API calls use bounded retries and explicit timeouts
- Project and branch names are validated before use
- Workflow permissions default to `{}` and are narrowed per job
- Branch protection is repaired only for the managed tracked mirror branches

## Local validation

```bash
python3 -m unittest discover -s tests
python3 -m compileall -q .github/scripts tests
```
