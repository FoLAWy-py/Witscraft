from __future__ import annotations

import hashlib
import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.clear_development_stories import _write_receipt, verify_backup_manifest


NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def _write_backup(tmp_path: Path, *, created_at: str = "20260820T145526Z") -> Path:
    artifact = tmp_path / "witscraft-test.dump.cms"
    artifact.write_bytes(b"encrypted-backup-fixture")
    checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
    Path(f"{artifact}.sha256").write_text(
        f"{checksum}  {artifact.name}\n",
        encoding="utf-8",
    )
    manifest_path = Path(f"{artifact}.json")
    manifest_path.write_text(
        json.dumps(
            {
                "created_at_utc": created_at,
                "artifact": artifact.name,
                "artifact_bytes": artifact.stat().st_size,
                "sha256": checksum,
                "format": "postgresql-custom-v1",
                "compression": "zstd-9",
                "encryption": "CMS-AES-256-GCM",
                "schema_revision": "0019",
                "application_revision": "abc123",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_verified_backup_manifest_returns_only_operational_metadata(tmp_path: Path) -> None:
    manifest_path = _write_backup(tmp_path)

    verified = verify_backup_manifest(
        manifest_path,
        now=NOW,
        max_age=timedelta(hours=24),
        cms_validator=lambda _: None,
    )

    assert verified["artifact"] == "witscraft-test.dump.cms"
    assert verified["schema_revision"] == "0019"
    assert verified["application_revision"] == "abc123"
    assert verified["sha256"] == hashlib.sha256(b"encrypted-backup-fixture").hexdigest()


def test_backup_manifest_rejects_stale_or_modified_artifacts(tmp_path: Path) -> None:
    stale_manifest = _write_backup(tmp_path, created_at="20260818T120000Z")
    with pytest.raises(ValueError, match="older"):
        verify_backup_manifest(
            stale_manifest,
            now=NOW,
            max_age=timedelta(hours=24),
            cms_validator=lambda _: None,
        )

    current_manifest = _write_backup(tmp_path)
    (tmp_path / "witscraft-test.dump.cms").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="size|hash"):
        verify_backup_manifest(
            current_manifest,
            now=NOW,
            max_age=timedelta(hours=24),
            cms_validator=lambda _: None,
        )


def test_backup_manifest_rejects_unapproved_encryption(tmp_path: Path) -> None:
    manifest_path = _write_backup(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["encryption"] = "none"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="approved encrypted backup"):
        verify_backup_manifest(
            manifest_path,
            now=NOW,
            max_age=timedelta(hours=24),
            cms_validator=lambda _: None,
        )


def test_backup_manifest_rejects_invalid_cms_envelope(tmp_path: Path) -> None:
    manifest_path = _write_backup(tmp_path)

    with pytest.raises(ValueError, match="valid CMS envelope"):
        verify_backup_manifest(manifest_path, now=NOW, max_age=timedelta(hours=24))


def test_cleanup_receipt_is_private_and_contains_counts_only(tmp_path: Path) -> None:
    receipt = {
        "operation": "delete_all_development_stories",
        "completed_at_utc": "2026-08-20T15:00:00+00:00",
        "deleted_scope_before": {"stories": 2, "messages": 7},
        "deleted_scope_after": {"stories": 0, "messages": 0},
    }

    receipt_path = _write_receipt(tmp_path, receipt)

    assert stat.S_IMODE(receipt_path.stat().st_mode) == 0o600
    assert json.loads(receipt_path.read_text(encoding="utf-8")) == receipt
