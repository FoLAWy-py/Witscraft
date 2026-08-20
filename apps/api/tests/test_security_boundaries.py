from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config as config_module
from app.config import Settings, get_settings, validate_runtime_security
from app.main import create_app
from app.services.auth_service import SESSION_COOKIE_NAME


def _production_settings(**updates) -> Settings:
    values = {
        "app_environment": "production",
        "frontend_base_url": "https://app.example.com/witscraft",
        "cors_origins": ["https://app.example.com"],
        "cors_origin_regex": None,
        "allowed_hosts": ["app.example.com", "127.0.0.1", "testserver"],
        "database_username": "database-user",
        "database_password": "database-password",
        "deepinfra_api_key": "provider-key",
        "smtp_host": "smtp.example.com",
        "smtp_username": "smtp-user",
        "smtp_password": "smtp-password",
        "smtp_from_email": "noreply@example.com",
        "operational_metrics_log_path": "/tmp/witscraft-test-access-metrics.log",
    }
    values.update(updates)
    return Settings(**values)


def _security_probe_client(settings: Settings) -> TestClient:
    application = create_app(settings)

    @application.post("/security-probe")
    async def security_probe() -> dict[str, bool]:
        return {"ok": True}

    return TestClient(application, base_url="https://app.example.com")


def test_production_runtime_rejects_missing_services_and_broad_boundaries() -> None:
    settings = Settings(
        app_environment="production",
        frontend_base_url="https://app.example.com",
        cors_origins=["*"],
        allowed_hosts=["*"],
        database_username=None,
        database_password=None,
    )

    with pytest.raises(RuntimeError) as caught:
        validate_runtime_security(settings)

    message = str(caught.value)
    assert "database credentials" in message
    assert "provider key" in message
    assert "SMTP" in message
    assert "CORS_ORIGIN_REGEX" in message
    assert "wildcard CORS" in message
    assert "ALLOWED_HOSTS" in message
    assert "OPERATIONAL_METRICS_LOG_PATH" in message


def test_trusted_host_rejects_unknown_hosts() -> None:
    client = _security_probe_client(_production_settings())

    response = client.get("/health", headers={"Host": "attacker.example"})

    assert response.status_code == 400
    assert response.text == "Invalid host header"


def test_csrf_rejects_untrusted_origin_before_route_execution() -> None:
    client = _security_probe_client(_production_settings())

    response = client.post(
        "/security-probe",
        headers={"Origin": "https://attacker.example"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Cross-site request blocked"}


def test_csrf_allows_frontend_origin_and_non_browser_api_clients() -> None:
    client = _security_probe_client(_production_settings())

    browser_response = client.post(
        "/security-probe",
        headers={"Origin": "https://app.example.com"},
    )
    cli_response = client.post("/security-probe")

    assert browser_response.status_code == 200
    assert cli_response.status_code == 200


def test_csrf_rejects_cross_site_cookie_request_without_origin() -> None:
    client = _security_probe_client(_production_settings())
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")

    response = client.post(
        "/security-probe",
        headers={"Sec-Fetch-Site": "cross-site"},
    )

    assert response.status_code == 403


def test_production_disables_api_schema_and_hides_unhandled_errors() -> None:
    application = create_app(_production_settings())

    @application.get("/debug-probe")
    async def debug_probe() -> None:
        raise RuntimeError("sensitive-internal-marker")

    client = TestClient(
        application,
        base_url="https://app.example.com",
        raise_server_exceptions=False,
    )

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404

    response = client.get("/debug-probe")
    assert response.status_code == 500
    assert "sensitive-internal-marker" not in response.text
    assert "Traceback" not in response.text


def test_production_secret_file_does_not_fall_back_to_env_md(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_file = tmp_path / "api.env"
    secret_file.write_text(
        "\n".join(
            [
                "APP_ENVIRONMENT=production",
                "FRONTEND_BASE_URL=https://app.example.com/witscraft",
                "DEEP_INFRA_APIKEY=secret-provider-key",
                "DATABASE_USERNAME=secret-user",
                "DATABASE_PASSWORD=secret-password",
                "SMTP_HOST=smtp.example.com",
                "SMTP_USERNAME=smtp-user",
                "SMTP_PASSWORD=smtp-password",
                "SMTP_FROM_EMAIL=noreply@example.com",
                'CORS_ORIGINS=["https://app.example.com"]',
                "CORS_ORIGIN_REGEX=",
                'ALLOWED_HOSTS=["app.example.com"]',
                f"OPERATIONAL_METRICS_LOG_PATH={tmp_path / 'access-metrics.log'}",
            ]
        )
    )
    monkeypatch.setenv("WITSCRAFT_SECRETS_FILE", str(secret_file))
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    monkeypatch.delenv("DATABASE_USERNAME", raising=False)
    monkeypatch.delenv("DATABASE_PASSWORD", raising=False)
    monkeypatch.setattr(
        config_module,
        "_read_env_md",
        lambda: (_ for _ in ()).throw(AssertionError("production read env.md")),
    )
    get_settings.cache_clear()
    try:
        settings = get_settings()
        validate_runtime_security(settings)
    finally:
        get_settings.cache_clear()

    assert settings.app_environment == "production"
    assert settings.database_username == "secret-user"
    assert settings.deepinfra_api_key == "secret-provider-key"


def test_development_environment_values_survive_missing_env_md_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config_module, "_read_env_md", lambda: {})
    monkeypatch.setenv("DATABASE_USERNAME", "environment-user")
    monkeypatch.setenv("DATABASE_PASSWORD", "environment-password")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://ci.example.test:3000")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.database_username == "environment-user"
    assert settings.database_password == "environment-password"
    assert settings.frontend_base_url == "http://ci.example.test:3000"


def test_process_environment_overrides_development_env_md(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        config_module,
        "_read_env_md",
        lambda: {
            "DATABASE_USERNAME": "local-file-user",
            "DATABASE_PASSWORD": "local-file-password",
            "MEMORY_EMBEDDING_WORKER_BATCH_SIZE": "99",
        },
    )
    monkeypatch.setenv("DATABASE_USERNAME", "process-user")
    monkeypatch.setenv("DATABASE_PASSWORD", "process-password")
    monkeypatch.setenv("MEMORY_EMBEDDING_WORKER_BATCH_SIZE", "7")
    get_settings.cache_clear()
    try:
        settings = get_settings()
    finally:
        get_settings.cache_clear()

    assert settings.database_username == "process-user"
    assert settings.database_password == "process-password"
    assert settings.memory_embedding_worker_batch_size == 7
