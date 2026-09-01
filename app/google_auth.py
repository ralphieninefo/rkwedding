"""Server-side Google OAuth token refresh."""

import httpx

from app.config import Settings


async def get_google_access_token(
    settings: Settings, account_id: int | None = None
) -> str:
    """Use a local access token or exchange a refresh token in production."""
    if account_id is None and settings.google_access_token:
        return settings.google_access_token.get_secret_value()
    try:
        from app.gmail_oauth import load_credentials

        credentials = load_credentials(account_id)
        if credentials.token:
            return credentials.token
    except (FileNotFoundError, ValueError):
        pass
    if account_id is not None or not (
        settings.google_client_id
        and settings.google_client_secret
        and settings.google_refresh_token
    ):
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
