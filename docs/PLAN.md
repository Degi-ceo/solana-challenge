# Implementation plan (tasks 1–8)

Written 2026-11-18 after task 0, using the API facts measured there (see JOURNAL.md). This is the working plan; deviations
get logged in JOURNAL.md with the reason. Order follows TASKS.md; one commit (or more) per task, journal updated each time.

## Guiding principles (apply to every task)

1. **One source of truth for trading logic.** `check_filters`, `exit_reason`, `fill_buy`/`proceeds_sell` live in `bot/bot.py`
   only. The backtester, calibrator and reporter import them; they never re-implement them.
2. **Point-in-time or nothing.** A decision at time *t* may only use data whose timestamp is ≤ *t*. A 5m candle with open time
   *t0* is usable only from *t0 + 5m*. Entries fill on the *next* candle, never on the signal candle's close.
3. **Missing data is not passing data.** A filter whose input does not exist in a dataset is reported as *not evaluable*,
   never silently passed or fabricated.
4. **Pre-register, then look.** Verdict thresholds and the train/test split are written into `docs/CALIBRATION.md` *before*
   out-of-sample (OOS) results are computed. Every parameter combination tried is counted.
5. **Always compare against a null model.** Same universe, same exits, random entry times. An "edge" that the random baseline
   also shows is market drift or survivorship, not a filter edge.
6. **Tests without network.** All tests use fixtures (recorded, sanitised API responses in `bot/fixtures/`). The 12 original tests
   keep passing (they may be adapted to the new feature layer, but they keep their intent).
7. **Live stays off.** Nothing in this plan sends a transaction. No keys are read in this environment.

## The core data problem (shapes tasks 1–3)

Measured in task 0: GeckoTerminal serves deep OHLCV (price + volume) but **no historical liquidity and no buy/sell counts**.
Strategy A's filters fall into three groups:

| filter | historical (GT OHLCV) | forward snapshots (DexScreener) |
|---|---|---|
| age (from `pool_created_at`) | yes | yes |
| h1 / h24 price change | yes (from candles) | yes |
| vol24 | yes (sum of candle volume) | yes |
| liquidity, vol/liq | **no** (only today's value → look-ahead) | yes |
| h1 txns, buy ratio | **no** | yes |
| on-chain safety (mint/freeze, holders, Token-2022) | only today's state | yes, at decision time |

So there are two datasets with different jobs:

- **A. Historical replay (GT OHLCV, 14+ days).** Tests price/volume/age filters and exit rules on many trades now. Liquidity is
  used only as a *universe gate* with today's value, and that is labelled as look-ahead + survivorship. Treat results as an
  **upper bound**, useful for rejecting ideas, not for proving an edge.
- **B. Forward point-in-time collector (DexScreener + GT snapshots every few minutes).** Records every candidate, including ones
  that later rug or vanish → no survivorship bias, all filters evaluable. This is the dataset that can support a verdict, and it
  only grows with wall-clock time. **The web sandbox is ephemeral, so B must run on Kamil's VPS as early as possible**
  (see task 2 below; full deploy notes stay in task 8).

## Task 1 — historical data + backtester

Files: `bot/data.py` (downloader + `data/market.db` SQLite, gitignored), `bot/features.py`, `bot/backtest.py`, tests.

1. **Refactor for reuse (no behaviour change first).** Add a normalised *features* dict (`age_h, liq_usd, vol24_usd, h1_pct,
   h24_pct, h1_buys, h1_sells`, each possibly `None`). `features_from_dexscreener(pair, now)` and
   `features_from_candles(candles_upto_t, pool_meta, t)` produce it. `check_filters(features, f)` works on it and returns failed
   names plus `not_evaluable` names. Live loop calls the DexScreener adapter. Run the 12 tests: must still pass.
2. **Universe.** Collect Solana pools with quote in {SOL, USDC, USDT}, created within the last ~30 days, from GT
   (`trending_pools`, `new_pools`, `pools?sort=…` pages) + DexScreener search. Store `pool, base_mint, dex, created_at,
   first_seen, source, liq_now`. Keep pools that are now dead (liq ≈ 0) instead of dropping them, and count them.
3. **Download.** 5m candles (and 1m for a sub-sample, to measure how much 5m granularity flatters stops) via `before_timestamp`
   paging. Rate limiter: ≥ 4 s spacing, exponential backoff on 429, resumable (skip ranges already in DB). Budget ≈ 15 req/min →
   ~300 pools × 14 days of 5m ≈ 1–2 h; run in background and log progress.
4. **Replay engine.** Walk each pool's candles in time order. At each candle close: build features from candles ≤ t, call
   `check_filters`; if pass → enter at next candle open through `fill_buy`; then step candles, calling `exit_reason` per candle.
   Intra-candle rule: if a candle touches both stop and TP, **assume stop first**; stop fills at `min(stop level, candle open)`
   (gap-down) — conservative. Same risk limits as live (max open, cash, daily loss, re-entry block) via shared functions.
5. **Outputs** (`python3 bot/backtest.py --days 14`): trade list, net PnL after costs, profit factor, win rate, max drawdown,
   exit-reason mix, funnel (pools → evaluable → pass per filter → entries), *plus* the random-entry null model and a
   bootstrap 95 % CI on mean PnL per trade.
6. **Bias statement** printed with every run: universe selection date, % of pools now dead, which filters were not evaluable.
7. **Tests:** look-ahead test (append a future spike candle → decision at *t* unchanged); next-candle-entry test; same-candle
   stop+TP → stop; gap-down stop fills at open; the backtester and live loop give identical decisions for identical features.

## Task 2 — candidate discovery

1. Add sources, each tagged: DexScreener boosts/profiles (kept, labelled "paid"), DexScreener search on SOL/USDC quote, GT
   `trending_pools` (5m/1h/24h), GT `new_pools`, GT top-volume pools. De-duplicate by base mint, keep *all* source tags.
2. Funnel table per source: candidates, with pair, pass rate per filter, on-chain pass rate. Log per cycle to the `funnel` table
   (schema extended with a `source` column; migration keeps old rows).
3. **Collector mode** (`python3 bot/bot.py collect`): every 5 min, write a snapshot row (all features + source) for every
   candidate to `snapshots`, whether or not it passes. This is dataset B. Add a 10-line "start the collector on the VPS now"
   section to `docs/DEPLOY.md` immediately, so data starts accumulating days before task 8. *Rationale: the verdict depends on
   forward data, and wall-clock time is the bottleneck.*
4. Done when one live cycle shows a meaningfully larger sample (target ≥ 3× the 51 pairs of the first run) and per-source rates.

## Task 3 — calibration without overfitting

1. **Pre-registration first.** Write in `docs/CALIBRATION.md`: split (time-ordered walk-forward: e.g. train days 1–9, test
   days 10–14; plus a second fold if data allows), parameter grid, selection rule, and verdict rule (OOS PF ≥ 1.2, OOS net > 0,
   ≥ 15 OOS trades, *and* beats the random-entry baseline with the bootstrap CI excluding zero) — before running OOS.
2. **Coarse grid only:** about 3 values per parameter for the 4–5 parameters that matter most (h1 band, age band, SL, TP/trail),
   ≤ ~100 combos. Every combo is logged to `data/trials.csv`; the count is reported.
3. **Selection for robustness:** choose the centre of the best *plateau* (median metric over neighbouring combos), not the single
   best cell. Report the in-sample rank of the chosen combo and how OOS PnL varies across neighbours.
4. Only liquidity-free filters are calibrated on dataset A; liquidity/flow thresholds stay at their current guesses until dataset
   B has enough data, and that is stated.
5. Verdict: **edge / no edge / inconclusive**, OOS numbers only. With a few hundred pools and ≤ 2 weeks, "inconclusive" is the
   likely honest outcome and will be reported as such.

## Task 4 — realistic execution simulation

1. Cost model becomes a profile (`pessimistic` / `base` / `optimistic`) in `config.json`, used by both live paper loop and backtest:
   - **Polling latency:** decision at poll *t*, fill at price after `latency_s` (from 1m candles where available); stops checked
     only at poll times (60 s), so gaps are realistic.
   - **Slippage/price impact:** calibrate an impact curve `impact(size_usd, liq_usd)` from real `lite-api.jup.ag` quotes on
     ~50 current tokens at $0.5–$5 sizes (both directions); fall back to a conservative formula if Jupiter is unreachable.
   - **Fees:** DEX fee per pool type, base fee 5000 lamports, priority fee (configurable, lamports), SOL price from a quote.
   - **Token-account rent:** ~0.00204 SOL per new token account (~15 % of $1). Base case: refunded when the account is closed
     after the sell, minus the close fee; pessimistic: not refunded.
   - **Failed / late fills:** probability `p_fail` per swap; a failed sell retries next poll at the then-current price.
2. Done when the sensitivity table (PnL, PF, DD under the 3 profiles, for the task 3 parameters) is in `docs/CALIBRATION.md`
   and printed by `backtest.py --costs all`.

## Task 5 — rug / safety checks

1. Parse the mint with `jsonParsed`: program id (SPL vs Token-2022) and extensions; reject `transferFeeConfig` (fee > 0),
   `transferHook`, `permanentDelegate`, `nonTransferable`, default-frozen state; mint/freeze authority as before.
2. Holder concentration: resolve owners of the top-20 token accounts (`getMultipleAccounts`), classify as LP vault when the owner
   is the pool / a known AMM authority (Raydium v4/CPMM/CLMM, Orca Whirlpool, Meteora, PumpSwap — list kept in config), as burn
   when it is the incinerator; concentration = top-10 *non-LP, non-burn* holders.
3. LP burn/lock: RugCheck `lpLockedPct` when reachable; for AMMs with an LP mint, % of LP supply in burn/incinerator accounts.
4. RugCheck cross-check: reject on high-severity risks or score above a configured threshold; log disagreements with our checks.
5. Sell simulation: Jupiter quote token→SOL for the position size; reject on no route, impact > `max_sell_impact_pct`, or
   round-trip loss > `max_roundtrip_loss_pct`.
6. Tests: one fixture per rejection reason (recorded real responses, sanitised) + a passing fixture.

## Task 6 — live executor (written, tested with mocks, disabled)

1. `bot/executor.py`: Jupiter `lite-api.jup.ag/swap/v1/quote` → `/swap` (returns a base64 versioned tx) → sign → `sendTransaction`
   → confirm. Signing via `solders` (optional dependency, imported only in live mode). Keypair path from env var
   `BURNER_KEYPAIR_PATH`; never logged, never in the repo.
2. Guards, enforced in code and tested: `live` must be true **and** env `CONFIRM_LIVE=yes-burner-only`; dry-run builds and
   *simulates* but never sends; max position size, max open, daily loss, KILL file, max slippage bps, and a **wallet balance cap**
   (refuse to run if the wallet holds more than e.g. $20 → protects against pointing it at a main wallet).
3. Tests use a fake signer and a fake RPC: assert `sendTransaction` is never called when `live` is false or in dry-run, and that
   each limit blocks. No real keypair is created or read in this environment.

## Task 7 — reporting

`bot/report.py` → `REPORT.md`: funnel per source, trades, PnL after costs, drawdown, null-model comparison, go/no-go from
`config.json` thresholds (refuses below `min_closed_trades`), and a caveats section generated from the data (sample size,
not-evaluable filters, survivorship share). One command regenerates it; `bot.py report` calls the same function.

## Task 8 — deployment notes

`docs/DEPLOY.md` (extending the task 2 collector section): venv, systemd units for collector + paper loop, logrotate, daily
report cron, keypair file permissions (`chmod 600`, outside the repo, burner only, ≤ $5), how to flip `live` and the
`CONFIRM_LIVE` env, how to stop (KILL file, `systemctl stop`). Copy-paste runnable; no secrets in the repo.

## Risks and what would change the plan

- GT rate limits make the download too slow → reduce to 15m candles / fewer pools, state it.
- Too few pools pass the age 2–14 d + liq ≥ $50k universe → widen the universe and report the effect, don't loosen silently.
- Dataset B has too little time to be meaningful within the week → the verdict stays "inconclusive", which is a valid result.
