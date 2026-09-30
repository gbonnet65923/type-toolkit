# Codeberg (Gitea) reg: HOME + mail.tm + API token via Basic Auth
import json
import random
import re
import string
import sys
import time
import urllib.request

sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
from camoufox.sync_api import Camoufox
from gh_mail import MailTM

SIGNUP_URL = "https://codeberg.org/user/sign_up"
API = "https://codeberg.org/api/v1"
OUT = r"C:\Users\User\tmp\bpproxy_run"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


mail = MailTM()
mb = mail.create()
if not mb:
    log("FATAL: mailbox")
    sys.exit(2)
addr, token = mb["address"], mb["token"]
log(f"mailbox: {addr}")

username = "rev" + "".join(random.choices(string.ascii_lowercase, k=4)) + "".join(random.choices(string.digits, k=3))
password = "Cb#" + "".join(random.choices(string.ascii_letters + string.digits, k=14)) + "!9"
log(f"account: {username}")

result = {"status": "unknown", "username": username, "password": password, "email": addr}

with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(SIGNUP_URL, timeout=90000, wait_until="domcontentloaded")
    time.sleep(3)

    # Gitea signup form: user_name, email, password, retype
    fields = page.evaluate("(() => Array.from(document.querySelectorAll('input')).map(i => i.name + '|' + i.type + '|' + (i.id||'')).slice(0,12))()")
    log(f"form fields: {fields}")

    def fill(sel, val):
        try:
            page.fill(sel, val, timeout=8000)
            time.sleep(0.6)
            return True
        except Exception:
            return False

    ok1 = fill("input[name=user_name]", username)
    ok2 = fill("input[name=email]", addr)
    ok3 = fill("input[name=password]", password)
    ok4 = fill("input[name=retype]", password)
    log(f"filled: name={ok1} email={ok2} pass={ok3} retype={ok4}")

    try:
        page.click("button[type=submit], #submit", timeout=8000)
    except Exception:
        page.evaluate("(() => { const b = document.querySelector('button[type=submit]') || document.querySelector('button.green') || document.querySelector('button'); if (b) b.click(); })()")
    time.sleep(8)

    st = page.evaluate("(() => ({url: location.href, body: document.body.innerText.slice(0,600)}))()")
    log(f"after submit: {st['url'][:90]}")
    log("BODY: " + st["body"][:400].replace("\n", " | "))

    # verification code flow?
    needs_code = bool(re.search(r"verification code|confirm|activate", st["body"], re.I)) or "activate" in st["url"]
    code_el = page.evaluate("(() => !!document.querySelector('input[name*=code i], input[id*=code i], input[inputmode=numeric]'))()")
    if needs_code or code_el:
        log("email-code flow detected")
        code = mail.wait_code(token, sender_hint="codeberg", timeout_sec=300)
        log(f"code: {code}")
        if code:
            page.evaluate("""(code) => {
                const cands = ['input[name*=code i]','input[id*=code i]','input[autocomplete=one-time-code]','input[inputmode=numeric]'];
                let el = null;
                for (const c of cands) { el = document.querySelector(c); if (el) break; }
                if (!el) return;
                el.focus(); el.value = code;
                el.dispatchEvent(new Event('input', {bubbles:true}));
            }""", code)
            time.sleep(1.2)
            page.evaluate("(() => { const b = document.querySelector('button[type=submit]'); if (b) b.click(); })()")
            time.sleep(8)
            st = page.evaluate("(() => ({url: location.href, body: document.body.innerText.slice(0,500)}))()")
            log(f"after code: {st['url'][:90]}")
            log("BODY: " + st["body"][:350].replace("\n", " | "))

    result["final_url"] = st["url"][:200]
    result["body"] = st["body"][:300]
    page.screenshot(path=OUT + r"\cb_state.png")

# --- API token via Basic Auth (works only if account activated) ---
import base64

def api(method, path, data=None, auth=True):
    h = {"Content-Type": "application/json"}
    if auth:
        cred = base64.b64encode(f"{username}:{password}".encode()).decode()
        h["Authorization"] = "Basic " + cred
    req = urllib.request.Request(
        API + path,
        data=json.dumps(data).encode() if data else None,
        headers=h,
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
    except Exception as e:
        return 0, {"err": str(e)[:80]}

stc, me = api("GET", "/user")
log(f"API /user: {stc} -> {str(me)[:120]}")
if stc == 200:
    stt, tok = api("POST", f"/users/{username}/tokens", {"name": "push", "scopes": ["write:repository", "read:user"]})
    log(f"API token: {stt} -> {str(tok)[:120]}")
    result["status"] = "OK"
    result["pat"] = tok.get("sha1")
    print(json.dumps(result))
else:
    result["status"] = "pending_activation"
    print(json.dumps(result))
