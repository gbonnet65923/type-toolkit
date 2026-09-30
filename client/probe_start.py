import json, urllib.request, urllib.error, urllib.parse, ssl

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

email = "throwaway.test.reg@gmail.com"
vuri = "https://auth.type.com/agent-claim?token=cat_ywILqSA7QnXgWZvCWN7CnsD-omQ581Xe"
cat = urllib.parse.parse_qs(urllib.parse.urlparse(vuri).query)["token"][0]
body = {
    "claimAttemptToken": cat,
    "email": email,
    "organizationName": "test lab",
}
req = urllib.request.Request(
    "https://api.type.com/api/agent-signup/start",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json", "User-Agent": "type-cli/rev (python)"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        print("HTTP", r.status)
        print(json.dumps(json.load(r), indent=2)[:800])
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode("utf-8", "replace")[:800])
