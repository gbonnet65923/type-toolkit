# Codeberg reg v2: image-captcha solved by operator (poll answer file)
import json
import random
import string
import sys
import time
import base64
import os
import re
import urllib.request
import urllib.error

sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
from camoufox.sync_api import Camoufox
from gh_mail import MailTM

OUT = r"C:\Users\User\tmp\bpproxy_run"
CAP = OUT + r"\cb_captcha.png"
ANS = OUT + r"\cb_answer.txt"
SIGNUP_URL = "https://codeberg.org/user/sign_up"
API = "https://codeberg.org/api/v1"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


for f in (ANS,):
    if os.path.exists(f):
        os.remove(f)

mail = MailTM()
mb = mail.create()
addr, token = mb["address"], mb["token"]
log(f"mailbox: {addr}")

username = "dev" + "".join(random.choices(string.ascii_lowercase, k=5)) + "".join(random.choices(string.digits, k=3))
password = "Cb#" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "!9"
log(f"account: {username}")

result = {"username": username, "password": password, "email": addr}

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(SIGNUP_URL, timeout=90000, wait_until="domcontentloaded")
    time.sleep(3)

    page.fill("input[name=user_name]", username)
    page.fill("input[name=email]", addr)
    page.fill("input[name=password]", password)
    page.fill("input[name=retype]", password)
    time.sleep(1)

    # screenshot the captcha image
    try:
        img = page.locator("img.captcha, img#captcha-img, img[src*=captcha]").first
        img.wait_for(state="visible", timeout=10000)
        img.screenshot(path=CAP)
        log("captcha screenshot saved -> cb_captcha.png")
    except Exception:
        page.screenshot(path=CAP)
        log("captcha element not found; full page saved")

    # wait for operator answer
    log("waiting operator answer (cb_answer.txt)...")
    answer = None
    for _ in range(90):
        if os.path.exists(ANS):
            answer = open(ANS).read().strip()
            if answer:
                break
        time.sleep(4)
    log(f"captcha answer: {answer!r}")
    if not answer:
        log("FATAL: no operator answer")
        sys.exit(3)

    page.fill("input[name=img-captcha-response]", answer)
    time.sleep(0.8)
    try:
        page.click("button[type=submit]", timeout=8000)
    except Exception:
        page.evaluate("(() => { const b = document.querySelector('button[type=submit]') || document.querySelector('button'); if (b) b.click(); })()")
    time.sleep(8)

    st = page.evaluate("() => ({url: location.href, body: document.body.innerText.slice(0,500)})()")
    log(f"after submit: {st['url'][:90]}")
    log("BODY: " + st["body"][:350].replace("\n", " | "))
    page.screenshot(path=OUT + r"\cb_state2.png")
    result["after_submit"] = st["body"][:200]

    # email code?
    code_el = page.evaluate("() => !!document.querySelector('input[name*=code i], input[id*=code i]')")
    if code_el or "verification" in st["body"].lower():
        log("email-code flow")
        code = mail.wait_code(token, sender_hint="codeberg", timeout_sec=300)
        log(f"code: {code}")
        if code:
            page.evaluate("""(code) => {
                const cands = ['input[name*=code i]','input[id*=code i]','input[autocomplete=one-time-code]'];
                let el = null;
                for (const c of cands) { el = document.querySelector(c); if (el) break; }
                if (!el) return;
                el.focus(); el.value = code;
                el.dispatchEvent(new Event('input', {bubbles:true}));
            }""", code)
            time.sleep(1)
            page.evaluate("(() => { const b = document.querySelector('button[type=submit]'); if (b) b.click(); })()")
            time.sleep(8)
            st = page.evaluate("() => ({url: location.href, body: document.body.innerText.slice(0,400)})()")
            log("AFTER CODE: " + st["body"][:300].replace("\n", " | "))
            result["after_code"] = st["body"][:200]

# API token via Basic Auth
def api(method, path, data=None):
    cred = base64.b64encode(f"{username}:{password}".encode()).decode()
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode() if data else None,
        headers={"Content-Type": "application/json", "Authorization": "Basic " + cred},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}

stc, me = api("GET", "/user")
log(f"API /user: {stc} -> {str(me)[:140]}")
result["api_user"] = stc
if stc == 200:
    stt, tok = api("POST", f"/users/{username}/tokens", {"name": "push1", "scopes": ["write:repository", "read:user"]})
    log(f"token: {stt} -> {str(tok)[:100]}")
    if stt == 201:
        result["pat"] = tok.get("sha1")
print(json.dumps(result))
