from __future__ import annotations

import json
import os
from pathlib import Path

from _common import require_env
from branch_policy import load_branch_policy
from glab_sync import (
    TargetSpec,
    load_gitlab_client,
    reconcile_target,
    render_reconcile_summary,
    write_json,
)


def main() -> int:
    target_json = require_env("TARGET_JSON")
    output_path = os.environ.get("OUTPUT_PATH", "reconcile.json")
    summary_path = os.environ.get("SUMMARY_PATH", "reconcile.md")

    try:
        target_payload = json.loads(target_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"TARGET_JSON is not valid JSON: {exc.msg}") from exc
    if not isinstance(target_payload, dict):
        raise SystemExit("TARGET_JSON must be a JSON object")

    target = TargetSpec.from_payload(target_payload)
    policy = load_branch_policy()
    client = load_gitlab_client(target.mode)
    payload = reconcile_target(target, policy, client)
    write_json(output_path, payload)
    Path(summary_path).write_text(render_reconcile_summary(payload), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
