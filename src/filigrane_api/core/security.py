from __future__ import annotations

import hashlib
import secrets


def mint_opaque_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def hash_secret(raw_token: str) -> str:
    encoded = raw_token.encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return secrets.compare_digest(left, right)
