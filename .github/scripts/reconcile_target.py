from __future__ import annotations

import os
from pathlib import Path

from _common import require_env
from branch_policy import load_branch_policy
from glab_sync import (
    TargetSpec,
    load_gitlab_client,
    load_targets,
    redact_target_context,
    reconcile_target,
    render_reconcile_summary,
    write_json,
)


def load_target(mode: str, target_id: str) -> TargetSpec:
    for target in load_targets(mode):
        if target.target_id == target_id:
            return target
    raise SystemExit(f"Unknown target id: {target_id}")


def main() -> int:
    mode = require_env("SYNC_MODE").strip()
    target_id = require_env("TARGET_ID").strip()
    output_path = os.environ.get("OUTPUT_PATH", "reconcile.json")
    summary_path = os.environ.get("SUMMARY_PATH", "reconcile.md")
    target = load_target(mode, target_id)
    policy = load_branch_policy()
    client = load_gitlab_client(mode)
    try:
        payload = reconcile_target(target, policy, client)
    except SystemExit as exc:
        raise SystemExit(redact_target_context(str(exc) or "reconcile_failed", target, client)) from exc
    write_json(output_path, payload)
    Path(summary_path).write_text(render_reconcile_summary(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
