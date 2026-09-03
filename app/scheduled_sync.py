"""Scheduled Gmail-to-database reconciliation for App Platform."""

import asyncio
import json
import sys

from app.config import get_settings
from app.database import init_database
from app.db_workflow import reconcile_gmail_database
from app.gmail_oauth import gmail_connected


async def sync_once() -> dict[str, object]:
    """Run one idempotent Gmail synchronization.

    ``status`` is ``completed`` when every mailbox synchronized,
    ``completed_with_errors`` when at least one mailbox failed but another
    succeeded, and ``failed`` when no mailbox could be checked. Per-mailbox
    outcomes are also persisted for the dashboard by the reconciliation itself.
    """
    init_database()
    if not gmail_connected():
        return {"status": "skipped", "reason": "Google is not connected."}
    result = await reconcile_gmail_database(get_settings(), days=30)
    failed = list(result.get("accounts_failed") or [])
    synced = list(result.get("accounts_synced") or [])
    if not failed:
        status = "completed"
    elif synced:
        status = "completed_with_errors"
    else:
        status = "failed"
    return {"status": status, **result}


def main() -> None:
    """Run the scheduled task, emit one structured log line, and exit."""
    result = asyncio.run(sync_once())
    print(json.dumps(result, sort_keys=True, default=str))
    if result.get("status") == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
