import os
import json
import base64
import boto3
from decimal import Decimal
from boto3.dynamodb.conditions import Key, Attr

DDB = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("TABLE_LEADS", "buyersboard_leads")
TABLE = DDB.Table(TABLE_NAME)

DEFAULT_LIMIT = int(os.environ.get("LIST_LIMIT", "24"))

def _decimal_to_float(obj):
    if isinstance(obj, list):
        return [_decimal_to_float(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj

def _b64e(dct):
    raw = json.dumps(dct).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")

def _b64d(s):
    return json.loads(base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8"))

def _pick_lightweight(item):
    # return only fields the UI needs for list view
    keys = ("lead_id","id","zip","zip_prefix","price","status","created_ts","beds","baths","email","name")
    out = {}
    for k in keys:
        if k in item:
            out[k] = item[k]
    # normalize id
    if "id" not in out and "lead_id" in out:
        out["id"] = out["lead_id"]
    if "lead_id" not in out and "id" in out:
        out["lead_id"] = out["id"]
    # normalize status/claimed if needed
    if "status" not in out and "claimed" in item:
        out["status"] = "claimed" if item.get("claimed") else "new"
    return out

def handler(event, context):
    # Parse query params
    qp = (event.get("queryStringParameters") or {})

    zip_code = (qp.get("zip") or "").strip()
    zip_prefix = (qp.get("zip_prefix") or "").strip()
    min_price = qp.get("min_price")
    max_price = qp.get("max_price")
    status = (qp.get("status") or "").strip()
    limit = int(qp.get("limit") or DEFAULT_LIMIT)
    cursor = qp.get("cursor") or qp.get("next_cursor")

    # Derive zip_prefix if only zip provided
    if zip_code and not zip_prefix:
        zip_prefix = zip_code[:3]

    # Build key condition for GSI when zip_prefix is present
    use_gsi = bool(zip_prefix)
    key_cond = None
    index_name = None
    scan_forward = False  # False => DESC (newest first)

    if use_gsi:
        index_name = "zip_prefix_created_index"
        key_cond = Key("zip_prefix").eq(zip_prefix)

    # Base query/scan kwargs
    kwargs = {
        "Limit": limit,
        "ScanIndexForward": scan_forward,
    }
    if cursor:
        try:
            kwargs["ExclusiveStartKey"] = _b64d(cursor)
        except Exception:
            # ignore bad cursor
            pass

    # Build filter expression
    fe = None
    def add_filter(expr):
        nonlocal fe
        fe = expr if fe is None else fe & expr

    if status:
        add_filter(Attr("status").eq(status))

    if min_price is not None:
        try:
            add_filter(Attr("price").gte(Decimal(str(min_price))))
        except Exception:
            pass

    if max_price is not None:
        try:
            add_filter(Attr("price").lte(Decimal(str(max_price))))
        except Exception:
            pass

    if zip_code:
        # When using GSI, we can still filter exact ZIP
        add_filter(Attr("zip").eq(zip_code))

    # Execute
    if use_gsi:
        # GSI query
        if key_cond is not None:
            kwargs["IndexName"] = index_name
            kwargs["KeyConditionExpression"] = key_cond
            if fe is not None:
                kwargs["FilterExpression"] = fe
            resp = TABLE.query(**kwargs)
        else:
            resp = {"Items": [], "Count": 0}
    else:
        # Fallback: full table scan (avoid if possible)
        scan_kwargs = {}
        if fe is not None:
            scan_kwargs["FilterExpression"] = fe
        if "ExclusiveStartKey" in kwargs:
            scan_kwargs["ExclusiveStartKey"] = kwargs["ExclusiveStartKey"]
        # Manual sort DESC on created_ts after scan (not ideal; prefer zip_prefix path)
        items = []
        last_evaluated_key = None
        count = 0
        while True:
            part = TABLE.scan(Limit=limit, **scan_kwargs)
            items.extend(part.get("Items", []))
            last_evaluated_key = part.get("LastEvaluatedKey")
            count += part.get("Count", 0)
            # stop after first page for responsiveness
            break
        items.sort(key=lambda x: x.get("created_ts", 0), reverse=True)
        resp = {"Items": items[:limit], "Count": len(items[:limit]), "LastEvaluatedKey": last_evaluated_key}

    items = [_pick_lightweight(i) for i in resp.get("Items", [])]
    items = _decimal_to_float(items)
    lek = resp.get("LastEvaluatedKey")
    out = {
        "items": items,
        "next_cursor": _b64e(lek) if lek else None,
    }
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(out),
    }