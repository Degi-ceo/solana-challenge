# Collector data (rolling snapshot)

This branch is written by the collector workflow. `launches.db.gz` is the SQLite database of the graduation collector, `MANIFEST.json` has row counts, time range and a checksum. Restore with `python3 bot/collect_backup.py restore` after copying these files to `data/collected/`.
Create a file named `STOP` here to stop the workflow from chaining new runs.
