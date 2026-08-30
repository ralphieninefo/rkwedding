"""Tests for Google API normalization and safe outreach behavior."""

import base64
import json

import httpx

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.documents import extract_pdf_text
from app.gmail import GmailClient, GmailSendResult, normalize_message
from app.models import VenueOutreachEvent
from app.workflow import WeddingWorkflow


def websafe(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_normalize_message_extracts_text_headers_and_pdf() -> None:
    message = normalize_message(
        {
            "id": "message-1",
            "threadId": "thread-1",
            "historyId": "101",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Villa <info@villa.example>"},
                    {"name": "Subject", "value": "Re: Matrimonio"},
                    {"name": "Message-ID", "value": "<reply@villa.example>"},
                ],
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": websafe("Preventivo allegato")},
                    },
                    {
                        "mimeType": "application/pdf",
                        "filename": "quote.pdf",
                        "body": {"attachmentId": "attachment-1"},
                    },
                ],
            },
        }
    )

    assert message.sender == "Villa <info@villa.example>"
    assert message.body == "Preventivo allegato"
    assert message.rfc_message_id == "<reply@villa.example>"
    assert message.attachments[0].filename == "quote.pdf"


def test_normalize_message_converts_html_to_readable_text() -> None:
    message = normalize_message({
        "id": "message-html",
        "threadId": "thread-html",
        "payload": {
            "mimeType": "text/html",
            "body": {"data": websafe("<html><style>.x{color:red}</style><body><p>Menu €120 per person</p></body></html>")},
        },
    })

    assert message.body == "Menu €120 per person"
    assert "style" not in message.body


def test_invalid_pdf_is_left_for_manual_review() -> None:
    assert extract_pdf_text(b"not a pdf") == ""


@pytest.mark.anyio
async def test_dashboard_reply_stays_in_existing_gmail_thread() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["threadId"] == "thread-1"
        return httpx.Response(200, json={"id": "reply-2", "threadId": "thread-1"})

    gmail = GmailClient("token", transport=httpx.MockTransport(handler))
    result = await gmail.send_reply(
        recipient="staff@venue.example",
        subject="Re: Wedding inquiry",
        body="Thank you.",
        thread_id="thread-1",
        in_reply_to="<reply@venue.example>",
    )

    assert result.message_id == "reply-2"
    assert result.thread_id == "thread-1"


class FakeGmail:
    def __init__(self, duplicates: list[str] | None = None) -> None:
        self.duplicates = duplicates or []
        self.drafts: list[tuple[str, str, str]] = []
        self.sent: list[tuple[str, str, str]] = []

    async def search_message_ids(self, query: str, max_results: int = 10) -> list[str]:
        assert "venue@example.com" in query
        return self.duplicates

    async def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> str:
        self.drafts.append((recipient, subject, body))
        return "draft-1"

    async def send_message(
        self, recipient: str, subject: str, body: str
    ) -> GmailSendResult:
        self.sent.append((recipient, subject, body))
        return GmailSendResult("message-1", "thread-1")


class FakeSheets:
    def __init__(self) -> None:
        self.updates: list[tuple[str, int, dict[str, object]]] = []

    async def update_row(
        self, sheet_name: str, row_number: int, updates: dict[str, object]
    ) -> None:
        self.updates.append((sheet_name, row_number, updates))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_ready_venue_sends_and_records_gmail_ids() -> None:
    gmail = FakeGmail()
    sheets = FakeSheets()
    settings = Settings(
        google_access_token=SecretStr("test-google-token"),
        google_spreadsheet_id="sheet-1",
    )
    workflow = WeddingWorkflow(settings, gmail=gmail, sheets=sheets)  # type: ignore[arg-type]

    result = await workflow.process_new_venue(
        VenueOutreachEvent(row_number=2, venue="Villa Test", email="venue@example.com")
    )

    assert result.status == "sent"
    assert gmail.sent[0][0] == "venue@example.com"
    assert "l’inizio di ottobre" in gmail.sent[0][2]
    assert sheets.updates[0][2]["Status"] == "Sent"
    assert sheets.updates[0][2]["Gmail Message ID"] == "message-1"
    assert sheets.updates[0][2]["Gmail Thread ID"] == "thread-1"
    assert sheets.updates[0][2]["Date Inquired"]


@pytest.mark.anyio
async def test_new_venue_skips_existing_conversation() -> None:
    gmail = FakeGmail(duplicates=["existing-message"])
    sheets = FakeSheets()
    settings = Settings(
        google_access_token=SecretStr("test-google-token"),
        google_spreadsheet_id="sheet-1",
    )
    workflow = WeddingWorkflow(settings, gmail=gmail, sheets=sheets)  # type: ignore[arg-type]

    result = await workflow.process_new_venue(
        VenueOutreachEvent(row_number=3, venue="Villa Test", email="venue@example.com")
    )

    assert result.status == "duplicate_skipped"
    assert not gmail.sent
    assert sheets.updates[0][2]["Status"] == "Duplicate skipped"
