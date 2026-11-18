#!/usr/bin/env python3
"""Point-in-time backtester over 5m GeckoTerminal candles.

  python3 backtest.py --days 14 [--liq-gate none|now] [--skip-filters liq,vol/liq,flow]

Re-uses bot.check_features / bot.exit_levels / bot.exit_reason / bot.fill_buy / bot.proceeds_sell: no duplicated logic.

Rules that prevent look-ahead:
  * A decision at candle i uses candles[:i+1] only; candle i is usable from its close (ts+300).
  * Entry fills at the OPEN of candle i+1 (never on the signal candle's close).
  * Intrabar exits: stop/trail are assumed to trip BEFORE take-profit when one candle touches both; a stop that
    gaps through its level fills at the candle open (worse), not at the level.
  * Filters whose inputs do not exist historically (liquidity, txns, buy ratio) are NOT evaluated; they are listed as
    skipped in the output. `--liq-gate now` applies today's liquidity as a universe gate (look-ahead + survivorship).
"""
import argparse
import math
import random
import sqlite3
import time
from pathlib import Path
from collections import Counter, defaultdict

import bot

TF = 300            # candle length, seconds
EXIT_MODE = "wick"  # "wick": exits can trip on a candle's low/high (pessimistic). "close": exits evaluated only at candle closes
                    # with bot.exit_reason (what a 5-minute poller would see; optimistic about wicks). Applied to signal AND null model.
LAUNCHPAD_DEXES = {"pumpswap", "pump-fun", "meteora-dbc", "moonshot", "raydium-launchlab", "heaven", "boop-fun", "bags-fm"}


def is_launchpad(meta):
    """PROXY for 'memecoin': the pool is on a memecoin-launchpad DEX or the mint is a pump.fun vanity address (ends in 'pump').
    Imperfect, but it removes the tokenised stocks, wrapped large coins and DeFi tokens that GeckoTerminal listings also return."""
    return meta["dex"] in LAUNCHPAD_DEXES or (meta["base_mint"] or "").endswith("pump")


HIST_SKIP = ("liq", "vol/liq", "flow")   # no historical input available from OHLCV


# ---------------------------------------------------------------- features (point-in-time)

def candle_features(cs, i, created_ts, liq_now=None):
    """Features for a decision taken at the close of cs[i]. cs: list of (ts,o,h,l,c,v) ascending, gap-free not required.
    Only cs[:i+1] is read. Returns dict or None if there is not enough history (needs 24h)."""
    ts_i = cs[i][0]
    t = ts_i + TF                               # decision time = close of candle i
    c_now = cs[i][4]
    # last candle at or before t-1h / t-24h (must exist within one candle of the target, else no feature)
    def close_at(target):
        j = i
        while j >= 0 and cs[j][0] + TF > target:   # candle j closes at ts+TF; need close <= target
            j -= 1
        if j < 0 or target - (cs[j][0] + TF) > TF * 2:
            return None
        return cs[j][4]
    c1, c24 = close_at(t - 3600), close_at(t - 86400)
    if c1 is None or c24 is None or c1 <= 0 or c24 <= 0:
        return None
    vol24, j = 0.0, i
    while j >= 0 and cs[j][0] >= t - 86400:
        vol24 += cs[j][5]
        j -= 1
    return {"age_h": (t - created_ts) / 3600, "liq_usd": liq_now, "vol24_usd": vol24,
            "h1_pct": 100 * (c_now / c1 - 1), "h24_pct": 100 * (c_now / c24 - 1),
            "h1_buys": None, "h1_sells": None}


# ---------------------------------------------------------------- trade simulation on one pool

def simulate_trade(cs, i_entry, cfg, liq_for_costs, size=None):
    """Enter at open of cs[i_entry]; walk forward. Returns trade dict. Uses bot.exit_levels/exit_reason/costs."""
    e, c = cfg["exit"], cfg["costs"]
    size = size or cfg["position_usd"]
    px0 = cs[i_entry][1]
    fill, qty = bot.fill_buy(px0, size, liq_for_costs, c)
    pos = {"entry_px": px0, "peak_px": px0, "entry_liq": liq_for_costs, "opened_ts": cs[i_entry][0]}
    exit_px, reason, k_exit = None, None, None
    for k in range(i_entry, len(cs)):
        ts, o, h, l, cl, _ = cs[k]
        if EXIT_MODE == "close":                    # same function as the live loop, evaluated at each candle close
            pos["peak_px"] = max(pos["peak_px"], cl)
            why = bot.exit_reason(pos, cl, liq_for_costs, ts + TF, e)
            if why:
                exit_px, reason = cl, why
        else:
          lv = bot.exit_levels(pos, e)              # levels from the peak BEFORE this candle
          if l <= lv["stop"]:
              exit_px, reason = min(o, lv["stop"]), "stop"
          elif lv["trail"] is not None and l <= lv["trail"]:
              exit_px, reason = min(o, lv["trail"]), "trail"
          else:
              pos["peak_px"] = max(pos["peak_px"], h)
              lv = bot.exit_levels(pos, e)           # peak after this candle's high
              if lv["trail"] is not None and l <= lv["trail"] and h < lv["tp"]:
                  exit_px, reason = lv["trail"], "trail"   # high first, then pulled back (pessimistic ordering)
              elif h >= lv["tp"]:
                  exit_px, reason = max(o, lv["tp"]) if o >= lv["tp"] else lv["tp"], "tp"
              elif (ts + TF - pos["opened_ts"]) / 3600 >= e["max_hold_h"]:
                  exit_px, reason = cl, "time"
        if reason:
            k_exit = k
            break
    if reason is None:                              # data ended: mark to last close, flagged
        k_exit, exit_px, reason = len(cs) - 1, cs[-1][4], "data_end"
    proceeds = bot.proceeds_sell(exit_px, qty, liq_for_costs, c)
    return {"entry_ts": cs[i_entry][0], "exit_ts": cs[k_exit][0] + TF, "entry_px": px0, "exit_px": exit_px,
            "reason": reason, "pnl": proceeds - size, "size": size,
            "wick_only": bool(EXIT_MODE == "wick" and reason in ("stop", "trail") and cs[k_exit][4] > exit_px)}


# ---------------------------------------------------------------- portfolio replay

def load(db, days, now=None, max_liq_now=None):
    """Load pools+candles. Pools with liq_now above max_liq_now are excluded (blue-chips / bad data; rule fixed before results)."""
    now = now or db.execute("SELECT MAX(ts) FROM candles").fetchone()[0] + TF
    start = now - days * 86400
    pools = {}
    for p in db.execute("SELECT * FROM pools"):
        if max_liq_now and (p["liq_now"] or 0) > max_liq_now:
            continue
        rows = db.execute("SELECT ts,o,h,l,c,v FROM candles WHERE pool=? ORDER BY ts", (p["pool"],)).fetchall()
        if rows:
            pools[p["pool"]] = {"meta": dict(p), "cs": [tuple(r) for r in rows]}
    return pools, start, now


def run_backtest(pools, start, end, cfg, liq_gate="none", skip=HIST_SKIP, rng=None):
    """Chronological replay with the live risk limits (max_open, cash, daily loss, re-entry block).
    Returns (trades, funnel Counter, signals list). `signals` = every passing (pool, i) ignoring capacity."""
    f = cfg["filters"]
    idx = {p: {c[0]: n for n, c in enumerate(d["cs"])} for p, d in pools.items()}
    funnel, trades, signals = Counter(), [], []
    open_pos, last_close, day_pnl = {}, {}, defaultdict(float)
    cash = cfg["bankroll_usd"]
    t = int(start - start % TF)
    timeline = sorted({c[0] for d in pools.values() for c in d["cs"] if start <= c[0] + TF <= end})
    for ts in timeline:
        now = ts + TF
        # exits first (positions opened earlier; simulate_trade already resolves the whole path -> we pre-resolved)
        for p, (tr, exit_ts) in list(open_pos.items()):
            if exit_ts <= now:
                cash += tr["size"] + tr["pnl"]
                day_pnl[int(exit_ts // 86400)] += tr["pnl"]
                last_close[p] = exit_ts
                trades.append(tr)
                del open_pos[p]
        day = int(now // 86400)
        if day_pnl[day] <= -cfg["risk"]["daily_loss_limit_usd"]:
            funnel["blocked_daily_loss"] += 1
            continue
        cands = []
        for p, d in pools.items():
            n = idx[p].get(ts)
            if n is None:
                continue
            funnel["candle_evaluations"] += 1
            if liq_gate == "now" and (d["meta"]["liq_now"] or 0) < f["min_liq_usd"]:
                funnel["gate_liq_now"] += 1
                continue
            ft = candle_features(d["cs"], n, d["meta"]["created_ts"], d["meta"]["liq_now"] if liq_gate == "now" else None)
            if ft is None:
                funnel["insufficient_history"] += 1
                continue
            failed, na = bot.check_features(ft, f, skip=skip)
            if failed:
                for x in failed:
                    funnel["fail_" + x] += 1
                continue
            funnel["signals"] += 1
            signals.append((p, n))
            if p in open_pos or now - last_close.get(p, -1e18) < cfg["risk"]["reentry_block_h"] * 3600:
                funnel["blocked_open_or_reentry"] += 1
                continue
            cands.append((-ft["vol24_usd"], p, n))
        cands.sort()
        for _, p, n in cands:
            if len(open_pos) >= cfg["max_open"] or cash < cfg["position_usd"]:
                funnel["blocked_capacity"] += 1
                break
            d = pools[p]
            if n + 1 >= len(d["cs"]):
                funnel["no_next_candle"] += 1
                continue
            liq = max(d["meta"]["liq_now"] or 0, 1.0)
            tr = simulate_trade(d["cs"], n + 1, cfg, liq)
            tr.update(pool=p, name=d["meta"]["name"])
            cash -= tr["size"]
            open_pos[p] = (tr, tr["exit_ts"])
            funnel["entries"] += 1
    for p, (tr, exit_ts) in open_pos.items():       # still open at end of window: mark as-is, flagged
        tr["reason"] = tr["reason"] if exit_ts <= end else "open_at_end"
        trades.append(tr)
    return trades, funnel, signals


# ---------------------------------------------------------------- statistics

def stats(trades):
    pnl = [t["pnl"] for t in trades]
    n = len(pnl)
    wins, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x <= 0)
    pf = wins / losses if losses > 0 else (float("inf") if wins else 0.0)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for t in sorted(trades, key=lambda t: t["exit_ts"]):
        eq += t["pnl"]
        peak = max(peak, eq)
        mdd = max(mdd, peak - eq)
    return {"n": n, "net": sum(pnl), "mean": sum(pnl) / n if n else 0.0, "pf": pf,
            "win": 100 * sum(x > 0 for x in pnl) / n if n else 0.0, "max_dd": mdd}


def bootstrap_ci(xs, iters=2000, seed=1):
    if not xs:
        return (0.0, 0.0)
    r = random.Random(seed)
    m = sorted(sum(r.choice(xs) for _ in xs) / len(xs) for _ in range(iters))
    return m[int(0.025 * iters)], m[int(0.975 * iters)]


def signal_trades(pools, signals, cfg, liq_gate):
    """Unconstrained per-signal trades (no capacity limits), one per pool per 24h to avoid counting one run N times."""
    out, last = [], {}
    for p, n in signals:
        d = pools[p]
        ts = d["cs"][n][0]
        if ts - last.get(p, -1e18) < 86400 or n + 1 >= len(d["cs"]):
            continue
        last[p] = ts
        out.append(simulate_trade(d["cs"], n + 1, cfg, max(d["meta"]["liq_now"] or 0, 1.0)))
    return out


def null_model(pools, start, end, cfg, n_trades, runs=200, seed=7, liq_gate="none"):
    """Random entries drawn from every candle that satisfies ONLY the age gate (+ history available).
    Same exits and costs. Returns list of per-run mean PnL per trade."""
    f = cfg["filters"]
    elig = []
    for p, d in pools.items():
        if liq_gate == "now" and (d["meta"]["liq_now"] or 0) < f["min_liq_usd"]:
            continue
        for n in range(len(d["cs"]) - 1):
            ts = d["cs"][n][0]
            if not start <= ts + TF <= end:
                continue
            age = (ts + TF - d["meta"]["created_ts"]) / 3600
            if f["min_age_h"] <= age <= f["max_age_h"] and n >= 288:
                elig.append((p, n))
    if not elig or n_trades < 1:
        return [], len(elig)
    r = random.Random(seed)
    means = []
    for _ in range(runs):
        pnls = []
        for p, n in r.sample(elig, min(n_trades, len(elig))):
            d = pools[p]
            pnls.append(simulate_trade(d["cs"], n + 1, cfg, max(d["meta"]["liq_now"] or 0, 1.0))["pnl"])
        means.append(sum(pnls) / len(pnls))
    return means, len(elig)


def report(pools, trades, funnel, signals, cfg, args, start, end):
    print("=" * 78)
    print(f"BACKTEST window {time.strftime('%Y-%m-%d', time.gmtime(start))} -> {time.strftime('%Y-%m-%d', time.gmtime(end))} "
          f"({args.days} d) | pools with candles: {len(pools)} | liq gate: {args.liq_gate}")
    dead = sum(1 for d in pools.values() if (d["meta"]["liq_now"] or 0) < cfg["filters"]["min_liq_usd"])
    print("BIAS: universe = pools listed by GeckoTerminal today (survivorship). "
          f"{dead}/{len(pools)} pools now have liq < ${cfg['filters']['min_liq_usd']:,.0f}.")
    print(f"NOT EVALUATED historically (no data): {', '.join(args.skip)}. Costs use TODAY's liquidity (look-ahead proxy).")
    print("Execution: entry at next-candle open; stop-before-TP in ambiguous candles; 5m granularity (live polls at 60s).")
    print("-" * 78)
    s = stats(trades)
    print(f"Portfolio replay (live risk limits): trades={s['n']} net=${s['net']:+.3f} mean=${s['mean']:+.4f}/trade "
          f"PF={s['pf']:.2f} win={s['win']:.0f}% maxDD=${s['max_dd']:.3f}")
    print("Exit reasons:", dict(Counter(t["reason"] for t in trades)))
    print("Funnel:", dict(sorted(funnel.items())))
    sig = signal_trades(pools, signals, cfg, args.liq_gate)
    ss = stats(sig)
    lo, hi = bootstrap_ci([t["pnl"] for t in sig])
    print(f"Unconstrained signal trades (1 per pool per 24h): n={ss['n']} mean=${ss['mean']:+.4f} "
          f"95% bootstrap CI [{lo:+.4f}, {hi:+.4f}] PF={ss['pf']:.2f} win={ss['win']:.0f}%")
    means, n_elig = null_model(pools, start, end, cfg, max(ss["n"], 1), liq_gate=args.liq_gate)
    if means:
        means.sort()
        pct = 100 * sum(m < ss["mean"] for m in means) / len(means)
        print(f"Null model (random entries, age gate only; {n_elig} eligible candles; same exits/costs): "
              f"mean/trade median=${means[len(means)//2]:+.4f} [5%..95%: {means[int(.05*len(means))]:+.4f}, "
              f"{means[int(.95*len(means))]:+.4f}]; signal mean beats {pct:.0f}% of null runs")
    print("=" * 78)


# ---------------------------------------------------------------- suite (all variants -> table + JSON for the dashboard)

def _variant(pools, start, end, cfg, liq_gate, mode):
    global EXIT_MODE
    EXIT_MODE = mode
    trades, funnel, signals = run_backtest(pools, start, end, cfg, liq_gate, HIST_SKIP)
    s = stats(trades)
    sig = signal_trades(pools, signals, cfg, liq_gate)
    ss = stats(sig)
    lo, hi = bootstrap_ci([t["pnl"] for t in sig])
    means, n_elig = null_model(pools, start, end, cfg, max(ss["n"], 1), liq_gate=liq_gate)
    means.sort()
    nm = means[len(means) // 2] if means else 0.0
    beat = 100 * sum(m < ss["mean"] for m in means) / len(means) if means else 0.0
    stops = [t for t in trades if t["reason"] in ("stop", "trail")]
    wick = 100 * sum(t["wick_only"] for t in stops) / len(stops) if stops else 0.0
    return {"gate": liq_gate, "mode": mode, "port": s, "sig": ss, "ci": (lo, hi), "null_median": nm, "beat_pct": beat,
            "exits": dict(Counter(t["reason"] for t in trades)), "funnel": dict(funnel), "wick_share": wick, "n_elig": n_elig}


def suite(db, days, cfg, json_path=None):
    global EXIT_MODE
    saved = EXIT_MODE
    pools, start, end = load(db, days, max_liq_now=cfg.get("universe", {}).get("max_liq_now_usd"))
    res = [_variant(pools, start, end, cfg, g, m) for m, g in (("wick", "none"), ("wick", "now"), ("close", "none"), ("close", "now"))]
    meme = {k: v for k, v in pools.items() if is_launchpad(v["meta"])}
    mres = [_variant(meme, start, end, cfg, "none", m) for m in ("wick", "close")]
    EXIT_MODE = saved
    print(f"{'exits':<6} {'liq gate':<9} {'trades':>6} {'net $':>8} {'PF':>5} {'win%':>5} {'maxDD':>6} | {'signal mean/trade [95% CI]':<34} {'null median':>11} {'beats null':>10}")
    for r in res:
        p, ci = r["port"], r["ci"]
        print(f"{r['mode']:<6} {r['gate']:<9} {p['n']:>6} {p['net']:>+8.2f} {p['pf']:>5.2f} {p['win']:>5.0f} {p['max_dd']:>6.2f} | "
              f"{r['sig']['mean']:>+7.4f} [{ci[0]:+.4f},{ci[1]:+.4f}] n={r['sig']['n']:<4} {r['null_median']:>+11.4f} {r['beat_pct']:>9.0f}%")
    print(f"MEMECOIN PROXY ONLY ({len(meme)} of {len(pools)} pools are launchpad-style):")
    for r in mres:
        pp, ci = r["port"], r["ci"]
        print(f"{r['mode']:<6} {r['gate']:<9} {pp['n']:>6} {pp['net']:>+8.2f} {pp['pf']:>5.2f} {pp['win']:>5.0f} {pp['max_dd']:>6.2f} | "
              f"{r['sig']['mean']:>+7.4f} [{ci[0]:+.4f},{ci[1]:+.4f}] n={r['sig']['n']:<4} {r['null_median']:>+11.4f} {r['beat_pct']:>9.0f}%")
    print("Share of stop/trail exits that were wick-only (close recovered above the level):", f"{res[0]['wick_share']:.0f}%")
    if json_path:
        import json
        h, c = res[0], res[2]
        d = lambda r: f"{r['port']['n']} trades, net {r['port']['net']:+.2f} USD, PF {r['port']['pf']:.2f}, win {r['port']['win']:.0f}%, max drawdown {r['port']['max_dd']:.2f} USD"
        m0, m1 = mres
        rows = [
            {"key": "caveat", "label": "Universe caveat", "value": f"only {len(meme)} of {len(pools)} pools are memecoin launches",
             "note": "The first test ran on every GeckoTerminal pool in range. Most are tokenised stocks (NVDA, QQQ), wrapped large coins (CRO, OSMO, LUNC, IOTA) and DeFi tokens (JUP, RAY). The memecoin test keeps only pools on memecoin launchpads or with a pump.fun address. The proxy is imperfect."},
            {"key": "meme", "label": "Memecoin-only test (launchpad-style pools)", "value": f"{m0['port']['net']:+.2f} to {m1['port']['net']:+.2f} USD",
             "note": f"Pessimistic and optimistic exits. Signal mean {m0['sig']['mean']:+.3f} USD per trade, 95% CI {m0['ci'][0]:+.3f} to {m0['ci'][1]:+.3f}, but only {m0['sig']['n']} signal trades from about {len(meme)} pools in one 14-day market. Thin evidence: it points the same way, it does not settle it."},
            {"key": "all", "label": "All pools in range (not a clean memecoin test)", "value": f"{res[0]['port']['net']:+.2f} USD", "note": d(res[0]) + f". Signal mean {res[0]['sig']['mean']:+.3f} vs random {res[0]['null_median']:+.3f} USD per trade; beat {res[0]['beat_pct']:.0f}% of random runs."},
            {"key": "close", "label": "All pools, optimistic bracket (exits at 5-minute closes only)", "value": f"{res[2]['port']['net']:+.2f} USD", "note": d(res[2]) + f"; signal beat {res[2]['beat_pct']:.0f}% of random runs."},
            {"key": "exits", "label": "Exit mix (all pools)", "value": ", ".join(f"{k} {v}" for k, v in sorted(res[0]["exits"].items())), "note": f"{res[0]['wick_share']:.0f}% of stop and trailing exits were triggered by a wick whose candle closed back above the level, so the exit assumption moves the result."},
            {"key": "reading", "label": "Reading", "value": "Not a valid memecoin verdict yet",
             "note": "The direction is negative everywhere, but the universe was contaminated, the memecoin sample is small, and real memecoin costs and the sell side are not modelled. Nothing here is tuned. The calibrated test (task 3) must start from a proper memecoin universe."},
            {"key": "skipped", "label": "Not tested here", "value": "liquidity, volume/liquidity, buy pressure", "note": "No historical data for these, so the backtest runs without them."},
        ]
        Path(json_path).parent.mkdir(parents=True, exist_ok=True)
        Path(json_path).write_text(json.dumps(rows))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=14)
    ap.add_argument("--liq-gate", choices=["none", "now"], default="none")
    ap.add_argument("--skip-filters", default=",".join(HIST_SKIP))
    ap.add_argument("--db", default=None)
    ap.add_argument("--exits", choices=["wick", "close"], default="wick")
    ap.add_argument("--suite", action="store_true", help="run wick/close x liq-gate none/now, print table")
    ap.add_argument("--json", default=None, help="with --suite: write dashboard rows here")
    a = ap.parse_args()
    a.skip = tuple(x for x in a.skip_filters.split(",") if x)
    import data
    db = data.connect(a.db) if a.db else data.connect()
    cfg = bot.load_cfg()
    EXIT_MODE = a.exits
    if a.suite:
        suite(db, a.days, cfg, a.json)
        raise SystemExit(0)
    pools, start, end = load(db, a.days, max_liq_now=cfg.get("universe", {}).get("max_liq_now_usd"))
    trades, funnel, signals = run_backtest(pools, start, end, cfg, a.liq_gate, a.skip)
    report(pools, trades, funnel, signals, cfg, a, start, end)
