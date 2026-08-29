"""Deterministically write Gmail response state into the Venues Sheet."""

from app.config import Settings
from app.gmail_sync import find_recent_responses
from app.google_auth import get_google_access_token
from app.sheets import GoogleSheetsClient
from starlette.concurrency import run_in_threadpool


async def sync_gmail_responses_to_sheet(settings: Settings) -> dict[str, object]:
    """Match replies by exact sender email and update only workflow columns."""
    if not settings.google_spreadsheet_id:
        raise ValueError("Google Sheet is not configured.")

    mailbox, threads_checked, responses = await run_in_threadpool(
        find_recent_responses
    )
    access_token = await get_google_access_token(settings)
    sheets = GoogleSheetsClient(access_token, settings.google_spreadsheet_id)
    venues = await sheets.get_rows(settings.google_venues_sheet)
    rows_by_email = {
        row.get("Email", "").strip().casefold(): row
        for row in venues
        if row.get("Email", "").strip()
    }

    matched = 0
    unmatched: list[str] = []
    for response in responses:
        row = rows_by_email.get(response["sender_email"].casefold())
        if not row:
            unmatched.append(response["sender_email"])
            continue
        await sheets.update_row(
            settings.google_venues_sheet,
            int(row["_row_number"]),
            {
                "Status": "Responded",
                "Response Received": "Yes",
                "Gmail Thread ID": response["thread_id"],
                "Last Response": response["received_at"],
                "Response Summary": response["snippet"],
            },
        )
        matched += 1

    return {
        "mailbox": mailbox,
        "threads_checked": threads_checked,
        "responses_found": len(responses),
        "venues_updated": matched,
        "unmatched_senders": sorted(set(unmatched)),
    }
