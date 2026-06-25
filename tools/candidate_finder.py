#!/usr/bin/env python3
"""Find public Discovery Inbox candidate leads from market search templates."""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_IMPORT_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import"
MARKET_PACKS_PATH = Path(__file__).with_name("market_packs.json")
BLOCKED_DOMAINS = (
    "duckduckgo.com",
    "bing.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "nextdoor.com",
    "x.com",
    "twitter.com",
)


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_link = False
        self._in_snippet = False
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = attr.get("class", "")
        if tag == "a" and ("result__a" in classes or "result-link" in classes):
            if self._current and self._current.get("title") and self._current.get("source_url"):
                self.results.append(self._current)
            self._current = {"title": "", "source_url": _clean_ddg_url(attr.get("href", "")), "snippet": ""}
            self._in_link = True
        elif tag in ("a", "div", "td") and ("result__snippet" in classes or "result-snippet" in classes) and self._current is not None:
            self._in_snippet = True

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._in_link:
            self._current["title"] = (self._current.get("title", "") + " " + text).strip()
        elif self._in_snippet:
            self._current["snippet"] = (self._current.get("snippet", "") + " " + text).strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag in ("a", "div", "td") and self._in_snippet:
            self._in_snippet = False
        if tag == "div" and self._current and self._current.get("title") and self._current.get("source_url"):
            self.results.append(self._current)
            self._current = None
            self._in_link = False
            self._in_snippet = False

    def close(self) -> None:
        if self._current and self._current.get("title") and self._current.get("source_url"):
            self.results.append(self._current)
            self._current = None
        super().close()


def _clean_ddg_url(url: str) -> str:
    url = html.unescape(url)
    if "duckduckgo.com/y.js" in url or "duckduckgo.com/duckduckgo-help-pages/" in url:
        return ""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return query["uddg"][0]
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path in ("/l/", "/y.js"):
        return ""
    return url


def load_market_packs(path: Path = MARKET_PACKS_PATH) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("market_packs.json must contain an object")
    return data


def render_queries(pack: dict[str, Any], per_market: int) -> list[tuple[str, str | None, str | None]]:
    queries: list[tuple[str, str | None, str | None]] = []
    cities = pack.get("cities") or [None]
    counties = pack.get("counties") or [None]
    templates = pack.get("query_templates") or []
    for template in templates:
        for city in cities:
            county = counties[0] if counties else None
            query = template.format(
                market=pack.get("market", ""),
                market_slug=pack.get("market_slug", ""),
                state=pack.get("state", ""),
                county=county or "",
                city=city or "",
            )
            query = " ".join(query.split())
            if query:
                queries.append((query, city, county))
            if len(queries) >= per_market:
                return queries
    return queries


def public_search(query: str, limit: int) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; ListlyHomesCandidateFinder/0.1; public-search-only)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
    parser = DuckDuckGoParser()
    parser.feed(body)
    parser.close()
    return parser.results[:limit]


def blocked_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(domain in host for domain in BLOCKED_DOMAINS)


def guess_role(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("sell", "selling", "seller", "listing", "inherited")):
        return "seller"
    if any(word in lowered for word in ("buy", "buyer", "relocat", "looking for", "need a home")):
        return "buyer"
    if "invest" in lowered or "duplex" in lowered or "rental" in lowered:
        return "buyer"
    return None


def guess_intent(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("sell", "selling", "seller", "listing", "inherited")):
        return "sell"
    if "invest" in lowered or "duplex" in lowered or "rental" in lowered:
        return "invest"
    if "relocat" in lowered or "moving" in lowered:
        return "relocate"
    if any(word in lowered for word in ("buy", "buyer", "looking for", "need a home")):
        return "buy"
    return None


def normalize_result(result: dict[str, str], pack: dict[str, Any], query: str, city: str | None, county: str | None) -> dict[str, Any]:
    title = result.get("title", "").strip()
    snippet = result.get("snippet", "").strip()
    text = f"{title} {snippet}"
    candidate: dict[str, Any] = {
        "title": title,
        "snippet": snippet,
        "message": snippet,
        "source": "public_search",
        "source_url": result.get("source_url"),
        "market": pack.get("market"),
        "market_slug": pack.get("market_slug"),
        "county": county,
        "city": city,
        "state": pack.get("state"),
        "role_guess": guess_role(text),
        "intent_guess": guess_intent(text),
        "intent_score": 0.5,
        "search_query": query,
        "contact_method": "source_url",
    }
    return {key: value for key, value in candidate.items() if value not in (None, "")}


def find_candidates(markets: list[str], per_market: int, per_query: int) -> list[dict[str, Any]]:
    packs = load_market_packs()
    candidates: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for market_slug in markets:
        pack = packs.get(market_slug)
        if not pack:
            raise ValueError(f"unknown market: {market_slug}")
        for query, city, county in render_queries(pack, per_market):
            try:
                results = public_search(query, per_query)
            except urllib.error.URLError as exc:
                print(f"search failed for {market_slug}: {query}: {exc}", file=sys.stderr)
                continue
            for result in results:
                url = result.get("source_url", "")
                title = result.get("title", "").strip().lower()
                if not url or title == "more info" or url in seen_urls or blocked_url(url):
                    continue
                seen_urls.add(url)
                candidates.append(normalize_result(result, pack, query, city, county))
            time.sleep(0.5)

    return candidates


def import_candidates(url: str, token: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    body = json.dumps({"items": candidates}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def write_output(path: str | None, candidates: list[dict[str, Any]]) -> None:
    text = json.dumps(candidates, indent=2, sort_keys=True)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Find public candidate leads for Discovery Inbox markets.")
    parser.add_argument("--market", action="append", choices=("broward-fl", "northwest-ar"), help="Market slug. Repeat to search multiple markets.")
    parser.add_argument("--all-markets", action="store_true", help="Search all configured markets.")
    parser.add_argument("--queries-per-market", type=int, default=4, help="Maximum rendered queries per market.")
    parser.add_argument("--results-per-query", type=int, default=5, help="Maximum search results to keep per query.")
    parser.add_argument("--output", help="Write normalized candidate JSON to this file instead of stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Find and print/write candidates without importing.")
    parser.add_argument("--import-url", default=DEFAULT_IMPORT_URL, help="Target /v1/candidates/import URL.")
    parser.add_argument("--token", default=os.environ.get("CANDIDATE_IMPORT_TOKEN"), help="Bearer token from /v1/agents/login.")
    args = parser.parse_args()

    markets = ["broward-fl", "northwest-ar"] if args.all_markets else args.market
    if not markets:
        parser.error("use --market or --all-markets")

    candidates = find_candidates(markets, args.queries_per_market, args.results_per_query)
    write_output(args.output, candidates)
    print(f"candidate_count: {len(candidates)}", file=sys.stderr)

    if args.dry_run:
        return 0
    if not args.token:
        print("Import failed: --token or CANDIDATE_IMPORT_TOKEN is required", file=sys.stderr)
        return 1
    if not candidates:
        print("Import skipped: no candidates found", file=sys.stderr)
        return 0

    try:
        result = import_candidates(args.import_url, args.token, candidates)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
