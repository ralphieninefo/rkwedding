"""Typed request, Pub/Sub, and decision models."""

import base64
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GmailEvent(BaseModel):
    """Normalized email event accepted by the local webhook."""

    venue: str = Field(min_length=1)
    message: str = Field(min_length=1)
    thread_id: str | None = None


class QuoteDetails(BaseModel):
    """Normalized commercial terms extracted from a venue quote."""

    total_price: float | None = Field(default=None, ge=0)
    currency: str | None = None
    guest_count: int | None = Field(default=None, ge=1)
    price_basis: str | None = None
    taxes_included: bool | None = None
    service_fee: float | None = Field(default=None, ge=0)
    deposit: float | None = Field(default=None, ge=0)
    deposit_due: str | None = None
    available_dates: list[str] = Field(default_factory=list)
    inclusions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    payment_terms: list[str] = Field(default_factory=list)
    source_file_name: str | None = None
    source_file_url: str | None = None
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)


class AgentDecision(BaseModel):
    """Structured outcome returned by the wedding venue agent."""

    venue: str
    event_type: Literal[
        "unprocessed",
        "quote_received",
        "needs_info",
        "viewing_offered",
        "unavailable",
        "general_reply",
    ]
    status: str
    recommended_action: str
    quoted_price: float | None = None
    currency: str | None = None
    quote: QuoteDetails | None = None
    facts: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True
    draft_reply: str | None = None


class VenueCandidate(BaseModel):
    """Comparable venue inputs supplied by Sheets or the dashboard."""

    venue: str = Field(min_length=1)
    normalized_all_in_cost: float | None = Field(default=None, ge=0)
    currency: str = "EUR"
    location_score: float | None = Field(default=None, ge=0, le=100)
    value_score: float | None = Field(default=None, ge=0, le=100)
    availability_score: float | None = Field(default=None, ge=0, le=100)
    quality_score: float | None = Field(default=None, ge=0, le=100)
    logistics_score: float | None = Field(default=None, ge=0, le=100)
    data_confidence: float = Field(default=1, ge=0, le=1)


class VenueRanking(BaseModel):
    """Deterministic score and audit trail for one venue."""

    rank: int = Field(ge=1)
    venue: str
    score: float = Field(ge=0, le=100)
    price_score: float | None = Field(default=None, ge=0, le=100)
    data_completeness: float = Field(ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class VenueComparisonRequest(BaseModel):
    """Request body for a transparent venue comparison."""

    venues: list[VenueCandidate] = Field(min_length=1)


class VenueComparisonResponse(BaseModel):
    """Ranked venue comparison produced without model judgment."""

    rankings: list[VenueRanking]
    scoring_version: str = "v1"


class PubSubMessage(BaseModel):
    """Google Cloud Pub/Sub push message wrapper."""

    model_config = ConfigDict(populate_by_name=True)

    data: str
    message_id: str | None = Field(default=None, alias="messageId")
    publish_time: str | None = Field(default=None, alias="publishTime")


class PubSubEnvelope(BaseModel):
    """HTTP body sent by a Pub/Sub push subscription."""

    message: PubSubMessage
    subscription: str | None = None

    def decode_gmail_notification(self) -> "GmailPushNotification":
        """Decode Gmail's base64-encoded JSON notification."""
        raw = base64.b64decode(self.message.data, validate=True)
        return GmailPushNotification.model_validate(json.loads(raw))


class GmailPushNotification(BaseModel):
    """Minimal notification Gmail publishes through Cloud Pub/Sub."""

    email_address: str = Field(alias="emailAddress")
    history_id: str = Field(alias="historyId")


class GmailPushReceipt(BaseModel):
    """Safe acknowledgement returned by the local webhook scaffold."""

    status: Literal["accepted"] = "accepted"
    email_address: str
    history_id: str
    next_action: Literal["fetch_gmail_history", "baseline_saved", "completed"] = (
        "fetch_gmail_history"
    )
    processed_messages: int = 0


class VenueOutreachEvent(BaseModel):
    """A new tracker row ready for one venue-specific inquiry."""

    row_number: int = Field(ge=2)
    venue: str = Field(min_length=1)
    email: str = Field(
        min_length=3,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )


class VenueOutreachReceipt(BaseModel):
    """Result of sending an initial inquiry or skipping a duplicate."""

    status: Literal["sent", "duplicate_skipped"]
    venue: str
    gmail_id: str | None = None
    gmail_thread_id: str | None = None


class VenueCreate(BaseModel):
    """Venue details entered through the private control center."""

    name: str = Field(min_length=1, max_length=250)
    region: str = Field(default="", max_length=250)
    location: str = Field(default="", max_length=250)
    email: str = Field(
        min_length=3,
        max_length=320,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )
    website: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=100)
    send_now: bool = False


class ResponseSynthesis(BaseModel):
    """Small, validated Kimi result used by the outreach dashboard."""

    summary: str = Field(min_length=1, max_length=800)
    status: Literal[
        "responded",
        "quote_received",
        "viewing_offered",
        "unavailable",
        "needs_reply",
    ] = "responded"
    estimated_total_min_eur: float | None = Field(default=None, ge=0)
    estimated_total_max_eur: float | None = Field(default=None, ge=0)
    price_note: str = Field(default="", max_length=300)


class VenueReply(BaseModel):
    """Human-written reply sent from the private dashboard."""

    body: str = Field(min_length=1, max_length=10_000)


class VenueResearchUpdate(BaseModel):
    """Human-sourced research kept separate from official venue quotes."""

    source_type: str = Field(default="", max_length=100)
    source_url: str = Field(default="", max_length=1_000)
    contact_name: str = Field(default="", max_length=250)
    notes: str = Field(default="", max_length=20_000)


class VenueDiscoveryRequest(BaseModel):
    """Public venue website to inspect for contact details."""

    url: str = Field(min_length=4, max_length=2_000)


class VenueDiscovery(BaseModel):
    """Contact details discovered from a public venue website."""

    name: str = ""
    location: str = ""
    email: str = ""
    website: str
    phone: str = ""
