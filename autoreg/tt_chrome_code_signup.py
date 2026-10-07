# -*- coding: utf-8 -*-
"""Signup in REAL Chrome via EMAIL-CODE method (skip password step entirely)."""
import sys, time, json, random
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\User\tmp")
from tt_wos_reg2 import voidash_account, device_start, device_poll, voidash_wait_code, pool_append
from playwright.sync_api import sync_playwright

email, _, vsk = voidash_account()
print("EMAIL:", email)

def click_any(page, patterns):
    els = page.locator("button, a, div[role='button']")
    for i in range(els.count()):
        try:
            t = els.nth(i).inner_text().strip().lower()
        except Exception:
            continue
        for pat in patterns:
            if pat and pat in t:
                els.nth(i).click()
                return t[:60]
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
    c = click_any(page, ["sign up"])
    print("signup clicked:", c)
    page.wait_for_timeout(4000)
    if page.locator("input[name='first_name']").count():
        page.locator("input[name='first_name']").first.fill("Nikita")
        page.locator("input[name='last_name']").first.fill("Orlov")
    page.locator("input[name='email'], input[type='email']").first.fill(email)
    page.wait_for_timeout(600)
    click_any(page, ["continue"])
    page.wait_for_timeout(5000)
    body0 = page.inner_text("body")
    print("AFTER CONTINUE:", body0[:250].replace(chr(10), " | "))
    # go straight to email-code method (skip password)
    c = click_any(page, ["continue with email code"])
    print("code method clicked:", c)
    page.wait_for_timeout(6000)
    body = page.inner_text("body")
    print("SCREEN:", body[:350].replace("\n", " | "))
    if "access blocked" in body.lower():
        print("=> RADAR BLOCK on code signup too")
        page.screenshot(path=r"C:\Users\User\tmp\tt_shots\chrome_codesignup_blocked.png")
        page.close()
        sys.exit(2)
    code = voidash_wait_code(vsk, timeout=300)
    print("CODE:", code)
    if code:
        ci = page.locator("input[inputmode='numeric'], input[autocomplete='one-time-code'], input[name*='code'], input[type='text']")
        n = ci.count()
        print("inputs:", n)
        if n >= 6:
            for i, ch in enumerate(code[:6]):
                ci.nth(i).fill(ch)
        elif n >= 1:
            ci.first.fill(code)
        page.wait_for_timeout(2000)
        click_any(page, ["verify", "continue", "sign up", "create"])
        page.wait_for_timeout(8000)
        print("FINAL URL:", page.url[:110])
        print("FINAL:", page.inner_text("body")[:300].replace("\n", " | "))
        # org creation / device consent steps
        for pats in (["create workspace", "continue", "next"], ["confirm", "allow", "authorize"]):
            c = click_any(page, pats)
            if c:
                print("clicked:", c)
                page.wait_for_timeout(5000)
        page.screenshot(path=r"C:\Users\User\tmp\tt_shots\chrome_codesignup.png")
    page.close()

try:
    tokens = device_poll(dr, timeout=120)
    rec = {"email": email, "org": "reform-org",
           "access_token": tokens["access_token"], "access_token_len": len(tokens["access_token"]),
           "refresh_token": tokens.get("refresh_token"),
           "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
           "source": "chrome-emailcode-signup", "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    pool_append(rec)
    print("=>=> SIGNUP SUCCESS — fresh type.com token in pool")
except Exception as e:
    print("poll fail:", str(e)[:200])
