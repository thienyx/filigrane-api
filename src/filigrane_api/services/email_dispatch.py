from __future__ import annotations

from typing import Protocol

import httpx

from filigrane_api.core.logging_config import get_logger


class EmailSender(Protocol):
    async def send_magic_link(
        self,
        *,
        to_email: str,
        link: str,
        ttl_minutes: int,
    ) -> None: ...


class ConsoleEmailSender:
    def __init__(self) -> None:
        self._log = get_logger(component="email")

    async def send_magic_link(
        self,
        *,
        to_email: str,
        link: str,
        ttl_minutes: int,
    ) -> None:
        self._log.warning(
            "magic_link_console_only",
            to=to_email,
            link=link,
            ttl_minutes=ttl_minutes,
            hint="FILIGRANE_RESEND_API_KEY not set — no email actually sent",
        )


class ResendEmailSender:
    def __init__(self, api_key: str, from_address: str) -> None:
        self._api_key = api_key
        self._from = from_address
        self._log = get_logger(component="email")

    async def send_magic_link(
        self,
        *,
        to_email: str,
        link: str,
        ttl_minutes: int,
    ) -> None:
        subject = "Filigrane sign-in link"
        minutes_note = (
            f"{ttl_minutes} minute" if ttl_minutes == 1 else f"{ttl_minutes} minutes"
        )
        html_body = (
            "<!DOCTYPE html><html><body>"
            "<p>Use this link to sign in to Filigrane. "
            f"If you did not request it, you can ignore this email.</p>"
            f'<p><a href="{link}">Continue</a></p>'
            f"<p>This link expires in {minutes_note}.</p>"
            "</body></html>"
        )
        text_body = (
            "Sign in to Filigrane (requested by you or someone with "
            "access to this address).\n\n"
            f"{link}\n\n"
            f"This link expires in {minutes_note}.\n"
        )
        payload = {
            "from": self._from,
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
            response = await client.post(
                "https://api.resend.com/emails",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()


def build_email_sender(*, api_key: str | None, from_address: str) -> EmailSender:
    if api_key:
        return ResendEmailSender(api_key=api_key, from_address=from_address)
    return ConsoleEmailSender()
