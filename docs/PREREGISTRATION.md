# Pre-registration: forward event study on Solana memecoin graduates

Committed **before** any graduate data is collected (see git history for the timestamp). Rules below may only be changed by a dated amendment at the
bottom; results may never change what was pre-registered. Rationale and evidence: `docs/RESEARCH_MEMECOIN_SYSTEM.md`.

## Unit of observation
A **graduate** is a newly created pool that is not a bonding-curve pool (dex not in `pump-fun`, `meteora-dbc`, `raydium-launchlab`, `moonshot`-curve),
first seen by the collector within **10 minutes** of `pool_created_at` (amended from 5, see A2), with reserve liquidity at first sight of at least **$3,000**.
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
- **2026-11-18 (A2), before any return was computed:** maximum detection delay raised from 5 to **10 minutes**. Reason, measured in the first live run (n=22): the data source lists new pools after a median of 214 s
  (p25 163 s, p75 315 s, max 385 s); a 5-minute limit would have excluded 27% of pools, which is a selection on indexing speed, and every primary entry age (15 min and later) is unaffected by a delay under 10 minutes.
  Detection delay stays recorded per launch and is reported as a covariate; snapshots at ages 1 and 5 min are exploratory for late-detected pools.
- **2026-11-18 (A3), before any return was computed:** the unit of analysis is the **first observed pool per token mint**; later pools of the same mint are stored but excluded from every primary count and test
  (the first live run showed the same token appearing in several pools, which would inflate the sample and correlate observations). Sample progress on the dashboard counts distinct mints.
  Note recorded for interpretation, not a rule change: several Meteora DAMM v2 pools showed 99.7-99.99% round-trip cost at 5 minutes. A plausible cause is a high launch fee that decays over time (anti-sniper
  fee scheduler) [open, unverified]; the pre-registered return definition already charges the measured cost at the entry age, so such pools are priced correctly rather than assumed un-sellable.
- **2026-11-18 (A4), before any return was computed:** implementation details that the first draft left open, fixed now:
  (a) **Entry cost** = the round-trip price cost measured by the $2.50 probe at the latest probe age at or before the entry age (probe ages are 5, 15, 60, 360 min), using only a probe taken at most 120 s after the
  entry snapshot. For the 24 h entry (H1) this is the 6 h probe. Pools where the entry probe shows no buy route or no sell route are **not enterable**: excluded from returns and reported as a count.
  (b) **Unsellable at exit** = the exit snapshot records the pool as gone, or exit liquidity is below $500, or a probe at the exit age shows no sell route. A launch whose exit snapshot was never taken
  (collector down) is **incomplete** and excluded, reported as a count; it is never imputed.
  (c) **Safety gates (H2)** = no insiders flagged by RugCheck AND top-10 holders excluding the pool's own accounts at most 40% AND mint and freeze authority revoked AND no active transfer-fee, transfer-hook or
  permanent-delegate extension AND entry round trip at most 3%. A safety report counts only if it was taken **before the entry snapshot**; otherwise the launch is "gate unknown" and excluded from gated sets (no look-ahead).
  (d) **H5 condition:** at the 6 h snapshot the price is 30-50% of the highest valid snapshot price at ages up to 6 h (a fall of 50-70% from the early peak).
  (e) **Minimum sample per primary cell:** H1 n >= 300; H2 and H5 the tested subset n >= 300 and the baseline n >= 300; H3 and H4 total n >= 300 with each group >= 100.
  (f) **Weekly rule:** a calendar week (by pool creation time, UTC, Monday start) counts if its own sample meets the minimum for that cell; "go" needs two such weeks that each pass after Holm correction.
- **2026-11-19 (A5), before any return was computed on persisted data:** the collector also stores a **second price** (DexScreener) next to the primary GeckoTerminal price at every snapshot. It is a cross-check only:
  it never enters a primary test. `eventstudy.robustness()` reports the share of snapshots where the two sources differ by more than 10% and the unconditional medians restricted to launches where both sources agree
  at entry and exit. A large disagreement would weaken every price-based result and is reported in the daily report, not used to drop launches from the primary tests.
- **2026-11-19 (A6), before any paper trade was opened and before any return was computed on persisted data:**
  (a) **Reporting change.** Medians and trimmed means describe the typical launch but are blind to a strategy that lives on rare large winners. Every cell therefore also reports the **untrimmed mean, the share of
  returns at or above +100%, the share of total gains coming from the top 1%, and the mean without that top 1%**. The primary tests (median-based) are unchanged; these are reported beside them, not as extra tests.
  (b) **H7, forward paper trading with rule set R1** (`bot/paper.py`, fixed, not tuned): entry on a graduate in the analysis population when its 15-minute snapshot is at most 5 minutes old, all safety gates pass and a fresh $2.50
  Jupiter round trip is at most 3%; size $2.50, at most 2 open positions of a $5 bankroll, one per token; exits: stop -20% from entry, **no take-profit**, trailing stop 30% below the peak once the peak is +50%,
  liquidity below half of entry or under $500, pool gone for 3 polls, maximum hold 48 h; a failed sell quote at exit counts as -100%; P&L = size x (exit/entry - 1 - measured round trip) - $0.02. Daily loss limit $1.5, KILL file stops entries.
  H7 is **forward and exploratory**: it runs continuously without waiting for any week rule, is not part of the Holm family, and is always reported with a bootstrap interval of the mean net return per trade.
  (c) **Evidence statement for H7.** With fewer than 30 closed trades the report says "not enough trades". With 30 or more it states whether the 95% bootstrap interval of the mean net return per trade excludes zero and how much of the total gain comes
  from the single best trade. Whether to risk real money on it is the owner's decision, made outside this repository's sessions; the report only states the evidence level.
- **2026-11-19 (A7), collection procedure only, no change to any definition or test:** the first 5.5 hours of persisted data showed that 24 of 126 stream polls (19%) did not overlap the previous poll, so pools
  created during bursts may have been missed. The poller now fetches pages adaptively until it reaches pools already seen and runs every minute; a poll that hits the page limit without overlap is still counted as a stream gap
  and reported. Launches missed before this change cannot be recovered; the gap count is reported with every result so the size of the possible bias is visible.

- **2026-11-19 (A8), collection procedure and one implementation constant, before any primary test could be evaluated (first 17 h of persisted data: H2 n=5, H3/H4 n=28):** the first persisted data showed a defect in
  the collector, not a market result: cost probes ran oldest-first at 12 per cycle for 3 ages and 2 sizes, so only 383 of 1,538 15-minute snapshots got a $2.50 probe, with median lag 4.6 h (0% within 120 s), and only
  21% of RugCheck reports were taken before the 15-minute snapshot. Changes: (a) cost probes are taken only at ages **15 min and 6 h** (the entry ages of the primary tests; ages 5 and 60 min dropped) and only at **$2.50**
  (the size of the primary tests; $1 dropped), only for snapshots at most 300 s old, newest first, in the same cycle as the snapshot; (b) the **maximum probe lag in A4(a) rises from 120 s to 300 s** (a quote 2-5 minutes
  after a snapshot still describes the entry; the cycle length makes 120 s unreachable); (c) RugCheck reports are fetched first for launches aged 5-15 min so they exist before the entry snapshot; (d) the slow stream poll runs last in the cycle.
  No hypothesis, threshold, gate or decision rule changes. Data collected before this change keeps its missing probes: they are never imputed, and those launches are reported as `no_probe`.
