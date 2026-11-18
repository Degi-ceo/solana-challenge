#!/usr/bin/env python3
"""Reachability check for every external API the bot depends on (task 0).

Uses the same stdlib urllib path as bot.py, so a pass here means the bot can reach the host.
Read-only GET/POST requests to public endpoints; no keys, no transactions.

  python3 netcheck.py            # human-readable table
  python3 netcheck.py --md       # markdown table (for JOURNAL.md)
"""
import json
import sys
import time
import urllib.error
import urllib.request

SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL_USDC_RAYDIUM = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2"
Q = f"inputMint={SOL}&outputMint={USDC}&amount=10000000&slippageBps=50"

# (name, url, json body or None, function(parsed json) -> short evidence string)
CHECKS = [
    ("DexScreener boosts", "https://api.dexscreener.com/token-boosts/top/v1", None,
     lambda j: f"{len(j)} boosted tokens"),
    ("DexScreener search", "https://api.dexscreener.com/latest/dex/search?q=SOL%20USDC", None,
     lambda j: f"{len(j.get('pairs') or [])} pairs"),
    ("GeckoTerminal trending", "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools", None,
     lambda j: f"{len(j.get('data') or [])} pools"),
    ("GeckoTerminal OHLCV 5m",
     f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{SOL_USDC_RAYDIUM}/ohlcv/minute?aggregate=5&limit=10",
     None, lambda j: f"{len(j['data']['attributes']['ohlcv_list'])} candles"),
    ("Solana RPC getSlot", "https://api.mainnet-beta.solana.com",
     {"jsonrpc": "2.0", "id": 1, "method": "getSlot"}, lambda j: f"slot {j['result']}"),
    ("Jupiter quote-api v6", f"https://quote-api.jup.ag/v6/quote?{Q}", None,
     lambda j: f"outAmount {j.get('outAmount')}"),
    ("Jupiter lite-api v1", f"https://lite-api.jup.ag/swap/v1/quote?{Q}", None,
     lambda j: f"outAmount {j.get('outAmount')}"),
    ("Jupiter api.jup.ag v1", f"https://api.jup.ag/swap/v1/quote?{Q}", None,
     lambda j: f"outAmount {j.get('outAmount')}"),
    ("RugCheck summary", f"https://api.rugcheck.xyz/v1/tokens/{USDC}/report/summary", None,
     lambda j: f"score {j.get('score')}, {len(j.get('risks') or [])} risks"),
]


def probe(url, body, timeout=20):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "User-Agent": "paper-trader-netcheck/0.1", "Content-Type": "application/json", "Accept": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, time.time() - t0, raw, None
    except urllib.error.HTTPError as e:
        return e.code, time.time() - t0, e.read()[:300], None
    except Exception as e:  # DNS, proxy CONNECT refusal, TLS, timeout
        return None, time.time() - t0, b"", repr(e)[:160]


def run():
    rows = []
    for name, url, body, ev in CHECKS:
        host = url.split("/")[2]
        code, dt, raw, err = probe(url, body)
        if err:
            status, note = "BLOCKED/ERROR", err
        elif code == 200:
            try:
                status, note = "OK", ev(json.loads(raw))
            except Exception as e:
                status, note = "OK (unexpected body)", repr(e)[:120]
        else:
            status, note = f"HTTP {code}", raw.decode("utf-8", "replace").replace("\n", " ")[:120]
        rows.append((name, host, status, f"{dt:.2f}s", note))
    return rows


if __name__ == "__main__":
    rows = run()
    if "--md" in sys.argv:
        print("| check | host | status | latency | evidence |\n|---|---|---|---|---|")
        for r in rows:
            print("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
    else:
        for r in rows:
            print(f"{r[0]:<24} {r[1]:<30} {r[2]:<14} {r[3]:>6}  {r[4]}")
