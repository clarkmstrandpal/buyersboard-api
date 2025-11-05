
# BuyersBoard MVP Pack (v1)
Date: 2025-10-25

This pack contains an AWS SAM project implementing the BuyersBoard MVP:
- Endpoints: `/v1/ingest`, `/v1/preview`, `/v1/claim`, `/v1/router`
- DynamoDB tables: Leads, Agents, Claims, SendLog
- SES email send in ingest
- HMAC request signing (X-Timestamp + X-Signature)
- Slack category router (SSM JSON) and audit log
- Ops stubs: FinOps digest (daily), Alerts

## Quick Start
1. Install AWS SAM CLI and configure credentials.
2. Build & deploy:
   ```bash
   sam build
   sam deploy --guided
   ```
3. Add secrets:
   ```bash
   aws ssm put-parameter --name "/buyersboard/dev/hmac_secret" --type "SecureString" --value "REPLACE_ME"
   aws ssm put-parameter --name "/buyersboard/dev/slack_routes" --type "String" --value '{"default":"https://hooks.slack.com/services/...","finops":"...","alerts":"..."}'
   ```
4. Verify SES sender identity and set `SES_FROM` during deploy.
5. Seed Agents (via Console or script). Minimal item example:
   ```json
   {"agent_id":"A1","email":"agent@example.com","zip":"33067","min_price":0,"max_price":1000000,"paused":false}
   ```
6. Use the Postman collection in `postman/` to test endpoints.

## HMAC Signing
Signature is `hex(hmac_sha256(secret, "<timestamp>.<body>"))`. Send headers `X-Timestamp` (epoch seconds) and `X-Signature` with the request.

## Notes
- Replace scans with GSI queries for performance.
- Add proper daily-cap counters and per-zip/budget throttles as needed.
- Enable CORS origins for your front-end in `template.yaml`.
