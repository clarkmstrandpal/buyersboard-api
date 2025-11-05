import os, json, base64, time, hmac, hashlib
import boto3

ddb = boto3.client("dynamodb"); ssm = boto3.client("ssm")
TABLE_LEADS = os.environ.get("TABLE_LEADS", "buyersboard_leads")
JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")

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

def resp(code, obj): return {"statusCode":code,"headers":{"content-type":"application/json","access-control-allow-origin":"*"},"body":json.dumps(obj)}

def handler(event, ctx):
    hdrs = event.get("headers") or {}
    auth = hdrs.get("authorization") or hdrs.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "): return resp(401, {"error":"missing bearer"})
    payload = jwt_decode(auth.split(" ",1)[1], get_secret())
    if not payload or int(time.time()) >= int(payload.get("exp",0)): return resp(401, {"error":"invalid token"})
    agent_id = payload.get("sub")

    out, items = {"total":0,"new":0,"contacted":0,"closed":0}, []
    r = ddb.query(TableName=TABLE_LEADS, IndexName="agent_id_created_index",
                  KeyConditionExpression="agent_id = :a",
                  ExpressionAttributeValues={":a":{"S":agent_id}},
                  ScanIndexForward=False, Limit=50)
    items.extend(r.get("Items", []))
    out["total"] = len(items)
    last10 = []
    for it in items:
        st = (it.get("status",{}).get("S") or "new").lower()
        if st in out: out[st]+=1
        if len(last10)<10:
            last10.append({"id":it["id"]["S"],"created_ts":int(it.get("created_ts",{}).get("N","0")),
                           "name":it.get("name",{}).get("S",""),
                           "email":it.get("email",{}).get("S",""),"status":st})
    return resp(200, {"agent_id":agent_id, "counts":out, "last10":last10})