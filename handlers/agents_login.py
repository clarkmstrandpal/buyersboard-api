import json, os, time, base64, hashlib, boto3, jwt
from boto3.dynamodb.conditions import Attr

DDB = boto3.resource("dynamodb")
SSM = boto3.client("ssm")

TABLE_NAME = os.getenv("TABLE_AGENTS", "buyersboard_agents")
JWT_SECRET_PARAM = os.getenv("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 16384, 8, 1, 64

def _json(status, body, headers=None):
    hdrs = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "Content-Type,Authorization",
        "Access-Control-Allow-Methods": "POST,OPTIONS"
    }
    if headers: hdrs.update(headers)
    return {"statusCode": status, "headers": hdrs, "body": json.dumps(body)}

def _b64dec(s: str) -> bytes: return base64.b64decode(s.encode("utf-8"))

def _get_jwt_secret():
    return SSM.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]

def _load_agent_by_email(email: str):
    t = DDB.Table(TABLE_NAME)
    try:
        got = t.get_item(Key={"email": email})
        if "Item" in got and got["Item"]: return got["Item"]
    except Exception: pass
    scan = t.scan(FilterExpression=Attr("email").eq(email))
    items = scan.get("Items", [])
    return items[0] if items else None

def _verify_scrypt(password: str, salt_b64: str, hash_b64: str) -> bool:
    salt = _b64dec(salt_b64); expected = _b64dec(hash_b64)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    try:    return hashlib.compare_digest(derived, expected)
    except: return derived == expected

def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _json(200, {"ok": True})
    try:
        body = json.loads(event.get("body") or "{}")
        email = (body.get("email") or "").strip().lower()
        password = body.get("password") or ""
    except Exception:
        return _json(400, {"error": "invalid json"})
    if not email or not password:
        return _json(400, {"error": "missing email or password"})

    agent = _load_agent_by_email(email)
    if not agent: return _json(401, {"error": "invalid credentials"})

    salt_b64, hash_b64 = agent.get("scrypt_salt"), agent.get("scrypt_hash")
    if not (salt_b64 and hash_b64): return _json(401, {"error": "invalid credentials"})
    if not _verify_scrypt(password, salt_b64, hash_b64): return _json(401, {"error": "invalid credentials"})

    secret = _get_jwt_secret()
    now = int(time.time())
    token = jwt.encode({"sub": email, "iat": now, "exp": now + 7*24*3600}, secret, algorithm="HS256")
    return _json(200, {"token": token, "email": email})
