# BAI-FARM

Automated account + API-key farm for **chat.b.ai** ("BAI"): each run generates
a fresh Ethereum wallet, passes the Cloudflare Turnstile challenge, completes
wallet login, and harvests an **OpenAI-compatible API key** (`sk-...`) with the
free-tier models.

> **Proven:** 44/44 accounts in one batch (~7-9 min, 4 workers, 100% success).
> ~25-35 s per account. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for
> the full design and [docs/RESEARCH.md](docs/RESEARCH.md) for every shortcut
> that was tried and rejected.

**⚠️ Disclaimer:** automating signups violates the target's Terms of Service.
Educational/research purposes only — you own all risk. See
[docs/ETHICS.md](docs/ETHICS.md).

---

## Features

- **Standalone** — one script, no external captcha solver, no manual steps, no email/OTP
- **Unlimited identity supply** — wallets are generated locally, free
- **2-phase architecture** — the browser only mints the Turnstile token (~10 s), everything else is fast HTTP (curl_cffi, Chrome TLS impersonation)
- **Proxy-aware** — automatic per-attempt rotation from a pool, same-IP enforcement across phases, 3 retries per account
- **Crash-safe** — results merge-saved after every account; sessions saved per wallet for login reuse

## Prerequisites

| Requirement | Notes |
|---|---|
| Python **3.11+** | 3.12 works too |
| Windows or Linux | ~2 GB RAM per worker; 8+ cores recommended |
| **Residential proxies** | Mandatory at volume — registration is rate-limited per IP. Webshare/IprRoyal/Bright Data all work. Budget ~2-4 MB bandwidth per registration |
| A GitHub-sized brain | Optional but recommended |

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/bai-farm.git
cd bai-farm

python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt

# download the Camoufox browser runtime (one time, ~500 MB):
python -m camoufox fetch
```

## Proxy setup

Copy the example and add your own proxies (gitignored, never commit the real file):

```bash
cp proxies.example.txt proxies.txt
```

One proxy per line — all three formats are accepted:

```
host:port
host:port:user:pass
http://user:pass@host:port
```

Rules of thumb:

- **Residential only** — datacenter IPs get harder challenges + rejections
- **1-3 registrations per IP**, then rotate (the farm rotates automatically from the pool)
- Test your pool any time: `python scripts/rotate_proxies.py proxies.txt`

## Usage

```bash
python farm_bai.py <workers> <accounts_per_worker> [proxies_file]

# examples:
python farm_bai.py 1 1 proxies.txt      # smoke test: 1 account
python farm_bai.py 4 10 proxies.txt     # proven config: 40 accounts, ~7-9 min
python farm_bai.py 8 10 proxies.txt     # scale: 80 accounts, ~5-10 min
```

What you'll see:

```
=== BAI FARM: 4 worker x 10 accounts = target 40 ===
[proxy] 100 proxies loaded from proxies.txt
[warmup] geoip OK
[W1#1] TOKEN (709ch) @ 4s
[W1#1] OK  0xAB12...cd  key=sk-17s...p0b7  verified=True
[progress] 12/40 (ok=12)
...
=== RESULTS ===
success: 40/40 accounts
```

### Outputs (all gitignored)

| Path | Contents |
|---|---|
| `data/accounts.json` | Every account: wallet address, private key, user id, `sk-...` key, verified flag, proxy used |
| `data/sessions/<addr>.json` | Session cookies + JWT per account (reuse logins without re-farming) |
| `logs/debug/` | Debug artifacts when an attempt fails |

## Using the harvested keys

The API is OpenAI-compatible:

```bash
curl https://api.b.ai/v1/chat/completions \
  -H "Authorization: Bearer sk-..." \
  -H "Content-Type: application/json" \
  -d '{"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "hi"}]}'
```

Free models per key: `deepseek-v4-flash`, `glm-5.3-flash`, `qwen3.8-flash`,
`hy3` (`minimax-m3` requires a deposit).

## Scripts

| Script | What it does |
|---|---|
| `scripts/single_account.py <proxy_url>` | Farm exactly one account (educational / smoke test) |
| `scripts/verify_keys.py` | Check every key against the API — prints ALIVE/DEAD per account |
| `scripts/summary.py` | Totals: accounts, verified count, proxies used, run dates |
| `scripts/rotate_proxies.py <file>` | Test every proxy, split into `<name>_alive.txt` / `<name>_dead.txt` |

## Tuning & performance

| Knob | Guidance |
|---|---|
| Workers | 4 = proven stable; 8 ≈ 16 accounts/min if you have the cores and proxy quota |
| RAM | ~1.5-2 GB per worker (Camoufox) |
| Registrations per IP | Keep 1-3; the pool rotation handles it automatically |
| Bandwidth | ~2-4 MB per registration of proxy quota |
| Per-account time | ~25-35 s (token @ ~4 s) — the browser is closed immediately after minting |

The real bottleneck is **proxy quota, not compute**. 3 GB of residential
bandwidth ≈ 500-800 registrations.

## Troubleshooting

Full symptom → cause → fix table in
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Quick hits:

- `login rejected: null` → your proxy IP is burned; rotate / check same-IP rule
- `error=Configuration` → per-IP registration rate limit; fresh IP needed
- Chinese UI → `locale="en-US"` missing from the Camoufox launch
- Solver keys rejected → expected; external solvers cannot work here (see RESEARCH.md)

## FAQ

**Why not a pure-API solution — no browser at all?**
The Turnstile token is cryptographically bound to a real widget rendered by a
real browser. Without the browser there is no valid token. The farm already
minimizes browser time to ~10 s per account.

**Why not use an external captcha solver?**
Tested exhaustively, including an airtight proxy-pinned re-test. Solver tokens
are form-valid but structurally different (745-766 vs 624-709 chars) and bound
to the widget context inside the app page. Server rejects them. Details:
[docs/RESEARCH.md](docs/RESEARCH.md).

**Can I skip proxies?**
For 1-2 test accounts, yes (`python scripts/single_account.py`). At volume the
per-IP rate limit kicks in after a few registrations and your IP is done.

**Is one token reusable?**
No — one token, one login.

**Do old accounts get rate-limited?**
No, only new registrations. Logins with saved sessions (`data/sessions/`) are
unaffected.

## Repository layout

```
bai-farm/
├── farm_bai.py               # the whole farm (standalone)
├── requirements.txt
├── proxies.example.txt       # format reference (real proxies.txt is gitignored)
├── scripts/                  # verify_keys / rotate_proxies / summary / single_account
├── docs/                     # ARCHITECTURE / RESEARCH / TROUBLESHOOTING / ETHICS
├── data/                     # gitignored runtime output (accounts + sessions)
└── logs/                     # gitignored debug artifacts
```

## Roadmap

- [ ] Warm browser reuse (~15-20 s/account instead of 25-35)
- [ ] Optional multi-account per IP (2-4 regis/IP, saves quota, adds risk)
- [ ] Simple key-pool gateway (rotate across harvested keys for downstream tools)

## License

MIT — see [LICENSE](LICENSE). Use responsibly; you own your actions.
