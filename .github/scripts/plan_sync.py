from __future__ import annotations

import json
import os
from pathlib import Path

from branch_policy import load_branch_policy
from glab_sync import (
    inspect_target,
    load_gitlab_client,
    load_targets,
    redact_target_context,
    render_plan_summary,
    write_json,
)
from _common import require_env


def main() -> int:
    mode = require_env("SYNC_MODE")
    output_path = os.environ.get("OUTPUT_PATH", "plan.json")
    summary_path = os.environ.get("SUMMARY_PATH", "plan.md")
    github_output = os.environ.get("GITHUB_OUTPUT", "")

    policy = load_branch_policy()
    client = load_gitlab_client(mode)
    targets = load_targets(mode)

    inspected: list[dict] = []
    errors: list[dict[str, str]] = []
    reconcile_queue: list[dict[str, str]] = []

    for target in targets:
        try:
            planned = inspect_target(target, policy, client)
        except SystemExit as exc:
            errors.append(
                {
                    "target_id": target.target_id,
                    "error": redact_target_context(str(exc) or "inspection_failed", target, client),
                }
            )
            continue
        inspected.append(planned)
        if planned.get("needs_reconcile"):
            reconcile_queue.append(
                {
                    "target_id": target.target_id,
                }
            )

    payload = {
        "mode": mode,
        "inspected": inspected,
        "errors": errors,
        "reconcile_queue": reconcile_queue,
    }
    write_json(output_path, payload)
    Path(summary_path).write_text(render_plan_summary(mode, inspected, errors), encoding="utf-8")

    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"has_targets={'true' if bool(targets) else 'false'}\n")
            handle.write(f"should_run={'true' if bool(reconcile_queue) else 'false'}\n")
            handle.write(f"target_count={len(targets)}\n")
            handle.write(f"actionable_count={len(reconcile_queue)}\n")
            handle.write(f"error_count={len(errors)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
