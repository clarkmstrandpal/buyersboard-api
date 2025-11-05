import os, base64, hashlib, boto3
from boto3.dynamodb.conditions import Attr

region      = os.environ["REGION"]
table_name  = "buyersboard_agents"
targets     = [
    (os.environ.get("EMAIL1"), os.environ.get("PASS1")),
    (os.environ.get("EMAIL2"), os.environ.get("PASS2")),
]
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 16384, 8, 1, 64

ddb = boto3.resource("dynamodb", region_name=region)
t = ddb.Table(table_name)

def upsert(email, password):
    if not email or not password: return
    # Try PK
    try:
        got = t.get_item(Key={"email": email})
        item = got.get("Item")
    except Exception:
        item = None
    if not item:
        scan = t.scan(FilterExpression=Attr("email").eq(email))
        arr = scan.get("Items", [])
        item = arr[0] if arr else {"email": email}
    salt = os.urandom(16)
    hashv = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    item["scrypt_salt"] = base64.b64encode(salt).decode("utf-8")
    item["scrypt_hash"] = base64.b64encode(hashv).decode("utf-8")
    item.pop("password_plain", None)
    item.pop("password_salt",  None)
    item.pop("password_hash",  None)
    t.put_item(Item=item)

for em,pw in targets: upsert(em,pw)
print("OK")
