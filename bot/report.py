#!/usr/bin/env python3
"""Generate REPORT.md from the collector database: data coverage, quality, sample progress and the pre-registered tests.

  python3 report.py [--db path] [--out REPORT.md] [--boot 10000]

Same frozen analysis code as bot/eventstudy.py. Negative and inconclusive results get the same space as positive ones.
"""
import sys
import time
from pathlib import Path

import eventstudy as E
import paper as PP
import random
import launches as L

CAVEATS = [
    "Observational data from public APIs; no trades were made. Quotes are not executed fills.",
    "Only pools listed by the data source are seen; detection delay is recorded per launch and the unit is the first observed pool per token.",
    "Prices come from GeckoTerminal; a second price from DexScreener is stored as a cross-check, never used in the primary tests.",
    "The analysis rules are in docs/PREREGISTRATION.md (amendments A1-A5). Anything not listed there is exploratory.",
    "Weeks with no collector running are gaps, recorded and never filled.",
]


def iso(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) + " UTC"


def gaps(db, min_gap_s=900):
    ts = [r[0] for r in db.execute("SELECT detected_ts FROM launches ORDER BY detected_ts")]
    out = [(a, b) for a, b in zip(ts, ts[1:]) if b - a > min_gap_s]
    return out, (sum(b - a for a, b in out) / 3600 if out else 0.0)


def build(db, boot=10_000):
    one = lambda q, *a: db.execute(q, a).fetchone()[0]
    L_status = {r[0]: r[1] for r in db.execute("SELECT status, COUNT(*) FROM launches GROUP BY status")}
    L_class = {r[0]: r[1] for r in db.execute("SELECT class, COUNT(*) FROM launches WHERE status='observed' GROUP BY class")}
    first, last = one("SELECT MIN(detected_ts) FROM launches"), one("SELECT MAX(detected_ts) FROM launches")
    span_h = (last - first) / 3600 if first and last else 0
    gl, gap_h = gaps(db)
    delays = sorted(r[0] for r in db.execute("SELECT detect_delay_s FROM launches WHERE status='observed'"))
    res = E.evaluate(db, boot)
    lines = [f"# Event-study report", "", f"Generated {iso(time.time())}. Data from {iso(first) if first else 'n/a'} to {iso(last) if last else 'n/a'} ({span_h:.1f} h).", ""]
    lines += ["## Data coverage", "",
              f"- Launches by status: {L_status or 'none'}", f"- Observed by class: {L_class or 'none'}",
              f"- Detection delay (observed): median {delays[len(delays)//2]:.0f} s, p90 {delays[int(.9*len(delays))]:.0f} s" if delays else "- Detection delay: no data",
              f"- Snapshots taken: {one('SELECT COUNT(*) FROM snaps WHERE missed=0')}, missed (collector not running or late): {one('SELECT COUNT(*) FROM snaps WHERE missed=1')}, pool gone: {one('SELECT COUNT(*) FROM snaps WHERE missed=2')}",
              f"- Cost probes: {one('SELECT COUNT(*) FROM probes')}; safety reports: {one('SELECT COUNT(*) FROM safety')}",
              f"- Stream polls: {L.meta(db, 'polls'):.0f}; polls without overlap (possible missed pools): {L.meta(db, 'stream_gaps'):.0f}",
              f"- Quiet periods over 15 minutes: {len(gl)} totalling {gap_h:.1f} h" + (" (" + ", ".join(f"{iso(a)} to {iso(b)}" for a, b in gl[:5]) + (" ..." if len(gl) > 5 else "") + ")" if gl else ""), ""]
    rb = res["robustness"]["snapshots"]
    lines += ["## Price-source cross-check", "",
              (f"- {rb['with_both_sources']} snapshots carry both prices; {100 * rb['share_disagreeing_over_10pct']:.1f}% disagree by more than 10%." if rb["with_both_sources"] else "- No snapshot carries a second price yet."), ""]
    lines += [f"## Pre-registered tests (population: {res['population']} memecoin graduates, weeks: {', '.join(res['weeks']) or 'none'})", "",
              "| id | claim | sample | needed | result |", "|---|---|---|---|---|"]
    for h, t in res["overall"].items():
        n = t.get("n", t.get("n_flagged", 0) + t.get("n_clean", 0) if "n_flagged" in t else t.get("n_pass", 0) + t.get("n_fail", 0))
        extra = f" (p = {t['p']:.3f}, Holm {t['p_holm']:.3f})" if t.get("p") is not None else ""
        lines.append(f"| {h} | {t['claim']} | {n} | {t['min_n']} | {t['verdict']}{extra} |")
    lines += ["", f"Go to paper trading (needs two separate passing weeks): **{res['go']}**", ""]
    for h, t in res["overall"].items():
        for k in ("desc", "desc_baseline", "desc_flagged", "desc_clean", "desc_pass", "desc_fail"):
            d = t.get(k)
            if d and d.get("n"):
                lines.append(f"- {h} {k}: n={d['n']}, median {100*d['median']:+.1f}%, trimmed mean {100*d['trimmed_mean']:+.1f}%, share <= -50%: {100*d['share_le_minus50']:.0f}%")
    lines += ["", "Results below the pre-registered minimum sample are descriptive only and say nothing about the claims.", ""]
    ps = PP.summary(db)
    lines += ["## Paper trading, rule set R1 (H7, forward, exploratory)", "",
              f"- Bankroll $5.00 -> equity ${ps['equity_usd']:.2f} (net {ps['net_pnl_usd']:+.2f} USD); closed trades {ps['closed']}, open {ps['open']}, skipped at the fresh sell gate {ps['skipped_fresh_gate']}."]
    if ps["closed"]:
        pn = [r_[0] for r_ in db.execute("SELECT pnl_usd FROM paper_positions WHERE status='closed'")]
        rng = random.Random(7)
        means = sorted(sum(pn[rng.randrange(len(pn))] for _ in pn) / len(pn) for _ in range(2000))
        lo, hi = means[50], means[1949]
        verdict = ("not enough trades (fewer than 30): no statement about an edge" if ps["closed"] < 30 else
                   ("the 95% interval of the mean per trade is above zero" if lo > 0 else "the 95% interval of the mean per trade includes zero or is below it"))
        lines += [f"- Win rate {100*ps['win_rate']:.0f}%, mean {ps['mean_usd']:+.3f} USD per trade (95% bootstrap interval {lo:+.3f} to {hi:+.3f}), median {ps['median_usd']:+.3f}, best trade {ps['best_usd']:+.2f} USD"
                  + (f" ({100*ps['best_share_of_gains']:.0f}% of all gains)" if ps.get("best_share_of_gains") else "") + f", max drawdown {ps['max_drawdown_usd']:.2f} USD.",
                  f"- Exit reasons: {ps['reasons']}. Evidence level: {verdict}."]
        for row in db.execute("SELECT name, opened_ts, closed_ts, reason, pnl_usd FROM paper_positions WHERE status='closed' ORDER BY closed_ts DESC LIMIT 15"):
            lines.append(f"  - {row['name']}: {row['reason']}, {row['pnl_usd']:+.3f} USD, held {(row['closed_ts']-row['opened_ts'])/3600:.1f} h")
    else:
        lines.append("- No closed paper trades yet.")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in CAVEATS] + [""]
    return "\n".join(lines)


if __name__ == "__main__":
    a = sys.argv
    db = L.connect(a[a.index("--db") + 1]) if "--db" in a else L.connect()
    text = build(db, int(a[a.index("--boot") + 1]) if "--boot" in a else 10_000)
    out = Path(a[a.index("--out") + 1]) if "--out" in a else Path("REPORT.md")
    out.write_text(text)
    print(text)
