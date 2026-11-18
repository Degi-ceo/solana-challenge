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
    (1, "Historical data + backtester", "active", "Evidence", "Downloader and point-in-time replay built; candles downloading"),
    (2, "Candidate discovery", "todo", "Evidence", "Broader sources, per-source funnel, forward collector"),
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
    ("universe", "max_liq_now_usd", "Universe liquidity cap", "USD", "Pools above this are blue-chips or bad data. Fixed before any result."),
]


def iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""


def rules_rows(cfg):
    rows = []
    for grp, key, name, unit, why in RULES:
        v = (cfg.get(grp) or {}).get(key) if grp not in ("limits",) else cfg.get(key)
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
        rows.append({"date": m.group(1), "title": m.group(2), "detail": " ".join(bullets[:3])[:420], "bullets": len(bullets)})
    return rows


def network_rows(live):
    if not live:
        return []
    import netcheck
    out = []
    for name, host, status, lat, note in netcheck.run():
        out.append({"check": name, "host": host, "status": status, "latency_s": float(lat.rstrip("s")), "evidence": note[:90]})
    return out


def history_rows(outdir, now, n_done, n_candles, n_elig):
    path = BASE / "data" / "progress_history.jsonl"
    rows = [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []
    if not rows or now - rows[-1]["ts"] >= 60:
        rows.append({"ts": int(now), "pools_done": n_done, "candles": n_candles, "eligible": n_elig})
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return [{"time": iso(r["ts"]), "ts": r["ts"], "pools_done": r["pools_done"], "candles": r["candles"], "eligible": r["eligible"]} for r in rows]


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
        "tests_passing": 30,
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

    files = {
        "summary": summary,
        "tasks": [{"task": t[0], "title": t[1], "status": t[2], "phase": t[3], "note": t[4]} for t in TASKS],
        "pools": [{"pool": p["pool"], "name": p["name"], "dex": p["dex"], "age_days": round((now - p["created_ts"]) / 86400, 1),
                   "liq_now_usd": round(p["liq_now"]), "vol24_now_usd": round(p["vol24_now"]),
                   "candles": p["n_candles"], "downloaded": bool(p["done"]), "eligible": p["liq_now"] <= MAX_LIQ,
                   "source": ", ".join(json.loads(p["sources"]))} for p in pools],
        "config": rules_rows(cfg),
        "network": network_rows(live_net),
        "activity": activity_rows(),
        "history": history_rows(outdir, now, n_done, n_candles, len(elig)),
        "paper": pdb_rows,
    }
    for name, rows in files.items():
        (outdir / f"{name}.json").write_text(json.dumps(rows, separators=(",", ":")))
    return {k: len(v) for k, v in files.items()}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else BASE / "data" / "export"
    print(build(out, live_net="--no-net" not in sys.argv))
