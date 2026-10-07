# -*- coding: utf-8 -*-
"""Signup via REAL Chrome (CDP :9223) — no automation fingerprint, home IP."""
import sys, time, json
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:\Users\User\tmp")
from tt_wos_reg2 import voidash_account, device_start, voidash_wait_code, log
import random, string
from playwright.sync_api import sync_playwright

email, _, vsk = voidash_account()
password = "Tt" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"
dr = device_start()
uri = dr["verification_uri_complete"]
print("EMAIL:", email, "DEVICE:", dr.get("user_code"))

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

with sync_playwright() as pw:
    b = pw.chromium.connect_over_cdp("http://127.0.0.1:9223")
    ctx = b.contexts[0]
    page = ctx.new_page()
    page.goto(uri, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    print("URL:", page.url[:100])
    body = page.inner_text("body")
    print("TEXT:", body[:250].replace("\n", " | "))
    c = click_any(page, ["sign up", "registrera", "create account"])
    print("clicked:", c)
    page.wait_for_timeout(4000)
    if page.locator("input[name='first_name']").count():
        page.locator("input[name='first_name']").first.fill("Nikita")
        page.locator("input[name='last_name']").first.fill("Orlov")
    page.locator("input[name='email'], input[type='email']").first.fill(email)
    page.wait_for_timeout(500)
    click_any(page, ["continue", "sign up", "next"])
    page.wait_for_timeout(5000)
    body = page.inner_text("body")
    print("TEXT2:", body[:350].replace("\n", " | "))
    blocked = "access blocked" in body.lower()
    print("BLOCKED:", blocked)
    if not blocked and page.locator("input[type='password']").count():
        page.locator("input[type='password']").first.fill(password)
        page.wait_for_timeout(600)
        click_any(page, ["continue", "sign up", "create"])
        page.wait_for_timeout(6000)
        body = page.inner_text("body")
        print("TEXT3:", body[:350].replace("\n", " | "))
        if "access blocked" not in body.lower():
            print("PASSWORD STEP PASSED")
            code = voidash_wait_code(vsk, timeout=300)
            print("CODE:", code)
    page.screenshot(path=r"C:\Users\User\tmp\tt_shots\chrome_signup.png")
    page.close()
