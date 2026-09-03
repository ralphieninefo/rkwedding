"""Smoke tests for the local API and dashboard."""

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
from pydantic import SecretStr

from app.config import Settings
from app.google_auth import GoogleCredentialError
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
    assert "Check Gmail" not in response.text
    assert "Workflow" not in response.text
    assert "Last automatic update" in response.text
    assert response.headers["cache-control"] == "no-store"


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


def test_private_document_view_redirects_to_short_lived_spaces_url(
    monkeypatch,
) -> None:
    settings = Settings(
        _env_file=None,
        allow_unauthenticated_local=True,
        spaces_bucket="wedding-documents",
        spaces_access_key_id=SecretStr("key"),
        spaces_secret_access_key=SecretStr("secret"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, _model, document_id):
            assert document_id == 7
            return SimpleNamespace(
                object_key="venues/1/messages/2/attachments/3/quote.pdf",
                original_filename="quote.pdf",
                content_type="application/pdf",
            )

    class FakeStorage:
        def __init__(self, received_settings):
            assert received_settings is settings

        def presigned_view_url(self, **_kwargs):
            return "https://private.example/signed"

    monkeypatch.setattr("app.database.SessionLocal", FakeSession)
    monkeypatch.setattr("app.storage.SpacesStorage", FakeStorage)

    response = client.get("/api/documents/7/view", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://private.example/signed"


def test_saved_draft_can_be_sent(monkeypatch) -> None:
    async def fake_send(_settings, venue_id):
        return {"id": venue_id, "status": "Sent", "sent": True}

    monkeypatch.setattr("app.db_workflow.send_venue_inquiry", fake_send)

    response = client.post("/api/venues/13/send")

    assert response.status_code == 200
    assert response.json() == {"id": 13, "status": "Sent", "sent": True}


@pytest.mark.parametrize(
    ("path", "target"),
    [
        ("/api/venues/13/send", "app.db_workflow.send_venue_inquiry"),
        ("/api/venues/13/reply", "app.db_workflow.reply_to_venue"),
    ],
)
def test_expired_google_authorization_asks_to_reconnect_instead_of_500(
    monkeypatch, path: str, target: str
) -> None:
    async def expired(*_args, **_kwargs):
        raise GoogleCredentialError("shared@example.com")

    monkeypatch.setattr(target, expired)

    response = client.post(path, json={"body": "Grazie."})

    assert response.status_code == 401
    assert "shared@example.com" in response.json()["detail"]
    assert "Add Gmail account" in response.json()["detail"]


def test_transient_google_refresh_failure_is_a_retryable_502(monkeypatch) -> None:
    async def flaky(*_args, **_kwargs):
        raise TransportError("connection reset")

    monkeypatch.setattr("app.db_workflow.send_venue_inquiry", flaky)

    response = client.post("/api/venues/13/send")

    assert response.status_code == 502
    assert "try again" in response.json()["detail"].casefold()
    assert "connection reset" not in response.json()["detail"]


def test_manual_sync_is_not_a_success_when_no_mailbox_could_be_checked(
    monkeypatch,
) -> None:
    async def nothing_synced(_settings):
        return {
            "new_messages": 0,
            "accounts_synced": [],
            "accounts_failed": [{"email": "shared@example.com", "error": "Reconnect it."}],
            "last_refreshed_at": None,
        }

    async def partially_synced(_settings):
        return {
            "new_messages": 1,
            "accounts_synced": ["shared@example.com"],
            "accounts_failed": [{"email": "personal@example.com", "error": "Expired."}],
            "last_refreshed_at": "2026-09-03T09:00:00+00:00",
        }

    monkeypatch.setattr("app.db_workflow.reconcile_gmail_database", nothing_synced)
    total = client.post("/api/control-center/sync")
    assert total.status_code == 502
    assert "shared@example.com" in total.json()["detail"]

    monkeypatch.setattr("app.db_workflow.reconcile_gmail_database", partially_synced)
    partial = client.post("/api/control-center/sync")
    assert partial.status_code == 200
    assert partial.json()["accounts_failed"][0]["email"] == "personal@example.com"


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


def test_followup_can_be_previewed_without_sending(monkeypatch) -> None:
    def fake_preview(venue_id):
        return {
            "id": venue_id,
            "venue": "Villa Test",
            "recipient": "info@example.com",
            "subject": "Re: Preventivo",
            "response_summary": "Quote received.",
            "body": "Grazie per il preventivo.",
        }

    monkeypatch.setattr("app.db_workflow.followup_preview", fake_preview)

    response = client.get("/api/venues/13/followup-preview")

    assert response.status_code == 200
    assert response.json()["subject"] == "Re: Preventivo"


def test_human_research_is_saved_separately(monkeypatch) -> None:
    captured = {}

    def fake_save(venue_id, **research):
        captured.update(research)
        return {"id": venue_id, "saved": True}

    monkeypatch.setattr("app.db_workflow.update_venue_research", fake_save)
    response = client.patch(
        "/api/venues/13/research",
        json={
            "source_type": "Reddit",
            "source_url": "https://reddit.com/example",
            "contact_name": "Helpful bride",
            "notes": "Great direct feedback.",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"id": 13, "saved": True}
    assert captured["source_type"] == "Reddit"


def test_hosted_dashboard_requires_password(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        control_center_username="raph",
        control_center_password=SecretStr("test-password"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with TestClient(app) as hosted_client:
        denied = hosted_client.get("/", follow_redirects=False)
        login_page = hosted_client.get("/login")
        incorrect = hosted_client.post(
            "/api/login",
            json={"username": "raph", "password": "wrong"},
        )
        allowed = hosted_client.post(
            "/api/login",
            json={"username": "raph", "password": "test-password"},
        )
        dashboard = hosted_client.get("/")

    assert denied.status_code == 303
    assert denied.headers["location"].startswith("/login?next=")
    assert "www-authenticate" not in denied.headers
    assert login_page.status_code == 200
    assert "Welcome back" in login_page.text
    assert incorrect.status_code == 401
    assert allowed.status_code == 200
    assert dashboard.status_code == 200


def test_hosted_api_returns_plain_401_without_browser_popup(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        control_center_username="raph",
        control_center_password=SecretStr("test-password"),
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with TestClient(app) as hosted_client:
        response = hosted_client.get("/api/gmail/status")

    assert response.status_code == 401
    assert "www-authenticate" not in response.headers


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
