from pathlib import Path
import subprocess

import pytest

from scripts.prepare_restore_smoke import main


ROOT = Path(__file__).resolve().parents[3]


def test_backup_shell_scripts_are_syntactically_valid() -> None:
    for script in ("backup-postgres.sh", "restore-postgres.sh"):
        result = subprocess.run(
            ["zsh", "-n", str(ROOT / "scripts" / script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr


def test_backup_scripts_do_not_contain_embedded_credentials() -> None:
    for script in ("backup-postgres.sh", "restore-postgres.sh"):
        content = (ROOT / "scripts" / script).read_text()
        assert "DATABASE_PASSWORD=" not in content
        assert "PRIVATE KEY-----" not in content
        assert "eval " not in content


def test_backup_streams_pg_dump_output_to_encryption() -> None:
    content = (ROOT / "scripts" / "backup-postgres.sh").read_text()
    assert "--file -" not in content
    assert 'artifact_bytes" -ge 1024' in content


def test_restore_smoke_fixture_rejects_the_primary_database(monkeypatch: pytest.MonkeyPatch) -> None:
    class PrimaryDatabaseSettings:
        database_name = "witscraft"

    monkeypatch.setattr(
        "scripts.prepare_restore_smoke.get_settings", lambda: PrimaryDatabaseSettings()
    )
    with pytest.raises(RuntimeError, match="restricted"):
        import asyncio

        asyncio.run(main())
