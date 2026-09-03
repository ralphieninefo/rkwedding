"""Tests for per-mailbox sync isolation and the visible sync-health record."""

import json

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import db_workflow
from app.config import Settings
from app.database import (
    LAST_REFRESH_KEY,
    SYNC_STATUS_KEY,
    Base,
    GoogleAccount,
    Venue,
    clear_sync_failure,
    dashboard_payload,
    get_system_state,
    set_system_state,
    sync_status_payload,
)
from app.google_auth import GoogleCredentialError, get_google_access_token

PERSONAL = {"id": 1, "email": "personal@example.com", "is_primary": False}
SHARED = {"id": 2, "email": "shared@example.com", "is_primary": True}
COUNTS = {
    "new_messages": 2,
    "sent_confirmed": 1,
    "replies_synthesized": 1,
    "attachments_mirrored": 0,
    "attachments_skipped": 0,
    "attachment_failures": 0,
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sync.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_workflow, "SessionLocal", factory)
    yield factory
    engine.dispose()


def _stored_status(factory) -> dict:
    with factory() as session:
        raw = get_system_state(session, SYNC_STATUS_KEY)
    assert raw is not None
    return json.loads(raw)


@pytest.mark.anyio
async def test_one_expired_mailbox_does_not_block_the_other(sessions, monkeypatch) -> None:
    reconciled: list[int] = []

    async def fake_reconcile(_settings, account_id, *, days):
        reconciled.append(account_id)
        if account_id == PERSONAL["id"]:
            raise GoogleCredentialError(PERSONAL["email"])
        return dict(COUNTS)

    monkeypatch.setattr(db_workflow, "list_google_accounts", lambda: [SHARED, PERSONAL])
    monkeypatch.setattr(db_workflow, "_reconcile_gmail_account", fake_reconcile)

    result = await db_workflow.reconcile_gmail_database(Settings(_env_file=None), days=30)

    assert reconciled == [SHARED["id"], PERSONAL["id"]]
    assert result["accounts_synced"] == [SHARED["email"]]
    assert result["accounts_failed"] == [
        {
            "email": PERSONAL["email"],
            "error": (
                "Google authorization for personal@example.com has expired or was "
                "revoked. Use “Add Gmail account” and choose that mailbox to reconnect it."
            ),
        }
    ]
    assert result["new_messages"] == 2
    assert result["last_refreshed_at"] is not None

    stored = _stored_status(sessions)
    by_email = {item["email"]: item for item in stored["accounts"]}
    assert by_email[SHARED["email"]]["status"] == "ok"
    assert by_email[SHARED["email"]]["error"] is None
    assert (
        by_email[SHARED["email"]]["last_checked_at"]
        <= by_email[SHARED["email"]]["last_success_at"]
        <= result["last_refreshed_at"]
    )
    assert by_email[PERSONAL["email"]]["status"] == "failed"
    assert by_email[PERSONAL["email"]]["last_success_at"] is None
    assert "reconnect" in by_email[PERSONAL["email"]]["error"]
    assert stored["failed_count"] == 1
    with sessions() as session:
        assert get_system_state(session, LAST_REFRESH_KEY) == result["last_refreshed_at"]


@pytest.mark.anyio
async def test_real_account_reconciliation_survives_a_revoked_token(
    sessions, monkeypatch
) -> None:
    """Exercise ``_reconcile_gmail_account`` itself with only Google faked."""
    with sessions() as session:
        session.add(Venue(name="Villa Test", email="info@villa.example"))
        session.commit()
    searched: list[str] = []

    async def fake_token(_settings, account_id):
        if account_id == PERSONAL["id"]:
            raise GoogleCredentialError(PERSONAL["email"])
        return "shared-access-token"

    class FakeGmail:
        def __init__(self, token, _user_id):
            assert token == "shared-access-token"

        async def search_message_ids(self, query, max_results=10):
            searched.append(query)
            return []

    monkeypatch.setattr(db_workflow, "list_google_accounts", lambda: [PERSONAL, SHARED])
    monkeypatch.setattr(db_workflow, "get_google_access_token", fake_token)
    monkeypatch.setattr(db_workflow, "GmailClient", FakeGmail)

    result = await db_workflow.reconcile_gmail_database(Settings(_env_file=None), days=30)

    assert [item["email"] for item in result["accounts_failed"]] == [PERSONAL["email"]]
    assert result["accounts_synced"] == [SHARED["email"]]
    assert searched and "info@villa.example" in searched[0]
    with sessions() as session:
        assert get_system_state(session, LAST_REFRESH_KEY) == result["last_refreshed_at"]


@pytest.mark.anyio
async def test_full_chain_from_google_refresh_error_to_dashboard_status(
    sessions, monkeypatch
) -> None:
    """Wire the real OAuth loader, token lookup, and reconciliation together."""
    from google.auth.exceptions import RefreshError

    from app import gmail_oauth

    monkeypatch.setattr(gmail_oauth, "SessionLocal", sessions)
    with sessions() as session:
        session.add_all([
            GoogleAccount(email=SHARED["email"], token_json='{"token":"fresh"}', is_primary=True),
            GoogleAccount(email=PERSONAL["email"], token_json='{"token":"stale"}'),
        ])
        session.commit()

    class FakeCredential:
        def __init__(self, info):
            self.token = info["token"]
            self.expired = info["token"] == "stale"
            self.refresh_token = "refresh"
            self.valid = not self.expired

        def refresh(self, _request):
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

        def to_json(self):
            return json.dumps({"token": self.token})

    class FakeCredentials:
        @staticmethod
        def from_authorized_user_info(info, _scopes):
            return FakeCredential(info)

    class FakeGmail:
        def __init__(self, token, _user_id):
            assert token == "fresh"

        async def search_message_ids(self, query, max_results=10):
            return []

    monkeypatch.setattr(gmail_oauth, "Credentials", FakeCredentials)
    monkeypatch.setattr(db_workflow, "GmailClient", FakeGmail)

    result = await db_workflow.reconcile_gmail_database(Settings(_env_file=None), days=30)

    assert result["accounts_synced"] == [SHARED["email"]]
    assert result["accounts_failed"][0]["email"] == PERSONAL["email"]
    assert "personal@example.com" in result["accounts_failed"][0]["error"]
    with sessions() as session:
        payload = dashboard_payload(session)
    failed = [item for item in payload["sync_status"]["accounts"] if item["status"] == "failed"]
    assert [item["email"] for item in failed] == [PERSONAL["email"]]
    assert payload["last_refreshed_at"] == result["last_refreshed_at"]


@pytest.mark.anyio
async def test_total_failure_keeps_the_previous_successful_checkpoint(
    sessions, monkeypatch
) -> None:
    with sessions() as session:
        set_system_state(session, LAST_REFRESH_KEY, "2026-09-01T10:00:00+00:00")
        set_system_state(
            session,
            SYNC_STATUS_KEY,
            json.dumps({
                "completed_at": "2026-09-01T10:00:00+00:00",
                "accounts": [
                    {
                        "email": SHARED["email"],
                        "status": "ok",
                        "last_success_at": "2026-09-01T10:00:00+00:00",
                    }
                ],
            }),
        )

    async def fake_reconcile(_settings, _account_id, *, days):
        request = httpx.Request("GET", "https://gmail.googleapis.com/gmail/v1/users/me/messages")
        raise httpx.HTTPStatusError(
            "rate limited", request=request, response=httpx.Response(429, request=request)
        )

    monkeypatch.setattr(db_workflow, "list_google_accounts", lambda: [SHARED])
    monkeypatch.setattr(db_workflow, "_reconcile_gmail_account", fake_reconcile)

    result = await db_workflow.reconcile_gmail_database(Settings(_env_file=None))

    assert result["accounts_synced"] == []
    assert result["accounts_failed"][0]["error"] == (
        "Gmail is rate limiting this mailbox; the next run will retry."
    )
    assert result["last_refreshed_at"] == "2026-09-01T10:00:00+00:00"
    stored = _stored_status(sessions)
    assert stored["accounts"][0]["status"] == "failed"
    # The last successful time survives a failed run so the UI can show it.
    assert stored["accounts"][0]["last_success_at"] == "2026-09-01T10:00:00+00:00"
    with sessions() as session:
        assert get_system_state(session, LAST_REFRESH_KEY) == "2026-09-01T10:00:00+00:00"


@pytest.mark.anyio
async def test_unexpected_database_errors_still_fail_loudly(sessions, monkeypatch) -> None:
    async def fake_reconcile(_settings, _account_id, *, days):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(db_workflow, "list_google_accounts", lambda: [SHARED])
    monkeypatch.setattr(db_workflow, "_reconcile_gmail_account", fake_reconcile)

    with pytest.raises(RuntimeError, match="database exploded"):
        await db_workflow.reconcile_gmail_database(Settings(_env_file=None))


@pytest.mark.anyio
async def test_access_token_lookup_keeps_the_reconnect_message(monkeypatch) -> None:
    def revoked(_account_id):
        raise GoogleCredentialError(PERSONAL["email"])

    monkeypatch.setattr("app.gmail_oauth.load_credentials", revoked)

    with pytest.raises(GoogleCredentialError, match="personal@example.com"):
        await get_google_access_token(Settings(_env_file=None), PERSONAL["id"])


@pytest.mark.anyio
async def test_missing_stored_token_for_a_mailbox_is_a_reconnect_problem(
    monkeypatch,
) -> None:
    def missing(_account_id):
        raise FileNotFoundError("No Google OAuth credential is stored in the database.")

    monkeypatch.setattr("app.gmail_oauth.load_credentials", missing)
    monkeypatch.setattr("app.gmail_oauth.account_email", lambda _id: SHARED["email"])

    with pytest.raises(GoogleCredentialError, match="shared@example.com"):
        await get_google_access_token(Settings(_env_file=None), SHARED["id"])


@pytest.mark.anyio
async def test_legacy_single_account_path_still_falls_back_to_env_refresh(
    monkeypatch,
) -> None:
    """Without an account id, an unusable stored token may still use env settings."""
    def revoked(_account_id):
        raise GoogleCredentialError(None)

    async def fake_post(self, _url, data):
        assert data["refresh_token"] == "env-refresh"
        return httpx.Response(
            200,
            json={"access_token": "env-access"},
            request=httpx.Request("POST", "https://oauth2.googleapis.com/token"),
        )

    monkeypatch.setattr("app.gmail_oauth.load_credentials", revoked)
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    settings = Settings(
        _env_file=None,
        google_client_id="client",
        google_client_secret="secret",
        google_refresh_token="env-refresh",
    )

    assert await get_google_access_token(settings, None) == "env-access"
    with pytest.raises(GoogleCredentialError):
        await get_google_access_token(Settings(_env_file=None), None)


def test_sync_error_messages_never_echo_upstream_bodies() -> None:
    request = httpx.Request("GET", "https://gmail.googleapis.com/x")
    forbidden = httpx.HTTPStatusError(
        "secret-body", request=request, response=httpx.Response(403, request=request)
    )
    assert "secret-body" not in db_workflow.sync_error_message(forbidden)
    assert "403" in db_workflow.sync_error_message(forbidden)
    assert "retry" in db_workflow.sync_error_message(httpx.ConnectError("boom"))
    assert "KeyError" in db_workflow.sync_error_message(KeyError("data"))


def test_dashboard_payload_exposes_only_safe_sync_fields(sessions) -> None:
    with sessions() as session:
        set_system_state(
            session,
            SYNC_STATUS_KEY,
            json.dumps({
                "completed_at": "2026-09-03T09:00:00+00:00",
                "accounts": [
                    {
                        "email": PERSONAL["email"],
                        "is_primary": False,
                        "status": "failed",
                        "error": "Google authorization for personal@example.com has expired.",
                        "last_success_at": "2026-08-30T09:00:00+00:00",
                        "last_checked_at": "2026-09-03T09:00:00+00:00",
                        "token_json": "must-not-leak",
                    }
                ],
            }),
        )
        payload = dashboard_payload(session)

    status = payload["sync_status"]
    assert status["failed_count"] == 1
    assert status["accounts"][0]["email"] == PERSONAL["email"]
    assert status["accounts"][0]["last_success_at"] == "2026-08-30T09:00:00+00:00"
    assert "token_json" not in status["accounts"][0]
    assert "must-not-leak" not in json.dumps(payload)


def test_unreadable_sync_status_does_not_break_the_dashboard(sessions) -> None:
    with sessions() as session:
        assert dashboard_payload(session)["sync_status"] is None
        set_system_state(session, SYNC_STATUS_KEY, "not json")
        assert sync_status_payload(session) is None
        assert dashboard_payload(session)["sync_status"] is None
        set_system_state(session, SYNC_STATUS_KEY, json.dumps({"accounts": None}))
        assert dashboard_payload(session)["sync_status"]["accounts"] == []


def test_reconnecting_a_mailbox_clears_its_recorded_failure(sessions) -> None:
    with sessions() as session:
        set_system_state(
            session,
            SYNC_STATUS_KEY,
            json.dumps({
                "completed_at": "2026-09-03T09:00:00+00:00",
                "accounts": [
                    {"email": SHARED["email"], "status": "ok", "error": None},
                    {"email": PERSONAL["email"], "status": "failed", "error": "Expired."},
                ],
                "failed_count": 1,
            }),
        )
        assert clear_sync_failure(session, "Personal@Example.com") is True
        status = sync_status_payload(session)
        assert status["failed_count"] == 0
        by_email = {item["email"]: item for item in status["accounts"]}
        assert by_email[PERSONAL["email"]]["status"] == "reconnected"
        assert by_email[PERSONAL["email"]]["error"] is None
        assert by_email[SHARED["email"]]["status"] == "ok"
        assert clear_sync_failure(session, "unknown@example.com") is False


def test_oauth_callback_clears_the_failure_for_that_mailbox(tmp_path, monkeypatch) -> None:
    from app import gmail_oauth

    engine = create_engine(f"sqlite:///{tmp_path / 'oauth.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(gmail_oauth, "SessionLocal", factory)
    with factory() as session:
        session.add(GoogleAccount(email=PERSONAL["email"], token_json='{"token":"stale"}'))
        session.commit()
        set_system_state(
            session,
            SYNC_STATUS_KEY,
            json.dumps({
                "accounts": [
                    {"email": PERSONAL["email"], "status": "failed", "error": "Expired."}
                ]
            }),
        )

    class FakeCredentials:
        def to_json(self):
            return '{"token":"fresh"}'

    class FakeFlow:
        def __init__(self, **_kwargs):
            self.credentials = FakeCredentials()
            self.redirect_uri = None

        def fetch_token(self, **_kwargs):
            return None

    monkeypatch.setattr(gmail_oauth, "_flow", lambda **kwargs: FakeFlow(**kwargs))
    monkeypatch.setattr(gmail_oauth, "_profile_email", lambda _credentials: PERSONAL["email"])

    account = gmail_oauth.finish_authorization(
        "https://app.example/auth/google/callback",
        "https://app.example/auth/google/callback?code=x&state=s",
        "s",
        "verifier",
    )

    assert account["email"] == PERSONAL["email"]
    with factory() as session:
        assert session.scalar(select(GoogleAccount.token_json)) == '{"token":"fresh"}'
        status = sync_status_payload(session)
    assert status["failed_count"] == 0
    assert status["accounts"][0]["status"] == "reconnected"
