"""FastAPI entrypoint for wedding venue events."""

from pathlib import Path
import secrets

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import SecretStr

from app.agent import analyze_event
from app.config import get_settings
from app.inference import InvalidInferenceResponseError
from app.models import (
    AgentDecision,
    GmailEvent,
    GmailPushReceipt,
    PubSubEnvelope,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Wedding Venue Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the local wedding venue operations dashboard."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a lightweight readiness response."""
    settings = get_settings()
    return {
        "status": "ok",
        "inference": (
            "configured" if settings.inference_configured else "not_configured"
        ),
        "gmail_push": (
            "configured"
            if settings.google_pubsub_verification_token
            else "local_only"
        ),
    }


@app.post("/events/gmail", response_model=AgentDecision)
async def handle_gmail_event(event: GmailEvent) -> AgentDecision:
    """Accept a normalized Gmail event for local phase-one testing."""
    try:
        return await analyze_event(event)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="DigitalOcean Serverless Inference is unavailable.",
        ) from exc
    except InvalidInferenceResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@app.post("/events/gmail/push", response_model=GmailPushReceipt)
async def handle_gmail_push(
    envelope: PubSubEnvelope,
    token: str | None = Query(default=None),
) -> GmailPushReceipt:
    """Decode a Gmail Pub/Sub notification and queue its next safe step.

    Gmail publishes only an email address and history ID. The next integration
    slice must call Gmail history.list and fetch the complete thread before
    sending any content to Serverless Inference.
    """
    expected: SecretStr | None = get_settings().google_pubsub_verification_token
    if expected and (
        token is None
        or not secrets.compare_digest(token, expected.get_secret_value())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Pub/Sub verification token.",
        )

    try:
        notification = envelope.decode_gmail_notification()
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Gmail Pub/Sub message data.",
        ) from exc

    return GmailPushReceipt(
        email_address=notification.email_address,
        history_id=notification.history_id,
    )
