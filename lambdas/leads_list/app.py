
import os
import json
import base64
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr

DDB = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("TABLE_LEADS", "buyersboard_leads")
TABLE = DDB.Table(TABLE_NAME)

GSI_NAME = "zip_prefix_created_index"
DEFAULT_LIMIT = int(os.environ.get("LIST_LIMIT", "24"))

LIGHT_KEYS = ("lead_id","id","zip","zip_prefix","price","status","created_ts","beds","baths","email","name")

def _json(body: Any) -> str:
    return json.dumps(body, default=str)

def _resp(code: int, body: Any, headers: Optional[Dict[str,str]] = None):
    h = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
    }
    if headers:
        h.update(headers)
    return {"statusCode": code, "headers": h, "body": _json(body)}

def _b64(obj: Optional[Dict[str, Any]]) -> Optional[str]:
    if not obj:
        return None
    raw = json.dumps(obj).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")

def _b64_to_obj(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(s.encode("utf-8")).decode("utf-8"))
    except Exception:
        return None

def _light(item: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in LIGHT_KEYS:
        if k in item:
            out[k] = item[k]
    # normalize ids
    if "id" not in out and "lead_id" in item:
        out["id"] = item["lead_id"]
    if "lead_id" not in out and "id" in item:
        out["lead_id"] = item["id"]
    # status fallback
    if "status" not in out and "claimed" in item:
        out["status"] = "claimed" if item.get("claimed") else "new"
    return out

def handler(event, context):
    try:
        qs = event.get("queryStringParameters") or {}

        zip_code = (qs.get("zip") or "").strip()
        zip_prefix = (qs.get("zip_prefix") or "").strip()
        # If only zip provided, derive prefix for GSI
        if zip_code and not zip_prefix:
            zip_prefix = zip_code[:3]

        # accept both keys
        cursor = qs.get("cursor") or qs.get("next_cursor")
        exclusive = _b64_to_obj(cursor)

        # numbers
        limit = int(qs.get("limit") or DEFAULT_LIMIT)
        min_price = qs.get("min_price")
        max_price = qs.get("max_price")

        # canonicalize numeric filters
        try:
            min_price = None if min_price in (None, "", "null") else Decimal(str(min_price))
        except Exception:
            min_price = None
        try:
            max_price = None if max_price in (None, "", "null") else Decimal(str(max_price))
        except Exception:
            max_price = None

        status = (qs.get("status") or "").strip()

        # build filter
        filt = None
        if status:
            filt = Attr("status").eq(status)
        if min_price is not None:
            cond = Attr("price").gte(min_price)
            filt = cond if filt is None else (filt & cond)
        if max_price is not None:
            cond = Attr("price").lte(max_price)
            filt = cond if filt is None else (filt & cond)
        if zip_code:
            cond = Attr("zip").eq(zip_code)
            filt = cond if filt is None else (filt & cond)

        # prefer GSI when prefix present
        if zip_prefix:
            kwargs = {
                "IndexName": GSI_NAME,
                "KeyConditionExpression": Key("zip_prefix").eq(zip_prefix),
                "Limit": limit,
                "ScanIndexForward": False,  # newest first
            }
            if exclusive:
                kwargs["ExclusiveStartKey"] = exclusive
            if filt is not None:
                kwargs["FilterExpression"] = filt
            resp = TABLE.query(**kwargs)
        else:
            # fallback scan (avoid if possible)
            kwargs = {"Limit": limit}
            if exclusive:
                kwargs["ExclusiveStartKey"] = exclusive
            if filt is not None:
                kwargs["FilterExpression"] = filt
            resp = TABLE.scan(**kwargs)
            items = resp.get("Items", [])
            # best-effort DESC on created_ts
            items.sort(key=lambda x: x.get("created_ts", 0), reverse=True)
            resp["Items"] = items[:limit]

        items = [_light(i) for i in resp.get("Items", [])]
        next_cursor = _b64(resp.get("LastEvaluatedKey"))

        return _resp(200, {"items": items, "next_cursor": next_cursor})

    except Exception as e:
        # Surface the exception for now to speed up debugging
        return _resp(500, {"error": str(e), "type": e.__class__.__name__})
