# Discovery Inbox v0

Discovery Inbox stores raw candidate leads before they become normal agent leads. Candidate leads are for internal market validation and review. Normal leads remain the records served by the existing `/v1/ingest`, `/v1/leads/list`, auth, and claim workflow.

## Candidate Import Flow

Import candidate leads into the candidate table with:

```bash
python3 tools/candidate_import.py samples/broward_candidates.sample.json --dry-run
python3 tools/candidate_import.py samples/broward_candidates.sample.json
```

Use a different backend URL:

```bash
python3 tools/candidate_import.py samples/northwest_ar_candidates.sample.json --url https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/import
```

The API route is `POST /v1/candidates/import`. It accepts either a JSON array or `{ "items": [...] }`. Each imported item receives a `candidate_id`, `created_at`, `created_ts`, and default `status` of `new` when missing. If `source_url` already exists, the importer skips the duplicate and reports it in the summary.

## Review Flow

List candidates with:

```bash
curl "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/list?market_slug=broward-fl&limit=20"
curl "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/list?market_slug=northwest-ar&status=new"
```

Supported filters include `market_slug`, `market`, `county`, `city`, `zip`, `state`, `source`, `status`, `intent_guess`, and `role_guess`. The response includes `items` and `next_cursor`.

Mark a candidate after review:

```bash
curl -X POST "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/action" \
  -H "Content-Type: application/json" \
  -d '{"candidate_id":"CANDIDATE_ID","action":"good","review_notes":"Looks relevant"}'
```

Actions are `good`, `maybe`, `rejected`, `duplicate`, `archive`, `archived`, and `send_to_leads`.

## Promote To Leads Flow

Promote a reviewed candidate into the existing normal leads table:

```bash
curl -X POST "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/candidates/action" \
  -H "Content-Type: application/json" \
  -d '{"candidate_id":"CANDIDATE_ID","action":"send_to_leads","review_notes":"Promoted for agent workflow"}'
```

Promotion maps candidate fields into the normal lead shape: `title`, `message` or `snippet`, `source`, `source_url`, `zip`, `city`, `state`, `role_guess` as `role`, `intent_guess` as `intent`, and `contact_method` when present. Missing email uses the same placeholder pattern as `/v1/ingest`. The candidate is marked `sent` and stores `promoted_lead_id`.

## Market Packs

`tools/market_packs.json` defines the initial market inputs:

- `broward-fl` for Broward County, FL
- `northwest-ar` for Benton and Washington counties in Northwest Arkansas

These packs are local configuration for candidate discovery scripts and do not rename any existing AWS resources.
