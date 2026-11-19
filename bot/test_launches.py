import json
import time
import unittest
from pathlib import Path

import launches as L

FX = Path(__file__).parent / "fixtures"
NOW = 1_800_000_000.0
POOL_A, POOL_B = "58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2", "CaWw5KT1jvMfZtRYbTTcfZsuJ8qVVH5wrN57YB4CTuL9"   # the two pools in fixtures/gt_multi.json
PLAIN_MINT = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def gt_row(pool, dex, liq, created, mint=PLAIN_MINT, name="X / SOL"):
    return {"attributes": {"address": pool, "name": name, "pool_created_at": iso(created), "reserve_in_usd": str(liq)},
            "relationships": {"base_token": {"data": {"id": "solana_" + mint}}, "dex": {"data": {"id": dex}}}}


def listing(*rows):
    return {"data": list(rows)}


def fx(name):
    return json.loads((FX / name).read_text())


def new_db():
    return L.connect(":memory:")


class TestIngest(unittest.TestCase):
    def setUp(self):
        self.db = new_db()

    def test_statuses_and_curve_ignored(self):
        pools = L.parse_pools(listing(
            gt_row("curve1", "pump-fun", 2500, NOW - 30),                 # bonding curve: ignored
            gt_row("good1", "pumpswap", 12_000, NOW - 60),                # observed
            gt_row("tiny1", "pumpswap", 200, NOW - 60),                   # liquidity too small
            gt_row("late1", "pumpswap", 20_000, NOW - 3600)))             # detected an hour after creation
        c = L.ingest(self.db, pools, NOW)
        self.assertEqual((c["curve"], c["observed"], c["tiny"], c["late"], c["new"]), (1, 1, 1, 1, 3))
        st = {r["pool"]: r["status"] for r in self.db.execute("SELECT pool, status FROM launches")}
        self.assertEqual(st, {"good1": "observed", "tiny1": "tiny", "late1": "late"})
        self.assertAlmostEqual(self.db.execute("SELECT detect_delay_s FROM launches WHERE pool='good1'").fetchone()[0], 60)

    def test_duplicates_are_not_reinserted(self):
        pools = L.parse_pools(listing(gt_row("g", "pumpswap", 12_000, NOW - 10)))
        L.ingest(self.db, pools, NOW)
        c = L.ingest(self.db, pools, NOW + 120)
        self.assertEqual(c["new"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM launches").fetchone()[0], 1)

    def test_classification_stored_at_ingest(self):
        L.ingest(self.db, L.parse_pools(listing(gt_row("p", "pumpswap", 12_000, NOW - 5, mint="X" * 40 + "pump"))), NOW)
        self.assertEqual(self.db.execute("SELECT class FROM launches").fetchone()[0], "memecoin_confirmed")

    def test_malformed_rows_are_skipped(self):
        self.assertEqual(L.parse_pools({"data": [{"attributes": {}}, {"nope": 1}]}), [])
        self.assertEqual(L.parse_pools(None), [])


class TestStreamGaps(unittest.TestCase):
    def test_gap_detected_when_polls_do_not_overlap(self):
        db = new_db()
        pages = {1: listing(gt_row("a", "pumpswap", 9000, NOW - 100), gt_row("b", "pumpswap", 9000, NOW - 150))}
        L.poll_stream(db, NOW, lambda path: pages.get(int(path.split("page=")[1]), {"data": []}), pages=2)
        self.assertEqual(L.meta(db, "stream_gaps"), 0)
        pages = {1: listing(gt_row("c", "pumpswap", 9000, NOW + 600), gt_row("d", "pumpswap", 9000, NOW + 500))}   # entirely newer than before
        L.poll_stream(db, NOW + 700, lambda path: pages.get(int(path.split("page=")[1]), {"data": []}), pages=2)
        self.assertEqual(L.meta(db, "stream_gaps"), 1)
        self.assertEqual(L.meta(db, "polls"), 2)

    def test_overlap_is_not_a_gap(self):
        db = new_db()
        mk = lambda rows: (lambda path: listing(*rows) if path.endswith("page=1") else {"data": []})
        L.poll_stream(db, NOW, mk([gt_row("a", "pumpswap", 9000, NOW - 100), gt_row("b", "pumpswap", 9000, NOW - 300)]), pages=2)
        L.poll_stream(db, NOW + 120, mk([gt_row("c", "pumpswap", 9000, NOW + 10), gt_row("a", "pumpswap", 9000, NOW - 100)]), pages=2)
        self.assertEqual(L.meta(db, "stream_gaps"), 0)


class TestAdaptivePolling(unittest.TestCase):
    def pages(self, per_page, total, base):
        """Fake listing: `total` pools, newest first, `per_page` per page; records which pages were requested."""
        rows = [gt_row(f"{base}{i}", "pumpswap", 9000, NOW - i) for i in range(total)]
        asked = []

        def fn(path):
            pg = int(path.split("page=")[1])
            asked.append(pg)
            return listing(*rows[(pg - 1) * per_page: pg * per_page])
        return fn, asked

    def test_stops_as_soon_as_it_reaches_pools_already_seen(self):
        db = new_db()
        fn, asked = self.pages(20, 100, "a")
        L.poll_stream(db, NOW, fn, pages=10)                               # first poll of a fresh database: three pages at most
        self.assertEqual(asked, [1, 2, 3])
        # next poll: 30 pools are newer than anything seen before, the rest are old ones
        newer = [gt_row(f"n{i}", "pumpswap", 9000, NOW + 100 + i) for i in range(30)]
        older = [gt_row(f"a{i}", "pumpswap", 9000, NOW - i) for i in range(100)]
        rows = newer[::-1] + older
        asked2 = []

        def fn2(path):
            pg = int(path.split("page=")[1])
            asked2.append(pg)
            return listing(*rows[(pg - 1) * 20: pg * 20])
        L.poll_stream(db, NOW + 60, fn2, pages=10)
        self.assertEqual(asked2, [1, 2])                                   # page 2 contains the overlap, so page 3 is never requested
        self.assertEqual(L.meta(db, "stream_gaps"), 0)

    def test_hitting_the_page_limit_without_overlap_is_a_gap(self):
        db = new_db()
        fn, _ = self.pages(20, 100, "a")
        L.poll_stream(db, NOW, fn, pages=10)
        rows = [gt_row(f"z{i}", "pumpswap", 9000, NOW + 1000 + i) for i in range(400)]     # 400 new pools: far more than 3 pages
        L.poll_stream(db, NOW + 60, lambda path: listing(*rows[(int(path.split("page=")[1]) - 1) * 20: int(path.split("page=")[1]) * 20]), pages=3)
        self.assertEqual(L.meta(db, "stream_gaps"), 1)


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        L.ingest(self.db, L.parse_pools(listing(gt_row(POOL_A, "pumpswap", 12_000, NOW))), NOW + 30)   # created at NOW, detected 30 s later

    def test_due_logic_take_wait_and_miss(self):
        self.assertEqual(L.due_targets(self.db, NOW + 59), [])                                   # younger than the first target (1 min)
        self.assertEqual(L.due_targets(self.db, NOW + 90), [(POOL_A, 1, "take")])
        d = {(p, t): k for p, t, k in L.due_targets(self.db, NOW + 400)}                         # pool is 6.7 min old
        self.assertEqual(d[(POOL_A, 1)], "miss")                                                 # 5.7 min late for a 1-minute target (limit 2.5)
        self.assertEqual(d[(POOL_A, 5)], "take")                                                 # 1.7 min late for a 5-minute target (limit 4.5)
        self.assertNotIn((POOL_A, 15), d)
        d2 = {(p, t): k for p, t, k in L.due_targets(self.db, NOW + 600)}                        # 10 min old
        self.assertEqual(d2[(POOL_A, 5)], "miss")                                                # 5 min late exceeds the 4.5 min limit

    def test_parse_multi_fixture(self):
        m = L.parse_multi(fx("gt_multi.json"))
        self.assertEqual(set(m), {POOL_A, POOL_B})
        r = m[POOL_A]
        self.assertGreater(r["price"], 0)
        self.assertGreater(r["liq"], 1000)
        self.assertIsNotNone(r["buys_h1"])
        self.assertIsNotNone(r["traders_h1"])

    def test_take_snapshot_stores_metrics_and_does_not_duplicate(self):
        calls = []
        gt = lambda path: calls.append(path) or fx("gt_multi.json")
        n = L.take_snapshots(self.db, NOW + 90, gt)
        self.assertEqual(n, 1)
        row = self.db.execute("SELECT * FROM snaps WHERE pool=? AND age_target_min=1", (POOL_A,)).fetchone()
        self.assertEqual(row["missed"], 0)
        self.assertAlmostEqual(row["age_min"], 1.5)
        self.assertGreater(row["price"], 0)
        self.assertEqual(L.take_snapshots(self.db, NOW + 95, gt), 0)                              # already taken: nothing new
        self.assertEqual(len(calls), 1)

    def test_late_target_is_recorded_as_missed_not_backfilled(self):
        L.take_snapshots(self.db, NOW + 600, lambda path: fx("gt_multi.json"))
        r = self.db.execute("SELECT missed, price FROM snaps WHERE pool=? AND age_target_min=1", (POOL_A,)).fetchone()
        self.assertEqual((r["missed"], r["price"]), (1, None))

    def test_pool_missing_from_api_is_recorded_as_gone(self):
        L.take_snapshots(self.db, NOW + 90, lambda path: {"data": []})
        self.assertEqual(self.db.execute("SELECT missed FROM snaps WHERE age_target_min=1").fetchone()[0], 2)

    def test_tiny_and_late_launches_get_no_snapshots(self):
        L.ingest(self.db, L.parse_pools(listing(gt_row("tinyx", "pumpswap", 100, NOW))), NOW + 30)
        L.take_snapshots(self.db, NOW + 90, lambda path: fx("gt_multi.json"))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snaps WHERE pool='tinyx'").fetchone()[0], 0)


class TestCrossCheckPrice(unittest.TestCase):
    def setUp(self):
        self.db = new_db()
        L.ingest(self.db, L.parse_pools(listing(gt_row(POOL_A, "pumpswap", 12_000, NOW))), NOW + 30)

    def test_parse_ds_pairs_skips_bad_rows(self):
        d = L.parse_ds_pairs(fx("ds_pairs.json"))
        self.assertEqual(set(d), {POOL_A})
        self.assertAlmostEqual(d[POOL_A]["price"], 74.40)

    def test_second_price_is_stored_next_to_the_primary_one(self):
        http = lambda url, body=None, retries=2, timeout=15: fx("ds_pairs.json")
        L.take_snapshots(self.db, NOW + 90, lambda p: fx("gt_multi.json"), http_json=http)
        r = self.db.execute("SELECT price, price_ds, liq_ds FROM snaps WHERE age_target_min=1").fetchone()
        self.assertGreater(r["price"], 0)
        self.assertAlmostEqual(r["price_ds"], 74.40)

    def test_cross_check_failure_never_breaks_the_primary_snapshot(self):
        def boom(url, body=None, retries=2, timeout=15):
            raise RuntimeError("dexscreener down")
        n = L.take_snapshots(self.db, NOW + 90, lambda p: fx("gt_multi.json"), http_json=boom)
        self.assertEqual(n, 1)
        r = self.db.execute("SELECT price, price_ds FROM snaps WHERE age_target_min=1").fetchone()
        self.assertGreater(r["price"], 0)
        self.assertIsNone(r["price_ds"])

    def test_old_databases_are_migrated(self):
        import sqlite3
        c = sqlite3.connect(":memory:")
        c.executescript("CREATE TABLE snaps(pool TEXT, age_target_min INT, ts REAL, age_min REAL, price REAL, liq REAL, mcap REAL, fdv REAL, vol_m5 REAL, vol_h1 REAL, vol_h24 REAL, buys_m5 INT, sells_m5 INT, buys_h1 INT, sells_h1 INT, traders_h1 INT, chg_m5 REAL, chg_h1 REAL, missed INT DEFAULT 0, PRIMARY KEY(pool, age_target_min));")
        import tempfile, os
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        old = sqlite3.connect(path)
        old.executescript("CREATE TABLE snaps(pool TEXT, age_target_min INT, ts REAL, age_min REAL, price REAL, liq REAL, mcap REAL, fdv REAL, vol_m5 REAL, vol_h1 REAL, vol_h24 REAL, buys_m5 INT, sells_m5 INT, buys_h1 INT, sells_h1 INT, traders_h1 INT, chg_m5 REAL, chg_h1 REAL, missed INT DEFAULT 0, PRIMARY KEY(pool, age_target_min));")
        old.close()
        cols = {r[1] for r in L.connect(path).execute("PRAGMA table_info(snaps)")}
        self.assertTrue({"price_ds", "liq_ds"} <= cols)


class TestProbes(unittest.TestCase):
    def quotes(self, buy_out, sell_out):
        def http(url, body=None, retries=2, timeout=15):
            if "outputMint=" + L.SOL in url:
                return None if sell_out is None else {"outAmount": str(sell_out), "routePlan": []}
            return None if buy_out is None else {"outAmount": str(buy_out), "priceImpactPct": "0.001", "routePlan": [{"swapInfo": {"label": "PumpSwap"}}]}
        return http

    def test_round_trip_cost_math(self):
        r = L.round_trip(self.quotes(1_000_000, int(13_000_000 * 0.97)), PLAIN_MINT, 1.0, 75.0)       # $1 at SOL 75 = 13,333,333 lamports
        lam = int(1.0 / 75.0 * 1e9)
        self.assertAlmostEqual(r["rt_pct"], 100 * (1 - int(13_000_000 * 0.97) / lam), places=6)
        self.assertEqual((r["buy_ok"], r["sell_ok"], r["route"]), (1, 1, "PumpSwap"))

    def test_no_buy_route(self):
        self.assertEqual(L.round_trip(self.quotes(None, None), PLAIN_MINT, 1.0, 75.0)["buy_ok"], 0)

    def test_buy_ok_but_no_sell_route_is_flagged_unsellable(self):
        r = L.round_trip(self.quotes(1_000_000, None), PLAIN_MINT, 2.5, 75.0)
        self.assertEqual((r["buy_ok"], r["sell_ok"], r["rt_pct"]), (1, 0, None))

    def test_probes_only_at_probe_ages_and_only_once(self):
        db = new_db()
        L.ingest(db, L.parse_pools(listing(gt_row(POOL_A, "pumpswap", 12_000, NOW))), NOW + 30)
        L.take_snapshots(db, NOW + 400, lambda p: fx("gt_multi.json"))                           # ages 1 (missed) and 5 (taken)
        http = self.quotes(1_000_000, 12_500_000)
        n1 = L.run_probes(db, NOW + 400, http, 75.0, sleep=0)
        self.assertEqual(n1, 2)                                                                  # age 5 x two sizes
        self.assertEqual(L.run_probes(db, NOW + 401, http, 75.0, sleep=0), 0)                    # idempotent
        self.assertEqual({r[0] for r in db.execute("SELECT age_target_min FROM probes")}, {5})


class TestSafety(unittest.TestCase):
    def test_parse_safety_fixture(self):
        s = L.parse_safety(fx("rugcheck_report.json"))
        self.assertEqual(s["launchpad"], "pump_fun")
        self.assertEqual(s["mint_authority"], 0)
        self.assertEqual(s["freeze_authority"], 0)
        self.assertEqual(s["lp_locked_pct"], 100)
        self.assertEqual(s["transfer_fee_pct"], 0)
        self.assertEqual(json.loads(s["extensions"]), [])
        self.assertLessEqual(s["top10_pct_ex_lp"], s["top10_pct_raw"])
        self.assertGreater(s["total_holders"], 1000)

    def test_pool_vault_is_excluded_from_concentration(self):
        rep = {"topHolders": [{"address": "vault", "owner": "POOLOWNER", "pct": 40.0}, {"address": "w1", "owner": "w1", "pct": 5.0}, {"address": "w2", "owner": "w2", "pct": 3.0}],
               "markets": [{"liquidityAAccount": {"owner": "POOLOWNER"}, "liquidityBAccount": {"owner": "POOLOWNER"}, "lp": {"lpLockedPct": 90}}]}
        s = L.parse_safety(rep)
        self.assertEqual(s["top1_pct_ex_lp"], 5.0)
        self.assertEqual(s["top10_pct_ex_lp"], 8.0)
        self.assertEqual(s["top10_pct_raw"], 48.0)

    def test_active_extensions_and_insiders_are_reported(self):
        rep = {"token_extensions": {"transferFeeConfig": {"x": 1}, "permanentDelegate": {"d": 1}, "metadataPointer": {"a": 1}, "transferHook": None},
               "transferFee": {"pct": 5}, "graphInsidersDetected": 3, "insiderNetworks": [{"id": 1}], "mintAuthority": "ABC"}
        s = L.parse_safety(rep)
        self.assertEqual(json.loads(s["extensions"]), ["permanentDelegate", "transferFeeConfig"])
        self.assertEqual((s["transfer_fee_pct"], s["insiders_detected"], s["insider_networks"], s["mint_authority"]), (5.0, 3, 1, 1))

    def test_run_safety_reclassifies_and_waits_for_min_age(self):
        db = new_db()
        L.ingest(db, L.parse_pools(listing(gt_row(POOL_A, "pumpswap", 12_000, NOW))), NOW + 30)
        http = lambda url, body=None, retries=2, timeout=15: fx("rugcheck_report.json")
        self.assertEqual(L.run_safety(db, NOW + 120, http, sleep=0), 0)                          # 2 min old: too early
        self.assertEqual(db.execute("SELECT class FROM launches").fetchone()[0], "memecoin_probable")
        self.assertEqual(L.run_safety(db, NOW + 400, http, sleep=0), 1)
        r = db.execute("SELECT class, reason, safety_done FROM launches").fetchone()
        self.assertEqual((r["class"], r["reason"], r["safety_done"]), ("memecoin_confirmed", "rugcheck_launchpad:pump_fun", 1))
        self.assertEqual(db.execute("SELECT COUNT(*) FROM safety").fetchone()[0], 1)

    def test_run_safety_records_failure_without_retrying_forever(self):
        db = new_db()
        L.ingest(db, L.parse_pools(listing(gt_row(POOL_A, "pumpswap", 12_000, NOW))), NOW + 30)
        L.run_safety(db, NOW + 400, lambda url, body=None, retries=2, timeout=15: None, sleep=0)
        self.assertEqual(db.execute("SELECT safety_done FROM launches").fetchone()[0], 2)
        self.assertEqual(L.run_safety(db, NOW + 500, lambda url, body=None, retries=2, timeout=15: None, sleep=0), 0)


class TestCycle(unittest.TestCase):
    def test_end_to_end_with_fakes(self):
        db = new_db()
        state = {"t": NOW}

        def gt(path):
            if path.startswith("/new_pools"):
                return listing(gt_row(POOL_A, "pumpswap", 12_000, NOW - 20)) if path.endswith("page=1") else {"data": []}
            return fx("gt_multi.json")

        def http(url, body=None, retries=2, timeout=15):
            if "rugcheck" in url:
                return fx("rugcheck_report.json")
            if "outputMint=" + L.SOL in url and "inputMint=" + L.SOL not in url:
                return {"outAmount": "12000000", "routePlan": []}
            return {"outAmount": "1000000", "priceImpactPct": "0.0", "routePlan": [{"swapInfo": {"label": "PumpSwap"}}]}
        import time as _t
        real_sleep = _t.sleep
        _t.sleep = lambda s: None
        try:
            L.cycle(db, NOW, gt, http)                                         # detect (age 20 s): nothing due yet
            self.assertEqual(db.execute("SELECT COUNT(*) FROM launches WHERE status='observed'").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM snaps").fetchone()[0], 0)
            L.cycle(db, NOW + 400, gt, http, do_stream=False)                  # age ~7 min: snapshot 1 (missed), 5 (taken), probes, safety
        finally:
            _t.sleep = real_sleep
        self.assertEqual(db.execute("SELECT COUNT(*) FROM snaps WHERE missed=0").fetchone()[0], 1)
        self.assertGreater(db.execute("SELECT COUNT(*) FROM probes").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT safety_done FROM launches").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
