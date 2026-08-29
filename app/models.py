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
    facts: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True
    draft_reply: str | None = None


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
    next_action: Literal["fetch_gmail_history"] = "fetch_gmail_history"
