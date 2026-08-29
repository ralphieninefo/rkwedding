"""Private attachment extraction helpers."""

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def extract_pdf_text(content: bytes) -> str:
    """Extract embedded PDF text locally; scanned files return an empty string."""
    try:
        reader = PdfReader(BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except (PdfReadError, ValueError):
        return ""
