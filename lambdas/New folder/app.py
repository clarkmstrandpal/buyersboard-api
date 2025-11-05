import os, json, base64, time, hmac, hashlib
import boto3
from boto3.dynamodb.conditions import Key, Attr

# --- Env / clients
ddb_client = boto3.client("dynamodb")
dynamodb   = boto3.resource("dynamodb")
ssm        = boto3.client("ssm")

TABLE_LEADS = os.environ.get("TABLE_LEADS", "buyersboard_leads")
JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")
GSI_PREFIX = "zip_prefix_created_index"           # global summary path
GSI_AGENT  = "agent_id_created_index"             # agent summary path
SUMMARY_SCAN_LIMIT = int(os.environ.get("SUMMARY_SCAN_LIMIT", "1000"))

# --- JWT helpers (unchanged from your file)
def _pad(s): return s + "=" * (-len(s) % 4)
def jwt_decode(t, secret):
    try:
        h,p,s = t.split("."); import base64 as b64, hmac, hashlib, json
        sig = b64.urlsafe_b64decode(_pad(s)); msg = f"{h}.{p}".encode()
        exp = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, exp): return None
        return json.loads(b64.urlsafe_b64decode(_pad(p)).decode())
    except Exception: return None

def get_secret():
    return ssm.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]

def resp(code, obj):
    return {
        "statusCode": code,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
            "access-control-allow-headers": "*",
            "access-control-allow-methods": "GET,OPTIONS",
        },
        "body": json.dumps(obj, default=str)
    }

# --- Global summary helpers
def _accumulate_counts(items, counts):
    for it in items:
        st = (it.get("status") or it.get("status",{}).get("S") or ("claimed" if (it.get("claimed") or it.get("claimed",{}).get("BOOL")) else "new")).lower()
        counts[st] = counts.get(st, 0) + 1

def global_summary(qs):
    """Return counts by status, optionally filtered by zip_prefix (GSI)."""
    zip_code = (qs.get("zip") or "").strip()
    zip_prefix = (qs.get("zip_prefix") or "").strip()
    status = (qs.get("status") or "").strip()

    # derive prefix if only full zip provided
    if zip_code and not zip_prefix:
        zip_prefix = zip_code[:3]

    table = dynamodb.Table(TABLE_LEADS)
    counts = {"new": 0, "claimed": 0, "archived": 0}
    scanned = 0
    last_evaluated_key = None

    if zip_prefix:
        # GSI query for speed
        while True and scanned < SUMMARY_SCAN_LIMIT:
            kwargs = {
                "IndexName": GSI_PREFIX,
                "KeyConditionExpression": Key("zip_prefix").eq(zip_prefix),
                "ScanIndexForward": False,
                "Limit": min(200, SUMMARY_SCAN_LIMIT - scanned),
            }
            if last_evaluated_key:
                kwargs["ExclusiveStartKey"] = last_evaluated_key
            if status:
                kwargs["FilterExpression"] = Attr("status").eq(status)
            respq = table.query(**kwargs)
            items = respq.get("Items", [])
            _accumulate_counts(items, counts)
            scanned += len(items)
            last_evaluated_key = respq.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break
    else:
        # bounded scan when no prefix provided
        while True and scanned < SUMMARY_SCAN_LIMIT:
            kwargs = {"Limit": min(200, SUMMARY_SCAN_LIMIT - scanned)}
            if last_evaluated_key:
                kwargs["ExclusiveStartKey"] = last_evaluated_key
            if status:
                kwargs["FilterExpression"] = Attr("status").eq(status)
            resps = table.scan(**kwargs)
            items = resps.get("Items", [])
            _accumulate_counts(items, counts)
            scanned += len(items)
            last_evaluated_key = resps.get("LastEvaluatedKey")
            if not last_evaluated_key:
                break

    return resp(200, {"zip_prefix": zip_prefix or None, "status_counts": counts, "scanned": scanned})

# --- Agent summary (your original behavior)
def agent_summary(agent_id):
    out, items = {"total":0,"new":0,"contacted":0,"closed":0,"claimed":0,"archived":0}, []
    r = ddb_client.query(
        TableName=TABLE_LEADS,
        IndexName=GSI_AGENT,
        KeyConditionExpression="agent_id = :a",
        ExpressionAttributeValues={":a":{"S":agent_id}},
        ScanIndexForward=False, Limit=50
    )
    items.extend(r.get("Items", []))
    out["total"] = len(items)
    last10 = []
    for it in items:
        st = (it.get("status",{}).get("S") or "new").lower()
        if st in out: out[st]+=1
        if len(last10)<10:
            last10.append({
                "id":it.get("id",{}).get("S",""),
                "created_ts":int(it.get("created_ts",{}).get("N","0")),
                "name":it.get("name",{}).get("S",""),
                "email":it.get("email",{}).get("S",""),
                "status":st
            })
    return resp(200, {"agent_id":agent_id, "counts":out, "last10":last10})

# --- Entry
def handler(event, ctx):
    qs = (event.get("queryStringParameters") or {})
    hdrs = event.get("headers") or {}
    auth = hdrs.get("authorization") or hdrs.get("Authorization")

    # Allow forcing global mode via scope=global (even if a bearer is present)
    scope = (qs.get("scope") or "").lower()

    if scope == "global" or not auth or not auth.lower().startswith("bearer "):
        # global summary (public-ish)
        return global_summary(qs)

    # agent summary (requires valid bearer)
    payload = jwt_decode(auth.split(" ",1)[1], get_secret())
    if not payload or int(time.time()) >= int(payload.get("exp",0)):
        return resp(401, {"error":"invalid token"})
    agent_id = payload.get("sub")
    return agent_summary(agent_id)