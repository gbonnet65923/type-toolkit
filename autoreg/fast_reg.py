# FAST registration worker: tight loop, rotate IP every 3 accounts, no long pauses
import subprocess, time, sqlite3, sys

PY = r"C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe"
OUT = r"C:\Users\User\tmp\bpproxy_run"
DB = OUT + r"\accounts.db"
LOG = open(OUT + r"\fast_reg.log", "a", encoding="utf-8")

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
PER_IP = 3


def log(m):
    print(m, flush=True)
    LOG.write(m + "\n")
    LOG.flush()


def ok_count():
    db = sqlite3.connect(DB)
    n = db.execute("SELECT COUNT(*) FROM accounts WHERE status='OK_VERIFIED'").fetchone()[0]
    db.close()
    return n


def run(cmd, timeout):
    try:
        r = subprocess.run([PY, "-u"] + cmd, cwd=OUT, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 99, "timeout"


idx = 400
made_on_ip = PER_IP  # rotate immediately on start
consecutive_ft = 0


def relay_alive():
    import socket as sk
    try:
        s = sk.create_connection(("127.0.0.1", 8899), timeout=3)
        s.close()
        return True
    except OSError:
        return False


def heal_relay():
    import subprocess as sp
    try:
        sp.Popen([PY, "zte_relay.py"], cwd=r"C:\Users\User\tmp",
                 creationflags=0x00000008)  # DETACHED_PROCESS, no wait
        log("relay healed (restarted)")
    except Exception as e:
        log(f"relay heal failed: {e}")


while True:
    if not relay_alive():
        log("relay dead (proactive probe) — healing")
        heal_relay()
        time.sleep(5)
    ok = ok_count()
    if ok >= TARGET:
        log(f"TARGET {TARGET} reached (ok={ok})")
        break
    # rotate every PER_IP accounts
    if made_on_ip >= PER_IP:
        # wait for warm worker to finish its browser session (modem disconnect kills it)
        import os, glob
        for _ in range(60):
            flags = glob.glob(OUT + r"\warm_busy_*.flag")
            if not flags:
                break
            # stale flag cleanup (crashed warm worker)
            for f in flags:
                try:
                    if time.time() - os.path.getmtime(f) > 1200:
                        os.remove(f)
                        log("removed stale warm flag")
                except OSError:
                    pass
            time.sleep(3)
        
        try:
            subprocess.run([PY, "-u", "zte_ui_rotate2.py"], cwd=OUT, capture_output=True, timeout=300)
            log("rotated IP")
        except Exception:
            log("rotate failed — continuing on current IP")
        made_on_ip = 0
    idx += 1
    t0 = time.time()
    rc, out = run(["gh_autoreg.py", str(idx).zfill(3), "ZTE", "gmail"], 700)
    dt = time.time() - t0
    if "OK_VERIFIED" in out:
        made_on_ip += 1
        consecutive_ft = 0
        log(f"reg #{idx}: OK ({dt:.0f}s) ok_total={ok + 1}")
        time.sleep(20)
    else:
        reason = "timeout" if rc == 99 else ("FORM_TIMEOUT" if "FORM_TIMEOUT" in out else "fail")
        log(f"reg #{idx}: {reason} ({dt:.0f}s)")
        if reason == "FORM_TIMEOUT":
            consecutive_ft += 1
            if consecutive_ft >= 3:
                heal_relay()
                consecutive_ft = 0
        time.sleep(8)
        made_on_ip += 2  # fails burn the IP budget 2x faster -> rotate sooner