import json
import sys

sys.path.insert(0, ".")
import type_client

cfg = type_client.discover()
mb = json.load(open("mailbox.json"))
EMAIL = mb["address"]  # fresh persistent mailbox
print("email:", EMAIL)
state = type_client.device_login(cfg, email=EMAIL)
print("DEVICE LOGIN DONE")
print("accessToken:", state.get("accessToken", "")[:30] + "…")
st, me = type_client.orpc_call(state, "cli/context/me")
print("orpc context/me ->", st)
print(str(me)[:400])
