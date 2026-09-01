"""FastAPI entrypoint for wedding venue events."""

import base64
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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
    VenueCreate,
    VenueDiscovery,
    VenueDiscoveryRequest,
    VenueOutreachEvent,
    VenueOutreachReceipt,
    VenueReply,
    VenueResearchUpdate,
)
from app.scoring import rank_venues

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from app.database import init_database

    settings = get_settings()
    if (
        not settings.control_center_password
        and not settings.allow_unauthenticated_local
    ):
        raise RuntimeError(
            "CONTROL_CENTER_PASSWORD is required unless "
            "ALLOW_UNAUTHENTICATED_LOCAL=true is explicitly set for local use."
        )
    init_database()
    yield


app = FastAPI(title="Wedding Venue Agent", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def protect_hosted_control_center(request: Request, call_next):
    """Require HTTP Basic auth when a hosted dashboard password is configured."""
    settings = get_settings()
    password = settings.control_center_password
    public_path = request.url.path in {"/about", "/privacy", "/health"} or (
        request.url.path.startswith("/events/")
    )
    if public_path:
        return await call_next(request)
    if not password:
        if settings.allow_unauthenticated_local:
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={"detail": "Control center login required."},
            headers={"WWW-Authenticate": 'Basic realm="Wedding Venue Control Center"'},
        )

    authorization = request.headers.get("Authorization", "")
    authenticated = False
    if authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:]).decode("utf-8")
            username, supplied_password = decoded.split(":", 1)
            authenticated = secrets.compare_digest(
                username, settings.control_center_username
            ) and secrets.compare_digest(
                supplied_password, password.get_secret_value()
            )
        except (ValueError, UnicodeDecodeError):
            authenticated = False
    if not authenticated:
        return JSONResponse(
            status_code=401,
            content={"detail": "Control center login required."},
            headers={"WWW-Authenticate": 'Basic realm="Wedding Venue Control Center"'},
        )
    return await call_next(request)


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the focused Gmail response tracker."""
    return FileResponse(STATIC_DIR / "inbox.html")


@app.get("/about", include_in_schema=False)
async def about() -> FileResponse:
    """Serve the public application information required for Google OAuth."""
    return FileResponse(STATIC_DIR / "about.html")


@app.get("/privacy", include_in_schema=False)
async def privacy() -> FileResponse:
    """Serve the public privacy policy required for Google OAuth."""
    return FileResponse(STATIC_DIR / "privacy.html")


@app.get("/analysis", include_in_schema=False)
async def analysis_dashboard() -> FileResponse:
    """Keep the earlier quote-analysis prototype available but out of the way."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/venues", include_in_schema=False)
async def venue_directory() -> FileResponse:
    """Serve the complete venue reference directory."""
    return FileResponse(STATIC_DIR / "venues.html")


@app.get("/api/gmail/status")
async def gmail_status() -> dict[str, object]:
    from app.gmail_oauth import (
        gmail_connected,
        list_google_accounts,
        oauth_setup_ready,
    )

    return {
        "oauth_setup_ready": oauth_setup_ready(),
        "connected": gmail_connected(),
        "accounts": list_google_accounts(),
        "spreadsheet_configured": bool(get_settings().google_spreadsheet_id),
    }


@app.get("/auth/google/start")
async def start_google_auth(request: Request) -> RedirectResponse:
    from app.gmail_oauth import authorization_url

    redirect_uri = str(request.url_for("finish_google_auth"))
    try:
        url, state, code_verifier = authorization_url(redirect_uri)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="Google OAuth client file has not been added yet.",
        ) from exc
    response = RedirectResponse(url)
    response.set_cookie(
        "google_oauth_state",
        state,
        httponly=True,
        secure=redirect_uri.startswith("https://"),
        samesite="lax",
        max_age=600,
    )
    response.set_cookie(
        "google_oauth_code_verifier",
        code_verifier,
        httponly=True,
        secure=redirect_uri.startswith("https://"),
        samesite="lax",
        max_age=600,
    )
    return response


@app.get("/auth/google/callback", name="finish_google_auth")
async def finish_google_auth(
    request: Request,
    state: str = Query(),
) -> RedirectResponse:
    from app.gmail_oauth import finish_authorization

    redirect_uri = str(request.url_for("finish_google_auth"))
    expected_state = request.cookies.get("google_oauth_state")
    code_verifier = request.cookies.get("google_oauth_code_verifier")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state.")
    if not code_verifier:
        raise HTTPException(status_code=400, detail="OAuth verifier is missing.")
    account = await run_in_threadpool(
        finish_authorization,
        redirect_uri,
        str(request.url),
        state,
        code_verifier,
    )
    response = RedirectResponse(f"/?connected=1&account={account['id']}")
    response.delete_cookie("google_oauth_state")
    response.delete_cookie("google_oauth_code_verifier")
    return response


@app.get("/api/responses")
async def tracked_responses() -> dict[str, object]:
    from app.response_tracker import list_responses

    return {"responses": await run_in_threadpool(list_responses)}


@app.get("/api/venues")
async def sheet_venues() -> dict[str, object]:
    """Return database-backed venue status without exposing full email bodies."""
    from app.database import SessionLocal, dashboard_payload

    with SessionLocal() as session:
        return dashboard_payload(session)


@app.post("/api/venues")
async def create_venue(venue: VenueCreate) -> dict[str, object]:
    """Save a venue and send only when the user explicitly requests it."""
    from app.db_workflow import create_venue_and_optionally_send

    try:
        return await create_venue_and_optionally_send(
            get_settings(), **venue.model_dump()
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Connect Google before sending.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Gmail could not send the inquiry.") from exc


@app.post("/api/venues/{venue_id}/send")
async def send_venue(venue_id: int) -> dict[str, object]:
    """Send the standard inquiry for an explicitly selected saved draft."""
    from app.db_workflow import send_venue_inquiry

    try:
        return await send_venue_inquiry(get_settings(), venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Connect Google before sending.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Gmail could not send the inquiry.") from exc


@app.get("/api/venues/{venue_id}/outreach-preview")
async def preview_venue_outreach(venue_id: int) -> dict[str, object]:
    """Show the exact standard inquiry before the user chooses to send it."""
    from app.db_workflow import outreach_preview

    try:
        return outreach_preview(venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/import/sheet")
async def import_existing_sheet() -> dict[str, int]:
    """Copy valid venue contacts into the database; never modify the Sheet."""
    from app.db_workflow import import_sheet_venues

    try:
        return await import_sheet_venues(get_settings())
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Connect Google first.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not read the venue Sheet.") from exc


@app.post("/api/venues/discover", response_model=VenueDiscovery)
async def discover_venue_contact(request: VenueDiscoveryRequest) -> VenueDiscovery:
    """Find public contact details without sending an email."""
    from app.discovery import discover_venue

    try:
        result = await discover_venue(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Could not read that venue website.") from exc
    if not result.email:
        raise HTTPException(status_code=404, detail="No public email address was found.")
    return result


@app.post("/api/venues/{venue_id}/reply")
async def reply_to_venue(venue_id: int, reply: VenueReply) -> dict[str, object]:
    """Send one explicit dashboard reply inside the tracked Gmail thread."""
    from app.db_workflow import reply_to_venue as send_reply

    try:
        return await send_reply(get_settings(), venue_id, reply.body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Connect Google first.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Gmail could not send the reply.") from exc


@app.get("/api/venues/{venue_id}/followup-preview")
async def preview_venue_followup(venue_id: int) -> dict[str, object]:
    """Show an editable follow-up without sending it."""
    from app.db_workflow import followup_preview

    try:
        return followup_preview(venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/venues/{venue_id}/research")
async def save_venue_research(
    venue_id: int, research: VenueResearchUpdate
) -> dict[str, object]:
    """Save separately labeled human research for one venue."""
    from app.db_workflow import update_venue_research

    try:
        return update_venue_research(venue_id, **research.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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


@app.post("/api/control-center/sync")
async def sync_control_center() -> dict[str, object]:
    """Reconcile Gmail into the database and synthesize new replies."""
    from googleapiclient.errors import HttpError

    from app.db_workflow import reconcile_gmail_database

    try:
        return await reconcile_gmail_database(get_settings())
    except HttpError as exc:
        if exc.resp.status == 403:
            detail = "Gmail API is unavailable or not enabled."
        else:
            detail = "Gmail response check failed."
        raise HTTPException(status_code=502, detail=detail) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail="Could not reconcile Gmail."
        ) from exc


@app.post("/events/reconcile")
async def scheduled_reconciliation(
    token: str | None = Query(default=None),
) -> dict[str, object]:
    """Run the same reconciliation from a private scheduled webhook."""
    settings = get_settings()
    expected = settings.google_sheet_webhook_token
    if not expected:
        raise HTTPException(status_code=503, detail="Reconciliation token is not configured.")
    if token is None or not secrets.compare_digest(token, expected.get_secret_value()):
        raise HTTPException(status_code=401, detail="Invalid reconciliation token.")
    if not settings.google_configured:
        raise HTTPException(status_code=503, detail="Google integration is not configured.")
    try:
        from app.db_workflow import reconcile_gmail_database

        return await reconcile_gmail_database(settings)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Reconciliation failed and will be retried by the scheduler.",
        ) from exc


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
async def handle_gmail_event(
    event: GmailEvent,
    token: str | None = Query(default=None),
) -> AgentDecision:
    """Accept a normalized Gmail event for local phase-one testing."""
    expected = get_settings().google_sheet_webhook_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Gmail event webhook token is not configured.",
        )
    if token is None or not secrets.compare_digest(
        token, expected.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid Gmail event token.")
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
        gmail_thread_id=result.gmail_thread_id,
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
