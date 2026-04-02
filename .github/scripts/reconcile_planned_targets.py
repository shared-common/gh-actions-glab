from __future__ import annotations

import os
from pathlib import Path

from _common import load_json_file, require_env
from branch_policy import load_branch_policy
from glab_sync import (
    TargetSpec,
    load_gitlab_client,
    load_targets,
    reconcile_target,
    redact_target_context,
    render_reconcile_batch_summary,
    write_json,
)


def load_reconcile_queue(plan_path: str, mode: str) -> list[str]:
    payload = load_json_file(plan_path, "plan")
    if not isinstance(payload, dict):
        raise SystemExit("plan file must be a JSON object")

    plan_mode = str(payload.get("mode") or "").strip()
    if plan_mode != mode:
        raise SystemExit(f"plan mode mismatch: expected {mode}, found {plan_mode or 'empty'}")

    raw_queue = payload.get("reconcile_queue")
    if not isinstance(raw_queue, list):
        raise SystemExit("plan file reconcile_queue must be a JSON array")

    target_ids: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_queue):
        if not isinstance(item, dict):
            raise SystemExit(f"plan reconcile_queue[{index}] must be a JSON object")
        target_id = str(item.get("target_id") or "").strip()
        if not target_id:
            raise SystemExit(f"plan reconcile_queue[{index}] is missing target_id")
        if target_id in seen:
            continue
        seen.add(target_id)
        target_ids.append(target_id)
    return target_ids


def render_unknown_target_error(target_id: str) -> dict[str, str]:
    return {
        "target_id": target_id,
        "error": "target_id_missing_from_runtime_config",
    }


def main() -> int:
    mode = require_env("SYNC_MODE")
    plan_path = os.environ.get("PLAN_PATH", "plan.json")
    output_path = os.environ.get("OUTPUT_PATH", "reconcile.json")
    summary_path = os.environ.get("SUMMARY_PATH", "reconcile.md")

    target_ids = load_reconcile_queue(plan_path, mode)
    policy = load_branch_policy()
    client = load_gitlab_client(mode)
    targets_by_id: dict[str, TargetSpec] = {target.target_id: target for target in load_targets(mode)}

    reconciled: list[dict] = []
    errors: list[dict[str, str]] = []

    for target_id in target_ids:
        target = targets_by_id.get(target_id)
        if target is None:
            errors.append(render_unknown_target_error(target_id))
            continue
        try:
            reconciled.append(reconcile_target(target, policy, client))
        except SystemExit as exc:
            errors.append(
                {
                    "target_id": target_id,
                    "error": redact_target_context(str(exc) or "reconcile_failed", target, client),
                }
            )

    payload = {
        "mode": mode,
        "queued_count": len(target_ids),
        "reconciled": reconciled,
        "errors": errors,
    }
    write_json(output_path, payload)
    Path(summary_path).write_text(
        render_reconcile_batch_summary(mode, len(target_ids), reconciled, errors),
        encoding="utf-8",
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
