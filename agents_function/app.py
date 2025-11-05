import os, json, base64, time, hmac, hashlib
import boto3

ddb = boto3.client("dynamodb")
ssm = boto3.client("ssm")

TABLE_AGENTS = os.environ.get("TABLE_AGENTS", "buyersboard_agents")
JWT_SECRET_PARAM = os.environ.get("JWT_SECRET_PARAM", "/buyersboard/dev/jwt_secret")

def _b64url(x: bytes) -> str:
    return base64.urlsafe_b64encode(x).decode().rstrip("=")
def _b64url_json(obj) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":")).encode())
def jwt_encode(payload: dict, secret: str) -> str:
    header = {"alg":"HS256","typ":"JWT"}
    signing_input = f"{_b64url_json(header)}.{_b64url_json(payload)}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig)
def jwt_decode(token: str, secret: str):
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        expected = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload_json = base64.urlsafe_b64decode(payload_b64 + "==").decode()
        return json.loads(payload_json)
    except Exception:
        return None

def get_jwt_secret():
    return ssm.get_parameter(Name=JWT_SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]

def get_agent_by_email(email: str):
    resp = ddb.query(
        TableName=TABLE_AGENTS,
        IndexName="email_index",
        KeyConditionExpression="email = :e",
        ExpressionAttributeValues={":e": {"S": email}},
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None

def scrypt_verify(password: str, salt_b64url: str, n:int, r:int, p:int, expected_b64url: str) -> bool:
    dk = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt_b64url+"=="), n=n, r=r, p=p, dklen=32)
    calc = base64.urlsafe_b64encode(dk).decode().rstrip("=")
    return hmac.compare_digest(calc, expected_b64url)

def json_resp(code: int, body: dict):
    return {"statusCode": code, "headers":{"content-type":"application/json","access-control-allow-origin":"*"}, "body": json.dumps(body)}

def route_login(event):
    body = json.loads(event.get("body") or "{}")
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    if not email or not password:
        return json_resp(400, {"error":"email and password required"})

    item = get_agent_by_email(email)
    if not item:
        time.sleep(0.2)
        return json_resp(401, {"error":"invalid credentials"})

    salt = item["password_salt"]["S"]
    sN = int(item["scrypt_n"]["N"]); sR = int(item["scrypt_r"]["N"]); sP = int(item["scrypt_p"]["N"])
    expected = item["password_scrypt"]["S"]
    if not scrypt_verify(password, salt, sN, sR, sP, expected):
        time.sleep(0.2)
        return json_resp(401, {"error":"invalid credentials"})

    agent_id = item["agent_id"]["S"]
    now = int(time.time())
    exp = now + 60*60*12
    secret = get_jwt_secret()
    token = jwt_encode({"sub":agent_id,"email":email,"iat":now,"exp":exp}, secret)
    return json_resp(200, {"token": token, "agent_id": agent_id, "email": email})

def route_me(event):
    headers = event.get("headers") or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return json_resp(401, {"error":"missing bearer token"})
    token = auth.split(" ",1)[1].strip()
    secret = get_jwt_secret()
    payload = jwt_decode(token, secret)
    if not payload:
        return json_resp(401, {"error":"invalid token"})
    if int(time.time()) >= int(payload.get("exp", 0)):
        return json_resp(401, {"error":"token expired"})
    return json_resp(200, {"sub":payload.get("sub"), "email":payload.get("email")})

def handler(event, context):
    route = (event.get("requestContext") or {}).get("http", {}).get("path") or event.get("rawPath") or ""
    method = (event.get("requestContext") or {}).get("http", {}).get("method") or (event.get("requestContext",{}).get("httpMethod") or "")
    route = route.lower(); method = method.upper()
    if route.endswith("/v1/agents/login") and method == "POST":
        return route_login(event)
    if route.endswith("/v1/agents/me") and method == "GET":
        return route_me(event)
    return json_resp(404, {"error":"not found"})