
import os, json, time, boto3, uuid
from common.resp import response
from common.ssm import get_json_param

dynamodb = boto3.resource("dynamodb")
sendlog = dynamodb.Table(os.environ["TABLE_SENDLOG"])

def handler(event, context):
    if event.get("httpMethod") != "POST":
        return response(405, {"error":"method not allowed"})
    routes = get_json_param(os.environ["SLACK_ROUTE_PARAM"])
    data = json.loads(event.get("body") or "{}")
    category = (data.get("category") or "default").lower()
    target = routes.get(category, routes.get("default"))
    audit = {
        "log_id": str(uuid.uuid4()),
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "category": category,
        "target": target,
        "payload": data
    }
    sendlog.put_item(Item=audit)
    return response(200, {"routed": True, "category": category})
