import copy
import unittest
from pathlib import Path

import backtest as bt
import bot

CFG = bot.load_cfg(Path(__file__).parent / "config.json")
T0 = 1_800_000_000 - 1_800_000_000 % 300   # aligned start
CREATED = T0 - 5 * 86400                   # pool is ~5 days old at T0


def flat(n, px=1.0, vol=1000.0, start=T0):
    return [(start + i * 300, px, px, px, px, vol) for i in range(n)]


def candle(ts, o, h, l, c, v=1000.0):
    return (ts, o, h, l, c, v)


class TestFeaturesNoLookahead(unittest.TestCase):
    def test_future_spike_does_not_change_past_features(self):
        cs = flat(400)
        i = 350
        before = bt.candle_features(cs, i, CREATED)
        spiked = cs + [candle(cs[-1][0] + 300, 1.0, 50.0, 1.0, 50.0, 1e9)]
        after = bt.candle_features(spiked, i, CREATED)
        self.assertEqual(before, after)

    def test_features_use_only_closed_data(self):
        cs = flat(400)
        # change ONLY the candle after the decision candle: decision at i must be identical
        i = 350
        mod = list(cs)
        mod[i + 1] = candle(cs[i + 1][0], 9, 9, 9, 9, 9e9)
        self.assertEqual(bt.candle_features(cs, i, CREATED), bt.candle_features(mod, i, CREATED))

    def test_h1_and_h24_computed_from_closes(self):
        cs = flat(400)
        i = 350
        # make the last candle +10% vs a flat history
        cs[i] = candle(cs[i][0], 1.0, 1.1, 1.0, 1.1)
        ft = bt.candle_features(cs, i, CREATED)
        self.assertAlmostEqual(ft["h1_pct"], 10.0, places=6)
        self.assertAlmostEqual(ft["h24_pct"], 10.0, places=6)
        self.assertIsNone(ft["liq_usd"])          # never fabricated
        self.assertIsNone(ft["h1_buys"])

    def test_not_enough_history_returns_none(self):
        self.assertIsNone(bt.candle_features(flat(100), 99, CREATED))   # < 24h of candles


class TestTradeSimulation(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(CFG)
        self.cfg["costs"] = dict(fee_pct=0.0, slippage_pct=0.0, network_fee_usd=0.0)

    def run_path(self, candles, liq=1e12):
        return bt.simulate_trade(candles, 0, self.cfg, liq)

    def test_entry_at_open_of_entry_candle(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0)] * 1 + flat(3, 1.0, start=T0 + 300)
        tr = self.run_path(cs)
        self.assertEqual(tr["entry_px"], 1.0)
        self.assertEqual(tr["entry_ts"], T0)

    def test_same_candle_stop_and_tp_resolves_to_stop(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0), candle(T0 + 300, 1.0, 1.5, 0.8, 1.2)]
        tr = self.run_path(cs)
        self.assertEqual(tr["reason"], "stop")
        self.assertAlmostEqual(tr["exit_px"], 0.85)

    def test_gap_down_stop_fills_at_open_not_level(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0), candle(T0 + 300, 0.60, 0.62, 0.55, 0.6)]
        tr = self.run_path(cs)
        self.assertEqual(tr["reason"], "stop")
        self.assertAlmostEqual(tr["exit_px"], 0.60)          # gapped through 0.85
        self.assertLess(tr["pnl"], -0.35)

    def test_take_profit_fills_at_level(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0), candle(T0 + 300, 1.0, 1.45, 1.0, 1.4)]
        tr = self.run_path(cs)
        self.assertEqual(tr["reason"], "tp")
        self.assertAlmostEqual(tr["exit_px"], 1.4)

    def test_trail_after_run_up(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0),
              candle(T0 + 300, 1.0, 1.25, 1.0, 1.25),        # peak 1.25 (+25% arms trail), no TP
              candle(T0 + 600, 1.25, 1.25, 1.0, 1.05)]        # falls through 1.25*0.88=1.10
        tr = self.run_path(cs)
        self.assertEqual(tr["reason"], "trail")
        self.assertAlmostEqual(tr["exit_px"], 1.25 * 0.88)

    def test_time_exit(self):
        n = int(25 * 3600 / 300)
        tr = self.run_path(flat(n, 1.0))
        self.assertEqual(tr["reason"], "time")

    def test_data_end_is_flagged_not_hidden(self):
        tr = self.run_path(flat(5, 1.0))
        self.assertEqual(tr["reason"], "data_end")

    def test_costs_reduce_pnl(self):
        cs = flat(5, 1.0)
        free = bt.simulate_trade(cs, 0, self.cfg, 100_000)["pnl"]
        paid = bt.simulate_trade(cs, 0, CFG, 100_000)["pnl"]
        self.assertLess(paid, free)


class TestCloseMode(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(CFG)
        self.cfg["costs"] = dict(fee_pct=0.0, slippage_pct=0.0, network_fee_usd=0.0)
        bt.EXIT_MODE = "close"

    def tearDown(self):
        bt.EXIT_MODE = "wick"

    def test_wick_through_stop_that_recovers_is_not_a_stop_in_close_mode(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0), candle(T0 + 300, 1.0, 1.0, 0.7, 0.99), candle(T0 + 600, 0.99, 1.0, 0.99, 1.0)]
        self.assertEqual(bt.simulate_trade(cs, 0, self.cfg, 1e12)["reason"], "data_end")
        bt.EXIT_MODE = "wick"
        tr = bt.simulate_trade(cs, 0, self.cfg, 1e12)
        self.assertEqual(tr["reason"], "stop")
        self.assertTrue(tr["wick_only"])

    def test_close_mode_stop_fills_at_close(self):
        cs = [candle(T0, 1.0, 1.0, 1.0, 1.0), candle(T0 + 300, 1.0, 1.0, 0.7, 0.8)]
        tr = bt.simulate_trade(cs, 0, self.cfg, 1e12)
        self.assertEqual((tr["reason"], tr["exit_px"]), ("stop", 0.8))


class TestSharedLogic(unittest.TestCase):
    """Backtester and live loop must use identical thresholds."""

    def test_exit_levels_match_exit_reason(self):
        e = CFG["exit"]
        pos = {"entry_px": 1.0, "peak_px": 1.3, "entry_liq": 1e5, "opened_ts": T0}
        lv = bot.exit_levels(pos, e)
        self.assertEqual(bot.exit_reason(pos, lv["stop"] - 1e-9, 1e5, T0, e), "stop")
        self.assertEqual(bot.exit_reason(pos, lv["trail"] - 1e-9, 1e5, T0, e), "trail")
        self.assertIsNone(bot.exit_reason(pos, lv["trail"] + 1e-3, 1e5, T0, e))
        pos2 = dict(pos, peak_px=1.0)
        self.assertEqual(bot.exit_reason(pos2, bot.exit_levels(pos2, e)["tp"] + 1e-9, 1e5, T0, e), "tp")

    def test_check_features_marks_missing_inputs_not_evaluable(self):
        ft = {"age_h": 100, "liq_usd": None, "vol24_usd": 80_000, "h1_pct": 5, "h24_pct": 20,
              "h1_buys": None, "h1_sells": None}
        failed, na = bot.check_features(ft, CFG["filters"])
        self.assertEqual(failed, [])
        self.assertEqual(set(na), {"liq", "vol/liq", "flow"})
        failed, na = bot.check_features(ft, CFG["filters"], skip=("liq", "vol/liq", "flow"))
        self.assertEqual((failed, na), ([], []))

    def test_live_wrapper_never_passes_unknowns(self):
        p = {"baseToken": {"address": "A", "symbol": "A"}, "pairCreatedAt": int((1e9 - 5 * 86400) * 1000),
             "priceChange": {"h1": 5, "h24": 20}, "volume": {"h24": 80_000}}   # no liquidity, no txns
        self.assertTrue(bot.check_filters(p, CFG["filters"], 1e9))


class TestPortfolioReplay(unittest.TestCase):
    def mkpool(self, name, n=700, drift=0.0):
        cs = []
        px = 1.0
        for i in range(n):
            ts = T0 + i * 300
            o = px
            px = px * (1 + drift)
            cs.append((ts, o, max(o, px) * 1.0005, min(o, px) * 0.9995, px, 5000.0))
        return {"meta": {"pool": name, "name": name, "liq_now": 100_000.0, "created_ts": CREATED}, "cs": cs}

    def test_replay_is_deterministic_and_respects_max_open(self):
        pools = {f"P{k}": self.mkpool(f"P{k}", drift=0.0025) for k in range(6)}
        cfg = copy.deepcopy(CFG)
        end = T0 + 700 * 300
        t1, f1, _ = bt.run_backtest(pools, T0 + 86400, end, cfg)
        t2, f2, _ = bt.run_backtest(pools, T0 + 86400, end, cfg)
        self.assertGreater(len(t1), 3)                      # not vacuous
        self.assertGreater(f1["blocked_capacity"] + f1["blocked_open_or_reentry"], 0)
        self.assertEqual([x["pnl"] for x in t1], [x["pnl"] for x in t2])
        # never more than max_open overlapping
        events = sorted([(t["entry_ts"], 1) for t in t1] + [(t["exit_ts"], -1) for t in t1])
        cur = peak = 0
        for _, d in events:
            cur += d
            peak = max(peak, cur)
        self.assertLessEqual(peak, cfg["max_open"])

    def test_entry_is_exactly_next_candle_after_signal(self):
        pools = {"P": self.mkpool("P", drift=0.0025)}
        trades, _, signals = bt.run_backtest(pools, T0 + 86400, T0 + 700 * 300, copy.deepcopy(CFG))
        self.assertTrue(trades)
        sig_ts = {pools["P"]["cs"][n][0] for _, n in signals}
        for t in trades:
            self.assertIn(t["entry_ts"] - 300, sig_ts)   # signal candle closed, THEN fill at the next open
            self.assertNotIn(t["entry_ts"], {t["entry_ts"] - 300})

    def test_stats_drawdown_and_pf(self):
        tr = [{"pnl": 0.5, "exit_ts": 1}, {"pnl": -0.2, "exit_ts": 2}, {"pnl": -0.2, "exit_ts": 3}, {"pnl": 0.1, "exit_ts": 4}]
        s = bt.stats(tr)
        self.assertAlmostEqual(s["net"], 0.2)
        self.assertAlmostEqual(s["max_dd"], 0.4)
        self.assertAlmostEqual(s["pf"], 0.6 / 0.4)


if __name__ == "__main__":
    unittest.main()
