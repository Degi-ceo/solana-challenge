import json
import time
import unittest
from pathlib import Path

import bot
import discovery
from test_bot import CFG, NOW, A, B, mkpair

FX = Path(__file__).parent / "fixtures"


def fx(name):
    return json.loads((FX / name).read_text())


class TestParsers(unittest.TestCase):
    def test_ds_boosts_keep_only_solana(self):
        out = discovery.parse_ds_tokens(fx("ds_boosts.json"), "ds_boost_top")
        self.assertTrue(out)
        self.assertNotIn("0xabc", out)
        self.assertTrue(all(v == "ds_boost_top" for v in out.values()))

    def test_ds_profiles(self):
        out = discovery.parse_ds_tokens(fx("ds_profiles.json"), "ds_profile")
        self.assertEqual(len(out), 3)

    def test_ds_search_filters_chain_and_quote_tokens(self):
        j = fx("ds_search.json")
        out = discovery.parse_ds_search(j)
        sol_bases = {p["baseToken"]["address"] for p in j["pairs"] if p["chainId"] == "solana"} - discovery.QUOTE_MINTS
        self.assertEqual(set(out), sol_bases)
        foreign = {p["baseToken"]["address"] for p in j["pairs"] if p["chainId"] != "solana"}
        self.assertTrue(foreign)                                    # fixture contains a non-Solana pair
        self.assertFalse(foreign & set(out))                        # and it must be dropped

    def test_ds_search_drops_quote_mint_as_base(self):
        j = {"pairs": [{"chainId": "solana", "baseToken": {"address": discovery.SOL}}]}
        self.assertEqual(discovery.parse_ds_search(j), {})

    def test_gt_pools_extract_base_mint(self):
        for name, tag in (("gt_trending.json", "gt_trending"), ("gt_new.json", "gt_new"), ("gt_volume.json", "gt_volume")):
            j = fx(name)
            out = discovery.parse_gt_pools(j, tag)
            exp = {d["relationships"]["base_token"]["data"]["id"].split("_", 1)[1] for d in j["data"]} - discovery.QUOTE_MINTS
            self.assertEqual(set(out), exp, name)
            self.assertTrue(all(v == tag for v in out.values()))

    def test_parsers_tolerate_garbage(self):
        self.assertEqual(discovery.parse_ds_tokens(None, "x"), {})
        self.assertEqual(discovery.parse_ds_tokens([{"nope": 1}, 5], "x"), {})
        self.assertEqual(discovery.parse_ds_search({"pairs": [{"chainId": "solana"}]}), {})
        self.assertEqual(discovery.parse_gt_pools({"data": [{"relationships": {}}]}, "x"), {})


class TestDiscoverMerge(unittest.TestCase):
    def setUp(self):
        discovery.clear_cache()
        self.saved = (discovery.fetch_ds_paid, discovery.fetch_ds_search, discovery.fetch_gt)

    def tearDown(self):
        discovery.fetch_ds_paid, discovery.fetch_ds_search, discovery.fetch_gt = self.saved
        discovery.clear_cache()

    def test_tags_merge_and_dedupe_by_mint(self):
        discovery.fetch_ds_paid = lambda: {A: {"ds_boost_top"}}
        discovery.fetch_ds_search = lambda qs: {A: {"ds_search"}, B: {"ds_search"}}
        discovery.fetch_gt = lambda c: {B: {"gt_trending", "gt_volume"}}
        out = discovery.discover(CFG, now=1000.0)
        self.assertEqual(out[A], "ds_boost_top+ds_search")
        self.assertEqual(out[B], "ds_search+gt_trending+gt_volume")
        self.assertEqual(len(out), 2)

    def test_outage_falls_back_to_last_good_result_and_is_not_cached_empty(self):
        discovery.fetch_ds_paid = lambda: {A: {"ds_boost_top"}}
        discovery.fetch_ds_search = lambda qs: {}
        discovery.fetch_gt = lambda c: {}
        self.assertEqual(set(discovery.discover(CFG, now=1000.0)), {A})
        discovery.fetch_ds_paid = lambda: {}                     # outage after the cache expired
        self.assertEqual(set(discovery.discover(CFG, now=1000.0 + 10_000)), {A})

    def test_cache_avoids_refetch_within_ttl(self):
        calls = []
        discovery.fetch_ds_paid = lambda: calls.append(1) or {A: {"ds_boost_top"}}
        discovery.fetch_ds_search = lambda qs: {}
        discovery.fetch_gt = lambda c: {}
        discovery.discover(CFG, now=1000.0)
        discovery.discover(CFG, now=1000.0 + 30)
        self.assertEqual(len(calls), 1)

    def test_paid_tags_are_marked(self):
        self.assertTrue({"ds_boost_top", "ds_boost_latest", "ds_profile"} <= discovery.PAID)
        self.assertFalse({"gt_trending", "gt_new", "gt_volume", "ds_search"} & discovery.PAID)


class CycleBase(unittest.TestCase):
    def setUp(self):
        self.db = bot.db_connect(":memory:")
        self.pairs, self.src = {}, {}
        bot.discover = lambda cfg=None: dict(self.src)
        bot.fetch_pairs = lambda addrs, qw=None: {a: self.pairs[a] for a in addrs if a in self.pairs}
        bot.onchain_check = lambda cfg, addr: (True, "ok", 10.0)


class TestPerSourceFunnel(CycleBase):
    def test_counts_per_source_and_snapshots(self):
        self.pairs = {A: mkpair(A, 1.0), B: mkpair(B, 1.0, h1=60)}     # A passes, B fails h1
        self.src = {A: "gt_trending+ds_search", B: "ds_boost_top", "NoPairXXXX": "gt_new"}
        st = bot.cycle(CFG, self.db, NOW)
        s = st["sources"]
        self.assertEqual(s["gt_trending"]["cheap_pass"], 1)
        self.assertEqual(s["ds_search"]["with_pair"], 1)
        self.assertEqual(s["ds_boost_top"]["cheap_pass"], 0)
        self.assertEqual(s["ds_boost_top"]["rejects"], {"h1": 1})
        self.assertEqual(s["gt_new"]["candidates"], 1)
        self.assertEqual(s["gt_new"]["with_pair"], 0)               # candidate without a pair is counted, not hidden
        rows = self.db.execute("SELECT addr, source, cheap_pass FROM snapshots ORDER BY addr").fetchall()
        self.assertEqual(len(rows), 2)                              # every candidate with a pair is snapshotted, pass or fail
        self.assertEqual({r["addr"]: r["cheap_pass"] for r in rows}, {A: 1, B: 0})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM funnel_src").fetchone()[0], 4)

    def test_position_records_all_source_tags(self):
        self.pairs = {A: mkpair(A, 1.0)}
        self.src = {A: "ds_search+gt_trending"}
        bot.cycle(CFG, self.db, NOW)
        self.assertEqual(self.db.execute("SELECT source FROM positions").fetchone()[0], "ds_search+gt_trending")

    def test_onchain_rate_per_source(self):
        bot.onchain_check = lambda cfg, addr: (False, "mint_authority", None)
        self.pairs = {A: mkpair(A, 1.0)}
        self.src = {A: "gt_volume"}
        s = bot.cycle(CFG, self.db, NOW)["sources"]["gt_volume"]
        self.assertEqual((s["onchain_checked"], s["onchain_ok"]), (1, 0))


class TestCollectorMode(CycleBase):
    def test_collect_never_opens_positions(self):
        self.pairs = {A: mkpair(A, 1.0)}
        self.src = {A: "gt_trending"}
        st = bot.cycle(CFG, self.db, NOW, trade=False)
        self.assertEqual(st["opened"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM positions").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)   # data still collected
        self.assertEqual(st["cheap_pass"], 1)

    def test_entry_halts_do_not_stop_data_collection(self):
        self.db.execute("""INSERT INTO positions(addr,symbol,status,closed_ts,pnl,size_usd) VALUES('X','X','closed',?, -1.6, 1.0)""", (NOW - 10,))
        self.pairs = {A: mkpair(A, 1.0)}
        self.src = {A: "gt_trending"}
        st = bot.cycle(CFG, self.db, NOW)
        self.assertEqual(st["opened"], 0)
        self.assertIn("daily loss", st["halt"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0], 1)

    def test_funnel_report_runs(self):
        self.pairs = {A: mkpair(A, 1.0), B: mkpair(B, 1.0, liq=1000)}
        self.src = {A: "gt_trending", B: "ds_boost_top"}
        bot.cycle(CFG, self.db, NOW, trade=False)
        agg = bot.funnel_report(self.db)
        self.assertEqual(agg["gt_trending"]["pass"], 1)
        self.assertEqual(agg["ds_boost_top"]["pass"], 0)
        self.assertEqual(agg["ds_boost_top"]["fail"]["liq"], 1)


if __name__ == "__main__":
    unittest.main()
