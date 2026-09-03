"""Tests for durable Google OAuth credential storage."""

import json

import pytest
from google.auth.exceptions import RefreshError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import gmail_oauth
from app.config import Settings
from app.database import Base, GoogleAccount, get_system_state, set_system_state
from app.google_auth import GoogleCredentialError


def _temporary_sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'oauth.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(gmail_oauth, "SessionLocal", sessions)
    monkeypatch.setattr(gmail_oauth, "TOKEN_PATH", tmp_path / "google_token.json")
    return sessions


def test_gmail_connected_uses_database_state(tmp_path, monkeypatch) -> None:
    sessions = _temporary_sessions(tmp_path, monkeypatch)

    assert gmail_oauth.gmail_connected() is False

    with sessions() as session:
        set_system_state(session, gmail_oauth.TOKEN_STATE_KEY, '{"token":"stored"}')

    assert gmail_oauth.gmail_connected() is True


def test_legacy_token_is_imported_only_when_database_is_empty(
    tmp_path, monkeypatch
) -> None:
    sessions = _temporary_sessions(tmp_path, monkeypatch)
    gmail_oauth.TOKEN_PATH.write_text('{"token":"legacy"}', encoding="utf-8")

    assert gmail_oauth.gmail_connected() is True

    with sessions() as session:
        assert get_system_state(session, gmail_oauth.TOKEN_STATE_KEY) == (
            '{"token":"legacy"}'
        )
        set_system_state(session, gmail_oauth.TOKEN_STATE_KEY, '{"token":"database"}')
    gmail_oauth.TOKEN_PATH.write_text('{"token":"changed"}', encoding="utf-8")

    assert gmail_oauth._stored_token() == ('{"token":"database"}', None)
    with sessions() as session:
        assert get_system_state(session, gmail_oauth.TOKEN_STATE_KEY) == (
            '{"token":"database"}'
        )


def test_refresh_persists_updated_credential(tmp_path, monkeypatch) -> None:
    sessions = _temporary_sessions(tmp_path, monkeypatch)
    with sessions() as session:
        set_system_state(session, gmail_oauth.TOKEN_STATE_KEY, '{"token":"old"}')

    class FakeCredential:
        expired = True
        refresh_token = "refresh-token"
        valid = True

        def refresh(self, _request) -> None:
            self.expired = False

        def to_json(self) -> str:
            return json.dumps({"token": "refreshed"})

    credential = FakeCredential()

    class FakeCredentials:
        @staticmethod
        def from_authorized_user_info(_info, _scopes):
            return credential

    monkeypatch.setattr(gmail_oauth, "Credentials", FakeCredentials)

    assert gmail_oauth.load_credentials() is credential
    with sessions() as session:
        assert json.loads(
            get_system_state(session, gmail_oauth.TOKEN_STATE_KEY)
        ) == {"token": "refreshed"}


def test_revoked_refresh_token_names_the_mailbox_to_reconnect(
    tmp_path, monkeypatch
) -> None:
    sessions = _temporary_sessions(tmp_path, monkeypatch)
    with sessions() as session:
        account = GoogleAccount(
            email="personal@example.com",
            token_json='{"token":"stale"}',
            is_primary=False,
        )
        session.add(account)
        session.commit()
        account_id = account.id

    class FakeCredential:
        expired = True
        refresh_token = "refresh-token"
        valid = False

        def refresh(self, _request) -> None:
            raise RefreshError("invalid_grant: Token has been expired or revoked.")

        def to_json(self) -> str:
            raise AssertionError("A failed refresh must not overwrite the stored token.")

    class FakeCredentials:
        @staticmethod
        def from_authorized_user_info(_info, _scopes):
            return FakeCredential()

    monkeypatch.setattr(gmail_oauth, "Credentials", FakeCredentials)

    with pytest.raises(GoogleCredentialError) as excinfo:
        gmail_oauth.load_credentials(account_id)

    assert excinfo.value.email == "personal@example.com"
    assert "personal@example.com" in str(excinfo.value)
    assert "Add Gmail account" in str(excinfo.value)
    assert "invalid_grant" not in str(excinfo.value)
    with sessions() as session:
        assert session.get(GoogleAccount, account_id).token_json == '{"token":"stale"}'


def test_client_secret_json_is_preferred_over_local_file(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        google_client_secret_json='{"web":{"client_id":"hosted-client"}}',
    )
    monkeypatch.setattr(gmail_oauth, "get_settings", lambda: settings)

    captured = {}

    class FakeFlow:
        @staticmethod
        def from_client_config(client_config, **kwargs):
            captured["config"] = client_config
            captured["kwargs"] = kwargs
            return "flow-from-json"

        @staticmethod
        def from_client_secrets_file(*_args, **_kwargs):
            raise AssertionError("The client file fallback should not be used.")

    monkeypatch.setattr(gmail_oauth, "Flow", FakeFlow)

    assert gmail_oauth.oauth_setup_ready() is True
    assert gmail_oauth._flow(state="state") == "flow-from-json"
    assert captured["config"]["web"]["client_id"] == "hosted-client"


def test_oauth_requests_only_gmail_scopes() -> None:
    assert gmail_oauth.SCOPES == [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
    ]
