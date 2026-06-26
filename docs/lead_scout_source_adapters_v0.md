# Lead Scout Source Adapters v0

Lead Scout source adapters are local-only discovery inputs for `tools/candidate_finder.py`. They are the next layer after Lead Scout Core v1: adapters should bring in reviewed public-source material, then the existing Lead Scout prefiltering and scoring path decides whether anything is worth importing.

This does not add backend APIs, public routes, AWS resources, or automatic imports.

## Manual Public URL Seed Adapter

The first adapter is `manual_public_urls`. It is for manually approved public URLs only. Do not use it for private pages, logged-in pages, scraped account data, or sources that require bypassing access controls.

Seed files can be plain text:

```text
https://www.example.com/
https://www.iana.org/domains/reserved
```

They can also be JSON:

```json
[
  {
    "url": "https://www.example.com/",
    "title": "Optional reviewed title",
    "snippet": "Optional reviewed snippet"
  }
]
```

When fetching is enabled, the adapter tries to read the public page title, description, and a short body excerpt. If fetching fails, the URL can still be represented with any seed-provided title/snippet. Results then pass through the same domain deny list, prefiltering, and Lead Scout scoring used by search discovery.

When possible, the adapter also extracts a `source_post_date` from visible page text. This currently handles common forum-style dates such as City-Data post timestamps, simple numeric dates, ISO dates, and long month-name dates. JSON seed entries may also provide `source_post_date` or `extracted_date` directly.

Old public pages are useful for testing extraction and classification, but they should not be treated as sellable leads. For real candidate runs, use `--max-age-days` and import only recent dated posts. By default, otherwise valid manual seed candidates with no discovered date are rejected with `unknown_source_date`; pass `--allow-unknown-date` only for testing or explicitly reviewed exceptions.

## Dry Run

Dry-run first:

```powershell
python tools/lead_scout_manual_seed.py samples/manual_public_urls.sample.txt --market broward-fl --show-rejected --debug
```

To avoid network page fetches and use only seed-provided values:

```powershell
python tools/lead_scout_manual_seed.py samples/manual_public_urls.sample.txt --market broward-fl --no-fetch-pages --show-rejected --debug
```

For real-lead screening, add a recency cutoff:

```powershell
python tools/lead_scout_manual_seed.py approved_urls.txt --market northwest-ar --max-age-days 30 --show-rejected --debug
```

Import remains explicit. The tool posts nothing unless both `--import-url` and `--token` are passed.

## Known Source Notes

City-Data and similar forum pages can be useful for validating extraction/classification, but stale threads should be rejected unless the visible post date is recent enough for the use case.

Reddit direct HTML may return verification/interstitial pages instead of discussion content. Those should remain rejected by the current manual seed path; Reddit needs a proper public source adapter later.

## Future Adapters

Do not add broad scraping by default. Source-specific adapters should target public demand/user-intent material:

- Reddit/public forum adapter.
- Marketplace/wanted-post adapter.
- Google Programmable Search/custom search adapter.
