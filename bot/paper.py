#!/usr/bin/env python3
"""Forward PAPER trading on memecoin graduates (rule set R1, hypothesis H7). Paper only: no wallet, no keys, nothing is ever sent.

R1 is fixed and not tuned (docs/PREREGISTRATION.md, amendment A6). It is built to be able to catch the rare large winners instead of capping them:
  entry   graduate in the analysis population, 15-minute snapshot fresh (<= 5 min old), all safety gates pass (no insider flag, top-10 holders ex-pool <= 40%,
          authorities revoked, no transfer-fee/hook/permanent-delegate extension), a FRESH Jupiter buy+sell quote at $2.50 with round trip <= 3%
  size    $2.50, at most 2 open positions out of a $5 bankroll, one position per token
  exits   stop -20% from entry | NO take-profit | trailing stop 30% below the peak once the peak is +50% | liquidity falls below half of entry (or under $500) |
          pool vanishes for 3 polls | maximum hold 48 h. If a sell quote fails at exit the position is counted as -100%.
  P&L     size * (exit price / entry price - 1 - measured round-trip cost) - $0.02 network fees. Exit price is the polled price (gaps are not hidden).
  limits  daily loss limit $1.5 (from config), KILL file stops new entries, no entries on stale data.
Prices are polled about once a minute for open positions only.
"""
import time

import bot
import eventstudy as E
import launches as L

BANKROLL = 5.0
SIZE_USD = 2.5
MAX_OPEN = 2
STOP = 0.20
TRAIL_ARM = 0.50
TRAIL = 0.30
MAX_HOLD_S = 48 * 3600
LIQ_EXIT_FRAC = 0.5
LIQ_FLOOR = 500
GONE_POLLS = 3
NET_FEE_USD = 0.02
DAILY_LOSS = 1.5
ENTRY_AGE = 15
STALE_S = 300
POLL_S = 60


def _bump(st, key):
    st["skipped"][key] = st["skipped"].get(key, 0) + 1


def daily_pnl(db, now):
    day0 = now - now % 86400
    return db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM paper_positions WHERE status='closed' AND closed_ts>=?", (day0,)).fetchone()[0]


def free_cash(db):
    realized = db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM paper_positions WHERE status='closed'").fetchone()[0]
    locked = db.execute("SELECT COALESCE(SUM(size_usd),0) FROM paper_positions WHERE status='open'").fetchone()[0]
    return BANKROLL + realized - locked


def exit_reason(pos, px, liq, now):
    """Pure rule check on one polled price. Returns a reason string or None."""
    if liq is not None and (liq < LIQ_FLOOR or liq < pos["entry_liq"] * LIQ_EXIT_FRAC):
        return "liq_drop"
    if px <= pos["entry_px"] * (1 - STOP):
        return "stop"
    if pos["peak_px"] >= pos["entry_px"] * (1 + TRAIL_ARM) and px <= pos["peak_px"] * (1 - TRAIL):
        return "trail"
    if now - pos["opened_ts"] >= MAX_HOLD_S:
        return "time"
    return None


def close(db, pos, now, px, reason, http_json, sol_usd, gone=False):
    sellable = True
    if not gone and http_json is not None and sol_usd:
        sellable = bool(L.round_trip(http_json, pos["mint"], pos["size_usd"], sol_usd)["sell_ok"])
    if gone or not sellable:
        pnl, reason = -pos["size_usd"], reason + ("_gone" if gone else "_unsellable")
    else:
        pnl = pos["size_usd"] * (px / pos["entry_px"] - 1 - (pos["rt_pct"] or 0) / 100) - NET_FEE_USD
    pnl = max(pnl, -pos["size_usd"])                    # a long spot position cannot lose more than it cost
    db.execute("UPDATE paper_positions SET status='closed', closed_ts=?, exit_px=?, reason=?, pnl_usd=? WHERE id=?", (now, px, reason, pnl, pos["id"]))
    bot.log(f"PAPER CLOSE {pos['name']} {reason} pnl=${pnl:+.3f}")
    return pnl


def manage(db, now, gt_get, http_json, sol_usd, st):
    opens = db.execute("SELECT * FROM paper_positions WHERE status='open'").fetchall()
    if not opens or now - L.meta(db, "paper_last_poll", 0.0) < POLL_S:
        return
    L.set_meta(db, "paper_last_poll", now)
    data = L.parse_multi(gt_get("/pools/multi/" + ",".join(p["pool"] for p in opens)))
    for p in opens:
        m = data.get(p["pool"])
        if m is None or not m.get("price"):
            misses = p["misses"] + 1
            db.execute("UPDATE paper_positions SET misses=? WHERE id=?", (misses, p["id"]))
            if misses >= GONE_POLLS:
                close(db, dict(p), now, p["last_px"] or p["entry_px"], "gone", http_json, sol_usd, gone=True)
                st["closed"] += 1
            continue
        px, liq = m["price"], m["liq"]
        pos = dict(p, peak_px=max(p["peak_px"] or p["entry_px"], px))
        db.execute("UPDATE paper_positions SET peak_px=?, last_px=?, last_ts=?, misses=0 WHERE id=?", (pos["peak_px"], px, now, p["id"]))
        why = exit_reason(pos, px, liq, now)
        if why:
            close(db, pos, now, px, why, http_json, sol_usd)
            st["closed"] += 1


def enter(db, now, http_json, sol_usd, st):
    if bot.KILL.exists():
        st["halt"] = "KILL file"
        return
    if daily_pnl(db, now) <= -DAILY_LOSS:
        st["halt"] = "daily loss limit"
        return
    rows = db.execute("""SELECT l.*, s.ts AS snap_ts, s.price AS snap_px, s.liq AS snap_liq FROM launches l
                         JOIN snaps s ON s.pool=l.pool AND s.age_target_min=? AND s.missed=0 AND s.price>0
                         WHERE l.status='observed' AND l.class IN ('memecoin_confirmed','memecoin_probable') AND s.ts >= ?
                         AND l.mint NOT IN (SELECT mint FROM paper_positions) ORDER BY s.ts""", (ENTRY_AGE, now - STALE_S)).fetchall()
    for r in rows:
        n_open = db.execute("SELECT COUNT(*) FROM paper_positions WHERE status='open'").fetchone()[0]
        if n_open >= MAX_OPEN or free_cash(db) < SIZE_USD:
            _bump(st, "no_capacity")
            return
        rec = E.load_record(db, r)
        g = E.gates(rec, ENTRY_AGE, enforce_time=False)
        if g is None:
            _bump(st, "waiting_for_safety")
            continue
        if not g["all_ok"]:
            _bump(st, "gate_fail")
            continue
        if (r["snap_liq"] or 0) < LIQ_FLOOR * 10:
            _bump(st, "thin")
            continue
        q = L.round_trip(http_json, r["mint"], SIZE_USD, sol_usd)
        if not (q["buy_ok"] and q["sell_ok"]) or q["rt_pct"] is None or q["rt_pct"] > E.SELL_GATE_PCT:
            _bump(st, "sell_gate_fresh")
            db.execute("INSERT INTO paper_positions(pool,mint,name,opened_ts,entry_px,entry_liq,size_usd,rt_pct,status,closed_ts,reason,pnl_usd) VALUES(?,?,?,?,?,?,?,?,'skipped',?,?,0)",
                       (r["pool"], r["mint"], r["name"], now, r["snap_px"], r["snap_liq"], SIZE_USD, q["rt_pct"], now, "sell_gate_fresh"))
            continue
        db.execute("INSERT INTO paper_positions(pool,mint,name,opened_ts,entry_px,entry_liq,size_usd,rt_pct,entry_delay_s,peak_px,last_px,last_ts,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'open')",
                   (r["pool"], r["mint"], r["name"], now, r["snap_px"], r["snap_liq"], SIZE_USD, q["rt_pct"], now - r["snap_ts"], r["snap_px"], r["snap_px"], now))
        bot.log(f"PAPER OPEN {r['name']} px={r['snap_px']:.6g} liq=${r['snap_liq']:,.0f} rt={q['rt_pct']:.2f}%")
        st["opened"] += 1


def step(db, now, gt_get, http_json, sol_usd):
    st = {"opened": 0, "closed": 0, "skipped": {}}
    manage(db, now, gt_get, http_json, sol_usd, st)
    if sol_usd:
        enter(db, now, http_json, sol_usd, st)
    db.commit()
    return st


def summary(db):
    rows = db.execute("SELECT * FROM paper_positions WHERE status='closed' ORDER BY closed_ts").fetchall()
    pnl = [r["pnl_usd"] for r in rows]
    open_ = db.execute("SELECT COUNT(*) FROM paper_positions WHERE status='open'").fetchone()[0]
    skipped = db.execute("SELECT COUNT(*) FROM paper_positions WHERE status='skipped'").fetchone()[0]
    out = {"closed": len(rows), "open": open_, "skipped_fresh_gate": skipped, "net_pnl_usd": sum(pnl), "equity_usd": BANKROLL + sum(pnl)}
    if pnl:
        wins, losses = sum(x for x in pnl if x > 0), -sum(x for x in pnl if x <= 0)
        eq, peak, dd = 0.0, 0.0, 0.0
        for x in pnl:
            eq += x
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        best = max(pnl)
        out.update(win_rate=sum(x > 0 for x in pnl) / len(pnl), profit_factor=(wins / losses) if losses > 0 else None, mean_usd=sum(pnl) / len(pnl),
                   median_usd=E.median(pnl), best_usd=best, best_share_of_gains=(best / wins) if wins > 0 and best > 0 else None, max_drawdown_usd=dd,
                   reasons={k: sum(1 for r in rows if r["reason"] == k) for k in {r["reason"] for r in rows}})
    return out
