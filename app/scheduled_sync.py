"""Scheduled Gmail-to-database reconciliation for App Platform."""

import asyncio
import json

from app.config import get_settings
from app.database import init_database
from app.db_workflow import reconcile_gmail_database
from app.gmail_oauth import gmail_connected


async def sync_once() -> dict[str, object]:
    """Run one idempotent Gmail synchronization."""
    init_database()
    if not gmail_connected():
        return {"status": "skipped", "reason": "Google is not connected."}
    result = await reconcile_gmail_database(get_settings(), days=30)
    return {"status": "completed", **result}


def main() -> None:
    """Run the scheduled task and emit one structured log line."""
    print(json.dumps(asyncio.run(sync_once()), sort_keys=True))


if __name__ == "__main__":
    main()
