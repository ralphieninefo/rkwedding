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
