import os, base64, hashlib, boto3
region      = os.environ["REGION"]
table_name  = os.environ["TABLE"]
email       = os.environ["EMAIL"]
password    = os.environ["PASSWORD"]
SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 16384, 8, 1, 64

ddb = boto3.resource("dynamodb", region_name=region)
t = ddb.Table(table_name)

# find or create record by email (scan if PK differs)
try:
    got = t.get_item(Key={"email": email})
    item = got.get("Item")
except Exception:
    item = None
if not item:
    scan = t.scan(FilterExpression=boto3.dynamodb.conditions.Attr("email").eq(email))
    it = scan.get("Items", [])
    item = it[0] if it else {"email": email}

salt = os.urandom(16)
hashv = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
item["scrypt_salt"] = base64.b64encode(salt).decode("utf-8")
item["scrypt_hash"] = base64.b64encode(hashv).decode("utf-8")
item.pop("password_plain", None)

t.put_item(Item=item)
print("OK")
