#!/usr/bin/env python3
"""
gateway.py - OpenAI-compatible gateway over the type.com agent pool.
Port 8311. Stdlib only. Pool-aware: rotates accounts from server/pool.json,
auto-refreshes identity (rotating refresh_token) before use.

Endpoints:
  GET  /v1/models           -> static agent catalog (pool-backed)
  GET  /health              -> {"ok", "pool", "upstream_mode"}
  POST /v1/chat/completions -> oRPC bridge (cli/messages/send etc.)
       Upstream api.type.com currently rejects agent tokens with
       401 Invalid token (aud=client, server policy - see FINDINGS.md),
       so completions return the upstream status verbatim.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

POOL_PATH = os.path.join(ROOT, "pool.json")
PORT = int(os.environ.get("TYPE2API_PORT", "8311"))
UA = "TypeCLI/1.0.0"
TOKEN_TTL = 3600

POOL_LOCK = threading.Lock()
_ROBIN = {"i": 0}
STATS = {"requests": 0, "upstream_401": 0, "upstream_200": 0, "refreshes": 0}


def log(msg):
    print("[gateway %s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


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


def refresh_account(acct):
    """Identity refresh (rotating rt) + jwt-bearer exchange. Live-verified flow."""
    rt = acct.get("refresh_token")
    if not rt:
        raise RuntimeError("no refresh_token for %s" % acct.get("email"))
    st, body = api("POST", "https://auth.type.com/agent/identity",
                   body={"refresh_token": rt, "type": "refresh"})
    if st != 200:
        raise RuntimeError("identity refresh %s: %s" % (st, str(body)[:120]))
    ident = body.get("identity") or {}
    new_rt = (ident.get("refresh_token") or {}).get("value")
    if ident.get("assertion"):
        acct["assertion"] = ident["assertion"]
    if new_rt:
        acct["refresh_token"] = new_rt
    st2, tok = api("POST", acct.get("token_endpoint", "https://auth.type.com/oauth2/token"),
                   form={"assertion": acct["assertion"],
                         "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer"})
    at = tok.get("access_token")
    if not at:
        raise RuntimeError("exchange %s: %s" % (st2, str(tok)[:120]))
    acct["access_token"] = at
    acct["access_token_len"] = len(at)
    acct["last_refresh"] = time.strftime("%Y-%m-%d %H:%M:%S")
    acct["last_status"] = "refresh:%s/exchange:%s" % (st, st2)
    acct["token_expires_at"] = time.time() + TOKEN_TTL
    STATS["refreshes"] += 1
    return acct


def pick_account():
    """Round-robin a pool account with a live-ish token; refresh if stale."""
    with POOL_LOCK:
        pool = load_pool()
    usable = [a for a in pool if a.get("refresh_token")]
    if not usable:
        raise RuntimeError("pool empty: POST http://127.0.0.1:8312/api/autoreg first")
    acct = usable[_ROBIN["i"] % len(usable)]
    _ROBIN["i"] += 1
    if time.time() > acct.get("token_expires_at", 0):
        refresh_account(acct)
        with POOL_LOCK:
            pool = load_pool()
            for i, a in enumerate(pool):
                if a.get("email") == acct["email"]:
                    pool[i] = acct
            save_pool(pool)
    return acct


def orpc(acct, procedure, args=None):
    return api("POST", "https://api.type.com/api/orpc/" + procedure,
               body={"json": args or {}},
               headers={"Authorization": "Bearer " + acct["access_token"]})


SEND_PROCEDURE_CANDIDATES = [
    "cli/threads/create", "cli/messages/create", "cli/threads/send",
    "cli/chat/send", "cli/agents/run", "cli/threads/message",
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            with POOL_LOCK:
                pool = load_pool()
            self._send(200, {
                "ok": True,
                "port": PORT,
                "pool": {"count": len(pool), "with_token": sum(1 for a in pool if a.get("access_token"))},
                "stats": STATS,
                "upstream_mode": "agent-pool (oRPC gated server-side: 401 Invalid token)",
            })
        elif self.path == "/v1/models":
            self._send(200, {"object": "list", "data": [
                {"id": "type-agent", "object": "model", "owned_by": "type.com"},
                {"id": "type-default", "object": "model", "owned_by": "type.com"},
            ]})
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send(404, {"error": {"message": "not found"}})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            req = {}
        STATS["requests"] += 1
        messages = req.get("messages") or []
        last = messages[-1].get("content", "") if messages else ""
        prompt = last if isinstance(last, str) else json.dumps(last, ensure_ascii=False)
        try:
            acct = pick_account()
        except Exception as e:
            self._send(500, {"error": {"message": str(e), "type": "pool_error"}})
            return
        # probe live procedures with the account token
        last_err = None
        for proc in SEND_PROCEDURE_CANDIDATES:
            st, body = orpc(acct, proc, {"text": prompt})
            if st == 200:
                STATS["upstream_200"] += 1
                content = body
                if isinstance(content, dict):
                    content = content.get("json") or content.get("content") or json.dumps(content, ensure_ascii=False)
                out = {
                    "id": "chatcmpl-type-%d" % int(time.time() * 1000),
                    "object": "chat.completion", "created": int(time.time()),
                    "model": req.get("model", "type-agent"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": str(content)},
                                 "finish_reason": "stop"}],
                }
                self._send(200, out)
                return
            last_err = (st, body)
            if st == 404:
                continue
            break
        STATS["upstream_401"] += 1
        st, body = last_err or (0, {"error": "no procedure"})
        self._send(502, {
            "error": {
                "message": "type.com oRPC rejected agent token: HTTP %s %s" % (
                    st, json.dumps(body, ensure_ascii=False)[:300]),
                "type": "type_upstream",
                "upstream_status": st,
                "note": "api.type.com requires aud=https://api.type.com (user token). "
                        "Agent tokens get 401 by server policy. See FINDINGS.md.",
            },
        })


def main():
    log("gateway on :%d, pool=%s" % (PORT, POOL_PATH))
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
