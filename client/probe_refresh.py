import json
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, ".")
import type_client

state = type_client.load_profile()
form = {
    "client_id": state.get("clientId") or "client_01K5GFDDKQWV8MM9FSRZS3YNNN",
    "grant_type": "refresh_token",
    "refresh_token": state["refreshToken"],
}
org = (state.get("organization") or {}).get("workosOrgId")
if org:
    form["organization_id"] = org
req = urllib.request.Request(
    "https://api.workos.com/user_management/authenticate",
    data=urllib.parse.urlencode(form).encode(),
    headers={"Content-Type": "application/x-www-form-urlencoded"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30, context=type_client._CTX) as r:
        body = json.load(r)
        print("refresh @workos -> 200:", {k: (v[:24] + "…" if isinstance(v, str) and len(v) > 24 else v) for k, v in body.items()})
        # try the fresh token against the oRPC API
        tok = body["access_token"]
        req2 = urllib.request.Request(
            "https://api.type.com/api/orpc/cli/context/me",
            data=json.dumps({"json": {}}).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + tok,
                "User-Agent": "TypeCLI/rev",
                "x-type-cli-version": "0.0.0",
            },
        )
        with urllib.request.urlopen(req2, timeout=30, context=type_client._CTX) as r2:
            print("orpc context/me ->", r2.status, r2.read().decode()[:400])
except urllib.error.HTTPError as e:
    print("refresh @workos ->", e.code, e.read().decode()[:300])
