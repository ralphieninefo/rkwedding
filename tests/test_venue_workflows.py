"""Database-backed tests for the dossier, decisions, reminders, and guards."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import database, db_workflow
from app.config import Settings
from app.database import (
    Attachment,
    Base,
    GoogleAccount,
    Message,
    Outreach,
    Venue,
    venue_detail_payload,
)
from app.db_workflow import VenueConflictError, _is_outgoing, _stored_attachment_text
from app.gmail import GmailMessage, GmailSendResult
from app.google_auth import GoogleCredentialError

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'venues.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_workflow, "SessionLocal", factory)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(
        database, "get_settings",
        lambda: Settings(_env_file=None, google_primary_email="shared@example.com"),
    )
    monkeypatch.setattr(
        db_workflow, "list_google_accounts",
        lambda: [
            {"id": 1, "email": "shared@example.com", "is_primary": True},
            {"id": 2, "email": "personal@example.com", "is_primary": False},
        ],
    )
    monkeypatch.setattr(db_workflow, "default_google_account_id", lambda: 1)
    with factory() as session:
        session.add_all([
            GoogleAccount(id=1, email="shared@example.com", token_json="{}", is_primary=True),
            GoogleAccount(id=2, email="personal@example.com", token_json="{}"),
        ])
        session.commit()
    yield factory
    engine.dispose()


def make_venue(factory, **overrides) -> int:
    fields = {"name": "Villa Test", "email": "info@villa.example", "status": "Draft"}
    fields.update(overrides)
    with factory() as session:
        venue = Venue(**fields)
        session.add(venue)
        session.commit()
        return venue.id


def add_inquiry(factory, venue_id: int, *, account_id: int, days_ago: int, thread="t1") -> None:
    when = NOW - timedelta(days=days_ago)
    with factory() as session:
        session.add(Outreach(venue_id=venue_id, gmail_message_id=f"out-{thread}", gmail_thread_id=thread, gmail_account_id=account_id, sent_at=when))
        session.add(Message(venue_id=venue_id, gmail_message_id=f"out-{thread}", gmail_thread_id=thread, gmail_account_id=account_id, direction="outbound", kind="inquiry", subject="Richiesta informazioni", body="Buongiorno,\n\nvorremmo informazioni.", occurred_at=when))
        session.get(Venue, venue_id).status = "Sent"
        session.commit()


def add_reply(factory, venue_id: int, *, account_id: int, days_ago: int, sender: str, thread="t1", summary="They have space.") -> None:
    when = NOW - timedelta(days=days_ago)
    with factory() as session:
        session.add(Message(venue_id=venue_id, gmail_message_id=f"in-{thread}-{days_ago}", gmail_thread_id=thread, gmail_account_id=account_id, direction="inbound", sender_email=sender, subject="Re: Richiesta informazioni", body="(venue body)", synthesized_summary=summary, occurred_at=when))
        venue = session.get(Venue, venue_id)
        venue.status = "Responded"
        venue.response_summary = summary
        session.commit()


class FakeGmail:
    sent: ClassVar[list[dict]] = []
    existing: ClassVar[dict[str, list[str]]] = {}

    def __init__(self, token, _user_id):
        self.token = token

    async def search_message_ids(self, query, max_results=10):
        return FakeGmail.existing.get(self.token, [])

    async def get_message(self, message_id):
        return GmailMessage(
            message_id=message_id, thread_id="t1", sender="Staff <staff@villa.example>",
            recipients="", subject="Re: Richiesta informazioni", body="", received_at="2026-09-01T10:00:00+00:00",
            rfc_message_id="<rfc-1@villa.example>", references="<rfc-0@example.com>",
        )

    async def send_reply(self, **kwargs):
        FakeGmail.sent.append({"token": self.token, **kwargs})
        return GmailSendResult(message_id=f"sent-{len(FakeGmail.sent)}", thread_id=kwargs["thread_id"])

    async def send_message(self, recipient, subject, body):
        FakeGmail.sent.append({"token": self.token, "recipient": recipient, "subject": subject, "body": body})
        return GmailSendResult(message_id="new-1", thread_id="new-thread")


@pytest.fixture
def gmail(monkeypatch):
    FakeGmail.sent = []
    FakeGmail.existing = {}
    monkeypatch.setattr(db_workflow, "GmailClient", FakeGmail)

    async def token_for(_settings, account_id):
        return f"token-{account_id}"

    monkeypatch.setattr(db_workflow, "get_google_access_token", token_for)
    return FakeGmail


# ----- follow-up preview and reply agree ------------------------------------

def test_followup_preview_uses_the_exact_staff_address_and_mailbox(sessions) -> None:
    venue_id = make_venue(sessions)
    add_inquiry(sessions, venue_id, account_id=2, days_ago=8)
    add_reply(sessions, venue_id, account_id=2, days_ago=1, sender="g.chiara@villa.example")

    preview = db_workflow.followup_preview(venue_id)

    assert preview["recipient"] == "g.chiara@villa.example"
    assert preview["gmail_account_email"] == "personal@example.com"
    assert preview["subject"] == "Re: Richiesta informazioni"


@pytest.mark.anyio
async def test_reply_goes_to_the_previewed_recipient_from_the_owning_mailbox(sessions, gmail) -> None:
    venue_id = make_venue(sessions)
    add_inquiry(sessions, venue_id, account_id=2, days_ago=8)
    add_reply(sessions, venue_id, account_id=2, days_ago=1, sender="g.chiara@villa.example")
    preview = db_workflow.followup_preview(venue_id)

    result = await db_workflow.reply_to_venue(Settings(_env_file=None), venue_id, "Grazie mille.")

    assert result == {"sent": True, "status": "Responded to venue"}
    sent = gmail.sent[0]
    assert sent["token"] == "token-2"
    assert sent["recipient"] == preview["recipient"]
    assert sent["subject"] == preview["subject"]
    assert sent["thread_id"] == "t1"
    assert sent["in_reply_to"] == "<rfc-1@villa.example>"
    with sessions() as session:
        stored = session.scalar(select(Message).where(Message.kind == "reply"))
        assert stored is not None and stored.gmail_account_id == 2
        assert session.get(Venue, venue_id).status == "Responded to venue"


# ----- reminders -------------------------------------------------------------

def test_reminder_preview_continues_the_original_thread(sessions) -> None:
    venue_id = make_venue(sessions)
    add_inquiry(sessions, venue_id, account_id=2, days_ago=12)

    preview = db_workflow.reminder_preview(venue_id)

    assert preview["recipient"] == "info@villa.example"
    assert preview["gmail_account_email"] == "personal@example.com"
    assert preview["subject"] == "Re: Richiesta informazioni"
    assert "sollecito" in preview["body"]


def test_reminder_preview_requires_a_sent_inquiry(sessions) -> None:
    venue_id = make_venue(sessions)

    with pytest.raises(ValueError, match="No inquiry has been sent"):
        db_workflow.reminder_preview(venue_id)


@pytest.mark.anyio
async def test_reminder_is_sent_in_thread_and_recorded_as_a_reminder(sessions, gmail) -> None:
    venue_id = make_venue(sessions)
    add_inquiry(sessions, venue_id, account_id=1, days_ago=12)

    result = await db_workflow.send_venue_reminder(Settings(_env_file=None), venue_id, "Gentile sollecito.")

    assert result["sent"] is True
    sent = gmail.sent[0]
    assert sent["token"] == "token-1"
    assert sent["thread_id"] == "t1"
    assert sent["recipient"] == "info@villa.example"
    with sessions() as session:
        reminder = session.scalar(select(Message).where(Message.kind == "reminder"))
        assert reminder is not None
        assert reminder.direction == "outbound"
        assert session.get(Venue, venue_id).status == "Sent"
        payload = venue_detail_payload(session, session.get(Venue, venue_id), now=NOW + timedelta(days=1))
    assert payload["last_reminder_at"] is not None
    assert payload["next_action"] == "wait"


# ----- duplicate-inquiry guard across mailboxes ------------------------------

@pytest.mark.anyio
async def test_first_inquiry_is_blocked_when_the_personal_mailbox_has_history(sessions, gmail) -> None:
    venue_id = make_venue(sessions)
    gmail.existing = {"token-2": ["old-message"]}

    result = await db_workflow.send_venue_inquiry(Settings(_env_file=None), venue_id)

    assert result["sent"] is False
    assert result["status"] == "Existing conversation"
    assert result["existing_in"] == ["personal@example.com"]
    assert gmail.sent == []
    with sessions() as session:
        assert session.get(Venue, venue_id).status == "Existing conversation"


@pytest.mark.anyio
async def test_first_inquiry_is_sent_from_the_primary_mailbox_and_recorded(sessions, gmail) -> None:
    venue_id = make_venue(sessions)

    result = await db_workflow.send_venue_inquiry(Settings(_env_file=None), venue_id)

    assert result["sent"] is True
    assert result["unchecked_mailboxes"] == []
    assert gmail.sent[0]["token"] == "token-1"
    with sessions() as session:
        outreach = session.scalar(select(Outreach).where(Outreach.venue_id == venue_id))
        inquiry = session.scalar(select(Message).where(Message.venue_id == venue_id))
        assert outreach.gmail_account_id == 1
        assert inquiry.kind == "inquiry" and inquiry.direction == "outbound"
        assert session.get(Venue, venue_id).status == "Sent"


@pytest.mark.anyio
async def test_unreachable_secondary_mailbox_is_reported_not_fatal(sessions, gmail, monkeypatch) -> None:
    venue_id = make_venue(sessions)

    async def token_for(_settings, account_id):
        if account_id == 2:
            raise GoogleCredentialError("personal@example.com")
        return "token-1"

    monkeypatch.setattr(db_workflow, "get_google_access_token", token_for)

    result = await db_workflow.send_venue_inquiry(Settings(_env_file=None), venue_id)

    assert result["sent"] is True
    assert result["unchecked_mailboxes"] == ["personal@example.com"]


@pytest.mark.anyio
async def test_broken_primary_mailbox_stops_the_send(sessions, gmail, monkeypatch) -> None:
    venue_id = make_venue(sessions)

    async def token_for(_settings, account_id):
        raise GoogleCredentialError("shared@example.com")

    monkeypatch.setattr(db_workflow, "get_google_access_token", token_for)

    with pytest.raises(GoogleCredentialError, match="shared@example.com"):
        await db_workflow.send_venue_inquiry(Settings(_env_file=None), venue_id)
    assert gmail.sent == []


# ----- outbound detection ------------------------------------------------------

def test_manual_reply_to_staff_address_in_known_thread_counts_as_outgoing() -> None:
    message = GmailMessage(
        message_id="m", thread_id="t1", sender="Raph <raph@example.com>",
        recipients="Chiara <g.chiara@villa.example>", subject="Re: Richiesta", body="Grazie",
        received_at="2026-09-01T10:00:00+00:00", label_ids=("SENT",),
    )

    assert _is_outgoing(message, "info@villa.example", {"t1"})
    assert not _is_outgoing(message, "info@villa.example", set())


# ----- dossier, edits, decisions, deletion ----------------------------------

def test_detail_payload_has_a_timeline_without_venue_bodies(sessions) -> None:
    venue_id = make_venue(sessions)
    add_inquiry(sessions, venue_id, account_id=1, days_ago=8)
    add_reply(sessions, venue_id, account_id=1, days_ago=2, sender="staff@villa.example", summary="Quote: EUR 140 per person.")

    payload = db_workflow.venue_detail(venue_id)

    assert [item["direction"] for item in payload["messages"]] == ["inbound", "outbound"]
    inbound, outbound = payload["messages"]
    assert inbound["summary"] == "Quote: EUR 140 per person."
    assert inbound["sender_email"] == "staff@villa.example"
    assert inbound["gmail_account_email"] == "shared@example.com"
    assert "(venue body)" not in str(payload)
    assert outbound["kind"] == "inquiry"
    assert outbound["summary"] == "vorremmo informazioni."
    assert payload["stage"] == "reply_needed"


def test_update_venue_edits_fields_and_records_decisions(sessions) -> None:
    venue_id = make_venue(sessions)

    payload = db_workflow.update_venue(
        venue_id, name="Villa Nuova", decision="shortlisted", visit_at="2026-10-12", availability="2 Oct free"
    )

    assert payload["name"] == "Villa Nuova"
    assert payload["decision"] == "shortlisted"
    assert payload["visit_at"].startswith("2026-10-12")
    assert payload["availability"] == "2 Oct free"
    assert payload["stage"] == "draft"
    cleared = db_workflow.update_venue(venue_id, visit_at="", decision="")
    assert cleared["visit_at"] is None
    assert cleared["decision"] == ""


def test_shortlisting_assigns_ranks_and_moves_swap_neighbours(sessions) -> None:
    first = make_venue(sessions, name="First", email="first@villa.example")
    second = make_venue(sessions, name="Second", email="second@villa.example")
    third = make_venue(sessions, name="Third", email="third@villa.example")

    assert db_workflow.update_venue(first, decision="shortlisted")["shortlist_rank"] == 1
    assert db_workflow.update_venue(second, decision="shortlisted")["shortlist_rank"] == 2
    assert db_workflow.update_venue(third, decision="shortlisted")["shortlist_rank"] == 3
    # Re-shortlisting an already-shortlisted venue keeps its place.
    assert db_workflow.update_venue(second, decision="shortlisted")["shortlist_rank"] == 2

    moved = db_workflow.move_shortlisted(third, "up")
    assert moved["shortlist_rank"] == 2
    assert db_workflow.venue_detail(second)["shortlist_rank"] == 3
    # Moving the top venue up is a harmless no-op.
    assert db_workflow.move_shortlisted(first, "up")["shortlist_rank"] == 1

    # Leaving the shortlist clears the rank; others keep their order.
    assert db_workflow.update_venue(third, decision="passed")["shortlist_rank"] is None
    assert db_workflow.move_shortlisted(second, "up")["shortlist_rank"] == 1

    with pytest.raises(ValueError, match="shortlisted"):
        db_workflow.move_shortlisted(third, "up")
    with pytest.raises(ValueError, match="'up' or 'down'"):
        db_workflow.move_shortlisted(first, "sideways")
    with pytest.raises(ValueError, match="not found"):
        db_workflow.move_shortlisted(999, "up")


def test_update_venue_rejects_a_duplicate_email_and_bad_dates(sessions) -> None:
    first = make_venue(sessions, email="a@villa.example")
    make_venue(sessions, name="Other", email="b@villa.example")

    with pytest.raises(VenueConflictError):
        db_workflow.update_venue(first, email="B@villa.example")
    with pytest.raises(ValueError, match="date"):
        db_workflow.update_venue(first, visit_at="next week")


def test_delete_only_removes_venues_without_history(sessions) -> None:
    fresh = make_venue(sessions, email="fresh@villa.example")
    contacted = make_venue(sessions, name="Contacted", email="old@villa.example")
    add_inquiry(sessions, contacted, account_id=1, days_ago=3, thread="t9")

    assert db_workflow.delete_venue(fresh) == {"id": fresh, "deleted": True}
    with pytest.raises(VenueConflictError, match="passed"):
        db_workflow.delete_venue(contacted)


def test_preferences_store_the_budget(sessions) -> None:
    assert db_workflow.update_preferences(budget_eur=30_000)["budget_eur"] == 30_000.0
    with sessions() as session:
        assert database.preferences_payload(session)["guest_count"] == 90


# ----- PDF quote text feeding the English synthesis --------------------------

def test_stored_attachment_text_joins_pdfs_and_skips_the_no_text_marker(sessions) -> None:
    venue_id = make_venue(sessions)
    with sessions() as session:
        message = Message(
            venue_id=venue_id, gmail_message_id="in-1", gmail_thread_id="t1",
            gmail_account_id=1, direction="inbound", occurred_at=NOW,
        )
        session.add(message)
        session.commit()
        message_id = message.id
        session.add_all([
            Attachment(
                venue_id=venue_id, message_id=message_id, gmail_account_id=1,
                gmail_message_id="in-1", gmail_attachment_id="a1", object_key="k1",
                original_filename="listino.pdf", content_type="application/pdf",
                byte_size=10, sha256="x", extracted_text="EUR 140 a persona.",
            ),
            Attachment(
                venue_id=venue_id, message_id=message_id, gmail_account_id=1,
                gmail_message_id="in-1", gmail_attachment_id="a2", object_key="k2",
                original_filename="scan.pdf", content_type="application/pdf",
                byte_size=10, sha256="y", extracted_text="[no embedded text]",
            ),
            Attachment(
                venue_id=venue_id, message_id=message_id, gmail_account_id=1,
                gmail_message_id="in-1", gmail_attachment_id="a3", object_key="k3",
                original_filename="menu.png", content_type="image/png",
                byte_size=10, sha256="z", extracted_text="",
            ),
        ])
        session.commit()

    with sessions() as session:
        text = _stored_attachment_text(session, message_id)

    assert text == "EUR 140 a persona."
