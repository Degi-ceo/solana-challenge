"""Read-only market measurements used by docs/RESEARCH_MEMECOIN_SYSTEM.md: priority fees, fresh pool liquidity, Jupiter round-trip QUOTES, RugCheck, candle event study.
Sends no transactions and uses no keys. Run from anywhere: python3 bot/research/measure_market.py (needs data/market.db from data.py)."""
import json, time, statistics as st, sys
import os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bot, data, backtest as bt
db = data.connect(); now = time.time()
SOL = "So11111111111111111111111111111111111111112"
RPC = "https://api.mainnet-beta.solana.com"

print("=== A. priority fees on the public RPC (last ~150 slots) ===")
r = bot.http_json(RPC, {"jsonrpc": "2.0", "id": 1, "method": "getRecentPrioritizationFees", "params": []})
fees = [x["prioritizationFee"] for x in r["result"]]
nz = sorted(f for f in fees if f > 0)
print("slots:", len(fees), "| share with fee>0: %.0f%%" % (100 * len(nz) / len(fees)), "| median(nonzero) microlamports/CU:", st.median(nz) if nz else 0,
      "| p90:", nz[int(.9 * len(nz))] if nz else 0, "| max:", max(fees))
print("cost of a 200k-CU swap at p90 fee: %.6f SOL" % ((nz[int(.9 * len(nz))] if nz else 0) * 200_000 / 1e6 / 1e9))

print("\n=== B. liquidity of recently created PumpSwap / launchpad pools (GeckoTerminal new_pools) ===")
rows = []
for pg in (1, 2, 3):
    j = data.gt_get(f"/new_pools?page={pg}")
    for d in (j or {}).get("data", []):
        a = d["attributes"]; dex = d["relationships"]["dex"]["data"]["id"]
        age_min = (now - data._iso(a["pool_created_at"])) / 60
        rows.append((dex, float(a["reserve_in_usd"] or 0), age_min, a["name"]))
from collections import defaultdict
byd = defaultdict(list)
for dex, liq, age, name in rows: byd[dex].append(liq)
for dex, v in sorted(byd.items(), key=lambda kv: -len(kv[1])):
    v.sort(); print(f"{dex:<20} n={len(v):<3} liquidity median ${v[len(v)//2]:,.0f}  p10 ${v[int(.1*len(v))]:,.0f}  p90 ${v[int(.9*len(v))]:,.0f}")

print("\n=== C. real Jupiter round-trip cost on memecoin pools (quote only, nothing sent) ===")
pools = [dict(p) for p in db.execute("SELECT * FROM pools WHERE liq_now<=50000000 AND dex IN ('pumpswap','moonshot','meteora','raydium-launchlab','meteora-dbc') ORDER BY liq_now DESC")]
pick = [p for p in pools if p["base_mint"].endswith("pump")] [:30]
sample = pick[:2] + pick[len(pick)//2-1:len(pick)//2+1] + pick[-3:]
sol_usd = 74.4
for p in sample:
    out = []
    for usd in (1, 5):
        lam = int(usd / sol_usd * 1e9)
        q = bot.http_json(f"https://lite-api.jup.ag/swap/v1/quote?inputMint={SOL}&outputMint={p['base_mint']}&amount={lam}&slippageBps=300", retries=1)
        if not q or "outAmount" not in q: out.append(f"${usd}: no route"); continue
        b = bot.http_json(f"https://lite-api.jup.ag/swap/v1/quote?inputMint={p['base_mint']}&outputMint={SOL}&amount={q['outAmount']}&slippageBps=300", retries=1)
        if not b or "outAmount" not in b: out.append(f"${usd}: SELL no route"); continue
        rt = 100 * (1 - int(b["outAmount"]) / lam)
        route = "/".join(x["swapInfo"]["label"] for x in q["routePlan"])
        out.append(f"${usd}: buy impact {float(q.get('priceImpactPct') or 0):.2f}% round-trip loss {rt:.2f}% via {route}")
        time.sleep(0.4)
    print(f"{p['name'][:14]:<15} {p['dex']:<10} liq ${p['liq_now']:>9,.0f} | " + " | ".join(out))

print("\n=== D. RugCheck on the same tokens (summary endpoint) ===")
for p in sample[:6]:
    j = bot.http_json(f"https://api.rugcheck.xyz/v1/tokens/{p['base_mint']}/report/summary", retries=1)
    if not j: print(p["name"], "no data"); continue
    risks = [f"{x.get('name')}({x.get('level')})" for x in j.get("risks", [])][:5]
    print(f"{p['name'][:14]:<15} score_normalised={j.get('score_normalised')} score={j.get('score')} lpLockedPct={j.get('lpLockedPct')} risks={risks}")
    time.sleep(0.5)

print("\n=== E. own-data event study: launchpad-style pools with candles from creation ===")
meme = []
for p in db.execute("SELECT * FROM pools WHERE liq_now<=50000000"):
    if not bt.is_launchpad(dict(p)): continue
    cs = [tuple(r) for r in db.execute("SELECT ts,o,h,l,c,v FROM candles WHERE pool=? ORDER BY ts", (p["pool"],))]
    if len(cs) < 30: continue
    if cs[0][0] - p["created_ts"] > 3600: continue          # history must start near creation
    meme.append((p["name"], cs, p["created_ts"]))
print("launchpad-style pools with history from creation:", len(meme))
def px_at(cs, t0, hrs):
    tgt = t0 + hrs * 3600
    c = [x for x in cs if x[0] <= tgt]
    return c[-1][4] if c and cs[-1][0] >= tgt - 600 else None
for entry_h in (1, 6, 24, 72):
    res = {h: [] for h in (6, 24, 72, 168)}
    for name, cs, t0 in meme:
        e = px_at(cs, t0, entry_h)
        if not e: continue
        for h in res:
            x = px_at(cs, t0, entry_h + h)
            if x: res[h].append(100 * (x / e - 1))
    line = []
    for h, v in res.items():
        if len(v) >= 8: line.append(f"+{h}h n={len(v)} median {st.median(v):+.0f}% mean {st.mean(v):+.0f}% down>30%: {100*sum(x<-30 for x in v)/len(v):.0f}% up>30%: {100*sum(x>30 for x in v)/len(v):.0f}%")
    print(f"buy at {entry_h:>2}h after pool creation -> " + " | ".join(line))
tp = []
for name, cs, t0 in meme:
    hi = max(cs, key=lambda x: x[4]); tp.append((hi[0] - t0) / 3600)
tp.sort(); print("time of the highest close since creation (hours): median %.0f, p25 %.0f, p75 %.0f; peak in first 6h: %.0f%%, first 24h: %.0f%%" % (tp[len(tp)//2], tp[len(tp)//4], tp[3*len(tp)//4], 100*sum(x<=6 for x in tp)/len(tp), 100*sum(x<=24 for x in tp)/len(tp)))
