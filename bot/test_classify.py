import unittest

import classify as c

PUMP = "BSsmLA6UN8fzJ8qUkV4KwC5LxR7ab3TaUtcwvAyJpump"
PLAIN = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"


class TestClassify(unittest.TestCase):
    def test_rugcheck_launchpad_wins_even_without_vanity(self):
        # GeckoTerminal labelled these pools 'moonshot'; RugCheck says Meteora DBC
        self.assertEqual(c.classify(PLAIN, "moonshot", 66_000, {"launchpad_platform": "meteora_dbc"}),
                         ("memecoin_confirmed", "rugcheck_launchpad:meteora_dbc"))

    def test_pump_vanity_is_confirmed(self):
        self.assertEqual(c.classify(PUMP, "pumpswap", 50_000)[0], "memecoin_confirmed")
        self.assertEqual(c.classify("abcdefBONK", "raydium", 9_000)[1], "vanity_mint:bonk")

    def test_jup_verified_is_not_memecoin(self):
        self.assertEqual(c.classify(PLAIN, "raydium-clmm", 400_000, {"launchpad_platform": None, "jup_verified": True}),
                         ("not_memecoin", "jup_verified"))

    def test_launchpad_beats_verified(self):
        self.assertEqual(c.classify(PLAIN, "pumpswap", 20_000, {"launchpad_platform": "pump_fun", "jup_verified": True})[0], "memecoin_confirmed")

    def test_very_deep_pool_is_not_a_fresh_memecoin(self):
        self.assertEqual(c.classify(PLAIN, "raydium-clmm", 30_000_000), ("not_memecoin", "liquidity_gt_5m"))

    def test_launchpad_dex_without_proof_is_probable(self):
        self.assertEqual(c.classify(PLAIN, "pumpswap", 12_000), ("memecoin_probable", "launchpad_dex:pumpswap"))

    def test_no_evidence_is_unknown(self):
        self.assertEqual(c.classify(PLAIN, "orca", 80_000), ("unknown", "no_evidence"))
        self.assertEqual(c.classify(PLAIN), ("unknown", "no_evidence"))

    def test_analysis_population(self):
        self.assertTrue(c.in_analysis_population("memecoin_confirmed"))
        self.assertTrue(c.in_analysis_population("memecoin_probable"))
        self.assertFalse(c.in_analysis_population("not_memecoin"))
        self.assertFalse(c.in_analysis_population("unknown"))

    def test_curve_pools_are_detected(self):
        for d in ("pump-fun", "meteora-dbc", "raydium-launchlab"):
            self.assertTrue(c.is_curve_pool(d))
        for d in ("pumpswap", "meteora-damm-v2", "raydium", "orca", None):
            self.assertFalse(c.is_curve_pool(d))

    def test_rugcheck_fields_from_real_shaped_reports(self):
        meme = {"launchpad": {"name": "Pump.Fun", "platform": "pump_fun"}, "verification": None, "detectedAt": "2026-10-31T15:36:11.000Z"}
        stock = {"launchpad": None, "verification": {"jup_verified": True}, "detectedAt": "2026-06-18T07:15:58"}
        a, b = c.rugcheck_fields(meme), c.rugcheck_fields(stock)
        self.assertEqual((a["launchpad_platform"], a["jup_verified"]), ("pump_fun", None))
        self.assertEqual((b["launchpad_platform"], b["jup_verified"]), (None, True))
        self.assertIsNotNone(a["token_launch_ts"])
        self.assertEqual(c.rugcheck_fields(None), {"launchpad_platform": None, "jup_verified": None, "token_launch_ts": None})


if __name__ == "__main__":
    unittest.main()
