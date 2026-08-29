"""Focused tests for response synthesis shown in the control center."""

from datetime import datetime

from app.database import iso_utc
from app.db_workflow import _fallback_summary, _is_incoming
from app.gmail import GmailMessage


def test_fallback_summary_removes_quoted_outreach_and_stays_concise() -> None:
    body = """Gentili Raphaël e Kassia,

Siamo disponibili e vi invieremo il preventivo domani. Possiamo ospitare 120 persone.

Il 29 agosto Raphaël ha scritto:
> Buongiorno,
> vorremmo informazioni per il matrimonio.
"""

    summary = _fallback_summary(body)

    assert "Siamo disponibili" in summary
    assert "Buongiorno" not in summary
    assert len(summary) <= 220


def test_reply_from_staff_address_matches_known_outreach_thread() -> None:
    reply = GmailMessage(
        message_id="reply-1",
        thread_id="outreach-thread",
        sender="Chiara <g.chiara@villatuscolana.com>",
        recipients="Raphael <raphael@example.com>",
        subject="R: Richiesta informazioni",
        body="In allegato trova le nostre proposte.",
        received_at="2026-08-29T12:52:40+00:00",
        label_ids=("INBOX",),
    )

    assert _is_incoming(
        reply,
        "info@villatuscolana.com",
        {"outreach-thread"},
    )


def test_unrelated_message_is_not_assigned_to_venue() -> None:
    unrelated = GmailMessage(
        message_id="message-2",
        thread_id="different-thread",
        sender="Someone Else <person@example.net>",
        recipients="Raphael <raphael@example.com>",
        subject="Unrelated",
        body="Hello",
        received_at="2026-08-29T13:00:00+00:00",
        label_ids=("INBOX",),
    )

    assert not _is_incoming(
        unrelated,
        "info@villatuscolana.com",
        {"outreach-thread"},
    )


def test_sqlite_timestamp_is_serialized_as_utc() -> None:
    assert iso_utc(datetime(2026, 8, 29, 5, 9, 5)).endswith("+00:00")
