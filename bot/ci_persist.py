#!/usr/bin/env python3
"""Persist the collector database on a dedicated git branch (`data`) so a CI runner (or any host) can resume where the last one stopped.

  python3 ci_persist.py restore   # data branch -> bot/launches.db (skipped if the branch does not exist yet)
  python3 ci_persist.py persist   # bot/launches.db -> data branch (single rolling commit, force-with-lease)
  python3 ci_persist.py stop?     # exit code 3 if a STOP file exists on the data branch (kill switch), else 0

The remote is taken from env DATA_REMOTE (a URL or path); default 'origin' of the current repository. The data branch holds only
data/collected/launches.db.gz, MANIFEST.json and a README. It is a rolling snapshot: history is deliberately not kept (the file would grow the repo by its size on every commit).
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import collect_backup as cb

BRANCH = "data"
BASE = Path(__file__).resolve().parent
README = ("# Collector data (rolling snapshot)\n\nThis branch is written by the collector workflow. `launches.db.gz` is the SQLite database of the graduation collector, "
          "`MANIFEST.json` has row counts, time range and a checksum. Restore with `python3 bot/collect_backup.py restore` after copying these files to `data/collected/`.\n"
          "Create a file named `STOP` here to stop the workflow from chaining new runs.\n")


def git(args, cwd=None, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(a for a in args if 'x-access-token' not in a)} failed: {r.stderr.strip()[:300]}")
    return r


def remote(default_cwd=None):
    r = os.environ.get("DATA_REMOTE")
    if r:
        return r
    return git(["remote", "get-url", "origin"], cwd=default_cwd or BASE.parent).stdout.strip()


def branch_exists(url):
    return git(["ls-remote", "--exit-code", "--heads", url, BRANCH], check=False).returncode == 0


def _clone(url, dest):
    git(["clone", "--quiet", "--depth", "1", "--branch", BRANCH, url, str(dest)])


def restore(db_path=cb.DB, out_dir=cb.OUT, url=None):
    url = url or remote()
    if not branch_exists(url):
        return "no data branch yet: starting a fresh database"
    with tempfile.TemporaryDirectory() as td:
        _clone(url, Path(td) / "d")
        src = Path(td) / "d" / "data" / "collected"
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        for name in ("launches.db.gz", "MANIFEST.json"):
            shutil.copy(src / name, Path(out_dir) / name)
    return cb.restore(db_path, out_dir, force=True)


def persist(db_path=cb.DB, out_dir=cb.OUT, url=None):
    url = url or remote()
    man = cb.backup(db_path, out_dir)
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "d"
        if branch_exists(url):
            _clone(url, d)
        else:
            d.mkdir()
            git(["init", "--quiet", "-b", BRANCH], cwd=d)
            git(["remote", "add", "origin", url], cwd=d)
        git(["config", "user.name", "collector-bot"], cwd=d)
        git(["config", "user.email", "collector-bot@users.noreply.github.com"], cwd=d)
        target = d / "data" / "collected"
        target.mkdir(parents=True, exist_ok=True)
        for name in ("launches.db.gz", "MANIFEST.json"):
            shutil.copy(Path(out_dir) / name, target / name)
        (d / "README.md").write_text(README)
        git(["add", "-A"], cwd=d)
        msg = f"collector snapshot {man['written_utc']} UTC: {man['rows']['launches']} launches, {man['rows']['snaps']} snapshots"
        has_commit = git(["rev-parse", "--verify", "HEAD"], cwd=d, check=False).returncode == 0
        git(["commit", "--quiet", "--amend", "-m", msg] if has_commit else ["commit", "--quiet", "-m", msg], cwd=d)
        git(["push", "--quiet", "--force-with-lease", "origin", f"HEAD:refs/heads/{BRANCH}"], cwd=d)
    return man


def stop_requested(url=None):
    url = url or remote()
    if not branch_exists(url):
        return False
    with tempfile.TemporaryDirectory() as td:
        _clone(url, Path(td) / "d")
        return (Path(td) / "d" / "STOP").exists()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "restore"
    if cmd == "restore":
        print(restore())
    elif cmd == "persist":
        print(persist())
    elif cmd in ("stop?", "stop"):
        sys.exit(3 if stop_requested() else 0)
    else:
        sys.exit(__doc__)
