from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _common import (
    GitLabClient,
    delete_gitlab_protected_branch,
    ensure_gitlab_default_branch,
    ensure_gitlab_project,
    ensure_gitlab_protected_branch,
    git_askpass_env,
    get_gitlab_protected_branch,
    get_gitlab_branch_sha,
    get_gitlab_project,
    normalize_gitlab_project_url,
    protected_branch_allows_sync,
    require_secret,
    run_command,
    sanitize,
    validate_project_path,
    validate_project_segment,
    git_source_head,
    load_json_mapping,
)
from branch_policy import BranchPolicy


@dataclass(frozen=True)
class TargetSpec:
    mode: str
    target_project_path: str
    source: str
    repo_name: str

    def to_payload(self) -> dict[str, str]:
        return {
            "mode": self.mode,
            "target_project_path": self.target_project_path,
            "source": self.source,
            "repo_name": self.repo_name,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TargetSpec":
        mode = str(payload.get("mode") or "").strip()
        target_project_path = str(payload.get("target_project_path") or "").strip()
        source = str(payload.get("source") or "").strip()
        repo_name = str(payload.get("repo_name") or "").strip()
        if mode not in {"external", "internal"}:
            raise SystemExit(f"Unsupported sync mode: {mode}")
        validate_project_path(target_project_path, "target_project_path")
        validate_project_segment(repo_name, "repo_name")
        if mode == "external":
            normalized_source = normalize_gitlab_project_url(source, "external source url")
        else:
            validate_project_path(source, "internal source path")
            if source == target_project_path:
                raise SystemExit("internal source path must differ from target_project_path")
            normalized_source = source
        expected_repo_name = target_project_path.rsplit("/", 1)[-1]
        if repo_name != expected_repo_name:
            raise SystemExit("repo_name must match the final segment of target_project_path")
        return cls(
            mode=mode,
            target_project_path=target_project_path,
            source=normalized_source,
            repo_name=repo_name,
        )

    @property
    def target_id(self) -> str:
        digest = hashlib.sha256(self.target_project_path.encode("utf-8")).hexdigest()
        return f"target-{digest[:12]}"

    @property
    def source_display(self) -> str:
        return self.source


def redact_target_context(message: str, target: TargetSpec, client: GitLabClient | None = None) -> str:
    redacted = message
    candidates = {
        target.target_project_path,
        target.target_project_path.rsplit("/", 1)[0],
        target.source,
    }
    if "/" in target.source:
        candidates.add(target.source.rsplit("/", 1)[0])
    if target.mode == "external" and target.source.endswith(".git"):
        candidates.add(target.source[:-4])
    if client is not None:
        candidates.update(
            {
                client.project_git_url(target.target_project_path),
                client.project_web_url(target.target_project_path),
            }
        )
        if target.mode == "internal":
            candidates.update(
                {
                    client.project_git_url(target.source),
                    client.project_web_url(target.source),
                }
            )
    for value in sorted((item for item in candidates if item), key=len, reverse=True):
        redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def load_gitlab_client(mode: str) -> GitLabClient:
    if mode == "external":
        username_secret = "GL_BRIDGE_FORK_USER_SEEDBED"
        token_secret = "GL_PAT_FORK_SEEDBED_SVC"
    elif mode == "internal":
        username_secret = "GL_BRIDGE_FORK_USER_GLAB"
        token_secret = "GL_PAT_FORK_GLAB_SVC"
    else:
        raise SystemExit(f"Unsupported sync mode: {mode}")
    return GitLabClient(
        base_url=require_secret("GL_BASE_URL"),
        username=require_secret(username_secret),
        token=require_secret(token_secret),
    )


def load_targets(mode: str) -> list[TargetSpec]:
    if mode == "external":
        mapping = load_json_mapping(require_secret("GL_FORKS_EXT_JSON"), "GL_FORKS_EXT_JSON")
        if not mapping:
            raise SystemExit("GL_FORKS_EXT_JSON must contain at least one target mapping")
        group_top = require_secret("GL_GROUP_TOP_UPSTREAM")
        group_sub = require_secret("GL_GROUP_SUB_MAINLINE")
        target_group_path = f"{group_top}/{group_sub}"
        validate_project_path(target_group_path, "external target group path")
        targets: list[TargetSpec] = []
        for repo_name, source_url in sorted(mapping.items()):
            validate_project_segment(repo_name, "external repo_name")
            source_git_url = normalize_gitlab_project_url(source_url, "external source url")
            targets.append(
                TargetSpec(
                    mode="external",
                    target_project_path=f"{target_group_path}/{repo_name}",
                    source=source_git_url,
                    repo_name=repo_name,
                )
            )
        return targets

    if mode == "internal":
        mapping = load_json_mapping(require_secret("GL_FORKS_INT_JSON"), "GL_FORKS_INT_JSON")
        if not mapping:
            raise SystemExit("GL_FORKS_INT_JSON must contain at least one target mapping")
        targets = []
        for target_path, source_path in sorted(mapping.items()):
            validate_project_path(target_path, "internal target path")
            validate_project_path(source_path, "internal source path")
            repo_name = target_path.rsplit("/", 1)[-1]
            targets.append(
                TargetSpec(
                    mode="internal",
                    target_project_path=target_path,
                    source=source_path,
                    repo_name=repo_name,
                )
            )
        return targets

    raise SystemExit(f"Unsupported sync mode: {mode}")


def build_source_git_url(target: TargetSpec, client: GitLabClient) -> str:
    if target.mode == "external":
        return target.source
    return client.project_git_url(target.source)


def inspect_target(target: TargetSpec, policy: BranchPolicy, client: GitLabClient) -> dict[str, Any]:
    source_url = build_source_git_url(target, client)
    with git_askpass_env(client) as git_env:
        source_default_branch, source_sha = git_source_head(
            source_url,
            secrets=(client.token, client.username),
            env_overrides=git_env if target.mode == "internal" else None,
        )

    reasons: list[str] = []
    branch_state: dict[str, dict[str, Any]] = {}
    project = get_gitlab_project(client, target.target_project_path)
    project_id = int(project["id"]) if isinstance(project, dict) and project.get("id") else None

    if project is None:
        reasons.append("project_missing")
    else:
        for branch in policy.mirrors:
            current_sha = get_gitlab_branch_sha(client, project_id, branch.target_name)
            branch_reasons: list[str] = []
            if current_sha is None:
                branch_reasons.append("missing")
                reasons.append(f"branch_missing:{branch.target_name}")
            elif current_sha != source_sha:
                branch_reasons.append("sha_diverged")
                reasons.append(f"sha_diverged:{branch.target_name}")
            if branch.protected:
                protected = get_gitlab_protected_branch(client, project_id, branch.target_name)
                if not protected_branch_allows_sync(protected):
                    branch_reasons.append("protection_missing")
                    reasons.append(f"protection_missing:{branch.target_name}")
            branch_state[branch.target_name] = {
                "sha": current_sha,
                "reasons": branch_reasons,
            }

        snapshot_sha = get_gitlab_branch_sha(client, project_id, policy.snapshot.target_name)
        snapshot_protected = get_gitlab_protected_branch(client, project_id, policy.snapshot.target_name)
        if snapshot_sha is None:
            reasons.append(f"branch_missing:{policy.snapshot.target_name}")
        if snapshot_protected is not None:
            reasons.append(f"protection_present:{policy.snapshot.target_name}")
        branch_state[policy.snapshot.target_name] = {
            "sha": snapshot_sha,
            "reasons": (
                (["missing"] if snapshot_sha is None else [])
                + (["protection_present"] if snapshot_protected is not None else [])
            ),
        }

        if str(project.get("default_branch") or "") != policy.default_branch:
            reasons.append(f"default_branch_mismatch:{policy.default_branch}")

    return {
        "mode": target.mode,
        "target_id": target.target_id,
        "repo_name": target.repo_name,
        "target_project_path": target.target_project_path,
        "source": target.source_display,
        "source_default_branch": source_default_branch,
        "source_sha": source_sha,
        "target_exists": project is not None,
        "project_id": project_id,
        "needs_reconcile": bool(reasons),
        "reasons": reasons,
        "branches": branch_state,
    }


def _push_branch(
    repo_path: str,
    source_url: str,
    target_url: str,
    source_branch: str,
    target_branch: str,
    *,
    source_remote: str,
    target_remote: str,
    expected_remote_sha: str | None,
    allow_existing: bool = False,
    secrets: tuple[str, ...] = (),
    env_overrides: dict[str, str] | None = None,
) -> str:
    import subprocess

    def run_push(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        command_text = sanitize(" ".join(command), secrets)
        try:
            return subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise SystemExit(f"Command timed out after 300s: {command_text}") from exc

    run_command(
        ["git", "-C", repo_path, "lfs", "fetch", source_remote, f"refs/heads/{source_branch}"],
        secrets=secrets,
        timeout=300,
        env_overrides=env_overrides,
    )
    run_command(
        ["git", "-C", repo_path, "lfs", "push", target_remote, f"refs/heads/{source_branch}"],
        secrets=secrets,
        timeout=300,
        env_overrides=env_overrides,
    )

    command = [
        "git",
        "-C",
        repo_path,
        "push",
        target_url,
        f"refs/heads/{source_branch}:refs/heads/{target_branch}",
    ]
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if env_overrides:
        env.update(env_overrides)
    push_proc = run_push(command, env)
    if push_proc.returncode == 0:
        return "updated"

    stderr_text = sanitize(push_proc.stderr.strip(), secrets)
    stderr = stderr_text.lower()
    if allow_existing and "already exists" in stderr:
        return "skipped"
    if any(pattern in stderr for pattern in ("non-fast-forward", "[rejected]", "fetch first", "stale info")):
        lease = f"refs/heads/{target_branch}"
        if expected_remote_sha:
            lease = f"{lease}:{expected_remote_sha.lower()}"
        force_command = [
            "git",
            "-C",
            repo_path,
            "push",
            f"--force-with-lease={lease}",
            target_url,
            f"refs/heads/{source_branch}:refs/heads/{target_branch}",
        ]
        force_proc = run_push(force_command, env)
        if force_proc.returncode == 0:
            return "updated"
        raise SystemExit(sanitize(force_proc.stderr.strip(), secrets))

    raise SystemExit(stderr_text)


def reconcile_target(target: TargetSpec, policy: BranchPolicy, client: GitLabClient) -> dict[str, Any]:
    source_url = build_source_git_url(target, client)
    with git_askpass_env(client) as git_env:
        source_default_branch, source_sha = git_source_head(
            source_url,
            secrets=(client.token, client.username),
            env_overrides=git_env if target.mode == "internal" else None,
        )

        project, created = ensure_gitlab_project(client, target.target_project_path)
        project_id = int(project["id"])
        target_url = client.project_git_url(target.target_project_path)
        secrets = (client.token, client.username)

        results: dict[str, list[str]] = {
            "created": [],
            "updated": [],
            "skipped": [],
            "protected": [],
            "unprotected": [],
        }

        if created:
            results["created"].append(f"project:{target.target_project_path}")

        with tempfile.TemporaryDirectory() as repo_dir:
            repo_path = str(Path(repo_dir) / "repo.git")
            run_command(["git", "init", "--bare", repo_path], secrets=secrets, timeout=120, env_overrides=git_env)
            run_command(
                ["git", "-C", repo_path, "remote", "add", "source", source_url],
                secrets=secrets,
                timeout=120,
                env_overrides=git_env,
            )
            run_command(
                ["git", "-C", repo_path, "remote", "add", "target", target_url],
                secrets=secrets,
                timeout=120,
                env_overrides=git_env,
            )
            run_command(
                ["git", "-C", repo_path, "lfs", "install", "--local"],
                secrets=secrets,
                timeout=120,
                env_overrides=git_env,
            )
            run_command(
                [
                    "git",
                    "-C",
                    repo_path,
                    "fetch",
                    source_url,
                    f"refs/heads/{source_default_branch}:refs/heads/{source_default_branch}",
                ],
                secrets=secrets,
                timeout=300,
                env_overrides=git_env if target.mode == "internal" else None,
            )

            for branch in policy.mirrors:
                existing_sha = get_gitlab_branch_sha(client, project_id, branch.target_name)
                if existing_sha == source_sha:
                    results["skipped"].append(branch.target_name)
                else:
                    outcome = _push_branch(
                        repo_path,
                        source_url,
                        target_url,
                        source_default_branch,
                        branch.target_name,
                        source_remote="source",
                        target_remote="target",
                        expected_remote_sha=existing_sha,
                        secrets=secrets,
                        env_overrides=git_env,
                    )
                    bucket = "created" if existing_sha is None else "updated"
                    if outcome == "skipped":
                        bucket = "skipped"
                    results[bucket].append(branch.target_name)
                if branch.protected and ensure_gitlab_protected_branch(client, project_id, branch.target_name):
                    results["protected"].append(branch.target_name)

            snapshot_sha = get_gitlab_branch_sha(client, project_id, policy.snapshot.target_name)
            if snapshot_sha is None:
                _push_branch(
                    repo_path,
                    source_url,
                    target_url,
                    source_default_branch,
                    policy.snapshot.target_name,
                    source_remote="source",
                    target_remote="target",
                    expected_remote_sha=None,
                    allow_existing=True,
                    secrets=secrets,
                    env_overrides=git_env,
                )
                results["created"].append(policy.snapshot.target_name)
            else:
                results["skipped"].append(policy.snapshot.target_name)
            if delete_gitlab_protected_branch(client, project_id, policy.snapshot.target_name):
                results["unprotected"].append(policy.snapshot.target_name)

        default_branch_changed = ensure_gitlab_default_branch(client, project_id, policy.default_branch)
        if default_branch_changed:
            results["updated"].append(f"default_branch:{policy.default_branch}")

        return {
            "mode": target.mode,
            "target_id": target.target_id,
            "repo_name": target.repo_name,
            "target_project_path": target.target_project_path,
            "source": target.source_display,
            "source_default_branch": source_default_branch,
            "source_sha": source_sha,
            "results": results,
        }


def write_json(path: str, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def render_plan_summary(mode: str, inspected: list[dict[str, Any]], errors: list[dict[str, str]]) -> str:
    title = "External" if mode == "external" else "Internal"
    actionable = [item for item in inspected if item.get("needs_reconcile")]
    clean = len(inspected) - len(actionable)
    lines = [
        f"## {title} sync plan",
        "",
        f"- inspected: {len(inspected)}",
        f"- actionable: {len(actionable)}",
        f"- clean: {clean}",
        f"- errors: {len(errors)}",
        "",
    ]
    if actionable:
        lines.append("### Targets queued for reconcile")
        lines.append("")
        for item in actionable:
            reasons = ", ".join(item.get("reasons", []))
            lines.append(f"- `{item['target_id']}`: {reasons}")
        lines.append("")
    if errors:
        lines.append("### Inspection errors")
        lines.append("")
        for item in errors:
            lines.append(f"- `{item['target_id']}`: {item['error']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_reconcile_summary(payload: dict[str, Any]) -> str:
    results = payload.get("results", {})
    created = results.get("created", [])
    updated = results.get("updated", [])
    skipped = results.get("skipped", [])
    protected = results.get("protected", [])
    unprotected = results.get("unprotected", [])
    lines = [
        f"## Reconciled `{payload['target_id']}`",
        "",
        f"- mode: `{payload['mode']}`",
        f"- source default branch: `{payload['source_default_branch']}`",
        f"- source sha: `{payload['source_sha']}`",
        "",
        f"- created: {len(created)}",
        f"- updated: {len(updated)}",
        f"- skipped: {len(skipped)}",
        f"- protected repaired: {len(protected)}",
        f"- snapshot unprotected: {len(unprotected)}",
        "",
    ]
    for label, values in (
        ("Created", created),
        ("Updated", updated),
        ("Skipped", skipped),
        ("Protected", protected),
        ("Unprotected", unprotected),
    ):
        if values:
            lines.append(f"### {label}")
            lines.append("")
            for value in values:
                lines.append(f"- `{value}`")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
