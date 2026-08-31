"""Test every proxy in a file and split into alive/dead files (keep pool fresh)."""
import sys, os
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as cffi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from farm_bai import parse_proxy

def test_proxy(url):
    try:
        r = cffi.get("https://api.ipify.org?format=json", proxy=url, timeout=12, impersonate="chrome131")
        return r.status_code == 200, url, r.json().get("ip", "?")
    except Exception:
        return False, url, "-"

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "proxies.txt"
    urls = [p for ln in open(src, encoding="utf-8") for p in [parse_proxy(ln)] if p]
    print(f"testing {len(urls)} proxies from {src} (20 threads)...")
    alive, dead = [], []
    with ThreadPoolExecutor(max_workers=20) as ex:
        for ok, url, ip in ex.map(test_proxy, urls):
            (alive if ok else dead).append((url, ip))
    base = os.path.splitext(src)[0]
    with open(base + "_alive.txt", "w") as f:
        for url, ip in alive:
            f.write(url + "\n")
    with open(base + "_dead.txt", "w") as f:
        for url, ip in dead:
            f.write(url + "\n")
    print(f"\nalive: {len(alive)} -> {base}_alive.txt")
    print(f"dead : {len(dead)} -> {base}_dead.txt")
    for url, ip in alive[:5]:
        host = url.split("@")[-1]
        print(f"  {host}  exit-ip={ip}")

if __name__ == "__main__":
    main()
