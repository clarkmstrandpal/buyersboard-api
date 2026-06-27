
import os
import json
import base64
import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr

DDB = boto3.resource("dynamodb")
SSM = boto3.client("ssm")
TABLE_NAME = os.environ.get("TABLE_LEADS", "buyersboard_leads")
TABLE = DDB.Table(TABLE_NAME)
TABLE_AGENTS = os.environ.get("TABLE_AGENTS", "buyersboard_agents")
AGENTS_TABLE = DDB.Table(TABLE_AGENTS)
JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")

GSI_NAME = "zip_prefix_created_index"
DEFAULT_LIMIT = int(os.environ.get("LIST_LIMIT", "24"))
BETA_ACCESS_FIELDS = (
    "status",
    "plan_name",
    "monthly_price",
    "verticals",
    "markets",
    "zip_codes",
    "zip_prefixes",
    "sms_enabled",
    "phone",
)

LIGHT_KEYS = (
    "lead_id",
    "id",
    "zip",
    "zip_prefix",
    "price",
    "status",
    "created_ts",
    "beds",
    "baths",
    "email",
    "name",
    "source",
    "source_url",
    "intent",
    "message",
    "description",
    "notes",
    "title",
    "city",
    "state",
    "role",
    "first_name",
    "last_name",
    "phone",
    "created_at",
    "market",
    "vertical",
    "lead_type",
    "urgency",
    "summary",
    "original_text",
    "source_post_date",
    "review_status",
    "published",
    "candidate_id",
)

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

def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    return base64.urlsafe_b64decode(padded.encode("utf-8"))

def _jwt_decode(token: str, secret: str) -> Optional[Dict[str, Any]]:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        signature = _b64url_decode(sig_b64)
        expected = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(time.time()) >= int(payload.get("exp", 0)):
            return None
        return payload
    except Exception:
        return None

def _bearer_token(event: Dict[str, Any]) -> Optional[str]:
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    if not auth.lower().startswith("bearer "):
        raise ValueError("invalid authorization header")
    token = auth.split(" ", 1)[1].strip()
    if not token:
        raise ValueError("invalid authorization header")
    return token

def _agent_from_token(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    token = _bearer_token(event)
    if not token:
        return None
    secret = SSM.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]
    payload = _jwt_decode(token, secret)
    if not payload:
        raise PermissionError("invalid bearer token")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise PermissionError("invalid bearer token")
    resp = AGENTS_TABLE.query(
        IndexName="email_index",
        KeyConditionExpression=Key("email").eq(email),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        raise PermissionError("agent not found")
    return items[0]

def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "S" in value:
            return str(value.get("S") or "").strip()
        if "N" in value:
            return str(value.get("N") or "").strip()
        if "BOOL" in value:
            return "true" if value.get("BOOL") else "false"
    return str(value).strip()

def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, set)):
        return not any(not _is_blank(item) for item in value)
    if isinstance(value, dict):
        if "S" in value or "N" in value or "BOOL" in value:
            return not _scalar(value)
        if "SS" in value or "NS" in value:
            return not value.get("SS") and not value.get("NS")
        if "L" in value:
            return _is_blank(value.get("L"))
    return False

def _split_tokens(value: Any) -> list[str]:
    if _is_blank(value):
        return []
    if isinstance(value, dict):
        if "SS" in value:
            return _split_tokens(value.get("SS"))
        if "NS" in value:
            return _split_tokens(value.get("NS"))
        if "L" in value:
            return _split_tokens(value.get("L"))
        return _split_tokens(_scalar(value))
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_split_tokens(item))
        return out
    text = _scalar(value)
    parts = [part.strip() for part in text.replace(";", ",").split(",")]
    return [part for part in parts if part]

def _normalized_set(value: Any) -> set[str]:
    return {part.lower() for part in _split_tokens(value)}

def _agent_has_beta_fields(agent: Optional[Dict[str, Any]]) -> bool:
    if not agent:
        return False
    return any(field in agent and not _is_blank(agent.get(field)) for field in BETA_ACCESS_FIELDS)

def _customer_access(agent: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not _agent_has_beta_fields(agent):
        return None
    status = _scalar(agent.get("status")).lower() if agent else ""
    if status and status != "active":
        return {"active": False}
    return {
        "active": True,
        "verticals": _normalized_set(agent.get("verticals")),
        "markets": _normalized_set(agent.get("markets")),
        "zip_codes": _normalized_set(agent.get("zip_codes")),
        "zip_prefixes": _normalized_set(agent.get("zip_prefixes")),
    }

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

def _and_filter(existing, cond):
    return cond if existing is None else (existing & cond)

def _customer_visible_filter():
    approved_candidate = Attr("review_status").eq("approved") & Attr("published").eq(True)
    legacy_non_candidate = Attr("candidate_id").not_exists()
    return legacy_non_candidate | approved_candidate

def _approved_published_filter():
    return Attr("review_status").eq("approved") & Attr("published").eq(True)

def _approved_published_candidate_filter():
    return Attr("candidate_id").exists() & _approved_published_filter()

def _lead_value(item: Dict[str, Any], *fields: str) -> str:
    for field in fields:
        value = item.get(field)
        text = _scalar(value)
        if text:
            return text.lower()
    return ""

def _matches_one(value: str, allowed: set[str]) -> bool:
    return not allowed or bool(value and value in allowed)

def _matches_market(item: Dict[str, Any], allowed: set[str]) -> bool:
    if not allowed:
        return True
    values = {
        _lead_value(item, "market"),
        _lead_value(item, "market_slug"),
    }
    return any(value in allowed for value in values if value)

def _matches_customer_access(item: Dict[str, Any], access: Optional[Dict[str, Any]]) -> bool:
    if access is None:
        return True
    if not access.get("active"):
        return False
    vertical = _lead_value(item, "vertical")
    zip_code = _lead_value(item, "zip")
    zip_prefix = _lead_value(item, "zip_prefix")
    if not zip_prefix and zip_code:
        zip_prefix = zip_code[:3]
    return (
        _matches_one(vertical, access.get("verticals", set()))
        and _matches_market(item, access.get("markets", set()))
        and _matches_one(zip_code, access.get("zip_codes", set()))
        and _matches_one(zip_prefix, access.get("zip_prefixes", set()))
    )

def handler(event, context):
    try:
        try:
            agent = _agent_from_token(event)
        except PermissionError as exc:
            return _resp(401, {"error": str(exc)})
        except ValueError as exc:
            return _resp(401, {"error": str(exc)})

        access = _customer_access(agent)
        if access is not None and not access.get("active"):
            return _resp(200, {"items": [], "next_cursor": None})

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

        # Beta customers see only approved/published leads; unrestricted callers keep legacy visibility.
        filt = _approved_published_candidate_filter() if access is not None else _customer_visible_filter()
        if status:
            filt = _and_filter(filt, Attr("status").eq(status))
        if min_price is not None:
            filt = _and_filter(filt, Attr("price").gte(min_price))
        if max_price is not None:
            filt = _and_filter(filt, Attr("price").lte(max_price))
        if zip_code:
            filt = _and_filter(filt, Attr("zip").eq(zip_code))

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

        raw_items = resp.get("Items", [])
        if access is not None:
            raw_items = [item for item in raw_items if _matches_customer_access(item, access)]
        items = [_light(i) for i in raw_items]
        next_cursor = _b64(resp.get("LastEvaluatedKey"))

        return _resp(200, {"items": items, "next_cursor": next_cursor})

    except Exception as e:
        # Surface the exception for now to speed up debugging
        return _resp(500, {"error": str(e), "type": e.__class__.__name__})
