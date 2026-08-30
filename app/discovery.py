"""Safe, small public-website contact discovery for venue onboarding."""

import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import httpx

from app.models import VenueDiscovery


EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+39[\s.-]?)?(?:0\d{1,3}|3\d{2})[\s.-]?\d(?:[\s.-]?\d){5,9}")


async def _validate_public_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a valid public http or https URL.")
    if parsed.username or parsed.password:
        raise ValueError("Website credentials are not supported.")
    records = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
    )
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            raise ValueError("Only public venue websites can be inspected.")
    return value


async def _fetch(client: httpx.AsyncClient, value: str) -> tuple[str, str]:
    current = await _validate_public_url(value)
    for _ in range(4):
        response = await client.get(current)
        if response.is_redirect:
            target = response.headers.get("location")
            if not target:
                break
            current = await _validate_public_url(urljoin(current, target))
            continue
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            raise ValueError("That URL is not an HTML venue page.")
        return str(response.url), response.text[:2_000_000]
    raise ValueError("The venue website redirected too many times.")


def _emails(soup: BeautifulSoup, text: str) -> list[str]:
    candidates = {
        link.get("href", "").split(":", 1)[1].split("?", 1)[0].strip().casefold()
        for link in soup.select('a[href^="mailto:"]')
        if ":" in link.get("href", "")
    }
    candidates.update(email.casefold() for email in EMAIL_RE.findall(text))
    candidates = {email for email in candidates if not email.endswith((".png", ".jpg"))}
    priorities = ("info@", "eventi@", "events@", "wedding@", "booking@", "contact@")
    return sorted(candidates, key=lambda email: (not email.startswith(priorities), email))


def _details(url: str, html: str) -> VenueDiscovery:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = _emails(soup, text)
    site_name = soup.select_one('meta[property="og:site_name"]')
    title = site_name.get("content", "").strip() if site_name else ""
    if not title and soup.title:
        title = re.split(r"\s+[|–—-]\s+", soup.title.get_text(" ", strip=True))[0]
    phone_link = soup.select_one('a[href^="tel:"]')
    phone = phone_link.get("href", "").split(":", 1)[-1].strip() if phone_link else ""
    if not phone:
        match = PHONE_RE.search(text)
        phone = match.group(0).strip() if match else ""
    address = soup.find("address")
    return VenueDiscovery(
        name=title,
        location=address.get_text(" ", strip=True)[:250] if address else "",
        email=emails[0] if emails else "",
        website=url,
        phone=phone[:100],
    )


async def discover_venue(value: str) -> VenueDiscovery:
    headers = {"User-Agent": "WeddingVenueControlCenter/1.0 contact-discovery"}
    async with httpx.AsyncClient(timeout=12, headers=headers, follow_redirects=False) as client:
        url, html = await _fetch(client, value)
        result = _details(url, html)
        if result.email:
            return result
        soup = BeautifulSoup(html, "html.parser")
        links = []
        for link in soup.select("a[href]"):
            href = link.get("href", "")
            label = (link.get_text(" ", strip=True) + " " + href).casefold()
            candidate = urljoin(url, href)
            if urlparse(candidate).hostname == urlparse(url).hostname and any(
                word in label for word in ("contact", "contatt", "event", "wedding")
            ):
                links.append(candidate)
        for candidate in list(dict.fromkeys(links))[:2]:
            contact_url, contact_html = await _fetch(client, candidate)
            contact = _details(contact_url, contact_html)
            if contact.email:
                return VenueDiscovery(
                    name=result.name or contact.name,
                    location=result.location or contact.location,
                    email=contact.email,
                    website=url,
                    phone=result.phone or contact.phone,
                )
    return result
