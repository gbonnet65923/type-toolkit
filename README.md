# type-toolkit

Full reverse-engineering + automation stack for **type.com** (TypeCLI):

1. **`client/`** — protocol reverse: browserless signup, token exchange, identity refresh, device-login, and an **OpenAI-compatible API gateway** (`type2api.py`, port 8311).
2. **`autoreg/`** — GitHub/GitLab/Codeberg auto-registration framework (Camoufox-based), proxy rotation, PAT harvesting, mass account checking.

## client/ — type.com protocol

```
python client/type_client.py signup --email <addr>     # 7-HTTP-request browserless registration
python client/type_client.py device-login --email <addr> # one human click -> user token
python client/type2api.py                               # OpenAI-compatible gateway :8311
```

Key findings (live-probed):
- RFC 8414 discovery -> `auth.type.com` (issuer) + `api.type.com` (server)
- service_auth signup: `/api/agent-signup/start` -> email code -> verify -> claim/complete -> JWT bearer exchange
- **exchange trap**: assertion `aud`=issuer; sending `resource` returns 400 invalid_target — omit it
- refresh_token arrives as `{value, expires_at}` — send `.value`
- oRPC layer: `POST {server}/api/orpc/<procedure>` with `Authorization`/`TypeCLI` UA headers
- anti-farm: 429 on `/agent/identity` (IP-based, 3600s), AuthKit blocks disposable domains, Google blocks CDP browsers

## autoreg/ — account farming framework

```
autoreg/gh_autoreg.py <idx> [ZTE|HK1024|HOME] [mailtm|gmail]   # single GitHub account
autoreg/gh_pat.py                                              # PAT harvesting (login -> /settings/tokens)
autoreg/fast_reg.py <target>                                   # farm loop with IP rotation
autoreg/cb_reg2.py                                             # Codeberg reg (image-captcha via operator file)
autoreg/mass_check.py                                          # bulk profile shadowban check
autoreg/png2ascii.py                                           # pure-python PNG captcha decoder (no PIL)
```

Shadowban research (2026-09-30): accounts born via Camoufox autoreg are **instantly shadow-hidden** on GitHub (profile 404 for anonymous) regardless of email domain or IP; the flag triggers on the registration pattern itself. GitLab requires phone verification (step 2/2) + blocks gmail aliases. Codeberg uses a solvable image captcha.

All credentials sanitized to placeholders — bring your own.
