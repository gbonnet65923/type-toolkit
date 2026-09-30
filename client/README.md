# type.com reverse — protocol-level client & signup farm

**Type** (type.com) — shared-agent platform ("automations & agents powered by Claude, Codex, Grok, Gemini").
This repo contains the reverse of their CLI auth/protocol layer and a working
**browser-free protocol client + account farm** in one Python file (stdlib only).

```
type.com  →  api.type.com (server)  +  auth.type.com (WorkOS issuer)
CLI       →  Bun single-executable (102MB, linux/darwin/win) — bundle extractable
identity  →  WorkOS user_management: service_auth / device_code / jwt-bearer / refresh_token
signup    →  6-digit email code, NO browser, NO captcha observed
storage   →  ~/.type/credentials/<profile>.json
```

## Files

| File | What |
|---|---|
| `type_client.py` | Protocol client: discover / signup / complete / refresh / me / device-login / batch farm |
| `README.md` | This reverse report |

## Reversed protocol

### 1. Discovery (RFC 8414 chain)

```
GET https://api.type.com/.well-known/oauth-protected-resource
→ { resource, authorization_servers: ["https://auth.type.com"], type_workos_client_id }
GET https://auth.type.com/.well-known/oauth-authorization-server
→ { issuer, token_endpoint: "https://auth.type.com/oauth2/token",
    agent_auth: { identity_types_supported: ["service_auth"],
                  identity_endpoint: "https://auth.type.com/agent/identity" } }
```

Bundled WorkOS client_id (from CLI binary): `client_01K5GFDDKQWV8MM9FSRZS3YNNN`
(server discovery also returns `type_workos_client_id`).

### 2. Signup — service_auth, browserless (steps 1–4 live-verified, 5–7 from source)

```
POST https://auth.type.com/agent/identity
     { "login_hint": "<email>", "type": "service_auth" }
→  { claim: { token, attempt: { verification_uri (?token=...) → claimAttemptToken } },
    scopes: { post_claim: ["api.read"] } }            # REQUIRED_AGENT_SIGNUP_SCOPES = ["api.read"]

POST https://api.type.com/api/agent-signup/start
     { claimAttemptToken, email, organizationName }
→  { ok, email, signupToken }                         # 6-digit code sent by email

POST https://api.type.com/api/agent-signup/verify
     { code, signupToken }                             # code = 6 digits from email
→  { claim: { registrationId, userCode },
    organization: { name, slug, typeOrgId, workosOrgId }, organizationCreated }

POST https://auth.type.com/agent/identity/claim/complete
     { claim_token, user_code }
→  { id, status, identity: { assertion, refresh_token } }

POST https://auth.type.com/oauth2/token   (form)
     assertion=<jwt>&grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&resource=https://api.type.com
→  { access_token, refresh_token, token_type, expires_in }
```

State machine mirrored from CLI: `agent-signup-registered → pending → claim-ready → provisioned → tokens`.
Persisted to `~/.type/credentials/<profile>.json` (profile-per-account, same layout family as CLI).

### 3. Refresh

```
POST https://api.workos.com/user_management/authenticate   (form)
     client_id=<workosClientId>&grant_type=refresh_token&refresh_token=<rt>[&organization_id=<workosOrgId>]
→  { access_token, refresh_token, expires_in }
```

### 4. Device login (interactive accounts)

```
POST https://api.workos.com/user_management/authorize/device  { client_id, login_hint? }
→  { device_code, user_code, verification_uri[_complete], interval }
poll: POST /user_management/authenticate
      { client_id, device_code, grant_type=urn:ietf:params:oauth:grant-type:device_code }
      authorization_pending / slow_down / 200 {access_token…}
```

### 5. Platform API

`Authorization: Bearer <access_token>`; convex function surface seen in the bundle:
`agents, threads (list/get/recent/batch), messages, channels, spaces, automations, skills,
integrations (call/list/tools/…), apps (deploy/logs/scaffold…), search.workspace, users, /v1/me, /v1/items`.
Model harnesses: `claude | codex | grok | gemini | opencode` — the CLI runs agent steps locally
against your own Claude/Codex subscription; type.com hosts the shared workspace/schedules.

### 6. Live verification log (2026-09-30, anonymous)

```
GET  api.type.com/.well-known/oauth-protected-resource        → 200 (issuer, client_id)
GET  auth.type.com/.well-known/oauth-authorization-server     → 200 (endpoints above)
POST auth.type.com/agent/identity  {login_hint, service_auth} → 200
     claim.token=clm_7_…, attempt.verification_uri ?token=cat_… (claim attempt issued)
POST api.type.com/api/agent-signup/start {cat, email, org}    → 200
     signupToken=4b42… (6-digit email code dispatched)
```

### 7. Full E2E run (2026-09-30, live, throwaway mailbox)

```
mail.tm REST (mailbox + /messages)  →  6-digit code received
verify + claim/complete             →  identity {assertion (JWT, aud=issuer), refresh_token}
exchange (form, NO resource param)  →  200 {access_token (300s, aud=client_id, org_id, act.sub)}
```

**Finding:** assertion JWT `aud` = `https://auth.type.com` (issuer), NOT `https://api.type.com`.
Passing `resource=api.type.com` (as the CLI's non-loopback branch does) → HTTP 400 `invalid_target`.
Omitting `resource` → 200 + access_token. Decode: `aud=client_id, sub=agent_reg_…, org_id, act.sub=user_…`.

**Server-side gate observed:** registration returns `scopes.post_claim: []` while the CLI requires
`["api.read"]` (it aborts otherwise). With empty post-claim scopes the issued token gets
`401 Invalid token` on `POST /api/orpc/cli/context/me` (oRPC link: `{server}/api/orpc/<procedure>`,
body `{"json":{}}`, headers `Authorization / user-agent TypeCLI/… / x-type-cli-version`).
Refresh: the agent-credential route (from `refreshAgentRegistration` in the bundle, NOT the
WorkOS user grant) is **live-verified 200**: `POST identityEndpoint {"refresh_token": <value>,
"type": "refresh"}` → fresh `identity{assertion, refresh_token}` → re-exchange → new 300s token.
The `refresh_token` field arrives as `{value, expires_at}` — send `.value` (CLI's
`normalizeIdentity` does the same). Semantics: this is the CLI's **recovery** path (`refreshAgentRegistration` is invoked on
exchange failures). Refresh tokens are single-use (rotation rt0→rt1 observed live). Whether
the cycle repeats beyond one refresh per identity grant is **undetermined**: the runs that
produced `already_been_used` were confounded by a crashed exchange that burned the rotated
token before persist. Clean test (after the registration rate-limit window): fresh e2e →
`refresh` twice back-to-back. Hard finding regardless: `POST /agent/identity` is rate-limited
per IP — `429 Too many agent registrations, retry_after 3600` — farms must route through
proxies (client supports `TYPE_PROXY`).
Full API access still needs the interactive device-login (`auth login`) — consistent with
install.md: "Signup credentials currently support identity, search, and thread reads only".

Probes: `probe_identity.py`, `probe_start.py`, `e2e_test.py` (mail.tm REST code), `probe_orpc.py`, `probe_token.py`.

### 8. IMAP note

mail.tm exposes REST only (its `mail.tm:993` times out here); `fetch_code_imap` in the client
stays as a hook for real pools (RFC 3501-compliant: plain `UNSEEN` + Python header filtering +
`walk()` for multipart). E2E uses the mail.tm REST path.

## Usage

```sh
python type_client.py discover                      # live metadata
python type_client.py signup --email me@mail.tm --org "myteam"
python type_client.py complete --code 123456        # → tokens stored
python type_client.py me                            # GET /v1/me with auto-refresh
python type_client.py device-login                  # interactive device flow

# Farm (mail.tm: IMAP host is mail.tm:993, credentials = API account creds):
python type_client.py batch --emails pool.txt --org "farm" \
    --imap-host mail.tm --imap-pass-file creds.txt   # lines: email:password

# Proxies: TYPE_PROXY=http://user:pass@host:port  (per-invocation)
# Profiles: TYPE_PROFILE=<name> (default: "default")
```

## Extraction notes (CLI → source)

```
curl -fsSL https://type.com/install.sh | sh        # macOS/Linux
# binaries: https://desktop.type.com/cli/type-cli-{linux,darwin,win}*
sha256 verified against desktop.type.com/cli/SHA256SUMS
file → ELF 64-bit, not stripped, 102 MB
strings → "bun" runtime markers ("// @bun", "bunfs")
tail after last "// @bun" marker (offset 100819587) → 1.5 MB plain-JS bundle
bundle: zod 4.4.3, src/commands/*.ts (signup/auth/threads/…), convex/_generated
```

The bundle is unminified (commented module paths preserved) — all flow logic above
was lifted verbatim from `src/commands/signup.ts` and the auth core.

## Legal note

Research on an authorized security-lab target. Protocol reproduced from the public CLI
binary distributed by type.com. No auth bypass, no captcha bypass — plain HTTP semantics.


### 9. type2api.py — OpenAI-compatible gateway (bootstrap = 1 human click)

```
python type_client.py device-login --email <your@email>   # prints device URL
# open URL in your browser (Google session) -> "Continue with Google" -> click
# polling catches the token into ~/.type/credentials/default.json
python type2api.py                                        # :8311
GET  /v1/models        -> your type.com agents
POST /v1/chat/completions -> oRPC pipeline; send-procedure auto-discovered
```

Web-flow notes (live-probed 2026-09-30): AuthKit blocks disposable domains
(uberip.com = the only mail.tm domain: «Доступ заблокирован» on both login and
signup web paths — while the protocol-level service_auth signup still accepts it);
Google rejects CDP-automation browsers («небезопасный браузер»); Gmail IMAP needs
an app-password. Hence the single manual click for the user-token.
