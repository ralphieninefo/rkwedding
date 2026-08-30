"""Local read-only Google OAuth flow for the Gmail tracker."""

import json
import os
import secrets
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import get_settings
from app.database import SessionLocal, get_system_state, set_system_state

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


def _stored_token() -> str | None:
    """Return the DB credential, importing a legacy token file once if needed."""
    with SessionLocal() as session:
        token_json = get_system_state(session, TOKEN_STATE_KEY)
        if token_json is not None:
            return token_json
        if not TOKEN_PATH.is_file():
            return None
        token_json = TOKEN_PATH.read_text(encoding="utf-8")
        set_system_state(session, TOKEN_STATE_KEY, token_json)
        return token_json


def _store_token(token_json: str) -> None:
    with SessionLocal() as session:
        set_system_state(session, TOKEN_STATE_KEY, token_json)


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
        prompt="consent",
    )
    if not flow.code_verifier:
        raise ValueError("Google OAuth did not create a PKCE verifier.")
    return url, state, flow.code_verifier


def finish_authorization(
    redirect_uri: str,
    authorization_response: str,
    state: str,
    code_verifier: str,
) -> None:
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
    _store_token(flow.credentials.to_json())


def load_credentials() -> Credentials:
    """Load and refresh the database-backed Gmail credential."""
    token_json = _stored_token()
    if token_json is None:
        raise FileNotFoundError("No Google OAuth credential is stored in the database.")
    credentials = Credentials.from_authorized_user_info(
        json.loads(token_json), SCOPES
    )
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _store_token(credentials.to_json())
    if not credentials.valid:
        raise ValueError("Google authorization is no longer valid.")
    return credentials
