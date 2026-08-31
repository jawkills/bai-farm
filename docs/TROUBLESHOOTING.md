# Troubleshooting

Symptom → cause → fix, ordered by how often they bite.

## `login rejected: null` / `CredentialsSignin`

| Likelihood | Cause | Fix |
|---|---|---|
| High | Proxy IP burned (per-IP registration rate-limit) | Rotate to a fresh proxy. Test: try the same flow on a brand-new IP — if it passes, the IP was the problem |
| Medium | Phase-2 proxy ≠ Phase-1 proxy | Both phases must use the exact same proxy URL |
| Medium | Token consumed twice (replay) | 1 token = 1 login; mint a fresh token per attempt |
| Low | SIWE message template drift | Must match the app's template exactly (see ARCHITECTURE.md) |

## `error=Configuration` after some successes

Your IP hit the registration rate limit (~1-3 registrations/IP; hard stop
after ~10 even for previously-working IPs). Rotate residential proxies.
Old-account logins are **not** rate-limited — only new registrations.

## UI renders in Chinese / selectors fail

Camoufox `geoip=True` syncs locale to the proxy IP. The farm forces
`locale="en-US"` — if you removed that, put it back. Without it, all the
`text=Log in` selectors fail on non-US proxies.

## `no turnstile token` (120 s timeout)

1. The frame-click targets position `(28, 30)` inside the challenge frame —
   if Cloudflare changed the widget layout, adjust the offset.
2. Check your proxy IP reputation — datacenter IPs get stuck on harder
   challenges. Residential only.
3. Vanilla Chromium instead of Camoufox will not pass. Anti-fingerprint
   browser is required.

## Solver tokens rejected (external captcha service)

**Working as intended** — see RESEARCH.md. Tokens from bare-page solvers are
structurally different and are bound to the widget context. Do not spend time
re-trying solvers (including with proxy pinning — that was tested airtight).

## Proxy `407 Proxy Authentication Required`

You are using dedicated-IP list credentials against a rotating gateway (e.g.
`p.webshare.io`) or vice versa. Use the exact host:port:user:pass pair from
your provider's proxy list.

## `official/stable is not installed` (Camoufox)

Browser runtime not downloaded. Run:

```
python -m camoufox fetch
```

## Workers race / geoip DB download errors at startup

The farm warm-starts one Camoufox before spawning workers for exactly this
reason. If you see parallel download races, don't remove the warmup.

## `block_images` warning

If you re-add image blocking to save bandwidth, Camoufox will warn that
missing image requests are a WAF bot signal. It was reverted on purpose.

## Keys were working, now `401/403` on api.b.ai

Keys can be revoked by the provider. Run `python scripts/verify_keys.py` to
see which are alive; farm replacements for the dead ones.

## Debugging artifacts

On failure, check `logs/debug/` for screenshots and captured HTML from the
failing attempt. Console lines `[W#n] attempt X FAILED [proxy]: <error>` name
the proxy and the stage that failed.
