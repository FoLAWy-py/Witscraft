#!/usr/bin/env python3
"""Create a non-sensitive manifest for an already validated release build."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_FILES = (Path("apps/api/uv.lock"), Path("apps/web/package-lock.json"))


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _migration_heads() -> list[str]:
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in (ROOT / "apps/api/migrations/versions").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
                for target in targets:
                    if target in {"revision", "down_revision"}:
                        values[target] = ast.literal_eval(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in {"revision", "down_revision"} and node.value is not None:
                    values[node.target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        if not isinstance(revision, str):
            raise RuntimeError(f"Migration has no literal revision: {path.name}")
        revisions.add(revision)
        down_revision = values.get("down_revision")
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parents.update(parent for parent in down_revision if isinstance(parent, str))
    heads = sorted(revisions - parents)
    if not heads:
        raise RuntimeError("No Alembic migration head was found")
    return heads


def _created_at() -> str:
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = (
        datetime.fromtimestamp(int(source_epoch), timezone.utc)
        if source_epoch is not None
        else datetime.now(timezone.utc)
    )
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def build_manifest(*, allow_dirty: bool = False) -> dict:
    dirty = bool(_git("status", "--porcelain", "--untracked-files=no"))
    if dirty and not allow_dirty:
        raise RuntimeError("Tracked worktree changes must be committed before creating a release manifest")

    revision = _git("rev-parse", "HEAD")
    build_id_path = ROOT / "apps/web/.next/BUILD_ID"
    if not build_id_path.is_file():
        raise RuntimeError("Frontend production build is missing; run npm run build:production first")

    return {
        "manifest_schema": 1,
        "created_at_utc": _created_at(),
        "application_revision": revision,
        "source_tree_clean": not dirty,
        "migration_heads": _migration_heads(),
        "dependency_locks": {
            str(path): {"sha256": _sha256(ROOT / path)} for path in LOCK_FILES
        },
        "frontend": {"build_id": build_id_path.read_text().strip()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-dirty", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        manifest = build_manifest(allow_dirty=args.allow_dirty)
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(temporary, 0o600)
        temporary.replace(output)
    except (OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Release manifest failed: {error}", file=sys.stderr)
        return 1
    print(f"Release manifest created: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
