"""Smoke tests for the local API and dashboard."""

import base64
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def allow_local_dashboard(monkeypatch):
    settings = Settings(
        _env_file=None,
        allow_unauthenticated_local=True,
        google_sheet_webhook_token=SecretStr("test-webhook-token"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)


def test_dashboard_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Wedding Venue Control Center" in response.text
    assert "Private venue workspace" in response.text


@pytest.mark.parametrize(
    ("path", "expected_text"),
    [
        ("/about", "One place to manage our wedding venue search."),
        ("/privacy", "Google API Services User Data Policy"),
    ],
)
def test_public_oauth_information_pages_are_served_without_login(
    monkeypatch, path: str, expected_text: str
) -> None:
    settings = Settings(
        _env_file=None,
        control_center_username="raph",
        control_center_password=SecretStr("test-password"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    response = client.get(path)

    assert response.status_code == 200
    assert expected_text in response.text


def test_old_analysis_dashboard_is_parked() -> None:
    response = client.get("/analysis")

    assert response.status_code == 200
    assert "Wedding Venue Desk" in response.text


def test_venue_directory_is_served() -> None:
    response = client.get("/venues")

    assert response.status_code == 200
    assert "All venue information" in response.text
    assert "Search venues" in response.text


def test_saved_draft_can_be_sent(monkeypatch) -> None:
    async def fake_send(_settings, venue_id):
        return {"id": venue_id, "status": "Sent", "sent": True}

    monkeypatch.setattr("app.db_workflow.send_venue_inquiry", fake_send)

    response = client.post("/api/venues/13/send")

    assert response.status_code == 200
    assert response.json() == {"id": 13, "status": "Sent", "sent": True}


def test_saved_draft_message_can_be_previewed(monkeypatch) -> None:
    def fake_preview(venue_id):
        return {
            "id": venue_id,
            "venue": "Villa Test",
            "recipient": "info@example.com",
            "subject": "Richiesta informazioni",
            "body": "Buongiorno",
        }

    monkeypatch.setattr("app.db_workflow.outreach_preview", fake_preview)

    response = client.get("/api/venues/13/outreach-preview")

    assert response.status_code == 200
    assert response.json()["recipient"] == "info@example.com"
    assert response.json()["body"] == "Buongiorno"


def test_hosted_dashboard_requires_password(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        control_center_username="raph",
        control_center_password=SecretStr("test-password"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    denied = client.get("/")
    allowed = client.get("/", auth=("raph", "test-password"))

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_dashboard_fails_closed_without_password(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    response = client.get("/")

    assert response.status_code == 401


def test_dashboard_allows_explicit_local_bypass() -> None:
    response = client.get("/")

    assert response.status_code == 200


def test_startup_rejects_missing_dashboard_password(monkeypatch) -> None:
    settings = Settings(_env_file=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="CONTROL_CENTER_PASSWORD"), TestClient(
        app
    ):
        pass


def test_gmail_event_accepts_correct_token(monkeypatch) -> None:
    async def fake_analyze_event(_event):
        return {
            "venue": "Villa Test",
            "event_type": "unprocessed",
            "status": "received",
            "recommended_action": "connect_serverless_inference",
        }

    monkeypatch.setattr("app.main.analyze_event", fake_analyze_event)
    response = client.post(
        "/events/gmail?token=test-webhook-token",
        json={
            "venue": "Villa Test",
            "message": "Il prezzo è €28.000 per 90 persone.",
        },
    )

    assert response.status_code == 200
    assert response.json()["recommended_action"] == "connect_serverless_inference"


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_gmail_event_rejects_missing_or_wrong_token(token) -> None:
    suffix = f"?token={token}" if token else ""

    response = client.post(
        f"/events/gmail{suffix}",
        json={"venue": "Villa Test", "message": "Preventivo"},
    )

    assert response.status_code == 401


def test_gmail_event_requires_configured_token(monkeypatch) -> None:
    settings = Settings(_env_file=None, allow_unauthenticated_local=True)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    response = client.post(
        "/events/gmail?token=anything",
        json={"venue": "Villa Test", "message": "Preventivo"},
    )

    assert response.status_code == 503


def test_gmail_push_decodes_pubsub_message() -> None:
    notification = json.dumps(
        {"emailAddress": "wedding@example.com", "historyId": "987654321"}
    ).encode()
    encoded = base64.b64encode(notification).decode()

    response = client.post(
        "/events/gmail/push",
        json={
            "message": {"data": encoded, "messageId": "message-1"},
            "subscription": "projects/example/subscriptions/gmail-push",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "email_address": "wedding@example.com",
        "history_id": "987654321",
        "next_action": "fetch_gmail_history",
        "processed_messages": 0,
    }


def test_gmail_push_rejects_invalid_data() -> None:
    response = client.post(
        "/events/gmail/push",
        json={"message": {"data": "not-base64"}},
    )

    assert response.status_code == 400


def test_compare_endpoint_returns_ranked_venues() -> None:
    response = client.post(
        "/compare",
        json={
            "venues": [
                {
                    "venue": "Venue A",
                    "normalized_all_in_cost": 28_000,
                    "location_score": 90,
                    "value_score": 90,
                },
                {
                    "venue": "Venue B",
                    "normalized_all_in_cost": 38_000,
                    "location_score": 70,
                    "value_score": 60,
                },
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["rankings"][0]["venue"] == "Venue A"
    assert response.json()["scoring_version"] == "v1"
