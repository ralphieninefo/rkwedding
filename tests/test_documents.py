"""Tests for local PDF attachment text extraction."""

from app import documents
from app.documents import (
    EXTRACTED_TEXT_LIMIT,
    NO_EMBEDDED_TEXT,
    attachment_text,
    is_pdf,
)


def test_is_pdf_checks_content_type_and_filename() -> None:
    assert is_pdf("preventivo.pdf", "")
    assert is_pdf("preventivo", "application/pdf")
    assert not is_pdf("preventivo.docx", "application/msword")


def test_non_pdf_attachments_are_not_read_for_text() -> None:
    assert attachment_text("logo.png", "image/png", b"\x89PNG raw bytes") == ""


def test_scanned_pdf_with_no_embedded_text_is_marked_not_reread() -> None:
    # Not a real PDF, so extraction yields no text; the marker means a later
    # sync will not download and re-parse this attachment looking for text.
    assert attachment_text("scan.pdf", "application/pdf", b"not a real pdf") == NO_EMBEDDED_TEXT


def test_pdf_text_is_extracted_and_truncated(monkeypatch) -> None:
    monkeypatch.setattr(documents, "extract_pdf_text", lambda _data: "A" * 25_000)

    text = attachment_text("quote.pdf", "application/pdf", b"%PDF-fake")

    assert text != NO_EMBEDDED_TEXT
    assert len(text) == EXTRACTED_TEXT_LIMIT
