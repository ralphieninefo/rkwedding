"""Tests for the App Platform Gmail synchronization job."""

import pytest

from app import scheduled_sync


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_scheduled_sync_skips_until_google_is_connected(monkeypatch) -> None:
    monkeypatch.setattr(scheduled_sync, "init_database", lambda: None)
    monkeypatch.setattr(scheduled_sync, "gmail_connected", lambda: False)

    result = await scheduled_sync.sync_once()

    assert result == {
        "status": "skipped",
        "reason": "Google is not connected.",
    }


@pytest.mark.anyio
async def test_scheduled_sync_reconciles_recent_gmail(monkeypatch) -> None:
    captured = {}

    async def fake_reconcile(_settings, *, days):
        captured["days"] = days
        return {"new_messages": 2, "last_refreshed_at": "2026-08-30T07:15:00Z"}

    monkeypatch.setattr(scheduled_sync, "init_database", lambda: None)
    monkeypatch.setattr(scheduled_sync, "gmail_connected", lambda: True)
    monkeypatch.setattr(scheduled_sync, "reconcile_gmail_database", fake_reconcile)

    result = await scheduled_sync.sync_once()

    assert captured["days"] == 30
    assert result["status"] == "completed"
    assert result["new_messages"] == 2
