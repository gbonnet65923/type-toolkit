# -*- coding: utf-8 -*-
"""Batch runner for GitHub autoreg. Alternates between HOME IP and VPS SOCKS
to spread ban risk, with human-ish pauses. Continues until target count of
OK_VERIFIED accounts is reached. Progress journaled so restarts are safe.
Usage: python gh_runner.py [target_total] [start_idx]
"""
import subprocess, time, json, random, sys, os

OUT = r"C:\Users\User\tmp\bpproxy_run"
ACCOUNTS = OUT + r"\github_accounts.jsonl"
STATE = OUT + r"\gh_runner_state.json"
PY = r"C:/Users/User/AppData/Local/Programs/Python/Python311/python.exe"
SCRIPT = OUT + r"\gh_autoreg.py"

TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 50
START = int(sys.argv[2]) if len(sys.argv) > 2 else 10
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 0  # max accounts this run, 0 = unlimited

def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] RUNNER: {m}"
    print(line, flush=True)

def read_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"done": 0, "tries": 0, "next_idx": START, "errors": {}}

def write_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)

def count_ok():
    n = 0
    try:
        with open(ACCOUNTS, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("status") == "OK_VERIFIED":
                        n += 1
                except Exception:
                    pass
    except Exception:
        pass
    return n

def run_one(idx, source):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([PY, SCRIPT, str(idx).zfill(3), source, "gmail"],
                          capture_output=True, text=True, env=env, timeout=600)
    return proc.returncode, proc.stdout[-600:]

def main():
    st = read_state()
    ok_total = count_ok()
    log(f"state: done_total_ok={ok_total} target={TARGET} next_idx={st['next_idx']}")
    if ok_total >= TARGET:
        log("target already reached, nothing to do")
        return
    sources = ["HK1024"]
    done_this_run = 0
    while ok_total < TARGET and (not LIMIT or done_this_run < LIMIT):
        idx = st["next_idx"]
        st["next_idx"] += 1
        st["tries"] += 1
        source = random.choice(sources)
        log(f"== account {idx} via {source} (have {ok_total}/{TARGET}) ==")
        rc = None
        for attempt in range(3):
            try:
                rc, tail = run_one(idx, source if attempt == 0 else random.choice(sources))
                log(f"rc={rc} tail={tail[-200:].strip()[:180]}")
            except subprocess.TimeoutExpired:
                rc = 90
                log("timeout 600s")
            except Exception as e:
                rc = 99
                log("launch err: " + str(e)[:100])
            if rc == 0:
                done_this_run += 1
                break
            if rc in (7, 5, 4, 6, 1, 3):  # late-stage/logic - no retry value
                break
            # rc 2 = FORM_TIMEOUT, 90/99 -> retry with different source
            time.sleep(random.uniform(30, 90))
        ok_total = count_ok()
        if ok_total >= TARGET:
            log(f"DONE: {ok_total} OK_VERIFIED")
            break
        st["errors"][str(idx)] = rc
        write_state(st)
        pause = random.uniform(90, 240)
        log(f"pause {int(pause)}s before next")
        time.sleep(pause)
    write_state(st)
    log(f"final OK count = {ok_total}")

if __name__ == "__main__":
    main()