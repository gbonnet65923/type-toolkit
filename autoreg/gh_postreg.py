# -*- coding: utf-8 -*-
"""GitHub post-registration profiler + 2FA hardening.

For each OK_VERIFIED account from accounts.db:
  1. login (email + password) through Camoufox
  2. generate + upload avatar (Pillow, identicon-style gradient)
  3. set bio + name (profile "oformlenie")
  4. change username (fresh, non-patterned)
  5. create own repo OR fork a real one (README with content)
  6. enable TOTP 2FA, download backup codes
  7. save everything back to accounts.db, push creds to TG

Usage:
  python gh_postreg.py [limit] [username_filter]
  python gh_postreg.py 1              # one oldest account
  python gh_postreg.py 0 cobaltdev128 # exactly this account
"""
import time, json, re, sys, os, random, string, base64, io

sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
import gh_db
from gh_db import upsert_account

from camoufox.sync_api import Camoufox
import pyotp
from PIL import Image, ImageDraw
from gh_autoreg import human_sleep, human_type, human_scroll, human_move_mouse

OUT = r"C:\Users\User\tmp\bpproxy_run"
AVATARS = OUT + r"\avatars"
LOG = OUT + r"\gh_postreg.log"

P_USER = "bpproxy-user"
P_PASS = "BPPROXY_PASS"
P_HOST = "bpproxy-host:1000"

FORK_TARGETS = [
    ("awesome-chatgpt-prompts", "f/awesome-chatgpt-prompts"),
    ("public-api", "public-api"),
]
REPO_TOPICS = ["automation", "tools", "python", "scripts", "web", "api", "dev", "utils"]

# bios pool (short, human, no AI-isms)
BIOS = [
    "tinkering with python & web automation",
    "building small tools that do boring stuff",
    "dev tools, scripts, occasional scraping",
    "python / js. mostly experiments here",
    "code, coffee, side projects",
    "making repos so my scripts have a home",
    "software tinkering. random useful stuff",
]
NAMES_POOL = [
    ("Alex", "Moreau"), ("Sam", "Ridley"), ("Kai", "Novak"), ("Robin", "Hale"),
    ("Jesse", "Linden"), ("Morgan", "Reyes"), ("Ash", "Brennan"), ("Drew", "Karlsen"),
    ("Casey", "Volker"), ("Noel", "Ferrer"),
]

REPO_README = """# {repo}

{tagline}

## What's inside

- {item1}
- {item2}
- {item3}

## Notes

{note}

Made with too much coffee. License: MIT.
"""


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def proxy_cfg(label):
    if label == "HOME":
        return None
    if label == "ZTE":
        return {"server": "http://127.0.0.1:8899"}
    if label == "HK1024":
        import random as _r
        try:
            pool = [88291] + [int(x) for x in open(r"C:\Users\User\tmp\bpproxy_run\clean_sids.txt").read().split() if x.strip()]
        except Exception:
            pool = [88291]
        sid = _r.choice(pool)
        return {"server": "http://hk.1024proxy.io:3000",
                "username": f"PROXY_USER-region-HK-sid-{sid}-t-30",
                "password": "PROXY_PASS"}
    return {"server": f"http://{P_HOST}", "username": P_USER,
            "password": f"{P_PASS}_session-{label}_lifetime-30"}


def gen_new_username():
    """less bot-looking than adj+noun+3digits: word+digits, sometimes underscore."""
    words = ["harbor", "quill", "fjord", "wren", "onyx", "cedar", "maple", "rune",
             "solace", "vector", "kestrel", "lumen", "cobble", "thistle", "brisk",
             "hollow", "gravel", "saffron", "tidal", "ember"]
    w = random.choice(words)
    style = random.randint(0, 3)
    if style == 0:
        return w + str(random.randint(2, 99))
    if style == 1:
        return w + "_" + random.choice(["dev", "ops", "hq", "labs", "x"]) + str(random.randint(1, 99))
    if style == 2:
        return random.choice(words) + random.choice(words) + str(random.randint(1, 999))
    return w + str(random.randint(1000, 99999))


def make_avatar(seed):
    """Deterministic gradient identicon 512x512, saved to avatars/<seed>.png"""
    os.makedirs(AVATARS, exist_ok=True)
    path = os.path.join(AVATARS, seed + ".png")
    if os.path.exists(path):
        return path
    rnd = random.Random(seed)
    h = rnd.randint(0, 359)
    base = (h, rnd.randint(55, 75), rnd.randint(45, 65))
    h2 = (h + rnd.randint(30, 120)) % 360
    img = Image.new("RGB", (512, 512))
    dr = ImageDraw.Draw(img, "RGBA")

    def hx(hh, ss, vv):
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hh / 360, ss / 100, vv / 100)
        return (int(r * 255), int(g * 255), int(b * 255))

    for y in range(512):
        t = y / 511
        # gradient blend h->h2
        hh = (h + (h2 - h) * t) % 360
        ss = base[1] + (30 - 60 * t)
        vv = base[2] + (25 - 10 * t)
        dr.line([(0, y), (512, y)], fill=hx(hh, max(15, min(90, ss)), max(35, min(80, vv))))
    # random geometric overlay blocks
    for _ in range(rnd.randint(6, 12)):
        x0, y0 = rnd.randint(-60, 460), rnd.randint(-60, 460)
        s = rnd.randint(40, 200)
        alpha = rnd.randint(30, 90)
        col = hx((h + rnd.randint(0, 90)) % 360, rnd.randint(40, 80), rnd.randint(50, 90)) + (alpha,)
        if rnd.random() < 0.5:
            dr.rounded_rectangle([x0, y0, x0 + s, y0 + s], radius=s // 6, fill=col)
        else:
            dr.ellipse([x0, y0, x0 + s, y0 + s], fill=col)
    img.save(path, "PNG")
    return path


def ev(page, js):
    try:
        return page.evaluate(js)
    except Exception:
        return None


def body_text(page):
    try:
        return (page.evaluate("document.body.innerText") or "")[:2000]
    except Exception:
        return ""


def login(page, email, password, username):
    page.goto("https://github.com/login", timeout=90000,
              wait_until="domcontentloaded")
    human_sleep(3.0, 1.5)  # read the page
    human_move_mouse(page)
    human_scroll(page, "down", n=random.randint(1, 2))
    human_scroll(page, "up", n=1)
    human_sleep(1.2, 0.6)
    # type email like a person (no instant fill)
    human_type(page, "#login_field", email)
    human_sleep(1.3, 0.7)
    human_type(page, "#password", password)
    human_sleep(1.5, 0.8)
    page.screenshot(path=OUT + "\\pr_login_filled.png")
    # human pause before submit
    human_move_mouse(page)
    human_sleep(0.9, 0.5)
    page.click("input[name=commit], button[type=submit]")
    human_sleep(10, 3)
    url = page.url
    log("login url: " + url[:120])
    body = body_text(page)
    if "two-factor" in url or "2fa" in url:
        return "2FA_ALREADY", None
    if "Incorrect username or password" in body:
        return "BAD_CREDS", None
    # device verification screen (email code) — BEFORE generic /session check,
    # because its url contains /sessions/verified-device
    if "verified-device" in url or ("verify" in body.lower() and "code" in body.lower()
                                    and "resend" in body.lower()):
        return "DEVICE_VERIFY", url
    if "/session" in url:
        return "LOGIN_FAIL", None
    return "OK", url


def wait_device_code(page, account, timeout_sec=280):
    """If GitHub wants email device verification code, fetch it from mail."""
    from gh_mail import MailTM, GmailIMAP
    email = account["email"]
    code = None
    if account.get("mail_token"):
        code, _ = MailTM().wait_code(account["mail_token"], timeout_sec=timeout_sec,
                                     pattern=r"\b(\d{6,8})\b")
    if not code and "+ghsig" in (email or ""):
        code = GmailIMAP().wait_code(email, timeout_sec=timeout_sec)
    if not code:
        return False
    log(f"device code={code}")
    # type code like a human (found in live flow: #app_totp / numeric inputs)
    human_sleep(1.5, 0.8)  # "check the phone/email" pause
    sel = "input[name=otp], input[name=app_otp], input[autocomplete=one-time-code]"
    try:
        loc = page.locator(sel).first
        loc.wait_for(state="visible", timeout=8000)
        loc.click()
        loc.press_sequentially(str(code), delay=random.uniform(90, 160))
    except Exception as e:
        log("devver typewriter fallback: " + str(e)[:60])
        ev(page, f"""(() => {{
            const ins = Array.from(document.querySelectorAll('input[inputmode=numeric], input[autocomplete=one-time-code], input[name*=code i], input[id*=code i]'));
            if (!ins.length) return 'NO_INPUT';
            if (ins.length === 1) {{
                const i = ins[0]; i.focus(); i.value = {json.dumps(str(code))};
                i.dispatchEvent(new Event('input',{{bubbles:true}}));
                i.dispatchEvent(new Event('change',{{bubbles:true}}));
                return 'SINGLE';
            }}
            ins.forEach((i, n) => {{ i.focus(); i.value = String({json.dumps(str(code))})[n] || ''; i.dispatchEvent(new Event('input',{{bubbles:true}})); }});
            return 'SPLIT:' + ins.length;
        }})()""")
    human_sleep(2.0, 0.8)
    ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => !x.disabled && x.offsetParent && /verify/i.test((x.innerText||'').trim()));
        if (b) { b.click(); return true; }
        return false;
    })()""")
    time.sleep(10)
    return "/login" not in page.url


def upload_avatar(page, path):
    page.goto("https://github.com/settings/profile", timeout=90000,
              wait_until="domcontentloaded")
    human_sleep(3.0, 1.2)
    try:
        inp = page.query_selector("#avatar_upload, input[type=file][accept*=image], input.js-profile-file-edit")
        if not inp:
            # 2026 UI: avatar edit under button
            human_move_mouse(page)
            human_sleep(0.8, 0.4)
            ev(page, """(() => {
                const b = Array.from(document.querySelectorAll('button, summary')).find(x => /avatar|photo|picture/i.test((x.innerText||'') + (x.getAttribute('aria-label')||'')));
                if (b) { b.click(); return true; } return false;
            })()""")
            human_sleep(2.0, 0.8)
            inp = page.query_selector("input[type=file]")
        if not inp:
            return "NO_FILE_INPUT"
        inp.set_input_files(path)
        human_sleep(3.0, 1.0)  # photo 'processing'
        # crop/scale dialog may appear -> confirm
        ev(page, """(() => {
            const b = Array.from(document.querySelectorAll('button')).find(x => !x.disabled && /^(set new profile photo|save|apply|use photo|confirm)$/i.test((x.innerText||'').trim()));
            if (b) { b.click(); return 'SET'; } return 'NOBTN';
        })()""")
        human_sleep(4.0, 1.5)
        save_profile_settings(page)
        return "OK"
    except Exception as e:
        return "AVATAR_EXC:" + str(e)[:80]


def save_profile_settings(page):
    ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => !x.disabled && /^update profile$/i.test((x.innerText||'').trim()));
        if (b) { b.click(); return true; }
        const b2 = document.querySelector("button[data-testid='update-profile-button'], .js-profile-editable-save button");
        if (b2) { b2.click(); return true; }
        return false;
    })()""")
    time.sleep(5)


def set_profile(page, first, last, bio):
    try:
        if "settings/profile" not in page.url:
            page.goto("https://github.com/settings/profile", timeout=90000,
                      wait_until="domcontentloaded")
    except Exception:
        pass  # avatar step already navigated; double-nav race is harmless
    human_sleep(3.0, 1.2)
    human_scroll(page, "down", n=random.randint(1, 3))  # look around settings
    human_sleep(1.0, 0.5)
    # name — type like a person
    name_sel = "#user_display_name, #user_profile_name, input[name='user[profile_name]']"
    try:
        el = page.query_selector(name_sel.replace(", ", ", "))
        if el:
            human_type(page, name_sel.split(",")[0].strip(), f"{first} {last}")
    except Exception as e:
        log("name fill exc: " + str(e)[:60])
    human_sleep(1.2, 0.6)
    # bio
    bio_sel = "#user_profile_bio, textarea[name='user[profile_bio]']"
    try:
        human_type(page, bio_sel.split(",")[0].strip(), bio, click_first=True)
    except Exception as e:
        log("bio fill exc: " + str(e)[:60])
    human_sleep(1.5, 0.7)
    page.screenshot(path=OUT + "\\pr_profile_filled.png")
    save_profile_settings(page)
    human_sleep(2.5, 1.0)


def change_username(page, new_username):
    page.goto("https://github.com/settings/admin", timeout=90000)
    time.sleep(4)
    body = body_text(page)
    if "change username" not in body.lower() and "Change your username" not in body:
        log("no change-username block visible; trying UI anyway")
    ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button, summary, a')).find(x => /change username/i.test((x.innerText||'').trim()));
        if (b) { b.click(); return true; } return false;
    })()""")
    time.sleep(2.5)
    # danger-zone modal with input
    filled = ev(page, """(() => {
        const inp = Array.from(document.querySelectorAll('input[aria-describedby], input[name*=login i], input[placeholder*=current i]'))
            .find(i => i.offsetParent);
        if (!inp) return 'NO_INP';
        inp.focus();
        return 'FOUND:' + (inp.name || inp.id || 'x');
    })()""")
    log("rename input: " + str(filled))
    # type new name into the dialog field
    try:
        el = page.query_selector("input[name*='login' i], dialog input, modal input")
        if el:
            el.fill(new_username)
    except Exception:
        pass
    time.sleep(1)
    r = ev(page, """(() => {
        const dlg = document.querySelector('dialog[open], .Overlay, [role=dialog]');
        const scope = dlg || document;
        const b = Array.from(scope.querySelectorAll('button')).find(x => /update username|change username|rename/i.test((x.innerText||'').trim()) && !x.disabled);
        if (b) { b.click(); return 'CLICKED'; }
        return 'NOBTN';
    })()""")
    log("rename click: " + str(r))
    time.sleep(8)
    # confirm page: "I understand, update my username"
    r2 = ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => /i understand, update/i.test((x.innerText||'').trim()) && !x.disabled);
        if (b) { b.click(); return 'CONFIRM'; }
        return 'NOCONFIRM';
    })()""")
    log("rename confirm: " + str(r2))
    time.sleep(10)
    url = page.url
    ok = "admin" in url or page.query_selector("input[name*=login i]") is None
    # verify on profile
    page.goto(f"https://github.com/{new_username}", timeout=90000)
    time.sleep(4)
    notfound = "404" in body_text(page)[:200] or "This is not the web page" in body_text(page)
    if notfound:
        return False
    return True


def create_repo(page, repo_name, account):
    """2026 UI: #repository-name-input, Public toggle-button, Create repository submit."""
    page.goto("https://github.com/new", timeout=90000,
              wait_until="domcontentloaded")
    human_sleep(4.0, 1.5)  # read the form
    human_scroll(page, "down", n=random.randint(1, 3))
    human_scroll(page, "up", n=1)
    human_sleep(1.2, 0.6)
    # name (new 2026 input) — typed char by char
    try:
        page.wait_for_selector("#repository-name-input", timeout=30000)
        loc = page.locator("#repository-name-input")
        loc.click()
        loc.press_sequentially(repo_name, delay=random.uniform(80, 150))
        human_sleep(2.0, 0.8)
    except Exception as e:
        log("repo name fill exc: " + str(e)[:80])
        return False
    # description
    try:
        loc = page.locator("input[name='Description']")
        loc.click()
        loc.press_sequentially(random.choice([
            "small tools collection", "automation scripts", "helper utilities",
            "misc dev experiments", "tiny python utilities"])[:80],
            delay=random.uniform(30, 90))
        human_sleep(1.2, 0.6)
    except Exception:
        pass
    # Public (button in 2026 UI)
    ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => /^public$/i.test((x.innerText||'').trim()) && x.offsetParent !== null);
        if (b) { b.click(); return 'public'; }
        const r = document.querySelector('input#repository_visibility_public, input[name=repository_visibility][value=public]');
        if (r) { r.click(); return 'radio'; }
        return 'none';
    })()""")
    human_sleep(1.3, 0.6)
    # "Add a README" (checkbox or button in new UI)
    ev(page, """(() => {
        const c = document.querySelector('#repository_auto_init, input[name=auto_init]');
        if (c) { c.click(); return 'old'; }
        const b = Array.from(document.querySelectorAll('button, label, summary')).find(x => /readme/i.test((x.innerText||'').trim()) && x.offsetParent !== null);
        if (b) { b.click(); return 'btn'; }
        return 'none';
    })()""")
    human_sleep(1.5, 0.7)
    page.screenshot(path=OUT + "\\pr_repo_form.png")
    # submit "Create repository"
    r = ev(page, """(() => {
        const b = Array.from(document.querySelectorAll('button[type=submit], button')).find(x => /create repository/i.test((x.innerText||'').trim()) && x.offsetParent !== null);
        if (b && !b.disabled) { b.click(); return 'CLICK'; }
        return 'DISABLED';
    })()""")
    log("repo create click: " + str(r))
    time.sleep(14)
    # verify creation: page may sit at /new while redirect completes — re-check url + repo page
    ok_url = repo_name in page.url and "/new" not in page.url
    if not ok_url:
        try:
            page.goto(f"https://github.com/{account['username']}/{repo_name}",
                      timeout=60000, wait_until="domcontentloaded")
            time.sleep(3)
            ok_url = "Page not found" not in (body_text(page) or "")
        except Exception:
            ok_url = False
    if ok_url:
        # edit README with real content
        try:
            page.goto(f"https://github.com/{account['username']}/{repo_name}/edit/main/README.md",
                      timeout=90000)
            time.sleep(3)
            tagline = random.choice([
                "assorted scripts and tools", "random dev utilities",
                "small tools, nothing fancy", "stuff that automates stuff"])
            content = REPO_README.format(
                repo=repo_name, tagline=tagline,
                item1=random.choice(["CLI helpers", "scrapers", "file utilities", "API wrappers"]),
                item2=random.choice(["backup scripts", "cron jobs", "one-off experiments", "glue code"]),
                item3=random.choice(["notes & docs", "tiny libs", "docker snippets", "config templates"]),
                note=random.choice([
                    "Mostly for personal use, shared in case it helps.",
                    "Written late at night, works on my machine.",
                    "Refactor when time allows.",
                    "See commits for the mess in progress."]))
            ed = page.query_selector("textarea, div.CodeMirror, [role=textbox]")
            if ed:
                try:
                    ed.fill("")
                    ed.fill(content)
                except Exception:
                    ev(page, """(() => {
                        const t = document.querySelector('textarea');
                        if (t) { t.value = %s; t.dispatchEvent(new Event('input',{bubbles:true})); }
                    })()""" % json.dumps(content))
            page.screenshot(path=OUT + "\\pr_readme_edit.png")
            ev(page, """(() => {
                const b = document.querySelector("button[type=submit], .Button--primary");
                if (b && !b.disabled) { b.click(); return 'COMMIT'; }
                return 'NO';
            })()""")
            time.sleep(8)
        except Exception as e:
            log("readme edit exc: " + str(e)[:80])
        return True
    return False


def fork_repo(page):
    target = random.choice(["microsoft/WSL", "torvalds/linux", "psf/requests",
                            "tiangolo/fastapi", "sindresorhus/awesome"])
    log(f"fork target: {target}")
    page.goto(f"https://github.com/{target}/fork", timeout=90000,
              wait_until="domcontentloaded")
    human_sleep(4.0, 1.5)  # look at the fork page
    human_scroll(page, "down", n=random.randint(1, 2))
    r = ev(page, """(() => {
        const b = document.querySelector('.Button--primary, button[type=submit]');
        const b2 = Array.from(document.querySelectorAll('button')).find(x => /^create fork$/i.test((x.innerText||'').trim()));
        const bb = b2 || b;
        if (bb && !bb.disabled) { bb.click(); return 'CLICK'; }
        return 'FAIL:' + (bb ? bb.disabled : 'nobtn');
    })()""")
    log("fork click: " + str(r))
    human_sleep(15, 4)
    body = body_text(page)
    return "forked" in body.lower() or "already exists" in body.lower() or "your fork" in body.lower()


def enable_2fa_totp(page, uname):
    """Enable TOTP 2FA via wizard (verified live flow 2026-09).
    Returns (totp_secret, backup_codes_list) or (None, None)."""
    page.goto("https://github.com/settings/two_factor_authentication/setup/intro",
              timeout=90000, wait_until="domcontentloaded")
    human_sleep(5.0, 1.5)  # read the wizard
    human_scroll(page, "down", n=random.randint(1, 2))
    body = body_text(page)
    if "two-factor authentication" in body and "setup" not in page.url:
        log("2fa: already enabled?")
        return "ALREADY", None
    # 1. open "setup key" dialog
    page.evaluate("""(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => /setup key/i.test((x.innerText||'').trim()));
 if (b) b.click();
    })()""")
    time.sleep(3)
    # 2. extract secret from dialog
    secret = page.evaluate("""(() => {
        const dlg = document.querySelector('dialog[open]');
        const m = (dlg || document).innerText.match(/\\b([A-Z2-7]{16,})\\b/);
        return m ? m[1] : null;
    })()""")
    log("2fa secret: " + str(secret))
    if not secret:
        page.screenshot(path=OUT + f"\\pr_2fa_nosecret_{uname}.png")
        return None, None
    # 3. close dialog (X button, fallback Escape)
    closed = page.evaluate("""(() => {
        const dlg = document.querySelector('dialog[open]');
        if (!dlg) return 'nodialog';
        const x = dlg.querySelector('button[aria-label="Close"], .Overlay-closeButton, button[data-close-dialog-id]');
        if (x) { x.click(); return 'x'; }
        return 'nox';
    })()""")
    log("2fa dialog close: " + str(closed))
    if closed == "nox":
        page.keyboard.press("Escape")
    time.sleep(2)
    # dialog may persist — force remove overlay via Escape if still open
    still = page.evaluate("(() => !!document.querySelector('dialog[open]'))()")
    if still:
        page.keyboard.press("Escape")
        time.sleep(1.5)
        page.evaluate("""(() => {
            const dlg = document.querySelector('dialog[open]');
            if (dlg) dlg.close ? dlg.close() : dlg.removeAttribute('open');
        })()""")
        time.sleep(1)
    # 4. type TOTP code: focus via evaluate + keyboard.type (survives overlay/viewport issues)
    # human touch: 'open authenticator app' pause + variable per-key delay
    human_sleep(1.8, 0.9)
    entered = False
    for attempt in range(2):
        code = pyotp.TOTP(secret).now()
        log(f"2fa code={code} (attempt {attempt + 1})")
        page.evaluate("""(() => {
            const i = document.querySelector("input[name=otp][data-target*='appOtpInput']");
            if (i) { i.scrollIntoView({block: 'center'}); i.focus(); }
        })()""")
        human_sleep(0.9, 0.4)
        # variable typing speed, occasional slow key
        for ch in str(code):
            page.keyboard.type(ch, delay=0)
            d = random.uniform(0.09, 0.22)
            if random.random() < 0.15:
                d += random.uniform(0.2, 0.5)
            time.sleep(d)
        time.sleep(2.5)
        # verify value landed
        val = page.evaluate("""(() => document.querySelector("input[name=otp][data-target*='appOtpInput']").value)""")
        if val == code:
            entered = True
            # 5. scroll to Continue + click
            page.evaluate("""(() => {
                const b = Array.from(document.querySelectorAll('button')).find(x => /^continue$/i.test((x.innerText||'').trim()));
                if (b) b.scrollIntoView({block: 'center'});
            })()""")
            time.sleep(1)
            r = page.evaluate("""(() => {
                const b = Array.from(document.querySelectorAll('button')).find(x => /^continue$/i.test((x.innerText||'').trim()));
                if (b && !b.disabled) { b.click(); return 'clicked'; }
 return 'state:' + (b ? b.disabled : 'nobtn');
            })()""")
            log("2fa continue: " + str(r))
            # nobtn == step already advanced (observed live) — treat as success
            if r in ("clicked", "state:nobtn", "state:false"):
                break
        # code window rotated — retry
        time.sleep(5)
    if not entered:
        page.screenshot(path=OUT + f"\\pr_2fa_nocontinue_{uname}.png")
        return secret, None
    time.sleep(15)
    # 6. recovery step: download codes file (this also unlocks "I have saved")
    body = page.evaluate("document.body.innerText")
    m = re.search(r"\b([0-9a-f]{6}(?:-[0-9a-f]{6,}){6,})\b", body)
    recovery_inline = m.group(1) if m else None
    codes = None
    dl_path = os.path.join(OUT, "recovery_codes_download.txt")
    try:
        with page.expect_download(timeout=25000) as dl:
            page.evaluate("""(() => {
                const b = Array.from(document.querySelectorAll('button')).find(x => /^download$/i.test((x.innerText||'').trim()) && x.offsetParent !== null);
                if (b) b.click();
            })()""")
        codes = dl.value
        path = dl.value.path()
        # parse: each line "xxxxx-yyyyy"
        txt = open(path, encoding="utf-8").read()
        codes = [c for c in re.findall(r"\b([a-z0-9]{5}-[a-z0-9]{5})\b", txt, re.I)]
        import shutil
        shutil.copy(path, dl_path)
        log(f"2fa codes downloaded: {len(codes)}")
    except Exception as e:
        log("2fa download exc: " + str(e)[:120])
        if recovery_inline:
            codes = [recovery_inline]
    time.sleep(3)
    # 7. finalize: "I have saved my recovery codes"
    fin = page.evaluate("""(() => {
        const b = Array.from(document.querySelectorAll('button')).find(x => /i have saved my recovery codes/i.test((x.innerText||'').trim()));
        if (b && !b.disabled) { b.click(); return 'clicked'; }
        return 'disabled:' + (b ? b.disabled : 'nobtn');
    })()""")
    log("2fa finalize: " + str(fin))
    time.sleep(12)
    return secret, codes


def process_account(account, proxy_label="HOME"):
    uname = account["username"]
    email = account["email"]
    password = account["password"]
    log(f"=== POSTREG {uname} ({email}) ===")
    updates = {"provider": "github", "username": uname}
    avatar_path = make_avatar(uname)
    new_username = gen_new_username()
    first, last = random.choice(NAMES_POOL)
    bio = random.choice(BIOS)
    cfg = proxy_cfg(proxy_label)
    with Camoufox(proxy=cfg, headless=True, humanize=True) as browser:
        page = browser.new_page()
        st, url = login(page, email, password, uname)
        log("login: " + st)
        if st == "2FA_ALREADY":
            upsert_account({**updates, "status": "OK_VERIFIED", "twofa_enabled": 1})
            return "2FA_ALREADY"
        if st != "OK":
            if st == "DEVICE_VERIFY":
                if not wait_device_code(page, account):
                    upsert_account({**updates, "status": "DEVICE_VERIFY_FAIL"})
                    return "DEVICE_VERIFY_FAIL"
                log("device verified")
            else:
                upsert_account({**updates, "status": st})
                return st
        # ---- avatar ----
        av = upload_avatar(page, avatar_path)
        log("avatar: " + str(av))
        updates["avatar"] = avatar_path
        # ---- profile: name + bio ----
        set_profile(page, first, last, bio)
        updates["bio"] = bio
        # ---- repo ----
        repo_name = (uname + "-lab")[:60]
        repo_type = "own" if random.random() < 0.7 else "fork"
        if repo_type == "own":
            made = create_repo(page, repo_name, account)
        else:
            made = fork_repo(page)
            repo_name = None
        log(f"repo({repo_type}): {made}")
        if made:
            updates["repo_name"] = repo_name
            updates["repo_type"] = repo_type
        # ---- 2FA ----
        secret, codes = enable_2fa_totp(page, uname)
        if secret and secret != "ALREADY":
            updates["totp_secret"] = secret
            updates["totp_ok"] = 1
            updates["twofa_enabled"] = 1
            if codes:
                updates["backup_codes"] = codes
        elif secret == "ALREADY":
            updates["twofa_enabled"] = 1
        else:
            log("2FA FAILED for " + uname)
        # GitHub: rename disabled for fresh accounts ("contact us") — skip
        page.screenshot(path=OUT + "\\pr_final.png")
    updates["status"] = "POSTREG_DONE"
    upsert_account(updates)
    # TG push
    try:
        from gh_autoreg import tg_push_creds
        tg_push_creds(email, uname, password)
    except Exception as e:
        log("tg push exc: " + str(e)[:100])
    return "DONE"


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    uname_filter = sys.argv[2] if len(sys.argv) > 2 else None
    gh_db.init()
    if uname_filter:
        acc = gh_db.get_by_username(uname_filter)
        accounts = [acc] if acc else []
    else:
        accounts = gh_db.fetch("github", "OK_VERIFIED", limit=1000)
        # only un-warmed accounts; no fallback to already-warmed ones
        accounts = [a for a in accounts if not a.get("twofa_enabled")][:limit or 1]
    if not accounts:
        print("no accounts to process")
        return 0
    ok = 0
    for a in accounts[: (limit or len(accounts))]:
        res = None
        try:
            res = process_account(a, proxy_label="HOME")  # direct: ZTE modem dead
            if res in ("DONE", "2FA_ALREADY"):
                ok += 1
        except Exception as e:
            log(f"process EXC {a['username']}: {type(e).__name__} {str(e)[:200]}")
            upsert_account({"provider": "github", "username": a["username"],
                            "status": "OK_VERIFIED", "err": f"{type(e).__name__}: {str(e)[:160]}"})
        # fast cadence for unattended workers: short gap, skip trailing sleep
        gap = random.uniform(30, 60) if res in ("DONE", "2FA_ALREADY") else random.uniform(15, 30)
        log(f"waiting {int(gap)}s before next account")
        time.sleep(gap)
    log(f"postreg finished: ok={ok}/{len(accounts[:limit or 100])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
