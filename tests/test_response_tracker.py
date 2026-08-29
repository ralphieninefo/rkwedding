"""Tests for local response tracking and Gmail thread detection."""

from pathlib import Path
from typing import Any

import app.response_tracker as response_tracker
from app.gmail_sync import find_recent_responses, sync_recent_responses


class FakeRequest:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def execute(self) -> dict[str, Any]:
        return self.value


class FakeThreads:
    def __init__(self, thread: dict[str, Any]) -> None:
        self.thread = thread

    def list(self, **_: Any) -> FakeRequest:
        return FakeRequest({"threads": [{"id": self.thread["id"]}]})

    def get(self, **_: Any) -> FakeRequest:
        return FakeRequest(self.thread)


class FakeUsers:
    def __init__(self, thread: dict[str, Any]) -> None:
        self.fake_threads = FakeThreads(thread)

    def getProfile(self, **_: Any) -> FakeRequest:  # noqa: N802
        return FakeRequest({"emailAddress": "couple@example.com"})

    def threads(self) -> FakeThreads:
        return self.fake_threads


class FakeService:
    def __init__(self, thread: dict[str, Any]) -> None:
        self.fake_users = FakeUsers(thread)

    def users(self) -> FakeUsers:
        return self.fake_users


def _message(
    message_id: str,
    sender: str,
    timestamp: int,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "internalDate": str(timestamp),
        "labelIds": labels or [],
        "snippet": "Thank you for reaching out.",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "Wedding availability"},
            ]
        },
    }


def test_sync_tracks_reply_after_sent_message(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(response_tracker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(response_tracker, "DATABASE_PATH", tmp_path / "responses.db")
    thread = {
        "id": "thread-1",
        "messages": [
            _message("sent-1", "alias@example.com", 1_000, ["SENT"]),
            _message("reply-1", "Villa Test <events@villa.test>", 2_000),
        ],
    }

    result = sync_recent_responses(service=FakeService(thread))
    saved = response_tracker.list_responses()

    assert result["new_responses"] == 1
    assert result["responses_tracked"] == 1
    assert saved[0]["sender_email"] == "events@villa.test"


def test_sync_ignores_inbound_only_thread(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(response_tracker, "DATA_DIR", tmp_path)
    monkeypatch.setattr(response_tracker, "DATABASE_PATH", tmp_path / "responses.db")
    thread = {
        "id": "thread-2",
        "messages": [_message("inbound-1", "newsletter@example.com", 1_000)],
    }

    result = sync_recent_responses(service=FakeService(thread))

    assert result["responses_tracked"] == 0
    assert response_tracker.list_responses() == []


def test_known_venue_sender_is_tracked_in_new_thread() -> None:
    thread = {
        "id": "thread-3",
        "messages": [
            _message("inbound-2", "Villa <events@villa.test>", 2_000)
        ],
    }

    _, _, responses = find_recent_responses(
        service=FakeService(thread),
        known_senders={"events@villa.test"},
    )

    assert len(responses) == 1
    assert responses[0]["sender_email"] == "events@villa.test"
