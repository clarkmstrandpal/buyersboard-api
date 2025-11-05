# lambdas/ingest/app.py
import os, json, base64, uuid, datetime, time
from decimal import Decimal
import boto3

# Optional: use your layer if present; otherwise fallbacks keep working.
try:
    from common.resp import ok, err  # type: ignore
except Exception:
    def ok(payload, origin="*"):
        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key,X-Amz-Date,X-Amz-Security-Token",
            },
            "body": json.dumps(payload),
        }

    def err(msg, code=500, origin="*"):
        return {
            "statusCode": code,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Api-Key,X-Amz-Date,X-Amz-Security-Token",
            },
            "body": json.dumps({"error": msg}),
        }

def _origin():
    return os.environ.get("CORS_ORIGIN", "*")

def _parse_body(event):
    body = event.get("body")
    if body is None:
        return {}
    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except Exception:
            pass
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        try:
            return json.loads(body)
        except Exception:
            return {}
    if isinstance(body, dict):
        return body
    return {}

def _table():
    name = os.environ.get("TABLE_LEADS")
    if not name:
        raise RuntimeError("TABLE_LEADS env var not set")
    ddb = boto3.resource("dynamodb")
    return ddb.Table(name)

def _to_str(x):
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None

def _to_int(x):
    try:
        return int(x)
    except Exception:
        return None

def _to_decimal(x):
    # Accepts "350000", "350,000", 350000, "350000.00"
    if x is None or x == "":
        return None
    try:
        if isinstance(x, (int, float)):
            return Decimal(str(x))
        s = str(x).replace(",", "").strip()
        return Decimal(s)
    except Exception:
        return None

def lambda_handler(event, context):
    origin = _origin()

    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return ok({"preflight": True}, origin)

    try:
        data = _parse_body(event)

        # Required
        required = ["first_name", "email", "zip"]
        missing = [k for k in required if not data.get(k)]
        if missing:
            return err(f"Missing required fields: {', '.join(missing)}", 400, origin)

        # Normalize zip & zip_prefix
        zip_code = _to_str(data.get("zip"))
        if not zip_code:
            return err("zip is required", 400, origin)
        zip_code = zip_code[:10]  # basic guard
        zip_prefix = zip_code[:3]

        # Optional fields
        last_name = _to_str(data.get("last_name"))
        phone     = _to_str(data.get("phone"))
        notes     = _to_str(data.get("notes"))

        price     = _to_decimal(data.get("price"))
        beds      = _to_int(data.get("beds"))
        baths     = _to_int(data.get("baths"))

        status    = _to_str(data.get("status")) or "new"  # default "new"

        # Timestamps
        created_ts  = int(time.time())
        created_at  = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

        # Build item
        item = {
            "id": str(uuid.uuid4()),
            "first_name": _to_str(data.get("first_name")),
            "last_name": last_name,
            "email": _to_str(data.get("email")),
            "phone": phone,
            "zip": zip_code,
            "zip_prefix": zip_prefix,      # <-- for GSI
            "created_ts": created_ts,      # <-- numeric for sort/key
            "created_at": created_at,      # human-friendly
            "status": status,
            "source": _to_str(data.get("source")) or "api_ingest_v1",
        }

        # Optional numerics only if present
        if price is not None: item["price"] = price
        if beds  is not None: item["beds"]  = beds
        if baths is not None: item["baths"] = baths
        if notes is not None: item["notes"] = notes

        # Persist
        _table().put_item(Item=item)

        # Response (echo key fields)
        echo = {
            "id": item["id"],
            "first_name": item.get("first_name"),
            "email": item.get("email"),
            "zip": item.get("zip"),
            "status": item.get("status"),
            "created_at": item.get("created_at"),
        }
        return ok({"status": "ok", "received": echo}, origin)

    except Exception as e:
        try:
            print("ERROR:", repr(e))
            ev = dict(event)
            if "body" in ev and isinstance(ev["body"], str) and len(ev["body"]) > 1000:
                ev["body"] = ev["body"][:1000] + "...<truncated>"
            print("EVENT:", json.dumps(ev))
        except Exception:
            pass
        return err(str(e), 500, origin)
