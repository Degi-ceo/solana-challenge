#!/usr/bin/env python3
"""CI smoke test: fail fast (non-zero exit) if the data sources the collector needs are not reachable from this host.
GitHub-hosted runners use shared cloud IPs, which some APIs rate-limit or block; better to find out in the first minute than after hours of empty collection."""
import sys

import netcheck

NEEDED = ("GeckoTerminal trending", "GeckoTerminal OHLCV 5m", "Jupiter api.jup.ag v1", "RugCheck summary")

if __name__ == "__main__":
    rows = {r[0]: r for r in netcheck.run()}
    bad = [n for n in NEEDED if not rows.get(n) or rows[n][2] != "OK"]
    for n in NEEDED:
        r = rows.get(n)
        print(f"{n:<26} {r[2] if r else 'missing':<16} {r[3] if r else ''}  {r[4] if r else ''}")
    if bad:
        print("::error::data sources not reachable from this host: " + ", ".join(bad))
        sys.exit(1)
