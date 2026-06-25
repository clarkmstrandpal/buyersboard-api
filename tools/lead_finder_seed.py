#!/usr/bin/env python3
"""Print or POST five Lead Finder v0 sample payloads.

No paid APIs, credentials, or secrets are required. By default this script prints
JSON payloads that can be copied into /v1/ingest. Pass --url to POST them to a
local or deployed ingest endpoint.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

SAMPLE_LEADS: list[dict[str, Any]] = [
    {
        "source": "reddit",
        "source_url": "https://example.com/r/homebuying/sample-1",
        "intent": "buy",
        "title": "Looking for a starter home near Coral Springs",
        "message": "First-time buyer hoping to find a 3 bed home near good schools.",
        "city": "Coral Springs",
        "state": "FL",
        "role": "buyer",
        "notes": "Public post sample for Lead Finder v0.",
    },
    {
        "source": "craigslist",
        "source_url": "https://example.com/craigslist/sample-2",
        "intent": "rent-to-own",
        "title": "Family needs rent-to-own option in Broward",
        "description": "Relocating soon and comparing rent-to-own homes under $450k.",
        "city": "Pompano Beach",
        "state": "FL",
        "role": "buyer",
    },
    {
        "source": "forum",
        "source_url": "https://example.com/forum/sample-3",
        "intent": "sell",
        "title": "Considering selling inherited condo",
        "message": "Trying to understand value before listing an inherited condo.",
        "city": "Fort Lauderdale",
        "state": "FL",
        "role": "seller",
        "phone": "555-0103",
    },
    {
        "source": "x",
        "source_url": "https://example.com/x/sample-4",
        "intent": "buy",
        "title": "Need advice on townhomes near commute routes",
        "message": "Comparing townhomes with shorter commute and flexible closing timeline.",
        "city": "Boca Raton",
        "state": "FL",
        "role": "buyer",
    },
    {
        "source": "public_web",
        "source_url": "https://example.com/public-web/sample-5",
        "intent": "invest",
        "title": "Investor looking for duplex leads",
        "description": "Interested in duplexes or small multifamily properties with renovation potential.",
        "city": "Deerfield Beach",
        "state": "FL",
        "role": "investor",
        "zip": "33441",
        "email": "investor.sample@example.com",
    },
]


def post_payload(url: str, payload: dict[str, Any]) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.status, response.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Print or POST Lead Finder v0 sample leads.")
    parser.add_argument("--url", help="Optional /v1/ingest URL to POST sample leads to.")
    args = parser.parse_args()

    if not args.url:
        print(json.dumps(SAMPLE_LEADS, indent=2))
        return 0

    for index, payload in enumerate(SAMPLE_LEADS, start=1):
        try:
            status, response_body = post_payload(args.url, payload)
            print(f"[{index}] POST {status}: {response_body}")
        except urllib.error.HTTPError as exc:
            print(f"[{index}] POST failed with HTTP {exc.code}: {exc.read().decode('utf-8')}", file=sys.stderr)
            return 1
        except urllib.error.URLError as exc:
            print(f"[{index}] POST failed: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
