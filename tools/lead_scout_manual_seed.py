#!/usr/bin/env python3
"""Run Lead Scout scoring against manually approved public URL seeds."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
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
from lead_scout_sources import ManualPublicUrlSeedAdapter, SourceContext, SourceResult


DEFAULT_IMPORT_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import"


def source_result_to_candidate(result: SourceResult, pack: dict[str, Any], context: SourceContext) -> dict[str, Any]:
    intent, role = infer_intent_and_role(f"{result.title} {result.snippet}", context.vertical)
    candidate: dict[str, Any] = {
        "title": result.title,
        "snippet": result.snippet,
        "message": result.snippet or result.title,
        "source": result.source,
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
        "search_query": "manual_public_url_seed",
        "contact_method": "source_url",
        "source_adapter": result.provider,
        "source_strategy": "manual_seed",
        "source_category": "discussion",
    }
    if result.metadata:
        candidate["source_metadata"] = result.metadata
    return {key: value for key, value in candidate.items() if value not in (None, "")}


def discover_manual_seed(
    seed_file: Path,
    markets: list[str],
    vertical: str,
    fetch_pages: bool,
    debug: bool,
) -> tuple[list[dict[str, Any]], Counter[str], dict[str, Any]]:
    packs = load_market_packs()
    adapter = ManualPublicUrlSeedAdapter(seed_file, fetch_pages=fetch_pages)
    candidates: list[dict[str, Any]] = []
    rejected: Counter[str] = Counter()
    seen_urls: set[str] = set()
    diagnostics: dict[str, Any] = {
        "raw_result_count": 0,
        "candidate_after_dedupe_count": 0,
        "provider_error_count": 0,
        "provider_errors": [],
        "cities_used": {},
        "generated_query_count": 0,
        "executed_query_count": 0,
        "domain_denied_count": 0,
        "discussion_candidate_count": 0,
        "marketplace_candidate_count": 0,
    }
    debug_items: list[dict[str, Any]] = []

    for market_slug in markets:
        pack = packs.get(market_slug)
        if not pack:
            raise ValueError(f"unknown market: {market_slug}")
        city = (pack.get("cities") or [""])[0]
        county = (pack.get("counties") or [""])[0]
        context = SourceContext(
            vertical=vertical,
            market=str(pack.get("market", "")),
            market_slug=market_slug,
            city=city,
            county=county,
            state=str(pack.get("state", "")),
        )
        diagnostics["cities_used"][market_slug] = [city] if city else []
        diagnostics["generated_query_count"] += 1
        diagnostics["executed_query_count"] += 1

        for result in adapter.discover(context):
            diagnostics["raw_result_count"] += 1
            if debug:
                debug_items.append(
                    {
                        "source_adapter": adapter.name,
                        "market": market_slug,
                        "title": result.title,
                        "source_url": result.source_url,
                        "fetch_error": result.metadata.get("fetch_error", ""),
                    }
                )
            if result.source_url in seen_urls:
                rejected["duplicate_source_url"] += 1
                continue
            seen_urls.add(result.source_url)
            diagnostics["candidate_after_dedupe_count"] += 1
            if domain_denied(result.source_url):
                diagnostics["domain_denied_count"] += 1
                rejected["domain_denied"] += 1
                continue
            raw_result = {"title": result.title, "snippet": result.snippet, "source_url": result.source_url}
            reason = prefilter(raw_result, pack, context.city, context.county)
            if reason:
                rejected[reason] += 1
                continue
            diagnostics["discussion_candidate_count"] += 1
            candidates.append(source_result_to_candidate(result, pack, context))

    diagnostics["prefilter_rejected_count"] = (
        sum(rejected.values())
        - rejected.get("provider_error", 0)
        - rejected.get("duplicate_source_url", 0)
        - rejected.get("domain_denied", 0)
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
    parser = argparse.ArgumentParser(description="Run Lead Scout against approved public URL seeds.")
    parser.add_argument("seed_file", help="Text or JSON file of manually approved public URLs.")
    parser.add_argument("--vertical", choices=("real_estate",), default="real_estate")
    parser.add_argument("--market", action="append", choices=("broward-fl", "northwest-ar"), help="Market slug. Repeat to scan multiple markets.")
    parser.add_argument("--all-markets", action="store_true", help="Run against all configured markets.")
    parser.add_argument("--no-fetch-pages", action="store_true", help="Use seed-provided URL/title/snippet values only.")
    parser.add_argument("--ai-score", action="store_true", help="Use OPENAI_API_KEY for AI lead scoring when available.")
    parser.add_argument("--ai-max-candidates", type=int, help="Maximum surviving candidates to send to AI before falling back to rules.")
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--show-rejected", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", help="Write dry-run report JSON to this file instead of stdout.")
    parser.add_argument("--import-url", default=DEFAULT_IMPORT_URL, help="Target /v1/candidates/import URL.")
    parser.add_argument("--token", default=os.environ.get("CANDIDATE_IMPORT_TOKEN"), help="Bearer token from /v1/agents/login.")
    args = parser.parse_args()

    markets = ["broward-fl", "northwest-ar"] if args.all_markets else args.market
    if not markets:
        parser.error("use --market or --all-markets")

    try:
        discovered, prefilter_reasons, discovery_diagnostics = discover_manual_seed(
            Path(args.seed_file),
            markets,
            args.vertical,
            not args.no_fetch_pages,
            args.debug,
        )
        kept, rejected, score_reasons, scoring_diagnostics = score_candidates(
            discovered,
            args.min_confidence,
            args.ai_score,
            DEFAULT_OPENAI_MODEL,
            args.ai_max_candidates,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Manual seed scout failed: {exc}", file=sys.stderr)
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

    if not args.token:
        print("Import skipped: pass --token or CANDIDATE_IMPORT_TOKEN to import kept candidates.", file=sys.stderr)
        return 0
    if not kept:
        print("Import skipped: no kept candidates found.", file=sys.stderr)
        return 0

    try:
        result = import_candidates(args.import_url, args.token, kept)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
