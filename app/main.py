"""FastAPI entrypoint for wedding venue events."""

from pathlib import Path
import secrets

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.agent import analyze_event
from app.config import get_settings
from app.inference import InvalidInferenceResponseError
from app.models import (
    AgentDecision,
    GmailEvent,
    GmailPushReceipt,
    PubSubEnvelope,
    VenueComparisonRequest,
    VenueComparisonResponse,
    VenueOutreachEvent,
    VenueOutreachReceipt,
)
from app.scoring import rank_venues


STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Wedding Venue Agent", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the focused Gmail response tracker."""
    return FileResponse(STATIC_DIR / "inbox.html")


@app.get("/analysis", include_in_schema=False)
async def analysis_dashboard() -> FileResponse:
    """Keep the earlier quote-analysis prototype available but out of the way."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/gmail/status")
async def gmail_status() -> dict[str, bool]:
    from app.gmail_oauth import gmail_connected, oauth_setup_ready

    return {
        "oauth_setup_ready": oauth_setup_ready(),
        "connected": gmail_connected(),
    }


@app.get("/auth/google/start")
async def start_google_auth(request: Request) -> RedirectResponse:
    from app.gmail_oauth import authorization_url

    redirect_uri = str(request.url_for("finish_google_auth"))
    try:
        url = authorization_url(redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth client file has not been added yet.",
        ) from exc
    return RedirectResponse(url)


@app.get("/auth/google/callback", name="finish_google_auth")
async def finish_google_auth(
    request: Request,
    state: str = Query(),
) -> RedirectResponse:
    from app.gmail_oauth import finish_authorization

    redirect_uri = str(request.url_for("finish_google_auth"))
    await run_in_threadpool(
        finish_authorization,
        redirect_uri,
        str(request.url),
        state,
    )
    return RedirectResponse("/?connected=1")


@app.get("/api/responses")
async def tracked_responses() -> dict[str, object]:
    from app.response_tracker import list_responses

    return {"responses": await run_in_threadpool(list_responses)}


@app.post("/api/gmail/sync")
async def sync_gmail_responses() -> dict[str, int | str]:
    from app.gmail_oauth import gmail_connected
    from app.gmail_sync import sync_recent_responses

    if not gmail_connected():
        raise HTTPException(status_code=401, detail="Connect Gmail first.")
    try:
        return await run_in_threadpool(sync_recent_responses)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
        "google_api": "configured" if settings.google_configured else "not_configured",
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


@app.post("/compare", response_model=VenueComparisonResponse)
async def compare_venues(
    comparison: VenueComparisonRequest,
) -> VenueComparisonResponse:
    """Rank venues with fixed, auditable rules rather than model judgment."""
    return VenueComparisonResponse(rankings=rank_venues(comparison.venues))


@app.post("/events/sheets/venue", response_model=VenueOutreachReceipt)
async def handle_new_venue(
    event: VenueOutreachEvent,
    token: str | None = Query(default=None),
) -> VenueOutreachReceipt:
    """Create a safe initial inquiry from a newly ready Sheet row."""
    settings = get_settings()
    expected = settings.google_sheet_webhook_token
    if not expected:
        raise HTTPException(status_code=503, detail="Sheet webhook token is not configured.")
    if (
        token is None
        or not secrets.compare_digest(token, expected.get_secret_value())
    ):
        raise HTTPException(status_code=401, detail="Invalid Sheet webhook token.")
    if not settings.google_configured:
        raise HTTPException(status_code=503, detail="Google integration is not configured.")
    try:
        from app.workflow import WeddingWorkflow

        workflow = await WeddingWorkflow.create(settings)
        result = await workflow.process_new_venue(event)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=503, detail="Google integration failed.") from exc
    return VenueOutreachReceipt(
        status=result.status,
        venue=event.venue,
        gmail_id=result.gmail_id,
    )


@app.post("/events/gmail/push", response_model=GmailPushReceipt)
async def handle_gmail_push(
    envelope: PubSubEnvelope,
    token: str | None = Query(default=None),
) -> GmailPushReceipt:
    """Process a Gmail Pub/Sub history notification when Google is configured."""
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

    settings = get_settings()
    if not settings.google_configured:
        if expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Google integration is not configured; Pub/Sub should retry.",
            )
        return GmailPushReceipt(
            email_address=notification.email_address,
            history_id=notification.history_id,
        )

    try:
        from app.workflow import WeddingWorkflow

        workflow = await WeddingWorkflow.create(settings)
        result = await workflow.process_notification(notification)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google integration failed; Pub/Sub should retry this event.",
        ) from exc

    return GmailPushReceipt(
        email_address=notification.email_address,
        history_id=notification.history_id,
        next_action=result.action,
        processed_messages=result.processed_messages,
    )
