#!/usr/bin/env python3
"""Persist and restore the graduation-collector database so data survives an ephemeral sandbox.

  python3 collect_backup.py backup      # consistent copy of launches.db -> data/collected/launches.db.gz + MANIFEST.json
  python3 collect_backup.py restore     # restore into launches.db if it does not exist (use --force to overwrite)
  python3 collect_backup.py status      # print the manifest

Why: the web sandbox is reclaimed after inactivity. Commit data/collected/ to keep the experiment's data. Time while no collector runs is a gap, recorded
as missed snapshots and as a stream gap on restart; the analysis only uses launches whose snapshots exist (see docs/PREREGISTRATION.md).
"""
import gzip
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB = BASE / "launches.db"
OUT = BASE.parent / "data" / "collected"
TABLES = ["launches", "snaps", "probes", "safety", "meta"]


def backup(db_path=DB, out_dir=OUT):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(db_path)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "copy.db"
        dst = sqlite3.connect(tmp)
        src.backup(dst)                                   # consistent even while the collector writes
        counts = {t: dst.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        span = dst.execute("SELECT MIN(detected_ts), MAX(detected_ts) FROM launches").fetchone()
        dst.close()
        gz = out_dir / "launches.db.gz"
        with open(tmp, "rb") as f, gzip.open(gz, "wb", compresslevel=9) as g:
            shutil.copyfileobj(f, g)
    man = {"written_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "rows": counts,
           "first_detected_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(span[0])) if span[0] else None,
           "last_detected_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(span[1])) if span[1] else None,
           "bytes_gz": gz.stat().st_size, "sha256_gz": hashlib.sha256(gz.read_bytes()).hexdigest()}
    (out_dir / "MANIFEST.json").write_text(json.dumps(man, indent=2) + "\n")
    return man


def restore(db_path=DB, out_dir=OUT, force=False):
    gz = Path(out_dir) / "launches.db.gz"
    if not gz.exists():
        return "no backup found"
    if Path(db_path).exists() and not force:
        return "launches.db already exists (use --force to overwrite)"
    man = json.loads((Path(out_dir) / "MANIFEST.json").read_text())
    if hashlib.sha256(gz.read_bytes()).hexdigest() != man["sha256_gz"]:
        raise SystemExit("backup checksum mismatch, refusing to restore")
    with gzip.open(gz, "rb") as g, open(db_path, "wb") as f:
        shutil.copyfileobj(g, f)
    return f"restored {man['rows']}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "backup":
        print(backup())
    elif cmd == "restore":
        print(restore(force="--force" in sys.argv))
    else:
        p = OUT / "MANIFEST.json"
        print(p.read_text() if p.exists() else "no backup yet")
