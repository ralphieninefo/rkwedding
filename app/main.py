"""FastAPI entrypoint for wedding venue events."""

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from google.auth.exceptions import GoogleAuthError
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool

from app.agent import analyze_event
from app.config import get_settings
from app.google_auth import GoogleCredentialError
from app.inference import InvalidInferenceResponseError
from app.models import (
    AgentDecision,
    ControlCenterLogin,
    GmailEvent,
    GmailPushReceipt,
    PreferencesUpdate,
    PubSubEnvelope,
    ReplyDraftRequest,
    VenueComparisonRequest,
    VenueComparisonResponse,
    VenueCreate,
    VenueDiscovery,
    VenueDiscoveryRequest,
    VenueOutreachEvent,
    VenueOutreachReceipt,
    VenueReply,
    VenueResearchUpdate,
    VenueUpdate,
)
from app.scoring import rank_venues
from app.session_auth import (
    SESSION_COOKIE,
    create_session_cookie,
    valid_session_cookie,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
GOOGLE_TRANSIENT_DETAIL = (
    "Google could not refresh the Gmail sign-in just now. Please try again."
)


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
    """Require a signed login session for the private control center."""
    settings = get_settings()
    password = settings.control_center_password
    public_path = request.url.path in {
        "/login",
        "/api/login",
        "/about",
        "/privacy",
        "/health",
    } or (
        request.url.path.startswith(("/events/", "/static/"))
    )
    if public_path:
        return await call_next(request)
    if not password:
        if settings.allow_unauthenticated_local:
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Login required."})

    authenticated = valid_session_cookie(
        request.cookies.get(SESSION_COOKIE),
        settings.control_center_username,
        password,
    )
    if not authenticated and request.method == "GET" and not request.url.path.startswith(
        ("/api/", "/auth/")
    ):
        destination = request.url.path
        if request.url.query:
            destination = f"{destination}?{request.url.query}"
        return RedirectResponse(f"/login?next={quote(destination, safe='')}", status_code=303)
    if not authenticated:
        return JSONResponse(
            status_code=401,
            content={"detail": "Your control center session has expired. Sign in again."},
        )
    return await call_next(request)


@app.get("/login", include_in_schema=False)
async def login_page() -> FileResponse:
    """Serve a reliable application-owned login form."""
    return FileResponse(
        STATIC_DIR / "login.html", headers={"Cache-Control": "no-store"}
    )


@app.post("/api/login")
async def login(
    request: Request, credentials: ControlCenterLogin
) -> JSONResponse:
    """Exchange the shared dashboard credential for a signed session cookie."""
    settings = get_settings()
    password = settings.control_center_password
    if not password:
        raise HTTPException(status_code=503, detail="Dashboard login is not configured.")
    authenticated = secrets.compare_digest(
        credentials.username, settings.control_center_username
    ) and secrets.compare_digest(
        credentials.password, password.get_secret_value()
    )
    if not authenticated:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        create_session_cookie(
            settings.control_center_username,
            password,
            ttl_hours=settings.control_center_session_ttl_hours,
        ),
        httponly=True,
        secure=request.url.scheme == "https" or settings.app_env != "local",
        samesite="lax",
        max_age=settings.control_center_session_ttl_hours * 60 * 60,
    )
    return response


@app.post("/api/logout")
async def logout() -> JSONResponse:
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    """Serve the next-action home screen."""
    return FileResponse(
        STATIC_DIR / "home.html", headers={"Cache-Control": "no-store"}
    )


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
    return FileResponse(
        STATIC_DIR / "venues.html", headers={"Cache-Control": "no-store"}
    )


@app.get("/venues/{venue_id:int}", include_in_schema=False)
async def venue_page(venue_id: int) -> FileResponse:
    """Serve the venue dossier page; the browser loads the data by id."""
    return FileResponse(
        STATIC_DIR / "venue.html", headers={"Cache-Control": "no-store"}
    )


@app.get("/api/venues/{venue_id}")
async def venue_detail_api(venue_id: int) -> dict[str, object]:
    """Return one venue's dossier with its message timeline (no full bodies)."""
    from app.db_workflow import venue_detail

    try:
        return await run_in_threadpool(venue_detail, venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.patch("/api/venues/{venue_id}")
async def update_venue_api(venue_id: int, update: VenueUpdate) -> dict[str, object]:
    """Edit venue details, shortlist or pass it, or plan a visit."""
    from app.db_workflow import VenueConflictError, update_venue

    try:
        return await run_in_threadpool(
            update_venue, venue_id, **update.model_dump(exclude_unset=True)
        )
    except VenueConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        status_code = 404 if str(exc) == "Venue not found." else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@app.delete("/api/venues/{venue_id}")
async def delete_venue_api(venue_id: int) -> dict[str, object]:
    """Delete a venue that has no Gmail history; otherwise it must be passed."""
    from app.db_workflow import VenueConflictError, delete_venue

    try:
        return await run_in_threadpool(delete_venue, venue_id)
    except VenueConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/preferences")
async def preferences_api() -> dict[str, object]:
    from app.database import SessionLocal, preferences_payload

    with SessionLocal() as session:
        return preferences_payload(session)


@app.patch("/api/preferences")
async def update_preferences_api(update: PreferencesUpdate) -> dict[str, object]:
    from app.db_workflow import update_preferences

    return await run_in_threadpool(update_preferences, **update.model_dump())


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
    try:
        account = await run_in_threadpool(
            finish_authorization,
            redirect_uri,
            str(request.url),
            state,
            code_verifier,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    response = RedirectResponse(f"/?connected=1&account={account['id']}")
    response.delete_cookie("google_oauth_state")
    response.delete_cookie("google_oauth_code_verifier")
    return response


@app.get("/api/responses")
async def tracked_responses() -> dict[str, object]:
    from app.response_tracker import list_responses

    return {"responses": await run_in_threadpool(list_responses)}


@app.get("/api/venues")
async def venues_api() -> dict[str, object]:
    """Return database-backed venue status without exposing full email bodies."""
    from app.database import SessionLocal, dashboard_payload

    with SessionLocal() as session:
        return dashboard_payload(session)


@app.get("/api/documents/{document_id}/view")
async def view_document(document_id: int) -> RedirectResponse:
    """Authorize the dashboard user, then issue a short-lived Spaces URL."""
    from botocore.exceptions import BotoCoreError, ClientError

    from app.database import Attachment, SessionLocal
    from app.storage import SpacesStorage

    settings = get_settings()
    if not settings.spaces_configured:
        raise HTTPException(
            status_code=503,
            detail="Private document storage is not configured.",
        )
    with SessionLocal() as session:
        attachment = session.get(Attachment, document_id)
        if attachment is None:
            raise HTTPException(status_code=404, detail="Document not found.")
        object_key = attachment.object_key
        filename = attachment.original_filename
        content_type = attachment.content_type
    try:
        storage = SpacesStorage(settings)
        url = await run_in_threadpool(
            storage.presigned_view_url,
            object_key=object_key,
            filename=filename,
            content_type=content_type,
        )
    except (BotoCoreError, ClientError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The private document link could not be created.",
        ) from exc
    return RedirectResponse(url, status_code=302)


@app.post("/api/venues")
async def create_venue(venue: VenueCreate) -> dict[str, object]:
    """Save a venue and send only when the user explicitly requests it."""
    from app.db_workflow import create_venue_and_optionally_send

    try:
        return await create_venue_and_optionally_send(
            get_settings(), **venue.model_dump()
        )
    except GoogleCredentialError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=GOOGLE_TRANSIENT_DETAIL) from exc
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
    except GoogleCredentialError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=GOOGLE_TRANSIENT_DETAIL) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Connect Google before sending.") from exc
    except httpx.HTTPStatusError as exc:
        detail = _gmail_error_detail(exc, action="send the inquiry")
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Gmail could not send the inquiry. Please try again.",
        ) from exc


@app.get("/api/venues/{venue_id}/outreach-preview")
async def preview_venue_outreach(venue_id: int) -> dict[str, object]:
    """Show the exact standard inquiry before the user chooses to send it."""
    from app.db_workflow import outreach_preview

    try:
        return outreach_preview(venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
    except GoogleCredentialError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=GOOGLE_TRANSIENT_DETAIL) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Connect Google first.") from exc
    except httpx.HTTPStatusError as exc:
        detail = _gmail_error_detail(exc, action="send the reply")
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Gmail could not send the reply. Please try again.",
        ) from exc


def _gmail_error_detail(exc: httpx.HTTPStatusError, *, action: str) -> str:
    """Return a safe, useful Gmail failure without leaking response contents."""
    status_code = exc.response.status_code
    if status_code == 401:
        return f"Google authorization expired before Gmail could {action}. Reconnect it."
    if status_code == 403:
        return f"Gmail denied permission to {action}. Reconnect the sending account."
    if status_code == 429:
        return f"Gmail is temporarily rate limited and could not {action}. Try again shortly."
    return f"Gmail could not {action} (HTTP {status_code}). Please try again."


@app.get("/api/venues/{venue_id}/followup-preview")
async def preview_venue_followup(venue_id: int) -> dict[str, object]:
    """Show an editable follow-up without sending it."""
    from app.db_workflow import followup_preview

    try:
        return await run_in_threadpool(followup_preview, venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/venues/{venue_id}/draft-reply")
async def draft_venue_reply(venue_id: int, request: ReplyDraftRequest) -> dict[str, object]:
    """Draft an Italian reply from English points; the user still reviews and sends."""
    from app.db_workflow import InferenceUnavailableError, draft_reply

    try:
        return await draft_reply(get_settings(), venue_id, request.points)
    except InferenceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/venues/{venue_id}/reminder-preview")
async def preview_venue_reminder(venue_id: int) -> dict[str, object]:
    """Show the exact reminder (thread, mailbox, recipient) before sending."""
    from app.db_workflow import reminder_preview

    try:
        return await run_in_threadpool(reminder_preview, venue_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/venues/{venue_id}/remind")
async def remind_venue(venue_id: int, reply: VenueReply) -> dict[str, object]:
    """Send one explicit reminder inside the thread and mailbox already used."""
    from app.db_workflow import send_venue_reminder

    try:
        return await send_venue_reminder(get_settings(), venue_id, reply.body)
    except GoogleCredentialError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except GoogleAuthError as exc:
        raise HTTPException(status_code=502, detail=GOOGLE_TRANSIENT_DETAIL) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Connect Google first.") from exc
    except httpx.HTTPStatusError as exc:
        detail = _gmail_error_detail(exc, action="send the reminder")
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail="Gmail could not send the reminder. Please try again.",
        ) from exc


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
        result = await reconcile_gmail_database(get_settings())
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
    _raise_if_no_mailbox_synced(result, status_code=502)
    return result


def _raise_if_no_mailbox_synced(result: dict[str, object], *, status_code: int) -> None:
    """Keep manual reconciliation honest: no mailbox checked is not a success."""
    failed = list(result.get("accounts_failed") or [])
    if failed and not result.get("accounts_synced"):
        problems = "; ".join(
            f"{item.get('email', 'mailbox')}: {item.get('error', 'not checked')}"
            for item in failed
        )
        raise HTTPException(
            status_code=status_code,
            detail=f"No mailbox could be checked. {problems}",
        )


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

        result = await reconcile_gmail_database(settings)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Reconciliation failed and will be retried by the scheduler.",
        ) from exc
    _raise_if_no_mailbox_synced(result, status_code=503)
    return result


@app.get("/health")
async def health() -> dict[str, str]:
    """Return a lightweight readiness response."""
    from app.gmail_oauth import gmail_connected, oauth_setup_ready

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
        "google_oauth_client": (
            "configured" if oauth_setup_ready() else "not_configured"
        ),
        "gmail_accounts": "connected" if gmail_connected() else "not_connected",
        "document_storage": (
            "configured" if settings.spaces_configured else "not_configured"
        ),
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
