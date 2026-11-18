#!/usr/bin/env python3
"""Forward event study exactly as pre-registered in docs/PREREGISTRATION.md (amendments A1-A4). Read-only.

  python3 eventstudy.py [--boot 10000] [--json out.json]

Unit: first observed pool per token mint, analysis population = memecoin_confirmed + memecoin_probable.
Every launch outcome is derived only from stored snapshots / probes / safety reports; nothing is imputed.
Below the minimum sample a test reports 'inconclusive' (never 'no effect'). 'go' requires two separate weeks that each pass after Holm correction.
"""
import datetime
import json
import random
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SIZE_USD = 2.5
NET_FEE_RT_USD = 0.02
SELL_GATE_PCT = 3.0
PROBE_LAG_S = 120
MIN_N = 300
MIN_GROUP = 100
POP = ("memecoin_confirmed", "memecoin_probable")
CELLS = {"H1": (1440, 2880), "H2": (15, 360), "H3": (15, 360), "H4": (15, 360), "H5": (360, 1440)}
BAD_EXT = {"transferFeeConfig", "transferHook", "permanentDelegate"}


# ---------------------------------------------------------------- data access

def population(db):
    """First observed pool per mint, memecoin classes only."""
    rows = db.execute("""SELECT l.* FROM launches l WHERE l.status='observed' AND l.class IN (?,?)
                         AND l.created_ts = (SELECT MIN(x.created_ts) FROM launches x WHERE x.mint=l.mint AND x.status='observed')
                         GROUP BY l.mint""", POP).fetchall()
    out = []
    for r in rows:
        snaps = {s["age_target_min"]: dict(s) for s in db.execute("SELECT * FROM snaps WHERE pool=?", (r["pool"],))}
        probes = {(p["age_target_min"], p["size_usd"]): dict(p) for p in db.execute("SELECT * FROM probes WHERE pool=?", (r["pool"],))}
        sf = db.execute("SELECT * FROM safety WHERE pool=?", (r["pool"],)).fetchone()
        out.append({"pool": r["pool"], "mint": r["mint"], "created_ts": r["created_ts"], "snaps": snaps, "probes": probes, "safety": dict(sf) if sf else None})
    return out


def iso_week(ts):
    y, w, _ = datetime.datetime.utcfromtimestamp(ts).isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------- one launch -> one outcome for a cell

def outcome(rec, a, b):
    """Return (status, value, info). status in: ok, not_enterable, no_probe, no_entry, incomplete."""
    e = rec["snaps"].get(a)
    if not e or e["missed"] != 0 or not e["price"] or e["price"] <= 0:
        return "no_entry", None, {}
    cand = [(age, p) for (age, size), p in rec["probes"].items() if size == SIZE_USD and age <= a and p["ts"] <= e["ts"] + PROBE_LAG_S]
    if not cand:
        return "no_probe", None, {}
    pa, pr = max(cand, key=lambda x: x[0])
    if not pr["buy_ok"] or not pr["sell_ok"] or pr["rt_pct"] is None:
        return "not_enterable", None, {}
    x = rec["snaps"].get(b)
    if x is None or x["missed"] == 1:
        return "incomplete", None, {}
    rt, info = pr["rt_pct"], {"rt_pct": pr["rt_pct"]}
    exit_probe = [p for (age, size), p in rec["probes"].items() if size == SIZE_USD and age == b]
    unsellable = x["missed"] == 2 or (x["liq"] is not None and x["liq"] < 500) or any(p["buy_ok"] and not p["sell_ok"] for p in exit_probe)
    info["unsellable"] = bool(unsellable)
    if unsellable:
        return "ok", -1.0, info
    gross = x["price"] / e["price"] - 1
    return "ok", gross - rt / 100 - NET_FEE_RT_USD / SIZE_USD, info


def gates(rec, a):
    """Safety gates at entry age a. Returns dict or None if the safety report is unavailable at entry time (no look-ahead)."""
    e, s = rec["snaps"].get(a), rec["safety"]
    if not s or not e or s["ts"] > e["ts"]:
        return None
    ext = set(json.loads(s["extensions"] or "[]"))
    insider_flag = bool(s["insiders_detected"]) or (s["top10_pct_ex_lp"] or 0) > 40
    cand = [(age, p) for (age, size), p in rec["probes"].items() if size == SIZE_USD and age <= a]
    rt = max(cand, key=lambda x: x[0])[1]["rt_pct"] if cand else None
    return {"insider_flag": insider_flag, "authorities_ok": not (s["mint_authority"] or s["freeze_authority"]), "ext_ok": not (ext & BAD_EXT),
            "sell_ok": rt is not None and rt <= SELL_GATE_PCT, "all_ok": (not insider_flag) and not (s["mint_authority"] or s["freeze_authority"])
            and not (ext & BAD_EXT) and rt is not None and rt <= SELL_GATE_PCT}


def collect(pop, a, b):
    rows, counts = [], {"ok": 0, "not_enterable": 0, "no_probe": 0, "no_entry": 0, "incomplete": 0}
    for rec in pop:
        st, v, info = outcome(rec, a, b)
        counts[st] += 1
        if st == "ok":
            rows.append({"rec": rec, "ret": v, "unsellable": info["unsellable"], "gate": gates(rec, a), "week": iso_week(rec["created_ts"])})
    return rows, counts


# ---------------------------------------------------------------- statistics

def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def trimmed_mean(xs, cut=0.10):
    s = sorted(xs)
    k = int(len(s) * cut)
    s = s[k:len(s) - k] or s
    return sum(s) / len(s)


def describe(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "median": median(xs), "trimmed_mean": trimmed_mean(xs), "share_le_minus50": sum(x <= -0.5 for x in xs) / len(xs)}


def boot(stat, xs, B, rng):
    n = len(xs)
    return [stat([xs[rng.randrange(n)] for _ in range(n)]) for _ in range(B)]


def p_median_vs_zero(xs, sign, B, rng):
    """One-sided bootstrap p. sign=+1 tests median > 0 (p = P(boot median <= 0)); sign=-1 tests median < 0 (p = P(boot median >= 0))."""
    m = boot(median, xs, B, rng)
    return sum(v <= 0 for v in m) / B if sign > 0 else sum(v >= 0 for v in m) / B


def p_median_above_baseline(xs, base, B, rng):
    d = [median([xs[rng.randrange(len(xs))] for _ in xs]) - median([base[rng.randrange(len(base))] for _ in base]) for _ in range(B)]
    return sum(v <= 0 for v in d) / B


def p_prop_greater(flags_a, flags_b, B, rng):
    """H: share(A) > share(B). p = P(boot diff <= 0)."""
    na, nb = len(flags_a), len(flags_b)
    d = [sum(flags_a[rng.randrange(na)] for _ in range(na)) / na - sum(flags_b[rng.randrange(nb)] for _ in range(nb)) / nb for _ in range(B)]
    return sum(v <= 0 for v in d) / B


def holm(pvals, alpha=0.05):
    """pvals {id: p or None}. Returns {id: (adjusted_p, reject)} over the tests that have a p-value."""
    items = sorted(((k, v) for k, v in pvals.items() if v is not None), key=lambda kv: kv[1])
    m, out, running = len(items), {}, 0.0
    for i, (k, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[k] = (running, running < alpha)
    return out


# ---------------------------------------------------------------- the five tests (H6 needs candles)

def run_tests(pop, B=10_000, seed=1):
    rng = random.Random(seed)
    res = {}
    # H1
    rows, counts = collect(pop, *CELLS["H1"])
    xs = [r["ret"] for r in rows]
    res["H1"] = {"claim": "median net return of buying at 24 h (exit 48 h) is negative", "n": len(xs), "counts": counts, "desc": describe(xs),
                 "p": p_median_vs_zero(xs, -1, B, rng) if len(xs) >= MIN_N else None, "min_n": MIN_N}
    # H2
    rows, counts = collect(pop, *CELLS["H2"])
    allx = [r["ret"] for r in rows]
    gx = [r["ret"] for r in rows if r["gate"] and r["gate"]["all_ok"]]
    ok_n = len(gx) >= MIN_N and len(allx) >= MIN_N
    p2 = None
    if ok_n:
        p2 = max(p_median_vs_zero(gx, +1, B, rng), p_median_above_baseline(gx, allx, B, rng))
    res["H2"] = {"claim": "gated entry at 15 min (exit 6 h) has positive median and beats the unconditional set", "n": len(gx), "n_baseline": len(allx), "counts": counts,
                 "gate_unknown": sum(1 for r in rows if r["gate"] is None), "desc": describe(gx), "desc_baseline": describe(allx), "p": p2, "min_n": MIN_N}
    # H3 and H4 share the cell
    known = [r for r in rows if r["gate"] is not None]
    hi = [r for r in known if r["gate"]["insider_flag"]]
    lo = [r for r in known if not r["gate"]["insider_flag"]]
    ok3 = len(hi) + len(lo) >= MIN_N and min(len(hi), len(lo)) >= MIN_GROUP
    res["H3"] = {"claim": "insider-flagged launches have a higher share of net returns <= -50%", "n_flagged": len(hi), "n_clean": len(lo),
                 "desc_flagged": describe([r["ret"] for r in hi]), "desc_clean": describe([r["ret"] for r in lo]),
                 "p": p_prop_greater([r["ret"] <= -0.5 for r in hi], [r["ret"] <= -0.5 for r in lo], B, rng) if ok3 else None, "min_n": MIN_N}
    sellable = [r for r in known if r["gate"]["sell_ok"]]
    notsell = [r for r in known if not r["gate"]["sell_ok"]]
    ok4 = len(sellable) + len(notsell) >= MIN_N and min(len(sellable), len(notsell)) >= MIN_GROUP
    res["H4"] = {"claim": "launches failing the sell gate have a higher share of un-sellable outcomes", "n_pass": len(sellable), "n_fail": len(notsell),
                 "unsellable_pass": sum(r["unsellable"] for r in sellable) / len(sellable) if sellable else None,
                 "unsellable_fail": sum(r["unsellable"] for r in notsell) / len(notsell) if notsell else None,
                 "desc_pass": describe([r["ret"] for r in sellable]), "desc_fail": describe([r["ret"] for r in notsell]),
                 "p": p_prop_greater([r["unsellable"] for r in notsell], [r["unsellable"] for r in sellable], B, rng) if ok4 else None, "min_n": MIN_N}
    # H5
    rows5, counts5 = collect(pop, *CELLS["H5"])
    allx5 = [r["ret"] for r in rows5]
    sub = []
    for r in rows5:
        sn = r["rec"]["snaps"]
        peak = max([v["price"] for age, v in sn.items() if age <= 360 and v["missed"] == 0 and v["price"]] or [0])
        p6 = sn[360]["price"]
        if peak > 0 and 0.30 <= p6 / peak <= 0.50:
            sub.append(r["ret"])
    p5 = None
    if len(sub) >= MIN_N and len(allx5) >= MIN_N:
        p5 = max(p_median_vs_zero(sub, +1, B, rng), p_median_above_baseline(sub, allx5, B, rng))
    res["H5"] = {"claim": "entry at 6 h after a 50-70% fall from the early peak has a positive median (exit 24 h)", "n": len(sub), "n_baseline": len(allx5), "counts": counts5,
                 "desc": describe(sub), "desc_baseline": describe(allx5), "p": p5, "min_n": MIN_N}
    adj = holm({k: v["p"] for k, v in res.items()})
    for k, v in res.items():
        if v["p"] is None:
            v["verdict"] = "inconclusive (sample below the pre-registered minimum)"
        else:
            v["p_holm"], v["pass"] = adj[k]
            v["verdict"] = "passes" if v["pass"] else "does not pass"
    return res


def evaluate(db, B=10_000, seed=1):
    pop = population(db)
    overall = run_tests(pop, B, seed)
    weeks = sorted({iso_week(r["created_ts"]) for r in pop})
    per_week = {w: run_tests([r for r in pop if iso_week(r["created_ts"]) == w], B, seed) for w in weeks}
    go = {}
    for h in overall:
        passing = [w for w, t in per_week.items() if t[h].get("pass")]
        go[h] = len(passing) >= 2
    return {"population": len(pop), "weeks": weeks, "overall": overall, "per_week": per_week, "go": go,
            "note": "'go' (to paper trading) needs two separate weeks that each pass after Holm correction; H1 is a 'do not chase' result, not a trading rule."}


def report(result):
    print(f"Population: {result['population']} memecoin graduates (first pool per mint); weeks: {', '.join(result['weeks']) or 'none'}")
    for h, t in result["overall"].items():
        extra = f" | p={t['p']:.3f} holm={t.get('p_holm', float('nan')):.3f}" if t["p"] is not None else ""
        n = t.get("n", t.get("n_flagged", t.get("n_pass", 0)))
        print(f"  {h}: n={n} -> {t['verdict']}{extra}")
        for k in ("desc", "desc_baseline", "desc_flagged", "desc_clean", "desc_pass", "desc_fail"):
            if k in t and t[k].get("n"):
                d = t[k]
                print(f"       {k}: n={d['n']} median={100*d['median']:+.1f}% trimmed mean={100*d['trimmed_mean']:+.1f}% share<=-50%={100*d['share_le_minus50']:.0f}%")
    print("go to paper trading:", result["go"])


if __name__ == "__main__":
    B = int(sys.argv[sys.argv.index("--boot") + 1]) if "--boot" in sys.argv else 10_000
    import launches
    res = evaluate(launches.connect(), B)
    report(res)
    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(json.dumps(res, default=str))
