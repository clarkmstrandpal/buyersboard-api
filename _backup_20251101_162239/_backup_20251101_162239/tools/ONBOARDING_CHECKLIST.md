
# YES-23 Onboarding Checklist
- [ ] `sam build && sam deploy --guided`
- [ ] Put HMAC secret in SSM: `/buyersboard/{stage}/hmac_secret`
- [ ] Put Slack route map in SSM: `/buyersboard/{stage}/slack_routes` (JSON)
- [ ] Verify SES sender + domain; set `SES_FROM`
- [ ] Seed Agents table (CSV or Postman)
- [ ] Test `/v1/ingest` with signed request (see Postman)
- [ ] Confirm `/v1/preview`, `/v1/claim` happy paths
