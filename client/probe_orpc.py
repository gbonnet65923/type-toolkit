import json
import sys
import urllib.error
import urllib.request

sys.path.insert(0, ".")
import type_client

state = type_client.load_profile()
cfg = type_client.discover()
state = type_client.exchange(cfg, state)
token = state["accessToken"]
CTX = type_client._CTX
CLI_VERSION = "0.0.0-rev"


def call(label, path, body=None):
    req = urllib.request.Request(
        "https://api.type.com/api/orpc/" + path,
        data=json.dumps({"json": body or {}}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + token,
            "User-Agent": f"TypeCLI/{CLI_VERSION}",
            "x-type-cli-version": CLI_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            raw = r.read().decode("utf-8", "replace")
            print(f"{label} -> {r.status} {raw[:400]}")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        print(f"{label} -> {e.code} {e.read().decode()[:250]}")
        return None


call("cli/context/me", "cli/context/me")
call("cli/threads/list", "cli/threads/list")
call("cliAuth/listOrganizations", "cliAuth/listOrganizations")
call("cli/agents/list", "cli/agents/list")
