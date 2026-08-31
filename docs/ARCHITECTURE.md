# Architecture

How BAI-FARM works and why every piece is the way it is. Every design decision
here was validated empirically — failed alternatives are documented in
[RESEARCH.md](RESEARCH.md).

## The target

`chat.b.ai` ("BAI") is a LobeChat fork that grants free LLM credits to new
wallet-based accounts and exposes an **OpenAI-compatible API** at
`https://api.b.ai/v1/chat/completions`. One wallet = one account = one free
`sk-...` API key. Wallets are generated locally (Ethereum keypair), so identity
supply is unlimited and free — the only real friction is **Cloudflare
Turnstile** during registration and **per-IP rate limiting**.

Free models confirmed working per key (HTTP 200):
`deepseek-v4-flash`, `glm-5.3-flash`, `qwen3.8-flash`, `hy3`.
(`minimax-m3` requires a deposit — not usable.)

## Stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | All needed libs exist; multiprocessing for workers |
| Identity | `eth_account` | Local EVM keygen + `personal_sign` signing. No node, no gas, no funds |
| Browser | **Camoufox** | Anti-fingerprint Firefox. Turnstile reads the browser fingerprint — vanilla Playwright/Chrome/Chromium gets an interactive widget that never passes |
| Browser driver | Playwright (sync API, bundled with Camoufox) | Protocol-level frame enumeration is the only way into the Turnstile widget (see below) |
| HTTP client | **curl_cffi** `impersonate="chrome131"` | Replicates a real Chrome TLS handshake (JA3/JA4). Plain `requests`/`httpx` fingerprints are bot-tells and get rejected |
| Proxies | Residential (e.g. Webshare) | Registration is rate-limited **per IP**. Residential IPs pass; datacenter IPs get interactive challenges + rejections |
| Parallelism | `multiprocessing` | 1 process per worker (Camoufox doesn't share across processes). ~1.5-2 GB RAM per worker |

## The 2-phase flow (browser expensive, HTTP cheap)

```
PHASE 1 — BROWSER (~10-25s)                PHASE 2 — HTTP (~5s)
┌─────────────────────────────────┐        ┌──────────────────────────────────┐
│ Camoufox(headless, geoip,       │        │ curl_cffi(chrome131, SAME PROXY) │
│   proxy, locale="en-US")        │        │                                  │
│ 1. goto chat.b.ai/chat          │  token │ 1. GET  /api/auth/csrf           │
│ 2. inject EIP-6963 mock wallet  │ ─────► │ 2. POST /api/auth/callback/      │
│ 3. click: Log in → Other login  │        │          metamask                │
│    methods → EVM → MetaMask     │        │    (SIWE msg + signature +       │
│ 4. SIWE dialog appears with     │        │     turnstileToken) → session    │
│    Turnstile widget             │        │ 3. GET  /api/auth/session        │
│ 5. click checkbox FROM INSIDE   │        │ 4. GET  /trpc/lambda/            │
│    the cf frame (page.frames)   │        │      user.getUserState → JWT     │
│ 6. poll input[name=cf-          │        │ 5. POST /trpc/lambda/            │
│    turnstile-response] → token  │        │      apiKey.createApiKey         │
│ 7. browser CLOSES               │        │    → sk-...                      │
└─────────────────────────────────┘        │ 6. POST api.b.ai/v1/chat/        │
                                           │      completions (verify 200)    │
                                           └──────────────────────────────────┘
```

### Why the browser cannot be removed

Cloudflare Turnstile issues tokens that are cryptographically bound to:

1. **The minting browser fingerprint** — a real widget rendered by a real
   browser engine. External solvers produce *form-valid* tokens that the BAI
   server rejects, because their tokens come from a bare page with only the
   sitekey (different challenge type — token lengths differ: 745-766 chars from
   solvers vs 624-709 from the real widget).
2. **The minting IP** — siteverify cross-checks the IP that minted the token
   with the IP that submits it. Phase 2 therefore MUST reuse the exact proxy
   of Phase 1. Mismatch → `login rejected: null`.
3. **One-time use** — a token cannot be replayed or batched.

So the browser's *only* job is minting one token per account, and the farm
closes it immediately after — everything else is cheap HTTP.

### Turnstile widget mechanics (the hard part)

The widget iframe lives inside **closed Shadow DOM**: `document.querySelector`
from page JS sees nothing. The only reliable path is Playwright's
`page.frames` (protocol-level enumeration, crosses shadow + cross-origin
boundaries). The checkbox sits at approximately `(28, 30)` inside the frame:

```python
for f in page.frames:
    if "challenges.cloudflare.com" in (f.url or ""):
        f.locator("body").click(position={"x": 28, "y": 30}, timeout=2000)
        break
```

After clicking, the farm polls the hidden input `input[name=cf-turnstile-response]`
until it fills (typically 4-10 s on a fresh residential IP).

### Wallet mock (EIP-6963)

The site discovers wallets via **EIP-6963** (modern multi-wallet announce
protocol), *not* legacy `window.ethereum` injection — the legacy approach fails.
The farm injects a `<script>` DOM tag (survives Firefox Xray compartment
isolation, where automation-world objects are invisible to the page world) that:

- announces a fake provider with `rdns: "io.metamask"` via
  `eip6963:announceProvider`,
- answers `eth_requestAccounts` with the locally generated address,
- relays `personal_sign` to Python through `CustomEvent`s carrying JSON
  **strings** (strings cross worlds; objects don't).

Python signs the SIWE message with `eth_account.encode_defunct(text=msg)`.

### Registration HTTP trace (Phase 2)

```
GET  https://chat.b.ai/api/auth/csrf                          → csrfToken
POST https://chat.b.ai/api/auth/callback/metamask             → session cookie
     form: {chain:"eth", message:<SIWE>, signature:<0x…>,
            turnstileToken:<phase-1 token>, version:"2",
            csrfToken, callbackUrl, redirect:"false"}
     header: X-Auth-Return-Redirect: 1
GET  https://chat.b.ai/api/auth/session                       → {user:{id,name}}
GET  https://chat.b.ai/trpc/lambda/user.getUserState?batch=1  → apiAccessToken (JWT)
POST https://chat.b.ai/trpc/lambda/apiKey.createApiKey?batch=1 → {key:"sk-…"}
POST https://api.b.ai/v1/chat/completions                     → 200 = verified
```

SIWE message template (must match the app's expectation):

```
Welcome to BAI !
https://chat.b.ai wants you to sign in with your account:
<address>

Chain ID: 0x1
Expiration Time: <ISO 8601, +24h>
Nonce: <6 random alnum><epoch-ms>
```

tRPC is LobeChat's RPC layer (`/trpc/lambda/<procedure>`); it is probeable
directly with the session cookie — no browser needed after login.
API-key management endpoints on `api.b.ai` use header
`X-Ainft-Auth-Token: Bearer <jwt>` (regular `Authorization` errors with
"invalid team proxy internal token").

## Proxy rules (where farms usually die)

1. **Residential only.** Datacenter IPs get harder challenges and rejections.
2. **Per-IP registration budget.** ~1-3 registrations per IP, then
   `error=Configuration` on login. Old-account logins are NOT rate-limited.
3. **Rotation model.** `proxies.txt` → `mp.Queue`; each attempt pulls a proxy
   and returns it after (success or failure). Nothing is consumed.
4. **Same-IP rule.** Phase 1 and Phase 2 must share the proxy.
5. **`locale="en-US"` is mandatory** when the proxy is non-US: Camoufox
   `geoip=True` syncs timezone/locale to the proxy IP, which yields a Chinese
   UI and breaks the English selectors.

## Performance

| Metric | Value |
|---|---|
| Per account (post-optimization) | ~25-35 s (token @ 4 s, smart-wait waits on selectors not sleeps) |
| Throughput @ 4 workers | 40 accounts / ~7-9 min (measured, 40/40 success) |
| Throughput @ 8 workers | ~16 accounts / min (est.) |
| Bandwidth per registration | ~2-4 MB proxy quota |
| Image blocking | **Reverted** — Camoufox flags it as a WAF bot signal |

Reliability features: 3 attempts per account with a different proxy each time,
geoip warm-up before workers start (avoids DB-download races), incremental
merge-save after every result (crash-safe), per-wallet session files for reuse.
