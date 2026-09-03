"""Tests for the App Platform Gmail synchronization job."""

import json

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
        return {
            "new_messages": 2,
            "accounts_synced": ["shared@example.com"],
            "accounts_failed": [],
            "last_refreshed_at": "2026-08-30T07:15:00Z",
        }

    monkeypatch.setattr(scheduled_sync, "init_database", lambda: None)
    monkeypatch.setattr(scheduled_sync, "gmail_connected", lambda: True)
    monkeypatch.setattr(scheduled_sync, "reconcile_gmail_database", fake_reconcile)

    result = await scheduled_sync.sync_once()

    assert captured["days"] == 30
    assert result["status"] == "completed"
    assert result["new_messages"] == 2


@pytest.mark.anyio
async def test_scheduled_sync_reports_partial_mailbox_failure(monkeypatch) -> None:
    async def fake_reconcile(_settings, *, days):
        return {
            "new_messages": 1,
            "accounts_synced": ["shared@example.com"],
            "accounts_failed": [
                {"email": "personal@example.com", "error": "Reconnect it."}
            ],
            "last_refreshed_at": "2026-09-03T07:15:00Z",
        }

    monkeypatch.setattr(scheduled_sync, "init_database", lambda: None)
    monkeypatch.setattr(scheduled_sync, "gmail_connected", lambda: True)
    monkeypatch.setattr(scheduled_sync, "reconcile_gmail_database", fake_reconcile)

    result = await scheduled_sync.sync_once()

    assert result["status"] == "completed_with_errors"
    assert result["accounts_failed"][0]["email"] == "personal@example.com"


def test_scheduled_sync_exits_nonzero_only_when_no_mailbox_synced(
    monkeypatch, capsys
) -> None:
    async def total_failure():
        return {
            "status": "failed",
            "accounts_synced": [],
            "accounts_failed": [{"email": "shared@example.com", "error": "Reconnect it."}],
        }

    async def partial():
        return {"status": "completed_with_errors", "accounts_synced": ["a@example.com"]}

    monkeypatch.setattr(scheduled_sync, "sync_once", total_failure)
    with pytest.raises(SystemExit) as excinfo:
        scheduled_sync.main()
    assert excinfo.value.code == 1
    logged = json.loads(capsys.readouterr().out.strip())
    assert logged["status"] == "failed"

    monkeypatch.setattr(scheduled_sync, "sync_once", partial)
    scheduled_sync.main()
    assert json.loads(capsys.readouterr().out.strip())["status"] == "completed_with_errors"
