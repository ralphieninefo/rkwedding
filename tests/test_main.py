"""Smoke tests for the local API and dashboard."""

import base64
import json

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_dashboard_is_served() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Venue Response Tracker" in response.text
    assert "Gmail read-only" in response.text


def test_old_analysis_dashboard_is_parked() -> None:
    response = client.get("/analysis")

    assert response.status_code == 200
    assert "Wedding Venue Desk" in response.text


def test_gmail_event_returns_placeholder_decision(monkeypatch) -> None:
    async def fake_analyze_event(_event):
        return {
            "venue": "Villa Test",
            "event_type": "unprocessed",
            "status": "received",
            "recommended_action": "connect_serverless_inference",
        }

    monkeypatch.setattr("app.main.analyze_event", fake_analyze_event)
    response = client.post(
        "/events/gmail",
        json={
            "venue": "Villa Test",
            "message": "Il prezzo è €28.000 per 90 persone.",
        },
    )

    assert response.status_code == 200
    assert response.json()["recommended_action"] == "connect_serverless_inference"


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
