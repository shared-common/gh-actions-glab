from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from _common import config_path, load_json_file, require_secret, validate_ref_name


@dataclass(frozen=True)
class BranchSpec:
    name_env: str
    source_name: str
    target_name: str
    protected: bool
    sync: bool


@dataclass(frozen=True)
class BranchPolicy:
    prefix: str
    mirror_prefix: str
    mirrors: tuple[BranchSpec, ...]
    snapshot: BranchSpec

    @property
    def all_branches(self) -> tuple[BranchSpec, ...]:
        return self.mirrors + (self.snapshot,)

    @property
    def default_branch(self) -> str:
        return self.mirrors[0].target_name


def _require_dict(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise SystemExit(f"{label} must be an object")
    return value


def _require_list(value: object, label: str) -> list:
    if not isinstance(value, list):
        raise SystemExit(f"{label} must be a list")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} must be a non-empty string")
    return value.strip()


def _load_branch_name(env_name: str) -> str:
    branch_name = require_secret(env_name)
    validate_ref_name(branch_name, env_name)
    return branch_name


def load_branch_policy(path: str | None = None) -> BranchPolicy:
    policy_path = path or config_path("branch-policy.json")
    policy = _require_dict(load_json_file(policy_path, "branch policy"), "branch policy")

    mirror_prefix = _require_string(policy.get("mirrorPrefix"), "mirrorPrefix")
    validate_ref_name(mirror_prefix, "mirrorPrefix")
    prefix_env = _require_string(policy.get("prefixEnv"), "prefixEnv")
    prefix = require_secret(prefix_env)
    validate_ref_name(prefix, prefix_env)

    mirrors: list[BranchSpec] = []
    seen: set[str] = set()
    for item in _require_list(policy.get("mirrors"), "mirrors"):
        spec = _require_dict(item, "mirror entry")
        name_env = _require_string(spec.get("nameEnv"), "mirror.nameEnv")
        source_name = _load_branch_name(name_env)
        target_name = f"{mirror_prefix}/{prefix}/{source_name}"
        validate_ref_name(target_name, f"{name_env} target ref")
        if target_name in seen:
            raise SystemExit(f"Duplicate managed branch: {target_name}")
        seen.add(target_name)
        mirrors.append(
            BranchSpec(
                name_env=name_env,
                source_name=source_name,
                target_name=target_name,
                protected=bool(spec.get("protected", False)),
                sync=True,
            )
        )
    if not mirrors:
        raise SystemExit("Branch policy must define at least one mirror branch")

    snapshot_spec = _require_dict(policy.get("snapshot"), "snapshot")
    snapshot_env = _require_string(snapshot_spec.get("nameEnv"), "snapshot.nameEnv")
    snapshot_name = _load_branch_name(snapshot_env)
    snapshot_target = f"{prefix}/{snapshot_name}"
    validate_ref_name(snapshot_target, f"{snapshot_env} target ref")
    if snapshot_target in seen:
        raise SystemExit(f"Duplicate managed branch: {snapshot_target}")

    snapshot = BranchSpec(
        name_env=snapshot_env,
        source_name=snapshot_name,
        target_name=snapshot_target,
        protected=bool(snapshot_spec.get("protected", False)),
        sync=False,
    )
    return BranchPolicy(
        prefix=prefix,
        mirror_prefix=mirror_prefix,
        mirrors=tuple(mirrors),
        snapshot=snapshot,
    )


def branch_names(branches: Iterable[BranchSpec]) -> list[str]:
    return [branch.target_name for branch in branches]
