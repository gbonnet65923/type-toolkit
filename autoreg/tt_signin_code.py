# -*- coding: utf-8 -*-
"""Sign IN via EMAIL CODE path only (no password) in real Chrome."""
import sys, time, json, re
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\User\tmp")
from tt_wos_reg2 import device_start, device_poll, http_json, pool_append
from playwright.sync_api import sync_playwright

acct = json.load(open(r"C:\Users\User\tmp\type-toolkit\client\acct.json", encoding="utf-8"))
email = acct["email"]
mtok = acct.get("mt_token")
print("EMAIL:", email)

def click_any(page, patterns):
    els = page.locator("button, a")
    for i in range(els.count()):
        try:
            t = els.nth(i).inner_text().strip().lower()
        except Exception:
            continue
        for pat in patterns:
            if pat in t:
                els.nth(i).click()
                return t
    return None

def tm_code(timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st, msgs = http_json("GET", "https://api.mail.tm/messages?page=1",
                             headers={"Authorization": "Bearer " + mtok})
        if st == 200 and isinstance(msgs, dict):
            for m in (msgs.get("hydra:member") or [])[:5]:
                st2, full = http_json("GET", "https://api.mail.tm/messages/" + m["id"],
                                      headers={"Authorization": "Bearer " + mtok})
                if st2 == 200 and isinstance(full, dict):
                    text = (full.get("text") or "") + " ".join(str(p) for p in (full.get("html") or []))
                    c = re.search(r"\b(\d{6})\b", text)
                    if c:
                        print("CODE:", c.group(1))
                        return c.group(1)
        elif st == 401:
            print("tm token 401")
            return None
        time.sleep(5)
    return None

dr = device_start()
uri = dr["verification_uri_complete"]
print("DEVICE:", dr.get("user_code"))

with sync_playwright() as pw:
    b = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    ctx = b.contexts[0]
    page = ctx.new_page()
    page.goto(uri, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    page.locator("input[name='email'], input[type='email']").first.fill(email)
    page.wait_for_timeout(400)
    # continue with email (goes to password screen with options)
    click_any(page, ["continue with email", "continue"])
    page.wait_for_timeout(5000)
    body = page.inner_text("body")
    print("SCREEN:", body[:300].replace("\n", " | "))
    # choose EMAIL CODE method instead of password
    c = click_any(page, ["email sign-in code", "continue with email code", "use email code"])
    print("method clicked:", c)
    page.wait_for_timeout(5000)
    body = page.inner_text("body")
    print("AFTER METHOD:", body[:300].replace("\n", " | "))
    if "access blocked" in body.lower():
        print("=> BLOCKED even on email-code method")
        page.close()
        sys.exit(2)
    code = tm_code()
    if code:
        ci = page.locator("input[inputmode='numeric'], input[autocomplete='one-time-code'], input[name*='code'], input[type='text']")
        n = ci.count()
        print("code inputs:", n)
        if n >= 6:
            for i, ch in enumerate(code[:6]):
                ci.nth(i).fill(ch)
        elif n >= 1:
            ci.first.fill(code)
        page.wait_for_timeout(2000)
        click_any(page, ["verify", "continue", "sign in"])
        page.wait_for_timeout(8000)
        print("FINAL URL:", page.url[:100])
        print("FINAL TEXT:", page.inner_text("body")[:250].replace("\n", " | "))
        click_any(page, ["confirm", "allow", "continue", "authorize"])
        page.wait_for_timeout(4000)
    page.screenshot(path=r"C:\Users\User\tmp\tt_shots\chrome_code_signin.png")
    page.close()

try:
    tokens = device_poll(dr, timeout=120)
    rec = {"email": email, "org": "reform-org",
           "access_token": tokens["access_token"], "access_token_len": len(tokens["access_token"]),
           "refresh_token": tokens.get("refresh_token"),
           "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
           "source": "device-signin-emailcode", "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    pool_append(rec)
    print("=>=> SUCCESS fresh tokens in pool")
except Exception as e:
    print("poll fail:", str(e)[:200])
