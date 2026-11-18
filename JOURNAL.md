# JOURNAL (source of truth between sessions — update every session)

## 2026-11-18 — initial skeleton (cloud chat session)
- Built `bot/bot.py` paper trader (DexScreener + Solana RPC, SQLite), `config.json`, 12 unit tests passing.
- Live smoke test: DexScreener OK, public Solana RPC OK, Jupiter quote API unreachable from that sandbox.
- First cycle: 68 discovered, 51 with pair, 0 passed cheap filters (see `docs/KNOWN_GAPS.md`).
- Decisions so far: bankroll $5, position $1, max 3 open, SL -15%, TP +40%, trail 12% after +20%, max hold 24h,
  daily loss limit $1.5, 24h re-entry block, go/no-go needs >=15 closed trades, PF >= 1.2, net PnL > 0.
- Go/no-go day 3 is decided by the coded thresholds, not by hand.
- Next: task 0 (network check), then task 1 (backtester).

<!-- append new entries above this line, newest first -->
