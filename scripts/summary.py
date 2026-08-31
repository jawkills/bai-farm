"""Summary of data/accounts.json: totals, verified, proxies used, newest run."""
import os, sys, json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNTS = os.path.join(BASE, "data", "accounts.json")
SESSIONS = os.path.join(BASE, "data", "sessions")

def main():
    if not os.path.exists(ACCOUNTS):
        print(f"no accounts file at {ACCOUNTS} — run farm_bai.py first")
        sys.exit(1)
    accs = json.load(open(ACCOUNTS, encoding="utf-8"))
    ok = [a for a in accs if a.get("ok", a.get("api_key"))]
    verified = [a for a in accs if a.get("verified")]
    with_key = [a for a in accs if a.get("api_key")]
    proxies = sorted({(a.get("proxy") or "direct").split("@")[-1] for a in accs})
    ts = sorted({a.get("ts", "?") for a in accs})
    sess = len([f for f in os.listdir(SESSIONS) if f.endswith(".json")]) if os.path.isdir(SESSIONS) else 0
    print("=== BAI FARM ACCOUNT SUMMARY ===")
    print(f"total accounts : {len(accs)}")
    print(f"successful     : {len(ok)}")
    print(f"with api key   : {len(with_key)}")
    print(f"verified (200) : {len(verified)}")
    print(f"sessions saved : {sess}")
    print(f"first run      : {ts[0] if ts else '-'}")
    print(f"last run       : {ts[-1] if ts else '-'}")
    print(f"distinct proxy exit hosts used: {len(proxies)}")

if __name__ == "__main__":
    main()
