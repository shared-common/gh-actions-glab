from __future__ import annotations

import os
import re
from pathlib import Path


NAME_RE = re.compile(r"^[A-Z0-9_]+$")


def parse_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    secrets = parse_csv(os.environ.get("SECRETS", ""))
    allow_empty = set(parse_csv(os.environ.get("ALLOW_EMPTY_SECRETS", "")))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "bws"))
    env_file = os.environ.get("GITHUB_ENV", "")

    if not secrets:
        raise SystemExit("No secrets specified")
    if not env_file:
        raise SystemExit("GITHUB_ENV not set")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir_resolved = output_dir.resolve()
    env_lines: list[str] = []

    for name in secrets:
        if not NAME_RE.match(name):
            raise SystemExit(f"Invalid secret name: {name}")
        if name not in os.environ:
            raise SystemExit(f"Missing secret: {name}")

        value = os.environ.get(name, "")
        if not value and name not in allow_empty:
            raise SystemExit(f"Empty secret: {name}")

        path = output_dir / name
        path_resolved = path.resolve()
        if output_dir_resolved not in path_resolved.parents and path_resolved != output_dir_resolved:
            raise SystemExit("Secret path escapes output directory")

        path.write_text(value, encoding="utf-8")
        os.chmod(path, 0o600)
        env_lines.append(f"{name}_FILE={path_resolved}")

    with open(env_file, "a", encoding="utf-8") as handle:
        handle.write("\n".join(env_lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
