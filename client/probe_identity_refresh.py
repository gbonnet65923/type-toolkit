import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")
import type_client

state = type_client.load_profile()
cfg = type_client.discover()
rt = state.get("refreshToken")
rt = rt.get("value") if isinstance(rt, dict) else rt
print("refreshToken:", rt[:20] + "…")

req = urllib.request.Request(
    cfg["identity_endpoint"],
    data=json.dumps({"refresh_token": rt, "type": "refresh"}).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "type-cli/rev (python)"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30, context=type_client._CTX) as r:
        body = json.load(r)
        print("identity refresh -> 200:", json.dumps(body, ensure_ascii=False)[:500])
        identity = body.get("identity") or {}
        assertion = identity.get("assertion")
        if assertion:
            state2 = dict(state)
            state2["assertion"] = assertion
            new_rt = identity.get("refresh_token")
            if new_rt:
                state2["refreshToken"] = new_rt
            state2 = type_client.exchange(cfg, state2)
            type_client.save_profile(state2)
            print("re-exchange OK; expires_at:", state2["expiresAt"])
            st, me = type_client.orpc_call(state2, "cli/context/me")
            print("orpc context/me ->", st, json.dumps(me, ensure_ascii=False)[:300])
except urllib.error.HTTPError as e:
    print("identity refresh ->", e.code, e.read().decode()[:300])
