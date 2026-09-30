# GitLab reg: HOME + gmail alias (IMAP code)
import json
import random
import re
import string
import sys
import time

sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
from camoufox.sync_api import Camoufox
from gh_mail import GmailIMAP

SIGNUP_URL = "https://gitlab.com/users/sign_up"
OUT = r"C:\Users\User\tmp\bpproxy_run"
ACC = OUT + r"\gitlab_accounts.jsonl"

FIRST = ["Diego", "Mateo", "Sofia", "Valentina", "Lucas", "Camila", "Martin", "Elena", "Andres", "Isabel", "Javier", "Natalia", "Pablo", "Lucia", "Marco", "Ana"]
LAST = ["Costa", "Silva", "Rodriguez", "Martinez", "Lopez", "Garcia", "Pereira", "Fernandez", "Rojas", "Moreno", "Vargas", "Castro", "Ramos", "Suarez", "Medina", "Ortiz"]

gmail = GmailIMAP()
addr = gmail.make_address()
print(f"[{time.strftime('%H:%M:%S')}] gmail alias: {addr}", flush=True)

first, last = random.choice(FIRST), random.choice(LAST)
username = (first.lower() + last.lower() + random.choice(["", "dev", "42", "77"]) + "".join(random.choices(string.digits, k=2)))[:28]
password = "Gl#" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "!7"
print(f"account: {username}", flush=True)


def save(**kw):
    kw["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(ACC, "a", encoding="utf-8") as f:
        f.write(json.dumps(kw, ensure_ascii=False) + "\n")


with Camoufox(headless=True, humanize=True) as browser:
    page = browser.new_page()
    page.goto(SIGNUP_URL, timeout=90000, wait_until="domcontentloaded")
    page.wait_for_selector("#new_user_email", timeout=25000)
    time.sleep(3)

    for sel, val, d in [("#new_user_first_name", first, 0.5), ("#new_user_last_name", last, 0.4),
                        ("#new_user_username", username, 0.6), ("#new_user_email", addr, 0.6),
                        ("#new_user_password", password, 0.8)]:
        try:
            page.fill(sel, val, timeout=8000)
            time.sleep(d)
        except Exception as e:
            print(f"fill {sel}: ERR {str(e)[:60]}", flush=True)
    time.sleep(1)

    try:
        page.click("button[type=submit], input[type=submit]", timeout=10000)
    except Exception:
        page.evaluate("(() => { const b = document.querySelector('button[type=submit]') || document.querySelector('.btn-confirm') || document.querySelector('button'); if (b) b.click(); })()")
    time.sleep(6)

    for _ in range(12):
        try:
            body = page.evaluate("document.body.innerText.slice(0,300)") or ""
        except Exception:
            body = ""
        if re.search(r"Just a moment|checking your browser|verifies that you", body, re.I):
            time.sleep(4)
            continue
        break

    st = page.evaluate("(() => ({url: location.href, arkose: !!document.querySelector('iframe[src*=arkoselabs]'), body: document.body.innerText.slice(0,400)}))()")
    print(f"after submit: {st['url'][:90]} arkose={st['arkose']}", flush=True)
    print("BODY: " + st["body"][:250].replace("\n", " | "), flush=True)

    if "identity_verification" not in st["url"]:
        page.screenshot(path=OUT + r"\gl_g_state.png")
        save(status="unexpected", username=username, password=password, email=addr, url=st["url"], body=st["body"][:200])
        print(json.dumps({"status": "unexpected", "url": st["url"], "body": st["body"][:200]}))
        sys.exit(0)

    print("flow: identity_verification", flush=True)
    has_input = page.evaluate("(() => !!document.querySelector('input[inputmode=numeric], input[name*=code i], input[id*=code i], input[type=tel]'))()")
    if not has_input:
        sb = page.evaluate("""(() => { const btns = Array.from(document.querySelectorAll('button, a')); const b = btns.find(x => /Send|Get|Code|Verif|Enviar/i.test((x.innerText||''))); if (b) { b.click(); return (b.innerText||'').trim(); } return null; })()""")
        print(f"clicked send: {sb}", flush=True)
        time.sleep(6)

    code = gmail.wait_code(addr, timeout_sec=300)
    print(f"code: {code}", flush=True)
    if not code:
        save(status="no_code", username=username, password=password, email=addr)
        page.screenshot(path=OUT + r"\gl_g_nocode.png")
        sys.exit(4)

    page.evaluate("""(code) => {
        const cands = ['input[name*=code i]','input[id*=code i]','input[name*=verification i]','input[id*=verification i]','input[autocomplete=one-time-code]','input[inputmode=numeric]','input[type=tel]'];
        let el = null;
        for (const c of cands) { el = document.querySelector(c); if (el) break; }
        if (!el) return;
        el.focus(); el.value = code;
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
    }""", code)
    time.sleep(1.2)
    page.evaluate("(() => { const b = document.querySelector('button[type=submit]') || document.querySelector('.btn-confirm'); if (b) b.click(); })()")
    time.sleep(9)

    s2 = page.evaluate("(() => ({url: location.href, body: document.body.innerText.slice(0,900)}))()")
    print("STEP2 url=" + s2["url"][:90], flush=True)
    print("STEP2 BODY: " + s2["body"][:600].replace("\n", " | "), flush=True)
    page.screenshot(path=OUT + r"\gl_g_step2.png")
    save(status="iv_done", username=username, password=password, email=addr, step2_url=s2["url"], step2_body=s2["body"][:300])
    print(json.dumps({"username": username, "password": password, "email": addr,
                      "step2_url": s2["url"], "step2_body": s2["body"][:300]}))
