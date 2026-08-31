"""Farm exactly ONE account (educational / smoke test).

Usage:
  python scripts/single_account.py [proxy_url]
  python scripts/single_account.py                      # direct IP (will hit per-IP limit fast!)
  python scripts/single_account.py http://user:pass@host:port
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from farm_bai import parse_proxy, farm_one, merge_save

def main():
    proxy = parse_proxy(sys.argv[1]) if len(sys.argv) > 1 else None
    if not proxy:
        print("[!] running DIRECT — fine for 1-2 test accounts, but registration is")
        print("    rate-limited per IP; use a residential proxy file for volume.\n")
    print("farming 1 account... (browser phase ~10s, http phase ~5s)")
    r = farm_one(1, 1, proxy)
    if r["ok"]:
        merge_save([r])
    print(json.dumps({k: (v[:24] + "..." if k == "api_key" and v else v) for k, v in r.items()}, indent=2))
    if r["ok"]:
        print("\nOK — full record (with private key) saved to data/accounts.json")
    else:
        print("\nFAILED — see docs/TROUBLESHOOTING.md")
        sys.exit(1)

if __name__ == "__main__":
    main()
