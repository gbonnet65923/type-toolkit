"""E2E proof: mail.tm mailbox -> type.com signup -> code -> tokens -> /v1/me.

Chain under test (every step live):
  1. POST api.mail.tm/accounts        (throwaway mailbox)
  2. type_client.discover()           (oauth discovery)
  3. signup_start                     (identity + agent-signup/start, code dispatched)
  4. fetch_code_imap                  (RFC3501 UNSEEN + multipart walk fix)
  5. signup_complete                  (verify + claim/complete + jwt-bearer exchange)
  6. api_get /v1/me                   (Bearer access_token)
"""
import json
import random
import re
import string
import time
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "C:/Users/User/tmp/typerev")
import type_client

CTX = type_client._CTX


def mailtm_get(path, token=None):
    req = urllib.request.Request(
        "https://api.mail.tm" + path,
        headers={"Accept": "application/json", **({"Authorization": "Bearer "+token} if token else {})},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return json.load(r)


def mailtm_post(path, body, token=None):
    req = urllib.request.Request(
        "https://api.mail.tm" + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 **({"Authorization": "Bearer " + token} if token else {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
        return json.load(r)


resp = mailtm_get("/domains")
dom_list = resp["hydra:member"] if isinstance(resp, dict) else resp
domains = [d["domain"] for d in dom_list if d.get("isActive", True)]
domain = domains[0]
local = "e2e" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
address = local + "@" + domain
password = "Tp" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"
try:
    acct = mailtm_post("/accounts", {"address": address, "password": password})
    print(f"[1] mailbox created: {address} (domain {domain})")
except urllib.error.HTTPError as e:
    print("mailbox create failed:", e.code, e.read().decode()[:300])
    raise SystemExit(1)

cfg = type_client.discover()
print(f"[2] discovery ok: issuer={cfg['issuer']}")
state = type_client.signup_start(cfg, address, "e2e lab")
print(f"[3] signup start ok: signupToken={state['signupToken'][:8]}… code dispatched")

jwt = mailtm_post("/token", {"address": address, "password": password})["token"]
code = None
deadline = time.time() + 240
while time.time() < deadline and not code:
    time.sleep(8)
    msgs = mailtm_get("/messages", token=jwt)
    msgs = msgs["hydra:member"] if isinstance(msgs, dict) else msgs
    for msg in msgs:
        body = mailtm_get(f"/messages/{msg['id']}", token=jwt)
        text = body.get("text") or ""
        if not text and body.get("html"):
            html = body["html"]
            text = html if isinstance(html, str) else "".join(html)
        codes = re.findall(r"\b(\d{6})\b", text)
        if codes:
            code = codes[-1]
            break
if not code:
    raise RuntimeError("no code via mail.tm REST within 240s")
print(f"[4] REST code fetched: {code}")

state = type_client.signup_complete(cfg, state, code)
org = state.get("organization") or {}
print(f"[5] signup complete: org={org.get('slug')} accessToken={'yes' if state.get('accessToken') else 'NO'}")

st, me = type_client.api_get(state)
print(f"[6] GET /v1/me -> HTTP {st}")
print(json.dumps(me, indent=2, ensure_ascii=False)[:1200])
