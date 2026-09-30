# -*- coding: utf-8 -*-
"""Mailboxes for the GitHub autoreg pipeline.
Primary: mail.tm REST API (disposable inbox, uberip.com etc).
Fallback: Gmail IMAP with +alias addressing (FARM_ALIAS@gmail.com).
All code ASCII. Prints are UTF-8 safe via caller's PYTHONIOENCODING.
"""
import time, re, random, string, json
import requests

TM_BASE = "https://api.mail.tm"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class MailTM:
    def __init__(self):
        d = requests.get(f"{TM_BASE}/domains", headers={"User-Agent": UA}, timeout=20).json()
        self.domains = [x["domain"] for x in d["hydra:member"]]
        if not self.domains:
            raise RuntimeError("mail.tm no domains")

    def create(self, local=None, password=None):
        local = local or "gh" + "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        password = password or "Gh#" + "".join(random.choices(string.ascii_letters + string.digits, k=13)) + "!7z"
        domain = self.domains[0]
        address = f"{local}@{domain}"
        r = requests.post(f"{TM_BASE}/accounts",
                          headers={"User-Agent": UA, "Content-Type": "application/json"},
                          json={"address": address, "password": password}, timeout=20)
        if r.status_code not in (201, 200):
            raise RuntimeError(f"mail.tm create {r.status_code}: {r.text[:160]}")
        tok = self._token(address, password)
        return {"address": address, "password": password, "token": tok}

    def _token(self, address, password):
        r = requests.post(f"{TM_BASE}/token",
                          headers={"User-Agent": UA, "Content-Type": "application/json"},
                          json={"address": address, "password": password}, timeout=20)
        r.raise_for_status()
        return r.json()["token"]

    def wait_code(self, token, sender_hint="github", timeout_sec=300, pattern=r"\b(\d{6,8})\b", seen_ids=None):
        """Poll inbox for a code in the newest message matching sender_hint.
        Returns (code, message_id) or (None, None) on timeout."""
        seen_ids = seen_ids or set()
        hdr = {"User-Agent": UA, "Authorization": f"Bearer {token}"}
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                r = requests.get(f"{TM_BASE}/messages", headers=hdr, timeout=20)
                if r.status_code == 200:
                    for m in r.json()["hydra:member"]:
                        mid = m["id"]
                        if mid in seen_ids:
                            continue
                        seen_ids.add(mid)
                        sender = (m.get("from") or {}).get("address", "")
                        subject = m.get("subject", "")
                        if not (sender_hint.lower() in sender.lower() or sender_hint.lower() in subject.lower()):
                            continue
                        d = requests.get(f"{TM_BASE}/messages/{mid}", headers=hdr, timeout=20).json()
                        text = " ".join([d.get("text", "") or "", d.get("html", "") or ""])
                        mm = re.search(pattern, text, re.I)
                        if mm:
                            return mm.group(1), mid
            except Exception:
                pass
            time.sleep(5)
        return None, None


class GmailIMAP:
    """Gmail +alias mailbox via IMAP. All aliases land in one inbox."""

    def __init__(self, user="FARM_GMAIL@gmail.com", app_pass="GMAIL_APP_PASS", alias_prefix="ghsig"):
        import imaplib
        self.user = user
        self.pass_ = app_pass
        self.prefix = alias_prefix

    def make_address(self, idx=None):
        idx = idx or random.randint(10000, 99999)
        u, d = self.user.split("@")
        return f"{u}+{self.prefix}{idx}@{d}"

    def wait_code(self, address, timeout_sec=300):
        import imaplib
        import email as email_lib
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
                m.login(self.user, self.pass_)
                m.select("INBOX")
                st, data = m.search(None, f'TO "{address}"')
                ids = []
                if st == "OK" and data[0]:
                    ids = data[0].split()[-5:]
                else:
                    st, data = m.search(None, 'FROM "noreply@github.com"')
                    if st == "OK" and data[0]:
                        ids = data[0].split()[-5:]
                found = None
                for mid in reversed(ids):
                    st, md = m.fetch(mid, "(RFC822)")
                    if st != "OK":
                        continue
                    msg = email_lib.message_from_bytes(md[0][1])
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                try:
                                    body += part.get_payload(decode=True).decode("utf-8", "ignore")
                                except Exception:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode("utf-8", "ignore")
                        except Exception:
                            body = ""
                    mm = re.search(r"(\b\d{8}\b|\b\d{6}\b)", body)
                    if mm and ("github" in str(msg.get("From", "")).lower() or address in str(msg.get("To", "")) or address in str(msg.get("Delivered-To", ""))):
                        found = mm.group(1)
                        break
                m.logout()
                if found:
                    return found
            except Exception:
                pass
            time.sleep(6)
        return None


if __name__ == "__main__":
    tm = MailTM()
    box = tm.create()
    print(json.dumps({"address": box["address"], "token_len": len(box["token"])}, ensure_ascii=False))
    g = GmailIMAP()
    print("gmail alias sample:", g.make_address())