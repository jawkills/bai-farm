"""
BAI FARM — chat.b.ai wallet-farm: new account + API key per wallet
===================================================================
Proven: 44/44 accounts, 100% success rate (see README.md).

Flow:
  1. Generate fresh EVM wallet (eth_account, local, free)
  2. Camoufox (anti-fingerprint Firefox, geoip) + EIP-6963 mock MetaMask (DOM script tag)
  3. Click Log in -> Other login methods -> EVM -> MetaMask
  4. Solve Cloudflare Turnstile interactively: click checkbox FROM INSIDE the
     challenge frame via page.frames (closed shadow DOM is invisible to JS)
  5. personal_sign relayed to Python (eth_account) -> POST /api/auth/callback/metamask
  6. Session cookie -> tRPC apiKey.createApiKey -> sk-... key
  7. Verify key (qwen3.8-flash) -> save

Usage:
  python farm_bai.py [workers] [accounts_per_worker] [proxies_file]
  python farm_bai.py 2 5                    # 2 workers x 5 accounts = 10 accounts (direct IP)
  python farm_bai.py 2 5 proxies.txt        # + proxy rotation per attempt (anti rate-limit)

Proxy file format (one per line, all accepted):
  host:port
  host:port:user:pass
  http://user:pass@host:port   (socks5:// works too)

Outputs (gitignored):
  data/accounts.json          <- all farmed accounts (wallet + api key)
  data/sessions/<addr>.json   <- session cookies + JWT per account (reuse login)
  logs/debug/                 <- created for debugging artifacts

IMPORTANT:
  - Registration is rate-limited PER IP. Residential proxies + rotation required.
  - Phase 2 (HTTP) MUST use the same proxy IP as Phase 1 (browser) — Cloudflare
    siteverify cross-checks the token-minting IP vs the token-consuming IP.
  - External captcha solvers DO NOT WORK for chat.b.ai: tokens are bound to the
    original widget rendered inside the app page. See docs/RESEARCH.md.
"""
import json, time, random, string, sys, os, multiprocessing as mp
from eth_account import Account
from eth_account.messages import encode_defunct
from curl_cffi import requests as cffi
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
LOG_DIR = os.path.join(BASE, "logs")
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
SESSION_DIR = os.path.join(DATA_DIR, "sessions")
DEBUG_DIR = os.path.join(LOG_DIR, "debug")
os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# ============================ JS BLOCKS (proven v11) ============================

RELAY_JS = """
(() => {
  window.addEventListener('__py_req', (e) => {
    let req; try { req = JSON.parse(e.detail); } catch (err) { return; }
    const fn = req.kind === 'sign' ? window.__pySign : null;
    if (typeof fn !== 'function') {
      window.dispatchEvent(new CustomEvent('__py_resp', {detail: JSON.stringify({id: req.id, result: null, error: 'no bridge'})}));
      return;
    }
    Promise.resolve(fn(req.payload || '')).then((result) => {
      window.dispatchEvent(new CustomEvent('__py_resp', {detail: JSON.stringify({id: req.id, result: result === undefined ? null : result})}));
    }).catch((err) => {
      window.dispatchEvent(new CustomEvent('__py_resp', {detail: JSON.stringify({id: req.id, result: null, error: String(err)})}));
    });
  });
})();
"""

PYCALL_JS = """
(() => {
  if (window.__pyCall) return;
  window.__pyCall = (kind, payload) => new Promise((resolve) => {
    const id = 'q' + Math.random().toString(36).slice(2);
    const t0 = Date.now();
    const handler = (e) => {
      try {
        const d = JSON.parse(e.detail);
        if (d && d.id === id) {
          window.removeEventListener('__py_resp', handler); clearInterval(iv); resolve(d.result);
        }
      } catch (err) {}
    };
    const iv = setInterval(() => {
      if (Date.now() - t0 > 150000) { window.removeEventListener('__py_resp', handler); clearInterval(iv); resolve(null); }
    }, 500);
    window.addEventListener('__py_resp', handler);
    window.dispatchEvent(new CustomEvent('__py_req', {detail: JSON.stringify({id: id, kind: kind, payload: payload || ''})}));
  });
})();
"""

MOCK_JS = """
(() => {
  const ADDR = '__ADDR__';
  const listeners = {};
  const FALLBACK = {
    'eth_chainId': '0x1', 'net_version': '1',
    'eth_getBalance': '0x0', 'eth_blockNumber': '0x1',
    'eth_gasPrice': '0x1dcd65000', 'eth_getCode': '0x',
    'eth_call': '0x', 'eth_getTransactionCount': '0x0',
  };
  const provider = {
    isMetaMask: true,
    request: async (args) => {
      const m = args && args.method;
      if (m === 'eth_requestAccounts' || m === 'eth_accounts') return [ADDR];
      if (m in FALLBACK) return FALLBACK[m];
      if (m === 'personal_sign') {
        const out = await window.__pyCall('sign', JSON.stringify(args.params));
        return out;
      }
      if (m === 'wallet_switchEthereumChain') return null;
      if (m === 'wallet_getPermissions') return [{parentCapability:'eth_accounts',state:{}}];
      return null;
    },
    on: (evt, cb) => { (listeners[evt] = listeners[evt] || []).push(cb); },
    removeListener: (evt, cb) => { listeners[evt] = (listeners[evt]||[]).filter(c => c !== cb); },
  };
  window.__mmProvider = provider;
  try { window.ethereum = provider; } catch(e) {}
  window.ethereumProviders = { MetaMask: provider };
  const INFO = { uuid: '__UUID__', name: 'MetaMask',
                  icon: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"/>',
                  rdns: 'io.metamask' };
  const announce = () => {
    try { window.dispatchEvent(new CustomEvent('eip6963:announceProvider', { detail: { info: INFO, provider: provider } })); } catch (e) {}
  };
  window.addEventListener('eip6963:requestProvider', announce);
  window.__announceMM = announce;
})();
"""

REAL_TS_WRAP_JS = """
(() => {
  const wrapTS = () => {
    const ts = window.turnstile;
    if (!ts || ts.__wrapped || typeof ts.render !== 'function') return false;
    const realRender = ts.render.bind(ts);
    ts.render = function(el, cfg) {
      const id = realRender(el, cfg);
      const poll = setInterval(() => {
        try {
          const tok = ts.getResponse(id);
          if (tok && tok.length > 10) {
            clearInterval(poll);
            try { cfg && cfg.callback && cfg.callback(tok); } catch(e) {}
          }
        } catch(e) {}
      }, 500);
      return id;
    };
    ts.__wrapped = true;
    return true;
  };
  const iv = setInterval(() => { if (wrapTS()) clearInterval(iv); }, 100);
  setTimeout(() => clearInterval(iv), 90000);
})();
"""

def inject(page, code):
    page.evaluate("(code) => { const s = document.createElement('script'); s.textContent = code; document.documentElement.appendChild(s); s.remove(); }", code)


def parse_proxy(line):
    """'host:port' / 'host:port:user:pass' / 'http://user:pass@host:port' -> URL string."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) == 4:
        h, p, u, pw = parts
        return f"http://{u}:{pw}@{h}:{p}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None


def cf_proxy_dict(url):
    """Proxy URL -> dict for Camoufox/Playwright."""
    u = urlparse(url)
    d = {"server": f"{u.scheme or 'http'}://{u.hostname}:{u.port}"}
    if u.username:
        d["username"] = u.username
    if u.password:
        d["password"] = u.password
    return d


# ============================ CORE FLOW ============================

def farm_one(wid, idx, proxy=None):
    """Farm 1 account. Return result dict."""
    import uuid as uuidlib
    from camoufox.sync_api import Camoufox

    acct = Account.create()
    ADDR = acct.address
    tag = f"[W{wid}#{idx}]"
    tagp = f"{tag}({(urlparse(proxy).hostname if proxy else 'direct')})"
    result = {"ok": False, "wallet": ADDR, "privkey": acct.key.hex(),
              "user_id": None, "username": None, "api_key": None,
              "verified": False, "error": None, "proxy": proxy or "direct",
              "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    mock_js = MOCK_JS.replace("__ADDR__", ADDR).replace("__UUID__", str(uuidlib.uuid4()))
    cfd = cf_proxy_dict(proxy) if proxy else None

    def py_sign(raw):
        try:
            params = json.loads(raw)
            if not isinstance(params, list):
                params = [params]
        except Exception:
            params = [raw]
        p0 = params[0] if params else ""
        if isinstance(p0, str) and p0.startswith("0x") and len(p0) > 2 and all(c in "0123456789abcdefABCDEF" for c in p0[2:]):
            try:
                msg = bytes.fromhex(p0[2:]).decode("utf-8")
            except UnicodeDecodeError:
                msg = p0
        else:
            msg = p0
        sig = acct.sign_message(encode_defunct(text=msg))
        return "0x" + sig.signature.hex()

    # ===== PHASE 1 (browser): dialog + grab Turnstile token via frame-click =====
    token = None
    # NOTE: image blocking was reverted — Camoufox warns it is a WAF bot signal (risk > benefit)
    with Camoufox(headless=True, geoip=True, proxy=cfd, locale="en-US") as browser:
        page = browser.new_page()
        page.expose_function("__pySign", py_sign)
        page.add_init_script(RELAY_JS)

        page.goto("https://chat.b.ai/chat", timeout=90000, wait_until="domcontentloaded")
        page.wait_for_selector("text=Log in", timeout=30000)
        inject(page, PYCALL_JS)
        inject(page, mock_js)
        inject(page, REAL_TS_WRAP_JS)
        time.sleep(0.8)
        page.evaluate("() => window.__announceMM && window.__announceMM()")
        time.sleep(1)

        for label, sel in [("login", page.get_by_text("Log in", exact=True).first),
                           ("expand", page.get_by_text("Other login methods", exact=False).first),
                           ("evm", page.get_by_text("EVM", exact=True).first)]:
            sel.click(timeout=10000)
            time.sleep(0.8)
        try:
            page.locator("button").filter(has_text="MetaMask").locator("visible=true").first.click(timeout=8000)
        except Exception as e:
            result["error"] = f"click_metamask: {str(e)[:120]}"
            raise RuntimeError(result["error"])

        # grab token: click checkbox inside the cf frame until cf-turnstile-response fills
        t0 = time.time()
        while time.time() - t0 < 120:
            time.sleep(2)
            try:
                tok = page.evaluate("() => { const i = document.querySelector('input[name=\\\"cf-turnstile-response\\\"]'); return i ? i.value : ''; }")
            except Exception:
                tok = ""
            if tok and len(tok) > 100:
                token = tok
                print(f"{tag} TOKEN ({len(tok)}ch) @ {int(time.time()-t0)}s", flush=True)
                break
            cframes = [f for f in page.frames if "challenges.cloudflare.com" in (f.url or "")]
            for f in cframes:
                try:
                    f.locator("body").click(position={"x": 28, "y": 30}, timeout=2000)
                    print(f"{tag} TS-click @ {int(time.time()-t0)}s", flush=True)
                except Exception:
                    pass
                break
        if not token:
            result["error"] = "no turnstile token"
            raise RuntimeError(result["error"])

    # ===== PHASE 2 (pure curl_cffi, SAME proxy): login -> JWT -> API key =====
    s = cffi.Session(impersonate="chrome131", proxy=proxy) if proxy else cffi.Session(impersonate="chrome131")
    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
          "Origin": "https://chat.b.ai", "Referer": "https://chat.b.ai/chat"}
    csrf = s.get("https://chat.b.ai/api/auth/csrf", headers=UA, timeout=30).json()["csrfToken"]
    expiry = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 86400))
    nonce = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6)) + str(int(time.time() * 1000))
    msg = ("Welcome to BAI !\n"
           "https://chat.b.ai wants you to sign in with your account:\n"
           f"{ADDR}\n\n"
           "Chain ID: 0x1\n"
           f"Expiration Time: {expiry}\n"
           f"Nonce: {nonce}")
    sig = "0x" + acct.sign_message(encode_defunct(text=msg)).signature.hex()
    data = {"chain": "eth", "message": msg, "redirect": "false", "signature": sig,
            "turnstileToken": token, "version": "2", "csrfToken": csrf,
            "callbackUrl": "https://chat.b.ai/chat"}
    r = s.post("https://chat.b.ai/api/auth/callback/metamask", data=data,
               headers={**UA, "X-Auth-Return-Redirect": "1"}, timeout=30)
    r2 = s.get("https://chat.b.ai/api/auth/session", headers=UA, timeout=30)
    if '"user"' not in r2.text:
        result["error"] = f"login rejected: {r2.text[:100]} [GATE? per-IP registration rate-limit -> rotate proxy]"
        raise RuntimeError(result["error"])
    sess = r2.json()
    result["user_id"] = sess.get("user", {}).get("id")
    result["username"] = sess.get("user", {}).get("name")
    for c in s.cookies.jar:
        try:
            s.cookies.set(c.name, c.value, domain=".b.ai")
        except Exception:
            pass

    UA2 = {**UA, "Referer": "https://chat.b.ai/key"}
    INP = '%7B%220%22%3A%7B%22json%22%3Anull%2C%22meta%22%3A%7B%22values%22%3A%5B%22undefined%22%5D%2C%22v%22%3A1%7D%7D%7D'
    r = s.get("https://chat.b.ai/trpc/lambda/user.getUserState?batch=1&input=" + INP, headers=UA2, timeout=30)
    jwt = r.json()[0]["result"]["data"]["json"].get("apiAccessToken")

    r2 = s.post("https://chat.b.ai/trpc/lambda/apiKey.createApiKey?batch=1",
                data=json.dumps({"0": {"json": {"name": "default"}}}),
                headers={**UA2, "Content-Type": "application/json"}, timeout=30)
    kd = r2.json()
    try:
        key = kd[0]["result"]["data"]["json"]["key"]
    except Exception:
        result["error"] = f"createApiKey: {r2.text[:150]}"
        raise RuntimeError(result["error"])
    result["api_key"] = key

    # verify: qwen3.8-flash
    try:
        rv = cffi.post("https://api.b.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": "qwen3.8-flash", "messages": [{"role": "user", "content": "Say OK"}], "max_tokens": 20},
            timeout=60, proxy=proxy)
        result["verified"] = rv.status_code == 200
    except Exception:
        pass

    # save session cookies
    safe = ADDR[:12]
    with open(os.path.join(SESSION_DIR, f"{safe}.json"), "w") as f:
        json.dump({"wallet": ADDR, "privkey": acct.key.hex(), "user_id": result["user_id"],
                   "cookies": s.cookies.get_dict(), "jwt": jwt}, f, indent=1)

    result["ok"] = True
    return result

def farm_one_safe(wid, idx, proxy_q=None, attempts=3):
    last_err = None
    for a in range(1, attempts + 1):
        proxy = None
        if proxy_q is not None:
            try:
                proxy = proxy_q.get(timeout=180)
            except Exception:
                print(f"[W{wid}#{idx}] no proxy available, stop", flush=True)
                break
            if proxy is None:
                break
        try:
            r = farm_one(wid, idx, proxy)
            if r["ok"]:
                if proxy_q is not None:
                    proxy_q.put(proxy)
                return r
            last_err = r.get("error")
        except Exception as e:
            last_err = str(e)[:200]
        print(f"[W{wid}#{idx}] attempt {a} FAILED [{(proxy or 'direct')}]: {last_err}", flush=True)
        if proxy_q is not None and proxy is not None:
            proxy_q.put(proxy)
        time.sleep(3)
    return {"ok": False, "wallet": None, "privkey": None, "user_id": None, "username": None,
            "api_key": None, "verified": False, "error": last_err, "proxy": "n/a",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S")}

def worker_main(wid, count, q, proxy_q=None):
    for i in range(1, count + 1):
        print(f"[W{wid}] === account {i}/{count} ===", flush=True)
        r = farm_one_safe(wid, i, proxy_q)
        r["worker"] = wid
        q.put(r)
        if r["ok"]:
            print(f"[W{wid}#{i}] OK  {r['wallet']}  key={r['api_key']}  verified={r['verified']}", flush=True)
        else:
            print(f"[W{wid}#{i}] FAILED: {r['error']}", flush=True)
        time.sleep(random.uniform(2, 4))

def merge_save(acc):
    old = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            old = json.load(open(ACCOUNTS_FILE))
        except Exception:
            old = []
    wallets = {a.get("wallet") for a in old}
    for a in acc:
        if a.get("wallet") and a["wallet"] not in wallets:
            old.append(a)
            wallets.add(a["wallet"])
    json.dump(old, open(ACCOUNTS_FILE, "w"), indent=1)

if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    per = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    proxy_file = sys.argv[3] if len(sys.argv) > 3 else None
    total = workers * per
    print(f"=== BAI FARM: {workers} worker x {per} accounts = target {total} ===", flush=True)

    proxy_q = None
    if proxy_file:
        plist = []
        for ln in open(proxy_file, encoding="utf-8"):
            p = parse_proxy(ln)
            if p:
                plist.append(p)
        if plist:
            proxy_q = mp.Queue()
            for p in plist:
                proxy_q.put(p)
            print(f"[proxy] {len(plist)} proxies loaded from {proxy_file}", flush=True)
        else:
            print(f"[proxy] {proxy_file} empty/bad format -> running direct", flush=True)

    # warmup geoip (avoid parallel download race in workers)
    try:
        from camoufox.sync_api import Camoufox
        with Camoufox(headless=True, geoip=True) as b:
            b.new_page().close()
        print("[warmup] geoip OK", flush=True)
    except Exception as e:
        print(f"[warmup] skipped: {str(e)[:100]}", flush=True)

    q = mp.Queue()
    procs = [mp.Process(target=worker_main, args=(w + 1, per, q, proxy_q), daemon=True) for w in range(workers)]
    for p in procs:
        p.start()

    results = []
    t0 = time.time()
    while len(results) < total and time.time() - t0 < total * 420 + 300:
        try:
            r = q.get(timeout=10)
            results.append(r)
            merge_save([r])
            ok = sum(1 for x in results if x["ok"])
            print(f"[progress] {len(results)}/{total} (ok={ok})", flush=True)
        except Exception:
            pass
        if any(not p.is_alive() for p in procs):
            # drain queue before deciding
            while not q.empty():
                try:
                    results.append(q.get_nowait()); merge_save([results[-1]])
                except Exception:
                    break
            if all(not p.is_alive() for p in procs) and len(results) < total:
                print("[warn] a worker died before finishing", flush=True)
                break

    for p in procs:
        p.join(timeout=10)

    ok = [r for r in results if r["ok"]]
    print("\n=== RESULTS ===", flush=True)
    print(f"success: {len(ok)}/{len(results) or 0} accounts", flush=True)
    for r in ok:
        print(f"  {r['wallet']}  {r['api_key']}  verified={r['verified']}", flush=True)
    print(f"saved: {ACCOUNTS_FILE}", flush=True)
