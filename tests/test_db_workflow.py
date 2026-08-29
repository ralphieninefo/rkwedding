"""Focused tests for response synthesis shown in the control center."""

from app.db_workflow import _fallback_summary


def test_fallback_summary_removes_quoted_outreach_and_stays_concise() -> None:
    body = """Gentili Raphaël e Kassia,

Siamo disponibili e vi invieremo il preventivo domani. Possiamo ospitare 120 persone.

Il 29 agosto Raphaël ha scritto:
> Buongiorno,
> vorremmo informazioni per il matrimonio.
"""

    summary = _fallback_summary(body)

    assert "Siamo disponibili" in summary
    assert "Buongiorno" not in summary
    assert len(summary) <= 220
