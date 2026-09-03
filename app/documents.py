"""Private attachment extraction helpers."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

# Stored on attachments whose PDF carries no embedded text (scans, images),
# so a later run does not re-download them looking for text.
NO_EMBEDDED_TEXT = "[no embedded text]"
# Upper bound on stored text per attachment.
EXTRACTED_TEXT_LIMIT = 20_000


def extract_pdf_text(content: bytes) -> str:
    """Extract embedded PDF text locally; scanned files return an empty string."""
    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except (PdfReadError, ValueError):
        return ""


def is_pdf(filename: str, content_type: str) -> bool:
    return content_type == "application/pdf" or filename.casefold().endswith(".pdf")


def attachment_text(filename: str, content_type: str, data: bytes) -> str:
    """Return storable text for a mirrored attachment (a marker when none)."""
    if not is_pdf(filename, content_type):
        return ""
    text = extract_pdf_text(data)[:EXTRACTED_TEXT_LIMIT]
    return text or NO_EMBEDDED_TEXT
