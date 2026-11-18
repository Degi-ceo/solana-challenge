# JOURNAL (source of truth between sessions — update every session)

## 2026-11-18 — task 1 done: backtest result is NEGATIVE
- Data: 156 eligible pools (liq_now <= $50M cap fixed before any result; 55 of 211 excluded), 5m candles, 14-day window 2026-11-04 -> 11-18.
- Method: decision at candle close, fill at NEXT candle open, live risk limits (max 3 open, $1.5 daily loss, 24h re-entry block), same
  `check_features` / `exit_levels` / `exit_reason` / cost model as the live loop. Filters with no historical input (liquidity, vol/liq,
  buy pressure) are NOT evaluated. Costs use today's liquidity (look-ahead proxy). Thresholds are the untuned starting guesses, so nothing was fitted to this data.
- Results (`python3 backtest.py --days 14 --suite`):

| exits | liq gate | trades | net $ | PF | win % | max DD | signal mean/trade [95% CI] | random-entry median | signal beats |
|---|---|---|---|---|---|---|---|---|---|
| wick (pessimistic) | none | 67 | -4.08 | 0.42 | 36 | 4.08 | -0.0735 [-0.0898, -0.0567] | -0.0494 | 0% |
| wick | now | 66 | -4.09 | 0.38 | 33 | 4.26 | -0.0693 [-0.0883, -0.0491] | -0.0461 | 2% |
| close-only (optimistic) | none | 56 | -4.12 | 0.42 | 27 | 4.28 | -0.0824 [-0.1030, -0.0591] | -0.0441 | 0% |
| close-only | now | 75 | -3.02 | 0.59 | 32 | 3.02 | -0.0732 [-0.0957, -0.0488] | -0.0370 | 0% |

- Reading: NO EDGE with the starting thresholds. The strategy loses ~$3-4 of the $5 in 14 days under every variant, and its entries are WORSE than
  random entries with the same exits and costs (CI of the signal mean excludes zero on the negative side). Entering after a +2..15% one-hour move
  looks like buying short-term exhaustion in this sample.
- Robustness: 65% of wick-mode stop/trail exits were wicks whose 5m candle closed back above the level, so the exit assumption matters for the
  numbers, but the conclusion does not change between the pessimistic and optimistic brackets (both are applied to signal and random baseline).
- Biases that favour the strategy (so reality is likely worse): survivorship (only pools alive today), today's liquidity, no flow filter. Not a calibrated
  verdict: task 3 does the pre-registered walk-forward test. One caution against over-reading: 258 signal trades over 14 days in a single market regime.
- Also found: a $1 position pays ~3.5% round-trip cost (network fee $0.01/swap is the largest part); break-even needs +3.57% (about +20.7% if token-account
  rent is not refunded and not modelled yet); with stop -15% / TP +40% the required win rate is 33.8%. At any instant 0 of 82 pools pass all filters
  (the 1h momentum band blocks 77).
- Tests: 32 passing (added close-mode + wick-only diagnostics). Dashboard v4 published (Strategy tab, finding card, readiness gates).
- Next: task 2 (more discovery sources + forward collector), then task 3 (walk-forward calibration; expect to test whether a mean-reversion or
  breakout-after-consolidation entry beats the random baseline instead of chasing a +2..15% hour).

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
