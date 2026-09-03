"""Tests for the DigitalOcean Serverless Inference boundary."""

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.inference import DigitalOceanInferenceClient
from app.models import GmailEvent


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_inference_returns_validated_decision() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-model-key"

        content = {
            "venue": "Villa Test",
            "event_type": "quote_received",
            "status": "Quote received",
            "recommended_action": "review_all_inclusions",
            "quoted_price": 28000,
            "currency": "EUR",
            "facts": ["Quote is for 90 guests"],
            "unresolved_questions": ["Are taxes included?"],
            "requires_human_approval": True,
            "draft_reply": None,
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    settings = Settings(
        digitalocean_model_access_key=SecretStr("test-model-key"),
        digitalocean_model_id="test-model",
    )
    client = DigitalOceanInferenceClient(
        settings,
        transport=httpx.MockTransport(handler),
    )

    decision = await client.decide(
        GmailEvent(venue="Villa Test", message="Il prezzo è €28.000."),
        "Return structured JSON.",
    )

    assert decision.event_type == "quote_received"
    assert decision.quoted_price == 28000
    assert decision.currency == "EUR"


@pytest.mark.anyio
async def test_inference_returns_small_response_synthesis() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 500
        content = {
            "summary": "Menus cost EUR 120–150 per person for up to 90 guests.",
            "status": "quote_received",
            "estimated_total_min_eur": 10800,
            "estimated_total_max_eur": 13500,
            "price_note": "90 guests at EUR 120–150 per person.",
            "availability": "Free on 3 October 2026.",
            "guest_capacity": "up to 150 seated",
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    client = DigitalOceanInferenceClient(
        Settings(
            digitalocean_model_access_key=SecretStr("test-model-key"),
            digitalocean_model_id="test-model",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize_response(
        venue="Villa Test",
        subject="Preventivo",
        body="Il menu costa 120 euro a persona.",
    )

    assert result.status == "quote_received"
    assert "120" in result.summary
    assert result.estimated_total_min_eur == 10800
    assert result.availability == "Free on 3 October 2026."
    assert result.guest_capacity == "up to 150 seated"


@pytest.mark.anyio
async def test_inference_forwards_pdf_quote_text_alongside_the_email_body() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        content = {"summary": "The attached brochure lists EUR 140 per person.", "status": "quote_received"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    client = DigitalOceanInferenceClient(
        Settings(
            digitalocean_model_access_key=SecretStr("test-model-key"),
            digitalocean_model_id="test-model",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize_response(
        venue="Villa Test",
        subject="Preventivo",
        body="In allegato trovate il preventivo.",
        attachments_text="Listino prezzi: EUR 140 a persona, fino a 150 invitati.",
    )

    sent_payload = captured["payload"]
    user_message = json.loads(sent_payload["messages"][1]["content"])
    assert user_message["attachments_text"] == (
        "Listino prezzi: EUR 140 a persona, fino a 150 invitati."
    )
    assert "140" in result.summary


@pytest.mark.anyio
async def test_inference_defaults_missing_facts_to_empty_strings() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        content = {"summary": "Grazie per la disponibilità.", "status": "responded"}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    client = DigitalOceanInferenceClient(
        Settings(
            digitalocean_model_access_key=SecretStr("test-model-key"),
            digitalocean_model_id="test-model",
        ),
        transport=httpx.MockTransport(handler),
    )

    result = await client.synthesize_response(
        venue="Villa Test", subject="Re: Richiesta", body="Grazie."
    )

    assert result.availability == ""
    assert result.guest_capacity == ""
