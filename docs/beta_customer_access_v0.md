# Beta Customer Access v0

Beta customer access uses optional fields on the existing `buyersboard_agents` records. The goal is to manually activate a paying realtor/customer and restrict `/v1/leads/list` to approved, published leads in that customer's assigned verticals and service areas.

Manual billing remains outside the system. This does not add Stripe, Twilio, SMS delivery, or frontend changes.

## Agent Fields

Add these optional fields to an existing agent record:

```json
{
  "status": "active",
  "plan_name": "beta",
  "monthly_price": 500,
  "verticals": ["real_estate"],
  "markets": ["northwest-ar"],
  "zip_codes": ["72701", "72703"],
  "zip_prefixes": ["727"],
  "sms_enabled": false,
  "phone": "+15555550100"
}
```

The access code accepts DynamoDB lists, string sets, normal strings, or comma-separated strings. Empty coverage means no restriction for that dimension. For example, an active beta customer with `verticals=real_estate` and no ZIP fields can see approved/published real estate leads in all ZIPs that match other configured coverage.

## Visibility Rules

For an authenticated agent with beta access fields:

- `status=inactive` returns an empty lead list.
- `status=active` or missing status with coverage fields applies coverage filters.
- Candidate-origin leads must have a `candidate_id`, `review_status=approved`, and `published=true`.
- If `verticals` is set, lead `vertical` must match one value.
- If `markets` is set, lead `market` or `market_slug` must match one value.
- If `zip_codes` is set, lead `zip` must match one value.
- If `zip_prefixes` is set, lead `zip_prefix` must match one value.

For backward-compatible admin testing, callers with no Bearer token or authenticated agents with no beta access fields keep the existing `/v1/leads/list` behavior. Legacy non-candidate/form leads remain visible only in that unrestricted mode.

Invalid Bearer tokens, expired tokens, and tokens for missing agent records return `401`.

## PowerShell Examples

Set local variables:

```powershell
$table = "buyersboard_agents"
$email = "agent@example.com"
```

Find an agent by email:

```powershell
aws dynamodb query `
  --table-name $table `
  --index-name email_index `
  --key-condition-expression "email = :email" `
  --expression-attribute-values "{`":email`":{`"S`":`"$email`"}}" `
  --projection-expression "agent_id,email,#s,plan_name,verticals,markets,zip_codes,zip_prefixes" `
  --expression-attribute-names "{`"#s`":`"status`"}"
```

Activate beta access for an agent:

```powershell
$agentId = "PASTE_AGENT_ID"

aws dynamodb update-item `
  --table-name $table `
  --key "{`"agent_id`":{`"S`":`"$agentId`"}}" `
  --update-expression "SET #s = :active, plan_name = :plan, monthly_price = :price, verticals = :verticals, markets = :markets, zip_prefixes = :prefixes, sms_enabled = :sms" `
  --expression-attribute-names "{`"#s`":`"status`"}" `
  --expression-attribute-values "{`":active`":{`"S`":`"active`"},`":plan`":{`"S`":`"beta`"},`":price`":{`"N`":`"500`"},`":verticals`":{`"SS`":[`"real_estate`"]},`":markets`":{`"SS`":[`"northwest-ar`"]},`":prefixes`":{`"SS`":[`"727`"]},`":sms`":{`"BOOL`":false}}"
```

Deactivate access:

```powershell
aws dynamodb update-item `
  --table-name $table `
  --key "{`"agent_id`":{`"S`":`"$agentId`"}}" `
  --update-expression "SET #s = :inactive" `
  --expression-attribute-names "{`"#s`":`"status`"}" `
  --expression-attribute-values "{`":inactive`":{`"S`":`"inactive`"}}"
```

Call `/v1/leads/list` as a beta customer:

```powershell
$api = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/dev"
$token = "PASTE_AGENT_TOKEN"

Invoke-RestMethod -Method Get "$api/v1/leads/list?limit=20" `
  -Headers @{ Authorization = "Bearer $token" }
```

Do not put real passwords or tokens in repo files.

## Limitations

- This is manual beta access control only; billing remains manual.
- SMS fields are stored for future use only. This PR does not send SMS.
- `/v1/leads/list` remains backward compatible for no-token/admin test callers. Production customer portal calls should send a valid agent Bearer token so territory filters apply.
- Post-query filtering can return fewer than `limit` items when many leads are outside a customer's coverage.
