# USAGE — agent guide

Все компоненты stdlib-only (Python 3.11+), работают на Windows/Linux без зависимостей.

## Быстрый старт

```bash
# 1) Control-plane (авторег + пул + дашборд) — порт 8312
python server/manager.py
#    GET  /                dashboard
#    GET  /api/status      {gateway, pool, log tail}
#    GET  /api/accounts    пул (redacted, без токенов)
#    POST /api/autoreg     {"org": "reform-org"} -> регистрация 1 аккаунта (60-180s)
#    POST /api/refresh     refresh всех аккаунтов (identity refresh + jwt-bearer exchange)

# 2) OpenAI-compatible gateway поверх пула — порт 8311
python server/gateway.py
#    GET  /v1/models
#    GET  /health
#    POST /v1/chat/completions

# 3) Клиент протокола type.com
python client/type_client.py signup --email <addr>          # browserless регистрация (7 HTTP-запросов)
python client/type_client.py device-login --email <addr>    # 1 клик человека -> user token
python client/type2api.py                                    # альтернативный gateway :8311
```

## Авторег-фарм (GitHub/GitLab/Codeberg)

```bash
python autoreg/gh_autoreg.py <idx> [ZTE|HK1024|HOME] [mailtm|gmail]  # 1 GitHub-аккаунт (Camoufox)
python autoreg/gh_pat.py            # PAT harvesting: login -> /settings/tokens
python autoreg/fast_reg.py <target> # фарм-цикл с IP-ротацией (ZTE 4G)
python autoreg/cb_reg2.py           # Codeberg (image captcha через operator-файл)
python autoreg/mass_check.py        # bulk shadowban-проверка профилей
python autoreg/png2ascii.py         # pure-python PNG-декодер капчи (без PIL)
python autoreg/gl_home_reg.py       # GitLab (phone verify step 2/2)
```

## Флоу type.com signup (browserless, live-verified)

1. `auth.type.com` RFC 8414 discovery -> issuer + `api.type.com` server
2. `POST /api/agent-signup/start` (service_auth) -> email code (mail.tm)
3. `POST /api/agent-signup/verify` -> `agent/identity/claim/complete`
4. `POST oauth2/token` grant_type=jwt-bearer -> access_token

**Ловушки:** assertion `aud` = issuer; параметр `resource` -> 400 invalid_target (не слать);
refresh_token приходит как `{value, expires_at}` — слать `.value`; oRPC:
`POST {server}/api/orpc/<procedure>` с заголовками `Authorization` + `TypeCLI/1.0.0` UA.

## Анти-фарм лимиты

- 429 на `/agent/identity` — IP-based, окно 3600s (нужна ротация IP: ZTE 4G / резидентные прокси)
- AuthKit блочит disposable email-домены
- Google OAuth блочит CDP-браузеры (используется Camoufox)
- GitHub: аккаунты с Camoufox-авторега мгновенно shadow-hidden (профиль 404 для анонимов) — паттерн регистрации палится, домен/IP ни при чём

## Пул и секреты

- `server/pool.json`, `client/acct.json`, `client/api_token.json` — локальные, gitignored (JWT/refresh токены)
- Свои креды: mail.tm аккаунт + прокси-пул (ZTE modem 192.168.0.1, IP ротация через DISCONNECT_NETWORK/CONNECT_NETWORK)

## Известный статус upstream (2026-09-30)

`api.type.com` отвечает 401 Invalid token на agent-токены (aud=client, server-side policy) —
gateway проксирует upstream-статус как есть. device-login (user token) работает.
