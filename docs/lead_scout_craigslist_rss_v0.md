# Craigslist RSS Lead Scout Adapter v0

This local adapter reads public Craigslist RSS feed URLs, converts dated feed items into Discovery Inbox-compatible candidate objects, and runs the existing Lead Scout scoring, filtering, and recency checks.

It does not add backend routes, AWS resources, browser automation, or automatic imports.

## Setup

Create a local text file with one approved public Craigslist RSS URL per line. You can copy the RSS URL from a Craigslist search page by adding `format=rss` to the public search URL.

Example URL shapes:

```text
https://miami.craigslist.org/search/apa?format=rss&query=rent
https://fayar.craigslist.org/search/hhh?format=rss&query=wanted
```

Use market-appropriate feeds. Broward often appears under the Miami Craigslist region; Northwest Arkansas often appears under the Fayetteville Craigslist region.

## Dry Run

Dry-run is the default. Nothing imports unless both `--import-url` and `--token` are passed.

```powershell
python tools\lead_scout_craigslist_rss.py --market northwest-ar --feed-url "https://fayar.craigslist.org/search/hhh?format=rss&query=wanted" --show-rejected --debug
```

Seed-file example after adding approved public RSS URLs to your local seed file:

```powershell
python tools\lead_scout_craigslist_rss.py --market broward-fl --seed-file C:\buyerboard-api\broward-craigslist-rss-feeds.txt --show-rejected --debug
```

## Import Warning

Only import after reviewing dry-run output. The adapter rejects stale posts by default with `--max-age-days 14`, then applies existing Lead Scout prefilters and scoring. Pass both `--import-url` and a valid agent Bearer token only when the kept candidates have been reviewed.

## Limitations

- Craigslist RSS quality depends on the feed URL and search terms.
- Marketplace posts can still be supply/listing content, so scoring and human review remain required.
- This adapter is Craigslist RSS only. It does not build Reddit, Facebook, Nextdoor, Firecrawl, or Apify support.
- It uses public RSS feeds only and should not be used for private or logged-in pages.
