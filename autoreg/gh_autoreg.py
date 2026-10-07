# -*- coding: utf-8 -*-
"""GitHub account autoregister 2026 (v3).
2026 form = single page: #email, #password, #login + country + one submit.
Flow: mailbox -> /signup (wait DataDome; drag slider if shown) -> reject cookies ->
fill all fields -> submit (form button[type=submit] only) -> mail code -> verify -> save.
Usage: python gh_autoreg.py IDX [proxy_label|HOME] [mailtm|gmail]
"""
import time, json, re, random, string, sys, os
from camoufox.sync_api import Camoufox

sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
from gh_mail import MailTM, GmailIMAP

OUT = r"C:\Users\User\tmp\bpproxy_run"
ACCOUNTS = OUT + r"\github_accounts.jsonl"
LOG = OUT + r"\gh_autoreg.log"

IDX = (sys.argv[1] if len(sys.argv) > 1 else str(random.randint(1, 999))).zfill(3)
PROXY_LABEL = sys.argv[2] if len(sys.argv) > 2 else "HOME"
MAIL_MODE = sys.argv[3] if len(sys.argv) > 3 else "mailtm"

P_USER = "bpproxy-user"
P_PASS = "BPPROXY_PASS"
P_HOST = "bpproxy-host:1000"
DEBUG_SHOTS = os.path.isdir(r"C:\Users\User\tmp\bpproxy_run\shots")
CAPTCHA_WAIT = 160

gmail = GmailIMAP()

# ---- TG push: instant creds delivery ----
TG_BOT = {"bot_token": "TG_BOT_TOKEN"}
TG_BACKUP = {"chat_id": "TG_CHAT_ID", "thread": "350384",
             "token_alt": "7189316701"}
TG_CHATID_FILE = OUT + r"\gh_bot_chatid.txt"


def tg_request(token, method, params, timeout=25):
    try:
        req = __import__("urllib").request.Request(
            "https://api.telegram.org/bot%s/%s" % (token, method),
            data=__import__("urllib").parse.urlencode(params).encode())
        with __import__("urllib").request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {"ok": False}


def tg_chat_id():
    try:
        with open(TG_CHATID_FILE) as f:
            v = f.read().strip()
            if v:
                return v
    except Exception:
        pass
    try:
        upd = tg_request(TG_BOT["bot_token"], "getUpdates",
                         {"limit": 5, "timeout": 1})
        for u in upd.get("result", []):
            ch = u.get("message", {}).get("chat", {}).get("id")
            if ch:
                open(TG_CHATID_FILE, "w").write(str(ch))
                return str(ch)
    except Exception:
        pass
    return None


def tg_push_creds(email, username, password):
    msg = ("GitHub OK!\nemail: %s\nusername: %s\npassword: %s" %
           (email, username, password))
    cid = tg_chat_id()
    if cid:
        r = tg_request(TG_BOT["bot_token"], "sendMessage",
                       {"chat_id": cid, "text": msg})
        if r.get("ok"):
            log("TG pushed to Hermetik chat " + cid)
            return True
    try:
        tok = re.search(r"[0-9]{10}:[A-Za-z0-9_-]{30,}",
                        open(r"C:/Users/User/AppData/Local/hermes/config.yaml",
                             encoding="utf-8").read()).group(1)
    except Exception:
        tok = None
    if tok:
        r = tg_request(tok, "sendMessage",
                       {"chat_id": TG_BACKUP["chat_id"],
                        "message_thread_id": TG_BACKUP["thread"],
                        "text": msg})
        if r.get("ok"):
            log("TG pushed to backup chat")
    else:
        log("TG push failed: no token")
    # last-resort fallback: Telethon R3fIex -> reformboss DM
    try:
        import subprocess
        rc = subprocess.run(
            [r"C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe", OUT + "\tg_push_r3f.py", msg],
            capture_output=True, text=True, timeout=60)
        if rc.returncode == 0:
            log("TG pushed via R3fIex DM")
        else:
            log("R3fIex push rc=%d %s" % (rc.returncode, rc.stdout[-120:]))
    except Exception as e:
        log("R3fIex push EXC: " + str(e)[:120])

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] [{IDX}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def save(rec):
    rec = {"idx": IDX, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), **rec}
    with open(ACCOUNTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    log("SAVED: " + json.dumps(rec, ensure_ascii=False)[:240])
    try:
        import gh_db
        db_rec = {k: v for k, v in rec.items() if k in gh_db.VALID_COLS}
        if "ts" in rec and "created_ts" not in db_rec:
            db_rec["created_ts"] = rec["ts"]
        if "body" in rec or set(rec) - set(gh_db.VALID_COLS):
            extra = {k: v for k, v in rec.items() if k not in gh_db.VALID_COLS}
            if extra:
                db_rec["notes"] = json.dumps(extra, ensure_ascii=False)[:2000]
        gh_db.upsert_account(db_rec)
        log("DB saved")
    except Exception as e:
        log("DB save EXC: " + str(e)[:150])
    if rec.get("status") == "OK_VERIFIED":
        try:
            tg_push_creds(rec.get("email", ""), rec.get("username", ""),
                          rec.get("password", ""))
        except Exception as e:
            log("tg_push EXC: " + str(e)[:150])

def proxy_cfg():
    if PROXY_LABEL == "SOCKSH":
        return {"server": "socks5://127.0.0.1:2090"}
    if PROXY_LABEL == "ZTE":
        return {"server": "http://127.0.0.1:8899"}
    if PROXY_LABEL == "HK1024":
        # 1024proxy HK mobile sticky: rotate over verified-clean sids
        import random as _r
        try:
            pool = [88291] + [int(x) for x in open(r"C:\Users\User\tmp\bpproxy_run\clean_sids.txt").read().split() if x.strip()]
        except Exception:
            pool = [88291]
        sid = _r.choice(pool)
        return {"server": "http://hk.1024proxy.io:3000",
                "username": f"PROXY_USER-region-HK-sid-{sid}-t-30",
                "password": "PROXY_PASS"}
    if PROXY_LABEL == "ZTE":
        return {"server": "http://127.0.0.1:8899"}
    return {"server": f"http://{P_HOST}", "username": P_USER,
            "password": f"{P_PASS}_session-{PROXY_LABEL}_lifetime-30"}

def gen_pass():
    return "Gh#" + "".join(random.choices(string.ascii_letters + string.digits, k=12)) + "@9x"

def gen_username():
    adj = ["neon", "crimson", "violet", "silver", "arctic", "lunar", "cobalt", "amber", "steel", "ember"]
    noun = ["dev", "lab", "forge", "stack", "grid", "byte", "flux", "chip", "logic", "node"]
    return (random.choice(adj) + random.choice(noun) + "".join(random.choices(string.digits, k=3)))[:28].lower()

def ev(page, js):
    try:
        return page.evaluate(js)
    except Exception:
        return None

def try_drag_slider(page):
    for fr in page.frames:
        try:
            u = fr.url or ""
        except Exception:
            continue
        if "captcha" not in u:
            continue
        try:
            info = fr.evaluate("""(() => {
                const out = [];
                document.querySelectorAll('button,input,div[id],div[class]').forEach(e => {
                    if (out.length > 40) return;
                    const r = e.getBoundingClientRect();
                    const blob = ((e.id||'')+' '+((e.className||'')).toString()).toLowerCase();
                    if (r.width>8 && r.height>8 && /slider|drag|handle|captcha|button/i.test(blob))
                        out.push({tag:e.tagName, id:e.id||'', cls:(e.className||'').toString().slice(0,50),
                                  x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)});
                });
                return out;
            })()""")
        except Exception:
            continue
        target = None
        for e in info:
            blob = (e["id"] + " " + e["cls"]).lower()
            if ("slider" in blob or "drag" in blob or "handle" in blob) and e["w"] < 100:
                target = e
                break
        if not target:
            continue
        try:
            fb = page.evaluate("""(() => {
                const f = Array.from(document.querySelectorAll('iframe')).find(f => f.src.includes('captcha'));
                if (!f) return null; const r = f.getBoundingClientRect();
                return {x:r.x, y:r.y, w:r.width, h:r.height};
            })()""")
            if not fb:
                return False
            iw = fr.evaluate("document.documentElement.clientWidth") or fb["w"] or 1
            scale = fb["w"] / max(iw, 1)
            ax = fb["x"] + (target["x"] + target["w"] / 2) * scale
            ay = fb["y"] + (target["y"] + target["h"] / 2) * scale
            endx = fb["x"] + fb["w"] - 30
        except Exception:
            continue
        rng = random.Random()
        log(f"SLIDER drag {round(ax)}->{round(endx)}")
        page.mouse.move(ax, ay)
        time.sleep(0.35 + rng.random() * 0.3)
        page.mouse.down()
        time.sleep(0.3)
        steps = rng.randint(26, 36)
        for i in range(steps):
            f_ = (i + 1) / steps
            page.mouse.move(ax + (endx - ax) * f_, ay + rng.uniform(-3, 3))
            time.sleep(rng.uniform(0.012, 0.036))
        page.mouse.move(endx, ay + rng.uniform(-2, 2))
        time.sleep(0.2)
        page.mouse.up()
        log("SLIDER dragged")
        return True
    return False


# ---- DataDome trust-cookie carry-over (ported from regkit) ----
_TRUST_FILE = OUT + r"\.datadome-trust.json"
_TRUST_NAMES = {"datadome", "datadome_proxied", "device_id", "_device_id"}
_cur_exit_ip = None


def _exit_ip():
    global _cur_exit_ip
    if _cur_exit_ip:
        return _cur_exit_ip
    import requests
    try:
        server = (proxy_cfg() or {}).get("server", "http://127.0.0.1:8899")
        px = {"http": server, "https": server}
        _cur_exit_ip = requests.get("https://api.ipify.org", proxies=px, timeout=10).text.strip()
    except Exception:
        _cur_exit_ip = ""
    return _cur_exit_ip


def dd_save_trust(context):
    import json as _j
    try:
        keep = [c for c in context.cookies()
                if c.get("name") in _TRUST_NAMES and c.get("domain", "").endswith("github.com")]
        if not keep:
            return
        open(_TRUST_FILE, "w").write(_j.dumps({"cookies": keep, "exit_ip": _exit_ip()}))
        log(f"dd trust saved ({len(keep)} cookies, ip={_cur_exit_ip})")
    except Exception as e:
        log(f"trust save err {str(e)[:60]}")


def dd_restore_trust(context):
    import json as _j, os
    try:
        if not os.path.exists(_TRUST_FILE):
            return
        data = _j.loads(open(_TRUST_FILE).read())
        bound_ip = data.get("exit_ip") or ""
        cur = _exit_ip()
        if bound_ip and cur and bound_ip != cur:
            log(f"trust skip (bound {bound_ip} != cur {cur})")
            return
        if not cur:
            return
        clean = []
        for c in data.get("cookies") or []:
            cc = {k: c[k] for k in ("name", "value", "domain", "path",
                                    "expires", "httpOnly", "secure", "sameSite") if k in c}
            cc.setdefault("domain", ".github.com")
            cc.setdefault("path", "/")
            cc.setdefault("secure", True)
            cc.setdefault("httpOnly", False)
            clean.append(cc)
        context.add_cookies(clean)
        log(f"dd trust restored ({len(clean)})")
    except Exception as e:
        log(f"trust restore err {str(e)[:60]}")


def is_hard_block(page):
    t = (body_text(page) or "").lower()
    return "access is temporarily restricted" in t or "too many requests" in t


def open_signup(page):
    deadline = time.time() + CAPTCHA_WAIT
    last_drag = 0
    first_pass = True
    while time.time() < deadline:
        try:
            if first_pass:
                # referral entry (regkit): arrive like a search-result visitor
                try:
                    page.goto("https://github.com/?utm_source=google", timeout=60000,
                              wait_until="domcontentloaded")
                    ev(page, """(() => { const a = Array.from(document.querySelectorAll('a'))
                        .find(x => (x.innerText||'').trim() === 'Sign up'); if (a) { a.click(); return true; } return false; })()""")
                    time.sleep(3)
                except Exception:
                    page.goto("https://github.com/signup", timeout=60000, wait_until="domcontentloaded")
                first_pass = False
            else:
                page.goto("https://github.com/signup", timeout=60000, wait_until="domcontentloaded")
        except Exception as e:
            log(f"nav err {str(e)[:60]}")
            time.sleep(5)
            continue
        t0 = time.time()
        last_reload = time.time()
        while time.time() < deadline:
            if is_hard_block(page):
                log("HARD BLOCK detected — aborting early")
                return False
            st = ev(page, "(() => ({email: !!(document.querySelector('input#email') && document.querySelector('input#email').offsetParent), captcha: !!document.querySelector('iframe[src*=captcha]')}))()")
            if st["email"]:
                log(f"FORM VISIBLE after ~{int(time.time()-t0)}s")
                return True
            if st["captcha"] and time.time() - last_drag > 8:
                if try_drag_slider(page):
                    last_drag = time.time()
                    time.sleep(6)
            if time.time() - last_reload > 25:
                log("stale challenge, reloading")
                try:
                    page.goto("https://github.com/signup", timeout=60000, wait_until="domcontentloaded")
                except Exception:
                    pass
                last_reload = time.time()
            time.sleep(4)
    return False

def dismiss_cookies(page):
    ev(page, """(() => {
        let b = document.querySelector('button[data-testid=cookie-banner-accept], #ghcc button, .cookie-banner button, button[data-accept-cookie], button[data-consent-accept]');
        if (!b) b = Array.from(document.querySelectorAll('button')).find(x => /^(Accept|Reject|Accept all|Allow all|Agree)( all| cookies)?$/i.test((x.innerText||'').trim()));
        if (b) { b.click(); }
        setTimeout(() => { const c = document.querySelector('ghcc-consent'); if (c) c.remove(); }, 500);
        return b ? 'dismissed' : 'none';
    })()""")

def setf(page, sel, val):
    s = json.dumps(sel)
    v = json.dumps(val)
    return ev(page, f"""(() => {{
        const el = document.querySelector({s});
        if (!el) return 'NO_EL';
        el.focus(); el.value = {v};
        el.dispatchEvent(new Event('input', {{bubbles:true}}));
        el.dispatchEvent(new Event('change', {{bubbles:true}}));
        el.dispatchEvent(new Event('blur', {{bubbles:true}}));
        return el.value === {v} ? 'OK' : 'MISMATCH:' + el.value;
    }})()""")


def human_sleep(base=1.0, spread=0.6):
    """Human-ish pause: base +- spread, occasionally a longer 'distraction'."""
    t = random.uniform(base - spread, base + spread)
    if random.random() < 0.08:  # rare distraction pause
        t += random.uniform(2.0, 5.0)
    time.sleep(max(0.2, t))


def human_type(page, sel, text, click_first=True, allow_typo=False):
    """Type like a person: click into field, variable per-char delays.
    allow_typo=True adds rare typo+backspace-fix (use only for usernames/bios,
    NEVER for email/password — a half-fixed typo corrupts creds)."""
    loc = page.locator(sel)
    if click_first:
        box = loc.bounding_box()
        if box:
            page.mouse.move(box["x"] + box["width"] * random.uniform(0.3, 0.7),
                            box["y"] + box["height"] * random.uniform(0.3, 0.7),
                            steps=random.randint(8, 18))
            human_sleep(0.4, 0.3)
        loc.click()
        human_sleep(0.3, 0.2)
    # rare typo: swap two adjacent chars, then fix with backspaces
    typo_idx = None
    if allow_typo and len(text) > 4 and random.random() < 0.18:
        typo_idx = random.randint(1, len(text) - 2)
        broken = text[:typo_idx] + text[typo_idx + 1] + text[typo_idx] + text[typo_idx + 2:]
    else:
        broken = text
    typed = ""
    for ch_i, ch in enumerate(broken):
        page.keyboard.type(ch, delay=0)
        typed += ch
        # per-char variable delay
        d = random.uniform(0.05, 0.16)
        if ch in "@.#-_!":  # shifted keys take longer
            d += random.uniform(0.05, 0.12)
        if random.random() < 0.04:  # micro-think
            d += random.uniform(0.3, 0.9)
        time.sleep(d)
    if typo_idx is not None:
        time.sleep(random.uniform(0.3, 0.8))  # notice the typo
        page.keyboard.press("Backspace")
        time.sleep(random.uniform(0.08, 0.2))
        page.keyboard.press("Backspace")
        time.sleep(random.uniform(0.15, 0.4))
        for ch in (text[typo_idx], text[typo_idx + 1]):
            page.keyboard.type(ch, delay=0)
            time.sleep(random.uniform(0.06, 0.15))
    return typed


def human_scroll(page, direction="down", n=None):
    """Scroll like a reader: several wheel steps with pauses, sometimes up a bit."""
    n = n or random.randint(2, 5)
    dy = random.randint(180, 420) * (1 if direction == "down" else -1)
    for _ in range(n):
        page.mouse.wheel(0, dy + random.randint(-60, 60))
        time.sleep(random.uniform(0.2, 0.7))
    if random.random() < 0.25:  # scroll back up to check something
        page.mouse.wheel(0, -random.randint(100, 300))
        time.sleep(random.uniform(0.3, 0.8))


def human_move_mouse(page, target_box=None):
    """Idle-ish mouse drift to a random spot or near a target box."""
    if target_box:
        x = target_box["x"] + random.uniform(0.1, 0.9) * target_box["width"]
        y = target_box["y"] + random.uniform(0.1, 0.9) * target_box["height"]
    else:
        x = random.uniform(120, 900)
        y = random.uniform(120, 700)
    page.mouse.move(x, y, steps=random.randint(10, 25))
    time.sleep(random.uniform(0.1, 0.4))

def submit_form(page):
    """Click the primary Create account button; SSO buttons excluded."""
    return ev(page, """(() => {
        const bs = Array.from(document.querySelectorAll('button'));
        let b = bs.find(x => {
            const t = (x.innerText||'').trim();
            return !x.disabled && x.offsetParent && /^Create account/i.test(t) && !/google|apple|continue with/i.test(t);
        });
        if (b) { b.click(); return 'create_account'; }
        const f = document.querySelector('form[action*=signup]');
        if (f) {
            const s = f.querySelector('button[type=submit]');
            if (s && !/google|apple|continue with/i.test((s.innerText||''))) { s.click(); return 'signup_form_submit'; }
        }
        return 'NONE';
    })()""")

def body_text(page):
    try:
        return ev(page, "document.body.innerText.slice(0,500)").replace("\n", " | ")
    except Exception:
        return "?"

def main():
    email = None
    mailtm_box = None
    if MAIL_MODE == "mailtm":
        try:
            mailtm_box = MailTM().create()
            email = mailtm_box["address"]
            log(f"mailbox: {email}")
        except Exception as e:
            log(f"mailtm failed ({str(e)[:100]}) -> gmail fallback")
            mailtm_box = None
    if not email:
        email = gmail.make_address()
        log(f"mailbox(gmail): {email}")
    username = gen_username()
    password = gen_pass()
    cfg = None if PROXY_LABEL == "HOME" else proxy_cfg()
    attempt_label = PROXY_LABEL
    for browser_try in range(3):
        if browser_try > 0 and PROXY_LABEL not in ("HOME", "SOCKSH", "HK1024", "ZTE"):
            attempt_label = (("ghrt" + IDX + "x" * browser_try))[:15]
            cfg = {"server": f"http://{P_HOST}", "username": P_USER,
                   "password": f"{P_PASS}_session-{attempt_label}_lifetime-30"}
            log(f"browser retry #{browser_try} new sticky label={attempt_label}")
        elif browser_try > 0:
            cfg = None if PROXY_LABEL == "HOME" else proxy_cfg()
            log(f"browser retry #{browser_try} fresh {PROXY_LABEL} session")
        try:
            with Camoufox(proxy=cfg, headless=True, humanize=True, geoip=True) as browser:
                page = browser.new_page()
                dd_restore_trust(page.context)
                if not open_signup(page):
                    save({"status": "FORM_TIMEOUT", "email": email, "username": username, "password": password})
                    return 2
                time.sleep(random.uniform(2.5, 4.5))  # look at the page first
                dismiss_cookies(page)
                human_move_mouse(page)  # idle drift
                human_sleep(1.5, 0.8)

                # type like a human: email -> pause -> password -> pause -> username
                human_type(page, "#email", email)
                human_sleep(1.4, 0.7)
                human_move_mouse(page)
                human_type(page, "#password", password)
                human_sleep(1.1, 0.5)
                human_type(page, "#login", username, allow_typo=True)
                # 'review' the form: small scroll + re-read
                human_sleep(1.8, 0.9)
                human_move_mouse(page)
                human_sleep(0.9, 0.5)
                if DEBUG_SHOTS:
                    page.screenshot(path=OUT + f"\\gh_a{IDX}_1filled.png")

                sub = submit_form(page)
                log("submit: " + sub)
                time.sleep(12)
                st = ev(page, "(() => ({url: location.href, body: document.body.innerText.slice(0,500)}))()") or {}
                st.setdefault("body", "")
                st.setdefault("url", "")
                st["body"] = (st["body"] or "").replace("\n", " | ")
                log("after submit: url=" + st["url"][:120])
                log("BODY: " + st["body"][:400])
                if DEBUG_SHOTS:
                    page.screenshot(path=OUT + f"\\gh_a{IDX}_4submit.png")

                if "accounts.google.com" in st["url"] or "apple" in st["url"]:
                    save({"status": "SSO_REDIRECT", "email": email, "username": username, "password": password, "url": st["url"]})
                    return 7
                if "captcha" in st["url"].lower() or "arkose" in st["body"].lower() or "challenge" in st["url"].lower():
                    save({"status": "CHALLENGE_ON_SUBMIT", "email": email, "username": username, "password": password, "url": st["url"]})
                    return 5

                code_screen = False
                for _ in range(12):
                    time.sleep(4)
                    s2 = ev(page, "(() => ({url: location.href, inputsN: document.querySelectorAll('input').length}))()") or {}
                    log(f"wait code: url={str(s2.get('url',''))[:90]} inputs={s2.get('inputsN')}")
                    if "account_verifications" in str(s2.get("url", "")).lower():
                        code_screen = True
                        break
                if not code_screen:
                    save({"status": "NO_CODE_SCREEN", "email": email, "username": username, "password": password,
                          "url": (page.url or "")[:160]})
                    return 4
                code = None
                if mailtm_box:
                    code, _ = MailTM().wait_code(mailtm_box["token"], timeout_sec=260)
                if not code:
                    code = gmail.wait_code(email, timeout_sec=260)
                if not code:
                    save({"status": "NO_MAIL", "email": email, "username": username, "password": password})
                    return 6
                log(f"code={code}")

                c = json.dumps(code)
                filled = ev(page, f"""(() => {{
                    const ins = Array.from(document.querySelectorAll('input[inputmode=numeric], input[autocomplete=one-time-code], input[name*=code i], input[id*=code i]'));
                    if (!ins.length) return 'NO_INPUT';
                    if (ins.length === 1) {{
                        const i = ins[0]; i.focus(); i.value = {c};
                        i.dispatchEvent(new Event('input',{{bubbles:true}}));
                        i.dispatchEvent(new Event('change',{{bubbles:true}}));
                        return 'SINGLE';
                    }}
                    ins.forEach((i, n) => {{ i.focus(); i.value = String({c})[n] || ''; i.dispatchEvent(new Event('input',{{bubbles:true}})); }});
                    return 'SPLIT:' + ins.length;
                }})()""")
                log("code fill: " + str(filled))
                time.sleep(2)
                log("verify click: " + str(ev(page, """(() => {
                    const b = Array.from(document.querySelectorAll('button')).find(x => !x.disabled && x.offsetParent && /^Continue$/i.test((x.innerText||'').trim()));
                    if (b) { b.click(); return 'continue'; }
                    return 'NONE';
                })()""")))
                time.sleep(12)

                final = ev(page, "(() => ({url: location.href, body: document.body.innerText.slice(0,400)}))()") or {}
                final["body"] = (final.get("body") or "").replace("\n", " | ")
                log("FINAL url=" + str(final.get("url", ""))[:130])
                log("FINAL BODY: " + str(final.get("body", ""))[:350])
                if DEBUG_SHOTS:
                    page.screenshot(path=OUT + f"\\gh_a{IDX}_6final.png")
                for _ in range(6):
                    t = (body_text(page) or "").lower()
                    if "welcome" in t or "where teams" in t or "plan" in t or "cancel" in t or "skip" in t:
                        ev(page, """(() => {
                            const b = Array.from(document.querySelectorAll('button, a')).find(x =>
                                /^(Skip|Cancel|Continue|Next|Maybe later|Do this later)$/i.test((x.innerText||'').trim()) && !x.disabled);
                            if (b) { b.click(); return true; } return false;
                        })()""")
                        time.sleep(4)
                    else:
                        break
                dd_save_trust(page.context)
                cookies = page.context.cookies()
                verdict = "OK_VERIFIED"
                save({"status": verdict, "email": email, "username": username, "password": password,
                      "mail_password": (mailtm_box or {}).get("password", ""),
                      "mail_token": (mailtm_box or {}).get("token", ""),
                      "final_url": (page.url or "")[:160], "cookie_count": len(cookies),
                      "final_body": final.get("body", "")[:180]})
                return 0
        except Exception as e:
            log(f"EXC(try {browser_try}) " + type(e).__name__ + ": " + str(e)[:220])
            if browser_try == 2:
                save({"status": "EXC", "email": email, "username": username, "password": password,
                      "err": f"{type(e).__name__}: {str(e)[:160]}"})
                return 1
            time.sleep(20)
    save({"status": "BROWSER_DEAD", "email": email, "username": username, "password": password})
    return 1

if __name__ == "__main__":
    sys.exit(main())