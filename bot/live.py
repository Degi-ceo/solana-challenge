#!/usr/bin/env python3
"""Live engine: the SAME signals as the paper engine (bot/paper.py, rule set R1) executed through bot/executor.py.

  python3 live.py check      # preflight: prints every condition and whether real trading would be allowed. Sends nothing.
  python3 live.py positions  # live positions and results from the local database

  LIVE_ENGINE=dry  python3 launches.py run    # collector + engine that quotes, builds, validates and SIMULATES swaps; sends nothing, needs only BURNER_PUBKEY
  LIVE_ENGINE=live python3 launches.py run    # collector + REAL transactions, only if every guard in executor.py allows it (see docs/LIVE.md)

Never run from the web sandbox: the executor refuses there. Paper trading keeps running next to it, so real and paper fills can be compared.
"""
import json
import os
import sys
import time

import bot
import executor as X
import paper as P


def build_engine(mode, cfg=None):
    cfg = cfg or bot.load_cfg()
    guard = X.Guard(cfg)
    if mode == "live":
        guard.assert_live()                                           # refuse to even start if live is not allowed
        kp = X.load_keypair(os.environ["BURNER_KEYPAIR_PATH"])
        ex = X.Executor(cfg, guard, keypair=kp)
    else:
        pub = os.environ.get("BURNER_PUBKEY")
        if not pub:
            raise X.Refused("dry mode needs BURNER_PUBKEY (a public address only)")
        ex = X.Executor(cfg, guard, pubkey=pub)
    return Engine(cfg, ex, live=(mode == "live"))


class Engine:
    def __init__(self, cfg, executor, live):
        self.cfg, self.ex, self.live = cfg, executor, live
        self.limits = executor.guard.limits

    # -- helpers
    def daily_pnl(self, db, now):
        day0 = now - now % 86400
        return db.execute("SELECT COALESCE(SUM(pnl_usd),0) FROM live_positions WHERE status='closed' AND closed_ts>=?", (day0,)).fetchone()[0]

    def n_open(self, db):
        return db.execute("SELECT COUNT(*) FROM live_positions WHERE status='open'").fetchone()[0]

    # -- one step
    def step(self, db, now, gt_get, http_json, sol_usd):
        st = {"opened": 0, "closed": 0, "dry_ok": 0, "refused": {}, "mode": "live" if self.live else "dry"}
        if self.live:
            self.manage(db, now, gt_get, sol_usd, st)
        self.enter(db, now, sol_usd, st)
        db.commit()
        return st

    def enter(self, db, now, sol_usd, st):
        size = min(P.SIZE_USD, self.limits["position_usd"])
        for r in P.eligible(db, now, {"skipped": {}}, taken_table="live_positions"):
            try:
                out = self.ex.buy(r["mint"], size, sol_usd, self.n_open(db), self.daily_pnl(db, now), live=self.live)
            except X.Refused as e:
                key = str(e)[:60]
                st["refused"][key] = st["refused"].get(key, 0) + 1
                continue
            except Exception as e:                                     # network or chain problems: log, never crash the collector
                bot.log(f"LIVE buy error {r['name']}: {e!r}")
                st["refused"]["error"] = st["refused"].get("error", 0) + 1
                continue
            if not self.live:
                st["dry_ok"] += 1
                bot.log(f"LIVE-DRY would buy {r['name']} ${size:.2f}: route validated and simulated, nothing sent")
                db.execute("INSERT INTO live_positions(pool,mint,name,opened_ts,entry_px,entry_liq,size_usd,status,reason) VALUES(?,?,?,?,?,?,?,'dry',?)",
                           (r["pool"], r["mint"], r["name"], now, r["snap_px"], r["snap_liq"], size, "dry_run_ok"))
                continue
            db.execute("""INSERT INTO live_positions(pool,mint,name,opened_ts,entry_px,entry_liq,size_usd,lamports_spent,tokens_raw,sig_buy,peak_px,last_px,last_ts,status,sol_usd)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'open',?)""",
                       (r["pool"], r["mint"], r["name"], now, r["snap_px"], r["snap_liq"], size, out["lamports_spent"], out["tokens_raw"], out["signature"],
                        r["snap_px"], r["snap_px"], now, sol_usd))
            bot.log(f"LIVE OPEN {r['name']} spent {out['lamports_spent'] / 1e9:.5f} SOL, tokens {out['tokens_raw']}, sig {out['signature']}")
            st["opened"] += 1

    def manage(self, db, now, gt_get, sol_usd, st):
        import launches as L
        opens = db.execute("SELECT * FROM live_positions WHERE status='open'").fetchall()
        if not opens or now - L.meta(db, "live_last_poll", 0.0) < P.POLL_S:
            return
        L.set_meta(db, "live_last_poll", now)
        data = L.parse_multi(gt_get("/pools/multi/" + ",".join(p["pool"] for p in opens)))
        for p in opens:
            m = data.get(p["pool"])
            if m is None or not m.get("price"):
                misses = p["misses"] + 1
                db.execute("UPDATE live_positions SET misses=? WHERE id=?", (misses, p["id"]))
                if misses < P.GONE_POLLS:
                    continue
                reason, px = "gone", p["last_px"] or p["entry_px"]
            else:
                px, liq = m["price"], m["liq"]
                pos = dict(p, peak_px=max(p["peak_px"] or p["entry_px"], px))
                db.execute("UPDATE live_positions SET peak_px=?, last_px=?, last_ts=?, misses=0 WHERE id=?", (pos["peak_px"], px, now, p["id"]))
                reason = P.exit_reason(pos, px, liq, now)
                if not reason:
                    continue
            self.close(db, p, now, px, reason, sol_usd, st)

    def close(self, db, p, now, px, reason, sol_usd, st):
        try:
            out = self.ex.sell(p["mint"], p["tokens_raw"], live=True)
            received = out["lamports_received"]
        except Exception as e:                                         # cannot sell: keep the position open, try again next poll, say so loudly
            bot.log(f"LIVE SELL FAILED {p['name']} ({reason}): {e!r}")
            st["refused"]["sell_failed"] = st["refused"].get("sell_failed", 0) + 1
            return
        pnl = (received - p["lamports_spent"]) / 1e9 * sol_usd
        db.execute("UPDATE live_positions SET status='closed', closed_ts=?, exit_px=?, reason=?, sig_sell=?, lamports_received=?, pnl_usd=? WHERE id=?",
                   (now, px, reason, out["signature"], received, pnl, p["id"]))
        bot.log(f"LIVE CLOSE {p['name']} {reason} pnl=${pnl:+.3f}")
        st["closed"] += 1


def check(cfg=None, env=None):
    """Print the preflight list. Returns True only if real trading would be allowed right now. Sends nothing."""
    cfg = cfg or bot.load_cfg()
    env = os.environ if env is None else env
    g = X.Guard(cfg, env=env)
    rows = [("config live flag", bool(cfg.get("live", False)), 'set "live": true in config.json'),
            ("CONFIRM_LIVE", env.get("CONFIRM_LIVE") == X.CONFIRM_VALUE, f"export CONFIRM_LIVE={X.CONFIRM_VALUE}"),
            ("not an agent sandbox", not X.in_agent_sandbox(), "run this on your own machine"),
            ("BURNER_KEYPAIR_PATH set", bool(env.get("BURNER_KEYPAIR_PATH")), "export BURNER_KEYPAIR_PATH=/path/outside/repo/burner.json (chmod 600)")]
    pub = env.get("BURNER_PUBKEY")
    ok_key = False
    if env.get("BURNER_KEYPAIR_PATH"):
        try:
            kp = X.load_keypair(env["BURNER_KEYPAIR_PATH"])
            ok_key, pub = True, str(kp.pubkey())
        except Exception as e:
            rows.append(("keypair file", False, str(e)))
    rows.append(("keypair file loads safely", ok_key, "owner-only permissions, outside the repository, Solana CLI format"))
    try:
        rpc = X.Rpc()
        bal = rpc.balance_lamports(pub) if pub else None
        rows.append(("RPC reachable", True, X.Rpc().url.split("?")[0]))
        if bal is not None:
            import launches as L
            usd = bal / 1e9 * (L.sol_price(bot.http_json) or 0)
            rows.append((f"wallet {pub[:6]}... holds ${usd:.2f}", usd <= g.limits["wallet_usd"], f"must be at most ${g.limits['wallet_usd']:.0f}: use a dedicated burner"))
    except Exception as e:
        rows.append(("RPC reachable", False, repr(e)[:100]))
    rows.append(("KILL file absent", not bot.KILL.exists(), "delete the KILL file to allow entries"))
    for name, ok, hint in rows:
        print(f"  [{'ok' if ok else '--'}] {name}" + ("" if ok else f"   -> {hint}"))
    print("limits in force:", g.limits)
    allowed = not g.why_not_live() and ok_key
    print("REAL TRADING WOULD BE ALLOWED" if allowed else "NOT LIVE (dry mode only):", "; ".join(g.why_not_live()) or ("keypair problem" if not ok_key else ""))
    return allowed


def positions():
    import launches as L
    db = L.connect()
    for r in db.execute("SELECT * FROM live_positions ORDER BY opened_ts DESC LIMIT 30"):
        print(f"{r['status']:<7} {r['name']:<14} {r['reason'] or '':<14} pnl {r['pnl_usd'] if r['pnl_usd'] is not None else '-'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "check":
        sys.exit(0 if check() else 1)
    elif cmd == "positions":
        positions()
    else:
        sys.exit(__doc__)
