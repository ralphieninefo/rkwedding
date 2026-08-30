"""Tests for public venue website contact discovery."""

from app.discovery import _details


def test_contact_details_are_extracted_from_public_html() -> None:
    result = _details(
        "https://venue.example/",
        """
        <html><head><meta property="og:site_name" content="Villa Example"></head>
        <body><a href="mailto:info@venue.example">Email</a>
        <a href="tel:+39061234567">Call</a><address>Frascati, Italy</address></body></html>
        """,
    )

    assert result.name == "Villa Example"
    assert result.email == "info@venue.example"
    assert result.phone == "+39061234567"
    assert result.location == "Frascati, Italy"
