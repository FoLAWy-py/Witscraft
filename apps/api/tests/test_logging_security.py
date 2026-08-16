import logging

from app.llm.audit import CallAuditor
from app.logging_security import REDACTED, SensitiveDataFilter, redact_log_value, redact_sensitive_text


def test_redact_sensitive_text_cleans_headers_queries_and_assignments() -> None:
    source = (
        "GET /verify?verify_email=email-token&next=/home "
        "Authorization: Bearer bearer-token password=hunter2 "
        'api_key="sk-abcdefgh12345678" prompt="private-story"'
    )

    redacted = redact_sensitive_text(source)

    assert redacted.count(REDACTED) >= 5
    for secret in ("email-token", "bearer-token", "hunter2", "sk-abcdefgh12345678", "private-story"):
        assert secret not in redacted
    assert "next=/home" in redacted


def test_redact_log_value_recursively_hides_sensitive_fields() -> None:
    payload = {
        "request_id": "safe-id",
        "messages": [{"role": "user", "content": "private prompt"}],
        "nested": {"smtp_password": "mail-secret"},
    }

    redacted = redact_log_value(payload)

    assert redacted["request_id"] == "safe-id"
    assert redacted["messages"] == REDACTED
    assert redacted["nested"]["smtp_password"] == REDACTED


def test_logging_filter_redacts_uvicorn_access_log_arguments() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/api/auth/verify-email?token=url-secret", "1.1", 200),
        None,
    )

    assert SensitiveDataFilter().filter(record)
    formatted = logging.Formatter().format(record)

    assert "url-secret" not in formatted
    assert REDACTED in formatted
    assert "127.0.0.1" in formatted
    assert "token=[REDACTED] HTTP/1.1" in formatted


def test_model_audit_error_is_redacted_before_persistence() -> None:
    error = RuntimeError("provider failed: api_key=sk-secret123456 prompt=private-story")

    safe_error = CallAuditor._safe_error(error)

    assert safe_error is not None
    assert "sk-secret123456" not in safe_error
    assert "private-story" not in safe_error
    assert safe_error.count(REDACTED) == 2
