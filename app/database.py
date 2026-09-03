"""Database models and small repository helpers for the control center."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

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
    sessionmaker,
)

from app.config import get_settings


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
            },
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


def venue_payload(venue: Venue) -> dict[str, object]:
    first_outreach = min(
        venue.outreach, key=lambda item: item.sent_at, default=None
    )
    latest_outreach = max(
        venue.outreach, key=lambda item: item.sent_at, default=None
    )
    inbound = [item for item in venue.messages if item.direction == "inbound"]
    latest_reply = max(inbound, key=lambda item: item.occurred_at, default=None)
    activity_times = [
        *[item.sent_at for item in venue.outreach],
        *[item.occurred_at for item in venue.messages],
    ]
    latest_activity = max(activity_times, default=None)
    gmail_item = _preferred_gmail_item(venue, latest_reply, latest_outreach)
    gmail_thread_id = gmail_item.gmail_thread_id if gmail_item else None
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
        "created_at": iso_utc(venue.created_at) if venue.created_at else None,
        "last_activity_at": iso_utc(latest_activity) if latest_activity else None,
        "sent_at": iso_utc(first_outreach.sent_at) if first_outreach else None,
        "responded_at": iso_utc(latest_reply.occurred_at) if latest_reply else None,
        "response_summary": venue.response_summary,
        "price_minimum_eur": venue.estimate.minimum_eur if venue.estimate else None,
        "price_maximum_eur": venue.estimate.maximum_eur if venue.estimate else None,
        "price_note": venue.estimate.note if venue.estimate else "",
        "gmail_url": _gmail_url(gmail_thread_id, gmail_item, None),
        "gmail_account_email": _gmail_account_email(gmail_item),
        "documents": [
            attachment_payload(item)
            for item in sorted(
                venue.attachments,
                key=lambda attachment: attachment.message.occurred_at,
                reverse=True,
            )
        ],
    }


def attachment_payload(attachment: Attachment) -> dict[str, object]:
    """Expose document metadata while keeping the private object key secret."""
    message = attachment.message
    return {
        "id": attachment.id,
        "filename": attachment.original_filename,
        "content_type": attachment.content_type,
        "byte_size": attachment.byte_size,
        "source": attachment.source,
        "subject": message.subject,
        "received_at": iso_utc(message.occurred_at),
        "view_url": f"/api/documents/{attachment.id}/view",
        "gmail_url": _gmail_url(message.gmail_thread_id, message, None),
    }


def _gmail_url(
    thread_id: str | None,
    latest_reply: Message | None,
    latest_outreach: Outreach | None,
) -> str | None:
    if thread_id is None:
        return None
    item = latest_reply or latest_outreach
    auth_user = "0"
    if item is not None and item.gmail_account_id is not None:
        with SessionLocal() as session:
            account = session.get(GoogleAccount, item.gmail_account_id)
            if account is not None:
                auth_user = account.email
    return f"https://mail.google.com/mail/?authuser={auth_user}#all/{thread_id}"


def _gmail_account_email(item: Message | Outreach | None) -> str | None:
    if item is None or item.gmail_account_id is None:
        return None
    with SessionLocal() as session:
        account = session.get(GoogleAccount, item.gmail_account_id)
        return account.email if account else None


def _preferred_gmail_item(
    venue: Venue,
    latest_reply: Message | None,
    latest_outreach: Outreach | None,
) -> Message | Outreach | None:
    """Prefer a thread owned by the configured sender when the venue has one."""
    preferred_email = get_settings().google_primary_email.strip().casefold()
    preferred_account_id: int | None = None
    if preferred_email:
        with SessionLocal() as session:
            preferred_account_id = session.scalar(
                select(GoogleAccount.id).where(GoogleAccount.email == preferred_email)
            )
    items: list[Message | Outreach] = [*venue.messages, *venue.outreach]
    if preferred_account_id is not None:
        preferred = [
            item for item in items
            if item.gmail_account_id == preferred_account_id
        ]
        if preferred:
            return max(
                preferred,
                key=lambda item: (
                    item.occurred_at if isinstance(item, Message) else item.sent_at
                ),
            )
    return latest_reply or latest_outreach


def list_venues(session: Session) -> list[dict[str, object]]:
    venues = session.scalars(select(Venue).order_by(Venue.name)).unique().all()
    return sort_venue_payloads([venue_payload(venue) for venue in venues])


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
    state = session.get(SystemState, "gmail_last_refresh")
    return {
        "venues": venues,
        "last_refreshed_at": state.value if state else None,
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
