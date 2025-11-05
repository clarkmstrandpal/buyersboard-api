import os, json, base64, time, hmac, hashlib
import boto3

ddb = boto3.client("dynamodb")
ssm = boto3.client("ssm")

TABLE_LEADS = os.environ.get("TABLE_LEADS", "buyersboard_leads")
JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")

def _pad(s): return s + "=" * (-len(s) % 4)
def jwt_decode(t, secret):
    try:
        h,p,s = t.split(".")
        sig = base64.urlsafe_b64decode(_pad(s))
        msg = f"{h}.{p}".encode()
        exp = hmac.new(secret.encode(), msg, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, exp): return None
        return json.loads(base64.urlsafe_b64decode(_pad(p)).decode())
    except Exception:
        return None

def get_secret():
    return ssm.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]

def resp(code, obj):
    return {"statusCode":code,"headers":{"content-type":"application/json","access-control-allow-origin":"*"},"body":json.dumps(obj)}

def handler(event, ctx):
    # Auth
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return resp(401, {"error":"missing bearer"})
    payload = jwt_decode(auth.split(" ",1)[1], get_secret())
    if not payload or int(time.time()) >= int(payload.get("exp",0)):
        return resp(401, {"error":"invalid token"})
    agent_id = payload.get("sub")

    # Body
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        body = {}
    lead_id = (body.get("lead_id") or "").strip()
    if not lead_id:
        return resp(400, {"error":"lead_id required"})

    now = int(time.time())

    # Only allow claim if:
    # - item exists
    # - agent_id matches this agent
    # - status is NOT already 'claimed'
    try:
        r = ddb.update_item(
            TableName=TABLE_LEADS,
            Key={"id":{"S":lead_id}},
            UpdateExpression="SET #st = :claimed, claimed_ts = :ts",
            ConditionExpression="agent_id = :a AND (attribute_not_exists(#st) OR #st <> :claimed)",
            ExpressionAttributeNames={"#st":"status"},
            ExpressionAttributeValues={
                ":a":{"S":agent_id},
                ":claimed":{"S":"claimed"},
                ":ts":{"N":str(now)}
            },
            ReturnValues="ALL_NEW"
        )
        item = r.get("Attributes", {})
        return resp(200, {
            "ok": True,
            "lead": {
                "id": item.get("id",{}).get("S",""),
                "status": item.get("status",{}).get("S",""),
                "claimed_ts": int(item.get("claimed_ts",{}).get("N","0") or 0)
            }
        })
    except ddb.exceptions.ConditionalCheckFailedException:
        return resp(409, {"ok": False, "error":"cannot claim (already claimed or not assigned to you)"})
    except Exception as e:
        return resp(500, {"ok": False, "error": str(e)})