# JOURNAL (source of truth between sessions — update every session)

## 2026-11-18 — task 0: network check (Claude Code web session)
- Initial state: every API host was refused by the environment's network policy (proxy 403 on CONNECT); only docs sites
  were allowlisted. Kamil approved adding to environment "Claude-Coding": `api.dexscreener.com`, `api.geckoterminal.com`,
  `api.mainnet-beta.solana.com`, `quote-api.jup.ag`, `lite-api.jup.ag`, `api.jup.ag`, `api.rugcheck.xyz`.
- Re-test with `python3 bot/netcheck.py --md` (same stdlib urllib path as the bot):

| check | host | status | latency | evidence |
|---|---|---|---|---|
| DexScreener boosts | api.dexscreener.com | OK | 0.34s | 30 boosted tokens |
| DexScreener search | api.dexscreener.com | OK | 0.07s | 30 pairs |
| GeckoTerminal trending | api.geckoterminal.com | OK | 0.07s | 20 pools |
| GeckoTerminal OHLCV 5m | api.geckoterminal.com | OK | 0.15s | 10 candles |
| Solana RPC getSlot | api.mainnet-beta.solana.com | OK | 0.13s | slot 470813442 |
| Jupiter quote-api v6 | quote-api.jup.ag | FAIL (502) | 0.08s | allowed by policy, upstream does not answer (likely the retired v6 host) |
| Jupiter lite-api v1 | lite-api.jup.ag | OK | 0.47s | 0.01 SOL -> 0.7486 USDC |
| Jupiter api.jup.ag v1 | api.jup.ag | OK | 0.16s | 0.01 SOL -> 0.7486 USDC |
| RugCheck summary | api.rugcheck.xyz | OK | 0.33s | score 1, 0 risks (USDC) |

- Verdict: all essential sources reachable. Use `lite-api.jup.ag/swap/v1` for quotes; `quote-api.jup.ag` is not needed.
- Facts measured for planning (not assumed):
  - GeckoTerminal OHLCV pages back with `before_timestamp`: 1h candles reach pool creation; 5m and 1m pages
    (1000 candles each) went back >= 25 days and >= 6 days respectively on a 6-week-old pool.
  - GeckoTerminal rate limit is tight: 429 after ~5 back-to-back calls; ~4 s spacing still hit an occasional 429.
    Budget ~15 req/min with backoff for bulk downloads.
  - GeckoTerminal OHLCV has price + volume only: no historical liquidity, no buy/sell counts. Filters on liquidity,
    txns and buy ratio cannot be evaluated point-in-time from it (see docs/PLAN.md, task 1).
  - SOL ~= $75 (implied by the quote). Token-account rent (~0.00204 SOL ~= $0.15) is ~15% of a $1 position unless the
    account is closed after the sell; must be modelled in task 4.
- Plan for tasks 1-8 written to `docs/PLAN.md`.

## 2026-11-18 — initial skeleton (cloud chat session)
- Built `bot/bot.py` paper trader (DexScreener + Solana RPC, SQLite), `config.json`, 12 unit tests passing.
- Live smoke test: DexScreener OK, public Solana RPC OK, Jupiter quote API unreachable from that sandbox.
- First cycle: 68 discovered, 51 with pair, 0 passed cheap filters (see `docs/KNOWN_GAPS.md`).
- Decisions so far: bankroll $5, position $1, max 3 open, SL -15%, TP +40%, trail 12% after +20%, max hold 24h,
  daily loss limit $1.5, 24h re-entry block, go/no-go needs >=15 closed trades, PF >= 1.2, net PnL > 0.
- Go/no-go day 3 is decided by the coded thresholds, not by hand.
- Next: task 0 (network check), then task 1 (backtester).

<!-- append new entries above this line, newest first -->
