#!/usr/bin/env python3
"""
manager.py - type-toolkit control plane: autoreg API + account pool + dashboard.
Port 8312. Stdlib only.

Endpoints:
  GET  /               dashboard (dashboard.html)
  GET  /api/status     {gateway, pool summary, log tail}
  GET  /api/accounts   pool (redacted - no tokens)
  POST /api/autoreg    {"org": "reform-org"} -> register 1 account (60-180s)
  POST /api/refresh    refresh all accounts (identity refresh + jwt-bearer exchange)

Autoreg flow (live-verified 2026-09-30):
  mail.tm account -> auth.type.com/agent/identity (service_auth)
  -> api.type.com/api/agent-signup/start -> email code via mail.tm
  -> agent-signup/verify -> agent/identity/claim/complete
  -> oauth2/token jwt-bearer exchange -> access_token
"""
import json
import os
import random
import re
import string
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
POOL_PATH = os.path.join(ROOT, "pool.json")
DASH_PATH = os.path.join(ROOT, "dashboard.html")
GATEWAY_URL = os.environ.get("TYPE2API_URL", "http://127.0.0.1:8311")
PORT = int(os.environ.get("TYPE_MANAGER_PORT", "8312"))
UA = "TypeCLI/1.0.0"

POOL_LOCK = threading.Lock()
LOG = []


def log(msg):
    LOG.append("[%s] %s" % (time.strftime("%H:%M:%S"), msg))
    del LOG[:-200]
    print(msg, flush=True)


def api(method, url, body=None, form=None, headers=None, timeout=30):
    h = {"Content-Type": "application/json", "User-Agent": UA}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        raw = r.read()
        status = r.status
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
    except Exception as e:
        return 0, {"error": str(e)}
    try:
        parsed = json.loads(raw or b"{}")
    except Exception:
        parsed = {"_raw": raw.decode("utf-8", "replace")[:300]}
    return status, parsed


# ---------------------------------------------------------------- pool
def load_pool():
    if not os.path.exists(POOL_PATH):
        return []
    try:
        with open(POOL_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_pool(pool):
    tmp = POOL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=1)
    os.replace(tmp, POOL_PATH)


def redact(acct):
    return {
        "email": acct.get("email"),
        "org": (acct.get("org") or {}).get("slug") if isinstance(acct.get("org"), dict) else acct.get("org"),
        "created_at": acct.get("created_at"),
        "last_refresh": acct.get("last_refresh"),
        "last_status": acct.get("last_status"),
        "access_token_len": acct.get("access_token_len") or len(acct.get("access_token") or ""),
        "has_refresh": bool(acct.get("refresh_token")),
    }


# ---------------------------------------------------------------- autoreg (full_reg.py flow)
def autoreg_one(org="reform-org"):
    user = "tt" + "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    email = user + "@uberip.com"
    mpwd = "Tp" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!"

    st, acc = api("POST", "https://api.mail.tm/accounts", body={"address": email, "password": mpwd})
    if st not in (200, 201):
        raise RuntimeError("mail.tm create %s: %s" % (st, str(acc)[:150]))
    st, tok = api("POST", "https://api.mail.tm/token", body={"address": email, "password": mpwd})
    mt = tok.get("token")
    if not mt:
        raise RuntimeError("mail.tm no token: %s" % str(tok)[:150])
    log("mail created %s" % email)

    st, reg = api("POST", "https://auth.type.com/agent/identity",
                  body={"type": "service_auth", "login_hint": email})
    claim = reg.get("claim") or {}
    if not claim.get("token"):
        raise RuntimeError("service_auth %s: %s" % (st, str(reg)[:200]))
    cat = urllib.parse.parse_qs(
        urllib.parse.urlparse(claim["attempt"]["verification_uri"]).query)["token"][0]
    log("claim ok (HTTP %s)" % st)

    st, s = api("POST", "https://api.type.com/api/agent-signup/start",
                body={"claimAttemptToken": cat, "email": email, "organizationName": org})
    if not s.get("signupToken"):
        raise RuntimeError("signup/start %s: %s" % (st, str(s)[:200]))
    log("signup started, waiting for email code")

    code = None
    for _ in range(30):
        time.sleep(6)
        st, msgs = api("GET", "https://api.mail.tm/messages",
                       headers={"Authorization": "Bearer " + mt})
        lst = msgs.get("hydra:member", msgs if isinstance(msgs, list) else [])
        for m in lst:
            frm = (m.get("from") or {}).get("address", "")
            if "type" in (frm + m.get("subject", "")).lower():
                st2, full = api("GET", "https://api.mail.tm/messages/" + m["id"],
                                headers={"Authorization": "Bearer " + mt})
                body_text = full.get("text", "") or json.dumps(full.get("html", []))
                codes = re.findall(r"\b(\d{6})\b", body_text)
                if codes:
                    code = codes[-1]
                    break
        if code:
            break
    if not code:
        raise RuntimeError("no email code within 180s")
    log("email code %s" % code)

    st, v = api("POST", "https://api.type.com/api/agent-signup/verify",
                body={"code": code, "signupToken": s["signupToken"]})
    uc = (v.get("claim") or {}).get("userCode")
    if not uc:
        raise RuntimeError("verify %s: %s" % (st, str(v)[:200]))
    log("verified, org=%s" % ((v.get("organization") or {}).get("slug")))

    st, done = api("POST", "https://auth.type.com/agent/identity/claim/complete",
                   body={"claim_token": claim["token"], "user_code": uc})
    ident = done.get("identity") or {}
    if not ident.get("assertion"):
        raise RuntimeError("claim/complete %s: %s" % (st, str(done)[:200]))
    log("identity issued")

    st, tok2 = api("POST", "https://auth.type.com/oauth2/token", form={
        "assertion": ident["assertion"],
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
    })
    at = tok2.get("access_token")
    log("exchange HTTP %s, token len %d" % (st, len(at or "")))
    if not at:
        raise RuntimeError("exchange %s: %s" % (st, str(tok2)[:200]))

    return {
        "email": email,
        "mail_pwd": mpwd,
        "mt_token": mt,
        "assertion": ident.get("assertion"),
        "refresh_token": (ident.get("refresh_token") or {}).get("value"),
        "token_endpoint": "https://auth.type.com/oauth2/token",
        "org": v.get("organization"),
        "user_created": v.get("organizationCreated"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_refresh": time.strftime("%Y-%m-%d %H:%M:%S"),
        "last_status": "exchange:%s" % st,
        "access_token_len": len(at),
        "access_token": at,
    }


# ---------------------------------------------------------------- refresh (live-verified flow)
def refresh_one(acct):
    rt = acct.get("refresh_token")
    if not rt:
        raise RuntimeError("no refresh_token")
    st, body = api("POST", "https://auth.type.com/agent/identity",
                   body={"refresh_token": rt, "type": "refresh"})
    if st != 200:
        raise RuntimeError("identity refresh %s: %s" % (st, str(body)[:150]))
    ident = body.get("identity") or {}
    new_rt = (ident.get("refresh_token") or {}).get("value")
    if ident.get("assertion"):
        acct["assertion"] = ident["assertion"]
    if new_rt:
        acct["refresh_token"] = new_rt
    st2, tok = api("POST", acct.get("token_endpoint", "https://auth.type.com/oauth2/token"),
                   form={
                       "assertion": acct["assertion"],
                       "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                   })
    at = tok.get("access_token")
    if not at:
        raise RuntimeError("exchange %s: %s" % (st2, str(tok)[:150]))
    acct["access_token"] = at
    acct["access_token_len"] = len(at)
    acct["last_refresh"] = time.strftime("%Y-%m-%d %H:%M:%S")
    acct["last_status"] = "refresh:%s/exchange:%s" % (st, st2)
    return acct


# ---------------------------------------------------------------- http
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        elif isinstance(payload, str):
            body = payload.encode("utf-8")
        else:
            body = payload
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html", "/dashboard"):
            try:
                with open(DASH_PATH, "rb") as f:
                    self._send(200, f.read(), "text/html; charset=utf-8")
            except Exception as e:
                self._send(500, {"error": str(e)})
        elif self.path == "/api/status":
            st, gw = api("GET", GATEWAY_URL + "/health", timeout=5)
            with POOL_LOCK:
                pool = load_pool()
            self._send(200, {
                "gateway": {"up": st == 200, "port": 8311, "body": gw},
                "pool": {
                    "count": len(pool),
                    "with_token": sum(1 for a in pool if a.get("access_token")),
                },
                "log": LOG[-30:],
                "now": time.strftime("%Y-%m-%d %H:%M:%S"),
            })
        elif self.path == "/api/accounts":
            with POOL_LOCK:
                pool = load_pool()
            self._send(200, [redact(a) for a in pool])
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        req = {}
        if length:
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                req = {}
        if self.path == "/api/autoreg":
            org = (req.get("org") or "reform-org").strip() or "reform-org"
            try:
                acct = autoreg_one(org)
                with POOL_LOCK:
                    pool = load_pool()
                    pool.append(acct)
                    save_pool(pool)
                log("autoreg OK %s -> %s" % (acct["email"], redact(acct)["org"]))
                self._send(200, {"ok": True, "account": redact(acct)})
            except Exception as e:
                log("autoreg FAIL: %s" % e)
                self._send(500, {"ok": False, "error": str(e)})
        elif self.path == "/api/refresh":
            with POOL_LOCK:
                pool = load_pool()
            results = []
            for a in pool:
                try:
                    refresh_one(a)
                    results.append({"email": a["email"], "ok": True})
                    log("refresh OK %s" % a["email"])
                except Exception as e:
                    a["last_status"] = "error:%s" % str(e)[:80]
                    results.append({"email": a["email"], "ok": False, "error": str(e)})
                    log("refresh FAIL %s: %s" % (a["email"], str(e)[:100]))
            with POOL_LOCK:
                save_pool(pool)
            self._send(200, results)
        else:
            self._send(404, {"error": "not found"})


def main():
    log("manager on :%d (gateway %s)" % (PORT, GATEWAY_URL))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
