
import hashlib, hmac, time

def verify_signature(body: bytes, timestamp: str, signature: str, secret: str, max_skew=300):
    if not timestamp or not signature or not secret:
        return False
    try:
        ts = int(timestamp)
    except Exception:
        return False
    if abs(int(time.time()) - ts) > max_skew:
        return False
    base = f"{timestamp}.{body.decode('utf-8')}"
    expected = hmac.new(secret.encode('utf-8'), base.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

def sign(body: str, secret: str):
    ts = str(int(time.time()))
    base = f"{ts}.{body}"
    return ts, hmac.new(secret.encode('utf-8'), base.encode('utf-8'), hashlib.sha256).hexdigest()
