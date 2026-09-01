"""Repair stored reply summaries after inference becomes available."""

import asyncio
import json

from sqlalchemy import select

from app.config import get_settings
from app.database import Message, SessionLocal, Venue
from app.db_workflow import _save_estimate, _synthesize
from app.gmail import GmailMessage


async def repair_unavailable_summaries() -> dict[str, int]:
    with SessionLocal() as session:
        candidate_ids = session.scalars(
            select(Message.id)
            .where(
                Message.direction == "inbound",
                Message.synthesized_summary.contains("temporarily unavailable"),
            )
            .order_by(Message.occurred_at)
        ).all()

    repaired = 0
    for message_id in candidate_ids:
        with SessionLocal() as session:
            stored = session.get(Message, message_id)
            if stored is None:
                continue
            venue = session.get(Venue, stored.venue_id)
            if venue is None:
                continue
            gmail_message = GmailMessage(
                message_id=stored.gmail_message_id,
                thread_id=stored.gmail_thread_id,
                sender="",
                recipients="",
                subject=stored.subject,
                body=stored.body,
                received_at=stored.occurred_at.isoformat(),
            )
            venue_id = venue.id
        synthesis, status = await _synthesize(get_settings(), gmail_message, venue)
        if "temporarily unavailable" in synthesis.summary:
            continue
        with SessionLocal() as session:
            stored = session.get(Message, message_id)
            venue = session.get(Venue, venue_id)
            if stored is None or venue is None:
                continue
            stored.synthesized_summary = synthesis.summary
            latest_inbound_id = session.scalar(
                select(Message.id)
                .where(Message.venue_id == venue_id, Message.direction == "inbound")
                .order_by(Message.occurred_at.desc())
            )
            if latest_inbound_id == stored.id:
                venue.response_summary = synthesis.summary
                venue.status = status
            _save_estimate(session, venue_id, stored.gmail_message_id, synthesis)
            session.commit()
            repaired += 1
    return {"candidates": len(candidate_ids), "repaired": repaired}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(repair_unavailable_summaries())))
