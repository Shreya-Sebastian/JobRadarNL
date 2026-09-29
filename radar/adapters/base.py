from __future__ import annotations

import html
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

from radar.config import settings


class RawPosting(BaseModel):
    """A posting exactly as one source reports it, before normalisation."""

    external_id: str
    title: str
    url: str
    company: str | None = None  # the hiring organisation when a board hosts many employers
    location: str | None = None
    city: str | None = None
    country: str | None = None
    remote: bool | None = None
    description_html: str | None = None
    description_text: str | None = None
    posted_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    def text(self) -> str:
        if self.description_text:
            return self.description_text
        if self.description_html:
            return html_to_text(self.description_html)
        return ""


class AdapterError(Exception):
    pass


class SourceNotFound(AdapterError):
    """The board does not exist (HTTP 404 or equivalent): deactivate the source."""


class Adapter(ABC):
    ats: str = "base"

    def __init__(self, client: httpx.Client | None = None):
        self._client = client

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            from radar.ratelimit import throttle_request

            self._client = httpx.Client(
                timeout=settings.http_timeout,
                headers={"User-Agent": settings.user_agent, "Accept": "application/json, text/html;q=0.8"},
                follow_redirects=True,
                event_hooks={"request": [throttle_request]},
            )
        return self._client

    @abstractmethod
    def fetch(self, slug: str) -> list[RawPosting]:
        """Return every posting currently listed on the board identified by slug."""

    def probe(self, slug: str) -> bool:
        """Cheaply test whether the board exists. Default: try a fetch."""
        try:
            self.fetch(slug)
            return True
        except SourceNotFound:
            return False

    def _get_json(self, url: str, **params: Any) -> Any:
        resp = self.client.get(url, params=params or None)
        if resp.status_code == 404:
            raise SourceNotFound(url)
        if resp.status_code >= 400:
            raise AdapterError(f"{resp.status_code} for {url}")
        try:
            return resp.json()
        except ValueError as e:
            raise AdapterError(f"non-JSON response from {url}") from e


_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def html_to_text(fragment: str) -> str:
    """Convert an HTML fragment (possibly entity-escaped, as Greenhouse does) to readable text."""
    if not fragment:
        return ""
    if "<" not in fragment and "&lt;" in fragment:
        fragment = html.unescape(fragment)
    soup = BeautifulSoup(fragment, "lxml")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "ul", "ol"]):
        block.append("\n")
    text = soup.get_text()
    text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = _NL.sub("\n\n", text)
    return text.strip()


def parse_dt(value: Any) -> datetime | None:
    """Parse ISO strings and epoch milliseconds into naive UTC datetimes."""
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 1e11:
                ts /= 1000.0
            return datetime.utcfromtimestamp(ts)
        from dateutil import parser as dtparser

        dt = dtparser.parse(str(value))
        if dt.tzinfo is not None:
            dt = dt.astimezone(tz=None).replace(tzinfo=None)
        return dt
    except (ValueError, OverflowError, TypeError):
        return None
