import json, urllib.request, urllib.error, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

req = urllib.request.Request(
    "https://auth.type.com/agent/identity",
    data=json.dumps({"login_hint": "throwaway.test.reg@gmail.com", "type": "service_auth"}).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "type-cli/rev (python)"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        print("HTTP", r.status)
        print(json.dumps(json.load(r), indent=2)[:1500])
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode("utf-8", "replace")[:1500])
