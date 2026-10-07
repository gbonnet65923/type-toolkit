# -*- coding: utf-8 -*-
"""Google SSO via real Chrome: device flow -> Continue with Google -> account chooser."""
import sys, time, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\User\tmp")
from tt_wos_reg2 import device_start, device_poll, pool_append
from playwright.sync_api import sync_playwright

def click_any(page, patterns):
    els = page.locator("button, a, div[role='button'], li")
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
    body = page.inner_text("body")
    print("LANDING:", body[:200].replace("\n", " | "))
    c = click_any(page, ["continue with google"])
    print("google clicked:", c)
    page.wait_for_timeout(8000)
    print("URL:", page.url[:110])
    body = page.inner_text("body")
    print("GOOGLE SCREEN:", body[:400].replace("\n", " | "))
    # list accounts shown in chooser
    accounts = page.locator("[data-email], [data-identifier]")
    n = accounts.count()
    print("accounts in chooser:", n)
    for i in range(min(n, 5)):
        try:
            print("  acct:", accounts.nth(i).get_attribute("data-email") or accounts.nth(i).get_attribute("data-identifier"))
        except Exception:
            pass
    if n > 0:
        accounts.first.click()
        page.wait_for_timeout(10000)
        print("AFTER PICK URL:", page.url[:110])
        print("AFTER PICK:", page.inner_text("body")[:300].replace("\n", " | "))
        # consent screen?
        c2 = click_any(page, ["continue", "allow", "accept", "confirm"])
        print("consent clicked:", c2)
        page.wait_for_timeout(8000)
        print("FINAL URL:", page.url[:110])
        print("FINAL:", page.inner_text("body")[:250].replace("\n", " | "))
    page.screenshot(path=r"C:\Users\User\tmp\tt_shots\google_sso.png")
    page.close()

try:
    tokens = device_poll(dr, timeout=120)
    rec = {"email": "google-sso", "org": "reform-org",
           "access_token": tokens["access_token"], "access_token_len": len(tokens["access_token"]),
           "refresh_token": tokens.get("refresh_token"),
           "expires_at": time.time() + int(tokens.get("expires_in") or 3600),
           "source": "google-sso-real-chrome", "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    pool_append(rec)
    print("=>=> GOOGLE SSO SUCCESS, token in pool")
except Exception as e:
    print("poll fail:", str(e)[:200])
