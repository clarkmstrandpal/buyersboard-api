
import json, time
def handler(event, context):
    return {"statusCode":200, "body": json.dumps({"ok": True, "generated_at": time.time()})}
