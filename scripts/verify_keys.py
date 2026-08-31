"""Verify all API keys in data/accounts.json against api.b.ai (alive or dead?)."""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from curl_cffi import requests as cffi

ACCOUNTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "accounts.json")
MODEL = "qwen3.8-flash"

def check(key, proxy=None):
    try:
        r = cffi.post("https://api.b.ai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": MODEL, "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 10},
                      timeout=45, proxy=proxy)
        return r.status_code == 200, r.status_code
    except Exception as e:
        return False, str(e)[:60]

def main():
    if not os.path.exists(ACCOUNTS):
        print(f"no accounts file at {ACCOUNTS}")
        sys.exit(1)
    accs = json.load(open(ACCOUNTS, encoding="utf-8"))
    with_key = [a for a in accs if a.get("api_key")]
    print(f"checking {len(with_key)}/{len(accs)} accounts (model={MODEL})\n")
    alive = dead = 0
    for i, a in enumerate(with_key, 1):
        proxy = a.get("proxy") if a.get("proxy") and a.get("proxy") != "direct" else None
        ok, info = check(a["api_key"], proxy)
        alive += ok; dead += (not ok)
        wallet = (a.get("wallet") or "?")[:14]
        print(f"[{i:>3}] {'ALIVE ' if ok else 'DEAD  '} {wallet}..  (status={info})")
    print(f"\n=== {alive} alive / {dead} dead of {len(with_key)} ===")
    sys.exit(0 if dead == 0 else 2)

if __name__ == "__main__":
    main()
