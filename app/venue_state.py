"""Derive the plain-language stage and next action for one venue.

The rules use message direction, timestamps, and the couple's decision only,
so the same stored Gmail data always produces the same answer. Nothing here
touches the database or Gmail; ``database.venue_payload`` feeds it.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# After this many days without an answer the queue suggests a reminder, and a
# second reminder is suggested only after the same interval has passed again.
CHASE_AFTER_DAYS = 7

DECISION_NONE = ""
DECISION_SHORTLISTED = "shortlisted"
DECISION_PASSED = "passed"
DECISIONS = {DECISION_NONE, DECISION_SHORTLISTED, DECISION_PASSED}

STAGE_LABELS = {
    "reply_needed": "Reply needed",
    "waiting": "Waiting on venue",
    "draft": "Not contacted yet",
    "shortlist": "Shortlist",
    "closed": "Closed",
}
STAGE_ORDER = ["reply_needed", "waiting", "draft", "shortlist", "closed"]

_REPLY_STATUS_LABELS = {
    "quote received": "Quote received",
    "viewing offered": "Visit offered",
    "more info needed": "They need more info",
    "needs reply": "They need more info",
}


@dataclass(frozen=True)
class VenueState:
    stage: str
    stage_label: str
    plain_status: str
    next_action: str
    next_action_label: str
    attention: bool
    waiting_days: int | None
    days_since_activity: int | None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _days_between(later: datetime, earlier: datetime) -> int:
    return max(0, (later - earlier).days)


def _format_visit(visit_at: datetime) -> str:
    return visit_at.strftime("%-d %b %Y")


def derive_state(
    *,
    status: str,
    decision: str,
    latest_inbound_at: datetime | None,
    latest_outbound_at: datetime | None,
    last_reminder_at: datetime | None = None,
    visit_at: datetime | None = None,
    now: datetime | None = None,
) -> VenueState:
    """Return the stage, plain status, and next action for a venue."""
    now = _aware(now) or datetime.now(UTC)
    latest_inbound_at = _aware(latest_inbound_at)
    latest_outbound_at = _aware(latest_outbound_at)
    last_reminder_at = _aware(last_reminder_at)
    visit_at = _aware(visit_at)
    normalized_status = status.strip().casefold()
    latest_activity = max(
        [item for item in (latest_inbound_at, latest_outbound_at) if item is not None],
        default=None,
    )
    days_since_activity = (
        _days_between(now, latest_activity) if latest_activity else None
    )
    upcoming_visit = visit_at is not None and visit_at >= now - timedelta(days=1)

    if decision == DECISION_PASSED:
        return VenueState(
            stage="closed",
            stage_label=STAGE_LABELS["closed"],
            plain_status="Passed",
            next_action="none",
            next_action_label="Nothing to do",
            attention=False,
            waiting_days=None,
            days_since_activity=days_since_activity,
        )

    if normalized_status == "unavailable":
        return VenueState(
            stage="closed",
            stage_label=STAGE_LABELS["closed"],
            plain_status="Not available",
            next_action="pass",
            next_action_label="Not available — mark as passed",
            attention=False,
            waiting_days=None,
            days_since_activity=days_since_activity,
        )

    venue_spoke_last = latest_inbound_at is not None and (
        latest_outbound_at is None or latest_inbound_at >= latest_outbound_at
    )
    if venue_spoke_last:
        plain = _REPLY_STATUS_LABELS.get(normalized_status, "They replied")
        return VenueState(
            stage="reply_needed",
            stage_label=STAGE_LABELS["reply_needed"],
            plain_status=plain,
            next_action="review_reply",
            next_action_label="Review their reply",
            attention=True,
            waiting_days=None,
            days_since_activity=days_since_activity,
        )

    if latest_outbound_at is not None:
        waiting_days = _days_between(now, latest_outbound_at)
        shortlisted = decision == DECISION_SHORTLISTED or upcoming_visit
        stage = "shortlist" if shortlisted else "waiting"
        plain = "You replied — waiting" if latest_inbound_at else "Waiting for reply"
        if upcoming_visit and visit_at is not None:
            plain = f"Visit on {_format_visit(visit_at)}"
        reminder_due = waiting_days >= CHASE_AFTER_DAYS and (
            last_reminder_at is None
            or _days_between(now, last_reminder_at) >= CHASE_AFTER_DAYS
        )
        if upcoming_visit and visit_at is not None:
            next_action, label, attention = (
                "visit",
                f"Visit planned for {_format_visit(visit_at)}",
                False,
            )
        elif reminder_due:
            next_action, label, attention = (
                "send_reminder",
                f"Waiting {waiting_days} days — send a reminder",
                True,
            )
        else:
            next_action, label, attention = (
                "wait",
                (
                    f"Waiting {waiting_days} days"
                    if waiting_days != 1
                    else "Waiting 1 day"
                ),
                False,
            )
        return VenueState(
            stage=stage,
            stage_label=STAGE_LABELS[stage],
            plain_status=plain,
            next_action=next_action,
            next_action_label=label,
            attention=attention,
            waiting_days=waiting_days,
            days_since_activity=days_since_activity,
        )

    if normalized_status == "existing conversation":
        return VenueState(
            stage="waiting",
            stage_label=STAGE_LABELS["waiting"],
            plain_status="Existing conversation found",
            next_action="sync_pending",
            next_action_label="Details appear after the next Gmail check",
            attention=False,
            waiting_days=None,
            days_since_activity=None,
        )

    return VenueState(
        stage="draft",
        stage_label=STAGE_LABELS["draft"],
        plain_status="Not contacted yet",
        next_action="send_inquiry",
        next_action_label="Send the inquiry",
        attention=True,
        waiting_days=None,
        days_since_activity=None,
    )
