"""Tests for private dashboard sessions and Gmail account approval."""

from pydantic import SecretStr

from app.config import Settings
from app.gmail_oauth import account_is_approved
from app.session_auth import create_session_cookie, valid_session_cookie


def test_signed_session_cookie_round_trip() -> None:
    password = SecretStr("correct horse battery staple")
    cookie = create_session_cookie("raph", password, ttl_hours=1)

    assert valid_session_cookie(cookie, "raph", password)
    assert not valid_session_cookie(cookie, "other-user", password)
    assert not valid_session_cookie(cookie + "tampered", "raph", password)


def test_google_account_allowlist_is_fail_closed(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        google_allowed_emails="raph@example.com, shared@example.com",
    )
    monkeypatch.setattr("app.gmail_oauth.get_settings", lambda: settings)

    assert account_is_approved("SHARED@example.com", already_connected=False)
    assert account_is_approved("legacy@example.com", already_connected=True)
    assert not account_is_approved("stranger@example.com", already_connected=False)
