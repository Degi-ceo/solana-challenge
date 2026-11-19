import unittest

import launches as L
import report as R
from test_eventstudy import add, synth, T0, new_db


class TestReport(unittest.TestCase):
    def test_empty_database_does_not_crash_and_says_inconclusive(self):
        text = R.build(new_db(), boot=50)
        self.assertIn("inconclusive", text)
        self.assertIn("## Caveats", text)

    def test_planted_effect_shows_pass_and_quiet_periods_are_reported(self):
        db = new_db()
        synth(db, 400, 400)
        db.execute("UPDATE launches SET detected_ts = detected_ts + 7200 WHERE pool IN (SELECT pool FROM launches ORDER BY created_ts DESC LIMIT 300)")
        db.commit()
        text = R.build(db, boot=200)
        self.assertIn("passes", text)
        self.assertIn("Quiet periods over 15 minutes", text)
        self.assertIn("Price-source cross-check", text)

    def test_gaps_are_measured(self):
        db = new_db()
        add(db, 1, T0)
        add(db, 2, T0 + 5000)
        g, hours = R.gaps(db)
        self.assertEqual(len(g), 1)
        self.assertAlmostEqual(hours, 5000 / 3600, places=2)


if __name__ == "__main__":
    unittest.main()
