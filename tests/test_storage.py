"""Tests for deterministic private attachment storage behavior."""

from app.storage import SpacesStorage, attachment_object_key


class FakeS3Client:
    def __init__(self) -> None:
        self.put: dict[str, object] | None = None
        self.presign: dict[str, object] | None = None

    def put_object(self, **kwargs: object) -> None:
        self.put = kwargs

    def generate_presigned_url(
        self, operation: str, *, Params: dict[str, object], ExpiresIn: int
    ) -> str:
        self.presign = {
            "operation": operation,
            "params": Params,
            "expires_in": ExpiresIn,
        }
        return "https://private.example/signed"


def fake_storage() -> SpacesStorage:
    storage = object.__new__(SpacesStorage)
    storage.bucket = "wedding-documents"
    storage.max_attachment_bytes = 1024
    storage.presigned_url_seconds = 600
    storage.client = FakeS3Client()
    return storage


def test_attachment_key_uses_stable_ids_not_venue_names() -> None:
    key = attachment_object_key(
        42,
        "gmail/message",
        "attachment:1",
        "Preventivo Villa.pdf",
    )

    assert key.startswith("venues/42/messages/gmail-message-")
    assert "/attachments/attachment-1-" in key
    assert key.endswith("/Preventivo-Villa.pdf")


def test_attachment_upload_is_private_and_idempotently_named() -> None:
    storage = fake_storage()

    result = storage.put_attachment(
        venue_id=42,
        gmail_message_id="message-1",
        gmail_attachment_id="attachment-1",
        filename="quote.pdf",
        content_type="application/pdf",
        data=b"quote bytes",
    )

    assert "/attachment-1-" in result.object_key
    assert result.object_key.endswith("/quote.pdf")
    assert result.byte_size == 11
    assert storage.client.put is not None
    assert "ACL" not in storage.client.put
    assert storage.client.put["ContentDisposition"] == 'inline; filename="quote.pdf"'


def test_view_link_is_short_lived_and_preserves_inline_pdf() -> None:
    storage = fake_storage()

    url = storage.presigned_view_url(
        object_key="venues/42/messages/1/attachments/1/quote.pdf",
        filename="quote.pdf",
        content_type="application/pdf",
    )

    assert url == "https://private.example/signed"
    assert storage.client.presign is not None
    assert storage.client.presign["expires_in"] == 600
    params = storage.client.presign["params"]
    assert params["ResponseContentDisposition"] == 'inline; filename="quote.pdf"'
