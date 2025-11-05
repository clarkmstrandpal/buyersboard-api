# handlers/leads_actions/app.py
import os, json, time, base64, boto3
from decimal import Decimal

TABLE = os.environ.get("TABLE_LEADS", "buyersboard_leads")
CLAIM_WINDOW_SEC = int(os.environ.get("CLAIM_WINDOW_SEC", "600"))  # 10 minutes

ddb = boto3.resource("dynamodb")
table = ddb.Table(TABLE)

def _resp(code, body):
    return {"statusCode": code,
            "headers": {"Content-Type":"application/json", "Access-Control-Allow-Origin":"*"},
            "body": json.dumps(body)}

def _now(): return int(time.time())

def _json(event):
    try:
        return json.loads(event.get("body") or "{}")
    except Exception:
        return {}

def _bearer_email(event):
    # best-effort: decode JWT payload without verification to read "email"
    auth = (event.get("headers") or {}).get("authorization") or (event.get("headers") or {}).get("Authorization")
    if not auth or not auth.lower().startswith("bearer "): return None
    token = auth.split(" ",1)[1]
    parts = token.split(".")
    if len(parts) != 3: return None
    try:
        import json, base64
        pad = "="*((4 - len(parts[1])%4)%4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad).decode("utf-8"))
        return payload.get("email") or payload.get("sub") or None
    except Exception:
        return None

def _get_id(body):
    return body.get("id") or body.get("lead_id") or body.get("leadId")

def _claim(lead_id, agent_email):
    if not lead_id: return _resp(400, {"error":"missing id"})
    if not agent_email: agent_email = "unknown@local"
    now = _now()
    min_cts = now - CLAIM_WINDOW_SEC
    # guard: exists, not already claimed/closed/archived, and created_ts not too old (if present)
    expr = "SET claimed_by=:c, claimed_ts=:t, #st=:open"
    cond = "attribute_exists(id) AND (attribute_not_exists(claimed_by)) AND (attribute_not_exists(archived) OR archived = :false) AND (attribute_not_exists(closed) OR closed = :false) AND (attribute_not_exists(created_ts) OR created_ts >= :min)"
    names = {"#st":"status"}
    vals  = {":c":agent_email, ":t":now, ":open":"open", ":false":False, ":min":min_cts}
    try:
        table.update_item(Key={"id": lead_id}, UpdateExpression=expr, ConditionExpression=cond,
                          ExpressionAttributeNames=names, ExpressionAttributeValues=vals)
        return _resp(200, {"ok":True, "id":lead_id, "status":"open"})
    except ddb.meta.client.exceptions.ConditionalCheckFailedException:
        return _resp(409, {"error":"expired or already claimed/closed/archived"})
    except Exception as e:
        return _resp(500, {"error":str(e)})

def _archive(lead_id):
    if not lead_id: return _resp(400, {"error":"missing id"})
    try:
        table.update_item(Key={"id": lead_id},
                          UpdateExpression="SET archived=:true, archived_ts=:t, #st=:arch",
                          ExpressionAttributeNames={"#st":"status"},
                          ExpressionAttributeValues={":true":True, ":arch":"archived", ":t":_now()})
        return _resp(200, {"ok":True, "id":lead_id, "status":"archived"})
    except Exception as e:
        return _resp(500, {"error":str(e)})

def _close(lead_id, outcome):
    if not lead_id: return _resp(400, {"error":"missing id"})
    if outcome not in ("sale","nosale"):
        return _resp(400, {"error":"outcome must be 'sale' or 'nosale'"})
    try:
        table.update_item(Key={"id": lead_id},
                          UpdateExpression="SET closed=:true, closed_ts=:t, outcome=:o, #st=:closed",
                          ExpressionAttributeNames={"#st":"status"},
                          ExpressionAttributeValues={":true":True, ":closed":"closed", ":t":_now(), ":o":outcome})
        return _resp(200, {"ok":True, "id":lead_id, "status":"closed", "outcome":outcome})
    except Exception as e:
        return _resp(500, {"error":str(e)})

def _reopen(lead_id):
    if not lead_id: return _resp(400, {"error":"missing id"})
    try:
        # If it was claimed before, reopen to 'open', else 'new'
        item = table.get_item(Key={"id": lead_id}).get("Item") or {}
        new_status = "open" if item.get("claimed_by") else "new"
        table.update_item(Key={"id": lead_id},
                          UpdateExpression="REMOVE archived, archived_ts, closed, closed_ts, outcome SET #st=:s, reopened_ts=:t",
                          ExpressionAttributeNames={"#st":"status"},
                          ExpressionAttributeValues={":s":new_status, ":t":_now()})
        return _resp(200, {"ok":True, "id":lead_id, "status":new_status})
    except Exception as e:
        return _resp(500, {"error":str(e)})

def handler(event, context):
    route = (event.get("requestContext") or {}).get("http",{}).get("path","")
    method= (event.get("requestContext") or {}).get("http",{}).get("method","GET")
    if method != "POST":
        return _resp(405, {"error":"method not allowed"})

    body  = _json(event)
    lid   = _get_id(body)
    email = _bearer_email(event)

    if route.endswith("/v1/leads/claim"):   return _claim(lid, email)
    if route.endswith("/v1/leads/archive"): return _archive(lid)
    if route.endswith("/v1/leads/close"):   return _close(lid, body.get("outcome"))
    if route.endswith("/v1/leads/reopen"):  return _reopen(lid)
    return _resp(404, {"error":"not found"})
