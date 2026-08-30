"""Tests for durable Google OAuth credential storage."""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import gmail_oauth
from app.database import Base, get_system_state, set_system_state


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
