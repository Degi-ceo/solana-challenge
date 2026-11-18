#!/usr/bin/env python3
"""Export the bot's current state as small JSON snapshots for the monitoring dashboard.

  python3 export_status.py [outdir]     # default: bot/data/export/

Writes rows-style JSON arrays (one file per dashboard dataset). Read-only: never touches keys, never sends anything.
"""
import json
import sys
import time
from pathlib import Path

import bot
import data

BASE = Path(__file__).resolve().parent

# Task board. Update `status` here as work proceeds (done | active | next | todo). Statements are facts, not hopes.
TASKS = [
    (0, "Network check", "done", "All data hosts reachable; Jupiter via lite-api / api.jup.ag"),
    (1, "Historical data + backtester", "active", "Downloader + point-in-time replay built; candles downloading"),
    (2, "Candidate discovery", "todo", "Broader sources, per-source funnel, forward collector"),
    (3, "Calibration (walk-forward)", "todo", "Pre-registered split, trials counted, OOS verdict only"),
    (4, "Realistic execution costs", "todo", "Latency, quote-based slippage, rent, failed fills"),
    (5, "Rug / safety checks", "todo", "Token-2022, LP lock, RugCheck, sell simulation"),
    (6, "Live executor (disabled)", "todo", "Mocked tests; nothing sent unless live=true"),
    (7, "Reporting", "todo", "REPORT.md from the DB"),
    (8, "Deployment notes", "todo", "systemd, cron, key handling"),
]


def iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""


def build(outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cfg = bot.load_cfg()
    db = data.connect()
    pools = db.execute("""SELECT p.*, COALESCE(f.complete,0) AS done, COALESCE(f.n,0) AS n_candles,
                          f.oldest_ts, f.newest_ts FROM pools p LEFT JOIN fetched f ON f.pool=p.pool
                          ORDER BY p.liq_now DESC""").fetchall()
    n_done = sum(1 for p in pools if p["done"])
    n_candles = sum(p["n_candles"] for p in pools)
    plausible = sum(1 for p in pools if p["liq_now"] <= 50_000_000)
    meets_liq = sum(1 for p in pools if cfg["filters"]["min_liq_usd"] <= p["liq_now"] <= 50_000_000)

    summary = [{
        "updated": iso(now) + " UTC",
        "mode": "PAPER ONLY",
        "live_trading": bool(cfg.get("live", False)),
        "kill_file": bot.KILL.exists(),
        "bankroll_usd": cfg["bankroll_usd"],
        "position_usd": cfg["position_usd"],
        "max_open": cfg["max_open"],
        "daily_loss_limit_usd": cfg["risk"]["daily_loss_limit_usd"],
        "pools_in_universe": len(pools),
        "pools_downloaded": n_done,
        "candles_stored": n_candles,
        "pools_plausible_liq": plausible,
        "pools_meeting_liq_filter": meets_liq,
        "tasks_done": sum(1 for t in TASKS if t[2] == "done"),
        "tasks_total": len(TASKS),
    }]
    tasks = [{"task": t[0], "title": t[1], "status": t[2], "note": t[3]} for t in TASKS]
    pool_rows = [{
        "name": p["name"], "dex": p["dex"], "age_days": round((now - p["created_ts"]) / 86400, 1),
        "liq_now_usd": round(p["liq_now"]), "vol24_now_usd": round(p["vol24_now"]),
        "candles": p["n_candles"], "downloaded": bool(p["done"]),
        "source": ", ".join(json.loads(p["sources"])),
        "plausible": p["liq_now"] <= 50_000_000,
    } for p in pools]

    paper = []
    try:
        pdb = bot.db_connect(bot.BASE / cfg["db"])
        for r in pdb.execute("SELECT * FROM positions ORDER BY opened_ts DESC LIMIT 100"):
            paper.append({"symbol": r["symbol"], "status": r["status"], "opened": iso(r["opened_ts"]),
                          "size_usd": r["size_usd"], "pnl_usd": round(r["pnl"] or 0, 4), "reason": r["reason"] or ""})
    except Exception:
        pass

    files = {"summary": summary, "tasks": tasks, "pools": pool_rows, "paper": paper}
    for name, rows in files.items():
        (outdir / f"{name}.json").write_text(json.dumps(rows, separators=(",", ":")))
    return {k: len(v) for k, v in files.items()}


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE / "data" / "export"
    print(build(out))
