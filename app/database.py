"""Database models and small repository helpers for the control center."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    selectinload,
    sessionmaker,
)

from app.config import get_settings
from app.venue_state import STAGE_ORDER, derive_state

# SystemState keys written by the scheduled Gmail reconciliation.
LAST_REFRESH_KEY = "gmail_last_refresh"
SYNC_STATUS_KEY = "gmail_sync_status"
# The inquiry template asks for roughly this many guests.
GUEST_COUNT = 90


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime) -> str:
    """Serialize SQLite's naive UTC values unambiguously for the browser."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    region: Mapped[str] = mapped_column(String(250), default="")
    location: Mapped[str] = mapped_column(String(250), default="")
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    website: Mapped[str] = mapped_column(String(500), default="")
    phone: Mapped[str] = mapped_column(String(100), default="")
    vibe: Mapped[str] = mapped_column(String(250), default="")
    guest_capacity: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    research_source_type: Mapped[str] = mapped_column(String(100), default="")
    research_source_url: Mapped[str] = mapped_column(String(1000), default="")
    research_contact_name: Mapped[str] = mapped_column(String(250), default="")
    research_notes: Mapped[str] = mapped_column(Text, default="")
    research_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), default="Draft")
    # The couple's own decision: "", "shortlisted", or "passed".
    decision: Mapped[str] = mapped_column(String(30), default="")
    # 1 = favourite; only meaningful while decision == "shortlisted".
    shortlist_rank: Mapped[int | None] = mapped_column(nullable=True)
    visit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Availability for the requested dates, extracted from replies or typed.
    availability: Mapped[str] = mapped_column(String(500), default="")
    response_summary: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    outreach: Mapped[list["Outreach"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="venue", cascade="all, delete-orphan"
    )
    estimate: Mapped["PriceEstimate | None"] = relationship(
        back_populates="venue", cascade="all, delete-orphan", uselist=False
    )


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(100), unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(100), index=True)
    gmail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("google_accounts.id"), nullable=True, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[Venue] = relationship(back_populates="outreach")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(100), unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(100), index=True)
    gmail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("google_accounts.id"), nullable=True, index=True
    )
    rfc_message_id: Mapped[str] = mapped_column(String(500), default="", index=True)
    direction: Mapped[str] = mapped_column(String(20))
    # "inquiry", "reply", or "reminder" for messages the app sent; "" when the
    # message was discovered in Gmail.
    kind: Mapped[str] = mapped_column(String(30), default="")
    # Address the inbound message came from (may differ from the venue's
    # public contact address); the exact recipient for a reply.
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    synthesized_summary: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[Venue] = relationship(back_populates="messages")
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class Attachment(Base):
    """Metadata for one Gmail attachment mirrored into private Spaces storage."""

    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint(
            "gmail_account_id",
            "gmail_message_id",
            "gmail_attachment_id",
            name="uq_gmail_attachment_source",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id"), index=True)
    gmail_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("google_accounts.id"), nullable=True, index=True
    )
    gmail_message_id: Mapped[str] = mapped_column(String(100), index=True)
    gmail_attachment_id: Mapped[str] = mapped_column(String(1000))
    object_key: Mapped[str] = mapped_column(String(1500), unique=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(250), default="application/octet-stream")
    byte_size: Mapped[int] = mapped_column(default=0)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(50), default="gmail")
    # Embedded text of PDF quotes, used for synthesis; empty for scans/images.
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    venue: Mapped[Venue] = relationship(back_populates="attachments")
    message: Mapped[Message] = relationship(back_populates="attachments")


class PriceEstimate(Base):
    __tablename__ = "price_estimates"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), unique=True)
    source_message_id: Mapped[str] = mapped_column(String(100), default="")
    minimum_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    maximum_eur: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    venue: Mapped[Venue] = relationship(back_populates="estimate")


class SystemState(Base):
    __tablename__ = "system_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class GoogleAccount(Base):
    __tablename__ = "google_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    token_json: Mapped[str] = mapped_column(Text)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _engine():
    url = _database_url()
    if url.startswith("sqlite") and get_settings().app_env.casefold() != "local":
        raise RuntimeError(
            "Production requires a PostgreSQL DATABASE_URL; refusing to use "
            "ephemeral SQLite storage when APP_ENV is not local."
        )
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )


ENGINE = _engine()
SessionLocal = sessionmaker(bind=ENGINE, expire_on_commit=False)


def init_database() -> None:
    Base.metadata.create_all(ENGINE)
    columns = {column["name"] for column in inspect(ENGINE).get_columns("venues")}
    additions = {
        "region": "VARCHAR(250) DEFAULT ''",
        "vibe": "VARCHAR(250) DEFAULT ''",
        "guest_capacity": "VARCHAR(100) DEFAULT ''",
        "notes": "TEXT DEFAULT ''",
        "research_source_type": "VARCHAR(100) DEFAULT ''",
        "research_source_url": "VARCHAR(1000) DEFAULT ''",
        "research_contact_name": "VARCHAR(250) DEFAULT ''",
        "research_notes": "TEXT DEFAULT ''",
        "research_updated_at": "TIMESTAMP NULL",
        "decision": "VARCHAR(30) DEFAULT ''",
        "shortlist_rank": "INTEGER NULL",
        "visit_at": "TIMESTAMP NULL",
        "availability": "VARCHAR(500) DEFAULT ''",
    }
    with ENGINE.begin() as connection:
        for name, definition in additions.items():
            if name in columns:
                continue
            connection.execute(
                text(f"ALTER TABLE venues ADD COLUMN {name} {definition}")
            )
        table_additions = {
            "outreach": {"gmail_account_id": "INTEGER NULL"},
            "messages": {
                "gmail_account_id": "INTEGER NULL",
                "rfc_message_id": "VARCHAR(500) DEFAULT ''",
                "kind": "VARCHAR(30) DEFAULT ''",
                "sender_email": "VARCHAR(320) DEFAULT ''",
            },
            "attachments": {"extracted_text": "TEXT DEFAULT ''"},
        }
        for table_name, requested in table_additions.items():
            existing = {
                column["name"]
                for column in inspect(ENGINE).get_columns(table_name)
            }
            for name, definition in requested.items():
                if name not in existing:
                    connection.execute(
                        text(
                            f"ALTER TABLE {table_name} ADD COLUMN "
                            f"{name} {definition}"
                        )
                    )


def session_scope() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def upsert_venue(
    session: Session,
    *,
    name: str,
    email: str,
    region: str = "",
    location: str = "",
    website: str = "",
    phone: str = "",
    vibe: str = "",
    guest_capacity: str = "",
    notes: str = "",
) -> Venue:
    normalized = email.strip().casefold()
    venue = session.scalar(select(Venue).where(Venue.email == normalized))
    if venue is None:
        venue = Venue(name=name.strip(), email=normalized)
        session.add(venue)
    venue.name = name.strip()
    venue.region = region.strip()
    venue.location = location.strip()
    venue.website = website.strip()
    venue.phone = phone.strip()
    venue.vibe = vibe.strip()
    venue.guest_capacity = guest_capacity.strip()
    venue.notes = notes.strip()
    session.commit()
    return venue


class AccountDirectory:
    """Cached Gmail account lookups so one page load does not query per row."""

    def __init__(self, emails: dict[int, str], preferred_account_id: int | None):
        self.emails = emails
        self.preferred_account_id = preferred_account_id

    @classmethod
    def load(cls, session: Session) -> "AccountDirectory":
        emails = {
            account.id: account.email
            for account in session.scalars(select(GoogleAccount)).all()
        }
        preferred_email = get_settings().google_primary_email.strip().casefold()
        preferred_id = next(
            (
                account_id
                for account_id, email in emails.items()
                if email.casefold() == preferred_email
            ),
            None,
        ) if preferred_email else None
        return cls(emails, preferred_id)

    def email_for(self, account_id: int | None) -> str | None:
        if account_id is None:
            return None
        return self.emails.get(account_id)


def _fallback_directory() -> AccountDirectory:
    with SessionLocal() as session:
        return AccountDirectory.load(session)


def _item_time(item: "Message | Outreach") -> datetime:
    return item.occurred_at if isinstance(item, Message) else item.sent_at


def venue_payload(
    venue: Venue,
    accounts: AccountDirectory | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    """Summarize one venue for the queue: derived state, no full email bodies."""
    accounts = accounts or _fallback_directory()
    first_outreach = min(
        venue.outreach, key=lambda item: item.sent_at, default=None
    )
    latest_outreach = max(
        venue.outreach, key=lambda item: item.sent_at, default=None
    )
    inbound = [item for item in venue.messages if item.direction == "inbound"]
    outbound = [item for item in venue.messages if item.direction == "outbound"]
    latest_reply = max(inbound, key=lambda item: item.occurred_at, default=None)
    outbound_times = [
        *[item.sent_at for item in venue.outreach],
        *[item.occurred_at for item in outbound],
    ]
    latest_outbound_at = max(outbound_times, default=None)
    reminders = [item for item in outbound if item.kind == "reminder"]
    last_reminder = max(reminders, key=lambda item: item.occurred_at, default=None)
    activity_times = [*outbound_times, *[item.occurred_at for item in inbound]]
    latest_activity = max(activity_times, default=None)
    gmail_item = _preferred_gmail_item(venue, latest_reply, latest_outreach, accounts)
    gmail_thread_id = gmail_item.gmail_thread_id if gmail_item else None
    state = derive_state(
        status=venue.status or "",
        decision=venue.decision or "",
        latest_inbound_at=latest_reply.occurred_at if latest_reply else None,
        latest_outbound_at=latest_outbound_at,
        last_reminder_at=last_reminder.occurred_at if last_reminder else None,
        visit_at=venue.visit_at,
        now=now,
    )
    return {
        "id": venue.id,
        "name": venue.name,
        "region": venue.region,
        "location": venue.location,
        "email": venue.email,
        "website": venue.website,
        "phone": venue.phone,
        "vibe": venue.vibe,
        "guest_capacity": venue.guest_capacity,
        "availability": venue.availability or "",
        "notes": venue.notes,
        "research_source_type": venue.research_source_type,
        "research_source_url": venue.research_source_url,
        "research_contact_name": venue.research_contact_name,
        "research_notes": venue.research_notes,
        "research_updated_at": (
            iso_utc(venue.research_updated_at)
            if venue.research_updated_at else None
        ),
        "status": venue.status,
        "decision": venue.decision or "",
        "shortlist_rank": venue.shortlist_rank,
        "visit_at": iso_utc(venue.visit_at) if venue.visit_at else None,
        "stage": state.stage,
        "stage_label": state.stage_label,
        "plain_status": state.plain_status,
        "next_action": state.next_action,
        "next_action_label": state.next_action_label,
        "attention": state.attention,
        "waiting_days": state.waiting_days,
        "days_since_activity": state.days_since_activity,
        "created_at": iso_utc(venue.created_at) if venue.created_at else None,
        "last_activity_at": iso_utc(latest_activity) if latest_activity else None,
        "sent_at": iso_utc(first_outreach.sent_at) if first_outreach else None,
        "responded_at": iso_utc(latest_reply.occurred_at) if latest_reply else None,
        "last_reminder_at": (
            iso_utc(last_reminder.occurred_at) if last_reminder else None
        ),
        "message_count": len(venue.messages),
        "inbound_count": len(inbound),
        "response_summary": venue.response_summary,
        "price_minimum_eur": venue.estimate.minimum_eur if venue.estimate else None,
        "price_maximum_eur": venue.estimate.maximum_eur if venue.estimate else None,
        "price_note": venue.estimate.note if venue.estimate else "",
        "gmail_url": _gmail_url(gmail_thread_id, gmail_item, None, accounts),
        "gmail_account_email": _gmail_account_email(gmail_item, accounts),
        "documents": [
            attachment_payload(item, accounts)
            for item in sorted(
                venue.attachments,
                key=lambda attachment: attachment.message.occurred_at,
                reverse=True,
            )
        ],
    }


def _snippet(value: str, limit: int = 140) -> str:
    """Return the first useful line of our own outbound text, shortened."""
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line and not line.casefold().startswith(("buongiorno", "gentile", "salve")):
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return ""


def message_payload(
    message: Message, accounts: AccountDirectory | None = None
) -> dict[str, object]:
    """Describe one message for the timeline without exposing venue bodies.

    Inbound messages expose only their English synthesis; outbound messages
    (written by the couple) expose a short first-line snippet.
    """
    accounts = accounts or _fallback_directory()
    inbound = message.direction == "inbound"
    return {
        "id": message.id,
        "direction": message.direction,
        "kind": message.kind or "",
        "occurred_at": iso_utc(message.occurred_at),
        "subject": message.subject,
        "summary": (
            message.synthesized_summary if inbound else _snippet(message.body or "")
        ),
        "sender_email": message.sender_email or "" if inbound else "",
        "gmail_account_email": _gmail_account_email(message, accounts),
        "gmail_url": _gmail_url(message.gmail_thread_id, message, None, accounts),
        "documents": [
            attachment_payload(item, accounts)
            for item in sorted(message.attachments, key=lambda item: item.id)
        ],
    }


def venue_detail_payload(
    session: Session, venue: Venue, *, now: datetime | None = None
) -> dict[str, object]:
    """Return the full dossier for one venue: summary plus a message timeline."""
    accounts = AccountDirectory.load(session)
    payload = venue_payload(venue, accounts, now=now)
    payload["messages"] = [
        message_payload(item, accounts)
        for item in sorted(venue.messages, key=lambda item: item.occurred_at, reverse=True)
    ]
    payload["outreach"] = [
        {
            "id": item.id,
            "sent_at": iso_utc(item.sent_at),
            "gmail_account_email": accounts.email_for(item.gmail_account_id),
            "gmail_url": _gmail_url(item.gmail_thread_id, item, None, accounts),
        }
        for item in sorted(venue.outreach, key=lambda item: item.sent_at, reverse=True)
    ]
    return payload


def attachment_payload(
    attachment: Attachment, accounts: AccountDirectory | None = None
) -> dict[str, object]:
    """Expose document metadata while keeping the private object key secret."""
    accounts = accounts or _fallback_directory()
    message = attachment.message
    return {
        "id": attachment.id,
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "byte_size": attachment.byte_size,
        "source": attachment.source,
        "has_text": bool(attachment.extracted_text),
        "subject": message.subject,
        "received_at": iso_utc(message.occurred_at),
        "view_url": f"/api/documents/{attachment.id}/view",
        "gdocs_url": (
            f"/api/documents/{attachment.id}/gdocs"
            if attachment.content_type == "application/pdf"
            else None
        ),
        "gmail_url": _gmail_url(message.gmail_thread_id, message, None, accounts),
        "gmail_account_email": _gmail_account_email(message, accounts),
    }


def _gmail_url(
    thread_id: str | None,
    latest_reply: Message | None,
    latest_outreach: Outreach | None,
    accounts: AccountDirectory | None = None,
) -> str | None:
    if thread_id is None:
        return None
    item = latest_reply or latest_outreach
    auth_user: str | None = None
    if item is not None and item.gmail_account_id is not None:
        if accounts is not None:
            auth_user = accounts.email_for(item.gmail_account_id)
        else:
            with SessionLocal() as session:
                account = session.get(GoogleAccount, item.gmail_account_id)
                if account is not None:
                    auth_user = account.email
    encoded_thread_id = quote(thread_id, safe="")
    if auth_user is None:
        return f"https://mail.google.com/mail/#all/{encoded_thread_id}"
    mailbox_url = (
        "https://mail.google.com/mail/?"
        f"{urlencode({'authuser': auth_user})}#all/{encoded_thread_id}"
    )
    return (
        "https://accounts.google.com/AccountChooser?"
        + urlencode({"Email": auth_user, "continue": mailbox_url})
    )


def _gmail_account_email(
    item: Message | Outreach | None, accounts: AccountDirectory | None = None
) -> str | None:
    if item is None or item.gmail_account_id is None:
        return None
    if accounts is not None:
        return accounts.email_for(item.gmail_account_id)
    with SessionLocal() as session:
        account = session.get(GoogleAccount, item.gmail_account_id)
        return account.email if account else None


def _preferred_gmail_item(
    venue: Venue,
    latest_reply: Message | None,
    latest_outreach: Outreach | None,
    accounts: AccountDirectory | None = None,
) -> Message | Outreach | None:
    """Prefer a thread owned by the configured sender when the venue has one."""
    accounts = accounts or _fallback_directory()
    preferred_account_id = accounts.preferred_account_id
    items: list[Message | Outreach] = [*venue.messages, *venue.outreach]
    if preferred_account_id is not None:
        preferred = [
            item for item in items
            if item.gmail_account_id == preferred_account_id
        ]
        if preferred:
            return max(preferred, key=_item_time)
    return latest_reply or latest_outreach


def list_venues(
    session: Session, *, now: datetime | None = None
) -> list[dict[str, object]]:
    accounts = AccountDirectory.load(session)
    venues = session.scalars(
        select(Venue)
        .order_by(Venue.name)
        .options(
            selectinload(Venue.messages).selectinload(Message.attachments),
            selectinload(Venue.outreach),
            selectinload(Venue.attachments),
            selectinload(Venue.estimate),
        )
    ).unique().all()
    return sort_venue_payloads([venue_payload(venue, accounts, now=now) for venue in venues])


def queue_summary(venues: list[dict[str, object]]) -> dict[str, object]:
    """Count venues per stage so the home screen can show a one-line overview."""
    counts = {stage: 0 for stage in STAGE_ORDER}
    for venue in venues:
        counts[str(venue["stage"])] = counts.get(str(venue["stage"]), 0) + 1
    return {
        "total": len(venues),
        "by_stage": counts,
        "attention": sum(1 for venue in venues if venue["attention"]),
    }


def dashboard_payload(session: Session) -> dict[str, object]:
    venues = list_venues(session)
    priced = [
        venue for venue in venues
        if venue["price_minimum_eur"] is not None
        or venue["price_maximum_eur"] is not None
    ]
    midpoints = [
        (
            float(venue["price_minimum_eur"] or venue["price_maximum_eur"])
            + float(venue["price_maximum_eur"] or venue["price_minimum_eur"])
        ) / 2
        for venue in priced
    ]
    state = session.get(SystemState, LAST_REFRESH_KEY)
    return {
        "venues": venues,
        "queue": queue_summary(venues),
        "last_refreshed_at": state.value if state else None,
        "sync_status": sync_status_payload(session),
        "preferences": preferences_payload(session),
        "price_overview": {
            "venue_count": len(priced),
            "average_eur": round(sum(midpoints) / len(midpoints)) if midpoints else None,
            "minimum_eur": round(min(
                float(venue["price_minimum_eur"] or venue["price_maximum_eur"])
                for venue in priced
            )) if priced else None,
            "maximum_eur": round(max(
                float(venue["price_maximum_eur"] or venue["price_minimum_eur"])
                for venue in priced
            )) if priced else None,
        },
    }


BUDGET_KEY = "budget_eur"


def preferences_payload(session: Session) -> dict[str, object]:
    """Small couple-level settings kept in SystemState (never secrets)."""
    raw = get_system_state(session, BUDGET_KEY)
    budget: float | None = None
    if raw:
        try:
            budget = float(raw)
        except ValueError:
            budget = None
    return {"budget_eur": budget, "guest_count": GUEST_COUNT}


def sync_status_payload(session: Session) -> dict[str, object] | None:
    """Expose the last scheduled-sync outcome so the UI can name a broken mailbox.

    The record contains mailbox addresses, timestamps, and short error text
    only; it never includes tokens, message bodies, or object keys.
    """
    raw = get_system_state(session, SYNC_STATUS_KEY)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(parsed, dict):
        return None
    raw_accounts = parsed.get("accounts")
    accounts = [
        item
        for item in (raw_accounts if isinstance(raw_accounts, list) else [])
        if isinstance(item, dict)
    ]
    return {
        "completed_at": parsed.get("completed_at"),
        "accounts": [
            {
                "email": item.get("email"),
                "is_primary": bool(item.get("is_primary")),
                "status": item.get("status"),
                "error": item.get("error"),
                "last_success_at": item.get("last_success_at"),
                "last_checked_at": item.get("last_checked_at"),
            }
            for item in accounts
        ],
        "failed_count": sum(1 for item in accounts if item.get("status") == "failed"),
    }


def clear_sync_failure(session: Session, email: str) -> bool:
    """Mark a mailbox as reconnected so the dashboard stops asking for it.

    The next scheduled run rewrites the whole record; until then the entry
    reads ``reconnected`` rather than ``failed``. Returns whether a failed
    entry for that mailbox existed.
    """
    status = sync_status_payload(session)
    if status is None:
        return False
    normalized = email.strip().casefold()
    cleared = False
    for item in status["accounts"]:
        if str(item.get("email", "")).casefold() != normalized:
            continue
        if item.get("status") == "failed":
            cleared = True
        item["status"] = "reconnected"
        item["error"] = None
    status["failed_count"] = sum(
        1 for item in status["accounts"] if item.get("status") == "failed"
    )
    set_system_state(session, SYNC_STATUS_KEY, json.dumps(status))
    return cleared


def set_system_state(session: Session, key: str, value: str) -> None:
    state = session.get(SystemState, key) or SystemState(key=key)
    state.value = value
    session.add(state)
    session.commit()


def get_system_state(session: Session, key: str) -> str | None:
    state = session.get(SystemState, key)
    return state.value if state else None


def sort_venue_payloads(
    venues: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Show newest replies first, with unanswered venues below them."""
    return sorted(
        venues,
        key=lambda venue: (
            venue["responded_at"] is None,
            -datetime.fromisoformat(str(venue["responded_at"])).timestamp()
            if venue["responded_at"]
            else 0,
            str(venue["name"]).casefold(),
        ),
    )
