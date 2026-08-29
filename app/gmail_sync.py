"""Read recent Gmail threads and identify replies to sent outreach."""

from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

from googleapiclient.discovery import build

from app.gmail_oauth import load_credentials
from app.response_tracker import upsert_response


def _headers(message: dict[str, Any]) -> dict[str, str]:
    return {
        item.get("name", "").lower(): item.get("value", "")
        for item in message.get("payload", {}).get("headers", [])
    }


def _received_at(message: dict[str, Any]) -> str:
    milliseconds = int(message.get("internalDate", "0"))
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC).isoformat()


def sync_recent_responses(
    days: int = 30,
    max_threads: int = 100,
    service: Any | None = None,
) -> dict[str, int | str]:
    """Track threads containing an outbound message followed by an inbound reply."""
    if service is None:
        service = build(
            "gmail", "v1", credentials=load_credentials(), cache_discovery=False
        )
    profile = service.users().getProfile(userId="me").execute()
    mailbox = profile["emailAddress"].casefold()
    result = (
        service.users()
        .threads()
        .list(userId="me", q=f"in:inbox newer_than:{days}d", maxResults=max_threads)
        .execute()
    )

    tracked = 0
    newly_found = 0
    for thread_ref in result.get("threads", []):
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_ref["id"], format="full")
            .execute()
        )
        messages = sorted(
            thread.get("messages", []), key=lambda item: int(item.get("internalDate", "0"))
        )
        sent_seen = False
        latest_reply: dict[str, Any] | None = None
        for message in messages:
            headers = _headers(message)
            sender_email = parseaddr(headers.get("from", ""))[1].casefold()
            if "SENT" in message.get("labelIds", []) or sender_email == mailbox:
                sent_seen = True
            elif sent_seen and sender_email:
                latest_reply = message
        if not latest_reply:
            continue

        headers = _headers(latest_reply)
        sender_name, sender_email = parseaddr(headers.get("from", ""))
        response = {
            "thread_id": thread["id"],
            "message_id": latest_reply["id"],
            "sender_name": sender_name or sender_email.split("@")[0],
            "sender_email": sender_email.casefold(),
            "subject": headers.get("subject", "(no subject)"),
            "received_at": _received_at(latest_reply),
            "snippet": latest_reply.get("snippet", ""),
        }
        if upsert_response(response):
            newly_found += 1
        tracked += 1

    return {
        "mailbox": mailbox,
        "threads_checked": len(result.get("threads", [])),
        "responses_tracked": tracked,
        "new_responses": newly_found,
    }
