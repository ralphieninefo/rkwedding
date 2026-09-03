"""Gmail reconciliation and concise database-backed response synthesis."""

import asyncio
import json
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
import re

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from google.auth.exceptions import GoogleAuthError
from sqlalchemy import select

from app.config import Settings
from app.database import (
    BUDGET_KEY,
    LAST_REFRESH_KEY,
    SYNC_STATUS_KEY,
    Attachment,
    GoogleAccount,
    Message,
    Outreach,
    PriceEstimate,
    SessionLocal,
    Venue,
    get_system_state,
    iso_utc,
    preferences_payload,
    set_system_state,
    sync_status_payload,
    upsert_venue,
    venue_detail_payload,
)
from app.email_templates import (
    FOLLOWUP_BODY,
    OUTREACH_BODY,
    OUTREACH_SUBJECT,
    REMINDER_BODY,
)
from app.gmail import GmailClient, GmailMessage
from app.gmail_oauth import default_google_account_id, list_google_accounts
from app.google_auth import GoogleCredentialError, get_google_access_token
from app.inference import DigitalOceanInferenceClient, InvalidInferenceResponseError
from app.models import ResponseSynthesis
from app.storage import AttachmentTooLargeError, SpacesStorage
from app.venue_state import DECISIONS

# Venues with no stored history for a mailbox are searched this far back so
# older conversations (for example in the personal mailbox) are attached.
HISTORICAL_SEARCH_DAYS = 365


class VenueConflictError(ValueError):
    """The requested change collides with another venue or with history."""

# Failures that affect one mailbox only. They are recorded per account so a
# revoked token or a Gmail outage on one mailbox never blocks the other.
ACCOUNT_SYNC_ERRORS = (
    GoogleCredentialError,
    GoogleAuthError,
    httpx.HTTPError,
    ValueError,
    OSError,
    KeyError,
)


def _addresses(value: str) -> set[str]:
    return {address.casefold() for _, address in getaddresses([value]) if address}


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_outgoing(
    message: GmailMessage,
    venue_email: str,
    known_thread_ids: set[str] | frozenset[str] = frozenset(),
) -> bool:
    """A message we sent to the venue address, or inside a known venue thread.

    The second case covers a manual reply to a staff member's personal
    address from Gmail itself; it still counts as our follow-up.
    """
    return "SENT" in message.label_ids and (
        venue_email in _addresses(message.recipients)
        or message.thread_id in known_thread_ids
    )


def _sender_address(message: GmailMessage) -> str:
    return parseaddr(message.sender)[1].strip().casefold()


def _is_incoming(
    message: GmailMessage, venue_email: str, known_thread_ids: set[str]
) -> bool:
    return (
        "SENT" not in message.label_ids
        and "DRAFT" not in message.label_ids
        and (
            parseaddr(message.sender)[1].casefold() == venue_email
            or message.thread_id in known_thread_ids
        )
    )


async def create_venue_and_optionally_send(
    settings: Settings,
    *,
    name: str,
    email: str,
    region: str,
    location: str,
    website: str,
    phone: str,
    send_now: bool,
) -> dict[str, object]:
    with SessionLocal() as session:
        venue = upsert_venue(
            session,
            name=name,
            email=email,
            region=region or location,
            location=location,
            website=website,
            phone=phone,
        )
        venue_id = venue.id
    if not send_now:
        return {"id": venue_id, "status": "Draft", "sent": False}

    return await send_venue_inquiry(settings, venue_id)


def outreach_preview(venue_id: int) -> dict[str, object]:
    """Return the exact initial message without sending anything."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        return {
            "id": venue.id,
            "venue": venue.name,
            "recipient": venue.email,
            "subject": OUTREACH_SUBJECT,
            "body": OUTREACH_BODY,
        }


async def _existing_conversation_accounts(
    settings: Settings, email: str, sending_account_id: int | None
) -> tuple[list[str], list[str]]:
    """Return mailboxes that already hold a conversation with this address.

    Every connected mailbox is searched, not only the sender, because earlier
    inquiries may live in the personal mailbox. Mailboxes that cannot be
    checked right now are reported separately rather than silently skipped.
    """
    found: list[str] = []
    unchecked: list[str] = []
    for account in list_google_accounts():
        account_id = int(account["id"])
        mailbox = str(account["email"])
        try:
            token = await get_google_access_token(settings, account_id)
            gmail = GmailClient(token, settings.google_gmail_user_id)
            existing = await gmail.search_message_ids(
                f"in:anywhere {{to:{email} from:{email}}}", max_results=1
            )
        except (GoogleCredentialError, ValueError, httpx.HTTPError):
            if account_id == sending_account_id:
                raise
            unchecked.append(mailbox)
            continue
        if existing:
            found.append(mailbox)
    return found, unchecked


async def send_venue_inquiry(
    settings: Settings, venue_id: int
) -> dict[str, object]:
    """Send the standard first inquiry for one saved draft venue."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        if venue.outreach or venue.messages:
            return {"id": venue_id, "status": venue.status, "sent": False}
        email = venue.email

    account_id = default_google_account_id()
    if account_id is None:
        raise FileNotFoundError("No Google OAuth credential is stored in the database.")
    found, unchecked = await _existing_conversation_accounts(settings, email, account_id)
    if found:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            assert venue is not None
            venue.status = "Existing conversation"
            session.commit()
        return {
            "id": venue_id,
            "status": "Existing conversation",
            "sent": False,
            "existing_in": found,
        }

    token = await get_google_access_token(settings, account_id)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    result = await gmail.send_message(email, OUTREACH_SUBJECT, OUTREACH_BODY)
    now = datetime.now(UTC)
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        assert venue is not None
        venue.status = "Sent"
        session.add(
            Outreach(
                venue_id=venue_id,
                gmail_message_id=result.message_id,
                gmail_thread_id=result.thread_id,
                gmail_account_id=account_id,
                sent_at=now,
            )
        )
        session.add(
            Message(
                venue_id=venue_id,
                gmail_message_id=result.message_id,
                gmail_thread_id=result.thread_id,
                gmail_account_id=account_id,
                direction="outbound",
                kind="inquiry",
                subject=OUTREACH_SUBJECT,
                body=OUTREACH_BODY,
                synthesized_summary="",
                occurred_at=now,
            )
        )
        session.commit()
    return {
        "id": venue_id,
        "status": "Sent",
        "sent": True,
        "unchecked_mailboxes": unchecked,
    }


async def _synthesize(
    settings: Settings, message: GmailMessage, venue: Venue
) -> tuple[ResponseSynthesis, str]:
    fallback = "Response received; English synthesis is temporarily unavailable."
    if not settings.inference_configured or not (message.body or message.subject):
        return ResponseSynthesis(summary=fallback), "Responded"
    try:
        synthesis = await asyncio.wait_for(
            DigitalOceanInferenceClient(settings).synthesize_response(
                venue=venue.name,
                subject=message.subject,
                body=message.body,
            ),
            timeout=45,
        )
        status = {
            "quote_received": "Quote received",
            "viewing_offered": "Viewing offered",
            "unavailable": "Unavailable",
            "needs_reply": "More info needed",
        }.get(synthesis.status, "Responded")
        return synthesis, status
    except (
        TimeoutError,
        httpx.HTTPError,
        InvalidInferenceResponseError,
        ValueError,
    ):
        return ResponseSynthesis(summary=fallback), "Responded"


def _save_estimate(
    session, venue_id: int, message_id: str, synthesis: ResponseSynthesis
) -> None:
    if (
        synthesis.estimated_total_min_eur is None
        and synthesis.estimated_total_max_eur is None
    ):
        return
    estimate = session.scalar(
        select(PriceEstimate).where(PriceEstimate.venue_id == venue_id)
    ) or PriceEstimate(venue_id=venue_id)
    estimate.source_message_id = message_id
    estimate.minimum_eur = synthesis.estimated_total_min_eur
    estimate.maximum_eur = synthesis.estimated_total_max_eur
    estimate.note = synthesis.price_note
    estimate.updated_at = datetime.now(UTC)
    session.add(estimate)


def _fallback_summary(value: str) -> str:
    """Create a compact display fallback without showing the whole response."""
    useful_lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        lowered = line.casefold()
        if not line or line.startswith((">", "[cid:", "[logo-")):
            continue
        if " ha scritto:" in lowered or lowered.startswith(("from:", "to:", "sent:")):
            continue
        useful_lines.append(line)
    cleaned = " ".join(useful_lines)
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    summary = " ".join(sentences[:2]).strip()
    return (summary or "Response received; synthesis pending.")[:220]


async def _reconcile_gmail_account(
    settings: Settings, account_id: int, *, days: int = 365
) -> dict[str, object]:
    """Persist messages for one connected Gmail account."""
    token = await get_google_access_token(settings, account_id)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    with SessionLocal() as session:
        venue_ids = [item for item in session.scalars(select(Venue.id)).all()]

    storage = SpacesStorage(settings) if settings.spaces_configured else None
    sent = replies = new_messages = 0
    attachments_mirrored = attachments_skipped = attachment_failures = 0
    for venue_id in venue_ids:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            if venue is None:
                continue
            venue_email = venue.email
            has_history_here = session.scalar(
                select(Message.id).where(
                    Message.venue_id == venue_id,
                    Message.gmail_account_id == account_id,
                ).limit(1)
            ) is not None
        # The first time a venue is checked in a mailbox, look a full year back
        # so earlier conversations (for example in the personal mailbox) are
        # attached; afterwards the short window keeps each run cheap.
        search_days = days if has_history_here else max(days, HISTORICAL_SEARCH_DAYS)
        ids = await gmail.search_message_ids(
            f"in:anywhere newer_than:{search_days}d "
            f"{{to:{venue_email} from:{venue_email}}}",
            max_results=100,
        )
        messages_by_id = {
            message.message_id: message
            for message in [await gmail.get_message(message_id) for message_id in ids]
        }
        known_thread_ids = {
            message.thread_id
            for message in messages_by_id.values()
            if _is_outgoing(message, venue_email)
        }
        with SessionLocal() as session:
            known_thread_ids.update(
                session.scalars(
                    select(Outreach.gmail_thread_id).where(
                        Outreach.venue_id == venue_id,
                        Outreach.gmail_account_id == account_id,
                    )
                ).all()
            )
            known_thread_ids.update(
                session.scalars(
                    select(Message.gmail_thread_id).where(
                        Message.venue_id == venue_id,
                        Message.gmail_account_id == account_id,
                        Message.direction == "outbound",
                    )
                ).all()
            )
        # A venue employee may reply from a personal address rather than the
        # public contact address. Once our exact-address outbound message has
        # established the Gmail thread, ingest replies from that whole thread.
        for thread_id in known_thread_ids:
            thread = await gmail.get_thread(thread_id)
            messages_by_id.update(
                {message.message_id: message for message in thread.messages}
            )
        messages = list(messages_by_id.values())
        messages.sort(key=lambda item: item.received_at)
        for message in messages:
            outgoing = _is_outgoing(message, venue_email, known_thread_ids)
            incoming = _is_incoming(message, venue_email, known_thread_ids)
            if not outgoing and not incoming:
                continue
            with SessionLocal() as session:
                stored_message = session.scalar(
                    select(Message).where(
                        Message.gmail_message_id == message.message_id
                    )
                )
                stored_message_id = stored_message.id if stored_message else None
                if (
                    stored_message is not None
                    and stored_message.direction == "inbound"
                    and not stored_message.sender_email
                ):
                    # Backfill the exact reply-to address for older rows so
                    # reply previews and sends agree.
                    stored_message.sender_email = _sender_address(message)
                    session.commit()
            if stored_message_id is None:
                synthesis = ResponseSynthesis(summary="Message sent.")
                status = ""
                if incoming:
                    with SessionLocal() as session:
                        venue = session.get(Venue, venue_id)
                        assert venue is not None
                        synthesis, status = await _synthesize(settings, message, venue)
                with SessionLocal() as session:
                    venue = session.get(Venue, venue_id)
                    assert venue is not None
                    stored_message = Message(
                        venue_id=venue_id,
                        gmail_message_id=message.message_id,
                        gmail_thread_id=message.thread_id,
                        gmail_account_id=account_id,
                        rfc_message_id=message.rfc_message_id or "",
                        direction="outbound" if outgoing else "inbound",
                        sender_email="" if outgoing else _sender_address(message),
                        subject=message.subject,
                        body=message.body,
                        synthesized_summary=synthesis.summary if incoming else "",
                        occurred_at=_when(message.received_at),
                    )
                    session.add(stored_message)
                    session.flush()
                    stored_message_id = stored_message.id
                    if outgoing:
                        if not session.scalar(
                            select(Outreach).where(
                                Outreach.gmail_message_id == message.message_id
                            )
                        ):
                            session.add(
                                Outreach(
                                    venue_id=venue_id,
                                    gmail_message_id=message.message_id,
                                    gmail_thread_id=message.thread_id,
                                    gmail_account_id=account_id,
                                    sent_at=_when(message.received_at),
                                )
                            )
                        prior_inbound = session.scalar(
                            select(Message.id).where(
                                Message.venue_id == venue_id,
                                Message.direction == "inbound",
                                Message.occurred_at < _when(message.received_at),
                            )
                        )
                        venue.status = "Responded to venue" if prior_inbound else "Sent"
                        sent += 1
                    else:
                        venue.status = status
                        venue.response_summary = synthesis.summary
                        _save_estimate(session, venue_id, message.message_id, synthesis)
                        replies += 1
                    session.commit()
                    new_messages += 1

            assert stored_message_id is not None
            result = await _mirror_message_attachments(
                gmail=gmail,
                storage=storage,
                venue_id=venue_id,
                stored_message_id=stored_message_id,
                account_id=account_id,
                message=message,
            )
            attachments_mirrored += result["mirrored"]
            attachments_skipped += result["skipped"]
            attachment_failures += result["failed"]
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            assert venue is not None
            latest_outbound = session.scalar(
                select(Message)
                .where(Message.venue_id == venue_id, Message.direction == "outbound")
                .order_by(Message.occurred_at.desc())
            )
            latest_reply = session.scalar(
                select(Message)
                .where(Message.venue_id == venue_id, Message.direction == "inbound")
                .order_by(Message.occurred_at.desc())
            )
            if latest_reply:
                venue.response_summary = latest_reply.synthesized_summary
                if latest_outbound and latest_outbound.occurred_at > latest_reply.occurred_at:
                    venue.status = "Responded to venue"
                elif venue.status == "Needs reply":
                    venue.status = "More info needed"
                elif venue.status in {"Sent", "Existing conversation"}:
                    venue.status = "Responded"
                session.commit()
    return {
        "new_messages": new_messages,
        "sent_confirmed": sent,
        "replies_synthesized": replies,
        "attachments_mirrored": attachments_mirrored,
        "attachments_skipped": attachments_skipped,
        "attachment_failures": attachment_failures,
    }


async def _mirror_message_attachments(
    *,
    gmail: GmailClient,
    storage: SpacesStorage | None,
    venue_id: int,
    stored_message_id: int,
    account_id: int,
    message: GmailMessage,
) -> dict[str, int]:
    """Mirror each Gmail attachment once, including for previously known messages."""
    counts = {"mirrored": 0, "skipped": 0, "failed": 0}
    for gmail_attachment in message.attachments:
        with SessionLocal() as session:
            exists = session.scalar(
                select(Attachment.id).where(
                    Attachment.gmail_account_id == account_id,
                    Attachment.gmail_message_id == message.message_id,
                    Attachment.gmail_attachment_id
                    == gmail_attachment.attachment_id,
                )
            )
        if exists is not None:
            counts["skipped"] += 1
            continue
        if storage is None:
            counts["skipped"] += 1
            continue
        try:
            data = await gmail.get_attachment(gmail_attachment)
            stored = await asyncio.to_thread(
                storage.put_attachment,
                venue_id=venue_id,
                gmail_message_id=message.message_id,
                gmail_attachment_id=gmail_attachment.attachment_id,
                filename=gmail_attachment.filename,
                content_type=gmail_attachment.mime_type,
                data=data,
            )
            with SessionLocal() as session:
                session.add(
                    Attachment(
                        venue_id=venue_id,
                        message_id=stored_message_id,
                        gmail_account_id=account_id,
                        gmail_message_id=message.message_id,
                        gmail_attachment_id=gmail_attachment.attachment_id,
                        object_key=stored.object_key,
                        original_filename=gmail_attachment.filename,
                        content_type=(
                            gmail_attachment.mime_type or "application/octet-stream"
                        ),
                        byte_size=stored.byte_size,
                        sha256=stored.sha256,
                    )
                )
                session.commit()
            counts["mirrored"] += 1
        except (
            AttachmentTooLargeError,
            BotoCoreError,
            ClientError,
            httpx.HTTPError,
        ):
            counts["failed"] += 1
    return counts


def sync_error_message(exc: BaseException) -> str:
    """Describe one mailbox failure for the dashboard without leaking data."""
    if isinstance(exc, GoogleCredentialError):
        return str(exc)
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        if status_code in {401, 403}:
            return (
                f"Gmail refused access (HTTP {status_code}). Reconnect this "
                "mailbox if it keeps happening."
            )
        if status_code == 429:
            return "Gmail is rate limiting this mailbox; the next run will retry."
        return f"Gmail returned HTTP {status_code}; the next run will retry."
    if isinstance(exc, httpx.HTTPError):
        return "Gmail could not be reached; the next run will retry."
    if isinstance(exc, GoogleAuthError):
        return "Google could not refresh the sign-in; the next run will retry."
    return f"{type(exc).__name__} while checking this mailbox; the next run will retry."


async def reconcile_gmail_database(
    settings: Settings, *, days: int = 365
) -> dict[str, object]:
    """Reconcile every connected Gmail account into one shared dashboard.

    Each mailbox is reconciled independently. A failure on one account is
    recorded in ``gmail_sync_status`` and the remaining accounts still run, so
    an expired token on the personal mailbox cannot hide replies arriving in
    the shared wedding mailbox. ``gmail_last_refresh`` advances whenever at
    least one mailbox synchronized successfully.
    """
    accounts = list_google_accounts()
    if not accounts:
        raise FileNotFoundError("No Google OAuth credential is stored in the database.")
    totals = {
        "new_messages": 0,
        "sent_confirmed": 0,
        "replies_synthesized": 0,
        "attachments_mirrored": 0,
        "attachments_skipped": 0,
        "attachment_failures": 0,
    }
    with SessionLocal() as session:
        previous = sync_status_payload(session) or {}
        previous_refresh = get_system_state(session, LAST_REFRESH_KEY)
    previous_accounts = {
        str(item["email"]): item for item in previous.get("accounts", [])
    }
    synced_accounts: list[str] = []
    failed_accounts: list[dict[str, str]] = []
    account_states: list[dict[str, object]] = []
    for account in accounts:
        email = str(account["email"])
        checked_at = iso_utc(datetime.now(UTC))
        state: dict[str, object] = {
            "email": email,
            "is_primary": bool(account.get("is_primary")),
            "last_checked_at": checked_at,
            "last_success_at": previous_accounts.get(email, {}).get("last_success_at"),
        }
        try:
            result = await _reconcile_gmail_account(
                settings, int(account["id"]), days=days
            )
        except ACCOUNT_SYNC_ERRORS as exc:
            error = sync_error_message(exc)
            failed_accounts.append({"email": email, "error": error})
            state.update({"status": "failed", "error": error})
            account_states.append(state)
            continue
        for key in totals:
            totals[key] += int(result[key])
        synced_accounts.append(email)
        state.update(
            {
                "status": "ok",
                "error": None,
                "last_success_at": iso_utc(datetime.now(UTC)),
                "new_messages": int(result["new_messages"]),
                "attachment_failures": int(result["attachment_failures"]),
            }
        )
        account_states.append(state)
    completed_at = datetime.now(UTC)
    last_refreshed_at = iso_utc(completed_at) if synced_accounts else previous_refresh
    sync_status: dict[str, object] = {
        "completed_at": iso_utc(completed_at),
        "accounts": account_states,
        "failed_count": len(failed_accounts),
        **totals,
    }
    with SessionLocal() as session:
        if synced_accounts:
            set_system_state(session, LAST_REFRESH_KEY, iso_utc(completed_at))
        set_system_state(session, SYNC_STATUS_KEY, json.dumps(sync_status))
    return {
        **totals,
        "accounts_synced": synced_accounts,
        "accounts_failed": failed_accounts,
        "last_refreshed_at": last_refreshed_at,
        "sync_status": sync_status,
    }


def _reply_subject(subject: str) -> str:
    subject = subject or OUTREACH_SUBJECT
    if subject.casefold().startswith(("re:", "r:")):
        return subject
    return f"Re: {subject}"


def _latest_inbound(session, venue_id: int) -> Message | None:
    return session.scalar(
        select(Message)
        .where(Message.venue_id == venue_id, Message.direction == "inbound")
        .order_by(Message.occurred_at.desc())
    )


def _account_email(session, account_id: int | None) -> str | None:
    if account_id is None:
        return None
    account = session.get(GoogleAccount, account_id)
    return account.email if account else None


def followup_preview(venue_id: int) -> dict[str, object]:
    """Prepare, but do not send, a reply to the latest venue response.

    The recipient, subject, and sending mailbox shown here are exactly the
    values ``reply_to_venue`` uses, so what the couple approves is what goes.
    """
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        latest = _latest_inbound(session, venue_id)
        if latest is None:
            raise ValueError("This venue has not replied yet.")
        return {
            "id": venue.id,
            "venue": venue.name,
            "recipient": latest.sender_email or venue.email,
            "subject": _reply_subject(latest.subject),
            "gmail_account_email": _account_email(session, latest.gmail_account_id),
            "response_summary": venue.response_summary,
            "body": FOLLOWUP_BODY,
        }


def update_venue_research(
    venue_id: int,
    *,
    source_type: str,
    source_url: str,
    contact_name: str,
    notes: str,
) -> dict[str, object]:
    """Store human research separately from official Gmail/quote data."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        venue.research_source_type = source_type.strip()
        venue.research_source_url = source_url.strip()
        venue.research_contact_name = contact_name.strip()
        venue.research_notes = notes.strip()
        venue.research_updated_at = datetime.now(UTC)
        session.commit()
        return {"id": venue.id, "saved": True}


async def reply_to_venue(settings: Settings, venue_id: int, body: str) -> dict[str, object]:
    """Send an explicit human-written reply to the venue's latest message."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        latest = _latest_inbound(session, venue_id)
        if latest is None:
            raise ValueError("This venue has not replied yet.")
        latest_id = latest.gmail_message_id
        thread_id = latest.gmail_thread_id
        account_id = latest.gmail_account_id
        recipient = latest.sender_email or venue.email
        subject = _reply_subject(latest.subject)
    token = await get_google_access_token(settings, account_id)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    source = await gmail.get_message(latest_id)
    result = await gmail.send_reply(
        recipient=recipient,
        subject=subject,
        body=body.strip(),
        thread_id=thread_id,
        in_reply_to=source.rfc_message_id,
        references=source.references,
    )
    now = datetime.now(UTC)
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        assert venue is not None
        venue.status = "Responded to venue"
        session.add(Message(
            venue_id=venue_id,
            gmail_message_id=result.message_id,
            gmail_thread_id=result.thread_id,
            gmail_account_id=account_id,
            direction="outbound",
            kind="reply",
            subject=subject,
            body=body.strip(),
            synthesized_summary="",
            occurred_at=now,
        ))
        session.commit()
    return {"sent": True, "status": "Responded to venue"}


def _reminder_anchor(session, venue_id: int) -> tuple[Message | None, Outreach | None]:
    """Return the latest message we sent (the thread a reminder continues)."""
    latest_outbound = session.scalar(
        select(Message)
        .where(Message.venue_id == venue_id, Message.direction == "outbound")
        .order_by(Message.occurred_at.desc())
    )
    latest_outreach = session.scalar(
        select(Outreach)
        .where(Outreach.venue_id == venue_id)
        .order_by(Outreach.sent_at.desc())
    )
    if latest_outbound is None and latest_outreach is None:
        return None, None
    if latest_outbound is None:
        return None, latest_outreach
    if latest_outreach is None or latest_outbound.occurred_at >= latest_outreach.sent_at:
        return latest_outbound, None
    return None, latest_outreach


def reminder_preview(venue_id: int) -> dict[str, object]:
    """Prepare, but do not send, a polite reminder in the existing thread."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        anchor_message, anchor_outreach = _reminder_anchor(session, venue_id)
        if anchor_message is None and anchor_outreach is None:
            raise ValueError("No inquiry has been sent to this venue yet.")
        latest_inbound = _latest_inbound(session, venue_id)
        account_id = (
            anchor_message.gmail_account_id
            if anchor_message is not None
            else anchor_outreach.gmail_account_id
        )
        subject_source = (
            anchor_message.subject if anchor_message is not None else OUTREACH_SUBJECT
        )
        return {
            "id": venue.id,
            "venue": venue.name,
            "recipient": (
                latest_inbound.sender_email if latest_inbound and latest_inbound.sender_email
                else venue.email
            ),
            "subject": _reply_subject(subject_source),
            "gmail_account_email": _account_email(session, account_id),
            "body": REMINDER_BODY,
        }


async def send_venue_reminder(
    settings: Settings, venue_id: int, body: str
) -> dict[str, object]:
    """Send an explicit reminder inside the thread and mailbox we already used."""
    preview = reminder_preview(venue_id)
    with SessionLocal() as session:
        anchor_message, anchor_outreach = _reminder_anchor(session, venue_id)
        assert anchor_message is not None or anchor_outreach is not None
        anchor_gmail_id = (
            anchor_message.gmail_message_id
            if anchor_message is not None
            else anchor_outreach.gmail_message_id
        )
        thread_id = (
            anchor_message.gmail_thread_id
            if anchor_message is not None
            else anchor_outreach.gmail_thread_id
        )
        account_id = (
            anchor_message.gmail_account_id
            if anchor_message is not None
            else anchor_outreach.gmail_account_id
        )
    token = await get_google_access_token(settings, account_id)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    source = await gmail.get_message(anchor_gmail_id)
    result = await gmail.send_reply(
        recipient=str(preview["recipient"]),
        subject=str(preview["subject"]),
        body=body.strip(),
        thread_id=thread_id,
        in_reply_to=source.rfc_message_id,
        references=source.references,
    )
    now = datetime.now(UTC)
    with SessionLocal() as session:
        session.add(Message(
            venue_id=venue_id,
            gmail_message_id=result.message_id,
            gmail_thread_id=result.thread_id,
            gmail_account_id=account_id,
            direction="outbound",
            kind="reminder",
            subject=str(preview["subject"]),
            body=body.strip(),
            synthesized_summary="",
            occurred_at=now,
        ))
        session.commit()
    return {"sent": True, "reminder_sent_at": iso_utc(now)}


async def draft_reply(settings: Settings, venue_id: int, points: str) -> dict[str, object]:
    """Ask Kimi for an Italian draft from English points; never sends anything."""
    if not settings.inference_configured:
        raise InferenceUnavailableError(
            "Reply drafting needs the Kimi model configuration. Write the reply directly."
        )
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        venue_name = venue.name
        summary = venue.response_summary or ""
    try:
        body = await asyncio.wait_for(
            DigitalOceanInferenceClient(settings).draft_reply(
                venue=venue_name, latest_summary=summary, points=points
            ),
            timeout=45,
        )
    except (TimeoutError, httpx.HTTPError, InvalidInferenceResponseError) as exc:
        raise InferenceUnavailableError(
            "The drafting model did not answer. Try again or write the reply directly."
        ) from exc
    return {"id": venue_id, "body": body}


class InferenceUnavailableError(RuntimeError):
    """Kimi is not configured or did not answer; the user can write by hand."""


def _parse_visit(value: str) -> datetime | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def update_venue(venue_id: int, **fields: object) -> dict[str, object]:
    """Edit venue details or record a decision; ``None`` leaves a field alone."""
    text_fields = {
        "name", "region", "location", "website", "phone", "notes",
        "guest_capacity", "availability", "vibe",
    }
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        email = fields.get("email")
        if isinstance(email, str):
            normalized = email.strip().casefold()
            clash = session.scalar(
                select(Venue.id).where(Venue.email == normalized, Venue.id != venue_id)
            )
            if clash is not None:
                raise VenueConflictError(
                    "Another venue already uses that e-mail address."
                )
            venue.email = normalized
        for name in text_fields:
            value = fields.get(name)
            if isinstance(value, str):
                setattr(venue, name, value.strip())
        decision = fields.get("decision")
        if isinstance(decision, str):
            if decision not in DECISIONS:
                raise ValueError("Unknown decision.")
            venue.decision = decision
        visit = fields.get("visit_at")
        if isinstance(visit, str):
            try:
                venue.visit_at = _parse_visit(visit)
            except ValueError as exc:
                raise ValueError("Enter the visit as a date, e.g. 2026-10-12.") from exc
        session.commit()
        return venue_detail_payload(session, venue)


def venue_detail(venue_id: int) -> dict[str, object]:
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        return venue_detail_payload(session, venue)


def delete_venue(venue_id: int) -> dict[str, object]:
    """Remove a venue that never had any correspondence; history is kept."""
    with SessionLocal() as session:
        venue = session.get(Venue, venue_id)
        if venue is None:
            raise ValueError("Venue not found.")
        if venue.outreach or venue.messages or venue.attachments:
            raise VenueConflictError(
                "This venue has Gmail history. Mark it as passed instead of deleting it."
            )
        session.delete(venue)
        session.commit()
        return {"id": venue_id, "deleted": True}


def update_preferences(*, budget_eur: float | None) -> dict[str, object]:
    with SessionLocal() as session:
        if budget_eur is not None:
            set_system_state(session, BUDGET_KEY, str(round(float(budget_eur))))
        return preferences_payload(session)


async def backfill_response_insights(settings: Settings) -> dict[str, int]:
    """Re-run bounded English synthesis for existing latest replies."""
    token = await get_google_access_token(settings)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    updated = 0
    with SessionLocal() as session:
        venue_ids = session.scalars(select(Venue.id)).all()
    for venue_id in venue_ids:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            latest = session.scalar(
                select(Message)
                .where(Message.venue_id == venue_id, Message.direction == "inbound")
                .order_by(Message.occurred_at.desc())
            )
            if venue is None or latest is None:
                continue
            message_id = latest.gmail_message_id
        message = await gmail.get_message(message_id)
        synthesis, status = await _synthesize(settings, message, venue)
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            latest = session.scalar(select(Message).where(Message.gmail_message_id == message_id))
            assert venue is not None and latest is not None
            fallback_used = synthesis.summary.startswith(
                "Response received; English synthesis is temporarily unavailable."
            )
            if not fallback_used or not venue.response_summary:
                venue.response_summary = synthesis.summary
                latest.synthesized_summary = synthesis.summary
            if not fallback_used:
                venue.status = status
            _save_estimate(session, venue_id, message_id, synthesis)
            session.commit()
            updated += 1
    return {"updated": updated}
