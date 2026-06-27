#!/usr/bin/env python3
"""Prepare manually found public leads for Discovery Inbox candidate import."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


CANDIDATE_FIELDS = (
    "title",
    "original_text",
    "summary",
    "source",
    "source_url",
    "source_post_date",
    "vertical",
    "market",
    "market_slug",
    "city",
    "state",
    "zip",
    "lead_type",
    "intent",
    "urgency",
    "contact_method",
)
STRIPPED_REVIEW_FIELDS = ("review_status", "published", "reviewed_at", "reviewed_by")


def warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def load_json_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
        items = payload["items"]
    elif isinstance(payload, dict):
        items = [payload]
    else:
        raise ValueError("JSON input must be one object, an array, or an object with items")
    return require_objects(items)


def load_csv_file(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV input must include a header row")
        return [dict(row) for row in reader]


def prompt_lead() -> list[dict[str, Any]]:
    print("Paste one manually reviewed public lead. Leave optional fields blank.", file=sys.stderr)
    item: dict[str, str] = {}
    for field in CANDIDATE_FIELDS:
        value = input(f"{field}: ").strip()
        if value:
            item[field] = value
    return [item]


def require_objects(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"lead {index} must be an object")
        out.append(item)
    return out


def normalize_lead(raw: dict[str, Any], index: int) -> dict[str, str]:
    candidate: dict[str, str] = {}
    for field in CANDIDATE_FIELDS:
        value = clean_text(raw.get(field))
        if value:
            candidate[field] = value

    if not candidate.get("source"):
        candidate["source"] = "manual"
    if not candidate.get("vertical"):
        candidate["vertical"] = "real_estate"

    if not candidate.get("source_url"):
        warn(f"lead {index}: source_url missing")
    if not candidate.get("original_text") and not candidate.get("summary"):
        raise ValueError(f"lead {index}: original_text or summary is required")

    stripped = [field for field in STRIPPED_REVIEW_FIELDS if clean_text(raw.get(field))]
    if stripped:
        warn(f"lead {index}: ignored review-only field(s): {', '.join(stripped)}")

    return candidate


def normalize_leads(raw_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [normalize_lead(item, index) for index, item in enumerate(raw_items, start=1)]


def post_candidates(url: str, token: str, candidates: list[dict[str, str]]) -> dict[str, Any]:
    body = json.dumps({"items": candidates}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8")
    payload = json.loads(response_body)
    if not isinstance(payload, dict):
        raise ValueError("import endpoint returned a non-object response")
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare manually found public leads for candidate review.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--json-file", help="Path to a JSON object, JSON array, or {\"items\": [...]} file.")
    inputs.add_argument("--csv-file", help="Path to a CSV file with headers.")
    inputs.add_argument("--interactive", action="store_true", help="Prompt for one pasted lead.")
    parser.add_argument("--import-url", help="Target /v1/candidates/import URL.")
    parser.add_argument("--token", help="Bearer token from /v1/agents/login.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.json_file:
            raw_items = load_json_file(Path(args.json_file))
        elif args.csv_file:
            raw_items = load_csv_file(Path(args.csv_file))
        else:
            raw_items = prompt_lead()
        candidates = normalize_leads(raw_items)
    except (OSError, csv.Error, json.JSONDecodeError, ValueError) as exc:
        print(f"manual intake failed: {exc}", file=sys.stderr)
        return 1

    if bool(args.import_url) != bool(args.token):
        print(json.dumps(candidates, indent=2, sort_keys=True))
        print("Import skipped: pass both --import-url and --token to import.", file=sys.stderr)
        return 1
    if not args.import_url or not args.token:
        print(json.dumps(candidates, indent=2, sort_keys=True))
        return 0

    try:
        result = post_candidates(args.import_url, args.token, candidates)
    except urllib.error.HTTPError as exc:
        print(f"Import failed with HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({"candidate_count": len(candidates), "import_result": result}, indent=2, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
