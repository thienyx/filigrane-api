from __future__ import annotations

from email_validator import EmailNotValidError, validate_email


def normalize_email(candidate: str) -> str | None:
    trimmed = candidate.strip().lower()
    if not trimmed:
        return None
    try:
        parsed = validate_email(trimmed, check_deliverability=False)
        return parsed.email.lower()
    except EmailNotValidError:
        return None
