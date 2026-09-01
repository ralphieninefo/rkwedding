"""Local read-only Google OAuth flow for the Gmail tracker."""

import json
import os
import secrets
from pathlib import Path

import httpx
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select, update

from app.config import get_settings
from app.database import (
    GoogleAccount,
    Message,
    Outreach,
    SessionLocal,
    get_system_state,
    set_system_state,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLIENT_SECRET_PATH = DATA_DIR / "google_client_secret.json"
TOKEN_PATH = DATA_DIR / "google_token.json"
TOKEN_STATE_KEY = "google_oauth_token"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _client_config() -> dict[str, object] | None:
    configured_json = get_settings().google_client_secret_json
    if not configured_json:
        return None
    parsed = json.loads(configured_json.get_secret_value())
    if not isinstance(parsed, dict):
        raise TypeError("GOOGLE_CLIENT_SECRET_JSON must contain a JSON object.")
    return parsed


def _flow(**kwargs: object) -> Flow:
    client_config = _client_config()
    if client_config is not None:
        return Flow.from_client_config(client_config, scopes=SCOPES, **kwargs)
    return Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), scopes=SCOPES, **kwargs
    )


def _legacy_token() -> str | None:
    """Return the original single-account token during migration."""
    with SessionLocal() as session:
        token_json = get_system_state(session, TOKEN_STATE_KEY)
        if token_json is not None:
            return token_json
        if not TOKEN_PATH.is_file():
            return None
        token_json = TOKEN_PATH.read_text(encoding="utf-8")
        set_system_state(session, TOKEN_STATE_KEY, token_json)
        return token_json


def _profile_email(credentials: Credentials) -> str:
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    with httpx.Client(timeout=20) as client:
        response = client.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {credentials.token}"},
        )
        response.raise_for_status()
    email = response.json().get("emailAddress", "").strip().casefold()
    if not email:
        raise ValueError("Google did not return an account email address.")
    return email


def _migrate_legacy_account() -> None:
    """Import the existing connected Gmail into the multi-account table once."""
    with SessionLocal() as session:
        if session.scalar(select(GoogleAccount.id).limit(1)) is not None:
            return
    token_json = _legacy_token()
    if token_json is None:
        return
    try:
        credentials = Credentials.from_authorized_user_info(
            json.loads(token_json), SCOPES
        )
        email = _profile_email(credentials)
    except (AttributeError, GoogleAuthError, ValueError, httpx.HTTPError):
        # Keep the legacy credential usable if it cannot be identified yet.
        return
    with SessionLocal() as session:
        account = GoogleAccount(
            email=email,
            token_json=credentials.to_json(),
            is_primary=True,
        )
        session.add(account)
        session.flush()
        session.execute(
            update(Outreach)
            .where(Outreach.gmail_account_id.is_(None))
            .values(gmail_account_id=account.id)
        )
        session.execute(
            update(Message)
            .where(Message.gmail_account_id.is_(None))
            .values(gmail_account_id=account.id)
        )
        session.commit()


def list_google_accounts() -> list[dict[str, object]]:
    _migrate_legacy_account()
    with SessionLocal() as session:
        accounts = session.scalars(
            select(GoogleAccount).order_by(
                GoogleAccount.is_primary.desc(), GoogleAccount.connected_at
            )
        ).all()
        return [
            {
                "id": account.id,
                "email": account.email,
                "is_primary": account.is_primary,
            }
            for account in accounts
        ]


def default_google_account_id() -> int | None:
    """Return the account used for new outreach."""
    stored = _stored_token()
    return stored[1] if stored else None


def _stored_token(account_id: int | None = None) -> tuple[str, int | None] | None:
    _migrate_legacy_account()
    with SessionLocal() as session:
        if account_id is not None:
            account = session.get(GoogleAccount, account_id)
        else:
            account = session.scalar(
                select(GoogleAccount).order_by(
                    GoogleAccount.is_primary.desc(), GoogleAccount.connected_at
                )
            )
        if account is not None:
            return account.token_json, account.id
    token_json = _legacy_token()
    return (token_json, None) if token_json is not None else None


def _store_token(token_json: str, account_id: int | None) -> None:
    if account_id is None:
        with SessionLocal() as session:
            set_system_state(session, TOKEN_STATE_KEY, token_json)
        return
    with SessionLocal() as session:
        account = session.get(GoogleAccount, account_id)
        if account is None:
            raise ValueError("Connected Google account no longer exists.")
        account.token_json = token_json
        session.commit()


def oauth_setup_ready() -> bool:
    return _client_config() is not None or CLIENT_SECRET_PATH.is_file()


def gmail_connected() -> bool:
    return _stored_token() is not None


def authorization_url(redirect_uri: str) -> tuple[str, str, str]:
    """Create a Google consent URL and its one-time PKCE browser values."""
    if not oauth_setup_ready():
        raise FileNotFoundError(CLIENT_SECRET_PATH)
    state = secrets.token_urlsafe(32)
    flow = _flow(state=state)
    flow.redirect_uri = redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent select_account",
    )
    if not flow.code_verifier:
        raise ValueError("Google OAuth did not create a PKCE verifier.")
    return url, state, flow.code_verifier


def finish_authorization(
    redirect_uri: str,
    authorization_response: str,
    state: str,
    code_verifier: str,
) -> dict[str, object]:
    """Exchange Google's callback and store the refreshable token in the DB."""
    flow = _flow(
        state=state,
        code_verifier=code_verifier,
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = redirect_uri
    if redirect_uri.startswith("http://127.0.0.1"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow.fetch_token(authorization_response=authorization_response)
    email = _profile_email(flow.credentials)
    token_json = flow.credentials.to_json()
    with SessionLocal() as session:
        account = session.scalar(
            select(GoogleAccount).where(GoogleAccount.email == email)
        )
        if account is None:
            is_primary = session.scalar(
                select(GoogleAccount.id).limit(1)
            ) is None
            account = GoogleAccount(
                email=email,
                token_json=token_json,
                is_primary=is_primary,
            )
            session.add(account)
        else:
            account.token_json = token_json
        session.commit()
        return {
            "id": account.id,
            "email": account.email,
            "is_primary": account.is_primary,
        }


def load_credentials(account_id: int | None = None) -> Credentials:
    """Load and refresh the database-backed Gmail credential."""
    stored = _stored_token(account_id)
    if stored is None:
        raise FileNotFoundError("No Google OAuth credential is stored in the database.")
    token_json, stored_account_id = stored
    credentials = Credentials.from_authorized_user_info(
        json.loads(token_json), SCOPES
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _store_token(credentials.to_json(), stored_account_id)
    elif stored_account_id is None:
        # Preserve any refresh performed while identifying a legacy account.
        _store_token(credentials.to_json(), None)
    if not credentials.valid:
        raise ValueError("Google authorization is no longer valid.")
    return credentials
