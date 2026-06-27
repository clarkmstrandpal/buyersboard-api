# Beta Lead Review Workflow v0

This workflow keeps raw discovered candidates out of the customer-facing realtor portal until a human reviews and publishes them.

## Flow

1. A local source adapter finds a public candidate lead.
2. Lead Scout AI/rules score and filter the candidate.
3. The reviewed candidate is imported into the Discovery Inbox with `review_status=pending` and `published=false`.
4. An authenticated internal reviewer opens the Discovery Inbox and reviews the candidate.
5. The reviewer rejects the candidate, approves it for later, or approves and publishes it.
6. Paying realtor/customer lead lists only show candidate-origin leads after `review_status=approved` and `published=true`.

Manual billing remains outside the system for now. This does not add Stripe, Twilio, SMS, or any frontend redesign.

## Candidate Fields

Imported candidates default missing review fields to:

```json
{
  "review_status": "pending",
  "published": false
}
```

The candidate records may include:

- `vertical`
- `market`
- `zip`
- `city`
- `lead_type`
- `urgency`
- `intent`
- `summary`
- `source`
- `source_url`
- `source_post_date`
- `original_text`
- `snippet`
- `reviewed_at`
- `reviewed_by`

## Admin Review Actions

All `/v1/candidates/*` routes require a valid Bearer token from `/v1/agents/login`.

Approve without publishing:

```powershell
$token = "PASTE_AGENT_TOKEN"
$api = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev"

Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"approve","review_notes":"Looks valid, hold for publishing"}'
```

Approve and publish:

```powershell
Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"publish","review_notes":"Approved for beta customer"}'
```

Reject:

```powershell
Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"reject","review_notes":"Not a real customer intent lead"}'
```

Unpublish:

```powershell
Invoke-RestMethod -Method Post "$api/v1/candidates/action" `
  -Headers @{ Authorization = "Bearer $token" } `
  -ContentType "application/json" `
  -Body '{"candidate_id":"CANDIDATE_ID","action":"unpublish","review_notes":"Pulled from beta customer view"}'
```

Legacy actions still work: `good`, `maybe`, `rejected`, `duplicate`, `archive`, `archived`, and `send_to_leads`. For v0, `send_to_leads` is treated as an approve-and-publish action.

## Discovery Inbox Filters

List pending candidates:

```powershell
Invoke-RestMethod -Method Get "$api/v1/candidates/list?review_status=pending&limit=20" `
  -Headers @{ Authorization = "Bearer $token" }
```

List approved or rejected candidates:

```powershell
Invoke-RestMethod -Method Get "$api/v1/candidates/list?review_status=approved&limit=20" `
  -Headers @{ Authorization = "Bearer $token" }

Invoke-RestMethod -Method Get "$api/v1/candidates/list?review_status=rejected&limit=20" `
  -Headers @{ Authorization = "Bearer $token" }
```

## Customer Visibility

Candidate-origin records promoted into the normal leads table are visible through `/v1/leads/list` only when:

```json
{
  "review_status": "approved",
  "published": true
}
```

Non-candidate legacy/form leads continue to appear as before so existing dashboard behavior is preserved.

## Limitations

- There is no separate admin role gate yet. Any authenticated agent/admin token accepted by the existing candidate routes can review candidates in v0.
- Billing remains manual and outside the backend.
- This PR does not depend on Craigslist RSS availability and does not add any source adapters.
- Rejected or unpublished promoted leads remain in the leads table but are hidden from `/v1/leads/list` by the candidate visibility filter.
