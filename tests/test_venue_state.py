"""Tests for the plain-language stage and next-action rules."""

from datetime import UTC, datetime, timedelta

from app.venue_state import CHASE_AFTER_DAYS, derive_state

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


def days_ago(days: int) -> datetime:
    return NOW - timedelta(days=days)


def test_draft_needs_the_first_inquiry() -> None:
    state = derive_state(
        status="Draft", decision="", latest_inbound_at=None, latest_outbound_at=None, now=NOW
    )

    assert state.stage == "draft"
    assert state.plain_status == "Not contacted yet"
    assert state.next_action == "send_inquiry"
    assert state.attention is True


def test_recent_inquiry_is_waiting_without_a_reminder() -> None:
    state = derive_state(
        status="Sent", decision="", latest_inbound_at=None, latest_outbound_at=days_ago(3), now=NOW
    )

    assert state.stage == "waiting"
    assert state.plain_status == "Waiting for reply"
    assert state.next_action == "wait"
    assert state.next_action_label == "Waiting 3 days"
    assert state.waiting_days == 3
    assert state.attention is False


def test_silent_venue_gets_a_reminder_after_a_week() -> None:
    state = derive_state(
        status="Sent",
        decision="",
        latest_inbound_at=None,
        latest_outbound_at=days_ago(CHASE_AFTER_DAYS + 5),
        now=NOW,
    )

    assert state.next_action == "send_reminder"
    assert state.next_action_label == "Waiting 12 days — send a reminder"
    assert state.attention is True


def test_recent_reminder_suppresses_a_second_one() -> None:
    state = derive_state(
        status="Sent",
        decision="",
        latest_inbound_at=None,
        latest_outbound_at=days_ago(2),
        last_reminder_at=days_ago(2),
        now=NOW,
    )

    assert state.next_action == "wait"
    assert state.waiting_days == 2


def test_venue_reply_needs_review_with_specific_wording() -> None:
    state = derive_state(
        status="Quote received",
        decision="",
        latest_inbound_at=days_ago(1),
        latest_outbound_at=days_ago(6),
        now=NOW,
    )

    assert state.stage == "reply_needed"
    assert state.plain_status == "Quote received"
    assert state.next_action == "review_reply"
    assert state.attention is True
    assert state.days_since_activity == 1


def test_after_our_reply_the_venue_is_waiting_again() -> None:
    state = derive_state(
        status="Responded to venue",
        decision="",
        latest_inbound_at=days_ago(10),
        latest_outbound_at=days_ago(9),
        now=NOW,
    )

    assert state.stage == "waiting"
    assert state.plain_status == "You replied — waiting"
    assert state.next_action == "send_reminder"
    assert state.waiting_days == 9


def test_shortlisted_venue_with_visit_shows_the_visit() -> None:
    state = derive_state(
        status="Responded to venue",
        decision="shortlisted",
        latest_inbound_at=days_ago(10),
        latest_outbound_at=days_ago(9),
        visit_at=NOW + timedelta(days=9),
        now=NOW,
    )

    assert state.stage == "shortlist"
    assert state.plain_status == "Visit on 12 Sep 2026"
    assert state.next_action == "visit"
    assert state.attention is False


def test_shortlisted_venue_that_replied_still_needs_review() -> None:
    state = derive_state(
        status="Responded",
        decision="shortlisted",
        latest_inbound_at=days_ago(0),
        latest_outbound_at=days_ago(4),
        now=NOW,
    )

    assert state.stage == "reply_needed"


def test_unavailable_and_passed_are_closed() -> None:
    unavailable = derive_state(
        status="Unavailable", decision="", latest_inbound_at=days_ago(2), latest_outbound_at=days_ago(5), now=NOW
    )
    passed = derive_state(
        status="Quote received", decision="passed", latest_inbound_at=days_ago(2), latest_outbound_at=days_ago(5), now=NOW
    )

    assert unavailable.stage == "closed"
    assert unavailable.plain_status == "Not available"
    assert unavailable.next_action == "pass"
    assert passed.stage == "closed"
    assert passed.plain_status == "Passed"
    assert passed.next_action == "none"


def test_existing_conversation_waits_for_the_next_sync() -> None:
    state = derive_state(
        status="Existing conversation", decision="", latest_inbound_at=None, latest_outbound_at=None, now=NOW
    )

    assert state.stage == "waiting"
    assert state.next_action == "sync_pending"
    assert state.attention is False


def test_naive_timestamps_are_treated_as_utc() -> None:
    state = derive_state(
        status="Sent",
        decision="",
        latest_inbound_at=None,
        latest_outbound_at=NOW.replace(tzinfo=None) - timedelta(days=2),
        now=NOW,
    )

    assert state.waiting_days == 2
