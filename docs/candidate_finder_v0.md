# Candidate Finder v0

Candidate Finder is a local, public-search-only discovery helper for the ListlyHomes Discovery Inbox. It uses `tools/market_packs.json` query templates, searches public web result pages, normalizes results into candidate lead JSON, deduplicates by `source_url`, and can import the results into the authenticated `/v1/candidates/import` endpoint.

It does not add a backend route, does not change AWS/SAM resources, and does not scrape private or logged-in sites.

## Markets

Supported market slugs come from `tools/market_packs.json`:

- `broward-fl`
- `northwest-ar`

## Dry Run

Search one market and print normalized candidates:

```bash
python3 tools/candidate_finder.py --market broward-fl --dry-run
```

Search both markets and write a JSON file:

```bash
python3 tools/candidate_finder.py --all-markets --dry-run --output samples/real_candidates.sample.json
```

## Import

Candidate import requires the same agent Bearer token used by Discovery Inbox candidate routes:

```bash
python3 tools/candidate_finder.py --market northwest-ar --token YOUR_AGENT_TOKEN --import-url https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import
```

You can also set the token once:

```bash
$env:CANDIDATE_IMPORT_TOKEN = "YOUR_AGENT_TOKEN"
python3 tools/candidate_finder.py --market broward-fl --import-url https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import
```

## Output Shape

Each result is normalized to fields accepted by `tools/candidate_import.py` and `/v1/candidates/import`, including:

- `title`
- `snippet`
- `message`
- `source`
- `source_url`
- `market`
- `market_slug`
- `county`
- `city`
- `state`
- `role_guess`
- `intent_guess`
- `intent_score`
- `search_query`
- `contact_method`

`source_url` is used for local dedupe before import. The backend import route also dedupes by `source_url`.

## Notes

Candidate Finder only uses public search result pages and skips common private/logged-in social domains. Search results should still be reviewed in Discovery Inbox before promotion to normal leads.
