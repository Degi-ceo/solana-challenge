#!/usr/bin/env python3
"""Graduation stream + fixed-age snapshots (task 4). Read-only: no keys, no transactions, quotes only.

  python3 launches.py once     # one full cycle (poll stream, snapshots, probes, safety)
  python3 launches.py run      # loop forever (what the VPS runs)
  python3 launches.py stats    # what has been collected

What it records (see docs/PREREGISTRATION.md for how it is analysed):
  launches  every NEW non-curve pool seen on GeckoTerminal new_pools, with detection delay, classification and status
            (observed / tiny / late / curve_ignored are counted; only 'observed' launches get snapshots)
  snaps     price, liquidity, volume, buys/sells, unique traders at fixed pool ages (1,5,15,30,60 min, 2,6,24,48,72 h)
  probes    Jupiter buy+sell QUOTES (never sent) at $1 / $2.50 -> measured round-trip price cost
  safety    one RugCheck full report per launch (insiders, holders ex-LP, LP lock, authorities, Token-2022 extensions)
Nothing is back-filled: a snapshot that was not taken in time is recorded as missed.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

import bot
import classify

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "launches.db"
GT = "/new_pools?page={p}"
SOL = "So11111111111111111111111111111111111111112"
AGES_MIN = [1, 5, 15, 30, 60, 120, 360, 1440, 2880, 4320]
PROBE_AGES = {5, 15, 60, 360}
PROBE_SIZES_USD = [1.0, 2.5]
SAFETY_AGE_MIN = 5
MAX_DETECT_DELAY_S = 600   # amendment A2: GeckoTerminal lists new pools after a median of ~3.5 min; 5 min excluded ~27%
MIN_LIQ_USD = 3_000
UNSELLABLE_LIQ_USD = 500
JUP = "https://api.jup.ag/swap/v1/quote"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"


def log(msg):
    bot.log(msg)


# ---------------------------------------------------------------- db

def connect(path=DB_PATH):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS launches(pool TEXT PRIMARY KEY, mint TEXT, name TEXT, dex TEXT, created_ts REAL, detected_ts REAL,
      detect_delay_s REAL, liq_at_detect REAL, class TEXT, reason TEXT, launchpad TEXT, jup_verified INT, status TEXT, safety_done INT DEFAULT 0);
    CREATE TABLE IF NOT EXISTS snaps(pool TEXT, age_target_min INT, ts REAL, age_min REAL, price REAL, liq REAL, mcap REAL, fdv REAL,
      vol_m5 REAL, vol_h1 REAL, vol_h24 REAL, buys_m5 INT, sells_m5 INT, buys_h1 INT, sells_h1 INT, traders_h1 INT, chg_m5 REAL, chg_h1 REAL,
      missed INT DEFAULT 0, PRIMARY KEY(pool, age_target_min));
    CREATE TABLE IF NOT EXISTS probes(pool TEXT, age_target_min INT, size_usd REAL, ts REAL, buy_ok INT, sell_ok INT, rt_pct REAL,
      impact_raw REAL, route TEXT, PRIMARY KEY(pool, age_target_min, size_usd));
    CREATE TABLE IF NOT EXISTS safety(pool TEXT PRIMARY KEY, ts REAL, score REAL, rugged INT, launchpad TEXT, jup_verified INT,
      creator_pct REAL, insiders_detected INT, insider_networks INT, top1_pct_ex_lp REAL, top10_pct_ex_lp REAL, top10_pct_raw REAL,
      total_holders INT, lp_locked_pct REAL, mint_authority INT, freeze_authority INT, transfer_fee_pct REAL, extensions TEXT,
      token_program TEXT, risks TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value REAL);
    CREATE INDEX IF NOT EXISTS launches_status ON launches(status, created_ts);
    """)
    return db


def bump(db, key, n=1):
    db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value = value + ?", (key, n, n))


def meta(db, key, default=0.0):
    r = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def set_meta(db, key, v):
    db.execute("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=?", (key, v, v))


# ---------------------------------------------------------------- stream (pure parse + ingest)

def _ts(s):
    import calendar
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def parse_pools(j):
    """GeckoTerminal pool listing -> list of dicts (skips malformed rows)."""
    out = []
    for d in (j or {}).get("data", []) or []:
        try:
            a, rel = d["attributes"], d["relationships"]
            out.append({"pool": a["address"], "name": a["name"], "created_ts": _ts(a["pool_created_at"]),
                        "liq": float(a.get("reserve_in_usd") or 0), "mint": rel["base_token"]["data"]["id"].split("_", 1)[1],
                        "dex": rel["dex"]["data"]["id"]})
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    return out


def ingest(db, pools, now):
    """Register unseen pools. Returns counters. Curve pools are ignored; tiny and late pools are stored (status) but never observed."""
    c = {"seen": 0, "new": 0, "curve": 0, "tiny": 0, "late": 0, "observed": 0}
    for p in pools:
        c["seen"] += 1
        if classify.is_curve_pool(p["dex"]):
            c["curve"] += 1
            continue
        if db.execute("SELECT 1 FROM launches WHERE pool=?", (p["pool"],)).fetchone():
            continue
        delay = now - p["created_ts"]
        status = "tiny" if p["liq"] < MIN_LIQ_USD else "late" if delay > MAX_DETECT_DELAY_S else "observed"
        cls, why = classify.classify(p["mint"], p["dex"], p["liq"])
        db.execute("INSERT INTO launches(pool,mint,name,dex,created_ts,detected_ts,detect_delay_s,liq_at_detect,class,reason,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (p["pool"], p["mint"], p["name"], p["dex"], p["created_ts"], now, delay, p["liq"], cls, why, status))
        c["new"] += 1
        c[status] += 1
    return c


def poll_stream(db, now, gt_get, pages=10):
    """Fetch new_pools pages 1..pages, ingest, and detect coverage gaps between consecutive polls."""
    allp = []
    for pg in range(1, pages + 1):
        rows = parse_pools(gt_get(GT.format(p=pg)))
        if not rows:
            break
        allp.extend(rows)
    c = ingest(db, allp, now)
    if allp:
        oldest, newest = min(p["created_ts"] for p in allp), max(p["created_ts"] for p in allp)
        prev_newest = meta(db, "last_poll_newest_ts", 0.0)
        bump(db, "polls")
        if prev_newest and oldest > prev_newest:        # nothing overlaps with the previous poll -> pools may have been missed
            bump(db, "stream_gaps")
        set_meta(db, "last_poll_newest_ts", newest)
        set_meta(db, "last_poll_span_s", newest - oldest)
    for k, v in c.items():
        bump(db, "n_" + k, v)
    db.commit()
    return c


# ---------------------------------------------------------------- snapshots

def due_targets(db, now):
    """[(pool, age_target_min, 'take'|'miss')] for observed launches. Take if age >= target and the delay is at most 50% of target + 2 min."""
    out = []
    for r in db.execute("SELECT pool, created_ts FROM launches WHERE status='observed'").fetchall():
        age = (now - r["created_ts"]) / 60
        have = {x[0] for x in db.execute("SELECT age_target_min FROM snaps WHERE pool=?", (r["pool"],))}
        for t in AGES_MIN:
            if t in have or age < t:
                continue
            out.append((r["pool"], t, "take" if age - t <= 0.5 * t + 2 else "miss"))
    return out


def parse_multi(j):
    """GeckoTerminal /pools/multi response -> {pool: metrics dict}."""
    out = {}
    for d in (j or {}).get("data", []) or []:
        try:
            a = d["attributes"]
            f = lambda x: float(x) if x not in (None, "") else None
            tx, vol, chg = a.get("transactions") or {}, a.get("volume_usd") or {}, a.get("price_change_percentage") or {}
            out[a["address"]] = {"price": f(a.get("base_token_price_usd")), "liq": f(a.get("reserve_in_usd")), "mcap": f(a.get("market_cap_usd")),
                                 "fdv": f(a.get("fdv_usd")), "vol_m5": f(vol.get("m5")), "vol_h1": f(vol.get("h1")), "vol_h24": f(vol.get("h24")),
                                 "buys_m5": (tx.get("m5") or {}).get("buys"), "sells_m5": (tx.get("m5") or {}).get("sells"),
                                 "buys_h1": (tx.get("h1") or {}).get("buys"), "sells_h1": (tx.get("h1") or {}).get("sells"),
                                 "traders_h1": (tx.get("h1") or {}).get("unique_traders"), "chg_m5": f(chg.get("m5")), "chg_h1": f(chg.get("h1"))}
        except (KeyError, TypeError, ValueError):
            continue
    return out


def take_snapshots(db, now, gt_get, max_pools=60):
    todo = [x for x in due_targets(db, now) if x[2] == "take"]
    for pool, t, kind in [x for x in due_targets(db, now) if x[2] == "miss"]:
        db.execute("INSERT OR IGNORE INTO snaps(pool, age_target_min, ts, missed) VALUES(?,?,?,1)", (pool, t, now))
        bump(db, "snaps_missed")
    pools = sorted({p for p, _, _ in todo})[:max_pools]
    taken = 0
    for i in range(0, len(pools), 30):
        chunk = pools[i:i + 30]
        data = parse_multi(gt_get("/pools/multi/" + ",".join(chunk)))
        for pool in chunk:
            m = data.get(pool)
            created = db.execute("SELECT created_ts FROM launches WHERE pool=?", (pool,)).fetchone()["created_ts"]
            for p, t, _ in [x for x in todo if x[0] == pool]:
                if m is None:                                  # pool vanished from the API: record it, it counts as unsellable later
                    db.execute("INSERT OR IGNORE INTO snaps(pool, age_target_min, ts, age_min, missed) VALUES(?,?,?,?,2)", (pool, t, now, (now - created) / 60))
                    bump(db, "snaps_gone")
                    continue
                db.execute("""INSERT OR IGNORE INTO snaps(pool,age_target_min,ts,age_min,price,liq,mcap,fdv,vol_m5,vol_h1,vol_h24,buys_m5,sells_m5,buys_h1,sells_h1,traders_h1,chg_m5,chg_h1)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (pool, t, now, (now - created) / 60, m["price"], m["liq"], m["mcap"], m["fdv"], m["vol_m5"], m["vol_h1"], m["vol_h24"],
                            m["buys_m5"], m["sells_m5"], m["buys_h1"], m["sells_h1"], m["traders_h1"], m["chg_m5"], m["chg_h1"]))
                taken += 1
    bump(db, "snaps_taken", taken)
    db.commit()
    return taken


# ---------------------------------------------------------------- cost probes (quotes only)

def round_trip(http_json, mint, size_usd, sol_usd, slippage_bps=300):
    """Quote SOL->token then token->SOL of the received amount. Returns dict; nothing is ever sent."""
    lam = int(size_usd / sol_usd * 1e9)
    q = http_json(f"{JUP}?inputMint={SOL}&outputMint={mint}&amount={lam}&slippageBps={slippage_bps}")
    if not q or "outAmount" not in q:
        return {"buy_ok": 0, "sell_ok": 0, "rt_pct": None, "impact_raw": None, "route": ""}
    b = http_json(f"{JUP}?inputMint={mint}&outputMint={SOL}&amount={q['outAmount']}&slippageBps={slippage_bps}")
    route = "/".join(x["swapInfo"]["label"] for x in q.get("routePlan", []))
    imp = float(q.get("priceImpactPct") or 0)         # stored as returned by Jupiter (unit not relied upon; rt_pct is the cost measure)
    if not b or "outAmount" not in b:
        return {"buy_ok": 1, "sell_ok": 0, "rt_pct": None, "impact_raw": imp, "route": route}
    return {"buy_ok": 1, "sell_ok": 1, "rt_pct": 100 * (1 - int(b["outAmount"]) / lam), "impact_raw": imp, "route": route}


def run_probes(db, now, http_json, sol_usd, max_n=12, sleep=0.3):
    """Probe launches that have a snapshot at a probe age but no probe yet."""
    rows = db.execute("""SELECT s.pool, s.age_target_min, l.mint FROM snaps s JOIN launches l ON l.pool=s.pool
                         WHERE s.missed=0 AND s.age_target_min IN (%s)""" % ",".join(str(a) for a in sorted(PROBE_AGES))).fetchall()
    n = 0
    for r in rows:
        for size in PROBE_SIZES_USD:
            if n >= max_n:
                break
            if db.execute("SELECT 1 FROM probes WHERE pool=? AND age_target_min=? AND size_usd=?", (r["pool"], r["age_target_min"], size)).fetchone():
                continue
            res = round_trip(http_json, r["mint"], size, sol_usd)
            db.execute("INSERT OR IGNORE INTO probes VALUES(?,?,?,?,?,?,?,?,?)", (r["pool"], r["age_target_min"], size, now, res["buy_ok"], res["sell_ok"], res["rt_pct"], res["impact_raw"], res["route"]))
            n += 1
            time.sleep(sleep)
    bump(db, "probes", n)
    db.commit()
    return n


# ---------------------------------------------------------------- safety (RugCheck full report)

def parse_safety(report):
    """Extract the safety fields from a RugCheck /report JSON. Top-holder shares exclude the pool's own token accounts."""
    r = report or {}
    markets = r.get("markets") or []
    lp_owners = set()
    for m in markets:
        for k in ("liquidityAAccount", "liquidityBAccount"):
            a = m.get(k)
            if isinstance(a, dict) and a.get("owner"):
                lp_owners.add(a["owner"])
    th = r.get("topHolders") or []
    ex = [h for h in th if h.get("owner") not in lp_owners]
    pct = lambda xs, n: round(sum(float(h.get("pct") or 0) for h in xs[:n]), 2)
    lp = [(m.get("lp") or {}).get("lpLockedPct") for m in markets if isinstance(m.get("lp"), dict)]
    lp = [x for x in lp if x is not None]
    ext = r.get("token_extensions") or {}
    active = sorted(k for k, v in ext.items() if v and k not in ("tokenMetadata", "metadataPointer"))
    tf = r.get("transferFee") or {}
    rc = classify.rugcheck_fields(r)
    return {"score": r.get("score_normalised") if r.get("score_normalised") is not None else r.get("score"), "rugged": int(bool(r.get("rugged"))),
            "launchpad": rc["launchpad_platform"], "jup_verified": int(bool(rc["jup_verified"])),
            "creator_pct": None if r.get("creatorBalance") is None else float(r["creatorBalance"]),
            "insiders_detected": int(r.get("graphInsidersDetected") or 0), "insider_networks": len(r.get("insiderNetworks") or []),
            "top1_pct_ex_lp": pct(ex, 1), "top10_pct_ex_lp": pct(ex, 10), "top10_pct_raw": pct(th, 10), "total_holders": r.get("totalHolders"),
            "lp_locked_pct": max(lp) if lp else None, "mint_authority": int(r.get("mintAuthority") is not None), "freeze_authority": int(r.get("freezeAuthority") is not None),
            "transfer_fee_pct": float(tf.get("pct") or 0), "extensions": json.dumps(active), "token_program": r.get("tokenProgram"),
            "risks": json.dumps([x.get("name") for x in r.get("risks", []) if isinstance(x, dict)])}


def run_safety(db, now, http_json, max_n=8, sleep=0.4):
    rows = db.execute("""SELECT pool, mint, dex, liq_at_detect, created_ts FROM launches WHERE status='observed' AND safety_done=0""").fetchall()
    n = 0
    for r in rows:
        if n >= max_n or (now - r["created_ts"]) / 60 < SAFETY_AGE_MIN:
            continue
        rep = http_json(RUGCHECK.format(mint=r["mint"]), retries=1)
        n += 1
        if not rep:
            db.execute("UPDATE launches SET safety_done=2 WHERE pool=?", (r["pool"],))          # tried, no data
            bump(db, "safety_failed")
            continue
        s = parse_safety(rep)
        db.execute("INSERT OR REPLACE INTO safety VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (r["pool"], now, s["score"], s["rugged"], s["launchpad"], s["jup_verified"], s["creator_pct"], s["insiders_detected"], s["insider_networks"],
                    s["top1_pct_ex_lp"], s["top10_pct_ex_lp"], s["top10_pct_raw"], s["total_holders"], s["lp_locked_pct"], s["mint_authority"],
                    s["freeze_authority"], s["transfer_fee_pct"], s["extensions"], s["token_program"], s["risks"]))
        cls, why = classify.classify(r["mint"], r["dex"], r["liq_at_detect"], {"launchpad_platform": s["launchpad"], "jup_verified": s["jup_verified"]})
        db.execute("UPDATE launches SET class=?, reason=?, launchpad=?, jup_verified=?, safety_done=1 WHERE pool=?", (cls, why, s["launchpad"], s["jup_verified"], r["pool"]))
        time.sleep(sleep)
    bump(db, "safety", n)
    db.commit()
    return n


# ---------------------------------------------------------------- orchestration

def sol_price(http_json):
    q = http_json(f"{JUP}?inputMint={SOL}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=10000000&slippageBps=50")
    try:
        return int(q["outAmount"]) / 1e6 / 0.01
    except (TypeError, KeyError, ValueError):
        return None


def cycle(db, now=None, gt_get=None, http_json=None, do_stream=True):
    import data
    now = now or time.time()
    gt_get = gt_get or data.gt_get
    http_json = http_json or bot.http_json
    st = {}
    if do_stream:
        st["stream"] = poll_stream(db, now, gt_get)
    st["snaps"] = take_snapshots(db, now, gt_get)
    px = sol_price(http_json)
    st["probes"] = run_probes(db, now, http_json, px) if px else 0
    st["safety"] = run_safety(db, now, http_json)
    return st


def run(db):
    log("graduation collector started (read-only, no keys)")
    next_stream = 0.0
    while True:
        try:
            now = time.time()
            st = cycle(db, now, do_stream=now >= next_stream)
            if now >= next_stream:
                next_stream = now + 120
            log(st)
        except Exception as e:
            log(f"launches cycle error: {e!r}")
        time.sleep(5)


def stats(db):
    n = lambda q, *a: db.execute(q, a).fetchone()[0]
    print("launches by status:", {r[0]: r[1] for r in db.execute("SELECT status, COUNT(*) FROM launches GROUP BY status")})
    print("observed by class:", {r[0]: r[1] for r in db.execute("SELECT class, COUNT(*) FROM launches WHERE status='observed' GROUP BY class")})
    r = db.execute("SELECT detect_delay_s FROM launches WHERE status='observed' ORDER BY detect_delay_s LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM launches WHERE status='observed')").fetchone()
    print("detection delay of observed launches, median seconds:", None if r is None else round(r[0]))
    print("snapshots taken:", n("SELECT COUNT(*) FROM snaps WHERE missed=0"), "| missed:", n("SELECT COUNT(*) FROM snaps WHERE missed=1"), "| gone:", n("SELECT COUNT(*) FROM snaps WHERE missed=2"))
    print("by age:", {r[0]: r[1] for r in db.execute("SELECT age_target_min, COUNT(*) FROM snaps WHERE missed=0 GROUP BY age_target_min ORDER BY age_target_min")})
    print("probes:", n("SELECT COUNT(*) FROM probes"), "| safety reports:", n("SELECT COUNT(*) FROM safety"), "| polls:", meta(db, "polls"), "| stream gaps:", meta(db, "stream_gaps"))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    d = connect()
    if cmd == "run":
        run(d)
    elif cmd == "stats":
        stats(d)
    else:
        print(cycle(d))
        stats(d)
