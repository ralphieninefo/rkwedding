"""Google Sheets integration boundary."""

from typing import Any


async def get_venue(venue_name: str) -> dict[str, Any]:
    """Fetch a venue row once Google authentication is configured."""
    raise NotImplementedError("Google Sheets integration is planned for a later phase.")


async def update_venue(venue_name: str, updates: dict[str, Any]) -> None:
    """Update a venue row once Google authentication is configured."""
    raise NotImplementedError("Google Sheets integration is planned for a later phase.")
