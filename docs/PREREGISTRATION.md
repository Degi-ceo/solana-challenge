# Pre-registration: forward event study on Solana memecoin graduates

Committed **before** any graduate data is collected (see git history for the timestamp). Rules below may only be changed by a dated amendment at the
bottom; results may never change what was pre-registered. Rationale and evidence: `docs/RESEARCH_MEMECOIN_SYSTEM.md`.

## Unit of observation
A **graduate** is a newly created pool that is not a bonding-curve pool (dex not in `pump-fun`, `meteora-dbc`, `raydium-launchlab`, `moonshot`-curve),
first seen by the collector within **5 minutes** of `pool_created_at`, with reserve liquidity at first sight of at least **$3,000**.
Late detections and tiny pools are counted and reported, never silently dropped.
Each graduate carries a classification: `memecoin_confirmed` (vanity mint `...pump` or `...bonk`, or RugCheck launchpad field), `memecoin_probable`
(launchpad-family dex), `not_memecoin` (liquidity at first sight above $5M), `unknown`. **Analysis population = confirmed + probable.** Other classes are reported separately.

## Observations (point-in-time, taken by the collector; nothing is back-filled)
Snapshots at pool age 1, 5, 15, 30, 60 min and 2, 6, 24, 48, 72 h (tolerance: taken if the delay is at most 50% of the target age plus 2 minutes, else recorded as missed).
Each: price, liquidity, market cap, volume and buy/sell counts (GeckoTerminal). Cost probes (Jupiter quotes, nothing sent) at ages 5, 15, 60 min and 6 h for notional $1 and $2.50:
buy quote then sell quote of the received amount; round-trip price cost = 1 - SOL back / SOL spent. One RugCheck full report at age >= 5 min.

## Return definition
`net return = (exit price / entry price) - 1 - round_trip_cost(entry age, size) - network_fee / size`, with `network_fee = $0.02` per round trip (base profile; sensitivity at $0.004 and $0.15).
An exit is treated as **-100%** if the pool is unsellable at the exit age (sell quote fails or liquidity below $500). Entry price = snapshot price at the entry age (no better fill assumed).

## Baseline
The **unconditional graduate set**: every analysis-population graduate entered at the same age and exited at the same horizon, with no filter. A rule must beat its own complement and this baseline.

## Hypotheses and primary tests (everything else is exploratory and labelled so)
| id | claim | primary cell | test |
|---|---|---|---|
| H1 | Buying 24 h after graduation has negative median net return | entry 24 h, exit +24 h | median < 0, one-sided bootstrap |
| H2 | Entry 15 min after graduation, after all safety gates, has positive median net return | entry 15 min, exit +6 h | median of gated set > 0 and > baseline |
| H3 | High bundled/insider supply share raises the frequency of net return <= -50% | entry 15 min, exit +6 h | difference in proportion, gated vs not |
| H4 | A cheap sell quote (round trip <= 3%) removes un-sellable outcomes at little cost to returns | entry 15 min, exit +6 h | share unsellable, gated vs not |
| H5 | After a fall of 50-70% from the first-6 h peak, a time-boxed entry at 6 h has positive median | entry 6 h, exit +24 h | median > 0 and > baseline |
| H6 | A fixed time exit beats the stop/take-profit/trailing rule on identical entries | entry 15 min | paired difference of means, needs candle data: evaluated after candles are added |

Insider gate = RugCheck `graphInsidersDetected` > 0 or top-10 holder share above 40% after excluding LP accounts. Sell gate = measured $2.50 round trip <= 3%. Both thresholds are fixed here and not tuned.

## Statistics
Bootstrap (10,000 resamples) for medians and differences; trimmed mean (10%) reported next to the median; Holm correction across the six primary tests;
**minimum 300 graduates per primary cell**, otherwise the result is "inconclusive", not "no effect". Trial budget: 6 primary tests; any additional cell examined is logged in
`docs/TRIALS.md` with its count and is exploratory only.

## Decision rule
A rule is **"go to paper trading"** only if its pre-registered primary test passes (after Holm) in **two separate calendar weeks**, with net return measured under the base cost profile
and still non-negative under the pessimistic profile for the median. Otherwise the verdict is "no edge" or "inconclusive" and is reported as such.

## Known biases accepted up front
Detection delay (up to 5 min), GeckoTerminal price quality for thin pools, wash-traded volume, one or two market regimes in a short window, quotes taken at snapshot time rather than executed fills.

## Amendments
- **2026-11-18 (A1), before any return was computed:** "exit +X h" in the hypothesis table means the **snapshot at pool age X**, not entry + X, because snapshots exist only at the fixed ages.
  Cells therefore are: H1 entry 24 h, exit at age 48 h; H2, H3, H4 entry 15 min, exit at age 6 h; H5 entry 6 h, exit at age 24 h. Only the label changes; no threshold, test or decision rule changes.
  At the time of this amendment the collector had been running for minutes and no analysis had been run.
