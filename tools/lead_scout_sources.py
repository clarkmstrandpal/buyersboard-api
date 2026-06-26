"""Lead Scout source adapter primitives for local candidate discovery."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol


DEFAULT_FETCH_BYTES = 120_000
DEFAULT_TIMEOUT_SECONDS = 20
BODY_EXCERPT_CHARS = 500
DATE_SCAN_CHARS = 40_000
DATE_PATTERNS = (
    re.compile(r"\b(\d{1,2})-(\d{1,2})-(\d{4})(?:,\s+\d{1,2}:\d{2}\s*[AP]M)?\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+\d{1,2}:\d{2}\s*[AP]M)?\b", re.IGNORECASE),
    re.compile(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+"
        r"(\d{1,2}),\s+(\d{4})\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
)
MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


@dataclass(frozen=True)
class SourceContext:
    vertical: str
    market: str
    market_slug: str
    city: str
    county: str
    state: str


@dataclass(frozen=True)
class SourceResult:
    title: str
    snippet: str
    source_url: str
    source: str
    provider: str
    metadata: dict[str, Any]


class SourceAdapter(Protocol):
    name: str

    def discover(self, context: SourceContext) -> list[SourceResult]:
        """Return source results for a local Lead Scout run."""


class PageSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.description = ""
        self.body_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._in_skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript", "svg"):
            self._in_skip = True
        elif tag == "meta" and attr.get("name", "").lower() == "description":
            self.description = " ".join(attr.get("content", "").split())

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        elif not self._in_skip and len(" ".join(self.body_parts)) < BODY_EXCERPT_CHARS:
            self.body_parts.append(text)
        if not self._in_skip and len(" ".join(self.text_parts)) < DATE_SCAN_CHARS:
            self.text_parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript", "svg"):
            self._in_skip = False

    @property
    def body_excerpt(self) -> str:
        return " ".join(" ".join(self.body_parts).split())[:BODY_EXCERPT_CHARS]

    @property
    def searchable_text(self) -> str:
        return " ".join(" ".join(self.text_parts).split())[:DATE_SCAN_CHARS]


class ManualPublicUrlSeedAdapter:
    name = "manual_public_urls"

    def __init__(self, seed_file: Path, fetch_pages: bool = True) -> None:
        self.seed_file = seed_file
        self.fetch_pages = fetch_pages

    def discover(self, context: SourceContext) -> list[SourceResult]:
        rows = load_seed_rows(self.seed_file)
        results: list[SourceResult] = []
        seen: set[str] = set()
        for row in rows:
            url = normalize_url(str(row["url"]))
            if not url or url in seen:
                continue
            seen.add(url)
            page = fetch_page_summary(url) if self.fetch_pages else {}
            title = str(row.get("title") or page.get("title") or url)
            snippet = str(row.get("snippet") or page.get("description") or page.get("body_excerpt") or "")
            metadata = {
                "adapter": self.name,
                "approved_source": "manual_seed",
                "fetch_error": page.get("fetch_error", ""),
                "source_post_date": str(row.get("source_post_date") or row.get("extracted_date") or page.get("source_post_date") or ""),
            }
            results.append(
                SourceResult(
                    title=title,
                    snippet=snippet,
                    source_url=url,
                    source=self.name,
                    provider=self.name,
                    metadata=metadata,
                )
            )
        return results


def load_seed_rows(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if path.suffix.lower() == ".json" or stripped[0] in "[{":
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            payload = payload.get("urls") or payload.get("items") or []
        if not isinstance(payload, list):
            raise ValueError("seed JSON must contain an array, urls array, or items array")
        rows = []
        for item in payload:
            if isinstance(item, str):
                rows.append({"url": item})
            elif isinstance(item, dict) and item.get("url"):
                rows.append(item)
            else:
                raise ValueError("seed JSON entries must be URL strings or objects with url")
        return rows
    return [{"url": line.strip()} for line in stripped.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def normalize_url(url: str) -> str:
    url = url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"seed URL must be http/https: {url}")
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def fetch_page_summary(url: str) -> dict[str, str]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 ListlyLeadScout/1.0", "Accept": "text/html, text/plain;q=0.8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw = response.read(DEFAULT_FETCH_BYTES)
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"fetch_error": str(exc)}
    text = raw.decode("utf-8", errors="replace")
    if "html" not in content_type.lower():
        return {"body_excerpt": excerpt_text(text), "source_post_date": extract_source_post_date(text), "fetch_error": ""}
    parser = PageSummaryParser()
    parser.feed(text)
    parser.close()
    return {
        "title": parser.title,
        "description": parser.description,
        "body_excerpt": parser.body_excerpt,
        "source_post_date": extract_source_post_date(parser.searchable_text or text),
        "fetch_error": "",
    }


def excerpt_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:BODY_EXCERPT_CHARS]


def extract_source_post_date(text: str) -> str:
    search = re.sub(r"\s+", " ", text)[:DATE_SCAN_CHARS]
    for pattern in DATE_PATTERNS:
        match = pattern.search(search)
        if not match:
            continue
        parsed = parse_date_match(match)
        if parsed:
            return parsed.isoformat()
    lowered = search.lower()
    today = date.today()
    if re.search(r"\btoday,\s+\d{1,2}:\d{2}\s*[ap]m\b", lowered):
        return today.isoformat()
    if re.search(r"\byesterday,\s+\d{1,2}:\d{2}\s*[ap]m\b", lowered):
        return (today - timedelta(days=1)).isoformat()
    return ""


def parse_date_match(match: re.Match[str]) -> date | None:
    groups = match.groups()
    try:
        if len(groups) >= 3 and groups[0].isalpha():
            return date(int(groups[2]), MONTHS[groups[0].lower()], int(groups[1]))
        if len(groups) >= 3 and len(groups[0]) == 4:
            return date(int(groups[0]), int(groups[1]), int(groups[2]))
        return date(int(groups[2]), int(groups[0]), int(groups[1]))
    except ValueError:
        return None
