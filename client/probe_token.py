import base64
import json
import sys

sys.path.insert(0, ".")
import type_client

state = type_client.load_profile()
cfg = type_client.discover()
state = type_client.exchange(cfg, state)
tok = state["accessToken"]
seg = tok.split(".")[1]
seg += "=" * (-len(seg) % 4)
payload = json.loads(base64.urlsafe_b64decode(seg))
print(json.dumps(payload, indent=2)[:900])
print("scopes in state identity:", "refreshToken" if state.get("refreshToken") else "none")

# WorkOS refresh_token grant (identity refresh token from claim/complete)
import urllib.error
import urllib.parse
import urllib.request

form = {
    "client_id": state.get("clientId") or "client_01K5GFDDKQWV8MM9FSRZS3YNNN",
    "grant_type": "refresh_token",
    "refresh_token": state["refreshToken"],
}
req = urllib.request.Request(
    "https://auth.type.com/oauth2/token",
    data=urllib.parse.urlencode(form).encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30, context=type_client._CTX) as r:
        body = json.load(r)
        print("refresh via issuer -> 200:", {k: (v[:20] + "…" if isinstance(v, str) and len(v) > 20 else v) for k, v in body.items()})
except urllib.error.HTTPError as e:
    print("refresh via issuer ->", e.code, e.read().decode()[:200])
