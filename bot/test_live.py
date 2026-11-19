import os
import tempfile
import unittest
from pathlib import Path

import bot
import executor as X
import launches as L
import live
import paper as P
from test_eventstudy import new_db
from test_paper import NOW, candidate, gt_multi, quotes


class FakeExecutor:
    """Stands in for executor.Executor: records calls, applies the same cap on open positions the real Guard applies."""
    def __init__(self, fail_buy=None, fail_sell=False, max_open=2):
        self.guard = type("G", (), {"limits": dict(X.CAPS, position_usd=2.5, max_open=max_open)})()
        self.buys, self.sells, self.fail_buy, self.fail_sell = [], [], fail_buy, fail_sell

    def buy(self, mint, size_usd, sol_usd, n_open, daily_pnl_usd, live):
        if self.fail_buy:
            raise self.fail_buy
        if n_open >= self.guard.limits["max_open"]:
            raise X.Refused("already open positions")
        self.buys.append((mint, size_usd, live))
        return {"mode": "live" if live else "dry", "signature": "SIGBUY", "lamports_spent": 34_000_000, "tokens_raw": 1000} if live else {"mode": "dry"}

    def sell(self, mint, amount_raw, live):
        if self.fail_sell:
            raise RuntimeError("route gone")
        self.sells.append((mint, amount_raw, live))
        return {"mode": "live", "signature": "SIGSELL", "lamports_received": 40_000_000}


class Base(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        self._kill = bot.KILL
        bot.KILL = Path(tempfile.mkdtemp()) / "KILL"

    def tearDown(self):
        bot.KILL = self._kill

    def engine(self, live_mode, **kw):
        self.ex = FakeExecutor(**kw)
        return live.Engine({}, self.ex, live=live_mode)

    def step(self, eng, now=NOW, prices=None):
        return eng.step(self.db, now, gt_multi(prices or {}), quotes(), 75.0)


class TestDry(Base):
    def test_dry_mode_never_opens_a_live_position_and_never_sells(self):
        candidate(self.db)
        eng = self.engine(False)
        st = self.step(eng)
        self.assertEqual((st["dry_ok"], st["opened"]), (1, 0))
        self.assertEqual(self.ex.buys, [("mint1", 2.5, False)])                           # called with live=False
        self.assertEqual(self.ex.sells, [])
        self.assertEqual(self.db.execute("SELECT status FROM live_positions").fetchone()[0], "dry")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM live_positions WHERE status='open'").fetchone()[0], 0)

    def test_refusals_are_counted_not_raised(self):
        candidate(self.db)
        eng = self.engine(False, fail_buy=X.Refused("route validated badly"))
        st = self.step(eng)
        self.assertEqual(st["dry_ok"], 0)
        self.assertEqual(sum(st["refused"].values()), 1)

    def test_network_errors_do_not_crash_the_loop(self):
        candidate(self.db)
        st = self.step(self.engine(True, fail_buy=RuntimeError("rpc down")))
        self.assertEqual(st["refused"], {"error": 1})


class TestLive(Base):
    def test_live_buy_records_the_real_fill_and_only_once_per_token(self):
        candidate(self.db)
        eng = self.engine(True)
        self.assertEqual(self.step(eng)["opened"], 1)
        r = self.db.execute("SELECT * FROM live_positions").fetchone()
        self.assertEqual((r["status"], r["lamports_spent"], r["tokens_raw"], r["sig_buy"]), ("open", 34_000_000, 1000, "SIGBUY"))
        self.assertEqual(self.step(eng, now=NOW + 5)["opened"], 0)

    def test_open_position_cap_is_enforced_by_the_guard_path(self):
        for i in (1, 2, 3):
            candidate(self.db, i)
        st = self.step(self.engine(True, max_open=2))
        self.assertEqual(st["opened"], 2)
        self.assertEqual(sum(st["refused"].values()), 1)

    def test_stop_sells_everything_and_pnl_comes_from_the_real_lamports(self):
        candidate(self.db)
        eng = self.engine(True)
        self.step(eng)
        st = self.step(eng, now=NOW + P.POLL_S + 1, prices={"pool1": 0.7})
        self.assertEqual(st["closed"], 1)
        self.assertEqual(self.ex.sells, [("mint1", 1000, True)])
        r = self.db.execute("SELECT * FROM live_positions").fetchone()
        self.assertEqual((r["status"], r["reason"]), ("closed", "stop"))
        self.assertAlmostEqual(r["pnl_usd"], (40_000_000 - 34_000_000) / 1e9 * 75.0, places=6)      # actual SOL in vs out, not the price path

    def test_runner_is_not_capped_and_trailing_stop_sells(self):
        candidate(self.db)
        eng = self.engine(True)
        self.step(eng)
        t = NOW
        for px in (1.6, 3.0, 8.0):
            t += P.POLL_S + 1
            self.step(eng, now=t, prices={"pool1": px})
            self.assertEqual(self.ex.sells, [])                                                       # still holding while it climbs
        t += P.POLL_S + 1
        self.step(eng, now=t, prices={"pool1": 8.0 * 0.69})
        self.assertEqual(len(self.ex.sells), 1)
        self.assertEqual(self.db.execute("SELECT reason FROM live_positions").fetchone()[0], "trail")

    def test_failed_sell_keeps_the_position_open_and_retries(self):
        candidate(self.db)
        eng = self.engine(True, fail_sell=True)
        self.step(eng)
        st = self.step(eng, now=NOW + P.POLL_S + 1, prices={"pool1": 0.7})
        self.assertEqual((st["closed"], st["refused"].get("sell_failed")), (0, 1))
        self.assertEqual(self.db.execute("SELECT status FROM live_positions").fetchone()[0], "open")
        self.ex.fail_sell = False
        st = self.step(eng, now=NOW + 2 * (P.POLL_S + 1), prices={"pool1": 0.7})
        self.assertEqual(st["closed"], 1)

    def test_exits_still_run_when_the_kill_file_exists(self):
        candidate(self.db)
        eng = self.engine(True)
        self.step(eng)
        bot.KILL.write_text("x")
        st = self.step(eng, now=NOW + P.POLL_S + 1, prices={"pool1": 0.7})
        self.assertEqual(st["closed"], 1)


class TestParityWithPaper(Base):
    def test_both_engines_see_the_same_signals_and_exits(self):
        for i in (1, 2):
            candidate(self.db, i)
        candidate(self.db, 3, safety="insider")                                                      # a candidate both must reject
        P.step(self.db, NOW, gt_multi({}), quotes(), 75.0)
        eng = self.engine(True)
        self.step(eng)
        paper_mints = {r[0] for r in self.db.execute("SELECT mint FROM paper_positions WHERE status='open'")}
        live_mints = {r[0] for r in self.db.execute("SELECT mint FROM live_positions WHERE status='open'")}
        self.assertEqual(paper_mints, live_mints)
        self.assertNotIn("mint3", live_mints)


class TestSafetyOfConstruction(unittest.TestCase):
    def test_live_engine_refuses_to_start_unless_every_guard_allows(self):
        with self.assertRaises(X.Refused):
            live.build_engine("live", cfg={"live": False})
        with self.assertRaises(X.Refused):                                                           # even with config live=true: no confirmation, no key
            live.build_engine("live", cfg={"live": True})

    def test_dry_mode_needs_only_a_public_key(self):
        old = os.environ.pop("BURNER_PUBKEY", None)
        try:
            with self.assertRaises(X.Refused):
                live.build_engine("dry", cfg={})
            os.environ["BURNER_PUBKEY"] = "11111111111111111111111111111111"
            self.assertFalse(live.build_engine("dry", cfg={}).live)
        finally:
            os.environ.pop("BURNER_PUBKEY", None)
            if old:
                os.environ["BURNER_PUBKEY"] = old

    def test_default_config_is_not_live(self):
        cfg = bot.load_cfg()
        self.assertIs(cfg.get("live"), False)
        self.assertTrue(X.Guard(cfg, env={"CONFIRM_LIVE": "yes-burner-only", "BURNER_KEYPAIR_PATH": "/x"}, sandbox=lambda: False).why_not_live())


if __name__ == "__main__":
    unittest.main()
