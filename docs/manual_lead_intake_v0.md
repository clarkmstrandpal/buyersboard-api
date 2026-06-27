# Manual Lead Intake v0

`tools/manual_lead_intake.py` is a local-only helper for turning manually reviewed public lead examples into Discovery Inbox candidate JSON. It is meant for Cody or an internal reviewer to paste or load public examples while source adapters are still imperfect.

The tool does not scrape, browse, enrich, publish, bill, or send SMS. It imports nothing unless both `--import-url` and `--token` are passed. Imported candidates still start as `review_status=pending` and `published=false` because `/v1/candidates/import` enforces review defaults.

## Supported Fields

CSV and JSON inputs may include:

- `title`
- `original_text`
- `summary`
- `source`
- `source_url`
- `source_post_date`
- `vertical`
- `market`
- `market_slug`
- `city`
- `state`
- `zip`
- `lead_type`
- `intent`
- `urgency`
- `contact_method`

`original_text` or `summary` is required. `source_url` is optional, but the tool warns when it is missing. `source` defaults to `manual`, and `vertical` defaults to `real_estate`.

Review-only fields such as `review_status`, `published`, `reviewed_at`, and `reviewed_by` are ignored by the local tool. The backend also forces imports to pending and unpublished.

## Create A CSV From Public Posts

Create a local test folder:

```powershell
New-Item -ItemType Directory -Force C:\buyerboard-api\test
```

Create a CSV from manually reviewed public posts:

```powershell
@'
title,original_text,summary,source,source_url,source_post_date,vertical,market,market_slug,city,state,zip,lead_type,intent,urgency,contact_method
"Public rental request","Paste the public post text or useful excerpt here.","Needs a rental in the next month.","manual","https://example.com/public-post","2026-06-01","real_estate","northwest-ar","northwest-ar","Fayetteville","AR","72701","renter","rent","high","source_message"
'@ | Set-Content -Encoding UTF8 C:\buyerboard-api\test\manual-leads.csv
```

Do not paste private messages, logged-in-only content, passwords, tokens, or payment details into CSV files.

## Dry-Run Output

Generate candidate-compatible JSON to inspect before importing:

```powershell
cd C:\buyerboard-api\app
python tools\manual_lead_intake.py --csv-file C:\buyerboard-api\test\manual-leads.csv > C:\buyerboard-api\test\manual-candidates.json
Get-Content C:\buyerboard-api\test\manual-candidates.json
```

You can also load one JSON object, a JSON array, or `{ "items": [...] }`:

```powershell
python tools\manual_lead_intake.py --json-file C:\buyerboard-api\test\manual-leads.json > C:\buyerboard-api\test\manual-candidates.json
```

For paste-based entry:

```powershell
python tools\manual_lead_intake.py --interactive > C:\buyerboard-api\test\manual-candidates.json
```

## Import Into Discovery Inbox

Import only after inspecting the generated JSON. Both `--import-url` and `--token` are required:

```powershell
$api = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev"
$token = "PASTE_AGENT_TOKEN"

python tools\manual_lead_intake.py `
  --csv-file C:\buyerboard-api\test\manual-leads.csv `
  --import-url "$api/v1/candidates/import" `
  --token $token `
  > C:\buyerboard-api\test\manual-import-result.json
```

The backend candidate importer requires a valid agent Bearer token. Do not store real tokens in repo files.

## Review And Publish

After import, review the candidate in Discovery Inbox. Importing is not publishing.

List pending candidates:

```powershell
Invoke-RestMethod -Method Get "$api/v1/candidates/list?review_status=pending&limit=20" `
  -Headers @{ Authorization = "Bearer $token" } |
  ConvertTo-Json -Depth 8 |
  Set-Content -Encoding UTF8 C:\buyerboard-api\test\pending-candidates.json
```

Reject a bad candidate:

```powershell
Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"reject","review_notes":"Not a real customer intent lead"}' |
  ConvertTo-Json -Depth 8 |
  Set-Content -Encoding UTF8 C:\buyerboard-api\test\reject-result.json
```

Approve and publish a real beta lead:

```powershell
Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"publish","review_notes":"Verified public lead for beta portal"}' |
  ConvertTo-Json -Depth 8 |
  Set-Content -Encoding UTF8 C:\buyerboard-api\test\publish-result.json
```

Customer visibility still depends on the approved/published lead matching the beta customer's configured vertical and service-area coverage.
