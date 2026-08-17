from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.health import ReadinessReport, expected_migration_heads


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_live_and_ready_health_contracts_and_shutdown() -> None:
    database_engine = FakeEngine()

    async def ready_probe(_settings, observed_engine) -> ReadinessReport:
        assert observed_engine is database_engine
        return ReadinessReport(
            checks={"configuration": "ok", "database": "ok", "migrations": "ok"},
            migration_revisions=("0011",),
            expected_migration_revisions=("0011",),
        )

    application = create_app(
        Settings(dry_run_llm=True),
        database_engine=database_engine,
        readiness_probe=ready_probe,
    )
    with TestClient(application) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

        assert live.status_code == 200
        assert live.json()["status"] == "alive"
        assert ready.status_code == 200
        assert ready.headers["Cache-Control"] == "no-store"
        assert ready.json() == {
            "status": "ready",
            "checks": {"configuration": "ok", "database": "ok", "migrations": "ok"},
            "migration_revisions": ["0011"],
            "expected_migration_revisions": ["0011"],
        }

    assert database_engine.disposed is True


def test_readiness_returns_503_without_exposing_internal_errors() -> None:
    async def failed_probe(_settings, _engine) -> ReadinessReport:
        return ReadinessReport(
            checks={
                "configuration": "ok",
                "database": "failed",
                "migrations": "unknown",
            },
            expected_migration_revisions=("0011",),
        )

    application = create_app(
        Settings(dry_run_llm=True),
        database_engine=FakeEngine(),
        readiness_probe=failed_probe,
    )
    with TestClient(application) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"
    assert "exception" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_expected_migration_revision_matches_repository_head() -> None:
    assert expected_migration_heads() == ("0018",)
