import time
import unittest
from pathlib import Path

import bot

CFG = bot.load_cfg(Path(__file__).parent / "config.json")
NOW = 1_800_000_000.0
A = "TokenAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
B = "TokenBbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def mkpair(addr, px, liq=100_000, h1=5.0, h24=20.0, vol24=80_000, age_days=5, buys=40, sells=25):
    return {
        "baseToken": {"address": addr, "symbol": addr[:6]},
        "quoteToken": {"symbol": "SOL"},
        "priceUsd": str(px),
        "liquidity": {"usd": liq},
        "volume": {"h24": vol24},
        "priceChange": {"h1": h1, "h24": h24},
        "txns": {"h1": {"buys": buys, "sells": sells}},
        "pairCreatedAt": int((NOW - age_days * 86400) * 1000),
    }


class Base(unittest.TestCase):
    def setUp(self):
        self.db = bot.db_connect(":memory:")
        self.pairs = {}
        bot.discover = lambda: {a: "boost_top" for a in self.pairs}
        bot.fetch_pairs = lambda addrs, qw=None: {a: self.pairs[a] for a in addrs if a in self.pairs}
        bot.onchain_check = lambda cfg, addr: (True, "ok", 10.0)


class TestCosts(unittest.TestCase):
    def test_round_trip_flat_price_loses_about_3_5_cents(self):
        c = CFG["costs"]
        fill, qty = bot.fill_buy(1.0, 1.0, 100_000, c)
        pnl = bot.proceeds_sell(1.0, qty, 100_000, c) - 1.0
        self.assertTrue(-0.05 < pnl < -0.02, pnl)

    def test_slippage_capped_when_liquidity_collapses(self):
        c = CFG["costs"]
        _, qty = bot.fill_buy(1.0, 1.0, 100_000, c)
        proceeds = bot.proceeds_sell(1.0, qty, 1.0, c)  # liquidity $1
        self.assertGreater(proceeds, -0.02)  # slip capped at 95%, only the flat fee goes negative


class TestExit(unittest.TestCase):
    def pos(self, peak=1.0, opened=NOW):
        return {"entry_px": 1.0, "peak_px": peak, "entry_liq": 100_000, "opened_ts": opened}

    def test_rules(self):
        e = CFG["exit"]
        self.assertEqual(bot.exit_reason(self.pos(), 0.84, 100_000, NOW, e), "stop")
        self.assertEqual(bot.exit_reason(self.pos(1.41), 1.41, 100_000, NOW, e), "tp")
        self.assertEqual(bot.exit_reason(self.pos(1.3), 1.3 * 0.87, 100_000, NOW, e), "trail")
        self.assertEqual(bot.exit_reason(self.pos(), 1.0, 100_000, NOW + 25 * 3600, e), "time")
        self.assertEqual(bot.exit_reason(self.pos(), 1.0, 40_000, NOW, e), "liq_drop")
        self.assertIsNone(bot.exit_reason(self.pos(), 1.05, 100_000, NOW, e))
        self.assertIsNone(bot.exit_reason(self.pos(1.1), 1.0, 100_000, NOW, e))  # trail not armed below +20%


class TestFilters(unittest.TestCase):
    def test_good_pair_passes(self):
        self.assertEqual(bot.check_filters(mkpair(A, 1.0), CFG["filters"], NOW), [])

    def test_rejections(self):
        f = CFG["filters"]
        self.assertIn("age", bot.check_filters(mkpair(A, 1, age_days=0.5), f, NOW))
        self.assertIn("liq", bot.check_filters(mkpair(A, 1, liq=10_000), f, NOW))
        self.assertIn("h1", bot.check_filters(mkpair(A, 1, h1=60), f, NOW))
        self.assertIn("h24", bot.check_filters(mkpair(A, 1, h24=400), f, NOW))
        self.assertIn("flow", bot.check_filters(mkpair(A, 1, buys=10, sells=40), f, NOW))
        self.assertIn("vol/liq", bot.check_filters(mkpair(A, 1, vol24=60_000, liq=1_000_000), f, NOW))


class TestCycle(Base):
    def test_open_then_stop_loss(self):
        self.pairs = {A: mkpair(A, 1.0)}
        st = bot.cycle(CFG, self.db, NOW)
        self.assertEqual(st["opened"], 1)
        self.pairs = {A: mkpair(A, 0.80)}
        st = bot.cycle(CFG, self.db, NOW + 60)
        self.assertEqual(st["closed"], 1)
        r = self.db.execute("SELECT * FROM positions").fetchone()
        self.assertEqual(r["reason"], "stop")
        self.assertLess(r["pnl"], -0.15)  # stop gap: filled at 0.80, not at -15%

    def test_open_then_take_profit_positive_net(self):
        self.pairs = {A: mkpair(A, 1.0)}
        bot.cycle(CFG, self.db, NOW)
        self.pairs = {A: mkpair(A, 1.45)}
        bot.cycle(CFG, self.db, NOW + 60)
        r = self.db.execute("SELECT * FROM positions").fetchone()
        self.assertEqual(r["reason"], "tp")
        self.assertGreater(r["pnl"], 0.3)

    def test_no_reentry_after_close(self):
        self.pairs = {A: mkpair(A, 1.0)}
        bot.cycle(CFG, self.db, NOW)
        self.pairs = {A: mkpair(A, 0.80)}
        bot.cycle(CFG, self.db, NOW + 60)
        self.pairs = {A: mkpair(A, 1.0)}
        st = bot.cycle(CFG, self.db, NOW + 120)
        self.assertEqual(st["opened"], 0)

    def test_pair_vanishes_assumes_half(self):
        self.pairs = {A: mkpair(A, 1.0)}
        bot.cycle(CFG, self.db, NOW)
        self.pairs = {}
        bot.cycle(CFG, self.db, NOW + 31 * 60)
        r = self.db.execute("SELECT * FROM positions").fetchone()
        self.assertEqual(r["reason"], "no_data")
        self.assertLess(r["pnl"], -0.45)

    def test_capacity_and_cash(self):
        cfg = dict(CFG, max_open=2)
        self.pairs = {A: mkpair(A, 1.0), B: mkpair(B, 2.0)}
        st = bot.cycle(cfg, self.db, NOW)
        self.assertEqual(st["opened"], 2)
        self.assertAlmostEqual(bot.free_cash(self.db, cfg), 3.0)

    def test_daily_loss_limit_halts_entries(self):
        self.db.execute("""INSERT INTO positions(addr,symbol,status,closed_ts,pnl,size_usd)
                           VALUES('X','X','closed',?, -1.6, 1.0)""", (NOW - 10,))
        self.pairs = {A: mkpair(A, 1.0)}
        st = bot.cycle(CFG, self.db, NOW)
        self.assertEqual(st["opened"], 0)
        self.assertIn("daily loss", st["halt"])

    def test_failed_onchain_blocks_entry(self):
        bot.onchain_check = lambda cfg, addr: (False, "mint_authority", None)
        self.pairs = {A: mkpair(A, 1.0)}
        st = bot.cycle(CFG, self.db, NOW)
        self.assertEqual(st["opened"], 0)
        self.assertEqual(st["rejects"].get("mint_authority"), 1)


if __name__ == "__main__":
    unittest.main()
