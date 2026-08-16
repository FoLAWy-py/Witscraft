from __future__ import annotations

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.config import Settings


API_DIR = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ReadinessReport:
    checks: dict[str, str]
    migration_revisions: tuple[str, ...] = ()
    expected_migration_revisions: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return all(result == "ok" for result in self.checks.values())


@lru_cache
def expected_migration_heads() -> tuple[str, ...]:
    config = Config(str(API_DIR / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return tuple(sorted(script.get_heads()))


def _configuration_ready(settings: Settings) -> bool:
    provider_ready = bool(
        settings.openai_api_key or settings.deepinfra_api_key or settings.dry_run_llm
    )
    return settings.database_url is not None and provider_ready


async def check_readiness(
    settings: Settings,
    engine: AsyncEngine,
    *,
    timeout_seconds: float = 3.0,
) -> ReadinessReport:
    checks = {"configuration": "ok" if _configuration_ready(settings) else "failed"}
    expected_revisions = expected_migration_heads()
    if checks["configuration"] != "ok":
        checks.update(database="skipped", migrations="skipped")
        return ReadinessReport(
            checks=checks,
            expected_migration_revisions=expected_revisions,
        )

    try:
        async with asyncio.timeout(timeout_seconds):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
                current_revisions = tuple(sorted(result.scalars().all()))
    except Exception:
        checks.update(database="failed", migrations="unknown")
        return ReadinessReport(
            checks=checks,
            expected_migration_revisions=expected_revisions,
        )

    checks["database"] = "ok"
    checks["migrations"] = "ok" if current_revisions == expected_revisions else "failed"
    return ReadinessReport(
        checks=checks,
        migration_revisions=current_revisions,
        expected_migration_revisions=expected_revisions,
    )
