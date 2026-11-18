import json
import random
import unittest

import eventstudy as E
import launches as L

T0 = 1_800_000_000.0          # a Monday 00:00 UTC is not needed; weeks are derived from created_ts
WEEK = 7 * 86400


def new_db():
    return L.connect(":memory:")


def add(db, i, created, cls="memecoin_confirmed", entry=1.0, exit_p=1.0, rt=1.0, a=15, b=360, safety="clean", exit_liq=20_000, exit_missed=0,
        probe_lag=20, safety_ts=None, entry_probe=True, exit_probe_sell_ok=None, mint=None):
    pool, mint = f"pool{i}", mint or f"mint{i}"
    db.execute("INSERT INTO launches(pool,mint,name,dex,created_ts,detected_ts,detect_delay_s,liq_at_detect,class,reason,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
               (pool, mint, "X / SOL", "pumpswap", created, created + 100, 100, 12_000, cls, "t", "observed"))
    ets = created + a * 60 + 30
    db.execute("INSERT INTO snaps(pool,age_target_min,ts,age_min,price,liq,missed) VALUES(?,?,?,?,?,?,0)", (pool, a, ets, a + 0.5, entry, 20_000))
    if exit_missed == 2:
        db.execute("INSERT INTO snaps(pool,age_target_min,ts,age_min,missed) VALUES(?,?,?,?,2)", (pool, b, created + b * 60, b))
    elif exit_missed == 1:
        db.execute("INSERT INTO snaps(pool,age_target_min,ts,missed) VALUES(?,?,?,1)", (pool, b, created + b * 60))
    elif exit_p is not None:
        db.execute("INSERT INTO snaps(pool,age_target_min,ts,age_min,price,liq,missed) VALUES(?,?,?,?,?,?,0)", (pool, b, created + b * 60 + 30, b + 0.5, exit_p, exit_liq))
    if entry_probe:
        pa = max(x for x in (5, 15, 60, 360) if x <= a)
        db.execute("INSERT INTO probes VALUES(?,?,?,?,?,?,?,?,?)", (pool, pa, 2.5, ets + probe_lag, 1, 0 if rt is None else 1, rt, 0.0, "PumpSwap"))
    if exit_probe_sell_ok is not None:
        db.execute("INSERT INTO probes VALUES(?,?,?,?,?,?,?,?,?)", (pool, b, 2.5, created + b * 60 + 40, 1, exit_probe_sell_ok, 1.0 if exit_probe_sell_ok else None, 0.0, "PumpSwap"))
    if safety:
        ins, top10 = (0, 10.0) if safety == "clean" else (3, 10.0) if safety == "insider" else (0, 70.0)
        db.execute("INSERT INTO safety(pool,ts,score,rugged,launchpad,jup_verified,insiders_detected,top10_pct_ex_lp,mint_authority,freeze_authority,transfer_fee_pct,extensions) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                   (pool, safety_ts if safety_ts is not None else created + 6 * 60, 1, 0, "pump_fun", 0, ins, top10, 0, 0, 0.0, "[]"))
    db.commit()


class TestOutcome(unittest.TestCase):
    def one(self, **kw):
        db = new_db()
        add(db, 1, T0, **kw)
        rec = E.population(db)[0]
        return E.outcome(rec, kw.get("a", 15), kw.get("b", 360))

    def test_cost_math_flat_price(self):
        st, v, info = self.one(rt=2.0)
        self.assertEqual(st, "ok")
        self.assertAlmostEqual(v, -0.02 - 0.02 / 2.5)            # round trip 2% + $0.02 network on a $2.50 position
        self.assertFalse(info["unsellable"])

    def test_gain_and_loss(self):
        self.assertAlmostEqual(self.one(exit_p=1.5, rt=0.0)[1], 0.5 - 0.008)
        self.assertAlmostEqual(self.one(exit_p=0.4, rt=0.0)[1], -0.6 - 0.008)

    def test_pool_gone_at_exit_is_minus_100(self):
        st, v, info = self.one(exit_missed=2)
        self.assertEqual((st, v, info["unsellable"]), ("ok", -1.0, True))

    def test_exit_liquidity_below_500_is_minus_100(self):
        self.assertEqual(self.one(exit_p=0.9, exit_liq=300)[1], -1.0)

    def test_exit_sell_probe_failure_is_minus_100(self):
        self.assertEqual(self.one(exit_p=1.2, exit_probe_sell_ok=0)[1], -1.0)

    def test_exit_never_taken_is_incomplete_not_imputed(self):
        self.assertEqual(self.one(exit_missed=1)[0], "incomplete")
        self.assertEqual(self.one(exit_p=None)[0], "incomplete")

    def test_no_sell_route_at_entry_is_not_enterable(self):
        self.assertEqual(self.one(rt=None)[0], "not_enterable")

    def test_probe_taken_too_late_is_ignored(self):
        self.assertEqual(self.one(probe_lag=500)[0], "no_probe")
        self.assertEqual(self.one(entry_probe=False)[0], "no_probe")

    def test_24h_entry_uses_the_latest_earlier_probe(self):
        db = new_db()
        add(db, 1, T0, a=1440, b=2880, entry_probe=False)
        e = db.execute("SELECT ts FROM snaps WHERE age_target_min=1440").fetchone()[0]
        db.execute("INSERT INTO probes VALUES('pool1',360,2.5,?,1,1,3.0,0,'x')", (e + 10,))
        rec = E.population(db)[0]
        st, v, _ = E.outcome(rec, 1440, 2880)
        self.assertEqual(st, "ok")
        self.assertAlmostEqual(v, -0.03 - 0.008)


class TestGatesAndPopulation(unittest.TestCase):
    def test_safety_after_entry_is_gate_unknown(self):
        db = new_db()
        add(db, 1, T0, safety="clean", safety_ts=T0 + 15 * 60 + 600)      # report arrives 10 minutes AFTER the entry snapshot
        add(db, 2, T0, safety="clean", safety_ts=T0 + 6 * 60)
        pop = {r["pool"]: r for r in E.population(db)}
        self.assertIsNone(E.gates(pop["pool1"], 15))
        self.assertTrue(E.gates(pop["pool2"], 15)["all_ok"])

    def test_gate_rules(self):
        db = new_db()
        add(db, 1, T0, safety="insider")
        add(db, 2, T0, safety="concentrated")
        add(db, 3, T0, safety="clean", rt=5.0)
        pop = {r["pool"]: r for r in E.population(db)}
        self.assertTrue(E.gates(pop["pool1"], 15)["insider_flag"])
        self.assertTrue(E.gates(pop["pool2"], 15)["insider_flag"])         # top-10 over 40%
        g = E.gates(pop["pool3"], 15)
        self.assertFalse(g["sell_ok"])
        self.assertFalse(g["all_ok"])

    def test_one_pool_per_mint_and_memecoin_only(self):
        db = new_db()
        add(db, 1, T0, mint="SAME")
        add(db, 2, T0 + 100, mint="SAME")
        add(db, 3, T0, cls="not_memecoin")
        add(db, 4, T0, cls="unknown")
        add(db, 5, T0, cls="memecoin_probable")
        self.assertEqual(sorted(r["pool"] for r in E.population(db)), ["pool1", "pool5"])


class TestStatistics(unittest.TestCase):
    def test_median_trimmed_mean_holm(self):
        self.assertEqual(E.median([3, 1, 2]), 2)
        self.assertEqual(E.median([1, 2, 3, 4]), 2.5)
        self.assertAlmostEqual(E.trimmed_mean([0] * 8 + [100, -100]), 0.0)
        h = E.holm({"a": 0.01, "b": 0.03, "c": 0.5, "d": None})
        self.assertAlmostEqual(h["a"][0], 0.03)
        self.assertTrue(h["a"][1])
        self.assertFalse(h["c"][1])
        self.assertNotIn("d", h)


def synth(db, n_gated, n_bad, start=0, created=T0, gated_exit=1.15, bad_exit=0.45, rng=None):
    """Gated launches rise ~15%, insider-flagged ones lose ~55%. Plants an effect for H2 and H3."""
    rng = rng or random.Random(3)
    for k in range(n_gated):
        add(db, start + k, created + k, safety="clean", exit_p=gated_exit * (1 + rng.uniform(-0.1, 0.1)), rt=1.0)
    for k in range(n_bad):
        add(db, start + n_gated + k, created + k, safety="insider", exit_p=bad_exit * (1 + rng.uniform(-0.1, 0.1)), rt=1.0)


class TestPlantedEffectAndNoise(unittest.TestCase):
    def test_detects_a_planted_effect(self):
        db = new_db()
        synth(db, 400, 400)
        res = E.evaluate(db, B=400)["overall"]
        self.assertEqual(res["H2"]["verdict"], "passes")
        self.assertEqual(res["H3"]["verdict"], "passes")
        self.assertGreater(res["H2"]["desc"]["median"], 0)

    def test_below_minimum_sample_is_inconclusive_not_negative(self):
        db = new_db()
        synth(db, 40, 40)                         # a huge effect, but far below the minimum
        res = E.evaluate(db, B=200)["overall"]
        for h in ("H1", "H2", "H3", "H4", "H5"):
            self.assertIsNone(res[h]["p"])
            self.assertTrue(res[h]["verdict"].startswith("inconclusive"))

    def test_no_false_discoveries_in_noise(self):
        """Outcomes independent of every gate: across 12 seeds almost nothing may pass after Holm correction."""
        passes = 0
        for seed in range(12):
            rng = random.Random(seed)
            db = new_db()
            for k in range(450):
                s = rng.choice(["clean", "insider", "concentrated"])
                rt = rng.choice([1.0, 5.0])
                gross = rng.lognormvariate(0, 0.5)                      # median gross 0%, so net median is below zero
                add(db, k, T0 + k, safety=s, rt=rt, exit_p=gross)
            res = E.evaluate(db, B=300, seed=seed)["overall"]
            passes += sum(1 for h in res.values() if h.get("pass"))
        self.assertLessEqual(passes, 1)

    def test_go_needs_two_separate_weeks(self):
        db = new_db()
        synth(db, 400, 400, start=0, created=T0)
        r = E.evaluate(db, B=300)
        self.assertEqual(len(r["weeks"]), 1)
        self.assertFalse(any(r["go"].values()))                         # one week is never enough
        db2 = new_db()
        synth(db2, 400, 400, start=0, created=T0)
        synth(db2, 400, 400, start=10_000, created=T0 + 2 * WEEK)
        r2 = E.evaluate(db2, B=300)
        self.assertEqual(len(r2["weeks"]), 2)
        self.assertTrue(r2["go"]["H3"])
        self.assertTrue(r2["go"]["H2"])


class TestH1AndH5(unittest.TestCase):
    def test_h1_negative_median_detected(self):
        db = new_db()
        rng = random.Random(1)
        for k in range(350):
            add(db, k, T0 + k, a=1440, b=2880, exit_p=0.8 * (1 + rng.uniform(-0.1, 0.1)), rt=1.0, safety=None, entry_probe=False)
            e = db.execute("SELECT ts FROM snaps WHERE pool=? AND age_target_min=1440", (f"pool{k}",)).fetchone()[0]
            db.execute("INSERT INTO probes VALUES(?,360,2.5,?,1,1,1.0,0,'x')", (f"pool{k}", e + 5))
        db.commit()
        res = E.evaluate(db, B=400)["overall"]["H1"]
        self.assertEqual(res["verdict"], "passes")
        self.assertLess(res["desc"]["median"], 0)


if __name__ == "__main__":
    unittest.main()
