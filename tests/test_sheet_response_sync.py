"""Tests for deterministic Gmail-to-Sheet response tracking."""

from typing import Any

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.sheet_response_sync import sync_gmail_responses_to_sheet


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeSheets:
    updates: list[tuple[str, int, dict[str, Any]]] = []

    def __init__(self, _token: str, _spreadsheet_id: str) -> None:
        self.updates = []
        FakeSheets.updates = self.updates

    async def get_rows(self, _sheet: str) -> list[dict[str, str]]:
        return [
            {
                "_row_number": "2",
                "Venue": "Villa Test",
                "Email": "events@villa.test",
            }
        ]

    async def update_row(
        self, sheet: str, row_number: int, updates: dict[str, Any]
    ) -> None:
        self.updates.append((sheet, row_number, updates))


@pytest.mark.anyio
async def test_response_sync_updates_exact_email_match(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "app.sheet_response_sync.find_recent_responses",
        lambda: (
            "couple@example.com",
            3,
            [
                {
                    "thread_id": "thread-1",
                    "message_id": "message-1",
                    "sender_name": "Villa Test",
                    "sender_email": "events@villa.test",
                    "subject": "Re: Wedding",
                    "received_at": "2026-08-29T20:00:00+00:00",
                    "snippet": "Thank you for your inquiry.",
                }
            ],
        ),
    )

    async def fake_token(_settings: Settings) -> str:
        return "token"

    monkeypatch.setattr("app.sheet_response_sync.get_google_access_token", fake_token)
    monkeypatch.setattr("app.sheet_response_sync.GoogleSheetsClient", FakeSheets)
    settings = Settings(
        google_access_token=SecretStr("token"),
        google_spreadsheet_id="sheet-1",
    )

    result = await sync_gmail_responses_to_sheet(settings)

    assert result["venues_updated"] == 1
    assert FakeSheets.updates[0][1] == 2
    assert FakeSheets.updates[0][2]["Status"] == "Responded"
    assert FakeSheets.updates[0][2]["Response Received"] == "Yes"
