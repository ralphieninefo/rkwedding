"""Gmail integration boundary."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GmailThread:
    """Normalized Gmail thread data used by the agent."""

    thread_id: str
    subject: str
    body: str


async def get_thread(thread_id: str) -> GmailThread:
    """Fetch a Gmail thread once Google authentication is configured."""
    raise NotImplementedError("Gmail integration is planned for a later phase.")
