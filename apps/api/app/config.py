import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[3]


def _read_env_md() -> dict[str, str]:
    env_path = ROOT_DIR / "env.md"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Witscraft API"
    app_environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )
    cors_origin_regex: str | None = (
        r"^https?://(localhost|127\.0\.0\.1|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}|"
        r"192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$"
    )
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    csrf_trusted_origins: list[str] = Field(default_factory=list)
    rate_limit_enabled: bool | None = None
    rate_limit_max_keys: int = Field(default=10000, ge=100)
    rate_limit_register_requests: int = Field(default=5, ge=1)
    rate_limit_login_requests: int = Field(default=30, ge=1)
    rate_limit_auth_email_requests: int = Field(default=5, ge=1)
    rate_limit_provider_test_requests: int = Field(default=10, ge=1)
    rate_limit_generation_requests: int = Field(default=20, ge=1)
    rate_limit_export_requests: int = Field(default=30, ge=1)
    rate_limit_account_delete_requests: int = Field(default=5, ge=1)
    rate_limit_admin_reset_requests: int = Field(default=5, ge=1)

    openai_api_key: str | None = None
    deepinfra_api_key: str | None = None
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"

    database_username: str | None = None
    database_password: str | None = None
    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "witscraft"

    default_provider: str = "deepinfra"
    default_openai_model: str = "gpt-5.5"
    default_deepinfra_model: str = "Qwen/Qwen3-Max"
    openai_embedding_model: str = "text-embedding-3-large"
    model_pricing: dict[str, dict[str, float]] = Field(default_factory=dict)
    model_pricing_version: str = "unconfigured"
    dry_run_llm: bool = False
    llm_connect_timeout_seconds: float = Field(default=10.0, gt=0)
    llm_read_timeout_seconds: float = Field(default=90.0, gt=0)
    llm_total_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_max_attempts: int = Field(default=2, ge=1, le=5)
    llm_retry_base_seconds: float = Field(default=0.5, ge=0)
    llm_retry_max_seconds: float = Field(default=4.0, ge=0)
    llm_max_fallbacks: int = Field(default=1, ge=0, le=3)
    llm_max_external_calls_per_turn: int = Field(default=8, ge=2, le=20)
    llm_circuit_failure_threshold: int = Field(default=3, ge=1)
    llm_circuit_cooldown_seconds: float = Field(default=30.0, gt=0)
    stream_checkpoint_seconds: float = Field(default=1.0, gt=0)
    stream_checkpoint_characters: int = Field(default=512, ge=64)
    generation_stale_seconds: int = Field(default=900, ge=120)
    auth_session_days: int = 30
    auth_cookie_secure: bool | None = None
    auth_login_max_attempts: int = 5
    auth_login_window_minutes: int = 15
    auth_login_lock_minutes: int = 15
    auth_verification_token_hours: int = 24
    auth_password_reset_token_minutes: int = 30
    auth_email_min_interval_seconds: int = 60
    auth_login_throttle_retention_hours: int = Field(default=24, ge=1)
    model_call_retention_days: int = Field(default=30, ge=1)
    user_weekly_token_quota: int = Field(default=500000, ge=1000)
    user_weekly_token_soft_limit_percentage: int = Field(default=80, ge=1, le=99)

    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    frontend_base_url: str = "http://127.0.0.1:3000"

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_username
            and self.smtp_password
            and self.smtp_from_email
        )

    @property
    def session_cookie_secure(self) -> bool:
        if self.auth_cookie_secure is not None:
            return self.auth_cookie_secure
        return self.app_environment == "production"

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.app_environment != "production":
            return self
        if not self.frontend_base_url.lower().startswith("https://"):
            raise ValueError("FRONTEND_BASE_URL must use HTTPS in production")
        if not self.session_cookie_secure:
            raise ValueError("Secure authentication cookies cannot be disabled in production")
        return self

    @property
    def database_url(self) -> str | None:
        if not self.database_username or not self.database_password:
            return None
        return (
            "postgresql+asyncpg://"
            f"{self.database_username}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )

    @property
    def frontend_origin(self) -> str:
        parsed = urlsplit(self.frontend_base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def rate_limits_active(self) -> bool:
        if self.rate_limit_enabled is not None:
            return self.rate_limit_enabled
        return self.app_environment == "production"


def validate_runtime_security(settings: Settings) -> None:
    if settings.app_environment != "production":
        return
    errors: list[str] = []
    if settings.database_url is None:
        errors.append("database credentials are required")
    if not settings.openai_api_key and not settings.deepinfra_api_key:
        errors.append("at least one model provider key is required")
    if settings.dry_run_llm:
        errors.append("DRY_RUN_LLM cannot be enabled")
    if not settings.rate_limits_active:
        errors.append("rate limiting cannot be disabled")
    if not settings.smtp_configured:
        errors.append("SMTP configuration is required")
    if settings.cors_origin_regex:
        errors.append("CORS_ORIGIN_REGEX must be disabled")
    if "*" in settings.cors_origins:
        errors.append("wildcard CORS origins are forbidden")
    if not settings.allowed_hosts or any("*" in host for host in settings.allowed_hosts):
        errors.append("ALLOWED_HOSTS must be explicit")
    frontend_host = urlsplit(settings.frontend_base_url).hostname
    if frontend_host not in settings.allowed_hosts:
        errors.append("ALLOWED_HOSTS must include the frontend hostname")
    if errors:
        raise RuntimeError("Invalid production security configuration: " + "; ".join(errors))


@lru_cache
def get_settings() -> Settings:
    secrets_file = os.environ.get("WITSCRAFT_SECRETS_FILE")
    secret_values = dotenv_values(secrets_file) if secrets_file else {}
    runtime_environment = (
        os.environ.get("APP_ENVIRONMENT")
        or secret_values.get("APP_ENVIRONMENT")
        or "development"
    )
    if runtime_environment == "production":
        compatibility: dict[str, str] = {}
        if not os.environ.get("DEEPINFRA_API_KEY") and secret_values.get("DEEP_INFRA_APIKEY"):
            compatibility["deepinfra_api_key"] = str(secret_values["DEEP_INFRA_APIKEY"])
        return Settings(_env_file=secrets_file, **compatibility)

    env_md = _read_env_md()
    overrides: dict[str, object] = {}
    text_settings = {
        "OPENAI_API_KEY": "openai_api_key",
        "DATABASE_USERNAME": "database_username",
        "DATABASE_PASSWORD": "database_password",
        "SMTP_HOST": "smtp_host",
        "SMTP_USERNAME": "smtp_username",
        "SMTP_PASSWORD": "smtp_password",
        "SMTP_FROM_EMAIL": "smtp_from_email",
        "FRONTEND_BASE_URL": "frontend_base_url",
    }
    for env_key, setting_name in text_settings.items():
        if env_key in env_md:
            overrides[setting_name] = env_md[env_key]
    deepinfra_key = env_md.get("DEEPINFRA_API_KEY") or env_md.get("DEEP_INFRA_APIKEY")
    if deepinfra_key:
        overrides["deepinfra_api_key"] = deepinfra_key
    if "SMTP_PORT" in env_md:
        overrides["smtp_port"] = int(env_md["SMTP_PORT"])
    if env_md.get("MODEL_PRICING"):
        overrides["model_pricing"] = json.loads(env_md["MODEL_PRICING"])
    if env_md.get("MODEL_PRICING_VERSION"):
        overrides["model_pricing_version"] = env_md["MODEL_PRICING_VERSION"]
    if env_md.get("AUTH_COOKIE_SECURE"):
        overrides["auth_cookie_secure"] = env_md["AUTH_COOKIE_SECURE"]
    numeric_settings = {
        "LLM_CONNECT_TIMEOUT_SECONDS": ("llm_connect_timeout_seconds", float),
        "LLM_READ_TIMEOUT_SECONDS": ("llm_read_timeout_seconds", float),
        "LLM_TOTAL_TIMEOUT_SECONDS": ("llm_total_timeout_seconds", float),
        "LLM_MAX_ATTEMPTS": ("llm_max_attempts", int),
        "LLM_RETRY_BASE_SECONDS": ("llm_retry_base_seconds", float),
        "LLM_RETRY_MAX_SECONDS": ("llm_retry_max_seconds", float),
        "LLM_MAX_FALLBACKS": ("llm_max_fallbacks", int),
        "LLM_MAX_EXTERNAL_CALLS_PER_TURN": ("llm_max_external_calls_per_turn", int),
        "LLM_CIRCUIT_FAILURE_THRESHOLD": ("llm_circuit_failure_threshold", int),
        "LLM_CIRCUIT_COOLDOWN_SECONDS": ("llm_circuit_cooldown_seconds", float),
        "STREAM_CHECKPOINT_SECONDS": ("stream_checkpoint_seconds", float),
        "STREAM_CHECKPOINT_CHARACTERS": ("stream_checkpoint_characters", int),
        "GENERATION_STALE_SECONDS": ("generation_stale_seconds", int),
        "AUTH_LOGIN_THROTTLE_RETENTION_HOURS": (
            "auth_login_throttle_retention_hours",
            int,
        ),
        "MODEL_CALL_RETENTION_DAYS": ("model_call_retention_days", int),
        "USER_WEEKLY_TOKEN_QUOTA": ("user_weekly_token_quota", int),
        "USER_WEEKLY_TOKEN_SOFT_LIMIT_PERCENTAGE": (
            "user_weekly_token_soft_limit_percentage",
            int,
        ),
        "RATE_LIMIT_ADMIN_RESET_REQUESTS": ("rate_limit_admin_reset_requests", int),
    }
    for env_key, (setting_name, parser) in numeric_settings.items():
        if env_key in env_md:
            overrides[setting_name] = parser(env_md[env_key])
    return Settings(**overrides)
