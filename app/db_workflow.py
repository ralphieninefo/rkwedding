"""Sheet import, Gmail reconciliation, and concise response synthesis."""

import asyncio
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
import re

import httpx
from sqlalchemy import select

from app.config import Settings
from app.database import Message, Outreach, SessionLocal, Venue, upsert_venue
from app.gmail import GmailClient, GmailMessage
from app.google_auth import get_google_access_token
from app.inference import DigitalOceanInferenceClient, InvalidInferenceResponseError
from app.sheets import GoogleSheetsClient
from app.workflow import OUTREACH_BODY, OUTREACH_SUBJECT


def _addresses(value: str) -> set[str]:
    return {address.casefold() for _, address in getaddresses([value]) if address}


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_outgoing(message: GmailMessage, venue_email: str) -> bool:
    return (
        "SENT" in message.label_ids
        and venue_email in _addresses(message.recipients)
    )


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


async def import_sheet_venues(settings: Settings) -> dict[str, int]:
    """Copy valid venue contacts from the existing Sheet into the app database."""
    if not settings.google_spreadsheet_id:
        raise ValueError("Google Sheet is not configured.")
    token = await get_google_access_token(settings)
    sheets = GoogleSheetsClient(token, settings.google_spreadsheet_id)
    rows = await sheets.get_rows(settings.google_venues_sheet)
    imported = skipped = 0
    with SessionLocal() as session:
        for row in rows:
            email = row.get("Email", "").strip()
            if "@" not in email or " " in email:
                skipped += 1
                continue
            upsert_venue(
                session,
                name=row.get("Venue", email),
                email=email,
                location=row.get("Location", ""),
                website=row.get("Website", ""),
                phone=row.get("Phone", ""),
            )
            imported += 1
    return {"imported": imported, "skipped": skipped}


async def create_venue_and_optionally_send(
    settings: Settings,
    *,
    name: str,
    email: str,
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
            location=location,
            website=website,
            phone=phone,
        )
        venue_id = venue.id
    if not send_now:
        return {"id": venue_id, "status": "Draft", "sent": False}

    token = await get_google_access_token(settings)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    existing = await gmail.search_message_ids(
        f"in:anywhere {{to:{email} from:{email}}}", max_results=1
    )
    if existing:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            assert venue is not None
            venue.status = "Existing conversation"
            session.commit()
        return {"id": venue_id, "status": "Existing conversation", "sent": False}

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
                sent_at=now,
            )
        )
        session.commit()
    return {"id": venue_id, "status": "Sent", "sent": True}


async def _synthesize(
    settings: Settings, message: GmailMessage, venue: Venue
) -> tuple[str, str]:
    fallback = _fallback_summary(message.body or message.subject)
    if not settings.inference_configured or not (message.body or message.subject):
        return fallback, "Responded"
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
            "needs_reply": "Needs reply",
        }.get(synthesis.status, "Responded")
        return synthesis.summary, status
    except (
        TimeoutError,
        httpx.HTTPError,
        InvalidInferenceResponseError,
        ValueError,
    ):
        return fallback, "Responded"


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


async def reconcile_gmail_database(
    settings: Settings, *, days: int = 365
) -> dict[str, int]:
    """Persist new sent/reply messages once and synthesize replies for the UI."""
    token = await get_google_access_token(settings)
    gmail = GmailClient(token, settings.google_gmail_user_id)
    with SessionLocal() as session:
        venue_ids = [item for item in session.scalars(select(Venue.id)).all()]

    sent = replies = new_messages = 0
    for venue_id in venue_ids:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            if venue is None:
                continue
            venue_email = venue.email
        ids = await gmail.search_message_ids(
            f"in:anywhere newer_than:{days}d {{to:{venue_email} from:{venue_email}}}",
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
                        Outreach.venue_id == venue_id
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
            outgoing = _is_outgoing(message, venue_email)
            incoming = _is_incoming(message, venue_email, known_thread_ids)
            if not outgoing and not incoming:
                continue
            with SessionLocal() as session:
                if session.scalar(
                    select(Message).where(Message.gmail_message_id == message.message_id)
                ):
                    continue
            summary = status = ""
            if incoming:
                with SessionLocal() as session:
                    venue = session.get(Venue, venue_id)
                    assert venue is not None
                    summary, status = await _synthesize(settings, message, venue)
            with SessionLocal() as session:
                venue = session.get(Venue, venue_id)
                assert venue is not None
                session.add(
                    Message(
                        venue_id=venue_id,
                        gmail_message_id=message.message_id,
                        gmail_thread_id=message.thread_id,
                        direction="outbound" if outgoing else "inbound",
                        subject=message.subject,
                        body=message.body,
                        synthesized_summary=summary,
                        occurred_at=_when(message.received_at),
                    )
                )
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
                                sent_at=_when(message.received_at),
                            )
                        )
                    if venue.status in {"Draft", "Sent", "Existing conversation"}:
                        venue.status = "Sent"
                    sent += 1
                else:
                    venue.status = status
                    venue.response_summary = summary
                    replies += 1
                session.commit()
                new_messages += 1
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            assert venue is not None
            latest_reply = session.scalar(
                select(Message)
                .where(Message.venue_id == venue_id, Message.direction == "inbound")
                .order_by(Message.occurred_at.desc())
            )
            if latest_reply:
                venue.response_summary = latest_reply.synthesized_summary
                if venue.status == "Sent":
                    venue.status = "Responded"
                session.commit()
    return {"new_messages": new_messages, "sent_confirmed": sent, "replies_synthesized": replies}
