"""Small signed-cookie authentication for the private control center."""

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from pydantic import SecretStr

SESSION_COOKIE = "rkwedding_session"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signature(payload: str, password: SecretStr) -> str:
    return hmac.new(
        password.get_secret_value().encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def create_session_cookie(
    username: str, password: SecretStr, *, ttl_hours: int
) -> str:
    expires = datetime.now(UTC) + timedelta(hours=ttl_hours)
    payload = _encode(f"{username}|{int(expires.timestamp())}".encode())
    return f"{payload}.{_signature(payload, password)}"


def valid_session_cookie(
    value: str | None,
    username: str,
    password: SecretStr,
) -> bool:
    if not value or "." not in value:
        return False
    payload, supplied_signature = value.rsplit(".", 1)
    if not hmac.compare_digest(_signature(payload, password), supplied_signature):
        return False
    try:
        padded = payload + "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
        stored_username, expires_at = decoded.rsplit("|", 1)
        expires_timestamp = int(expires_at)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(stored_username, username) and (
        expires_timestamp > int(datetime.now(UTC).timestamp())
    )
