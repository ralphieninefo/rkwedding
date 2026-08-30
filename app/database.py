"""Database models and small repository helpers for the control center."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

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
    estimate: Mapped["PriceEstimate | None"] = relationship(
        back_populates="venue", cascade="all, delete-orphan", uselist=False
    )


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(100), unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(100), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[Venue] = relationship(back_populates="outreach")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(100), unique=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(100), index=True)
    direction: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    synthesized_summary: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    venue: Mapped[Venue] = relationship(back_populates="messages")


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


def _database_url() -> str:
    url = get_settings().database_url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://") and "+psycopg" not in url:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


def _engine():
    url = _database_url()
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
    }
    with ENGINE.begin() as connection:
        for name, definition in additions.items():
            if name in columns:
                continue
            connection.execute(
                text(f"ALTER TABLE venues ADD COLUMN {name} {definition}")
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
    gmail_thread_id = (
        latest_reply.gmail_thread_id
        if latest_reply
        else latest_outreach.gmail_thread_id if latest_outreach else None
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
        "notes": venue.notes,
        "status": venue.status,
        "created_at": iso_utc(venue.created_at) if venue.created_at else None,
        "last_activity_at": iso_utc(latest_activity) if latest_activity else None,
        "sent_at": iso_utc(first_outreach.sent_at) if first_outreach else None,
        "responded_at": iso_utc(latest_reply.occurred_at) if latest_reply else None,
        "response_summary": venue.response_summary,
        "price_minimum_eur": venue.estimate.minimum_eur if venue.estimate else None,
        "price_maximum_eur": venue.estimate.maximum_eur if venue.estimate else None,
        "price_note": venue.estimate.note if venue.estimate else "",
        "gmail_url": (
            f"https://mail.google.com/mail/u/0/#all/{gmail_thread_id}"
            if gmail_thread_id else None
        ),
    }


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
