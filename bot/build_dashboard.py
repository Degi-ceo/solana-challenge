#!/usr/bin/env python3
"""Build the self-contained dashboard HTML: docs/dashboard/template.html + exported JSON snapshots.

  python3 build_dashboard.py            # runs export_status.build() first, writes data/export/dashboard.html
  python3 build_dashboard.py --no-net   # skip the network probe (reuses the last one)
"""
import json
import sys
from pathlib import Path

import export_status

BASE = Path(__file__).resolve().parent
TEMPLATE = BASE.parent / "docs" / "dashboard" / "template.html"
OUT = BASE / "data" / "export"


def build(live_net=True):
    export_status.build(OUT, live_net=live_net)
    names = ["summary", "tasks", "pools", "config", "network", "activity", "history", "paper", "backtest"]
    snap = {n: json.loads((OUT / f"{n}.json").read_text()) for n in names}
    payload = json.dumps(snap, separators=(",", ":")).replace("</", "<\\/")   # keep the JSON inert inside <script>
    html = TEMPLATE.read_text().replace("/*__DATA__*/", payload)
    path = OUT / "dashboard.html"
    path.write_text(html)
    return path, len(html)


if __name__ == "__main__":
    p, n = build(live_net="--no-net" not in sys.argv)
    print(f"wrote {p} ({n:,} bytes)")
