# lambdas/lead_finder_import/app.py
import base64
import csv
import datetime
import io
import json
import os
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import boto3

from common.resp import ok, err  # type: ignore

MAX_IMPORT_ROWS = int(os.environ.get("MAX_IMPORT_ROWS", "100"))
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
FORM_FIELDS = (
    "first_name",
    "last_name",
    "name",
    "email",
    "phone",
    "zip",
    "price",
    "beds",
    "baths",
    "notes",
    "status",
    "source",
)
IMPORT_FIELDS = FORM_FIELDS + LEAD_FINDER_FIELDS


def _origin() -> str:
    return os.environ.get("CORS_ORIGIN", "*")


def _table():
    name = os.environ.get("TABLE_LEADS")
    if not name:
        raise RuntimeError("TABLE_LEADS env var not set")
    return boto3.resource("dynamodb").Table(name)


def _decode_body(event: Dict[str, Any]) -> str:
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    if isinstance(body, dict):
        return json.dumps(body)
    return str(body)


def _content_type(event: Dict[str, Any]) -> str:
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == "content-type":
            return str(value).lower()
    return ""


def _parse_json_payload(raw: str) -> List[Dict[str, Any]]:
    payload = json.loads(raw or "{}")
    if isinstance(payload, list):
        rows = payload
    else:
        rows = payload.get("leads") or payload.get("items") or payload.get("rows") or []
    if not isinstance(rows, list):
        raise ValueError("JSON import body must include a leads array")
    return [row for row in rows if isinstance(row, dict)]


def _parse_csv_payload(raw: str) -> List[Dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV import body must include a header row")
    return [dict(row) for row in reader]


def _parse_rows(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = _decode_body(event).strip()
    if not raw:
        return []
    content_type = _content_type(event)
    if "text/csv" in content_type or "application/csv" in content_type:
        return _parse_csv_payload(raw)
    if raw.startswith("{") or raw.startswith("["):
        return _parse_json_payload(raw)
    return _parse_csv_payload(raw)


def _to_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _to_int(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None


def _build_item(row: Dict[str, Any], import_id: str, row_number: int, created_ts: int, created_at: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    lead_id = str(uuid.uuid4())
    email = _to_str(row.get("email")) or f"missing+{lead_id}@placeholder.listlyhomes.local"
    zip_code = (_to_str(row.get("zip")) or "00000")[:10]
    source = _to_str(row.get("source")) or "lead_finder_import_v0"

    item: Dict[str, Any] = {
        "id": lead_id,
        "email": email,
        "zip": zip_code,
        "zip_prefix": zip_code[:3],
        "created_ts": created_ts,
        "created_at": created_at,
        "status": _to_str(row.get("status")) or "new",
        "source": source,
        "import_id": import_id,
        "import_row": row_number,
    }

    for field in ("first_name", "last_name", "name", "phone", "notes") + LEAD_FINDER_FIELDS:
        value = _to_str(row.get(field))
        if value is not None:
            item[field] = value

    price = _to_decimal(row.get("price"))
    beds = _to_int(row.get("beds"))
    baths = _to_int(row.get("baths"))
    if price is not None:
        item["price"] = price
    if beds is not None:
        item["beds"] = beds
    if baths is not None:
        item["baths"] = baths

    has_lead_content = any(_to_str(row.get(field)) for field in IMPORT_FIELDS)
    if not has_lead_content:
        return None, "empty row"
    return item, None


def _preview(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("id", "email", "zip", "status", "source", "source_url", "intent", "title", "city", "state", "import_row")
    return {key: item[key] for key in keys if key in item}


def lambda_handler(event, context):
    origin = _origin()
    method = event.get("requestContext", {}).get("http", {}).get("method")
    if method == "OPTIONS":
        return ok({"preflight": True}, origin)

    try:
        rows = _parse_rows(event)
        if not rows:
            return err("no import rows found", 400, origin)
        if len(rows) > MAX_IMPORT_ROWS:
            return err(f"too many rows: max {MAX_IMPORT_ROWS}", 400, origin)

        import_id = str(uuid.uuid4())
        created_ts = int(time.time())
        created_at = datetime.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        imported: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        table = _table()
        with table.batch_writer() as batch:
            for index, row in enumerate(rows, start=1):
                item, skip_reason = _build_item(row, import_id, index, created_ts + index, created_at)
                if item is None:
                    skipped.append({"row": index, "reason": skip_reason})
                    continue
                batch.put_item(Item=item)
                imported.append(_preview(item))

        return ok({"status": "ok", "import_id": import_id, "imported_count": len(imported), "skipped_count": len(skipped), "imported": imported, "skipped": skipped}, origin)
    except ValueError as exc:
        return err(str(exc), 400, origin)
    except Exception as exc:
        print("ERROR:", repr(exc))
        return err(str(exc), 500, origin)
