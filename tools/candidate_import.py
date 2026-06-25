#!/usr/bin/env python3
"""Import Discovery Inbox candidate leads from a local JSON file."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import"


def load_items(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items")
    else:
        raise ValueError("file must contain a JSON array or an object with items")
    if not isinstance(items, list):
        raise ValueError("items must be a JSON array")
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item {index} must be an object")
    return items


def post_items(url: str, items: list[dict[str, Any]], token: str | None) -> dict[str, Any]:
    body = json.dumps({"items": items}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        response_body = response.read().decode("utf-8")
    data = json.loads(response_body)
    if not isinstance(data, dict):
        raise ValueError("import endpoint returned a non-object response")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Import candidate leads into the Discovery Inbox.")
    parser.add_argument("file", help="JSON file containing a candidate array or {\"items\": [...]}.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Target /v1/candidates/import URL.")
    parser.add_argument("--token", default=os.environ.get("CANDIDATE_IMPORT_TOKEN"), help="Bearer token from /v1/agents/login.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize without POSTing.")
    args = parser.parse_args()

    try:
        items = load_items(Path(args.file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"dry-run ok: {len(items)} candidate(s) loaded")
        return 0
    if not args.token:
        print("Import failed: --token or CANDIDATE_IMPORT_TOKEN is required", file=sys.stderr)
        return 1

    try:
        result = post_items(args.url, items, args.token)
    except urllib.error.HTTPError as exc:
        print(f"Import failed with HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    print(f"imported_count: {result.get('imported_count', 0)}")
    print(f"duplicate_count: {result.get('duplicate_count', 0)}")
    print(f"error_count: {result.get('error_count', 0)}")
    for item in result.get("items", []):
        print(json.dumps(item, sort_keys=True))
    return 0 if not result.get("error_count") else 1


if __name__ == "__main__":
    raise SystemExit(main())
