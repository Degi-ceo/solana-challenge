# JOURNAL (source of truth between sessions — update every session)

## 2026-11-18 — task 4 done: graduation collector, first live results (bot/launches.py)
- Built and tested (80 tests passing, 22 new in test_launches.py): GeckoTerminal new_pools polled every ~2 minutes (10 pages), curve pools ignored, tiny (< $3k) and late pools stored with a
  status, observed pools classified and snapshotted at fixed ages from GeckoTerminal's multi-pool endpoint (price, liquidity, volume, buys/sells, unique traders), Jupiter buy+sell cost probes
  (quotes only) at ages 5/15/60/360 min for $1 and $2.50, one RugCheck report per launch (insiders, holders excluding the pool's own accounts, LP lock, authorities, Token-2022 extensions).
  Stream coverage is measured: detection delay per launch and "stream gaps" (polls that do not overlap the previous one).
- First live run (about 10 minutes, sandbox): 51 new non-curve pools -> 16 observed, 6 late, 29 tiny (57% are spam under $3k). Observed class: 3 confirmed + 7 probable memecoins, 6 unknown.
  Detection delay (n=22): median 214 s, p25 163, p75 315, max 385; 73% within 300 s. Stream gaps: 0 in 6 polls. 36 cost probes, 16 safety reports.
- Pre-registration amendment A2 (before any return was computed): max detection delay 5 -> 10 minutes (the 5-minute limit would have excluded 27% by indexing speed). 6 'late' rows re-statused.
- Cost probes already show what the sell gate catches: round trips of 0.24-0.67% on healthy pools, but 99.75% and 99.9% on a Meteora DAMM v2 pool (buying works, selling returns almost nothing = effectively un-sellable).
  Safety reports vary a lot: one token had top-10 holders (excluding the pool) at 90.7% with 0% LP locked; another showed 111 insider accounts flagged; others were clean.
- Throughput estimate: about 60 memecoin graduates per hour (confirmed + probable) observed -> roughly 1,400 per day, so the 300-sample minimum for the entry-15-min cells is reachable in under a day of
  continuous running; H1 and H5 need 48 h and 24 h of pool age first. The sandbox is ephemeral: the collector must run on the VPS (docs/DEPLOY.md) to accumulate anything that matters.
- Pre-registration amendment A3: unit = first observed pool per mint (the same token showed up in several pools). Hypothesis [open]: the 99.7-99.99% round-trip costs on some Meteora DAMM v2
  pools may be a decaying anti-sniper launch fee, not a honeypot; the probe at 15 min and 60 min will show whether the cost falls.
- Not yet verified: whether late-detected pools differ systematically in outcome (will be reported as a covariate), and GeckoTerminal price quality for thin pools.
- Next: task 5, the event-study analysis tool exactly as pre-registered, tested on synthetic data first (planted effect, pure noise, below-minimum sample).

## 2026-11-18 — task 3 done: memecoin classifier (bot/classify.py)
- Evidence order (first match wins): RugCheck `launchpad.platform` -> confirmed; vanity mint `...pump`/`...bonk` -> confirmed; RugCheck `jup_verified` -> not_memecoin;
  liquidity at first sight > $5M -> not_memecoin; launchpad-family DEX -> probable; else unknown. Every result stores its reason. 10 tests (58 total passing).
- Verified on real RugCheck reports: `launchpad.platform` is pump_fun / meteora_dbc / raydium_launchlab / stonk_fun; stocks and majors have `jup_verified = true`.
  GeckoTerminal's dex label is unreliable: all 34 pools labelled `moonshot` are Meteora DBC tokens per RugCheck.
- Applied to the 211 stored pools (187 distinct mints, 0 RugCheck failures): eligible (<= $50M) 156 -> memecoin_confirmed 74, not_memecoin 63, unknown 19
  (confirmed by platform: Meteora DBC 34, pump.fun 28, LaunchLab 5, stonk.fun 7 across all 211). The earlier launchpad-DEX proxy (63 pools) was close in size but not in membership.
  The 19 unknown are mostly Raydium AMM pools with meme-like names (GREENDILDO, HWAN, PHILCOIN, MEOW): they stay outside the analysis population by the pre-registration and are reported.
- Token age: RugCheck `detectedAt` is NOT the launch time (median equals pool creation; p75 49 h later than pool creation), so token launch time stays [open]. Pool age = time since graduation is what is measured.
- Table `pool_class` added to data/market.db (gitignored). Next: task 4, the graduation stream and fixed-age snapshots.

## 2026-11-18 — plan accepted by the user; pre-registration written before any data
- The user agreed with the re-plan. TASKS.md is revised (classifier -> graduation stream -> event study -> paper execution -> executor -> reporting -> deploy).
- `docs/PREREGISTRATION.md` fixes the unit (graduate), snapshot ages, return definition, baseline (unconditional graduate set), six primary tests, minimum 300 per cell,
  Holm correction and the two-week decision rule. It is committed before the stream collector exists, so results cannot shape it.

## 2026-11-18 — deep research: how the system should work for Solana memecoins (docs/RESEARCH_MEMECOIN_SYSTEM.md)
- Read four papers from arxiv.org (host allowed by the user): Marino et al. (655,770 tokens created in Sept 2025, 4,338 = 0.63% graduated, threshold about $69k market cap),
  Li et al. (6.4M tokens over 7 months; XGBoost on first 5 minutes, MCC about 0.36-0.39, authors say not deployable), MELT (41k+ launches; 36.5% of supply held by coordinated accounts;
  top-10 share +24 pt for high-risk vs +6; about 73% drop below 40% of migration price), early-buyer groups (a follower lost money out of sample in all 32 configurations).
  A fifth paper (2607.02795) has its numbers withdrawn by the authors and is not used. The first agent fetches failed with DNS errors before the network change propagated; the curl reads worked.
- Live measurements (quotes only, nothing sent): Jupiter round trip 0.27-5.2% at $1-$5 depending on pool; price impact about 0; priority fee for popular pools about $0.0015 per swap (max 3.0M
  microlamports/CU); fresh PumpSwap graduates hold about $10-33k liquidity; RugCheck summary score was uninformative (6/6 score 1) but the full report has insiders, creator, LP, authorities;
  the newest 200 pools on GeckoTerminal cover only 2.4 minutes (86% pre-graduation), so the graduation stream needs polling every 2 minutes.
- Own-data event study (22 launchpad-style pools, survivors only): buy 1h after pool creation: median +11% (6h) / +18% (24h), mean +177% / +225%; buy at 24h: median -8% (24h), -17% (72h);
  median time of highest close 15h, 64% within 24h. Fat right tail, negative typical outcome later.
- Conclusion: a memecoin is a launch event; outcome is driven by insiders and costs; the powerful design is a forward event study on ALL graduates (about 25 per hour), observing at fixed ages with
  measured sell-side costs, and trading only rules that beat random entry out of sample. Round-trip cost at $1 is 0.8-35% depending on pool/tips/rent, so position size matters.
- Nothing new was built. Proposed re-plan is in section 6 of the research doc. Awaiting the user's go-ahead.

## 2026-11-18 — CORRECTION to task 1 + research pause (user asked to understand the market before building more)
- Retraction: the "no edge found" reading of the first backtest overstated what was tested. Its universe (every GeckoTerminal pool in range, liq <= $50M) was mostly NOT
  memecoins: 63 of 156 pools are launchpad-style, and only 6 of the 32 pools inside the strategy window. The rest are tokenised stocks, wrapped large coins and DeFi tokens.
  The dashboard wording was corrected ("negative, but not yet a clean test of memecoins"). Task 1 is re-opened: the engine and look-ahead tests stand, the universe does not.
- Memecoin-only re-test (proxy: launchpad DEX or pump.fun mint): net -3.52 (wick exits) / -0.84 (close-only), signal -0.079 vs random -0.040 per trade, but n = 98 signals
  from ~20 pools in one 14-day market. Direction unchanged, evidence thin. `backtest.py --suite` now prints it and writes keyed rows for the dashboard.
- Research written to `docs/HOW_IT_WORKS.md` (bonding curve -> graduation to PumpSwap ~85 SOL, <2% of launches graduate, LP burned, rugs are liquidity/social,
  snipers/bundlers, sandwiching at >=1-2% slippage, Jito tips of 0.0001-0.005 SOL = 0.7-7% of a $1 swap per side). Items not yet verified are marked [open].
- Findings that change the plan: pool age = time since graduation, not token launch; the $50k liquidity floor is ~4x a fresh graduate's liquidity, so it only selects survivors;
  the flat $0.01 network fee is the LOW end of realistic costs at $1 per trade; Token-2022/honeypot mechanics still need checking against Solana docs.
- Process lesson: I built a dashboard and a discovery pipeline before validating that the test universe represented the thing being tested. Task 3 is paused.
- Proposed next steps (awaiting the user's go-ahead): (1) define the memecoin universe explicitly and verify it on live pools, (2) re-run the backtest on memecoins only and
  report sample size honestly, (3) measure real costs (recent priority fees via RPC, Jupiter quotes at $1 / $5), (4) only then pre-register calibration.

## 2026-11-18 — task 2 done: discovery broadened, per-source funnel, forward collector
- New `bot/discovery.py`: seven tagged sources: DexScreener boosts top / latest and profiles (PAID promotion), DexScreener search (12 meme keywords),
  GeckoTerminal trending (1h/6h/24h), new pools and top-volume. De-duplicated by mint, all tags kept (`ds_search+gt_trending`). GeckoTerminal calls are
  cached 15 min behind the shared 5 s rate limiter; empty results are never cached and an outage falls back to the last good result.
- `bot.py`: candidates carry their source tags into `positions.source`; every cycle writes `snapshots` (all candidates with a pair, pass or fail) and
  `funnel_src` (per-source counts); entry halts (KILL, daily loss, capacity) no longer stop data collection; new commands `collect [--once]` (no
  trading, no keys) and `funnel`. 16 new tests (fixture parsing for every source, tag merge, cache/outage, per-source counters, collector never opens).
- Live check (one real cycle): 282 candidates, 217 with a market pair, versus 68 / 51 in the first build (4.3x; target was 3x). Per source, share inside the
  strategy age window (2-14 d) / pairs seen: ds_search 8% / 97, gt_volume 2% / 47, gt_trending 6% / 32, ds_boost_top 29% / 21, ds_boost_latest 25% / 20,
  gt_new 0% / 20, ds_profile 0% / 12. Pass-all-filters: 0 of 217 in this cycle (1h momentum band rejects 202, age 201, flow 187), consistent with the backtest.
- Reading: paid-promotion lists are the only sources with a meaningful share inside the age window, which is also why the first build looked at them; they are
  also the most biased. One cycle is a snapshot, so rates are indicative only until the collector has run for days.
- `docs/DEPLOY.md` (collector section): run it on the VPS now, forward data only grows with wall-clock time.
- Next: task 3 (calibration). The backtest showed the +2..15% 1h-momentum entry underperforms random entries, so the pre-registration will test entry-rule
  families (momentum, mean reversion, breakout after consolidation) against the random baseline with a time-ordered train/test split and a counted trial budget.

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
