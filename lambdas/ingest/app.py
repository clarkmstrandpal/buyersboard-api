# lambdas/ingest/app.py
import os, json, base64, uuid, datetime, time
from decimal import Decimal
import boto3

from common.resp import ok, err  # type: ignore

LEAD_FINDER_FIELDS = (
    "source_url",
    "intent",
    "message",
    "description",
    "title",
    "city",
    "state",
    "role",
)


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

        lead_id = str(uuid.uuid4())

        # Form leads can keep sending full contact fields. Scraped/public posts may
        # omit name, email, and zip while still preserving the lead-like content.
        first_name = _to_str(data.get("first_name"))
        last_name = _to_str(data.get("last_name"))
        email = _to_str(data.get("email")) or f"missing+{lead_id}@placeholder.listlyhomes.local"

        # Normalize zip & zip_prefix. Public posts often do not expose ZIP yet.
        zip_code = (_to_str(data.get("zip")) or "00000")[:10]
        zip_prefix = zip_code[:3]

        # Optional fields
        phone = _to_str(data.get("phone"))
        notes = _to_str(data.get("notes"))
        source = _to_str(data.get("source")) or "api_ingest_v1"

        price = _to_decimal(data.get("price"))
        beds = _to_int(data.get("beds"))
        baths = _to_int(data.get("baths"))

        status = _to_str(data.get("status")) or "new"  # default "new"

        # Timestamps
        created_ts = int(time.time())
        created_at = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"

        # Build item
        item = {
            "id": lead_id,
            "email": email,
            "zip": zip_code,
            "zip_prefix": zip_prefix,      # <-- for GSI
            "created_ts": created_ts,      # <-- numeric for sort/key
            "created_at": created_at,      # human-friendly
            "status": status,
            "source": source,
        }

        if first_name is not None: item["first_name"] = first_name
        if last_name is not None: item["last_name"] = last_name
        if phone is not None: item["phone"] = phone
        if notes is not None: item["notes"] = notes

        for field in LEAD_FINDER_FIELDS:
            value = _to_str(data.get(field))
            if value is not None:
                item[field] = value

        # Optional numerics only if present
        if price is not None: item["price"] = price
        if beds is not None: item["beds"] = beds
        if baths is not None: item["baths"] = baths

        # Persist
        _table().put_item(Item=item)

        # Response (echo key fields)
        echo = {
            "id": item["id"],
            "first_name": item.get("first_name"),
            "email": item.get("email"),
            "zip": item.get("zip"),
            "status": item.get("status"),
            "source": item.get("source"),
            "source_url": item.get("source_url"),
            "intent": item.get("intent"),
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
