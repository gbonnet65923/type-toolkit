# 24/7 pipeline supervisor: register -> warmup -> PAT, loop until target
import subprocess, time, json, sqlite3, sys, os

PY = r"C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe"
OUT = r"C:\Users\User\tmp\bpproxy_run"
DB = OUT + r"\accounts.db"
LOG = open(OUT + r"\pipeline.log", "a", encoding="utf-8")

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1000


def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] PIPE: {m}"
    print(line, flush=True)
    LOG.write(line + "\n")
    LOG.flush()


def counts():
    db = sqlite3.connect(DB)
    ok = db.execute("SELECT COUNT(*) FROM accounts WHERE status='OK_VERIFIED'").fetchone()[0]
    warmed = db.execute("SELECT COUNT(*) FROM accounts WHERE twofa_enabled=1").fetchone()[0]
    pats = db.execute("SELECT COUNT(*) FROM accounts WHERE pat IS NOT NULL AND pat != ''").fetchone()[0]
    db.close()
    return ok, warmed, pats


def run(cmd, timeout):
    try:
        r = subprocess.run([PY, "-u"] + cmd, cwd=OUT, capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except subprocess.TimeoutExpired:
        return 99, "timeout"


idx = 200  # supervisor's own registration index space
cycle = 0
while True:
    cycle += 1
    ok, warmed, pats = counts()
    log(f"cycle {cycle}: ok={ok} warmed={warmed} pat={pats} target={TARGET}")
    if ok >= TARGET:
        log("TARGET REACHED")
        break

    # 1) registration if below target
    if ok < TARGET:
        idx += 1
        # ZTE: fresh mobile IP before each attempt (UI toggle rotation)
        try:
            subprocess.run([PY, "-u", "zte_ui_rotate2.py"], cwd=OUT,
                           capture_output=True, timeout=300)
        except Exception:
            pass
        rc, out = run(["gh_autoreg.py", str(idx).zfill(3), "ZTE", "gmail"], 900)
        status = "ok" if "OK_VERIFIED" in out else ("timeout" if rc == 99 else "fail")
        log(f"reg #{idx}: {status}")
        time.sleep(30)  # let modem/browser settle before warmup
        time.sleep(__import__("random").uniform(90, 200))

    # 2) warmup: pick one warmed-less account (retry once)
    rc, out = run(["gh_postreg.py", "1"], 900)
    if ("skip" not in out and "finished: ok=0" in out) or rc in (99, None):
        time.sleep(45)
        rc, out = run(["gh_postreg.py", "1"], 900)
    if "finished: ok=1" in out or "ok=1/" in out:
        log("warmup: +1")
    elif "no accounts to process" in out:
        log("warmup: queue empty")
    else:
        log("warmup: skip/fail")
    time.sleep(20)

    # 3) PAT for one warmed account without PAT
    rc, out = run(["gh_pat.py", "1"], 900)
    if "DONE ok=1" in out:
        log("pat: +1")
    elif "target accounts: 0" in out:
        log("pat: queue empty")
    else:
        log("pat: skip/fail")
    time.sleep(20)