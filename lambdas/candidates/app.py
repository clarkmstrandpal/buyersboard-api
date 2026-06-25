import base64
import datetime
import hashlib
import hmac
import json
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
from boto3.dynamodb.conditions import Attr, Key

from common.resp import err, ok  # type: ignore


JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")
VALID_STATUSES = {"new", "good", "maybe", "rejected", "duplicate", "sent", "archived"}
ACTION_STATUS = {
    "good": "good",
    "maybe": "maybe",
    "rejected": "rejected",
    "duplicate": "duplicate",
    "archive": "archived",
    "archived": "archived",
}
LIST_FILTERS = (
    "market_slug",
    "market",
    "county",
    "city",
    "zip",
    "state",
    "source",
    "status",
    "intent_guess",
    "role_guess",
)


ddb = boto3.resource("dynamodb")
ssm = boto3.client("ssm")


def _origin() -> str:
    return os.environ.get("CORS_ORIGIN", "*")


def _candidates_table():
    name = os.environ.get("TABLE_CANDIDATES")
    if not name:
        raise RuntimeError("TABLE_CANDIDATES env var not set")
    return ddb.Table(name)


def _leads_table():
    name = os.environ.get("TABLE_LEADS")
    if not name:
        raise RuntimeError("TABLE_LEADS env var not set")
    return ddb.Table(name)


def _now() -> Tuple[str, int]:
    ts = int(time.time())
    at = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    return at, ts


def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _parse_body(event: Dict[str, Any]) -> Any:
    body = event.get("body")
    if body is None:
        return {}
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, str):
        body = body.strip()
        if not body:
            return {}
        return json.loads(body)
    return body


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


def _require_agent(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    secret = ssm.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]
    return _jwt_decode(token, secret)


def _cursor_to_key(cursor: Optional[str]) -> Optional[Dict[str, Any]]:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        return json.loads(raw, parse_float=Decimal)
    except Exception:
        return None


def _key_to_cursor(key: Optional[Dict[str, Any]]) -> Optional[str]:
    if not key:
        return None
    raw = json.dumps(_json_safe(key), separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value % 1 == 0:
            return int(value)
        return float(value)
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _filter_empty(item: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in item.items() if v is not None and v != ""}


def _normalize_candidate(raw: Dict[str, Any]) -> Dict[str, Any]:
    created_at, created_ts = _now()
    candidate_id = _to_str(raw.get("candidate_id")) or str(uuid.uuid4())
    status = (_to_str(raw.get("status")) or "new").lower()
    if status not in VALID_STATUSES:
        status = "new"

    item: Dict[str, Any] = {
        "candidate_id": candidate_id,
        "title": _to_str(raw.get("title")),
        "snippet": _to_str(raw.get("snippet")),
        "message": _to_str(raw.get("message")),
        "source": _to_str(raw.get("source")),
        "source_url": _to_str(raw.get("source_url")),
        "market": _to_str(raw.get("market")),
        "market_slug": _to_str(raw.get("market_slug")),
        "county": _to_str(raw.get("county")),
        "city": _to_str(raw.get("city")),
        "state": _to_str(raw.get("state")),
        "zip": _to_str(raw.get("zip")),
        "role_guess": _to_str(raw.get("role_guess")),
        "intent_guess": _to_str(raw.get("intent_guess")),
        "intent_score": _to_decimal(raw.get("intent_score")),
        "search_query": _to_str(raw.get("search_query")),
        "contact_method": _to_str(raw.get("contact_method")),
        "status": status,
        "review_notes": _to_str(raw.get("review_notes")),
        "created_at": _to_str(raw.get("created_at")) or created_at,
        "created_ts": int(raw.get("created_ts") or created_ts),
        "reviewed_at": _to_str(raw.get("reviewed_at")),
        "promoted_lead_id": _to_str(raw.get("promoted_lead_id")),
    }
    return _filter_empty(item)


def _import_items(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("items", [])
    else:
        raise ValueError("body must be a JSON array or an object with items")
    if not isinstance(items, list):
        raise ValueError("items must be a JSON array")
    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each candidate item must be an object")
        out.append(item)
    return out


def _find_by_source_url(source_url: Optional[str]) -> Optional[Dict[str, Any]]:
    if not source_url:
        return None
    resp = _candidates_table().query(
        IndexName="source_url_index",
        KeyConditionExpression=Key("source_url").eq(source_url),
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


def _import(event: Dict[str, Any]) -> Dict[str, Any]:
    payload = _parse_body(event)
    raw_items = _import_items(payload)
    table = _candidates_table()

    imported_count = 0
    duplicate_count = 0
    error_count = 0
    results: List[Dict[str, Any]] = []

    for index, raw in enumerate(raw_items, start=1):
        try:
            item = _normalize_candidate(raw)
            existing = _find_by_source_url(item.get("source_url"))
            if existing:
                duplicate_count += 1
                results.append(
                    {
                        "row": index,
                        "status": "duplicate",
                        "candidate_id": existing.get("candidate_id"),
                        "source_url": item.get("source_url"),
                    }
                )
                continue

            table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(candidate_id)",
            )
            imported_count += 1
            results.append(
                {
                    "row": index,
                    "status": "imported",
                    "candidate_id": item["candidate_id"],
                    "source_url": item.get("source_url"),
                }
            )
        except Exception as exc:
            error_count += 1
            results.append({"row": index, "status": "error", "error": str(exc)})

    return ok(
        _json_safe(
            {
                "imported_count": imported_count,
                "duplicate_count": duplicate_count,
                "error_count": error_count,
                "items": results,
            }
        ),
        _origin(),
    )


def _build_filter(params: Dict[str, str], skip: Iterable[str] = ()) -> Any:
    filt = None
    skip_set = set(skip)
    for field in LIST_FILTERS:
        if field in skip_set:
            continue
        value = _to_str(params.get(field))
        if value:
            cond = Attr(field).eq(value)
            filt = cond if filt is None else filt & cond
    return filt


def _list(event: Dict[str, Any]) -> Dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    limit = min(max(int(qs.get("limit") or 50), 1), 100)
    cursor = _cursor_to_key(qs.get("cursor") or qs.get("next_cursor"))
    table = _candidates_table()
    market_slug = _to_str(qs.get("market_slug"))

    if market_slug:
        kwargs: Dict[str, Any] = {
            "IndexName": "market_slug_created_index",
            "KeyConditionExpression": Key("market_slug").eq(market_slug),
            "Limit": limit,
            "ScanIndexForward": False,
        }
        filt = _build_filter(qs, skip=("market_slug",))
    else:
        kwargs = {"Limit": limit}
        filt = _build_filter(qs)

    if cursor:
        kwargs["ExclusiveStartKey"] = cursor
    if filt is not None:
        kwargs["FilterExpression"] = filt

    resp = table.query(**kwargs) if market_slug else table.scan(**kwargs)
    items = resp.get("Items", [])
    if not market_slug:
        items.sort(key=lambda x: x.get("created_ts", 0), reverse=True)

    return ok(
        _json_safe({"items": items[:limit], "next_cursor": _key_to_cursor(resp.get("LastEvaluatedKey"))}),
        _origin(),
    )


def _candidate_to_lead(candidate: Dict[str, Any]) -> Dict[str, Any]:
    lead_id = str(uuid.uuid4())
    created_at, created_ts = _now()
    zip_code = _to_str(candidate.get("zip")) or "00000"
    message = _to_str(candidate.get("message")) or _to_str(candidate.get("snippet"))
    item = {
        "id": lead_id,
        "email": f"missing+{lead_id}@placeholder.listlyhomes.local",
        "zip": zip_code[:10],
        "zip_prefix": zip_code[:3],
        "created_ts": created_ts,
        "created_at": created_at,
        "status": "new",
        "source": _to_str(candidate.get("source")) or "discovery_inbox_v0",
        "source_url": _to_str(candidate.get("source_url")),
        "title": _to_str(candidate.get("title")),
        "message": message,
        "description": _to_str(candidate.get("snippet")),
        "city": _to_str(candidate.get("city")),
        "state": _to_str(candidate.get("state")),
        "role": _to_str(candidate.get("role_guess")),
        "intent": _to_str(candidate.get("intent_guess")),
        "contact_method": _to_str(candidate.get("contact_method")),
        "candidate_id": candidate.get("candidate_id"),
    }
    return _filter_empty(item)


def _action(event: Dict[str, Any]) -> Dict[str, Any]:
    body = _parse_body(event)
    if not isinstance(body, dict):
        return err("body must be a JSON object", 400, _origin())

    candidate_id = _to_str(body.get("candidate_id"))
    action = _to_str(body.get("action"))
    if not candidate_id:
        return err("candidate_id is required", 400, _origin())
    if not action:
        return err("action is required", 400, _origin())

    table = _candidates_table()
    resp = table.get_item(Key={"candidate_id": candidate_id})
    candidate = resp.get("Item")
    if not candidate:
        return err("candidate not found", 404, _origin())

    reviewed_at, _ = _now()
    review_notes = _to_str(body.get("review_notes"))

    promoted_lead_id = candidate.get("promoted_lead_id")
    if action == "send_to_leads":
        if not promoted_lead_id:
            lead = _candidate_to_lead(candidate)
            _leads_table().put_item(Item=lead)
            promoted_lead_id = lead["id"]
        new_status = "sent"
    elif action in ACTION_STATUS:
        new_status = ACTION_STATUS[action]
    else:
        return err("unsupported action", 400, _origin())

    expr_names = {"#status": "status"}
    expr_values = {":status": new_status, ":reviewed_at": reviewed_at}
    update_expr = "SET #status = :status, reviewed_at = :reviewed_at"

    if review_notes is not None:
        update_expr += ", review_notes = :review_notes"
        expr_values[":review_notes"] = review_notes
    if promoted_lead_id:
        update_expr += ", promoted_lead_id = :promoted_lead_id"
        expr_values[":promoted_lead_id"] = promoted_lead_id

    updated = table.update_item(
        Key={"candidate_id": candidate_id},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
        ReturnValues="ALL_NEW",
    )["Attributes"]

    return ok(_json_safe({"candidate": updated, "promoted_lead_id": promoted_lead_id}), _origin())


def handler(event, context):
    origin = _origin()
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return ok({"preflight": True}, origin)

    path = event.get("rawPath") or event.get("path") or ""
    try:
        if not _require_agent(event):
            return err("missing or invalid bearer token", 401, origin)
        if method == "POST" and path.endswith("/v1/candidates/import"):
            return _import(event)
        if method == "GET" and path.endswith("/v1/candidates/list"):
            return _list(event)
        if method == "POST" and path.endswith("/v1/candidates/action"):
            return _action(event)
        return err("not found", 404, origin)
    except ValueError as exc:
        return err(str(exc), 400, origin)
    except Exception as exc:
        print("ERROR:", repr(exc))
        return err(str(exc), 500, origin)
