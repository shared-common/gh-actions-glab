from __future__ import annotations

import os
import re


NAME_RE = re.compile(r"^[A-Z0-9_]+$")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def validate_names(values: list[str], label: str) -> None:
    for value in values:
        if not NAME_RE.match(value):
            raise SystemExit(f"Invalid secret name in {label}: {value}")


def main() -> int:
    all_secrets = ordered_unique(parse_csv(os.environ.get("SECRETS", "")))
    optional = ordered_unique(parse_csv(os.environ.get("ALLOW_EMPTY_SECRETS", "")))
    validate_names(all_secrets, "SECRETS")
    validate_names(optional, "ALLOW_EMPTY_SECRETS")

    if not all_secrets:
        raise SystemExit("No secrets specified")

    missing = [value for value in optional if value not in all_secrets]
    if missing:
        raise SystemExit(f"allow-empty-secrets references names not present in secrets: {','.join(missing)}")

    optional_set = set(optional)
    required = [value for value in all_secrets if value not in optional_set]

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if not github_output:
        raise SystemExit("GITHUB_OUTPUT not set")

    with open(github_output, "a", encoding="utf-8") as handle:
        handle.write(f"required-secrets={','.join(required)}\n")
        handle.write(f"optional-secrets={','.join(optional)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
