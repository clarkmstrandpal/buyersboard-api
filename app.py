# ==== BEGIN CORS SHIM (appended by setup) ====
try:
    import json as _json
except Exception:
    import json as _json  # fallback same, keeps linter happy

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS"
}

def _cors_json_resp(status: int, body=None, headers: dict | None = None):
    base = {"Content-Type": "application/json", **_CORS_HEADERS}
    if headers:
        base.update(headers)
    if status == 204 or body is None:
        return {"statusCode": status, "headers": base, "body": ""}
    return {"statusCode": status, "headers": base, "body": _json.dumps(body)}

# If the file already defines json_resp, leave it; else provide one.
if "json_resp" not in globals():
    json_resp = _cors_json_resp  # expose as json_resp for the app to use

def _wrap_with_cors(fn):
    def _inner(event, context):
        # Normalize method across REST/HTTP APIs
        method = ""
        try:
            method = (event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method") or "").upper()
        except Exception:
            method = ""
        # Handle preflight
        if method == "OPTIONS":
            return _cors_json_resp(200, {})
        # Call original
        resp = fn(event, context)
        # Ensure CORS headers on any dict response
        if isinstance(resp, dict):
            hdrs = dict(resp.get("headers") or {})
            for k, v in _CORS_HEADERS.items():
                hdrs[k] = v
            resp["headers"] = hdrs
        return resp
    return _inner

# If `handler` exists, wrap it. If not yet defined, we try a late bind at import time.
try:
    if callable(handler):
        handler = _wrap_with_cors(handler)
except NameError:
    # Late-binding guard: if handler is defined later, it can do:
    #   handler = _wrap_with_cors(handler)
    pass
# ==== END CORS SHIM ====

