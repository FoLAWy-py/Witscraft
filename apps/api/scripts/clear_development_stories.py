"""Inventory or delete every story after verifying a recent encrypted backup."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings


ROOT_DIR = Path(__file__).resolve().parents[3]
CONFIRMATION = "DELETE ALL DEVELOPMENT STORIES"
STORY_TABLES = (
    "stories",
    "story_branches",
    "messages",
    "generation_requests",
    "plot_events",
    "story_state_snapshots",
    "story_summaries",
    "canon_facts",
)
PRESERVED_TABLES = (
    "users",
    "auth_credentials",
    "auth_sessions",
    "worlds",
    "characters",
    "user_preferences",
    "user_model_routes",
    "user_model_route_changes",
    "model_calls",
    "quota_reset_events",
    "quota_policy_changes",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backup-manifest",
        type=Path,
        required=True,
        help="Manifest written by scripts/backup-postgres.sh",
    )
    parser.add_argument("--execute", action="store_true", help="Commit the deletion")
    parser.add_argument(
        "--confirm",
        default="",
        help=f'Exact confirmation required with --execute: "{CONFIRMATION}"',
    )
    parser.add_argument(
        "--allow-production-runtime",
        action="store_true",
        help="Required when APP_ENVIRONMENT=production, even for development data",
    )
    parser.add_argument(
        "--max-backup-age-hours",
        type=int,
        default=24,
        choices=range(1, 169),
        metavar="1-168",
    )
    parser.add_argument(
        "--receipt-dir",
        type=Path,
        default=ROOT_DIR / ".runtime" / "maintenance",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_cms_envelope(path: Path) -> None:
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("OpenSSL is required to validate the encrypted backup envelope")
    result = subprocess.run(
        [openssl, "cms", "-cmsout", "-inform", "DER", "-in", str(path), "-noout"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("Backup artifact is not a valid CMS envelope")


def verify_backup_manifest(
    manifest_path: Path,
    *,
    now: datetime,
    max_age: timedelta,
    cms_validator: Callable[[Path], None] = _verify_cms_envelope,
) -> dict[str, Any]:
    resolved_manifest = manifest_path.expanduser().resolve(strict=True)
    manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    required = {
        "created_at_utc",
        "artifact",
        "artifact_bytes",
        "sha256",
        "format",
        "encryption",
        "schema_revision",
        "application_revision",
    }
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"Backup manifest is missing fields: {', '.join(missing)}")
    if manifest["format"] != "postgresql-custom-v1":
        raise ValueError("Backup manifest has an unsupported format")
    if manifest["encryption"] != "CMS-AES-256-GCM":
        raise ValueError("Backup manifest is not an approved encrypted backup")

    created_at = datetime.strptime(str(manifest["created_at_utc"]), "%Y%m%dT%H%M%SZ").replace(
        tzinfo=UTC
    )
    if created_at > now + timedelta(minutes=5):
        raise ValueError("Backup manifest creation time is in the future")
    if now - created_at > max_age:
        raise ValueError("Backup is older than the permitted pre-wipe window")

    artifact_name = str(manifest["artifact"])
    if Path(artifact_name).name != artifact_name:
        raise ValueError("Backup artifact must be a filename in the manifest directory")
    artifact_path = (resolved_manifest.parent / artifact_name).resolve(strict=True)
    if artifact_path.parent != resolved_manifest.parent:
        raise ValueError("Backup artifact escaped the manifest directory")
    if artifact_path.stat().st_size != int(manifest["artifact_bytes"]):
        raise ValueError("Backup artifact size does not match its manifest")

    actual_hash = _sha256(artifact_path)
    if actual_hash != str(manifest["sha256"]):
        raise ValueError("Backup artifact hash does not match its manifest")
    checksum_path = Path(f"{artifact_path}.sha256")
    checksum_line = checksum_path.resolve(strict=True).read_text(encoding="utf-8").strip()
    checksum_parts = checksum_line.split(maxsplit=1)
    if len(checksum_parts) != 2 or checksum_parts[0] != actual_hash:
        raise ValueError("Backup checksum sidecar does not match the artifact")
    if Path(checksum_parts[1]).name != artifact_name:
        raise ValueError("Backup checksum sidecar names a different artifact")
    cms_validator(artifact_path)

    return {
        "manifest_path": str(resolved_manifest),
        "artifact": artifact_name,
        "sha256": actual_hash,
        "schema_revision": str(manifest["schema_revision"]),
        "application_revision": str(manifest["application_revision"]),
        "created_at_utc": created_at.isoformat(),
    }


async def _table_counts(session: AsyncSession, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = int(await session.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
    return counts


async def _story_scoped_counts(session: AsyncSession) -> dict[str, int]:
    counts = await _table_counts(session, STORY_TABLES)
    counts["story_memory_items"] = int(
        await session.scalar(text("SELECT count(*) FROM memory_items WHERE story_id IS NOT NULL"))
        or 0
    )
    counts["story_memory_embedding_tasks"] = int(
        await session.scalar(
            text("SELECT count(*) FROM memory_embedding_tasks WHERE story_id IS NOT NULL")
        )
        or 0
    )
    counts["model_calls_with_story"] = int(
        await session.scalar(text("SELECT count(*) FROM model_calls WHERE story_id IS NOT NULL"))
        or 0
    )
    return counts


async def _preserved_counts(session: AsyncSession) -> dict[str, int]:
    counts = await _table_counts(session, PRESERVED_TABLES)
    counts["non_story_memory_items"] = int(
        await session.scalar(text("SELECT count(*) FROM memory_items WHERE story_id IS NULL"))
        or 0
    )
    counts["non_story_memory_embedding_tasks"] = int(
        await session.scalar(
            text("SELECT count(*) FROM memory_embedding_tasks WHERE story_id IS NULL")
        )
        or 0
    )
    return counts


def _write_receipt(receipt_dir: Path, receipt: dict[str, Any]) -> Path:
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(receipt_dir, 0o700)
    timestamp = str(receipt["completed_at_utc"]).replace(":", "").replace("-", "")
    receipt_path = receipt_dir / f"story-wipe-{timestamp}.json"
    temporary_path = receipt_path.with_suffix(".json.partial")
    temporary_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(temporary_path, 0o600)
    temporary_path.replace(receipt_path)
    return receipt_path


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("Database credentials are required")
    if settings.app_environment == "test":
        pass
    elif settings.app_environment == "production" and not args.allow_production_runtime:
        raise RuntimeError("Production runtime requires --allow-production-runtime")

    if args.execute and args.confirm != CONFIRMATION:
        raise RuntimeError(f'Execution requires --confirm "{CONFIRMATION}"')
    if not args.execute and args.confirm:
        raise RuntimeError("--confirm is only valid together with --execute")

    backup = verify_backup_manifest(
        args.backup_manifest,
        now=datetime.now(UTC),
        max_age=timedelta(hours=args.max_backup_age_hours),
    )
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            revision = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
            if revision != backup["schema_revision"]:
                raise RuntimeError(
                    "Backup schema revision does not match the target database revision"
                )

            before_story = await _story_scoped_counts(session)
            before_preserved = await _preserved_counts(session)
            print(
                json.dumps(
                    {
                        "mode": "execute" if args.execute else "dry-run",
                        "story": before_story,
                        "preserved": before_preserved,
                    },
                    sort_keys=True,
                )
            )
            if not args.execute:
                return 0

            await session.execute(text("SELECT pg_advisory_xact_lock(918273645)"))
            await session.execute(text("LOCK TABLE stories IN ACCESS EXCLUSIVE MODE"))
            locked_story = await _story_scoped_counts(session)
            if locked_story != before_story:
                raise RuntimeError("Story data changed during wipe preflight; retry with a new inventory")

            await session.execute(text("DELETE FROM stories"))
            after_story = await _story_scoped_counts(session)
            after_preserved = await _preserved_counts(session)
            nonzero = {name: count for name, count in after_story.items() if count != 0}
            if nonzero:
                raise RuntimeError(f"Story cleanup left scoped rows: {nonzero}")
            if after_preserved != before_preserved:
                raise RuntimeError("A preserved table changed during story cleanup")
            await session.commit()

        completed_at = datetime.now(UTC).isoformat()
        receipt = {
            "operation": "delete_all_development_stories",
            "completed_at_utc": completed_at,
            "schema_revision": backup["schema_revision"],
            "application_revision": backup["application_revision"],
            "backup": {
                "artifact": backup["artifact"],
                "created_at_utc": backup["created_at_utc"],
                "sha256": backup["sha256"],
            },
            "deleted_scope_before": before_story,
            "deleted_scope_after": after_story,
            "preserved_before": before_preserved,
            "preserved_after": after_preserved,
        }
        receipt_path = _write_receipt(args.receipt_dir, receipt)
        print(f"Story cleanup committed. Receipt: {receipt_path}")
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
