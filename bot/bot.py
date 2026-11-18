#!/usr/bin/env python3
"""Paper trader for Solana memecoins (DexScreener data). No real transactions.

Usage:
  python3 bot.py run      # loop forever (scan every scan_interval_s)
  python3 bot.py once     # single cycle
  python3 bot.py report   # results + go/no-go verdict
  python3 bot.py collect  # data collector only (no positions); add --once for a single cycle
  python3 bot.py funnel   # per-source pass rates from collected snapshots
  Create a file named KILL next to bot.py to stop new entries.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
API = "https://api.dexscreener.com"
KILL = BASE / "KILL"


def load_cfg(path=None):
    return json.loads(Path(path or BASE / "config.json").read_text())


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}Z {msg}"
    print(line, flush=True)
    try:
        with open(BASE / "bot.log", "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def http_json(url, body=None, retries=2, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": "paper-trader/0.1", "Content-Type": "application/json"}
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:  # network/HTTP/JSON errors: retry, then give up
            if i == retries:
                log(f"http fail {url[:90]}: {e!r}")
                return None
            time.sleep(1.5 * (i + 1))


# ---------------------------------------------------------------- data

def split_tags(source):
    return [t for t in (source or "").split("+") if t]


def discover(cfg=None):
    """Return {token_address: 'tagA+tagB'} from every configured source (see discovery.py). Tags let bias be measured per source."""
    import discovery
    return discovery.discover(cfg)


def fetch_pairs(addrs, quote_whitelist=None):
    """Best (highest-liquidity) pair per base token."""
    best = {}
    for i in range(0, len(addrs), 30):
        chunk = addrs[i:i + 30]
        data = http_json(f"{API}/tokens/v1/solana/{','.join(chunk)}") or []
        for p in data:
            try:
                a = p["baseToken"]["address"]
            except (KeyError, TypeError):
                continue
            if a not in chunk:
                continue
            if quote_whitelist and p.get("quoteToken", {}).get("symbol") not in quote_whitelist:
                continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if a in best and ((best[a].get("liquidity") or {}).get("usd") or 0) >= liq:
                continue
            best[a] = p
    return best


# ---------------------------------------------------------------- filters

def age_h(p, now=None):
    t = p.get("pairCreatedAt")
    return ((now or time.time()) * 1000 - t) / 3.6e6 if t else None


def features_from_dex(p, now=None):
    """Normalise a DexScreener pair into the feature dict used by check_features.
    A value of None means 'not available' (never silently 0)."""
    liq = (p.get("liquidity") or {}).get("usd")
    ch = p.get("priceChange") or {}
    tx = (p.get("txns") or {}).get("h1") or {}
    return {
        "age_h": age_h(p, now),
        "liq_usd": liq,
        "vol24_usd": (p.get("volume") or {}).get("h24"),
        "h1_pct": ch.get("h1"),
        "h24_pct": ch.get("h24"),
        "h1_buys": tx.get("buys"),
        "h1_sells": tx.get("sells"),
    }


# Which feature each filter needs. A filter whose inputs are None is "not evaluable" (reported, not passed).
FILTER_INPUTS = {
    "age": ("age_h",), "liq": ("liq_usd",), "vol24": ("vol24_usd",),
    "vol/liq": ("vol24_usd", "liq_usd"), "h1": ("h1_pct",), "h24": ("h24_pct",),
    "flow": ("h1_buys", "h1_sells"),
}


def check_features(ft, f, skip=()):
    """Return (failed, not_evaluable) filter-name lists. `skip` = filters deliberately not applied
    (e.g. the backtest has no historical liquidity). None inputs: age/h1/h24 fail (as before); others are
    reported as not evaluable and do NOT count as a pass for the caller to rely on."""
    failed, na = [], []
    for name, keys in FILTER_INPUTS.items():
        if name in skip:
            continue
        if any(ft.get(k) is None for k in keys):
            (failed if name in ("age", "h1", "h24") else na).append(name)
    if "age" not in failed and "age" not in skip and not f["min_age_h"] <= ft["age_h"] <= f["max_age_h"]:
        failed.append("age")
    liq, v24 = ft.get("liq_usd"), ft.get("vol24_usd")
    if "liq" not in na and "liq" not in skip and liq < f["min_liq_usd"]:
        failed.append("liq")
    if "vol24" not in na and "vol24" not in skip and v24 < f["min_vol24_usd"]:
        failed.append("vol24")
    if "vol/liq" not in na and "vol/liq" not in skip:
        vl = v24 / liq if liq else 0
        if not f["vol_liq_min"] <= vl <= f["vol_liq_max"]:
            failed.append("vol/liq")
    if "h1" not in failed and "h1" not in skip and not f["h1_change_min"] <= ft["h1_pct"] <= f["h1_change_max"]:
        failed.append("h1")
    if "h24" not in failed and "h24" not in skip and not f["h24_change_min"] <= ft["h24_pct"] <= f["h24_change_max"]:
        failed.append("h24")
    if "flow" not in na and "flow" not in skip:
        n = ft["h1_buys"] + ft["h1_sells"]
        if n < f["min_h1_txns"] or ft["h1_buys"] / n < f["min_h1_buy_ratio"]:
            failed.append("flow")
    return failed, na


def check_filters(p, f, now=None):
    """Live-loop wrapper: failed filter names for a DexScreener pair (empty = pass).
    Missing DexScreener fields count as failures here (live must never trade on unknowns)."""
    failed, na = check_features(features_from_dex(p, now), f)
    return failed + na


def rpc(cfg, method, params):
    return http_json(cfg["rpc_url"], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})


def onchain_check(cfg, addr):
    """Mint/freeze authority must be revoked; holder concentration (excl. largest = likely LP vault)."""
    m = rpc(cfg, "getAccountInfo", [addr, {"encoding": "jsonParsed"}])
    try:
        info = m["result"]["value"]["data"]["parsed"]["info"]
    except (TypeError, KeyError):
        return False, "mint_unreadable", None
    if info.get("mintAuthority"):
        return False, "mint_authority", None
    if info.get("freezeAuthority"):
        return False, "freeze_authority", None
    h = rpc(cfg, "getTokenLargestAccounts", [addr])
    try:
        total = float(info["supply"]) / 10 ** info["decimals"]
        amts = sorted((float(v.get("uiAmount") or 0) for v in h["result"]["value"]), reverse=True)
    except (TypeError, KeyError, ValueError):
        return False, "holders_unreadable", None
    pct = 100 * sum(amts[1:11]) / total if total else 100.0
    if pct > cfg["filters"]["max_top_ex_largest_pct"]:
        return False, "concentration", pct
    return True, "ok", pct


def onchain_cached(cfg, db, addr, now):
    row = db.execute("SELECT * FROM onchain WHERE addr=?", (addr,)).fetchone()
    if row and now - row["ts"] < cfg["risk"]["onchain_cache_h"] * 3600:
        return bool(row["ok"]), row["reason"], row["pct"]
    ok, why, pct = onchain_check(cfg, addr)
    if why not in ("mint_unreadable", "holders_unreadable"):  # don't cache RPC hiccups
        db.execute("INSERT OR REPLACE INTO onchain VALUES(?,?,?,?,?)", (addr, now, int(ok), why, pct))
    return ok, why, pct


# ---------------------------------------------------------------- costs / exits

def _slip(c, usd, liq):
    return min(c["slippage_pct"] / 100 + 2 * usd / max(liq, 1.0), 0.95)


def fill_buy(px, size, liq, c):
    """Return (fill_price, qty) after slippage, % fee and flat network fee."""
    fill = px * (1 + _slip(c, size, liq))
    qty = (size * (1 - c["fee_pct"] / 100) - c["network_fee_usd"]) / fill
    return fill, qty


def proceeds_sell(px, qty, liq, c):
    gross = qty * px
    return gross * (1 - _slip(c, gross, liq)) * (1 - c["fee_pct"] / 100) - c["network_fee_usd"]


def exit_levels(pos, e):
    """Price levels at which each price-based exit trips, given the position's peak so far.
    Single source of the thresholds: exit_reason() and the backtester both use it."""
    lv = {"stop": pos["entry_px"] * (1 - e["stop_loss_pct"] / 100),
          "tp": pos["entry_px"] * (1 + e["take_profit_pct"] / 100), "trail": None}
    if 100 * (pos["peak_px"] / pos["entry_px"] - 1) >= e["trail_activate_pct"]:
        lv["trail"] = pos["peak_px"] * (1 - e["trail_pct"] / 100)
    return lv


def exit_reason(pos, px, liq, now, e):
    """pos['peak_px'] must already include px."""
    lv = exit_levels(pos, e)
    if liq < pos["entry_liq"] * e["liq_drop_exit_frac"]:
        return "liq_drop"
    if px <= lv["stop"]:
        return "stop"
    if px >= lv["tp"]:
        return "tp"
    if lv["trail"] is not None and px <= lv["trail"]:
        return "trail"
    if (now - pos["opened_ts"]) / 3600 >= e["max_hold_h"]:
        return "time"
    return None


# ---------------------------------------------------------------- db

def db_connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS positions(
      id INTEGER PRIMARY KEY, addr TEXT, symbol TEXT, source TEXT,
      entry_liq REAL, liq REAL, opened_ts REAL, entry_px REAL, fill_px REAL,
      size_usd REAL, qty REAL, peak_px REAL, last_px REAL, last_seen_ts REAL,
      status TEXT DEFAULT 'open', closed_ts REAL, exit_px REAL, proceeds REAL,
      pnl REAL, reason TEXT, meta TEXT);
    CREATE TABLE IF NOT EXISTS onchain(addr TEXT PRIMARY KEY, ts REAL, ok INT, reason TEXT, pct REAL);
    CREATE TABLE IF NOT EXISTS funnel(ts REAL, discovered INT, with_pair INT, cheap_pass INT,
      opened INT, closed INT, rejects TEXT);
    CREATE TABLE IF NOT EXISTS funnel_src(ts REAL, source TEXT, candidates INT, with_pair INT, cheap_pass INT,
      onchain_checked INT, onchain_ok INT, rejects TEXT);
    CREATE TABLE IF NOT EXISTS snapshots(ts REAL, addr TEXT, symbol TEXT, source TEXT, price REAL, liq REAL, vol24 REAL,
      h1 REAL, h24 REAL, age_h REAL, buys INT, sells INT, failed TEXT, cheap_pass INT);
    CREATE INDEX IF NOT EXISTS snap_ts ON snapshots(ts);
    """)
    return db


def free_cash(db, cfg):
    realized = db.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed'").fetchone()[0]
    locked = db.execute("SELECT COALESCE(SUM(size_usd),0) FROM positions WHERE status='open'").fetchone()[0]
    return cfg["bankroll_usd"] + realized - locked


def open_position(db, cfg, addr, p, source, pct, now):
    px = float(p["priceUsd"])
    liq = (p.get("liquidity") or {}).get("usd") or 0
    size = cfg["position_usd"]
    fill, qty = fill_buy(px, size, liq, cfg["costs"])
    meta = {"h1": p["priceChange"].get("h1"), "h24": p["priceChange"].get("h24"),
            "vol24": p["volume"].get("h24"), "top_ex_largest_pct": pct,
            "age_h": round(age_h(p, now) or 0, 1)}
    db.execute("""INSERT INTO positions(addr,symbol,source,entry_liq,liq,opened_ts,entry_px,fill_px,
                  size_usd,qty,peak_px,last_px,last_seen_ts,meta) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (addr, p["baseToken"]["symbol"], source, liq, liq, now, px, fill, size, qty, px, px, now,
                json.dumps(meta)))
    log(f"OPEN {p['baseToken']['symbol']} px={px:.6g} liq=${liq:,.0f} {meta}")


def close_position(db, cfg, pos, px, reason, now, liq):
    proceeds = proceeds_sell(px, pos["qty"], liq, cfg["costs"])
    pnl = proceeds - pos["size_usd"]
    db.execute("""UPDATE positions SET status='closed',closed_ts=?,exit_px=?,proceeds=?,pnl=?,reason=?
                  WHERE id=?""", (now, px, proceeds, pnl, reason, pos["id"]))
    log(f"CLOSE {pos['symbol']} {reason} px={px:.6g} pnl=${pnl:+.3f}")


# ---------------------------------------------------------------- cycle

def record_snapshot(db, now, addr, p, source, failed):
    ft = features_from_dex(p, now)
    try:
        price = float(p.get("priceUsd") or 0)
    except ValueError:
        price = 0.0
    db.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (now, addr, (p.get("baseToken") or {}).get("symbol"), source, price, ft["liq_usd"], ft["vol24_usd"], ft["h1_pct"],
                ft["h24_pct"], ft["age_h"], ft["h1_buys"], ft["h1_sells"], json.dumps(failed), int(not failed)))


def cycle(cfg, db, now=None, trade=True):
    """One scan. trade=False = collector mode: discover, snapshot and run the same filters, but never open or manage positions."""
    now = now or time.time()
    st = {"opened": 0, "closed": 0}
    qw = cfg.get("quote_whitelist")

    opens = db.execute("SELECT * FROM positions WHERE status='open'").fetchall() if trade else []
    if opens:
        pairs = fetch_pairs([p["addr"] for p in opens], qw)
        for pos in opens:
            pr = pairs.get(pos["addr"])
            if pr and pr.get("priceUsd"):
                px = float(pr["priceUsd"])
                liq = (pr.get("liquidity") or {}).get("usd") or 0
                peak = max(pos["peak_px"], px)
                db.execute("UPDATE positions SET peak_px=?,last_px=?,last_seen_ts=?,liq=? WHERE id=?",
                           (peak, px, now, liq, pos["id"]))
                pos = db.execute("SELECT * FROM positions WHERE id=?", (pos["id"],)).fetchone()
                why = exit_reason(pos, px, liq, now, cfg["exit"])
                if why:
                    close_position(db, cfg, pos, px, why, now, liq)
                    st["closed"] += 1
            elif now - pos["last_seen_ts"] > cfg["exit"]["no_data_min"] * 60:
                # pair vanished: assume the worst (price halved) instead of the last quote
                close_position(db, cfg, pos, pos["last_px"] * 0.5, "no_data", now, pos["liq"])
                st["closed"] += 1
        db.commit()

    # entry gates: they only stop ENTRIES. Discovery and snapshots continue, so the data keeps accumulating.
    can_enter = trade
    n_open = cash = 0
    if trade:
        if KILL.exists():
            st["halt"], can_enter = "KILL file", False
        else:
            day0 = now - now % 86400
            day_pnl = db.execute("SELECT COALESCE(SUM(pnl),0) FROM positions WHERE status='closed' AND closed_ts>=?",
                                 (day0,)).fetchone()[0]
            if day_pnl <= -cfg["risk"]["daily_loss_limit_usd"]:
                st["halt"], can_enter = f"daily loss limit ({day_pnl:+.2f})", False
        n_open = db.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
        cash = free_cash(db, cfg)
        if can_enter and (n_open >= cfg["max_open"] or cash < cfg["position_usd"]):
            st["halt"], can_enter = "no capacity", False

    src = discover(cfg)
    blocked = {r[0] for r in db.execute(
        "SELECT addr FROM positions WHERE status='open' OR closed_ts>=?",
        (now - cfg["risk"]["reentry_block_h"] * 3600,))} if trade else set()
    cand = [a for a in src if a not in blocked]
    pairs = fetch_pairs(cand, qw)
    rej = Counter()
    per = {}                                     # per-source funnel counters
    def stat(tag):
        return per.setdefault(tag, {"candidates": 0, "with_pair": 0, "cheap_pass": 0, "onchain_checked": 0, "onchain_ok": 0, "rejects": Counter()})
    for a in cand:
        for tag in split_tags(src[a]):
            stat(tag)["candidates"] += 1
    cheap = []
    for a, p in pairs.items():
        r = check_filters(p, cfg["filters"], now)
        record_snapshot(db, now, a, p, src.get(a, ""), r)
        tags = split_tags(src.get(a, ""))
        for tag in tags:
            stat(tag)["with_pair"] += 1
            if r:
                stat(tag)["rejects"].update(r)
            else:
                stat(tag)["cheap_pass"] += 1
        if r:
            rej.update(r)
        else:
            cheap.append((a, p))
    cheap.sort(key=lambda x: -((x[1].get("volume") or {}).get("h24") or 0))
    checks_left = cfg.get("onchain_checks_per_cycle", 5)
    for a, p in cheap:
        if checks_left <= 0:
            break
        checks_left -= 1
        ok, why, pct = onchain_cached(cfg, db, a, now)
        for tag in split_tags(src[a]):
            stat(tag)["onchain_checked"] += 1
            stat(tag)["onchain_ok"] += int(ok)
        if not ok:
            rej[why] += 1
            continue
        if can_enter and n_open < cfg["max_open"] and cash >= cfg["position_usd"]:
            open_position(db, cfg, a, p, src[a], pct, now)
            n_open += 1
            cash -= cfg["position_usd"]
            st["opened"] += 1
    db.execute("INSERT INTO funnel VALUES(?,?,?,?,?,?,?)",
               (now, len(src), len(pairs), len(cheap), st["opened"], st["closed"], json.dumps(rej)))
    for tag, v in per.items():
        db.execute("INSERT INTO funnel_src VALUES(?,?,?,?,?,?,?,?)",
                   (now, tag, v["candidates"], v["with_pair"], v["cheap_pass"], v["onchain_checked"], v["onchain_ok"], json.dumps(v["rejects"])))
    db.commit()
    st.update(discovered=len(src), with_pair=len(pairs), cheap_pass=len(cheap), rejects=dict(rej),
              sources={t: {k: (dict(x) if isinstance(x, Counter) else x) for k, x in v.items()} for t, v in per.items()})
    return st


def run(cfg):
    db = db_connect(BASE / cfg["db"])
    log("paper trader started")
    while True:
        try:
            log(cycle(cfg, db))
        except Exception as e:  # keep the loop alive; log and retry next cycle
            log(f"cycle error: {e!r}")
        time.sleep(cfg["scan_interval_s"])


def collect(cfg):
    """Collector mode: no positions, just discovery + snapshots + filter results every collect_interval_s."""
    db = db_connect(BASE / cfg["db"])
    log("collector started (no trading)")
    while True:
        try:
            st = cycle(cfg, db, trade=False)
            log({k: st[k] for k in ("discovered", "with_pair", "cheap_pass")})
        except Exception as e:
            log(f"collect error: {e!r}")
        time.sleep(cfg.get("collect_interval_s", 300))


PAID_TAGS = ("ds_boost_top", "ds_boost_latest", "ds_profile")


def funnel_rows(db, hours=None):
    """Per-source funnel rows from snapshots (observations) and funnel_src (candidates incl. those with no pair)."""
    where, args = ("WHERE ts >= ?", (time.time() - hours * 3600,)) if hours else ("", ())
    agg = {}
    for r in db.execute(f"SELECT addr, source, cheap_pass, failed FROM snapshots {where}", args):
        for tag in split_tags(r["source"]):
            a = agg.setdefault(tag, {"obs": 0, "tokens": set(), "pass": 0, "fail": Counter()})
            a["obs"] += 1
            a["tokens"].add(r["addr"])
            a["pass"] += r["cheap_pass"]
            a["fail"].update(json.loads(r["failed"] or "[]"))
    cand = {r[0]: r[1] for r in db.execute(f"SELECT source, SUM(candidates) FROM funnel_src {where} GROUP BY source", args)}
    rows = []
    for tag, a in sorted(agg.items(), key=lambda kv: -kv[1]["obs"]):
        n = a["obs"]
        rows.append({"source": tag, "paid": tag in PAID_TAGS, "candidates": cand.get(tag, 0), "with_pair": n, "unique": len(a["tokens"]),
                     "age_ok_pct": round(100 * (1 - a["fail"].get("age", 0) / n), 1), "cheap_pass": a["pass"],
                     "pass_pct": round(100 * a["pass"] / n, 1),
                     "top_rejects": ", ".join(f"{k} {100 * v / n:.0f}%" for k, v in a["fail"].most_common(3)), "_agg": a})
    return rows


def funnel_report(db, hours=None):
    rows = funnel_rows(db, hours)
    print(f"{'source':<16}{'paid':<6}{'candidates':>11}{'with pair':>10}{'unique':>8}{'age ok %':>9}{'cheap pass':>11}{'pass %':>8}  top rejects")
    for r in rows:
        print(f"{r['source']:<16}{'yes' if r['paid'] else 'no':<6}{r['candidates']:>11}{r['with_pair']:>10}{r['unique']:>8}{r['age_ok_pct']:>8.1f}%"
              f"{r['cheap_pass']:>11}{r['pass_pct']:>7.1f}%  {r['top_rejects']}")
    return {r["source"]: r["_agg"] for r in rows}


# ---------------------------------------------------------------- report

def report(cfg, db):
    rows = db.execute("SELECT * FROM positions WHERE status='closed' ORDER BY closed_ts").fetchall()
    n_open = db.execute("SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]
    wins = [r["pnl"] for r in rows if r["pnl"] > 0]
    losses = [-r["pnl"] for r in rows if r["pnl"] <= 0]
    net = sum(r["pnl"] for r in rows)
    pf = (sum(wins) / sum(losses)) if losses and sum(losses) > 0 else float("inf") if wins else 0.0
    print(f"Closed trades: {len(rows)} | open: {n_open} | net PnL: ${net:+.3f} | "
          f"win rate: {100 * len(wins) / len(rows):.0f}% | profit factor: {pf:.2f}" if rows else
          f"No closed trades yet | open: {n_open}")
    by = Counter(r["reason"] for r in rows)
    print("Exit reasons:", dict(by))
    for r in rows[-15:]:
        print(f"  {r['symbol']:<10} {r['reason']:<8} pnl=${r['pnl']:+.3f}")
    fr = db.execute("SELECT COUNT(*), COALESCE(SUM(discovered),0), COALESCE(SUM(cheap_pass),0) FROM funnel").fetchone()
    print(f"Cycles: {fr[0]} | discovered(sum): {fr[1]} | passed cheap filters(sum): {fr[2]}")
    g = cfg["go_nogo"]
    if len(rows) < g["min_closed_trades"]:
        print(f"VERDICT: INSUFFICIENT DATA ({len(rows)}/{g['min_closed_trades']} trades) -> keep paper trading")
    elif net > g["min_net_pnl_usd"] and pf >= g["min_profit_factor"]:
        print("VERDICT: GO (paper edge after costs; still a small sample - go live with minimal size)")
    else:
        print("VERDICT: NO-GO (no edge after costs) -> stay on paper / change hypothesis")


if __name__ == "__main__":
    cfg = load_cfg()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "run":
        run(cfg)
    elif cmd == "once":
        print(cycle(cfg, db_connect(BASE / cfg["db"])))
    elif cmd == "collect":
        if "--once" in sys.argv:
            print(cycle(cfg, db_connect(BASE / cfg["db"]), trade=False))
        else:
            collect(cfg)
    elif cmd == "funnel":
        funnel_report(db_connect(BASE / cfg["db"]))
    elif cmd == "report":
        report(cfg, db_connect(BASE / cfg["db"]))
    else:
        sys.exit(__doc__)
