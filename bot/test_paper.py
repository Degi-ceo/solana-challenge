import tempfile
import unittest
from pathlib import Path

import bot
import launches as L
import paper as P
from test_eventstudy import add, new_db

NOW = 1_800_000_000.0


def gt_multi(prices, liq=50_000.0):
    """Fake GeckoTerminal multi-pool endpoint: prices = {pool: price or None (pool missing)}; liq may be a dict too."""
    def fn(path):
        wanted = path.split("/pools/multi/")[1].split(",")
        data = []
        for p in wanted:
            if prices.get(p) is None:
                continue
            lq = liq[p] if isinstance(liq, dict) else liq
            data.append({"attributes": {"address": p, "name": "X", "pool_created_at": "2026-01-01T00:00:00Z", "base_token_price_usd": str(prices[p]),
                                         "reserve_in_usd": str(lq), "transactions": {}, "volume_usd": {}, "price_change_percentage": {}}})
        return {"data": data}
    return fn


def quotes(rt_pct=1.0, sell_ok=True, buy_ok=True):
    lam = int(P.SIZE_USD / 75.0 * 1e9)

    def http(url, body=None, retries=2, timeout=15):
        if "outputMint=" + L.SOL in url and "inputMint=" + L.SOL not in url:
            return {"outAmount": str(int(lam * (1 - rt_pct / 100)))} if sell_ok else None
        return {"outAmount": "1000000", "priceImpactPct": "0", "routePlan": [{"swapInfo": {"label": "PumpSwap"}}]} if buy_ok else None
    return http


def candidate(db, i=1, now=NOW, snap_age_s=60, safety="clean", price=1.0, liq=50_000.0, mint=None):
    """A graduate whose 15-minute snapshot was taken snap_age_s seconds ago, with safety and a probe already stored."""
    created = now - 15 * 60 - snap_age_s
    add(db, i, created, safety=safety, exit_p=None, rt=1.0, mint=mint)
    db.execute("UPDATE snaps SET price=?, liq=?, ts=? WHERE pool=? AND age_target_min=15", (price, liq, now - snap_age_s, f"pool{i}"))
    db.commit()


class TestEntry(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self._kill = bot.KILL
        bot.KILL = Path(tempfile.mkdtemp()) / "KILL"          # not existing

    def tearDown(self):
        bot.KILL = self._kill

    def step(self, now=NOW, http=None, prices=None):
        return P.step(self.db, now, gt_multi(prices or {}), http or quotes(), 75.0)

    def test_opens_a_gated_fresh_candidate(self):
        candidate(self.db)
        st = self.step()
        self.assertEqual(st["opened"], 1)
        r = self.db.execute("SELECT * FROM paper_positions").fetchone()
        self.assertEqual((r["status"], r["size_usd"]), ("open", 2.5))
        self.assertAlmostEqual(r["rt_pct"], 1.0, places=1)
        self.assertEqual(self.step()["opened"], 0)                                 # one position per token

    def test_no_entry_on_stale_snapshot_or_failed_gates(self):
        candidate(self.db, 1, snap_age_s=P.STALE_S + 60)
        candidate(self.db, 2, safety="insider")
        candidate(self.db, 3, safety="concentrated")
        st = self.step()
        self.assertEqual(st["opened"], 0)
        self.assertEqual(st["skipped"].get("gate_fail"), 2)

    def test_fresh_sell_gate_failure_skips_and_is_recorded(self):
        candidate(self.db)
        st = self.step(http=quotes(rt_pct=9.0))
        self.assertEqual(st["opened"], 0)
        self.assertEqual(self.db.execute("SELECT status, reason FROM paper_positions").fetchone()[:], ("skipped", "sell_gate_fresh"))
        self.assertEqual(self.step(http=quotes(sell_ok=False))["opened"], 0)

    def test_max_two_open_positions(self):
        for i in (1, 2, 3):
            candidate(self.db, i)
        st = self.step()
        self.assertEqual(st["opened"], 2)
        self.assertEqual(st["skipped"].get("no_capacity"), 1)

    def test_kill_file_and_daily_loss_halt_entries(self):
        candidate(self.db)
        bot.KILL.write_text("x")
        self.assertEqual(self.step()["opened"], 0)
        bot.KILL.unlink()
        self.db.execute("INSERT INTO paper_positions(pool,mint,name,status,closed_ts,pnl_usd,size_usd) VALUES('x','mx','x','closed',?, -1.6, 2.5)", (NOW - 10,))
        st = self.step()
        self.assertEqual(st["opened"], 0)
        self.assertIn("daily loss", st["halt"])

    def test_safety_report_arriving_after_the_snapshot_is_usable_for_live_paper_trading(self):
        candidate(self.db)
        self.db.execute("UPDATE safety SET ts=? WHERE pool='pool1'", (NOW - 10,))        # report newer than the snapshot: known NOW, so allowed
        self.assertEqual(self.step()["opened"], 1)


class TestExits(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self._kill = bot.KILL
        bot.KILL = Path(tempfile.mkdtemp()) / "KILL"
        candidate(self.db)
        P.step(self.db, NOW, gt_multi({}), quotes(rt_pct=1.0), 75.0)                   # open at price 1.0
        self.pos = self.db.execute("SELECT * FROM paper_positions").fetchone()
        self.t = NOW

    def tearDown(self):
        bot.KILL = self._kill

    def poll(self, price, dt=P.POLL_S + 1, liq=50_000.0, http=None):
        self.t += dt
        P.step(self.db, self.t, gt_multi({"pool1": price}, liq=liq), http or quotes(rt_pct=1.0), 75.0)
        return self.db.execute("SELECT * FROM paper_positions WHERE pool='pool1'").fetchone()

    def test_stop_loss_pnl_math_uses_the_polled_price_not_the_stop_level(self):
        r = self.poll(0.70)                                                           # gapped through the -20% stop
        self.assertEqual((r["status"], r["reason"]), ("closed", "stop"))
        self.assertAlmostEqual(r["pnl_usd"], 2.5 * (0.70 - 1 - 0.01) - P.NET_FEE_USD, places=3)

    def test_no_take_profit_a_runner_stays_open_while_it_climbs(self):
        for px in (1.5, 2.0, 5.0, 10.0):
            r = self.poll(px)
            self.assertEqual(r["status"], "open", px)
        self.assertEqual(r["peak_px"], 10.0)

    def test_trailing_stop_captures_most_of_a_runner(self):
        self.poll(1.6)
        self.poll(6.0)
        r = self.poll(6.0 * 0.69)                                                     # 31% below the peak
        self.assertEqual((r["status"], r["reason"]), ("closed", "trail"))
        self.assertGreater(r["pnl_usd"], 2.5 * 3.0)                                   # more than +300% on the position

    def test_trailing_stop_is_not_armed_before_plus_50_percent(self):
        r = self.poll(1.3)
        r = self.poll(1.3 * 0.65)                                                     # -35% from a +30% peak: above the stop level (0.80)? 0.845 is
        self.assertEqual(r["status"], "open")

    def test_time_exit_after_48_hours(self):
        r = self.poll(1.05, dt=P.MAX_HOLD_S + 5)
        self.assertEqual((r["status"], r["reason"]), ("closed", "time"))

    def test_liquidity_collapse_exits(self):
        r = self.poll(1.0, liq=10_000.0)                                              # below half of the 50,000 at entry
        self.assertEqual((r["status"], r["reason"]), ("closed", "liq_drop"))

    def test_pool_vanishing_for_three_polls_is_minus_100(self):
        for _ in range(3):
            self.t += P.POLL_S + 1
            P.step(self.db, self.t, gt_multi({"pool1": None}), quotes(), 75.0)
        r = self.db.execute("SELECT * FROM paper_positions WHERE pool='pool1'").fetchone()
        self.assertEqual((r["status"], r["reason"], r["pnl_usd"]), ("closed", "gone_gone", -2.5))

    def test_unsellable_at_exit_is_minus_100(self):
        r = self.poll(0.7, http=quotes(sell_ok=False))
        self.assertEqual(r["pnl_usd"], -2.5)
        self.assertTrue(r["reason"].endswith("_unsellable"))

    def test_prices_are_polled_at_most_once_per_interval(self):
        calls = []
        def gt(path):
            calls.append(path)
            return gt_multi({"pool1": 1.0})(path)
        P.step(self.db, self.t + 5, gt, quotes(), 75.0)                  # the first look after opening happens at once
        self.assertEqual(len(calls), 1)
        P.step(self.db, self.t + 10, gt, quotes(), 75.0)
        P.step(self.db, self.t + 30, gt, quotes(), 75.0)
        self.assertEqual(len(calls), 1)                                  # then not again within the interval
        P.step(self.db, self.t + 5 + P.POLL_S + 1, gt, quotes(), 75.0)
        self.assertEqual(len(calls), 2)

    def test_loss_is_capped_at_the_position_size(self):
        r = self.poll(0.01)
        self.assertGreaterEqual(r["pnl_usd"], -2.5)


class TestSummary(unittest.TestCase):
    def test_summary_math_and_tail_dependence(self):
        db = new_db()
        for i, pnl in enumerate([-0.5, -0.5, -0.5, 6.0, -0.5]):
            db.execute("INSERT INTO paper_positions(pool,mint,name,status,closed_ts,pnl_usd,size_usd,reason) VALUES(?,?,?,?,?,?,?,?)", (f"p{i}", f"m{i}", "x", "closed", NOW + i, pnl, 2.5, "trail" if pnl > 0 else "stop"))
        s = P.summary(db)
        self.assertEqual(s["closed"], 5)
        self.assertAlmostEqual(s["net_pnl_usd"], 4.0)
        self.assertAlmostEqual(s["profit_factor"], 3.0)
        self.assertAlmostEqual(s["best_share_of_gains"], 1.0)                         # the whole gain came from one runner: stated, not hidden
        self.assertAlmostEqual(s["max_drawdown_usd"], 1.5)
        self.assertEqual(s["reasons"], {"stop": 4, "trail": 1})


if __name__ == "__main__":
    unittest.main()
