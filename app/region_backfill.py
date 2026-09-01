"""One-time metadata repair for venues saved before region discovery existed."""

import asyncio
import json

from sqlalchemy import or_, select

from app.database import SessionLocal, Venue
from app.discovery import discover_venue


async def backfill_missing_regions() -> dict[str, int]:
    with SessionLocal() as session:
        candidates = session.scalars(
            select(Venue).where(or_(Venue.region.is_(None), Venue.region == ""))
        ).all()
        candidate_ids = [venue.id for venue in candidates]

    repaired = inspected = 0
    for venue_id in candidate_ids:
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            if venue is None or (venue.region or "").strip():
                continue
            if (venue.location or "").strip():
                venue.region = venue.location.strip()
                session.commit()
                repaired += 1
                continue
            website = (venue.website or "").strip()
        if not website:
            continue
        inspected += 1
        try:
            details = await discover_venue(website)
        except Exception:  # A venue site failure must not abort the whole repair.
            continue
        region = (details.region or details.location).strip()
        if not region:
            continue
        with SessionLocal() as session:
            venue = session.get(Venue, venue_id)
            if venue is None or (venue.region or "").strip():
                continue
            venue.region = region
            if not (venue.location or "").strip() and details.location:
                venue.location = details.location.strip()
            session.commit()
            repaired += 1
    return {"candidates": len(candidate_ids), "inspected": inspected, "repaired": repaired}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(backfill_missing_regions())))
