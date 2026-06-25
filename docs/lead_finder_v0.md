# Lead Finder v0

Lead Finder v0 lets the backend store lead-shaped public or scraped posts in the existing leads table so product quality can be evaluated before dashboard polish.

## Fields

`POST /v1/ingest` still accepts form lead fields such as `first_name`, `last_name`, `email`, `phone`, `zip`, `price`, `beds`, `baths`, and `notes`.

For scraped/public posts, it also accepts:

- `title`
- `message`
- `description`
- `source`
- `source_url`
- `intent`
- `city`
- `state`
- `role`

If `email` is missing, ingest stores a harmless placeholder address under `placeholder.listlyhomes.local`. If `zip` is missing, ingest stores `00000` for now.

## Seed sample leads locally

The seed helper uses only the Python standard library and does not require paid APIs or secrets.

Print five sample payloads:

```bash
python3 tools/lead_finder_seed.py
```

POST them to a deployed ingest endpoint:

```bash
python3 tools/lead_finder_seed.py --url https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/ingest
```

## Verify list output

After posting seed data, call the list endpoint and confirm the Lead Finder fields are present:

```bash
curl "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev/v1/leads/list?zip_prefix=000&limit=10"
```

The `/v1/leads/list` response includes fields such as `source`, `source_url`, `intent`, `message`, `description`, `notes`, `title`, `city`, `state`, `role`, `first_name`, `last_name`, `phone`, and `created_at` when present on the stored lead.
