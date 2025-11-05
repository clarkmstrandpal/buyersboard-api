
import os, json, boto3
from common.resp import response

dynamodb = boto3.resource("dynamodb")

def handler(event, context):
    params = event.get("queryStringParameters") or {}
    limit = int((params.get("limit") or 20))
    dbc = boto3.client("dynamodb")
    scan = dbc.scan(TableName=os.environ["TABLE_LEADS"], Limit=limit)
    items = scan.get("Items", [])
    def simplify(item):
        out = {}
        for k,v in item.items():
            if "S" in v: out[k] = v["S"]
            elif "N" in v: out[k] = float(v["N"])
            elif "BOOL" in v: out[k] = bool(v["BOOL"])
            else: out[k] = v
        return out
    return response(200, {"items": [simplify(i) for i in items]})
