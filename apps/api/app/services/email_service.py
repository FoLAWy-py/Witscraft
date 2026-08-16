from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from html import escape
from urllib.parse import urlencode

from app.config import Settings


class EmailDeliveryError(RuntimeError):
    pass


async def check_smtp_connection(settings: Settings) -> None:
    try:
        await asyncio.to_thread(_check_connection, settings)
    except Exception as error:
        raise EmailDeliveryError("SMTP connection failed") from error


async def send_verification_email(
    settings: Settings,
    *,
    recipient: str,
    display_name: str,
    token: str,
) -> None:
    query = urlencode({"verify_email": token})
    link = f"{settings.frontend_base_url.rstrip('/')}?{query}"
    message = _message(
        settings,
        recipient=recipient,
        subject="验证你的 Witscraft 邮箱",
        display_name=display_name,
        action_label="验证邮箱",
        action_link=link,
        expiry="24 小时",
        explanation="完成验证后即可进入你的小说工作区。",
    )
    await _send_message(settings, message)


async def send_password_reset_email(
    settings: Settings,
    *,
    recipient: str,
    display_name: str,
    token: str,
) -> None:
    query = urlencode({"reset_password": token})
    link = f"{settings.frontend_base_url.rstrip('/')}?{query}"
    message = _message(
        settings,
        recipient=recipient,
        subject="重置你的 Witscraft 密码",
        display_name=display_name,
        action_label="重置密码",
        action_link=link,
        expiry="30 分钟",
        explanation="如果这不是你的操作，可以忽略这封邮件。",
    )
    await _send_message(settings, message)


def _message(
    settings: Settings,
    *,
    recipient: str,
    subject: str,
    display_name: str,
    action_label: str,
    action_link: str,
    expiry: str,
    explanation: str,
) -> EmailMessage:
    if not settings.smtp_configured:
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"Witscraft <{settings.smtp_from_email}>"
    message["To"] = recipient
    message.set_content(
        f"{display_name}，你好：\n\n{explanation}\n\n{action_label}：{action_link}\n\n"
        f"链接有效期为 {expiry}。"
    )
    message.add_alternative(
        """
        <div style="font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#24231f">
          <h2 style="margin-bottom:12px">Witscraft</h2>
          <p>{name}，你好：</p>
          <p>{explanation}</p>
          <p style="margin:24px 0">
            <a href="{link}" style="background:#167d78;color:#fff;text-decoration:none;padding:11px 18px;border-radius:6px">{label}</a>
          </p>
          <p style="font-size:13px;color:#6d6a62">链接有效期为 {expiry}。</p>
        </div>
        """.format(
            name=escape(display_name),
            explanation=escape(explanation),
            link=escape(action_link, quote=True),
            label=escape(action_label),
            expiry=escape(expiry),
        ),
        subtype="html",
    )
    return message


async def _send_message(settings: Settings, message: EmailMessage) -> None:
    try:
        await asyncio.to_thread(_send, settings, message)
    except Exception as error:
        raise EmailDeliveryError("SMTP delivery failed") from error


def _check_connection(settings: Settings) -> None:
    with _smtp_client(settings) as client:
        client.noop()


def _send(settings: Settings, message: EmailMessage) -> None:
    with _smtp_client(settings) as client:
        client.send_message(message)


def _smtp_client(settings: Settings) -> smtplib.SMTP_SSL:
    if not settings.smtp_configured:
        raise RuntimeError("SMTP is not configured")
    context = ssl.create_default_context()
    client = smtplib.SMTP_SSL(
        settings.smtp_host,
        settings.smtp_port,
        context=context,
        timeout=20,
    )
    try:
        client.login(settings.smtp_username, settings.smtp_password)
    except Exception:
        client.close()
        raise
    return client
