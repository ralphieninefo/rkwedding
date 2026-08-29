"""Transparent, deterministic venue comparison rules."""

from app.models import VenueCandidate, VenueRanking


WEIGHTS = {
    "price_score": 0.30,
    "location_score": 0.20,
    "value_score": 0.20,
    "availability_score": 0.10,
    "quality_score": 0.10,
    "logistics_score": 0.10,
}


def price_score(cost: float | None) -> float | None:
    """Map the current EUR budget bands to a 0–100 score."""
    if cost is None:
        return None
    if cost <= 25_000:
        return 100.0
    if cost <= 30_000:
        return 100.0 - ((cost - 25_000) / 5_000) * 20.0
    if cost <= 40_000:
        return 80.0 - ((cost - 30_000) / 10_000) * 80.0
    return 0.0


def rank_venues(venues: list[VenueCandidate]) -> list[VenueRanking]:
    """Rank venues using only supplied facts and fixed weights.

    Missing dimensions are excluded and the remaining weights are normalized.
    A completeness/confidence penalty keeps sparse quotes from outranking complete
    ones merely because unknown values were omitted.
    """
    unranked: list[VenueRanking] = []
    for venue in venues:
        values = {
            "price_score": price_score(venue.normalized_all_in_cost),
            "location_score": venue.location_score,
            "value_score": venue.value_score,
            "availability_score": venue.availability_score,
            "quality_score": venue.quality_score,
            "logistics_score": venue.logistics_score,
        }
        present_weight = sum(
            WEIGHTS[field] for field, value in values.items() if value is not None
        )
        weighted_score = (
            sum(
                value * WEIGHTS[field]
                for field, value in values.items()
                if value is not None
            )
            / present_weight
            if present_weight
            else 0.0
        )
        completeness = present_weight / sum(WEIGHTS.values())
        confidence_factor = 0.75 + (0.25 * venue.data_confidence)
        completeness_factor = 0.70 + (0.30 * completeness)
        final_score = weighted_score * confidence_factor * completeness_factor
        missing = [field for field, value in values.items() if value is None]

        reasons: list[str] = []
        calculated_price = values["price_score"]
        if calculated_price is not None:
            reasons.append(f"Price score {calculated_price:.1f}/100")
        if venue.location_score is not None:
            reasons.append(f"Location score {venue.location_score:.1f}/100")
        if venue.value_score is not None:
            reasons.append(f"Value score {venue.value_score:.1f}/100")
        if missing:
            reasons.append(f"Missing {len(missing)} comparison field(s)")

        unranked.append(
            VenueRanking(
                rank=1,
                venue=venue.venue,
                score=round(final_score, 2),
                price_score=(
                    round(calculated_price, 2)
                    if calculated_price is not None
                    else None
                ),
                data_completeness=round(completeness, 2),
                reasons=reasons,
                missing_fields=missing,
            )
        )

    unranked.sort(key=lambda item: (-item.score, item.venue.casefold()))
    return [item.model_copy(update={"rank": index}) for index, item in enumerate(unranked, 1)]
