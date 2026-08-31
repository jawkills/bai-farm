# Ethics & Legal Disclaimer

**Read this before using this software.**

## What this project does

Automates the creation of accounts on a third-party service (chat.b.ai /
"BAI") at scale, using locally generated cryptocurrency wallets, in order to
harvest the free API credits granted to each new account.

## Why this is likely against the rules

- Creating multiple accounts to multiply free credits almost certainly
  violates the target service's Terms of Service.
- Automating signups typically violates anti-abuse provisions regardless of
  jurisdiction.
- The operator of the target service can revoke keys, ban IP ranges, require
  deposits/verification, or pursue legal remedies at any time.

## You accept

- All risk of using this software is yours: legal, financial, and operational.
- The authors and contributors are **not affiliated with** the target service
  and provide this code **as-is**, for **educational and research purposes**,
  demonstrating browser automation, anti-fingerprinting, and anti-bot system
  analysis techniques.
- If the target service (or its anti-bot provider) asks this repository to be
  taken down, it will be.

## Practical guidance

- Keep usage volume within what you are prepared to defend.
- Do not resell the harvested credentials or build a commercial service on
  them.
- Expect every harvested key to be revocable without notice — design your own
  tooling to fail gracefully (`scripts/verify_keys.py` exists for this).
- Consider whether a paid API plan would simply cost you less than your time
  and proxy budget.

## For researchers

The interesting parts of this project are documented in
[ARCHITECTURE.md](ARCHITECTURE.md) (why each technique works) and
[RESEARCH.md](RESEARCH.md) (everything that fails and why). If you study
anti-bot systems, that pair of documents is the actual payload of this repo.
