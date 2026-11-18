# JOURNAL (source of truth between sessions — update every session)

## 2026-11-18 — task 1 in progress + monitoring dashboard
- Refactor: `bot.py` now has a feature layer (`features_from_dex`, `check_features`: missing input -> "not evaluable", never a silent pass)
  and `exit_levels` (single source of exit thresholds, used by `exit_reason` and the backtester). 12 original tests still pass.
- `backtest.py`: point-in-time replay (decision at candle close, fill at NEXT candle open, stop-before-TP in ambiguous candles, gap-down
  stops fill at the open), live risk limits, random-entry null model, bootstrap CI. 18 new tests (`test_backtest.py`); an early version
  of the replay tests was vacuous (no trades fired) and was fixed after a stricter test exposed it.
- `data.py`: universe from GeckoTerminal listings (211 pools, age 2-40 d, liq >= $5k, SOL/USDC/USDT quote), 5m candles resumable at 5 s/request.
- DATA QUALITY FLAG: some pools report absurd liquidity (e.g. QNT/USDC $4.3B). Rule fixed BEFORE looking at any backtest result:
  exclude pools with liq_now > $50M (blue-chips / bad data) from the memecoin universe. 55 of 211 fall under this rule.
- Not done yet for task 1: finish download, run `backtest.py --days 14`, write results and the bias statement here, commit.
- Dashboard: `bot/export_status.py` writes JSON snapshots (summary, tasks, pools, paper trades) consumed by a Claude artifact
  "Solana Paper Bot Monitor". It is a snapshot refreshed on republish, not a live stream from the sandbox.

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
