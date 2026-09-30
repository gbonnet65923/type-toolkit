# -*- coding: utf-8 -*-
"""GitHub autoreg watchdog. Cron (no_agent): silent when healthy,
prints ALERT lines when attention needed. Restarts dead components,
sends alerts to Vlad's TG chat (token parsed from hermes config.yaml)."""
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request

OUT = r"C:\Users\User\tmp\bpproxy_run"
ACC = os.path.join(OUT, "github_accounts.jsonl")
LOG = os.path.join(OUT, "gh_autoreg.log")
CFG = r"C:/Users/User/AppData/Local/hermes/config.yaml"
TARGET = 100
PY = r"C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe"
CHAT = "TG_CHAT_ID"
THREAD = "350384"
DETACH = 0x00000008


def get_token():
    for pat in (r"7189316701:[A-Za-z0-9_-]{20,}", r"8873155556:[A-Za-z0-9_-]{20,}"):
        m = re.search(pat, open(CFG, encoding="utf-8").read())
        if m:
            return m.group(1)
    return None


def tg(msg):
    t = get_token()
    if not t:
        return False
    try:
        data = urllib.parse.urlencode({
            "chat_id": CHAT, "message_thread_id": THREAD, "text": msg[:3500]}).encode()
        urllib.request.urlopen("https://api.telegram.org/bot%s/sendMessage" % t,
                               data=data, timeout=25).read()
        return True
    except Exception:
        return False


def count_statuses():
    c, ok_uniq, bad = {}, set(), []
    for line in open(ACC, encoding="utf-8"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        st = r.get("status", "?")
        c[st] = c.get(st, 0) + 1
        if st == "OK_VERIFIED":
            ok_uniq.add(r.get("username"))
        else:
            bad.append(r.get("ts", ""))
    return c, len(ok_uniq), len(bad[-12:])


def proc_alive(name):
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe' or name='python3.exe'",
             "get", "CommandLine", "/format:list"],
            capture_output=True, text=True, timeout=30).stdout
        return name in out
    except Exception:
        return True


def fresh_log():
    try:
        return time.time() - os.path.getmtime(LOG) < 60 * 15
    except Exception:
        return False


def main():
    alerts = []
    c, ok, bads = count_statuses()
    needed = TARGET - ok
    runner = proc_alive("gh_runner.py")
    socks = proc_alive("vps_socks.py")

    if not runner and needed > 0:
        subprocess.Popen([PY, os.path.join(OUT, "gh_runner.py"), str(TARGET)],
                         cwd=OUT, creationflags=DETACH)
        alerts.append("RESTART runner (ok=%d/%d)" % (ok, TARGET))
    if not socks:
        subprocess.Popen([PY, os.path.join(OUT, "vps_socks.py"), "2090", "27022"],
                         cwd=OUT, creationflags=DETACH)
        alerts.append("RESTART vps_socks")
    if runner and not fresh_log():
        alerts.append("STALE: log silent 15min, runner alive; ok=%d/%d" % (ok, TARGET))

    if TARGET - ok <= 3 and ok >= 97:
        alerts.append("ALMOST: %d/%d" % (ok, TARGET))
    if ok >= TARGET:
        alerts.append("DONE: %d OK_VERIFIED reached" % ok)

    hour_mark = os.path.join(OUT, ".wdg_hour")
    hb = False
    try:
        if time.time() - os.path.getmtime(hour_mark) > 3600:
            hb = True
    except Exception:
        hb = True
    if hb:
        try:
            open(hour_mark, "w").write(time.strftime("%H:%M"))
        except Exception:
            pass

    if hb and not alerts:
        alerts.append("watchdog beat: %d/%d | %s" % (ok, TARGET, c))
    if alerts:
        print("\n".join(alerts), flush=True)
        if not tg("GH-REG: " + "\n".join(alerts)):
            try:
                subprocess.run(
                    [PY, OUT + r"\tg_push_r3f.py", "GH-REG: " + "\n".join(alerts)],
                    capture_output=True, text=True, timeout=60)
            except Exception:
                pass


if __name__ == "__main__":
    main()