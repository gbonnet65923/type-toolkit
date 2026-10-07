# -*- coding: utf-8 -*-
"""
tt_wos_reg2.py — type.com autoreg v3 (WorkOS AuthKit signup path, browserless-captcha-free).

Flow (live-verified 2026-10-07):
  1. mail.tm account (dynamic domain)
  2. POST api.workos.com/user_management/authorize/device -> device_code + verification_uri_complete
  3. patchright: /sign-up -> first/last/email -> Continue
  4. /sign-up/password -> password (>=10 chars) -> Continue
  5. email verification code -> mail.tm poll -> enter
  6. device poll -> access_token + refresh_token
  7. save to server/pool.json (gateway :8311 compatible)

Usage: python tt_wos_reg2.py [--headless] [--org reform-org]
"""
import json
import os
import random
import re
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

ROOT = r"C:\Users\User\tmp\type-toolkit"
POOL_PATH = os.path.join(ROOT, "server", "pool.json")
CLIENT_ID = "client_01K5GFDDKQWV8MM9FSRZS3YNNN"
WOS_DEVICE = "https://api.workos.com/user_management/authorize/device"
WOS_AUTH = "https://api.workos.com/user_management/authenticate"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/129.0.0.0 Safari/537.36"

FIRST = ["Alex", "Sam", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Jamie", "Drew", "Quinn", "Nikita", "Artem", "Oleg", "Ivan", "Max", "Leo", "Kai", "Ren"]
LAST = ["Miller", "Stone", "Frost", "Vale", "Cross", "Webb", "Hale", "Reed", "Cole", "Ward", "Fox", "Lane", "Petrov", "Volkov", "Orlov", "Sokol"]


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def http_json(method, url, body=None, form=None, headers=None, timeout=30):
    h = {"User-Agent": UA}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")[:300]
    except Exception as e:
        return 0, str(e)[:200]


VOIDASH_API = "https://api.voidash.com/api/v1"
VOIDASH_DOMAINS = ["govno.eu.cc", "musor.eu.cc", "pomoi.eu.cc"]


def voidash_account():
    """Create a Voidash inbox on a custom eu.cc domain. Returns (email, None, session_key)."""
    for dom in VOIDASH_DOMAINS:
        st, r = http_json("POST", VOIDASH_API + "/inboxes", body={"domain": dom})
        if st in (200, 201) and isinstance(r, dict):
            sk = r.get("session_key") or r.get("sessionKey") or r.get("token")
            email = r.get("address") or r.get("email")
            if email and sk:
                log("voidash inbox:", email)
                return email, None, sk
    raise RuntimeError("voidash create failed for all domains")


def voidash_wait_code(sk, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, r = http_json("GET", VOIDASH_API + "/messages", headers={"Authorization": "Bearer " + sk})
        if st == 200:
            items = r if isinstance(r, list) else (r.get("messages") or r.get("data") or r.get("items") or [])
            for m in items:
                mid = m.get("id") or m.get("_id")
                st2, full = http_json("GET", VOIDASH_API + "/messages/" + str(mid),
                                      headers={"Authorization": "Bearer " + sk})
                src = full if isinstance(full, dict) else m
                text = (src.get("text") or src.get("body") or src.get("html") or "")
                if isinstance(text, list):
                    text = " ".join(str(x) for x in text)
                code = re.search(r"\b(\d{6})\b", text)
                if code:
                    log("code from voidash:", code.group(1))
                    return code.group(1)
        time.sleep(6)
    return None


def imap_tonline_account():
    """Take a t-online mailbox from the pool; return (email, password)."""
    pool_file = r"C:\Users\User\Desktop\avtoreg\working_mails.txt"
    lines = [l.strip() for l in open(pool_file, encoding="utf-8")
             if l.strip() and ":" in l and not l.startswith("#")]
    random.shuffle(lines)
    email, _, pwd = lines[0].partition(":")
    log("t-online mailbox:", email[:3] + "***")
    return email, pwd.strip()


def imap_wait_code(email, pwd, timeout=300):
    """Poll t-online IMAP for a 6-digit WorkOS/Type code."""
    import imaplib
    import email as emaillib
    host = "secureimap.t-online.de"
    t0 = time.time()
    conn = None
    while time.time() - t0 < timeout:
        try:
            conn = imaplib.IMAP4_SSL(host, 993)
            conn.login(email, pwd)
            conn.select("INBOX")
            typ, data = conn.search(None, "UNSEEN")
            ids = data[0].split()
            for num in ids[-10:]:
                typ, msgdata = conn.fetch(num, "(RFC822)")
                raw = msgdata[0][1]
                msg = emaillib.message_from_bytes(raw)
                subj = msg.get("Subject", "") + " " + msg.get("From", "")
                if not re.search(r"workos|type", subj, re.I):
                    continue
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body += part.get_payload(decode=True).decode(errors="replace")
                else:
                    body = msg.get_payload(decode=True).decode(errors="replace")
                code = re.search(r"\b(\d{6})\b", body)
                if code:
                    log("code from IMAP:", code.group(1), "| subj:", subj[:60])
                    conn.logout()
                    return code.group(1)
            conn.logout()
        except Exception as e:
            log("imap err:", str(e)[:120])
        time.sleep(6)
    return None


def mailtm_wait_code(mtok, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, msgs = http_json("GET", "https://api.mail.tm/messages?page=1",
                             headers={"Authorization": "Bearer " + mtok})
        if st == 200 and isinstance(msgs, dict):
            for m in msgs.get("hydra:member") or []:
                st2, full = http_json("GET", "https://api.mail.tm/messages/" + m["id"],
                                      headers={"Authorization": "Bearer " + mtok})
                if st2 == 200 and isinstance(full, dict):
                    text = (full.get("text") or "") + " ".join(str(p) for p in (full.get("html") or []))
                    code = re.search(r"\b(\d{6})\b", text)
                    if code:
                        log("code from mail:", code.group(1), "| subj:", (full.get("subject") or "")[:60])
                        return code.group(1)
        time.sleep(5)
    return None


def device_start():
    st, dr = http_json("POST", WOS_DEVICE, form={"client_id": CLIENT_ID})
    if st != 200 or not isinstance(dr, dict) or "device_code" not in dr:
        raise RuntimeError("workos device %s: %s" % (st, str(dr)[:200]))
    log("device:", dr.get("user_code"))
    return dr


def device_poll(dr, timeout=600):
    t0 = time.time()
    interval = int(dr.get("interval") or 5)
    while time.time() - t0 < timeout:
        time.sleep(interval)
        st, r = http_json("POST", WOS_AUTH, form={
            "client_id": CLIENT_ID, "device_code": dr["device_code"], "grant_type": DEVICE_GRANT})
        if st == 200 and isinstance(r, dict) and r.get("access_token"):
            return r
        err = r.get("error") if isinstance(r, dict) else None
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            raise RuntimeError("device poll: %s %s" % (err, str(r)[:150]))
    raise RuntimeError("device poll timeout")


def click_btn(page, texts):
    btns = page.locator("button")
    for i in range(btns.count()):
        try:
            t = btns.nth(i).inner_text().strip().lower()
        except Exception:
            continue
        for want in texts:
            if want in t:
                btns.nth(i).click()
                return t
    return None


def authkit_signup(uri, email, password, first, last, code_getter, headless=True, proxy=None):
    """Camoufox (anti-detect Firefox) — WorkOS Radar blocks plain Chromium."""
    from camoufox.sync_api import Camoufox
    kw = {"headless": headless}
    if proxy:
        kw["proxy"] = {"server": proxy}
        kw["geoip"] = True
    with Camoufox(**kw) as browser:
        page = browser.new_page()
        page.goto(uri, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)

        # landing -> Sign up
        page.locator("a:has-text('Sign up'), button:has-text('Sign up')").first.click()
        page.wait_for_timeout(3000)
        log("signup form url:", page.url[:90])

        # names + email
        page.locator("input[name='first_name']").first.fill(first)
        page.locator("input[name='last_name']").first.fill(last)
        page.locator("input[name='email'], input[type='email']").first.fill(email)
        page.wait_for_timeout(400)
        clicked = click_btn(page, ["continue", "sign up", "create"])
        log("step1 clicked:", clicked)
        page.wait_for_timeout(4500)

        # password step OR email-code option — prefer email code (no password policy / radar)
        body0 = page.inner_text("body")
        log("after step1 url:", page.url[:100])
        if "Continue with email code" in body0:
            page.locator("button:has-text('Continue with email code'), a:has-text('Continue with email code')").first.click()
            log("chose email-code path")
            page.wait_for_timeout(5000)
        elif page.locator("input[type='password']").count():
            page.locator("input[type='password']").first.fill(password)
            page.wait_for_timeout(300)
            clicked = click_btn(page, ["continue", "sign up", "create"])
            log("step2 clicked:", clicked)
            page.wait_for_timeout(5000)
        txt = page.inner_text("body")[:300].replace("\n", " | ")
        log("page text:", txt)
        if "access blocked" in txt.lower():
            raise RuntimeError("Radar: Access blocked")

        # email verification code step
        code = None
        deadline = time.time() + 300
        while time.time() < deadline:
            body = page.inner_text("body").lower()
            inputs = page.locator("input")
            code_inputs = page.locator("input[inputmode='numeric'], input[autocomplete='one-time-code'], input[name*='code']")
            if "code" in body and (code_inputs.count() or "verification" in body or "check your" in body):
                code = code_getter()
                if not code:
                    raise RuntimeError("no email code arrived")
                n = code_inputs.count()
                if n >= 6:
                    for i, ch in enumerate(code[:6]):
                        code_inputs.nth(i).fill(ch)
                elif n >= 1:
                    code_inputs.first.fill(code)
                else:
                    vis = page.locator("input[type='text']:visible, input:not([type='hidden']):visible")
                    if vis.count():
                        vis.first.fill(code)
                page.wait_for_timeout(1200)
                click_btn(page, ["verify", "continue", "submit", "confirm"])
                page.wait_for_timeout(6000)
                log("code submitted, url:", page.url[:100])
                break
            # maybe already through (device confirmed screen)
            if "confirmed" in body or "success" in body or "you can close" in body or "return to" in body:
                log("device confirmed screen:", body[:120])
                break
            page.wait_for_timeout(3000)
        else:
            raise RuntimeError("no code step detected")

        # final: device consent screen may need a click
        for t in ["confirm", "allow", "continue", "authorize"]:
            if click_btn(page, [t]):
                log("final click:", t)
                page.wait_for_timeout(3000)
                break
        log("final url:", page.url[:100], "| text:", page.inner_text("body")[:200].replace("\n", " | "))


def pool_append(acct):
    pool = []
    if os.path.exists(POOL_PATH):
        try:
            pool = json.load(open(POOL_PATH, encoding="utf-8"))
        except Exception:
            pool = []
    pool.append(acct)
    json.dump(pool, open(POOL_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    log("pool:", len(pool), "accounts")


def main():
    org = "reform-org"
    headless = "--headless" in sys.argv or True
    if "--org" in sys.argv:
        org = sys.argv[sys.argv.index("--org") + 1]

    email, mpwd, vsk = voidash_account()
    password = "Tt" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"
    first, last = random.choice(FIRST), random.choice(LAST)
    dr = device_start()

    proxies = []
    if "--proxy" in sys.argv:
        proxies = [sys.argv[sys.argv.index("--proxy") + 1]]
    elif os.path.exists(r"C:\Users\User\tmp\tt_live_px.json"):
        proxies = json.load(open(r"C:\Users\User\tmp\tt_live_px.json", encoding="utf-8"))
    log("proxies:", len(proxies))

    last_err = ""
    for px in proxies:
        try:
            authkit_signup(dr["verification_uri_complete"], email, password, first, last,
                           lambda: voidash_wait_code(vsk, timeout=300), headless=headless, proxy=px)
            last_err = ""
            break
        except Exception as e:
            last_err = str(e)[:200]
            log("proxy", px[:30], "FAIL:", last_err)
    if not proxies:
        try:
            authkit_signup(dr["verification_uri_complete"], email, password, first, last,
                           lambda: voidash_wait_code(vsk, timeout=300), headless=headless)
        except Exception as e:
            log("browser FAIL:", str(e)[:300])

    try:
        tokens = device_poll(dr, timeout=240)
    except Exception as e:
        log("poll FAIL:", str(e)[:200])
        pool_append({"email": email, "voidash_session": vsk, "workos_password": password,
                     "first": first, "last": last, "org": org,
                     "device_user_code": dr.get("user_code"), "status": "incomplete",
                     "created": time.strftime("%Y-%m-%d %H:%M:%S")})
        sys.exit(1)

    acct = {
        "email": email, "voidash_session": vsk, "workos_password": password,
        "first": first, "last": last, "org": org,
        "access_token": tokens["access_token"], "access_token_len": len(tokens["access_token"]),
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
        "source": "workos-authkit-signup", "created": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    pool_append(acct)
    log("SUCCESS:", email, "| token len", len(tokens["access_token"]))


if __name__ == "__main__":
    main()
