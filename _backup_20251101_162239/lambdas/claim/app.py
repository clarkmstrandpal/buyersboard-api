
import os, json, boto3, uuid, time
from common.resp import response

dynamodb = boto3.resource("dynamodb")
claims = dynamodb.Table(os.environ["TABLE_CLAIMS"])

def handler(event, context):
    if event.get("httpMethod") != "POST":
        return response(405, {"error":"method not allowed"})
    data = json.loads(event.get("body") or "{}")
    item = {
        "claim_id": data.get("claim_id") or str(uuid.uuid4()),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lead_id": data.get("lead_id"),
        "notes": data.get("notes",""),
        "status": "new"
    }
    claims.put_item(Item=item)
    return response(200, {"ok": True, "claim_id": item["claim_id"]})
