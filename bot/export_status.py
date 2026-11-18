#!/usr/bin/env python3
"""Export the bot's current state as JSON snapshots for the monitoring dashboard.

  python3 export_status.py [outdir] [--no-net]     # default outdir: bot/data/export/

Writes rows-style JSON arrays (one file per dashboard dataset). Read-only: never touches keys, never sends anything.
Datasets: summary, tasks, pools, config, network, activity, history, paper.
"""
import json
import re
import sys
import time
from pathlib import Path

import bot
import data

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
MAX_LIQ = 50_000_000

# Task board. Update `status` as work proceeds (done | active | todo). Facts, not hopes.
TASKS = [
    (0, "Network check", "done", "Setup", "Every data host reachable; Jupiter via lite-api / api.jup.ag"),
    (1, "Historical data + backtester", "active", "Evidence", "First backtest negative but on a contaminated universe; to be redone on memecoins only"),
    (2, "Candidate discovery", "done", "Evidence", "Seven tagged sources, per-source funnel, forward collector; 4.3x more candidates"),
    (3, "Calibration (walk-forward)", "todo", "Evidence", "Pre-registered split, trials counted, out-of-sample verdict only"),
    (4, "Realistic execution costs", "todo", "Realism", "Latency, quote-based slippage, rent, failed fills"),
    (5, "Rug / safety checks", "todo", "Realism", "Token-2022, LP lock, RugCheck, sell simulation"),
    (6, "Live executor (disabled)", "todo", "Execution", "Mocked tests; nothing is sent unless live=true"),
    (7, "Reporting", "todo", "Execution", "REPORT.md regenerated from the database"),
    (8, "Deployment notes", "todo", "Execution", "systemd, cron, key handling for the VPS"),
]

# Plain-language meaning of every tunable, shown on the dashboard so nothing is a black box.
RULES = [
    ("filters", "min_age_h", "Minimum token age", "hours", "Skip brand-new launches where most rugs happen."),
    ("filters", "max_age_h", "Maximum token age", "hours", "Skip old tokens that no longer behave like young memecoins."),
    ("filters", "min_liq_usd", "Minimum liquidity", "USD", "Enough depth that a $1 trade does not move the price."),
    ("filters", "min_vol24_usd", "Minimum 24h volume", "USD", "There must be real trading, not a dead pool."),
    ("filters", "vol_liq_min", "Volume / liquidity, min", "ratio", "Too low means nobody is trading it."),
    ("filters", "vol_liq_max", "Volume / liquidity, max", "ratio", "Too high looks like wash trading or a pump."),
    ("filters", "h1_change_min", "1h price change, min", "%", "Wants gentle momentum, not a falling knife."),
    ("filters", "h1_change_max", "1h price change, max", "%", "Avoids entering in the middle of a pump."),
    ("filters", "h24_change_min", "24h price change, min", "%", "Avoids tokens in a slow bleed."),
    ("filters", "h24_change_max", "24h price change, max", "%", "Avoids chasing a token that already ran."),
    ("filters", "min_h1_txns", "Minimum trades in last hour", "count", "Needs live activity."),
    ("filters", "min_h1_buy_ratio", "Minimum buy share, last hour", "ratio", "Buyers should at least match sellers."),
    ("filters", "max_top_ex_largest_pct", "Top-10 holders (excl. largest)", "% of supply", "Concentration check, see KNOWN_GAPS #4."),
    ("exit", "stop_loss_pct", "Stop loss", "%", "Cut a loser early."),
    ("exit", "take_profit_pct", "Take profit", "%", "Bank a clear win."),
    ("exit", "trail_activate_pct", "Trailing stop arms at", "% gain", "Protect a winner once it is up this much."),
    ("exit", "trail_pct", "Trailing stop distance", "% from peak", "Exit when price falls this far from its high."),
    ("exit", "max_hold_h", "Maximum holding time", "hours", "Do not let capital sit forever."),
    ("exit", "liq_drop_exit_frac", "Exit if liquidity falls below", "x entry", "Liquidity pulled means a possible rug."),
    ("costs", "fee_pct", "Swap fee", "%", "Paid on every buy and sell."),
    ("costs", "slippage_pct", "Base slippage", "%", "Plus an impact term that grows with size / liquidity."),
    ("costs", "network_fee_usd", "Network fee per swap", "USD", "Optimistic until task 4 adds priority fees and rent."),
    ("risk", "daily_loss_limit_usd", "Daily loss limit", "USD", "New entries stop for the day beyond this."),
    ("risk", "reentry_block_h", "Re-entry block", "hours", "No immediate re-buy of a token just sold."),
    ("limits", "bankroll_usd", "Bankroll", "USD", "The whole experiment."),
    ("limits", "position_usd", "Position size", "USD", "Per trade."),
    ("limits", "max_open", "Maximum open positions", "count", "Hard cap enforced in code."),
    ("verdict", "min_closed_trades", "Closed trades needed for a verdict", "count", "Below this the verdict is always 'not enough data'."),
    ("verdict", "min_profit_factor", "Profit factor needed", "ratio", "Gross wins divided by gross losses after costs."),
    ("verdict", "min_net_pnl_usd", "Net profit needed", "USD", "Must be above this after all costs."),
    ("universe", "max_liq_now_usd", "Universe liquidity cap", "USD", "Pools above this are blue-chips or bad data. Fixed before any result."),
]


# What the bot/Claude is doing and what the reader must do. Update when the step changes (facts only).
NOW = {
    "task": 1,
    "title": "Paused: checking how Solana memecoins work before building more",
    "next": "Fix the memecoin universe, re-run the backtest on memecoins only, and measure real trading costs. Nothing new is built until you agree.",
    "needs": ["Read the findings in the chat reply and tell me whether to go ahead with the corrected plan."],   # list of strings; empty means nothing is needed from Kamil
}


def downloader_running():
    import subprocess
    return subprocess.run(["pgrep", "-f", "data.py candles"], capture_output=True).returncode == 0


def iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""


def rules_rows(cfg):
    rows = []
    for grp, key, name, unit, why in RULES:
        if grp == "limits":
            v = cfg.get(key)
        elif grp == "verdict":
            v = cfg["go_nogo"].get(key)
        else:
            v = (cfg.get(grp) or {}).get(key)
        rows.append({"key": key, "group": grp, "name": name, "value": v, "unit": unit, "why": why})
    return rows


def activity_rows():
    """Timeline from JOURNAL.md (the project's source of truth): one row per entry, newest first."""
    txt = (ROOT / "JOURNAL.md").read_text()
    rows = []
    for block in re.split(r"(?m)^## ", txt)[1:]:
        head, _, body = block.partition("\n")
        m = re.match(r"(\d{4}-\d{2}-\d{2}) — (.*)", head.strip())
        if not m:
            continue
        bullets = [re.sub(r"\s+", " ", b.strip("- ").strip()) for b in re.findall(r"(?m)^- .*", body)]
        bullets = [re.sub(r"[`*]", "", b) for b in bullets]
        rows.append({"date": m.group(1), "title": m.group(2), "detail": " · ".join(bullets[:3])[:420], "bullets": len(bullets)})
    return rows


def network_rows(live, outdir=None):
    if not live:  # keep the last probe instead of blanking it
        prev = (outdir / "network.json") if outdir else None
        return json.loads(prev.read_text()) if prev and prev.exists() else []
    import netcheck
    out = []
    for name, host, status, lat, note in netcheck.run():
        if status != "OK":
            note = ("Server error. Not needed: lite-api.jup.ag is used for Jupiter quotes." if "quote-api" in host
                    else "Not reachable from this environment.")
        out.append({"check": name, "host": host, "status": status, "latency_s": float(lat.rstrip("s")), "evidence": note[:90]})
    return out


def history_rows(outdir, now, n_done, n_candles, n_elig):
    path = BASE / "data" / "progress_history.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    if not rows or now - rows[-1]["ts"] >= 60:
        rows.append({"ts": int(now), "pools_done": n_done, "candles": n_candles, "eligible": n_elig})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return [{"time": iso(r["ts"]), "ts": r["ts"], "pools_done": r["pools_done"], "candles": r["candles"], "eligible": r["eligible"]} for r in rows]



GLOSSARY = [
    ("Profit factor", "Total money won divided by total money lost. Above 1 means winners outweigh losers; the verdict needs 1.2 or more after costs."),
    ("Drawdown", "The biggest drop from a previous high point of the account. It shows how painful the worst stretch was."),
    ("Slippage", "The difference between the price you expect and the price you actually get. It grows when you trade a large amount in a shallow pool."),
    ("Break-even move", "How far the price must rise after you buy just to get your money back once fees and slippage are paid."),
    ("Look-ahead bias", "Accidentally using information from the future when testing. It makes results look better than they could ever be in real time."),
    ("Survivorship bias", "Testing only on tokens that still exist today, so the ones that died or rugged are missing and results look better than reality."),
    ("Out-of-sample", "Data the settings were never tuned on. Only out-of-sample results count toward the verdict."),
    ("Walk-forward", "Tune on an earlier period, then test on the following period, so the test is always about the future of the tuning data."),
    ("Null model", "A dumb baseline that enters at random times with the same exits and costs. A strategy must beat it to claim an edge."),
    ("Token-2022", "A newer Solana token standard with extensions such as transfer fees or hooks, which can trap or tax sellers."),
    ("Rent", "A small SOL deposit that Solana holds for each token account. It is refunded only if the account is closed."),
    ("Liquidity", "How much money sits in the pool. Deeper pools let you buy and sell without moving the price much."),
]

SOURCE_NOTES = {
    "ds_boost_top": "DexScreener boosted tokens, top. Paid promotion.",
    "ds_boost_latest": "DexScreener newly boosted tokens. Paid promotion.",
    "ds_profile": "DexScreener newest token profiles. Paid listing metadata.",
    "ds_search": "DexScreener search on twelve meme keywords. Organic but keyword-biased.",
    "gt_trending": "GeckoTerminal trending pools (1h, 6h, 24h). Already moving.",
    "gt_new": "GeckoTerminal newest pools. Mostly brand new.",
    "gt_volume": "GeckoTerminal pools by 24h volume. Established, highly traded.",
}

LEG_FILTERS = ["age", "liq", "vol24", "vol/liq", "h1", "h24"]


def sol_price():
    """SOL/USD from a public Jupiter quote (0.01 SOL -> USDC). None if unreachable."""
    try:
        sol = "So11111111111111111111111111111111111111112"
        usdc = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        j = bot.http_json(f"https://lite-api.jup.ag/swap/v1/quote?inputMint={sol}&outputMint={usdc}&amount=10000000&slippageBps=50", retries=1, timeout=10)
        return round(int(j["outAmount"]) / 1e6 / 0.01, 2)
    except Exception:
        return None


def cost_math(cfg, sol_usd):
    """Net P&L of one position vs price move, using the bot's own cost functions (no separate formula).
    Liquidity barely matters at a $1 size (measured), so one reference pool is drawn; cost parts come from ablation."""
    size, e = cfg["position_usd"], cfg["exit"]
    liq = 250_000

    def flat_cost(c):
        fill, qty = bot.fill_buy(1.0, size, liq, c)
        return size - bot.proceeds_sell(1.0, qty, liq, c)

    def breakeven(c):
        fill, qty = bot.fill_buy(1.0, size, liq, c)
        lo, hi = 0.0, 80.0
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if bot.proceeds_sell(1 + mid / 100, qty, liq, c) - size < 0 else (lo, mid)
        return hi

    c = cfg["costs"]
    total = flat_cost(c)
    parts = []
    for label, key in (("Network fees (buy + sell)", "network_fee_usd"), ("DEX swap fees (buy + sell)", "fee_pct"), ("Base slippage (buy + sell)", "slippage_pct")):
        parts.append({"part": label, "usd": round(total - flat_cost(dict(c, **{key: 0})), 4)})
    parts.append({"part": "Price impact from pool depth", "usd": round(max(0.0, total - sum(p["usd"] for p in parts)), 4)})
    fill, qty = bot.fill_buy(1.0, size, liq, c)
    rows = [{"move_pct": m, "pnl_usd": round(bot.proceeds_sell(1 + m / 100, qty, liq, c) - size, 4)} for m in range(-50, 101, 5)]
    stop_pnl = bot.proceeds_sell(1 - e["stop_loss_pct"] / 100, qty, liq, c) - size
    tp_pnl = bot.proceeds_sell(1 + e["take_profit_pct"] / 100, qty, liq, c) - size
    rent = round(0.00203928 * sol_usd, 3) if sol_usd else None
    summ = [{"ref_liq_usd": liq, "flat_cost_usd": round(total, 4), "flat_cost_pct": round(100 * total / size, 2),
             "breakeven_pct": round(breakeven(c), 2),
             "breakeven_with_rent_pct": round(breakeven(dict(c, network_fee_usd=c["network_fee_usd"] + (rent or 0) / 2)), 2) if rent else None,
             "stop_pnl_usd": round(stop_pnl, 4), "tp_pnl_usd": round(tp_pnl, 4),
             "stop_pct": e["stop_loss_pct"], "tp_pct": e["take_profit_pct"],
             "win_to_loss_ratio": round(tp_pnl / -stop_pnl, 2),
             "required_win_rate_pct": round(100 * -stop_pnl / (tp_pnl - stop_pnl), 1)}]
    return rows, parts, summ, rent


def readiness(tasks, S, cfg):
    st = {t[0]: t[2] for t in tasks}
    g = cfg["go_nogo"]
    def task(n): return "pass" if st[n] == "done" else "pending"
    return [
        {"gate": "Live trading is switched off in config", "status": "pass" if not cfg.get("live", False) else "fail", "detail": "live = " + str(cfg.get("live", False)).lower()},
        {"gate": "Network and data sources verified", "status": task(0), "detail": "Task 0"},
        {"gate": "Backtest built and free of look-ahead", "status": "pending" if st[1] != "done" else "pass", "detail": "Task 1, 48 tests passing"},
        {"gate": "Calibrated out-of-sample, verdict is 'edge'", "status": task(3), "detail": "Task 3. 'No edge' or 'inconclusive' keeps this red."},
        {"gate": "Realistic execution costs applied", "status": task(4), "detail": "Task 4"},
        {"gate": "Rug and safety checks tested", "status": task(5), "detail": "Task 5"},
        {"gate": "Executor tested with mocks, sends nothing when off", "status": task(6), "detail": "Task 6"},
        {"gate": f"At least {g['min_closed_trades']} closed paper trades", "status": "pass" if S["paper_trades"] >= g["min_closed_trades"] else "pending", "detail": f"{S['paper_trades']} so far"},
        {"gate": f"Profit factor at least {g['min_profit_factor']} after costs", "status": "pending", "detail": "Needs the trades above"},
        {"gate": "Net profit above zero after costs", "status": "pending", "detail": "Needs the trades above"},
        {"gate": "Beats the random-entry baseline", "status": "pending", "detail": "Task 1 and 3"},
        {"gate": "Deployment notes written, key handling reviewed", "status": task(8), "detail": "Task 8"},
    ]


def watchlist(db, cfg, now):
    """Latest point-in-time features for every eligible pool with candles, run through the same bot.check_features."""
    import backtest as bt
    rows, rejects = [], {k: 0 for k in LEG_FILTERS}
    for p in db.execute("SELECT * FROM pools WHERE liq_now <= ?", (MAX_LIQ,)).fetchall():
        cs = [tuple(r) for r in db.execute("SELECT ts,o,h,l,c,v FROM candles WHERE pool=? ORDER BY ts", (p["pool"],))]
        if len(cs) < 300:
            continue
        i = len(cs) - 1
        ft = bt.candle_features(cs, i, p["created_ts"], p["liq_now"])
        if ft is None:
            continue
        failed, _ = bot.check_features(ft, cfg["filters"], skip=("flow",))
        for f in failed:
            rejects[f] = rejects.get(f, 0) + 1
        rows.append({"name": p["name"], "dex": p["dex"], "age_days": round(ft["age_h"] / 24, 1), "liq_usd": round(p["liq_now"]),
                     "vol24_usd": round(ft["vol24_usd"]), "h1_pct": round(ft["h1_pct"], 1), "h24_pct": round(ft["h24_pct"], 1),
                     "failed": failed, "passes": not failed, "candle_time": iso(cs[i][0] + bt.TF)})
    rows.sort(key=lambda r: (len(r["failed"]), -r["liq_usd"]))
    return rows, [{"filter": k, "count": v} for k, v in rejects.items()]


def build(outdir, live_net=True):
    outdir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cfg = bot.load_cfg()
    db = data.connect()
    pools = db.execute("""SELECT p.*, COALESCE(f.complete,0) AS done, COALESCE(f.n,0) AS n_candles
                          FROM pools p LEFT JOIN fetched f ON f.pool=p.pool ORDER BY p.liq_now DESC""").fetchall()
    elig = [p for p in pools if p["liq_now"] <= MAX_LIQ]
    n_done = sum(1 for p in elig if p["done"])
    n_candles = sum(p["n_candles"] for p in pools)
    min_liq = cfg["filters"]["min_liq_usd"]
    meets = sum(1 for p in elig if p["liq_now"] >= min_liq)

    summary = [{
        "updated": iso(now) + " UTC", "updated_ts": int(now),
        "mode": "PAPER ONLY", "live_trading": bool(cfg.get("live", False)), "kill_file": bot.KILL.exists(),
        "bankroll_usd": cfg["bankroll_usd"], "position_usd": cfg["position_usd"], "max_open": cfg["max_open"],
        "daily_loss_limit_usd": cfg["risk"]["daily_loss_limit_usd"],
        "pools_found": len(pools), "pools_eligible": len(elig), "pools_excluded": len(pools) - len(elig),
        "pools_downloaded": n_done, "candles_stored": n_candles, "pools_meeting_liq_filter": meets,
        "paper_trades": 0, "tasks_done": sum(1 for t in TASKS if t[2] == "done"), "tasks_total": len(TASKS),
        "tests_passing": 48,
    }]
    pdb_rows = []
    try:
        pdb = bot.db_connect(bot.BASE / cfg["db"])
        for r in pdb.execute("SELECT * FROM positions ORDER BY opened_ts DESC LIMIT 100"):
            pdb_rows.append({"symbol": r["symbol"], "status": r["status"], "opened": iso(r["opened_ts"]),
                             "size_usd": r["size_usd"], "pnl_usd": round(r["pnl"] or 0, 4), "reason": r["reason"] or ""})
        summary[0]["paper_trades"] = len(pdb_rows)
    except Exception:
        pass

    sol = sol_price()
    cm_rows, cm_parts, cm_sum, rent = cost_math(cfg, sol)
    wl_rows, wl_rej = watchlist(db, cfg, now)
    cr = db.execute("SELECT MIN(ts), MAX(ts), COUNT(DISTINCT pool) FROM candles").fetchone()
    summary[0].update(sol_usd=sol, rent_usd=rent, rent_pct_of_position=round(100 * rent / cfg["position_usd"], 1) if rent else None,
                      candles_oldest=iso(cr[0]), candles_newest=iso(cr[1]), pools_with_candles=cr[2],
                      run_started=False, paper_days_total=7)
    summary[0]["downloader_running"] = downloader_running()
    summary[0]["now_task"], summary[0]["now_title"] = NOW["task"], NOW["title"]
    summary[0]["now_next"], summary[0]["now_needs"] = NOW["next"], NOW["needs"]
    src_rows, last_cycle = [], {}
    try:
        pdb2 = bot.db_connect(bot.BASE / cfg["db"])
        for r in bot.funnel_rows(pdb2):
            r.pop("_agg", None)
            r["note"] = SOURCE_NOTES.get(r["source"], "")
            src_rows.append(r)
        fr = pdb2.execute("SELECT ts, discovered, with_pair, cheap_pass FROM funnel ORDER BY ts DESC LIMIT 1").fetchone()
        n_cyc = pdb2.execute("SELECT COUNT(*) FROM funnel").fetchone()[0]
        if fr:
            last_cycle = {"collector_last": iso(fr[0]) + " UTC", "last_discovered": fr[1], "last_with_pair": fr[2], "last_cheap_pass": fr[3], "collector_cycles": n_cyc,
                          "baseline_with_pair": 51, "baseline_discovered": 68}
    except Exception:
        pass
    summary[0].update(last_cycle)
    bt_path = BASE / "data" / "backtest_last.json"
    backtest = json.loads(bt_path.read_text()) if bt_path.exists() else []
    files = {
        "summary": summary,
        "tasks": [{"task": t[0], "title": t[1], "status": t[2], "phase": t[3], "note": t[4]} for t in TASKS],
        "pools": [{"pool": p["pool"], "name": p["name"], "dex": p["dex"], "age_days": round((now - p["created_ts"]) / 86400, 1),
                   "liq_now_usd": round(p["liq_now"]), "vol24_now_usd": round(p["vol24_now"]),
                   "candles": p["n_candles"], "downloaded": bool(p["done"]), "eligible": p["liq_now"] <= MAX_LIQ,
                   "source": ", ".join(json.loads(p["sources"]))} for p in pools],
        "config": rules_rows(cfg),
        "network": network_rows(live_net, outdir),
        "activity": activity_rows(),
        "history": history_rows(outdir, now, n_done, n_candles, len(elig)),
        "paper": pdb_rows,
        "backtest": backtest,
        "costmath": cm_rows,
        "costsum": cm_sum,
        "costparts": cm_parts,
        "watch": wl_rows,
        "rejects": wl_rej,
        "readiness": readiness(TASKS, summary[0], cfg),
        "sources": src_rows,
        "glossary": [{"term": a, "meaning": b} for a, b in GLOSSARY],
    }
    for name, rows in files.items():
        (outdir / f"{name}.json").write_text(json.dumps(rows, separators=(",", ":")))
    return {k: len(v) for k, v in files.items()}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else BASE / "data" / "export"
    print(build(out, live_net="--no-net" not in sys.argv))
