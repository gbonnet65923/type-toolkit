# -*- coding: utf-8 -*-
"""Verify all collected OK_VERIFIED GitHub accounts via web login flow:
GET /login (authenticity_token) -> POST /session -> expect 302 away from /login.
Usage: python gh_verify_accounts.py [mode]
mode: check (default) / out (print table)
"""
import requests, re, json, sys, time

ACC = r"C:\Users\User\tmp\bpproxy_run\github_accounts.jsonl"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36"


def get_accounts():
    rows = []
    try:
        with open(ACC, encoding="utf-8") as f:
            for line in f:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def check_login(user, pwd):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    try:
        r = s.get("https://github.com/login", timeout=30)
        tok = re.search(r'name="authenticity_token" value="([^"]+)"', r.text)
        if not tok:
            return "NO_TOKEN"
        payload = {"authenticity_token": tok.group(1), "login": user, "password": pwd, "commit": "Sign in"}
        r2 = s.post("https://github.com/session", data=payload, timeout=30, allow_redirects=False)
        loc = r2.headers.get("Location", "")
        if r2.status_code in (302, 303) and "/login" not in loc.split("?")[0]:
            return "OK"
        if "two_factor" in loc or "2fa" in loc:
            return "2FA"
        if r2.status_code == 200:
            # maybe wrong password message
            if "Incorrect username or password" in r2.text:
                return "BAD_CREDS"
            return "UNKNOWN"
        return f"HTTP{r2.status_code}"
    except Exception as e:
        return "ERR"


def main():
    rows = get_accounts()
    verified = [r for r in rows if r.get("status") == "OK_VERIFIED"]
    print(f"total records={len(rows)} verified={len(verified)}", flush=True)
    results = []
    for i, r in enumerate(verified, 1):
        res = check_login(r["username"], r["password"])
        results.append((r["username"], r["email"], res))
        print(f"[{i}/{len(verified)}] {r['username']} -> {res}", flush=True)
        time.sleep(2)
    ok = sum(1 for _ in results if _[2] == "OK")
    full_path = ACC.replace(".jsonl", "_verify.jsonl")
    with open(full_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "results": results, "ok": ok, "total": len(verified)}) + "\n")
    print(f"OK={ok}/{len(verified)} saved -> {full_path}", flush=True)


if __name__ == "__main__":
    main()