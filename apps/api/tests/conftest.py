import pytest

from app.config import get_settings


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    settings = get_settings()
    database_name = settings.database_name.casefold()
    isolated_name = database_name.startswith("witscraft_preflight_test_") or database_name.endswith(
        "-ci"
    )
    if settings.app_environment != "test" or not isolated_name:
        raise pytest.UsageError(
            "Backend tests require APP_ENVIRONMENT=test and an isolated database name "
            "using the preflight-test prefix or '-ci' suffix; use "
            "scripts/run-backend-tests-isolated.sh"
        )
