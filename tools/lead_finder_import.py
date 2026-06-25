#!/usr/bin/env python3
"""Import Lead Finder records from a local JSON file into /v1/ingest."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_INGEST_URL = "https://2v0q4zm2v6.execute-api.us-east-1.amazonaws.com/dev/v1/ingest"
CONTENT_FIELDS = ("title", "message", "description")
SUPPORTED_FIELDS = (
    "first_name",
    "last_name",
    "name",
    "email",
    "phone",
    "zip",
    "price",
    "beds",
    "baths",
    "notes",
    "status",
    "source",
    "source_url",
    "intent",
    "message",
    "description",
    "title",
    "city",
    "state",
    "role",
)


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("input file must contain a JSON array")

    records: list[dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"record {index} must be a JSON object")
        records.append(item)
    return records


def validate_record(record: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not clean_str(record.get("source")):
        errors.append("source is required")

    if not any(clean_str(record.get(field)) for field in CONTENT_FIELDS):
        errors.append("at least one of title, message, or description is required")

    if not clean_str(record.get("source_url")):
        warnings.append("source_url missing")

    payload = {field: record[field] for field in SUPPORTED_FIELDS if field in record}
    if not clean_str(payload.get("zip")):
        payload["zip"] = "00000"
        warnings.append("zip missing; defaulting to 00000")

    if errors:
        return None, errors, warnings

    return payload, errors, warnings


def post_record(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.read().decode("utf-8")


def print_messages(index: int, messages: list[str], prefix: str) -> None:
    for message in messages:
        print(f"[{index}] {prefix}: {message}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate local Lead Finder JSON records and POST valid rows to /v1/ingest."
    )
    parser.add_argument("file", help="Path to a JSON file containing an array of lead records.")
    parser.add_argument("--url", default=DEFAULT_INGEST_URL, help="Target /v1/ingest URL.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print results without POSTing.")
    args = parser.parse_args()

    try:
        records = load_records(Path(args.file))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1

    failures = 0
    for index, record in enumerate(records, start=1):
        payload, errors, warnings = validate_record(record, index)
        print_messages(index, warnings, "warning")

        if errors:
            failures += 1
            print_messages(index, errors, "invalid")
            print(f"[{index}] failure")
            continue

        if args.dry_run:
            print(f"[{index}] success dry-run: {json.dumps(payload, sort_keys=True)}")
            continue

        try:
            status, response_body = post_record(args.url, payload or {})
            print(f"[{index}] success POST {status}: {response_body}")
        except urllib.error.HTTPError as exc:
            failures += 1
            body = exc.read().decode("utf-8", errors="replace")
            print(f"[{index}] failure HTTP {exc.code}: {body}")
        except urllib.error.URLError as exc:
            failures += 1
            print(f"[{index}] failure: {exc}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
