import asyncio
from email.message import EmailMessage

from app.config import Settings
from app.services import email_service


def _production_settings() -> Settings:
    return Settings(
        app_environment="production",
        frontend_base_url="https://app.example.com/witscraft",
        smtp_host="mail.example.com",
        smtp_username="noreply@example.com",
        smtp_password="test-password",
        smtp_from_email="noreply@example.com",
    )


def test_verification_email_uses_public_witscraft_url(monkeypatch) -> None:
    sent: list[EmailMessage] = []

    async def capture_message(_settings: Settings, message: EmailMessage) -> None:
        sent.append(message)

    monkeypatch.setattr(email_service, "_send_message", capture_message)

    asyncio.run(
        email_service.send_verification_email(
            _production_settings(),
            recipient="author@example.com",
            display_name="Author",
            token="verification-token",
        )
    )

    assert len(sent) == 1
    plain_body = sent[0].get_body(preferencelist=("plain",))
    assert plain_body is not None
    assert (
        "https://app.example.com/witscraft?verify_email=verification-token"
        in plain_body.get_content()
    )


def test_password_reset_email_uses_public_witscraft_url(monkeypatch) -> None:
    sent: list[EmailMessage] = []

    async def capture_message(_settings: Settings, message: EmailMessage) -> None:
        sent.append(message)

    monkeypatch.setattr(email_service, "_send_message", capture_message)

    asyncio.run(
        email_service.send_password_reset_email(
            _production_settings(),
            recipient="author@example.com",
            display_name="Author",
            token="reset-token",
        )
    )

    assert len(sent) == 1
    plain_body = sent[0].get_body(preferencelist=("plain",))
    assert plain_body is not None
    assert (
        "https://app.example.com/witscraft?reset_password=reset-token"
        in plain_body.get_content()
    )
