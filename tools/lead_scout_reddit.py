#!/usr/bin/env python3
"""Discover Lead Scout candidates from public Reddit posts via OAuth API."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
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
from lead_scout_sources import SourceContext, SourceResult


DEFAULT_IMPORT_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_BASE_URL = "https://oauth.reddit.com"

DEFAULT_SUBREDDITS = {
    "broward-fl": ("fortlauderdale", "SouthFlorida"),
    "northwest-ar": ("FayettevilleAr", "Arkansas"),
}
DEFAULT_QUERIES = (
    "moving",
    "rent",
    "rental",
    "apartment",
    "landlord",
    "where should I live",
    "looking for a place",
)


class RedditApiError(RuntimeError):
    pass


class RedditClient:
    def __init__(self, client_id: str, client_secret: str, user_agent: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self._token = ""

    def authenticate(self) -> None:
        auth = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode("utf-8")).decode("ascii")
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
        request = urllib.request.Request(
            TOKEN_URL,
            data=data,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RedditApiError(f"Reddit OAuth failed: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise RedditApiError("Reddit OAuth response did not include access_token")
        self._token = str(token)

    def get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._token:
            self.authenticate()
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{OAUTH_BASE_URL}{path}?{query}",
            headers={"Authorization": f"Bearer {self._token}", "User-Agent": self.user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RedditApiError(f"Reddit API request failed for {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise RedditApiError(f"Reddit API returned non-object payload for {path}")
        return payload

    def search_subreddit(self, subreddit: str, query: str, limit: int) -> list[dict[str, Any]]:
        payload = self.get_json(
            f"/r/{subreddit}/search",
            {
                "q": query,
                "restrict_sr": "on",
                "sort": "new",
                "t": "month",
                "limit": limit,
                "raw_json": 1,
            },
        )
        children = payload.get("data", {}).get("children", [])
        if not isinstance(children, list):
            return []
        posts = []
        for child in children:
            if isinstance(child, dict) and isinstance(child.get("data"), dict):
                posts.append(child["data"])
        return posts


def load_reddit_credentials() -> tuple[str, str, str] | None:
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    user_agent = os.environ.get("REDDIT_USER_AGENT", "").strip()
    if client_id and client_secret and user_agent:
        return client_id, client_secret, user_agent
    print(
        "Missing Reddit API credentials.\n"
        "Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and REDDIT_USER_AGENT in your environment.\n"
        "Use a Reddit app with read-only script/app credentials; do not commit credentials.",
        file=sys.stderr,
    )
    return None


def post_date_from_created_utc(value: Any) -> str:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).date().isoformat()


def reddit_permalink(permalink: str) -> str:
    if permalink.startswith("http://") or permalink.startswith("https://"):
        return permalink
    return f"https://www.reddit.com{permalink}"


def post_to_source_result(post: dict[str, Any]) -> SourceResult:
    title = str(post.get("title") or "").strip()
    selftext = str(post.get("selftext") or "").strip()
    permalink = reddit_permalink(str(post.get("permalink") or ""))
    source_post_date = post_date_from_created_utc(post.get("created_utc"))
    metadata = {
        "subreddit": str(post.get("subreddit") or ""),
        "score": int(post.get("score") or 0),
        "num_comments": int(post.get("num_comments") or 0),
        "source_post_date": source_post_date,
        "created_utc": post.get("created_utc"),
        "reddit_id": str(post.get("id") or ""),
    }
    return SourceResult(
        title=title,
        snippet=selftext[:500],
        source_url=permalink,
        source="reddit",
        provider="reddit",
        metadata=metadata,
    )


def source_result_to_candidate(result: SourceResult, pack: dict[str, Any], context: SourceContext, query: str) -> dict[str, Any]:
    intent, role = infer_intent_and_role(f"{result.title} {result.snippet}", context.vertical)
    candidate: dict[str, Any] = {
        "title": result.title,
        "snippet": result.snippet,
        "message": result.snippet or result.title,
        "source": "reddit",
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
        "search_query": query,
        "contact_method": "source_url",
        "source_adapter": "reddit",
        "source_category": "discussion",
        "source_post_date": result.metadata.get("source_post_date", ""),
        "subreddit": result.metadata.get("subreddit", ""),
        "reddit_score": result.metadata.get("score", 0),
        "reddit_num_comments": result.metadata.get("num_comments", 0),
    }
    return {key: value for key, value in candidate.items() if value not in (None, "")}


def is_stale(source_post_date: str, max_age_days: int) -> bool:
    try:
        parsed = date.fromisoformat(source_post_date)
    except ValueError:
        return False
    return (date.today() - parsed).days > max_age_days


def discover_reddit(
    client: RedditClient,
    market_slug: str,
    subreddits: list[str],
    queries: list[str],
    limit: int,
    max_age_days: int,
    min_score: int,
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
    candidates: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen_urls: set[str] = set()
    diagnostics: dict[str, Any] = {
        "raw_result_count": 0,
        "reddit_posts_seen_count": 0,
        "reddit_posts_matched_count": 0,
        "provider_error_count": 0,
        "provider_errors": [],
        "cities_used": {market_slug: [city] if city else []},
        "generated_query_count": len(subreddits) * len(queries),
        "executed_query_count": 0,
        "domain_denied_count": 0,
        "prefilter_rejected_count": 0,
        "discussion_candidate_count": 0,
        "marketplace_candidate_count": 0,
        "dated_candidate_count": 0,
        "stale_rejected_count": 0,
        "unknown_date_rejected_count": 0,
    }
    debug_items: list[dict[str, Any]] = []

    for subreddit in subreddits:
        for query in queries:
            diagnostics["executed_query_count"] += 1
            try:
                posts = client.search_subreddit(subreddit, query, limit)
            except RedditApiError as exc:
                diagnostics["provider_error_count"] += 1
                diagnostics["provider_errors"].append({"subreddit": subreddit, "query": query, "error": str(exc)})
                rejected["provider_error"] += 1
                continue
            diagnostics["raw_result_count"] += len(posts)
            diagnostics["reddit_posts_seen_count"] += len(posts)
            for post in posts:
                result = post_to_source_result(post)
                score = int(result.metadata.get("score") or 0)
                if debug:
                    debug_items.append(
                        {
                            "subreddit": subreddit,
                            "query": query,
                            "title": result.title,
                            "source_url": result.source_url,
                            "source_post_date": result.metadata.get("source_post_date", ""),
                            "score": score,
                            "num_comments": result.metadata.get("num_comments", 0),
                        }
                    )
                if result.source_url in seen_urls:
                    rejected["duplicate_source_url"] += 1
                    continue
                seen_urls.add(result.source_url)
                if score < min_score:
                    rejected["reddit_score_below_min"] += 1
                    continue
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
                diagnostics["reddit_posts_matched_count"] += 1
                diagnostics["discussion_candidate_count"] += 1
                candidates.append(source_result_to_candidate(result, pack, context, query))
            time.sleep(0.2)

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
        diagnostics["debug"] = {"queries": debug_items}
    return candidates, rejected, diagnostics


def write_output(path: str | None, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Lead Scout against public Reddit subreddit posts.")
    parser.add_argument("--market", choices=("broward-fl", "northwest-ar"), required=True)
    parser.add_argument("--subreddit", action="append", help="Subreddit name without r/. Repeatable.")
    parser.add_argument("--query", action="append", help="Search query. Repeatable.")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-age-days", type=int, default=14)
    parser.add_argument("--min-score", type=int, default=0)
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

    credentials = load_reddit_credentials()
    if credentials is None:
        return 2
    subreddits = args.subreddit or list(DEFAULT_SUBREDDITS[args.market])
    queries = args.query or list(DEFAULT_QUERIES)
    client = RedditClient(*credentials)

    try:
        discovered, prefilter_reasons, discovery_diagnostics = discover_reddit(
            client,
            args.market,
            subreddits,
            queries,
            args.limit,
            args.max_age_days,
            args.min_score,
            args.debug,
        )
        kept, rejected, score_reasons, scoring_diagnostics = score_candidates(
            discovered,
            args.min_confidence,
            args.ai_score,
            DEFAULT_OPENAI_MODEL,
            args.ai_max_candidates,
        )
    except (OSError, ValueError, RedditApiError, json.JSONDecodeError) as exc:
        print(f"Reddit lead scout failed: {exc}", file=sys.stderr)
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
    report["reddit_posts_seen_count"] = discovery_diagnostics["reddit_posts_seen_count"]
    report["reddit_posts_matched_count"] = discovery_diagnostics["reddit_posts_matched_count"]
    report["dated_candidate_count"] = discovery_diagnostics["dated_candidate_count"]
    report["stale_rejected_count"] = discovery_diagnostics["stale_rejected_count"]
    report["unknown_date_rejected_count"] = discovery_diagnostics["unknown_date_rejected_count"]
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
