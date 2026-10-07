# PAT harvester for warmed accounts: login w/ TOTP -> device-code via gmail -> PAT -> DB
import time, sys, re, json, sqlite3
sys.path.insert(0, r"C:\Users\User\tmp\bpproxy_run")
from camoufox.sync_api import Camoufox
import pyotp
import imaplib
import email as el

DB = r"C:\Users\User\tmp\bpproxy_run\accounts.db"
from gh_mail import GmailIMAP  # real creds live in gh_mail - never copy them here
_GMAIL = GmailIMAP()
# The workstation IP drives the fleet control plane; a fraud flag on it costs
# the whole fleet. Every login goes through the VPS SOCKS tunnel instead.
proxy = {"server": "socks5://127.0.0.1:2090"}


def fetch_device_code(addr, timeout=240, since=None):
    since = since or 0
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(_GMAIL.user, _GMAIL.pass_)
            m.select("INBOX")
            st, data = m.search(None, '(FROM "noreply@github.com")')
            ids = data[0].split()[-4:]
            for mid in reversed(ids):
                st, md = m.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT TO DATE)])")
                msg = el.message_from_bytes(md[0][1])
                if addr.lower() not in str(msg.get("To", "")).lower():
                    continue
                import email.utils as eutils
                try:
                    dt = eutils.parsedate_to_datetime(str(msg.get("Date", "")))
                    if since and dt.timestamp() < since - 60:
                        continue  # stale code from earlier session
                except Exception:
                    pass
                st2, md2 = m.fetch(mid, "(BODY.PEEK[])")
                body = md2[0][1].decode("utf-8", "ignore")
                mm = re.search(r'\b(\d{6,8})\b', str(msg.get("Subject", "")) + body[:800])
                if mm:
                    m.logout()
                    return mm.group(1)
            m.logout()
        except Exception:
            pass
        time.sleep(8)
    return None


def pat_for(username, password, totp_secret, email):
    login_start = time.time()
    with Camoufox(headless=True, humanize=True, proxy=proxy) as browser:
        page = browser.new_page()
        page.goto("https://github.com/login", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        page.fill("#login_field", username, timeout=15000)
        page.fill("#password", password, timeout=15000)
        page.click("input[name='commit'], button[type=submit]", timeout=10000)
        time.sleep(8)
        url = page.url
        # device verification?
        if "verified-device" in url:
            code = fetch_device_code(email, since=login_start)
            print(f"[p] {username} device code: {code}")
            if not code:
                return None
            try:
                loc = page.locator("input#otp, input[name='otp'], input[inputmode='numeric']").first
                loc.wait_for(state="visible", timeout=15000)
                loc.click()
                loc.press_sequentially(str(code), delay=90)
                time.sleep(2)
                page.click("button:has-text('Verify')", timeout=10000)
            except Exception as e:
                print(f"[p] {username} verify click: {str(e)[:50]}")
            # wait for the page to advance (slow 3G)
            for _ in range(12):
                time.sleep(5)
                if "verified-device" not in page.url:
                    break
            url = page.url
            if "verified-device" in url:
                try:
                    b = " ".join(page.inner_text("body").split())[:200]
                    print(f"[p] {username} device stuck, body: {b}")
                    inputs = page.evaluate("() => Array.from(document.querySelectorAll('input')).map(i => i.type + '#' + (i.id || i.name || '?')).join(' | ')")
                    print(f"[p] inputs: {inputs[:200]}")
                except Exception:
                    pass
        # 2FA TOTP?
        if "two-factor" in url:
            if not totp_secret:
                print(f"[p] {username} two-factor without totp_secret - skip")
                return None
            totp = pyotp.TOTP(totp_secret).now()
            try:
                page.fill("input[name='otp'], input#app_totp", totp, timeout=10000)
                page.click("button:has-text('Verify'), input[name='commit']", timeout=25000)
                time.sleep(8)
            except Exception as e:
                print(f"[p] {username} totp click slow: {str(e)[:50]}")
                time.sleep(10)
                if "two-factor" in page.url:
                    return None
                # navigation completed despite click timeout
        print(f"[p] {username} logged in: {page.url[:50]}")
        # PAT
        page.goto("https://github.com/settings/tokens/new", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)
        try:
            page.fill("input#oauth_access_description", f"ci-{username}-{int(time.time())%100000}", timeout=10000)
            page.evaluate("""() => { document.querySelectorAll('input[type="checkbox"]').forEach(cb => { if (!cb.checked) cb.click(); }); }""")
            time.sleep(1)
            for sel in ("label:has-text('No expiration')", "input[value='no_expiration']"):
                try:
                    if page.locator(sel).count() > 0:
                        page.locator(sel).first.click()
                        break
                except Exception:
                    pass
            time.sleep(1)
            for bt in ("Generate token", "Generate"):
                try:
                    b = page.locator(f"button:has-text('{bt}')").first
                    if b.count() > 0:
                        b.click(timeout=8000)
                        time.sleep(4)
                        break
                except Exception:
                    pass
            pat = page.evaluate("() => { const m = document.body.innerText.match(/gh[pousr]_[a-zA-Z0-9]{36,}/); return m ? m[0] : null; }")
            if not pat:
                # diagnostics: why no token
                try:
                    u = page.url
                    b = " ".join(page.inner_text("body").split())[:150]
                    print(f"[p] {username} no-token url={u[:60]} body={b[:120]}")
                except Exception:
                    pass
            return pat
        except Exception as e:
            print(f"[p] {username} PAT err: {str(e)[:80]}")
            return None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    only = sys.argv[2] if len(sys.argv) > 2 else None
    db = sqlite3.connect(DB)
    # warmed accounts (2FA on, no PAT yet) — PAT stored in notes col? add col
    try:
        db.execute("ALTER TABLE accounts ADD COLUMN pat TEXT")
        db.commit()
    except Exception:
        pass
    q = """SELECT username, password, totp_secret, email FROM accounts
           WHERE twofa_enabled=1 AND (pat IS NULL OR pat='') AND COALESCE(pat_fail,0) < 3"""
    if only:
        q += " AND username=?"
        rows = db.execute(q, (only,)).fetchall()
    else:
        rows = db.execute(q + " ORDER BY (pat_fail IS NULL) DESC, username LIMIT ?", (limit,)).fetchall()
    print(f"[p] target accounts: {len(rows)}")
    ok = 0
    for username, password, totp_secret, email in rows:
        print(f"[p] === {username} ===")
        pat = pat_for(username, password, totp_secret, email)
        if pat:
            db.execute("UPDATE accounts SET pat=?, pat_fail=0 WHERE username=?", (pat, username))
            db.commit()
            print(f"[p] {username} PAT: {pat[:18]}...")
            ok += 1
        else:
            print(f"[p] {username} PAT: FAILED")
            try:
                db.execute("UPDATE accounts SET pat_fail=COALESCE(pat_fail,0)+1 WHERE username=?", (username,))
                db.commit()
            except Exception:
                pass
        time.sleep(60)
    print(f"[p] DONE ok={ok}/{len(rows)}")


if __name__ == "__main__":
    main()