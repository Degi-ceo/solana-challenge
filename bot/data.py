#!/usr/bin/env python3
"""Historical market data from GeckoTerminal -> SQLite (data/market.db, gitignored).

  python3 data.py universe              # collect candidate Solana pools (tagged by source)
  python3 data.py candles --days 16     # download 5m OHLCV for the universe (resumable, rate-limited)
  python3 data.py stats                 # what is in the DB

BIAS WARNING (also printed by backtest.py): GeckoTerminal lists only pools that exist and have activity *today*.
Pools that rugged and were delisted/deadened are under-represented -> survivorship bias. `liq_now` is today's
reserve and must never be used as a historical value (look-ahead).
"""
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "data" / "market.db"
GT = "https://api.geckoterminal.com/api/v2/networks/solana"
MIN_INTERVAL_S = 5.0          # measured: ~5 back-to-back calls trigger 429; stay well under the limit
QUOTES = ("So11111111111111111111111111111111111111112",          # SOL
          "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",          # USDC
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB")         # USDT
_last = [0.0]


def log(msg):
    print(f"{time.strftime('%H:%M:%S', time.gmtime())}Z {msg}", flush=True)


def gt_get(path, retries=6):
    """Rate-limited GET with exponential backoff on 429/5xx. Returns parsed JSON or None."""
    url = path if path.startswith("http") else GT + path
    for i in range(retries):
        wait = MIN_INTERVAL_S - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "paper-trader-data/0.1"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(15 * 2 ** i)
                continue
            log(f"HTTP {e.code} {url[:100]}")
            return None
        except Exception as e:
            time.sleep(5 * (i + 1))
            err = e
    log(f"giving up {url[:100]}")
    return None


def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS pools(pool TEXT PRIMARY KEY, base_mint TEXT, name TEXT, dex TEXT, quote_mint TEXT,
      created_ts REAL, liq_now REAL, vol24_now REAL, sources TEXT, seen_ts REAL);
    CREATE TABLE IF NOT EXISTS candles(pool TEXT, ts INTEGER, o REAL, h REAL, l REAL, c REAL, v REAL,
      PRIMARY KEY(pool, ts)) WITHOUT ROWID;
    CREATE TABLE IF NOT EXISTS fetched(pool TEXT PRIMARY KEY, oldest_ts INTEGER, newest_ts INTEGER, n INT,
      complete INT, fetched_ts REAL);
    """)
    return db


def _iso(s):
    return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone


# ---------------------------------------------------------------- universe

LISTINGS = [  # (source tag, path template, pages)
    ("gt_top_volume", "/pools?sort=h24_volume_usd_desc&page={p}", range(1, 11)),
    ("gt_top_txcount", "/pools?sort=h24_tx_count_desc&page={p}", range(1, 11)),
    ("gt_trending_24h", "/trending_pools?duration=24h&page={p}", range(1, 4)),
    ("gt_trending_6h", "/trending_pools?duration=6h&page={p}", range(1, 3)),
] + [(f"gt_dex_{d}", "/dexes/" + d + "/pools?sort=h24_volume_usd_desc&page={p}", range(1, 9))
     for d in ("pumpswap", "raydium", "meteora", "raydium-clmm", "meteora-damm-v2", "meteora-dbc",
               "raydium-launchlab", "orca", "fluxbeam", "pump-fun", "moonshot", "humidifi")]


def collect_universe(db, min_age_d=2.0, max_age_d=40.0, min_liq=5_000):
    now = time.time()
    seen = {}
    for tag, tpl, pages in LISTINGS:
        got = 0
        for p in pages:
            j = gt_get(tpl.format(p=p))
            if not j or not j.get("data"):
                break
            for d in j["data"]:
                a, rel = d["attributes"], d["relationships"]
                try:
                    created = _iso(a["pool_created_at"])
                    base = rel["base_token"]["data"]["id"].split("_", 1)[1]
                    quote = rel["quote_token"]["data"]["id"].split("_", 1)[1]
                except (KeyError, TypeError, ValueError):
                    continue
                age_d = (now - created) / 86400
                liq = float(a.get("reserve_in_usd") or 0)
                if quote not in QUOTES or not min_age_d <= age_d <= max_age_d or liq < min_liq:
                    continue
                rec = seen.setdefault(a["address"], dict(
                    pool=a["address"], base_mint=base, name=a["name"], dex=rel["dex"]["data"]["id"], quote_mint=quote,
                    created_ts=created, liq_now=liq, vol24_now=float((a.get("volume_usd") or {}).get("h24") or 0),
                    sources=set()))
                rec["sources"].add(tag)
                got += 1
        log(f"{tag}: {got} usable pool rows; universe now {len(seen)}")
    for r in seen.values():
        db.execute("INSERT OR REPLACE INTO pools VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (r["pool"], r["base_mint"], r["name"], r["dex"], r["quote_mint"], r["created_ts"], r["liq_now"],
                    r["vol24_now"], json.dumps(sorted(r["sources"])), now))
    db.commit()
    log(f"universe stored: {len(seen)} pools")


# ---------------------------------------------------------------- candles

def download_candles(db, days, max_pools=None, max_liq_now=50_000_000):
    """5m candles back to `days` days ago (+1 day lookback for h24 features). Resumable per pool."""
    now = time.time()
    target = now - (days + 1) * 86400
    # skip blue-chips / implausible reserves (rule fixed before any backtest result); smallest-first would bias, so order by volume
    pools = db.execute("SELECT * FROM pools WHERE liq_now <= ? ORDER BY vol24_now DESC", (max_liq_now,)).fetchall()
    if max_pools:
        pools = pools[:max_pools]
    for i, pl in enumerate(pools, 1):
        done = db.execute("SELECT complete FROM fetched WHERE pool=?", (pl["pool"],)).fetchone()
        if done and done["complete"]:
            continue
        before, total = int(now) + 300, 0
        goal = max(target, pl["created_ts"] - 300)
        while True:
            j = gt_get(f"/pools/{pl['pool']}/ohlcv/minute?aggregate=5&limit=1000&before_timestamp={before}&currency=usd")
            if j is None:
                break
            lst = j["data"]["attributes"]["ohlcv_list"]
            if not lst:
                break
            db.executemany("INSERT OR IGNORE INTO candles VALUES(?,?,?,?,?,?,?)",
                           [(pl["pool"], int(t), o, h, l, c, v) for t, o, h, l, c, v in lst])
            total += len(lst)
            oldest = min(int(x[0]) for x in lst)
            if oldest <= goal or len(lst) < 1000:
                before = oldest
                break
            before = oldest
        else:
            pass
        ok = j is not None
        r = db.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM candles WHERE pool=?", (pl["pool"],)).fetchone()
        db.execute("INSERT OR REPLACE INTO fetched VALUES(?,?,?,?,?,?)",
                   (pl["pool"], r[0], r[1], r[2], int(ok), now))
        db.commit()
        log(f"[{i}/{len(pools)}] {pl['name']} {pl['pool'][:6]} +{total} candles (total {r[2]}) ok={ok}")


def stats(db):
    print("pools:", db.execute("SELECT COUNT(*) FROM pools").fetchone()[0],
          "| with candles:", db.execute("SELECT COUNT(*) FROM fetched WHERE complete=1").fetchone()[0],
          "| candles:", db.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
    for r in db.execute("SELECT dex, COUNT(*) n FROM pools GROUP BY dex ORDER BY n DESC LIMIT 8"):
        print("  dex", r["dex"], r["n"])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    db = connect()
    if cmd == "universe":
        collect_universe(db)
    elif cmd == "candles":
        d = float(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 16
        mp = int(sys.argv[sys.argv.index("--max-pools") + 1]) if "--max-pools" in sys.argv else None
        download_candles(db, d, mp)
    else:
        stats(db)
