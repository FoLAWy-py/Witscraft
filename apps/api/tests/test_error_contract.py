import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app, database_error_handler
from app.llm.audit import TurnCallBudgetExceededError


def test_database_errors_use_retryable_503_contract() -> None:
    error = OperationalError("select 1", {}, RuntimeError("database offline"))

    response = asyncio.run(database_error_handler(None, error))

    assert response.status_code == 503
    assert response.body == b'{"detail":"Database temporarily unavailable"}'


def test_request_id_is_preserved_in_response_headers() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-123"


def test_turn_call_budget_uses_explicit_429_contract() -> None:
    handler = app.exception_handlers[TurnCallBudgetExceededError]

    response = asyncio.run(handler(None, TurnCallBudgetExceededError(8)))

    assert response.status_code == 429
    assert response.body == (
        b'{"detail":"Per-turn external model call limit reached","limit":8}'
    )
