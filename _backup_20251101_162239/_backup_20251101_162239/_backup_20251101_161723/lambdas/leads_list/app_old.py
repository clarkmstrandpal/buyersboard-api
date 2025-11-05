# Create/overwrite the file in one go
New-Item -ItemType Directory -Force "C:\buyerboard-api\app\lambdas\leads_list" | Out-Null
@"
import base64
import json
import os
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr

# ----- DynamoDB setup -----
DDB = boto3.resource("dynamodb")
TABLE_NAME = os.environ.get("TABLE_LEADS", "buyersboard_leads")
TABLE = DDB.Table(TABLE_NAME)

# Optional, soft HMAC import (won't break if layer not attached)
def _try_hmac(event):
    try:
        from common.hmac_auth import require_hmac  # from buyersboard-common layer
        # allow GET without auth during MVP; lock down later if needed
        method = event.get("requestContext", {}).get("http", {}).get("method")
        if method and method.upper() != "GET":
            require_hmac(event)
    except Exception:
        # No layer / dev mode: do nothing
        pass

# ----- helpers -----
def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None

def _json(o):
    def _default(x):
        if isinstance(x, Decimal):
            # Keep 0/1/2 decimals sane; float is fine for client display
            return float(x)
        return x
    return json.dumps(o, default=_default)

def _resp(code: int, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
    h = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "GET,OPTIONS",
    }
    if headers:
        h.update(headers)
    return {"statusCode": code, "headers": h, "body": _json(body)}

def _b64(obj: Dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(obj).encode("utf-8")).decode("utf-8")

def _b64_to_obj(s: Optional[str]) -> Optional[Dict[str, Any]]:
    if not s:
        return None
    try:
        return json.loads(base64.urlsafe_b64decode(s.encode("utf-8")).decode("utf-8"))
    except Exception:
        return None

def _gsi_exists(index_name: str) -> bool:
    try:
        desc = DDB.meta.client.describe_table(TableName=TABLE_NAME)
        for idx in (desc.get("Table", {}).get("GlobalSecondaryIndexes") or []):
            if idx.get("IndexName") == index_name:
                return True
    except Exception:
        pass
    return False

# ----- Lambda handler -----
def handler(event, context):
    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return _resp(200, {"ok": True})

    _try_hmac(event)

    qs = event.get("queryStringParameters") or {}

    # pagination limit
    try:
        limit = int(qs.get("limit") or 25)
    except Exception:
        limit = 25
    limit = max(1, min(limit, 100))

    # filters
    zip_code   = (qs.get("zip") or "").strip() or None
    zip_prefix = (qs.get("zip_prefix") or "").strip() or None
    status     = (qs.get("status") or "").strip() or None
    min_price  = _to_float(qs.get("min_price"))
    max_price  = _to_float(qs.get("max_price"))

    # cursor
    eks = _b64_to_obj(qs.get("next_cursor")or qs.get("cursor"))

    # Prefer fast indexed query when possible
    gsi_name = "zip_prefix_created_index"  # HASH: zip_prefix (S), RANGE: created_ts (N)
    use_gsi = bool(zip_prefix) and _gsi_exists(gsi_name)

    items = []
    last_key = None

    if use_gsi:
        key_cond = Key("zip_prefix").eq(zip_prefix)
        q_kwargs: Dict[str, Any] = {
            "IndexName": gsi_name,
            "KeyConditionExpression": key_cond,
            "Limit": limit,
            "ScanIndexForward": False,  # newest first on created_ts
        }
        if eks:
            q_kwargs["ExclusiveStartKey"] = eks

        # non-key filters
        filt = None
        if status:
            filt = Attr("status").eq(status)
        if min_price is not None:
            fp = Attr("price").gte(Decimal(str(min_price)))
            filt = fp if filt is None else (filt & fp)
        if max_price is not None:
            fp2 = Attr("price").lte(Decimal(str(max_price)))
            filt = fp2 if filt is None else (filt & fp2)
        if filt is not None:
            q_kwargs["FilterExpression"] = filt

        resp = TABLE.query(**q_kwargs)
        items = resp.get("Items", [])
        last_key = resp.get("LastEvaluatedKey")
    else:
        # Fallback: Scan with filters — OK for MVP / small volumes
        s_kwargs: Dict[str, Any] = {"Limit": limit}
        if eks:
            s_kwargs["ExclusiveStartKey"] = eks

        filt = None
        if zip_code:
            fz = Attr("zip").eq(zip_code)
            filt = fz if filt is None else (filt & fz)
        if zip_prefix:
            fzp = Attr("zip_prefix").eq(zip_prefix)
            filt = fzp if filt is None else (filt & fzp)
        if status:
            fs = Attr("status").eq(status)
            filt = fs if filt is None else (filt & fs)
        if min_price is not None:
            fp = Attr("price").gte(Decimal(str(min_price)))
            filt = fp if filt is None else (filt & fp)
        if max_price is not None:
            fp2 = Attr("price").lte(Decimal(str(max_price)))
            filt = fp2 if filt is None else (filt & fp2)
        if filt is not None:
            s_kwargs["FilterExpression"] = filt

        resp = TABLE.scan(**s_kwargs)
        items = resp.get("Items", [])
        last_key = resp.get("LastEvaluatedKey")

    return _resp(200, {
        "items": items,
        "next_cursor": _b64(last_key) if last_key else None
    })
"@ | Set-Content -Encoding UTF8 "C:\buyerboard-api\app\lambdas\leads_list\app.py"
