"""Server-side Google OAuth token refresh."""

import httpx

from app.config import Settings


class GoogleCredentialError(ValueError):
    """The stored Google credential no longer works; the owner must reconnect it.

    Raised instead of Google's raw refresh failure so that the dashboard can
    name the mailbox and explain the recovery step without leaking token data.
    """

    def __init__(self, email: str | None = None) -> None:
        self.email = email
        mailbox = email or "the connected Google account"
        super().__init__(
            f"Google authorization for {mailbox} has expired or was revoked. "
            "Use “Add Gmail account” and choose that mailbox to reconnect it."
        )


async def get_google_access_token(
    settings: Settings, account_id: int | None = None
) -> str:
    """Use a local access token or exchange a refresh token in production."""
    if account_id is None and settings.google_access_token:
        return settings.google_access_token.get_secret_value()
    from app.gmail_oauth import account_email, load_credentials

    env_refresh_configured = bool(
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_refresh_token
    )
    try:
        credentials = load_credentials(account_id)
        if credentials.token:
            return credentials.token
    except GoogleCredentialError:
        # A revoked or expired refresh token is a reconnect problem, not a
        # missing-configuration problem; keep the mailbox-specific message.
        # The legacy single-account path may still fall back to environment
        # refresh settings exactly as before.
        if account_id is not None or not env_refresh_configured:
            raise
    except (FileNotFoundError, ValueError) as exc:
        if account_id is not None:
            # The stored token for this specific mailbox is missing or
            # unreadable; only reconnecting that mailbox can fix it.
            raise GoogleCredentialError(account_email(account_id)) from exc
    if account_id is not None:
        raise GoogleCredentialError(account_email(account_id))
    if not env_refresh_configured:
        raise ValueError("Google OAuth credentials are incomplete.")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "refresh_token": settings.google_refresh_token.get_secret_value(),
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
    return response.json()["access_token"]
