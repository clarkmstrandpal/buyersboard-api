#!/usr/bin/env python3
"""Lead Scout Core v1: find public Discovery Inbox candidate leads."""

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
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


MARKET_PACKS_PATH = Path(__file__).with_name("market_packs.json")
DEFAULT_MIN_CONFIDENCE = 0.65
DEFAULT_OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

SEARCH_PROVIDER_DOMAINS = ("duckduckgo.com", "bing.com", "google.com")
PRIVATE_OR_NOISY_DOMAINS = ("facebook.com", "instagram.com", "linkedin.com", "nextdoor.com", "x.com", "twitter.com")
DIRECTORY_DOMAINS = (
    "zillow.com",
    "realtor.com",
    "redfin.com",
    "homes.com",
    "yelp.com",
    "yellowpages.com",
    "trulia.com",
    "apartments.com",
    "rent.com",
    "hotpads.com",
)
DIRECTORY_TERMS = ("real estate agent", "realtor profile", "agent directory", "top agents", "find an agent", "business directory")
SEO_OR_PROGRAM_TERMS = (
    "homebuyer program",
    "first time home buyer program",
    "down payment assistance",
    "grant",
    "mortgage guide",
    "seo",
    "blog",
    "guide to",
    "how to buy",
    "listings",
    "homes for sale",
    "apartments for rent",
)

VERTICALS: dict[str, dict[str, Any]] = {
    "real_estate": {
        "query_templates": (
            '"{city}" "looking for a house"',
            '"{city}" "need a rental"',
            '"{city}" "private landlord"',
            '"{city}" "rent to own"',
            '"{city}" "owner finance"',
            '"{city}" "moving to" "house"',
            '"{city}" "does anyone know" "rental"',
            '"{city}" "ISO" "house"',
        ),
        "lead_terms": {
            "buy": ("looking for a house", "looking for home", "buy a house", "house hunting", "iso house"),
            "rent": ("need a rental", "looking for rental", "iso rental", "rental house", "rent a house"),
            "private_landlord": ("private landlord", "landlord", "no property management"),
            "rent_to_own": ("rent to own", "lease option"),
            "owner_finance": ("owner finance", "owner financing"),
            "moving": ("moving to", "relocating to"),
            "sell": ("need to sell", "selling my house", "sell my house", "inherited property"),
        },
    }
}


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


def render_queries(pack: dict[str, Any], vertical: str, per_market: int) -> list[dict[str, str]]:
    config = VERTICALS[vertical]
    queries: list[dict[str, str]] = []
    cities = pack.get("cities") or [""]
    counties = pack.get("counties") or [""]
    for city in cities:
        county = counties[0] if counties else ""
        for template in config["query_templates"]:
            query = template.format(
                market=pack.get("market", ""),
                market_slug=pack.get("market_slug", ""),
                state=pack.get("state", ""),
                county=county,
                city=city,
            )
            query = " ".join(query.split())
            if query:
                queries.append({"query": query, "city": city, "county": county})
            if len(queries) >= per_market:
                return queries
    return queries


def public_search(query: str, limit: int) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(
        f"https://lite.duckduckgo.com/lite/?{params}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; ListlyLeadScout/1.0; public-search-only)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
    parser = DuckDuckGoParser()
    parser.feed(body)
    parser.close()
    return parser.results[:limit]


def host_matches(url: str, domains: tuple[str, ...]) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in terms)


def prefilter(result: dict[str, str], pack: dict[str, Any], city: str, county: str) -> str | None:
    url = result.get("source_url", "")
    title = result.get("title", "").strip()
    snippet = result.get("snippet", "").strip()
    text = f"{title} {snippet} {url}".lower()
    if not url:
        return "missing_source_url"
    if title.lower() == "more info":
        return "search_provider_noise"
    if host_matches(url, SEARCH_PROVIDER_DOMAINS):
        return "search_provider_noise"
    if host_matches(url, PRIVATE_OR_NOISY_DOMAINS):
        return "private_or_login_site"
    if host_matches(url, DIRECTORY_DOMAINS) or contains_any(text, DIRECTORY_TERMS):
        return "directory_or_listing"
    if contains_any(text, SEO_OR_PROGRAM_TERMS):
        return "seo_or_program_page"
    if not geography_matches(text, pack, city, county):
        return "wrong_geography"
    return None


def geography_matches(text: str, pack: dict[str, Any], city: str, county: str) -> bool:
    lowered = text.lower()
    state = str(pack.get("state", "")).lower()
    market = str(pack.get("market", "")).lower()
    city_match = bool(city and city.lower() in lowered)
    county_match = bool(county and county.lower() in lowered and "county" in lowered)
    market_match = bool(market and market in lowered)
    state_match = bool(state and f" {state} " in f" {lowered} ")
    return city_match or county_match or market_match or state_match


def infer_intent_and_role(text: str, vertical: str) -> tuple[str, str]:
    lowered = text.lower()
    for intent, terms in VERTICALS[vertical]["lead_terms"].items():
        if any(term in lowered for term in terms):
            if intent == "rent":
                return intent, "renter"
            if intent == "private_landlord":
                return intent, "landlord"
            if intent == "sell":
                return intent, "seller"
            return intent, "buyer"
    return "unknown", "unknown"


def normalize_result(result: dict[str, str], pack: dict[str, Any], vertical: str, query: str, city: str, county: str) -> dict[str, Any]:
    title = result.get("title", "").strip()
    snippet = result.get("snippet", "").strip()
    intent, role = infer_intent_and_role(f"{title} {snippet}", vertical)
    candidate: dict[str, Any] = {
        "title": title,
        "snippet": snippet,
        "message": snippet or title,
        "source": "public_search",
        "source_url": result.get("source_url"),
        "market": pack.get("market"),
        "market_slug": pack.get("market_slug"),
        "county": county,
        "city": city,
        "state": pack.get("state"),
        "vertical": vertical,
        "role_guess": role,
        "intent_guess": intent,
        "intent_score": 0.0,
        "search_query": query,
        "contact_method": "source_url",
    }
    return {key: value for key, value in candidate.items() if value not in (None, "")}


def rule_score(candidate: dict[str, Any], min_confidence: float) -> dict[str, Any]:
    text = f"{candidate.get('title', '')} {candidate.get('snippet', '')}".lower()
    vertical = str(candidate.get("vertical", "real_estate"))
    intent, role = infer_intent_and_role(text, vertical)
    matched_terms = [term for terms in VERTICALS[vertical]["lead_terms"].values() for term in terms if term in text]
    directory_or_ad = contains_any(text, DIRECTORY_TERMS + SEO_OR_PROGRAM_TERMS)
    confidence = 0.35
    if matched_terms:
        confidence += 0.35
    if any(term in text for term in ("anyone know", "iso", "need", "looking for")):
        confidence += 0.15
    if candidate.get("city") and str(candidate["city"]).lower() in text:
        confidence += 0.1
    confidence = min(confidence, 0.95)
    reject_reason = ""
    if not matched_terms:
        reject_reason = "low_intent"
    elif directory_or_ad:
        reject_reason = "directory_or_listing"
    elif confidence < min_confidence:
        reject_reason = "low_confidence"

    return {
        "is_lead": bool(matched_terms) and confidence >= min_confidence and not directory_or_ad,
        "confidence": confidence,
        "vertical": vertical,
        "intent": intent,
        "role_guess": role,
        "location_match": True,
        "is_directory_or_ad": directory_or_ad,
        "reject_reason": reject_reason,
        "cleaned_title": candidate.get("title", ""),
        "cleaned_message": candidate.get("message") or candidate.get("snippet", ""),
        "scorer": "rules",
    }


def ai_score(candidate: dict[str, Any], api_key: str, model: str) -> dict[str, Any]:
    payload = {
        "vertical": candidate.get("vertical"),
        "title": candidate.get("title"),
        "snippet": candidate.get("snippet"),
        "source_url": candidate.get("source_url"),
        "market": candidate.get("market"),
        "city": candidate.get("city"),
        "county": candidate.get("county"),
        "state": candidate.get("state"),
        "search_query": candidate.get("search_query"),
    }
    prompt = (
        "Score whether this public search result is a real local lead for the requested vertical. "
        "Reject directories, ads, SEO content, public programs, generic listings, and wrong locations. "
        "Return only strict JSON with keys: is_lead, confidence, vertical, intent, role_guess, "
        "location_match, is_directory_or_ad, reject_reason, cleaned_title, cleaned_message.\n\n"
        f"Candidate:\n{json.dumps(payload, sort_keys=True)}"
    )
    body = json.dumps(
        {
            "model": model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "You are a strict lead-quality scorer. Return JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["choices"][0]["message"]["content"]
    score = json.loads(content)
    if not isinstance(score, dict):
        raise ValueError("AI scorer returned non-object JSON")
    score["scorer"] = "ai"
    return score


def normalize_score(score: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "is_lead": bool(score.get("is_lead")),
        "confidence": float(score.get("confidence") or 0.0),
        "vertical": str(score.get("vertical") or candidate.get("vertical") or "real_estate"),
        "intent": str(score.get("intent") or candidate.get("intent_guess") or "unknown"),
        "role_guess": str(score.get("role_guess") or candidate.get("role_guess") or "unknown"),
        "location_match": bool(score.get("location_match")),
        "is_directory_or_ad": bool(score.get("is_directory_or_ad")),
        "reject_reason": str(score.get("reject_reason") or ""),
        "cleaned_title": str(score.get("cleaned_title") or candidate.get("title") or ""),
        "cleaned_message": str(score.get("cleaned_message") or candidate.get("message") or candidate.get("snippet") or ""),
        "scorer": str(score.get("scorer") or "unknown"),
    }


def keep_score(score: dict[str, Any], min_confidence: float) -> tuple[bool, str]:
    if score["is_directory_or_ad"]:
        return False, score["reject_reason"] or "directory_or_listing"
    if not score["location_match"]:
        return False, score["reject_reason"] or "wrong_geography"
    if not score["is_lead"]:
        return False, score["reject_reason"] or "not_a_lead"
    if score["confidence"] < min_confidence:
        return False, score["reject_reason"] or "low_confidence"
    return True, ""


def raw_example(result: dict[str, str]) -> dict[str, str]:
    return {"title": result.get("title", ""), "source_url": result.get("source_url", "")}


def discover(
    markets: list[str],
    vertical: str,
    per_market: int,
    per_query: int,
    debug: bool,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Any]]:
    packs = load_market_packs()
    candidates: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen_urls: set[str] = set()
    diagnostics: dict[str, Any] = {
        "raw_result_count": 0,
        "candidate_after_dedupe_count": 0,
        "provider_error_count": 0,
        "provider_errors": [],
    }
    debug_queries: list[dict[str, Any]] = []

    for market_slug in markets:
        pack = packs.get(market_slug)
        if not pack:
            raise ValueError(f"unknown market: {market_slug}")
        for query_info in render_queries(pack, vertical, per_market):
            query = query_info["query"]
            city = query_info["city"]
            county = query_info["county"]
            try:
                results = public_search(query, per_query)
            except urllib.error.URLError as exc:
                error = {"market": market_slug, "query": query, "error": str(exc)}
                diagnostics["provider_error_count"] += 1
                diagnostics["provider_errors"].append(error)
                rejected["provider_error"] += 1
                if debug:
                    debug_queries.append(
                        {
                            "market": market_slug,
                            "query": query,
                            "raw_result_count": 0,
                            "raw_examples": [],
                            "provider_error": error["error"],
                        }
                    )
                continue
            diagnostics["raw_result_count"] += len(results)
            if debug:
                debug_queries.append(
                    {
                        "market": market_slug,
                        "query": query,
                        "raw_result_count": len(results),
                        "raw_examples": [raw_example(result) for result in results[:5]],
                    }
                )
            for result in results:
                url = result.get("source_url", "")
                if url in seen_urls:
                    rejected["duplicate_source_url"] += 1
                    continue
                seen_urls.add(url)
                diagnostics["candidate_after_dedupe_count"] += 1
                reason = prefilter(result, pack, city, county)
                if reason:
                    rejected[reason] += 1
                    continue
                candidates.append(normalize_result(result, pack, vertical, query, city, county))
            time.sleep(0.5)

    diagnostics["prefilter_rejected_count"] = sum(rejected.values()) - rejected.get("provider_error", 0) - rejected.get("duplicate_source_url", 0)
    if debug:
        diagnostics["debug"] = {"queries": debug_queries}
    return candidates, rejected, diagnostics


def score_candidates(
    candidates: list[dict[str, Any]],
    min_confidence: float,
    ai_enabled: bool,
    model: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    api_key = os.environ.get("OPENAI_API_KEY")
    use_ai = ai_enabled and bool(api_key)
    diagnostics = {
        "ai_requested": ai_enabled,
        "openai_api_key_detected": bool(api_key),
        "ai_enabled": use_ai,
        "ai_scored_count": 0,
    }
    if ai_enabled and not api_key:
        print("AI scoring requested but OPENAI_API_KEY is not set; using rule-based scoring.", file=sys.stderr)

    for candidate in candidates:
        try:
            if use_ai and api_key:
                raw_score = ai_score(candidate, api_key, model)
                diagnostics["ai_scored_count"] += 1
            else:
                raw_score = rule_score(candidate, min_confidence)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError) as exc:
            print(f"AI score failed for {candidate.get('source_url')}: {exc}; using rule-based scoring.", file=sys.stderr)
            raw_score = rule_score(candidate, min_confidence)
        score = normalize_score(raw_score, candidate)
        is_kept, reason = keep_score(score, min_confidence)
        scored_candidate = candidate | {
            "title": score["cleaned_title"],
            "message": score["cleaned_message"],
            "intent_guess": score["intent"],
            "role_guess": score["role_guess"],
            "intent_score": score["confidence"],
            "lead_scout_score": score,
        }
        if is_kept:
            kept.append(scored_candidate)
        else:
            reason = reason or "not_a_lead"
            reasons[reason] += 1
            rejected.append(scored_candidate | {"reject_reason": reason})
    return kept, rejected, reasons, diagnostics


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


def build_report(
    kept: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    prefilter_reasons: Counter[str],
    score_reasons: Counter[str],
    discovery_diagnostics: dict[str, Any],
    scoring_diagnostics: dict[str, Any],
    show_rejected: bool,
    debug: bool,
) -> dict[str, Any]:
    rejection_reasons = prefilter_reasons + score_reasons
    report: dict[str, Any] = {
        "raw_result_count": discovery_diagnostics["raw_result_count"],
        "candidate_after_dedupe_count": discovery_diagnostics["candidate_after_dedupe_count"],
        "prefilter_rejected_count": discovery_diagnostics["prefilter_rejected_count"],
        "ai_scored_count": scoring_diagnostics["ai_scored_count"],
        "kept_count": len(kept),
        "rejected_count": len(rejected) + sum(prefilter_reasons.values()),
        "provider_error_count": discovery_diagnostics["provider_error_count"],
        "rejection_reasons": dict(rejection_reasons.most_common()),
        "provider_errors": discovery_diagnostics["provider_errors"],
        "kept_candidates": kept,
    }
    if debug:
        report["debug"] = {
            "ai_scoring_requested": scoring_diagnostics["ai_requested"],
            "ai_scoring_enabled": scoring_diagnostics["ai_enabled"],
            "openai_api_key_detected": scoring_diagnostics["openai_api_key_detected"],
            "search_queries": discovery_diagnostics.get("debug", {}).get("queries", []),
        }
    if show_rejected:
        report["rejected_examples"] = rejected[:10]
    return report


def write_output(path: str | None, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Lead Scout Core v1 public-source candidate discovery.")
    parser.add_argument("--vertical", choices=tuple(VERTICALS), default="real_estate", help="Lead vertical to scout.")
    parser.add_argument("--market", action="append", choices=("broward-fl", "northwest-ar"), help="Market slug. Repeat to search multiple markets.")
    parser.add_argument("--all-markets", action="store_true", help="Search all configured markets.")
    parser.add_argument("--queries-per-market", type=int, default=4, help="Maximum rendered queries per market.")
    parser.add_argument("--results-per-query", type=int, default=5, help="Maximum search results to review per query.")
    parser.add_argument("--ai-score", action="store_true", help="Use OPENAI_API_KEY for AI lead scoring when available.")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE, help="Minimum score required to keep a candidate.")
    parser.add_argument("--show-rejected", action="store_true", help="Include rejected scored examples in dry-run output.")
    parser.add_argument("--debug", action="store_true", help="Include query-level search and scoring diagnostics in dry-run output.")
    parser.add_argument("--output", help="Write dry-run report JSON to this file instead of stdout.")
    parser.add_argument("--dry-run", action="store_true", help="Find, score, and print candidates without importing.")
    parser.add_argument("--import-url", help="Target /v1/candidates/import URL. Required with --token to import.")
    parser.add_argument("--token", default=os.environ.get("CANDIDATE_IMPORT_TOKEN"), help="Bearer token from /v1/agents/login.")
    parser.add_argument("--model", default=DEFAULT_OPENAI_MODEL, help="OpenAI model for --ai-score.")
    args = parser.parse_args()

    markets = ["broward-fl", "northwest-ar"] if args.all_markets else args.market
    if not markets:
        parser.error("use --market or --all-markets")

    try:
        discovered, prefilter_reasons, discovery_diagnostics = discover(
            markets,
            args.vertical,
            args.queries_per_market,
            args.results_per_query,
            args.debug,
        )
        kept, rejected, score_reasons, scoring_diagnostics = score_candidates(discovered, args.min_confidence, args.ai_score, args.model)
    except (OSError, ValueError) as exc:
        print(f"Lead scout failed: {exc}", file=sys.stderr)
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
    write_output(args.output, report)

    if args.dry_run:
        return 0
    if not args.import_url or not args.token:
        print("Import skipped: pass both --import-url and --token to import kept candidates.", file=sys.stderr)
        return 0
    if not kept:
        print("Import skipped: no kept candidates found.", file=sys.stderr)
        return 0

    try:
        result = import_candidates(args.import_url, args.token, kept)
    except urllib.error.HTTPError as exc:
        print(f"Import failed with HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
