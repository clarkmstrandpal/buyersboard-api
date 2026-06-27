#!/usr/bin/env python3
"""Discover Lead Scout candidates from public Craigslist RSS feeds."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from candidate_finder import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_OPENAI_MODEL,
    build_report,
    domain_denied,
    import_candidates,
    infer_intent_and_role,
    load_market_packs,
    prefilter,
    score_candidates,
)
from lead_scout_sources import SourceContext, SourceResult, normalize_url


DEFAULT_IMPORT_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_FETCH_BYTES = 1_000_000
DEFAULT_USER_AGENT = "ListlyHomesLeadScout/0.1 (+https://listlyhomes.com)"
ACCEPT_HEADER = "application/rss+xml, application/xml, text/xml, */*"
ACCEPT_LANGUAGE_HEADER = "en-US,en;q=0.9"


class CraigslistRssError(RuntimeError):
    pass


class HtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = True

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg"):
            self._skip = False

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class CraigslistRssAdapter:
    name = "craigslist_rss"

    def __init__(self, feed_urls: list[str], limit: int, user_agent: str, debug: bool = False) -> None:
        self.feed_urls = feed_urls
        self.limit = limit
        self.user_agent = user_agent
        self.debug = debug
        self.errors: list[dict[str, str]] = []

    def discover(self, context: SourceContext) -> list[SourceResult]:
        results: list[SourceResult] = []
        for feed_url in self.feed_urls:
            try:
                items = fetch_feed_items(feed_url, self.limit, self.user_agent)
            except CraigslistRssError as exc:
                self.errors.append({"feed_url": feed_url, "error": str(exc)})
                continue
            for item in items:
                results.append(item_to_source_result(item, feed_url, context))
                if len(results) >= self.limit:
                    return results
        return results


def load_feed_urls(feed_urls: list[str] | None, seed_file: str | None) -> list[str]:
    urls = list(feed_urls or [])
    if seed_file:
        text = Path(seed_file).read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            urls.append(stripped)
    normalized: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized_url = normalize_url(url)
        parsed = urllib.parse.urlparse(normalized_url)
        if "craigslist.org" not in parsed.netloc.lower():
            raise ValueError(f"feed URL must be a craigslist.org RSS URL: {url}")
        if normalized_url not in seen:
            seen.add(normalized_url)
            normalized.append(normalized_url)
    if not normalized:
        raise ValueError("pass at least one --feed-url or --seed-file")
    return normalized


def fetch_feed_items(feed_url: str, limit: int, user_agent: str) -> list[dict[str, str]]:
    request = urllib.request.Request(
        feed_url,
        headers={
            "User-Agent": user_agent,
            "Accept": ACCEPT_HEADER,
            "Accept-Language": ACCEPT_LANGUAGE_HEADER,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            raw = response.read(DEFAULT_FETCH_BYTES)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CraigslistRssError(str(exc)) from exc

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise CraigslistRssError(f"RSS XML parse failed: {exc}") from exc

    items = []
    for element in iter_feed_entries(root):
        title = child_text(element, "title")
        link = entry_link(element)
        description = child_text(element, "description") or child_text(element, "summary") or child_text(element, "content")
        published = child_text(element, "pubDate") or child_text(element, "published") or child_text(element, "updated") or child_text(element, "date")
        if not title and not link:
            continue
        items.append(
            {
                "title": clean_text(title or link),
                "link": link,
                "description": clean_html(description),
                "published": published,
            }
        )
        if len(items) >= limit:
            break
    return items


def iter_feed_entries(root: ET.Element) -> list[ET.Element]:
    items = [element for element in root.iter() if local_name(element.tag) in ("item", "entry")]
    return items


def child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if local_name(child.tag) == name:
            return "".join(child.itertext()).strip()
    return ""


def entry_link(element: ET.Element) -> str:
    for child in element:
        if local_name(child.tag) != "link":
            continue
        href = child.attrib.get("href", "").strip()
        if href:
            return href
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return ""


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def clean_html(value: str) -> str:
    parser = HtmlTextParser()
    parser.feed(value or "")
    parser.close()
    return clean_text(parser.text or value)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:500]


def parse_feed_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        parsed = None
    if parsed:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).date().isoformat()
    except ValueError:
        return ""


def item_to_source_result(item: dict[str, str], feed_url: str, context: SourceContext) -> SourceResult:
    source_post_date = parse_feed_date(item.get("published", ""))
    metadata = {
        "adapter": "craigslist_rss",
        "feed_url": feed_url,
        "published": item.get("published", ""),
        "source_post_date": source_post_date,
        "market_slug": context.market_slug,
    }
    return SourceResult(
        title=item.get("title", ""),
        snippet=item.get("description", ""),
        source_url=item.get("link", ""),
        source="craigslist",
        provider="craigslist_rss",
        metadata=metadata,
    )


def source_result_to_candidate(result: SourceResult, pack: dict[str, Any], context: SourceContext) -> dict[str, Any]:
    intent, role = infer_intent_and_role(f"{result.title} {result.snippet}", context.vertical)
    candidate: dict[str, Any] = {
        "title": result.title,
        "snippet": result.snippet,
        "message": result.snippet or result.title,
        "source": "craigslist",
        "source_url": result.source_url,
        "market": pack.get("market"),
        "market_slug": context.market_slug,
        "county": context.county,
        "city": context.city,
        "state": context.state,
        "vertical": context.vertical,
        "role_guess": role,
        "intent_guess": intent,
        "intent_score": 0.0,
        "search_query": result.metadata.get("feed_url", "craigslist_rss"),
        "contact_method": "source_url",
        "source_adapter": "craigslist_rss",
        "source_strategy": "rss_feed",
        "source_category": "marketplace",
        "source_post_date": result.metadata.get("source_post_date", ""),
        "source_metadata": result.metadata,
    }
    return {key: value for key, value in candidate.items() if value not in (None, "")}


def is_stale(source_post_date: str, max_age_days: int) -> bool:
    try:
        parsed = date.fromisoformat(source_post_date)
    except ValueError:
        return False
    return (date.today() - parsed).days > max_age_days


def discover_craigslist_rss(
    feed_urls: list[str],
    market_slug: str,
    limit: int,
    max_age_days: int,
    user_agent: str,
    debug: bool,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Any]]:
    packs = load_market_packs()
    pack = packs.get(market_slug)
    if not pack:
        raise ValueError(f"unknown market: {market_slug}")
    city = (pack.get("cities") or [""])[0]
    county = (pack.get("counties") or [""])[0]
    context = SourceContext(
        vertical="real_estate",
        market=str(pack.get("market", "")),
        market_slug=market_slug,
        city=city,
        county=county,
        state=str(pack.get("state", "")),
    )
    adapter = CraigslistRssAdapter(feed_urls, limit, user_agent=user_agent, debug=debug)
    candidates: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen_urls: set[str] = set()
    diagnostics: dict[str, Any] = {
        "raw_result_count": 0,
        "provider_error_count": 0,
        "provider_errors": [],
        "cities_used": {market_slug: [city] if city else []},
        "generated_query_count": len(feed_urls),
        "executed_query_count": len(feed_urls),
        "domain_denied_count": 0,
        "prefilter_rejected_count": 0,
        "discussion_candidate_count": 0,
        "marketplace_candidate_count": 0,
        "dated_candidate_count": 0,
        "stale_rejected_count": 0,
        "unknown_date_rejected_count": 0,
    }
    debug_items: list[dict[str, Any]] = []

    for result in adapter.discover(context):
        diagnostics["raw_result_count"] += 1
        if debug:
            debug_items.append(
                {
                    "title": result.title,
                    "source_url": result.source_url,
                    "source_post_date": result.metadata.get("source_post_date", ""),
                    "feed_url": result.metadata.get("feed_url", ""),
                }
            )
        if not result.source_url:
            rejected["missing_source_url"] += 1
            continue
        if result.source_url in seen_urls:
            rejected["duplicate_source_url"] += 1
            continue
        seen_urls.add(result.source_url)
        source_post_date = str(result.metadata.get("source_post_date") or "")
        if not source_post_date:
            diagnostics["unknown_date_rejected_count"] += 1
            rejected["unknown_source_date"] += 1
            continue
        diagnostics["dated_candidate_count"] += 1
        if is_stale(source_post_date, max_age_days):
            diagnostics["stale_rejected_count"] += 1
            rejected["stale_source"] += 1
            continue
        if domain_denied(result.source_url):
            diagnostics["domain_denied_count"] += 1
            rejected["domain_denied"] += 1
            continue
        raw_result = {"title": result.title, "snippet": result.snippet, "source_url": result.source_url}
        reason = prefilter(raw_result, pack, context.city, context.county)
        if reason:
            rejected[reason] += 1
            continue
        diagnostics["marketplace_candidate_count"] += 1
        candidates.append(source_result_to_candidate(result, pack, context))

    diagnostics["provider_errors"] = adapter.errors
    diagnostics["provider_error_count"] = len(adapter.errors)
    rejected["provider_error"] += len(adapter.errors)
    diagnostics["candidate_after_dedupe_count"] = len(seen_urls)
    diagnostics["prefilter_rejected_count"] = (
        sum(rejected.values())
        - rejected.get("provider_error", 0)
        - rejected.get("duplicate_source_url", 0)
        - rejected.get("domain_denied", 0)
        - rejected.get("stale_source", 0)
        - rejected.get("unknown_source_date", 0)
    )
    if debug:
        diagnostics["debug"] = {"items": debug_items}
    return candidates, rejected, diagnostics


def debug_request_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": ACCEPT_HEADER,
        "Accept-Language": ACCEPT_LANGUAGE_HEADER,
    }


def write_output(path: str | None, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Lead Scout against public Craigslist RSS feeds.")
    parser.add_argument("--market", choices=("broward-fl", "northwest-ar"), required=True)
    parser.add_argument("--feed-url", action="append", help="Public Craigslist RSS feed URL. Repeatable.")
    parser.add_argument("--seed-file", help="Text file with one Craigslist RSS feed URL per line.")
    parser.add_argument("--max-age-days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header for Craigslist RSS requests.")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--show-rejected", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", help="Write dry-run report JSON to this file instead of stdout.")
    parser.add_argument("--ai-score", action="store_true", help="Use OPENAI_API_KEY for AI lead scoring when available.")
    parser.add_argument("--ai-max-candidates", type=int, help="Maximum surviving candidates to send to AI before falling back to rules.")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--import-url", help=f"Target /v1/candidates/import URL. Default when importing: {DEFAULT_IMPORT_URL}")
    parser.add_argument("--token", help="Bearer token from /v1/agents/login.")
    args = parser.parse_args()

    try:
        feed_urls = load_feed_urls(args.feed_url, args.seed_file)
        discovered, prefilter_reasons, discovery_diagnostics = discover_craigslist_rss(
            feed_urls,
            args.market,
            args.limit,
            args.max_age_days,
            args.user_agent,
            args.debug,
        )
        kept, rejected, score_reasons, scoring_diagnostics = score_candidates(
            discovered,
            args.min_confidence,
            args.ai_score,
            DEFAULT_OPENAI_MODEL,
            args.ai_max_candidates,
        )
    except (OSError, ValueError, CraigslistRssError, json.JSONDecodeError) as exc:
        print(f"Craigslist RSS lead scout failed: {exc}", file=sys.stderr)
        return 1

    report = build_report(
        kept,
        rejected,
        prefilter_reasons,
        score_reasons,
        discovery_diagnostics,
        scoring_diagnostics,
        args.show_rejected,
        args.debug,
    )
    report["raw_result_count"] = discovery_diagnostics["raw_result_count"]
    report["dated_candidate_count"] = discovery_diagnostics["dated_candidate_count"]
    report["stale_rejected_count"] = discovery_diagnostics["stale_rejected_count"]
    if args.debug:
        report.setdefault("debug", {})
        report["debug"]["request_user_agent"] = args.user_agent
        report["debug"]["request_headers"] = debug_request_headers(args.user_agent)
        report["debug"]["feed_urls"] = feed_urls
        report["debug"]["rss_items"] = discovery_diagnostics.get("debug", {}).get("items", [])
    write_output(args.output, report)

    if not args.import_url or not args.token:
        print("Import skipped: pass both --import-url and --token to import kept candidates.", file=sys.stderr)
        return 0
    if not kept:
        print("Import skipped: no kept candidates found.", file=sys.stderr)
        return 0
    try:
        result = import_candidates(args.import_url or DEFAULT_IMPORT_URL, args.token, kept)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
