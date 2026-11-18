# How the system should work: Solana memecoins first

Deep research, 2026-11-18. Purpose: decide what to build before building more. Evidence labels: **[paper]** read from the paper itself,
**[source]** web article/vendor page (figures conflict between sources), **[measured]** measured by this project today from live APIs,
**[own data]** computed on this project's candle database (survivors only, see caveats), **[inference]** my reasoning, **[open]** not verified.

## 0. Bottom line

1. **A memecoin on Solana is a launch event, not a listed asset.** Almost everything that decides the outcome happens before and right after graduation, and
   it is driven by insiders (bundled wallets, snipers, creators). Our current design (filter "stable" pools with a $50k floor, age 2-14 days) looks at the
   market after the outcome is mostly decided.
2. **The base rate is hostile.** Graduation is rare (0.63% in Sept 2025 [paper]); after graduation most tokens fall hard (about 73% dropped below 40% of migration
   price within a short window [paper, MELT]); retail wallets mostly lose (74% over two weeks [source, Bitquery]). A follower copying the earliest coordinated
   wallets lost money out of sample in all 32 tested configurations [paper]. Expect "no edge" as the default outcome and design for finding that out cheaply and honestly.
3. **What can still be won is mostly loss avoidance plus cost discipline,** not prediction of winners: avoid insider-dominated launches, avoid un-sellable or
   Token-2022-trapped tokens, avoid paying 5-35% round-trip costs on a $1 position.
4. **The statistically powerful design is an event study on ALL graduates, forward in time,** not trades on $5. Roughly 25 graduations per hour [source] gives thousands of
   samples per week; paper-trading three positions gives dozens. The bot should *observe and simulate every* fresh graduate, and *trade only if a pre-registered rule survives*.
5. **Costs decide small-bankroll viability.** Measured round-trip pool cost on Jupiter quotes was 0.3-5.2% (before network fees), and network fees plus a Jito tip can add
   $0.004-$0.15 per round trip. Position size matters as much as signal: $1 positions are 2-4x more expensive than $2.5-$5 positions in percentage terms.
6. **What I got wrong so far:** wrong universe (mostly non-memecoins), pool age mistaken for token age, a liquidity floor ~5x a fresh graduate's liquidity, a flat cost guess.

## 1. Market mechanics (what actually happens to a token)

| Stage | What happens | Evidence |
|---|---|---|
| Creation | Anyone creates a token on a launchpad in minutes. 655,770 tokens created in Sept 2025 by 243,123 creator addresses. | [paper] Marino et al. 2602.14860 |
| Bonding curve | Trades against a curve, not a pool. Price rises with buys. Pre-graduation pools showed a median of about $2.5k reserve. | [measured] GeckoTerminal new pools, 172 pump-fun pools |
| Graduation | When the curve fills (about $69k market cap in 2025) the token migrates to a DEX pool (PumpSwap since 2025-03-20; LetsBonk uses Raydium LaunchLab; others use Meteora DBC/DAMM). Only 4,338 of 655,770 (0.63%) graduated in Sept 2025. | [paper], [source] |
| Fresh pool | A new PumpSwap pool held about $10-33k of liquidity in my sample (n=3 clear graduates: $10.2k, $12.6k, $33k). LP is burned on PumpSwap, so the pool cannot be pulled, but insiders hold supply. | [measured] n small, [source] |
| First minutes | MELT labels high risk by the minimum price within a short window after migration; about 73% of memecoins dropped below 40% of their migration price. Insiders unwind cheap inventory. The window length did not survive my text extraction (a search snippet says 20 minutes). | [paper] 2602.13480, window [open] |
| After | Survivors decay: of 24 launchpad-style pools with 3+ days of candles, the median last close is 67% below the window peak. | [own data] survivors only |

Launchpad share flips between Pump.fun and LetsBonk (Raydium LaunchLab) over months [source]; a system must be launchpad-agnostic. Pool age from DexScreener/GeckoTerminal is **time since graduation**
for these tokens; token launch time must come from the launchpad/on-chain. [inference from mechanics]

## 2. Who wins and who loses

- **74% of ordinary memecoin buyers ended with less SOL after two weeks** (2.9M wallets). [source] Bitquery.
- **Insiders:** on average **36.5% of supply** that looks independently held is held by coordinated (bundled) accounts; after merging bundles the top-10 holder share rises
  by **24 points for high-risk launches versus 6 for low-risk**. [paper] MELT.
- **Bots and graduation:** tokens whose early activity is dominated by bot-like transactions are less likely to graduate; "historically successful traders" add at most a modest uplift;
  prolific creators add nothing. [paper] Marino et al.
- **Rug definition and base rate:** with TVL-drop or idle labels at one hour, over 80% of memecoins show rug characteristics; XGBoost on only the first 5 minutes of trading
  reaches MCC about 0.36-0.39 and AUCPRC above 0.8 in some settings, and the authors say it is **not yet deployable** because false negatives are costly. [paper] 2608.20271.
- **Copying smart wallets does not work for an outsider:** a follower entering at the earliest group signal **lost money out of sample in all 32 configurations and did no better
  than random entry**; late buyers' net cash flow was negative. Pre-registered negative result. [paper] 2610.39458.
- **Withdrawn:** the "coordinated sniper cohorts" paper (2607.02795) carries a correction notice that all its numbers are withdrawn; nothing from it is used here.
- **Heavy tails:** one study bought every new pool 30 minutes after launch (1,411 tokens) and lost 62% at six hours, driven by a few outliers [source]. In my own survivors-only sample,
  buying 1 hour after pool creation had median +11% to +18% but mean +177% to +225% (n=22): a few huge winners and a typical flat-to-negative outcome. Buying at 24 hours: median -8% (24h) and -17% (72h).
  Median time to the highest close was 15 hours; 64% peak within 24 hours. [own data, n=22, survivors only: tokens that collapsed within about 2.5 hours are excluded by construction]

**Reading:** returns are a lottery with negative drift and fat right tail, concentrated in the first hours, funded by late buyers. A rule "buy stable, aged memecoins" buys the part of the
distribution where the insiders have already left.

## 3. Costs and execution (measured today)

| Item | Result | Evidence |
|---|---|---|
| Jupiter round-trip price cost, $1 | 0.27% (pool $340k) / 0.87% ($53k) / 1.8% ($65k) / 2.3% ($12k) / 5.2% ($8.7k) | [measured] quotes only, nothing sent |
| Same at $5 | 0.40% / 1.9% / 2.5% / 2.3% / 5.2% | [measured] |
| Price impact at $1-$5 | about 0.00-0.01% | [measured]: fees, not impact, dominate |
| Priority fee, popular pools (microlamports per compute unit) | median of non-zero slots 10k-240k, max 3.0M; a 200k-unit swap at 100k costs 0.00002 SOL (about $0.0015) | [measured] public RPC, 4 pools |
| Global priority-fee query | returned all zeros: uninformative, use per-pool queries | [measured] |
| Jito tip | quoted 0.0001-0.001 SOL for a normal swap (about $0.007-$0.07), more when competing | [source] |
| PumpSwap fee | tiered by market cap, about 1.25% total at the lowest tier falling to 0.30%; sources disagree on details | [source] verify against pump.fun docs [open] |
| Sandwich risk | targets slippage of about 1-2% or more; sub-0.3% largely immune | [source] |
| Token-account rent | about 0.002 SOL (about $0.15) unless the account is closed | [measured] SOL price 74.4 |

Round-trip cost as a share of the position (price cost plus network cost; **[inference]** from the rows above):

| Profile | Pool RT | Network RT | $1 position | $2.50 | $5 |
|---|---|---|---|---|---|
| Optimistic (deep pool, plain priority fee) | 0.4% | $0.004 | 0.8% | 0.6% | 0.5% |
| Base (mid pool) | 2% | $0.02 | 4.0% | 2.8% | 2.4% |
| Pessimistic (thin pool, Jito tips) | 5% | $0.15 | 20% | 11% | 8% |
| Pessimistic, rent not recovered (+$0.15) | | | 35% | 17% | 11% |

My current simulation charges 0.25% fee + 0.5% slippage per side + $0.01 per swap = 3.5% at $1: roughly the base profile.

**Jupiter API:** the unified Swap API now lives at `api.jup.ag` (Swap V2), the older Ultra API is described as superseded, and the `lite-api.jup.ag` host is scheduled for
deprecation with the same paths on `api.jup.ag`. The executor must target `api.jup.ag` and re-check endpoints in the official docs first. [source] [open]

## 4. What an outsider can observe for free (and what the papers use)

| Signal | Papers' value | Free source for us | Gap |
|---|---|---|---|
| Bundled / coordinated holdings | strongest (MELT: +24 pt concentration) | RugCheck full report: `graphInsidersDetected`, `insiderNetworks`, `topHolders[].insider` | [measured] fields exist; rate limits and accuracy [open] |
| Creator holdings and history | modest | RugCheck `creator`, `creatorBalance`, `creatorTokens` | exists |
| Mint/freeze authority, Token-2022 extensions, transfer fee | gating | RugCheck + RPC `getAccountInfo` | exists [measured] |
| LP burned/locked | gating | RugCheck `markets[].lp.lpLockedPct` (37%-99% in sample) | exists |
| Rug label for outcome | training labels | RugCheck `rugged` flag | exists |
| Early trade dynamics (first 5 min) | best predictor | needs per-trade data: Bitquery/Helius/RPC parsing; DexScreener has only aggregates | **gap**: needs a keyed provider or own parsing |
| Graduation event stream | needed | GeckoTerminal `new_pools`: the newest 200 pools cover only 2.4 minutes (86% are pre-graduation curve pools); post-graduation style pools appeared at roughly 8 per minute including duplicates and spam | polling every 2 minutes x 10 pages = 5 requests/minute; tight but possible [measured]; on-chain program logs would be better [open] |
| RugCheck summary score | none | `score_normalised` = 1 and zero risks for 6 of 6 sampled tokens: **uninformative alone** | use the full report |

## 5. Target design: memecoins first

```
 (1) EVENT STREAM          (2) CLASSIFY & GATE        (3) OBSERVE & LABEL           (4) DECIDE            (5) EXECUTE (paper first)
 new pools every 2 min  -> launchpad origin,        -> snapshots at +1,5,15,30,60m  -> pre-registered   -> Jupiter quote at decision
 (GT new_pools, DS)        graduate vs spam,           then 2h,6h,24h,48h,72h;        rules only; each     time = the fill; network
                           token age from launch;      holders/insiders (RugCheck),   rule must beat      fee + failure rate;
                           hard rejects:               liquidity, volume, buys/       random entry on      position size chosen to
                           authority, Token-2022,      sells, price, quote-based      forward data         keep cost <= 3%
                           un-sellable, insider>X      sell cost                      (ALL graduates)
```

**Principles**
- **Event-driven, point-in-time, forward.** Every candidate is recorded at fixed ages after graduation, pass or fail, so there is no survivorship and no look-ahead.
- **Observe everything, trade almost nothing.** Rules are evaluated on all graduates (simulated at the quoted price). Real or paper positions are a later, small step.
- **The sell side first.** A token is only a candidate if a Jupiter sell quote at the intended size returns within a set round-trip cost. This is a hard gate, not a feature.
- **Costs are measured at decision time** (quote, priority fee, tip), never assumed. Position size is chosen so round-trip cost stays below a ceiling (target 3% of position).
- **Universe = memecoins by launchpad origin,** with a stored label of how it was classified, and a separate bucket for "not a memecoin" so contamination is visible.
- **Risk limits stay in code** (position, open count, daily loss, KILL file, wallet cap). Live trading stays off.

**Pre-registered hypotheses (each tested on forward data with the random-entry baseline and a counted trial budget)**
- **H1 (decay):** buying at 24h+ after graduation has negative median return after costs. Prior from data: likely true. A confirmed H1 means "do not chase" is the rule.
- **H2 (early window):** entering 5-60 minutes after graduation has a positive median after costs. Prior: dangerous (insider unwind); needs the sell-quote and insider gates to survive.
- **H3 (insider gate):** excluding launches with high bundled-supply share reduces the frequency of -50% outcomes versus the ungated set. Prior from MELT: likely true; the effect size for us is unknown.
- **H4 (sellability gate):** requiring a cheap sell quote removes un-exitable tokens at little cost to returns.
- **H5 (dip-recovery):** after a drop of 50-70% from the post-graduation peak, a time-boxed entry has positive expectancy. Prior: weak ("two-thirds never have a second bounce" [source]).
- **H6 (exit rule):** a fixed time exit (for example 2-6 h) beats the current stop/TP/trail on the same entries.

**Sample size reality [inference]:** with return standard deviation near 100% (fat tails), detecting a 5-point difference in mean needs about 1,500 trades per arm; rank/median tests and
log returns need far fewer. About 25 graduations per hour [source] gives roughly 4,000 per week, so a forward event study can reach that; a $5 paper-trading account (dozens of trades) cannot.

**Decision rule for "go":** a rule goes to paper trading only if, on forward out-of-sample graduates, its median and trimmed-mean net return after measured costs beat the random baseline with the
bootstrap interval excluding zero, in at least two separate weeks. Otherwise the verdict is "no edge", which is an acceptable and expected result of this experiment.

## 6. What changes in the current code and plan

| Item | Now | Change |
|---|---|---|
| Universe | every pool in liquidity range | memecoin classifier by launchpad/mint pattern (add `bonk` for LetsBonk) plus RugCheck `launchpad`/`deployPlatform`, with a stored "not memecoin" bucket |
| Age | pool timestamp | keep both: time since graduation and token launch time (RugCheck `detectedAt`, launchpad data) |
| Liquidity floor | $50k | replace with a sell-quote gate and a lower absolute floor (about $8-10k) |
| Discovery | boosts, search, GT listings | add the graduation stream (new_pools every 2 min), snapshots at fixed ages |
| Backtest on OHLCV | filters on price/volume | keep only for price-path questions; the verdict comes from the forward event study |
| Costs | flat | quote-based at decision time; measured network fee; failure probability |
| Safety (task 5) | crude holders check | RugCheck full report: insiders, creator, LP, authorities, Token-2022; sell simulation |
| Executor (task 6) | lite-api | `api.jup.ag`, re-verify endpoints; still disabled |
| Position size | $1 | evaluate $2.5 x 2 and $5 x 1 against the cost table |
| Tasks 3 (calibration) | threshold grid | replaced by the hypotheses above; calibration only after the event study exists |

## 7. Honest expectations and open questions

- Most likely outcome: **no exploitable edge for a $5 account**; the deliverable is a trustworthy measurement system and a data-backed "no" or "inconclusive", exactly as the brief states.
- Open: exact PumpSwap fee tiers; the MELT post-migration window length; whether RugCheck rate limits allow one full report per candidate; whether on-chain logs (WebSocket via the proxy) give a faster
  graduation stream than polling; real transaction landing rates and failure rates (need a tiny live test outside this session, which stays out of scope here); Token-2022 trap mechanics.
- Limits of my own data: 22-24 pools, survivors only, one 14-day market regime. The measured costs are quotes from one moment.
- Not used because unreliable: withdrawn paper 2607.02795; vendor statistics I could not trace (bot share at launch, Dune dashboards).

## Sources

Papers (read from arxiv.org): Marino, Naviglio, Tarantelli, Lillo, "Predicting the success of new crypto-tokens: the Pump.fun case", arXiv:2602.14860 ·
Li et al., "Catching the Rug: Early Prediction of Fraudulent Memecoins on Solana via Machine Learning", arXiv:2608.20271 ·
"MELT: A Behavioral Trace Dataset for High-Risk Memecoin Launch Detection" (v1 title "MemeTrans"), arXiv:2602.13480 ·
"Early-Buyer Groups and Fast-Wallet Teams on a Bonding-Curve Launchpad", arXiv:2610.39458 ·
"Coordinated Sniper Cohorts on Pump.fun", arXiv:2607.02795 (withdrawn numbers, not used).

Web: madeonsol.com (graduation, deployer stats Aug 2026), theblock.com (PumpSwap launch, launchpad share), docs.bitquery.io (migration), solanacompass.com, dextools.io, thedefiant.io,
soliduslabs.com, docs.solanatracker.io, helius.dev and quicknode.com (MEV), hub.jup.ag / developers.jup.ag (Swap API), blockeden.xyz, bitquery.io (trader losses), arrowalgo.com (paper trading study).

Measurements: `bot/research/measure_market.py` (quotes only, read-only; sends nothing).
