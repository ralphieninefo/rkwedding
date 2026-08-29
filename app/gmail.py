"""Minimal Gmail REST client and MIME normalization."""

import base64
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any

import httpx


def _decode_websafe(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {
        item.get("name", "").lower(): item.get("value", "")
        for item in payload.get("headers", [])
    }


@dataclass(frozen=True)
class GmailAttachment:
    message_id: str
    attachment_id: str
    filename: str
    mime_type: str


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    history_id: str | None = None
    rfc_message_id: str | None = None
    references: str | None = None
    attachments: list[GmailAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class GmailThread:
    thread_id: str
    subject: str
    body: str
    messages: list[GmailMessage] = field(default_factory=list)


def normalize_message(raw: dict[str, Any]) -> GmailMessage:
    """Extract readable text and attachment references from a Gmail message."""
    message_id = raw["id"]
    payload = raw.get("payload", {})
    headers = _headers(payload)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[GmailAttachment] = []

    def visit(part: dict[str, Any]) -> None:
        body = part.get("body", {})
        data = body.get("data")
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")
        attachment_id = body.get("attachmentId")
        if filename and attachment_id:
            attachments.append(
                GmailAttachment(
                    message_id=message_id,
                    attachment_id=attachment_id,
                    filename=filename,
                    mime_type=mime_type,
                )
            )
        elif data and mime_type == "text/plain":
            plain_parts.append(_decode_websafe(data).decode("utf-8", errors="replace"))
        elif data and mime_type == "text/html":
            html_parts.append(_decode_websafe(data).decode("utf-8", errors="replace"))
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    body = "\n\n".join(plain_parts or html_parts).strip()
    return GmailMessage(
        message_id=message_id,
        thread_id=raw["threadId"],
        sender=headers.get("from", ""),
        subject=headers.get("subject", ""),
        body=body,
        history_id=raw.get("historyId"),
        rfc_message_id=headers.get("message-id"),
        references=headers.get("references"),
        attachments=attachments,
    )


class GmailClient:
    """Async Gmail API client using a short-lived OAuth access token."""

    def __init__(
        self,
        access_token: str,
        user_id: str = "me",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.user_id = user_id
        self.transport = transport
        self.headers = {"Authorization": f"Bearer {access_token}"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url="https://gmail.googleapis.com/gmail/v1",
            headers=self.headers,
            timeout=30,
            transport=self.transport,
        ) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

    async def list_added_message_ids(self, start_history_id: str) -> tuple[list[str], str]:
        """Return message IDs added since a durable Gmail history checkpoint."""
        message_ids: set[str] = set()
        page_token: str | None = None
        latest_history_id = start_history_id
        while True:
            params = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
            }
            if page_token:
                params["pageToken"] = page_token
            data = await self._request(
                "GET", f"/users/{self.user_id}/history", params=params
            )
            latest_history_id = data.get("historyId", latest_history_id)
            for history in data.get("history", []):
                for added in history.get("messagesAdded", []):
                    message_id = added.get("message", {}).get("id")
                    if message_id:
                        message_ids.add(message_id)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return sorted(message_ids), latest_history_id

    async def get_message(self, message_id: str) -> GmailMessage:
        data = await self._request(
            "GET",
            f"/users/{self.user_id}/messages/{message_id}",
            params={"format": "full"},
        )
        return normalize_message(data)

    async def search_message_ids(self, query: str, max_results: int = 10) -> list[str]:
        data = await self._request(
            "GET",
            f"/users/{self.user_id}/messages",
            params={"q": query, "maxResults": max_results},
        )
        return [message["id"] for message in data.get("messages", [])]

    async def has_draft_in_thread(self, thread_id: str, recipient: str) -> bool:
        """Check whether a retry already created a draft in this conversation."""
        for message_id in await self.search_message_ids(
            f"in:drafts to:{recipient}", max_results=20
        ):
            if (await self.get_message(message_id)).thread_id == thread_id:
                return True
        return False

    async def get_thread(self, thread_id: str) -> GmailThread:
        data = await self._request(
            "GET",
            f"/users/{self.user_id}/threads/{thread_id}",
            params={"format": "full"},
        )
        messages = [normalize_message(item) for item in data.get("messages", [])]
        return GmailThread(
            thread_id=thread_id,
            subject=messages[-1].subject if messages else "",
            body="\n\n--- message ---\n\n".join(
                message.body for message in messages if message.body
            ),
            messages=messages,
        )

    async def get_attachment(self, attachment: GmailAttachment) -> bytes:
        data = await self._request(
            "GET",
            f"/users/{self.user_id}/messages/{attachment.message_id}/attachments/{attachment.attachment_id}",
        )
        return _decode_websafe(data["data"])

    async def create_draft(
        self,
        recipient: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> str:
        """Create an unsent Gmail draft and return its draft ID."""
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to
            message["References"] = " ".join(
                part for part in [references, in_reply_to] if part
            )
        message.set_content(body)
        payload: dict[str, Any] = {
            "message": {
                "raw": base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
            }
        }
        if thread_id:
            payload["message"]["threadId"] = thread_id
        data = await self._request(
            "POST", f"/users/{self.user_id}/drafts", json=payload
        )
        return data["id"]

    async def send_message(self, recipient: str, subject: str, body: str) -> str:
        """Send one standalone message; callers must explicitly authorize this path."""
        message = EmailMessage()
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        data = await self._request(
            "POST",
            f"/users/{self.user_id}/messages/send",
            json={"raw": raw},
        )
        return data["id"]
