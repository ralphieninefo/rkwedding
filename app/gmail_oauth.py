"""Local read-only Google OAuth flow for the Gmail tracker."""

import os
import secrets
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
CLIENT_SECRET_PATH = DATA_DIR / "google_client_secret.json"
TOKEN_PATH = DATA_DIR / "google_token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_pending_states: set[str] = set()


def oauth_setup_ready() -> bool:
    return CLIENT_SECRET_PATH.is_file()


def gmail_connected() -> bool:
    return TOKEN_PATH.is_file()


def authorization_url(redirect_uri: str) -> str:
    """Create a Google consent URL and remember its one-time state."""
    if not oauth_setup_ready():
        raise FileNotFoundError(CLIENT_SECRET_PATH)
    state = secrets.token_urlsafe(32)
    _pending_states.add(state)
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), scopes=SCOPES, state=state
    )
    flow.redirect_uri = redirect_uri
    url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url


def finish_authorization(
    redirect_uri: str,
    authorization_response: str,
    state: str,
) -> None:
    """Exchange Google's callback and store the refreshable token locally."""
    if state not in _pending_states:
        raise ValueError("Invalid or expired OAuth state.")
    _pending_states.remove(state)
    flow = Flow.from_client_secrets_file(
        str(CLIENT_SECRET_PATH), scopes=SCOPES, state=state
    )
    flow.redirect_uri = redirect_uri
    if redirect_uri.startswith("http://127.0.0.1"):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow.fetch_token(authorization_response=authorization_response)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
    TOKEN_PATH.chmod(0o600)


def load_credentials() -> Credentials:
    """Load and refresh the locally stored read-only Gmail credential."""
    if not TOKEN_PATH.is_file():
        raise FileNotFoundError(TOKEN_PATH)
    credentials = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        TOKEN_PATH.write_text(credentials.to_json(), encoding="utf-8")
        TOKEN_PATH.chmod(0o600)
    if not credentials.valid:
        raise ValueError("Google authorization is no longer valid.")
    return credentials
