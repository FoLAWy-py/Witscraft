#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


STATIC_DIR = Path("apps/web/.next/static")
FORBIDDEN_MARKERS = (
    b"DATABASE_PASSWORD",
    b"OPENAI_API_KEY",
    b"DEEPINFRA_API_KEY",
    b"SMTP_PASSWORD",
    b"WITSCRAFT_SECRETS_FILE",
    b"BEGIN PRIVATE KEY",
    b"BEGIN OPENSSH PRIVATE KEY",
)


def main() -> int:
    if not STATIC_DIR.is_dir():
        print(f"Production static directory not found: {STATIC_DIR}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for path in STATIC_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".map":
            failures.append(f"browser source map: {path}")
            continue
        if path.suffix not in {".js", ".css", ".json", ".txt"}:
            continue
        content = path.read_bytes()
        if b"sourceMappingURL=" in content:
            failures.append(f"sourceMappingURL directive: {path}")
        for marker in FORBIDDEN_MARKERS:
            if marker in content:
                failures.append(f"forbidden marker {marker.decode()}: {path}")

    if failures:
        print("Production artifact security check failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("Production artifact security check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
