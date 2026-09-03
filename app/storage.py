"""Private DigitalOcean Spaces storage for mirrored Gmail attachments."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import boto3
from botocore.client import Config

from app.config import Settings


class AttachmentTooLargeError(ValueError):
    """Raised when an attachment exceeds the configured mirror limit."""


def safe_key_component(value: str, *, fallback: str) -> str:
    """Make an external identifier safe and readable inside an object key."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip(".-")
    return (cleaned or fallback)[:240]


def stable_external_id(value: str, *, fallback: str) -> str:
    """Keep external IDs readable while preventing sanitized-key collisions."""
    readable = safe_key_component(value, fallback=fallback)[:80]
    digest = hashlib.sha256(value.encode()).hexdigest()[:12]
    return f"{readable}-{digest}"


def attachment_object_key(
    venue_id: int,
    gmail_message_id: str,
    gmail_attachment_id: str,
    filename: str,
) -> str:
    """Build the stable, folder-like key used inside the shared bucket."""
    return "/".join(
        (
            "venues",
            str(venue_id),
            "messages",
            stable_external_id(gmail_message_id, fallback="message"),
            "attachments",
            stable_external_id(gmail_attachment_id, fallback="attachment"),
            safe_key_component(filename, fallback="document"),
        )
    )


def _content_disposition(filename: str, content_type: str) -> str:
    mode = "inline" if (
        content_type == "application/pdf"
        or content_type.startswith(("image/", "text/", "audio/", "video/"))
    ) else "attachment"
    safe_filename = safe_key_component(filename, fallback="document")
    return f'{mode}; filename="{safe_filename}"'


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    byte_size: int
    sha256: str


class SpacesStorage:
    """Small S3-compatible client that never grants public object access."""

    def __init__(self, settings: Settings) -> None:
        if not settings.spaces_configured:
            raise ValueError("DigitalOcean Spaces attachment storage is not configured.")
        assert settings.spaces_access_key_id is not None
        assert settings.spaces_secret_access_key is not None
        self.bucket = settings.spaces_bucket
        self.max_attachment_bytes = settings.spaces_max_attachment_bytes
        self.presigned_url_seconds = settings.spaces_presigned_url_seconds
        self.client = boto3.client(
            "s3",
            region_name=settings.spaces_region,
            endpoint_url=settings.resolved_spaces_endpoint_url,
            aws_access_key_id=settings.spaces_access_key_id.get_secret_value(),
            aws_secret_access_key=(
                settings.spaces_secret_access_key.get_secret_value()
            ),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
            ),
        )

    def put_attachment(
        self,
        *,
        venue_id: int,
        gmail_message_id: str,
        gmail_attachment_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> StoredObject:
        """Store one private object using a deterministic, idempotent key."""
        if len(data) > self.max_attachment_bytes:
            raise AttachmentTooLargeError(
                f"Attachment is larger than {self.max_attachment_bytes} bytes."
            )
        object_key = attachment_object_key(
            venue_id,
            gmail_message_id,
            gmail_attachment_id,
            filename,
        )
        digest = hashlib.sha256(data).hexdigest()
        normalized_type = content_type or "application/octet-stream"
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            ContentType=normalized_type,
            ContentDisposition=_content_disposition(filename, normalized_type),
            Metadata={"sha256": digest, "source": "gmail"},
        )
        return StoredObject(
            object_key=object_key,
            byte_size=len(data),
            sha256=digest,
        )

    def presigned_view_url(
        self, *, object_key: str, filename: str, content_type: str
    ) -> str:
        """Create a short-lived read URL without exposing a long-lived key."""
        normalized_type = content_type or "application/octet-stream"
        return self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": object_key,
                "ResponseContentType": normalized_type,
                "ResponseContentDisposition": _content_disposition(
                    filename, normalized_type
                ),
            },
            ExpiresIn=self.presigned_url_seconds,
        )
