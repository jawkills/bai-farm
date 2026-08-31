# Research Log — every shortcut that was tried and rejected

Two days of experiments are compressed into this page. **Do not retry these
without new evidence** — each entry was tested against the live target.

| # | Approach | Result | Evidence / root cause |
|---|---|---|---|
| 1 | Full API, no browser at all | ❌ impossible | Turnstile token cannot be minted without a real browser widget |
| 2 | External captcha solver **A** (local cloakbrowser server, port 8877) | ❌ rejected | Server returns `error=Configuration`; solver token 745-766 ch vs real-widget token 624-709 ch — different challenge type |
| 3 | External captcha solver **B** (Boterdrop, port 8000) — plain | ❌ rejected | Same as above. `login rejected: null` / `CredentialsSignin` |
| 4 | Solver B **with per-request proxy pinning** (airtight re-test: solver forced to exactly 1 Webshare proxy, token minted through it, curl_cffi login through the SAME IP) | ❌ **still rejected** | Proves tokens are bound to the *original widget rendered inside the app page*, not just fingerprint+IP. Sitekey-only bare pages produce structurally different tokens. This closes the "hybrid solver" door definitively |
| 5 | Token replay (reuse a minted token for a 2nd login) | ❌ rejected | 1 token = 1 login, enforced server-side |
| 6 | Staging environment `chat-stg.b.ai` / `api-stg.b.ai` (seen in app JS) | ❌ unreachable | No public DNS — internal only (curl exit 28 / `000 0B`) |
| 7 | Webshare rotating gateway `p.webshare.io:80` | ❌ 407 | Dedicated-IP list credentials are not valid on the gateway (plan feature mismatch) |
| 8 | Vanilla Playwright/Chromium instead of Camoufox | ❌ stuck | Turnstile reads the browser fingerprint; vanilla automation → interactive widget that never resolves |
| 9 | Legacy `window.ethereum` wallet injection | ❌ not detected by app | App discovers wallets via **EIP-6963** announce protocol only |
| 10 | Accessing Turnstile widget via page JS (`document.querySelector`) | ❌ 0 results | Widget iframe is inside **closed Shadow DOM**; only protocol-level `page.frames` works |
| 11 | `block_images=True` in Camoufox (bandwidth saving) | ⚠️ reverted | Camoufox warns it is a Cloudflare WAF bot signal; risk > benefit |
| 12 | Direct IP (no proxy) at volume | ❌ after ~10 registrations | Per-IP rate limit → consecutive `error=Configuration` even on a previously-working flow |
| 13 | `python-requests` / plain `httpx` for Phase 2 | ❌ rejected | TLS fingerprint (JA3/JA4) is a bot-tell; `curl_cffi impersonate="chrome131"` passes |

## What made it work (the 4 keys)

1. **IP of token minter = IP of token consumer** (same proxy for both phases).
2. **Click the Turnstile checkbox from inside the frame** via `page.frames`
   (closed Shadow DOM is invisible to page JS).
3. **`locale="en-US"`** on Camoufox when the proxy is non-US (geoip otherwise
   renders a Chinese UI and the English selectors fail).
4. **The original widget is the only valid token source** — the browser stays
   in the loop, but only for ~10 seconds per account.

## Historical note on solver re-tests

Early solver tests were performed while the per-IP rate-limit was active,
which made the rejection ambiguous (gate vs token). The airtight re-test (#4)
was run on a fresh proxy with the farm's exact proven request format —
**rejection persisted**, eliminating the remaining doubt. Solver tokens are
form-valid but cryptographically bound to a different rendering context.

If Turnstile ever reverts to non-interactive (invisible auto-pass, as observed
on some IPs early in testing) or is removed entirely, a pure-HTTP farm becomes
possible — check for that periodically, it would be a massive speedup.
