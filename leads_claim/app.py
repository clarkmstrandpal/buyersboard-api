# app.py  Leads Claim (Python 3.12)
import os, json, time, base64, boto3

TABLE = os.environ.get("TABLE_LEADS", "buyersboard_leads")
ddb   = boto3.client("dynamodb")

def _b64url_decode_jwt_payload(token):
    try:
        parts = token.split(".")
        if len(parts) < 2: return {}
        p = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(p.encode()).decode())
    except Exception:
        return {}

def _agent_email_from_auth(auth):
    if not auth or " " not in auth: return None
    token = auth.split(" ",1)[1].strip()
    payload = _b64url_decode_jwt_payload(token)
    for k in ("email","sub","user","username"):
        if k in payload: return str(payload[k])
    return None

def _cors():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "authorization,content-type",
        "Access-Control-Allow-Methods": "OPTIONS,POST",
    }

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {**_cors(), "Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def handler(event, context):
    # Preflight
    if event.get("requestContext",{}).get("http",{}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    # Body
    try:
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64 as b64
            body = b64.b64decode(body).decode()
        data = json.loads(body)
    except Exception:
        return _resp(400, {"error":"invalid json"})

    lead_id = data.get("lead_id") or data.get("id") or data.get("leadId")
    if not lead_id:
        return _resp(400, {"error":"missing lead_id"})

    # Who is claiming?
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    agent_email = _agent_email_from_auth(auth) or "unknown@agent"
    now = int(time.time())

    # Simple unconditional update (robust for first cut)
    try:
        ddb.update_item(
            TableName=TABLE,
            Key={"id":{"S": lead_id}},
            UpdateExpression="SET #s=:claimed, claimed_by=:by, claimed_ts=:ts REMOVE claim_expires_ts",
            ExpressionAttributeNames={"#s":"status"},
            ExpressionAttributeValues={
                ":claimed":{"S":"claimed"},
                ":by":{"S": agent_email},
                ":ts":{"N": str(now)}
            },
        )
    except Exception as e:
        return _resp(500, {"error":"dynamodb update failed","detail":str(e)})

    return _resp(200, {"ok":True, "lead_id":lead_id, "claimed_by":agent_email, "claimed_ts":now})
