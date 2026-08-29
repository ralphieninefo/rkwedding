"""Tests for deterministic venue comparison."""

from app.models import VenueCandidate
from app.scoring import price_score, rank_venues


def test_price_score_uses_budget_bands() -> None:
    assert price_score(25_000) == 100
    assert price_score(30_000) == 80
    assert price_score(35_000) == 40
    assert price_score(40_000) == 0
    assert price_score(45_000) == 0


def test_rank_venues_orders_by_weighted_score() -> None:
    rankings = rank_venues(
        [
            VenueCandidate(
                venue="Beautiful but expensive",
                normalized_all_in_cost=38_000,
                location_score=95,
                value_score=60,
                availability_score=100,
                quality_score=95,
                logistics_score=80,
            ),
            VenueCandidate(
                venue="Best balance",
                normalized_all_in_cost=28_000,
                location_score=85,
                value_score=90,
                availability_score=100,
                quality_score=85,
                logistics_score=80,
            ),
        ]
    )

    assert rankings[0].venue == "Best balance"
    assert rankings[0].rank == 1
    assert rankings[1].rank == 2


def test_missing_data_is_reported_and_penalized() -> None:
    rankings = rank_venues(
        [
            VenueCandidate(venue="Sparse", normalized_all_in_cost=24_000),
            VenueCandidate(
                venue="Complete",
                normalized_all_in_cost=24_000,
                location_score=100,
                value_score=100,
                availability_score=100,
                quality_score=100,
                logistics_score=100,
            ),
        ]
    )

    sparse = next(item for item in rankings if item.venue == "Sparse")
    complete = next(item for item in rankings if item.venue == "Complete")
    assert sparse.score < complete.score
    assert "location_score" in sparse.missing_fields
    assert sparse.data_completeness == 0.3
