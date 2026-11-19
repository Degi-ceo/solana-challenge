import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

import ci_persist as C
import collect_backup as cb
import launches as L


def make_db(path, n):
    db = L.connect(path)
    for i in range(n):
        db.execute("INSERT INTO launches(pool,mint,name,dex,created_ts,detected_ts,detect_delay_s,liq_at_detect,class,reason,status) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (f"p{i}", f"m{i}", "X / SOL", "pumpswap", 1.8e9 + i, 1.8e9 + i + 60, 60, 12000, "memecoin_confirmed", "t", "observed"))
    db.commit()
    db.close()


def count(path):
    return sqlite3.connect(path).execute("SELECT COUNT(*) FROM launches").fetchone()[0]


class TestPersist(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.remote = str(Path(self.td) / "remote.git")
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", self.remote], check=True)
        self.db = Path(self.td) / "launches.db"
        self.out = Path(self.td) / "collected"

    def tearDown(self):
        shutil.rmtree(self.td, ignore_errors=True)

    def commits_on_data(self):
        r = subprocess.run(["git", "--git-dir", self.remote, "rev-list", "--count", "data"], capture_output=True, text=True)
        return int(r.stdout.strip())

    def test_first_run_has_nothing_to_restore(self):
        msg = C.restore(self.db, self.out, url=self.remote)
        self.assertIn("no data branch", msg)
        self.assertFalse(self.db.exists())

    def test_persist_creates_branch_and_roundtrips(self):
        make_db(self.db, 5)
        man = C.persist(self.db, self.out, url=self.remote)
        self.assertEqual(man["rows"]["launches"], 5)
        self.assertTrue(C.branch_exists(self.remote))
        db2, out2 = Path(self.td) / "again.db", Path(self.td) / "collected2"
        C.restore(db2, out2, url=self.remote)
        self.assertEqual(count(db2), 5)

    def test_rolling_snapshot_keeps_a_single_commit(self):
        make_db(self.db, 3)
        C.persist(self.db, self.out, url=self.remote)
        db = sqlite3.connect(self.db)
        db.execute("INSERT INTO launches(pool,mint,name,dex,created_ts,detected_ts,detect_delay_s,liq_at_detect,class,reason,status) VALUES('px','mx','X','d',1,2,1,9000,'memecoin_probable','t','observed')")
        db.commit()
        db.close()
        C.persist(self.db, self.out, url=self.remote)
        C.persist(self.db, self.out, url=self.remote)
        self.assertEqual(self.commits_on_data(), 1)               # history is not kept, so the branch does not grow
        db2 = Path(self.td) / "r.db"
        C.restore(db2, Path(self.td) / "c3", url=self.remote)
        self.assertEqual(count(db2), 4)

    def test_restore_then_continue_adds_to_existing_data(self):
        make_db(self.db, 2)
        C.persist(self.db, self.out, url=self.remote)
        os.remove(self.db)                                         # a fresh runner has no database
        C.restore(self.db, self.out, url=self.remote)
        d = L.connect(self.db)
        d.execute("INSERT INTO launches(pool,mint,name,dex,created_ts,detected_ts,detect_delay_s,liq_at_detect,class,reason,status) VALUES('new','mnew','X','d',1,2,1,9000,'memecoin_probable','t','observed')")
        d.commit()
        d.close()
        C.persist(self.db, self.out, url=self.remote)
        db2 = Path(self.td) / "z.db"
        C.restore(db2, Path(self.td) / "c4", url=self.remote)
        self.assertEqual(count(db2), 3)

    def test_stop_file_is_detected(self):
        make_db(self.db, 1)
        C.persist(self.db, self.out, url=self.remote)
        self.assertFalse(C.stop_requested(self.remote))
        w = Path(self.td) / "w"
        subprocess.run(["git", "clone", "--quiet", "--branch", "data", self.remote, str(w)], check=True)
        (w / "STOP").write_text("x")
        for a in (["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "stop"], ["push", "--quiet", "origin", "data"]):
            subprocess.run(["git"] + a, cwd=w, check=True)
        self.assertTrue(C.stop_requested(self.remote))

    def test_report_goes_to_its_own_branch_and_never_touches_the_data_branch(self):
        make_db(self.db, 2)
        C.persist(self.db, self.out, url=self.remote)
        data_sha = subprocess.run(["git", "--git-dir", self.remote, "rev-parse", "data"], capture_output=True, text=True).stdout.strip()
        rep = Path(self.td) / "REPORT.md"
        rep.write_text("# r1")
        C.publish_report(rep, url=self.remote)
        rep.write_text("# r2")
        C.publish_report(rep, url=self.remote)
        self.assertEqual(subprocess.run(["git", "--git-dir", self.remote, "rev-parse", "data"], capture_output=True, text=True).stdout.strip(), data_sha)
        self.assertEqual(subprocess.run(["git", "--git-dir", self.remote, "rev-list", "--count", "report"], capture_output=True, text=True).stdout.strip(), "1")
        shown = subprocess.run(["git", "--git-dir", self.remote, "show", "report:REPORT.md"], capture_output=True, text=True).stdout
        self.assertEqual(shown, "# r2")
        # the collector can still persist after a report was published (no force-with-lease conflict)
        C.persist(self.db, self.out, url=self.remote)

    def test_restore_refuses_a_corrupted_snapshot(self):
        make_db(self.db, 2)
        C.persist(self.db, self.out, url=self.remote)
        bad = Path(self.td) / "bad"
        bad.mkdir()
        shutil.copy(self.out / "MANIFEST.json", bad / "MANIFEST.json")
        (bad / "launches.db.gz").write_bytes(b"not the same bytes")
        with self.assertRaises(SystemExit):
            cb.restore(Path(self.td) / "x.db", bad, force=True)


if __name__ == "__main__":
    unittest.main()
