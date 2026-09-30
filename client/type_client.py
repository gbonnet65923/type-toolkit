#!/usr/bin/env python3
"""
type_client.py — protocol-level client for type.com (Type shared-agent platform).

Reversed from type-cli (Bun single-executable, `bun build --compile`):
  installer : https://type.com/install.sh -> https://desktop.type.com/cli/
  server    : https://api.type.com (prod) / https://api.typestaging.com (staging)
  identity  : WorkOS user_management (device + jwt-bearer + refresh_token grants)
  signup    : "service_auth" agent registration, 6-digit email code, NO BROWSER
  storage   : ~/.type/credentials/{profile}.json (CLI-compatible)

Zero dependencies (stdlib only). Python 3.9+.

Usage:
  python type_client.py discover
  python type_client.py signup --email me@mail.com --org "myteam"
  python type_client.py complete --code 123456
  python type_client.py status
  python type_client.py refresh
  python type_client.py me
  python type_client.py device-login
  python type_client.py batch --emails emails.txt --org "farm"  # IMAP hook below
"""
import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

SERVER = os.environ.get("TYPE_SERVER_URL", "https://api.type.com")
WORKOS_AUTHENTICATE_URL = "https://api.workos.com/user_management/authenticate"
WORKOS_DEVICE_AUTHORIZE_URL = "https://api.workos.com/user_management/authorize/device"
AGENT_TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
BUNDLED_WORKOS_CLIENT_ID = "client_01K5GFDDKQWV8MM9FSRZS3YNNN"  # extracted from CLI
CRED_DIR = os.path.join(
    os.environ.get("TYPE_CONFIG_DIR", os.path.join(os.path.expanduser("~"), ".type")),
    "credentials",
)
PROFILE = os.environ.get("TYPE_PROFILE", "default")

_CTX = ssl.create_default_context()
if os.environ.get("TYPE_INSECURE") == "1":
    _CTX.check_hostname = False
    _CTX.verify_mode = ssl.CERT_NONE


def _proxies():
    handlers = []
    proxy = os.environ.get("TYPE_PROXY")  # http://user:pass@host:port
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers) if handlers else None
    return opener


def http_json(method, url, body=None, form=None, token=None, expect=None):
    """JSON/form request -> (status, dict). Non-JSON responses become {"_raw": str}."""
    headers = {"User-Agent": "type-cli/rev (python)"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = _proxies()
    urlopen = opener.urlopen if opener else urllib.request.urlopen
    try:
        resp = urlopen(req, timeout=30, context=_CTX)
        raw = resp.read()
        status = resp.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    try:
        parsed = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(parsed, dict):
            parsed = {"_raw": parsed}
    except Exception:
        parsed = {"_raw": raw.decode("utf-8", "replace")}
    if expect is not None and status != expect:
        raise RuntimeError(f"{method} {url} -> {status}: {parsed}")
    return status, parsed


def load_profile():
    path = os.path.join(CRED_DIR, PROFILE + ".json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_profile(state):
    os.makedirs(CRED_DIR, exist_ok=True)
    path = os.path.join(CRED_DIR, PROFILE + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return path


# ---------------------------------------------------------------- discovery
def discover(server=SERVER):
    """RFC 8414 chain the CLI walks: protected-resource -> authorization server."""
    st, pr = http_json("GET", server + "/.well-known/oauth-protected-resource")
    if st != 200:
        raise RuntimeError(f"protected-resource discovery HTTP {st}: {pr}")
    issuer = (pr.get("authorization_servers") or [""])[0].rstrip("/")
    client_id = pr.get("type_workos_client_id") or BUNDLED_WORKOS_CLIENT_ID
    meta = None
    for well_known in (
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
    ):
        st, meta = http_json("GET", issuer + well_known)
        if st == 200 and isinstance(meta, dict):
            break
    if not isinstance(meta, dict) or "token_endpoint" not in meta:
        raise RuntimeError(f"authorization-server metadata not found on {issuer}")
    agent_auth = meta.get("agent_auth") or {}
    cfg = {
        "server": server,
        "issuer": issuer,
        "resource": (pr.get("resource") or server).rstrip("/"),
        "client_id": client_id,
        "token_endpoint": meta["token_endpoint"],
        "identity_endpoint": agent_auth.get("identity_endpoint"),
        "identity_types": agent_auth.get("identity_types_supported"),
    }
    return cfg


# ---------------------------------------------------------------- signup
def signup_start(cfg, email, org_name, state=None):
    """service_auth registration + agent-signup/start -> state saved, email code sent."""
    if not state:
        st, reg = http_json(
            "POST",
            cfg["identity_endpoint"],
            body={"login_hint": email, "type": "service_auth"},
            expect=200,
        )
        claim = reg.get("claim") or {}
        attempt = claim.get("attempt") or {}
        vuri = attempt.get("verification_uri") or ""
        claim_attempt_token = (
            (urllib.parse.parse_qs(urllib.parse.urlparse(vuri).query).get("token") or [None])[0]
        )
        if not claim.get("token") or not claim_attempt_token:
            raise RuntimeError(f"unexpected registration payload: {reg}")
        state = {
            "kind": "agent-signup-registered",
            "email": email,
            "organizationName": org_name,
            "claimToken": claim["token"],
            "claimAttemptToken": claim_attempt_token,
            "issuer": cfg["issuer"],
            "resource": cfg["resource"],
            "tokenEndpoint": cfg["token_endpoint"],
            "clientId": cfg["client_id"],
        }
    st, resp = http_json(
        "POST",
        cfg["server"] + "/api/agent-signup/start",
        body={
            "claimAttemptToken": state["claimAttemptToken"],
            "email": state["email"],
            "organizationName": state["organizationName"],
        },
        expect=200,
    )
    state["signupToken"] = resp.get("signupToken")
    state["kind"] = "agent-signup-pending"
    save_profile(state)
    return state


def signup_complete(cfg, state, code):
    """verify 6-digit code -> complete WorkOS claim -> jwt-bearer exchange -> tokens."""
    code = (code or "").strip()
    if not (code.isdigit() and len(code) == 6):
        raise SystemExit("code must be 6 digits")
    st, resp = http_json(
        "POST",
        cfg["server"] + "/api/agent-signup/verify",
        body={"code": code, "signupToken": state["signupToken"]},
        expect=200,
    )
    claim = resp["claim"]
    org = resp["organization"]
    state.update(
        {
            "kind": "agent-signup-claim-ready",
            "registrationId": claim["registrationId"],
            "userCode": claim["userCode"],
            "organization": org,
            "organizationCreated": resp.get("organizationCreated"),
        }
    )
    st, done = http_json(
        "POST",
        cfg["issuer"] + "/agent/identity/claim/complete",
        body={"claim_token": state["claimToken"], "user_code": claim["userCode"]},
    )
    if st != 200:
        raise RuntimeError(f"claim/complete HTTP {st}: {done}")
    identity = done.get("identity") or {}
    assertion = identity.get("assertion")
    refresh_token = identity.get("refresh_token") or identity.get("refreshToken")
    if isinstance(refresh_token, dict):  # {value, expires_at} per normalizeIdentity
        refresh_token = refresh_token.get("value")
    if not assertion:
        raise RuntimeError(f"claim/complete returned no assertion: {done}")
    state.update(
        {
            "kind": "agent-signup-provisioned",
            "assertion": assertion,
            "refreshToken": refresh_token,
        }
    )
    save_profile(state)  # persist before exchange so a failed exchange is retryable
    return exchange(cfg, state)


def exchange(cfg, state):
    # assertion aud == issuer (auth.type.com), NOT the api resource: sending
    # resource=api.type.com yields HTTP 400 invalid_target. Omit unless forced.
    form = {
        "assertion": state["assertion"],
        "grant_type": AGENT_TOKEN_EXCHANGE_GRANT,
    }
    if os.environ.get("TYPE_EXCHANGE_RESOURCE"):
        form["resource"] = os.environ["TYPE_EXCHANGE_RESOURCE"]
    token_endpoint = (cfg or {}).get("token_endpoint") or state.get("tokenEndpoint")
    if not token_endpoint:
        raise RuntimeError("profile has no tokenEndpoint; run signup again")
    st, tokens = http_json("POST", token_endpoint, form=form)
    if st != 200:
        raise RuntimeError(f"token exchange HTTP {st}: {tokens}")
    state.update(
        {
            "kind": "tokens",
            "accessToken": tokens["access_token"],
            "refreshToken": tokens.get("refresh_token") or state.get("refreshToken"),
            "tokenType": tokens.get("token_type"),
            "expiresAt": time.time() + int(tokens.get("expires_in") or 3600),
        }
    )
    save_profile(state)
    return state


# ---------------------------------------------------------------- refresh / API
def refresh(cfg, state):
    """Agent-credential refresh (bundle: refreshAgentRegistration):
    POST identityEndpoint {refresh_token, type:"refresh"} -> fresh assertion
    -> jwt-bearer exchange (no resource) -> new access_token. Live-verified 200."""
    rt = state.get("refreshToken")
    rt = rt.get("value") if isinstance(rt, dict) else rt
    if not rt:
        raise RuntimeError("no refreshToken in profile; run signup/complete again")
    issuer = (cfg or {}).get("issuer") or state.get("issuer")
    endpoint = (cfg or {}).get("identity_endpoint") or (issuer + "/agent/identity" if issuer else None)
    if not endpoint:
        raise RuntimeError("profile has no issuer; run signup or device-login first")
    st, body = http_json(
        "POST",
        endpoint,
        body={"refresh_token": rt, "type": "refresh"},
    )
    if st != 200:
        raise RuntimeError(f"identity refresh HTTP {st}: {body}")
    identity = body.get("identity") or {}
    state["assertion"] = identity["assertion"]
    new_rt = identity.get("refresh_token")
    if new_rt:
        state["refreshToken"] = new_rt.get("value") if isinstance(new_rt, dict) else new_rt
    save_profile(state)  # persist rotation BEFORE exchange: single-use rt must not burn
    return exchange(cfg, state)


def api_get(state, path="/v1/me"):
    st, body = http_json("GET", state.get("server", SERVER) + path, token=state["accessToken"])
    return st, body


def orpc_call(state, procedure, args=None):
    """oRPC call: POST {server}/api/orpc/{procedure} body {"json": args}.
    Procedures (from bundle): cli/context/me, cli/threads/list, cliAuth/listOrganizations…
    Note: service_auth tokens currently carry empty post_claim scopes -> API returns
    401 Invalid token; full access requires device-login (auth login)."""
    st, body = http_json(
        "POST",
        state.get("server", SERVER) + "/api/orpc/" + procedure,
        body={"json": args or {}},
        token=state["accessToken"],
    )
    return st, body


# ---------------------------------------------------------------- device login
def device_login(cfg, email=None):
    form = {"client_id": cfg["client_id"]}
    if email:
        form["login_hint"] = email
    st, dr = http_json("POST", WORKOS_DEVICE_AUTHORIZE_URL, form=form, expect=200)
    print(f"Open: {dr.get('verification_uri_complete') or dr.get('verification_uri')}")
    print(f"User code: {dr.get('user_code')}")
    interval = int(dr.get("interval") or 5)
    deadline = time.time() + 900
    while time.time() < deadline:
        time.sleep(interval)
        form = {
            "client_id": cfg["client_id"],
            "device_code": dr["device_code"],
            "grant_type": DEVICE_CODE_GRANT,
        }
        st, tokens = http_json("POST", WORKOS_AUTHENTICATE_URL, form=form)
        if st == 200:
            state = {
                "kind": "tokens",
                "server": cfg["server"],
                "accessToken": tokens["access_token"],
                "refreshToken": tokens.get("refresh_token"),
                "expiresAt": time.time() + int(tokens.get("expires_in") or 3600),
            }
            save_profile(state)
            return state
        err = tokens.get("error") if isinstance(tokens, dict) else None
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        raise RuntimeError(f"device grant stopped: {err or st}")
    raise RuntimeError("device grant timeout")


# ---------------------------------------------------------------- IMAP hook
def fetch_code_imap(email, password, host="mail.tm", folder="INBOX", wait=180):
    """Hook for mail pools: reads the newest 6-digit code from signup mail.
    Adapt host/credentials to your pool provider."""
    import imaplib
    import email as emaillib
    import re

    deadline = time.time() + wait
    while time.time() < deadline:
        m = imaplib.IMAP4_SSL(host)
        m.login(email, password)
        m.select(folder)
        # RFC 3501 has no infix OR — plain UNSEEN, filter headers in Python.
        _, ids = m.search(None, "UNSEEN")
        for i in (ids[0] or b"").split()[-5:]:
            _, data = m.fetch(i, "(RFC822)")
            raw = data[0][1] if data and isinstance(data[0], tuple) else None
            if raw is None:
                continue
            msg = emaillib.message_from_bytes(raw)
            sender = (msg.get("From") or "").lower()
            subject = (msg.get("Subject") or "").lower()
            if "type" not in sender and "type" not in subject:
                continue
            body = ""
            for part in msg.walk():  # multipart/alternative safe
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode("utf-8", "replace")
            codes = re.findall(r"\b(\d{6})\b", body)
            if codes:
                m.logout()
                return codes[-1]
        m.logout()
        time.sleep(10)
    raise RuntimeError("no code within wait window")


def batch_register(emails_file, org, imap_host="mail.tm", imap_pass_file=None):
    """Farm: one signup per line of `email:password`. Needs IMAP for codes."""
    cfg = discover()
    results = []
    passes = {}
    if imap_pass_file:
        for line in open(imap_pass_file, encoding="utf-8"):
            if ":" in line:
                e, p = line.strip().split(":", 1)
                passes[e] = p
    for line in open(emails_file, encoding="utf-8"):
        email = line.strip().lower()
        if not email:
            continue
        os.environ["TYPE_PROFILE"] = email.replace("@", "_at_").replace(".", "_")
        globals()["PROFILE"] = os.environ["TYPE_PROFILE"]
        try:
            state = signup_start(cfg, email, org)
            code = None
            if email in passes:
                code = fetch_code_imap(email, passes[email], host=imap_host)
            else:
                code = input(f"[{email}] code from email> ").strip()
            state = signup_complete(cfg, state, code)
            st, me = api_get(state)
            results.append({"email": email, "ok": st == 200, "org": state.get("organization")})
            print(f"OK  {email} -> {state.get('organization', {}).get('slug')}")
        except Exception as e:
            results.append({"email": email, "ok": False, "error": str(e)})
            print(f"FAIL {email}: {e}")
    out = os.path.join(os.path.dirname(emails_file) or ".", "type_batch_result.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"results -> {out}")


# ---------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="type.com protocol client")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover")
    sp = sub.add_parser("signup")
    sp.add_argument("--email", required=True)
    sp.add_argument("--org", required=True)
    cp = sub.add_parser("complete")
    cp.add_argument("--code", required=True)
    sub.add_parser("status")
    sub.add_parser("refresh")
    sub.add_parser("me")
    dp = sub.add_parser("device-login")
    dp.add_argument("--email")
    bp = sub.add_parser("batch")
    bp.add_argument("--emails", required=True)
    bp.add_argument("--org", required=True)
    bp.add_argument("--imap-host", default="mail.tm")
    bp.add_argument("--imap-pass-file")
    args = ap.parse_args()

    if args.cmd == "discover":
        cfg = discover()
        print(json.dumps(cfg, indent=2))
    elif args.cmd == "signup":
        cfg = discover()
        state = signup_start(cfg, args.email, args.org)
        print(f"code sent to {state['email']} (state saved).")
        print(f"next: python {sys.argv[0]} complete --code <6digits> [--profile {PROFILE}]")
    elif args.cmd == "complete":
        state = load_profile()
        if not state or state.get("kind") not in ("agent-signup-pending", "agent-signup-verifying"):
            raise SystemExit("no pending signup in this profile")
        cfg = discover(state.get("server") or SERVER)
        state = signup_complete(cfg, state, args.code)
        print(f"PROVISIONED org={state.get('organization', {}).get('slug')} "
              f"accessToken={'yes' if state.get('accessToken') else 'no'}")
    elif args.cmd == "status":
        state = load_profile()
        print(json.dumps(
            {k: v for k, v in (state or {}).items()
             if k not in ("assertion", "accessToken", "refreshToken", "signupToken")},
            indent=2, ensure_ascii=False))
    elif args.cmd == "refresh":
        state = load_profile()
        cfg = discover(state.get("server") or SERVER)
        state = refresh(cfg, state)
        print(f"refreshed, expires_at={state['expiresAt']}")
    elif args.cmd == "me":
        state = load_profile()
        if state.get("kind") != "tokens":
            raise SystemExit("profile has no access token; run signup/complete or device-login")
        if time.time() > state.get("expiresAt", 0):
            refresh(discover(state.get("server") or SERVER), state)
            state = load_profile()
        st, me = orpc_call(state, "cli/context/me")
        print(st, json.dumps(me, indent=2, ensure_ascii=False)[:2000])
    elif args.cmd == "device-login":
        cfg = discover()
        device_login(cfg, email=args.email)
        print("tokens stored")
    elif args.cmd == "batch":
        batch_register(args.emails, args.org, args.imap_host, args.imap_pass_file)


if __name__ == "__main__":
    main()
