# How Solana memecoins work, and what it means for strategy A

Written 2026-11-18 after the user asked to understand the market before building more. Labels: **[data]** = measured on this project's own data,
**[source]** = from a cited web source (vendor/blog sources vary; figures differ between them), **[open]** = not verified yet.

## Lifecycle of a pump.fun token
1. **Launch on a bonding curve.** The token trades against a curve, not a pool. Price rises as people buy. [source: madeonsol, cointelegraph]
2. **Graduation.** When the curve fills (roughly 85 SOL deposited; sources differ on the exact trigger) the token migrates. Since 2025-03-20 the destination
   is **PumpSwap** (earlier: Raydium). The pool is seeded from the curve's SOL, the LP tokens are burned, and trading fees are 0.25%. [source: theblock, bitquery]
3. **Graduation is rare.** Cumulatively under 2% of launches graduate; monthly figures from sources range from about 0.3% to 1.8%. [source: solanacompass, madeonsol, dextools]
4. **Graduating is not surviving.** One report says the median graduate's peak equals its graduation market cap and nine in ten peak below about $67k. Only 18 tokens
   ever passed $10M market cap and 96 passed $1M. About 3% of traders made over $1,000. [source: madeonsol, solanacompass (Dune data)]
5. **Pool age is not token age.** A PumpSwap pool is created at graduation, so "age" from the pool timestamp is time since graduation, not since launch. [source + data: pools on pumpswap]

## Why people lose money
- **Rugs on Solana are mostly liquidity and social manipulation** (dev or insider dumps, coordinated wallets), less often backdoored contracts. With burned LP on PumpSwap the
  pool cannot be pulled, but insiders can still dump. [source: arxiv rug study, soliduslabs]
- **Snipers and bundlers** buy at launch with pre-signed transactions; one report says bots enter about 1 in 4 new pump.fun tokens. Signals: wallets funded by the deployer,
  clusters of 3+ wallets with matching transfers, active mint authority. [source: mobula, solanatracker, dextools; vendor claims]
- **Sandwich bots** target swaps with slippage of about 1-2% or more, which memecoin traders often set. [source: helius, quicknode]
- **Token-2022 extensions and honeypots** (transfer fees, hooks) can trap or tax sellers. [open: this search did not cover them; the safety task must verify against Solana docs]

## What costs a small trade
- DEX fee 0.25% each way on PumpSwap. [source]
- Network fee = base fee + priority fee, optionally a Jito tip. Quoted tip ranges: 0.0001-0.001 SOL for a normal swap, 0.001-0.005 SOL for active trading. At SOL = $74 that is
  roughly $0.007-$0.07 per swap, i.e. **0.7-7% of a $1 position per swap**. The simulation currently charges a flat $0.01 per swap, the low end. [source for range; data for SOL price]
- Failed transactions, sandwiching and slippage settings are not modelled. Rent for a token account is about 0.002 SOL (about $0.15, 15% of $1) unless the account is closed. [data]

## What this project's own data shows
- **[data] The first backtest universe was mostly not memecoins.** Of 156 eligible pools only 63 are launchpad-style; of the 32 pools inside the strategy window (age 2-14 d,
  liquidity >= $50k) only 6 are. The rest are tokenised stocks (NVDA, QQQ, TSLA), wrapped large coins (CRO, OSMO, LUNC, IOTA, KAS, XDC) and DeFi tokens (JUP, RAY, KMNO).
- **[data] Memecoin-only re-test** (launchpad proxy, 63 pools): net -$3.52 (pessimistic exits) to -$0.84 (optimistic exits); signal mean per trade -$0.079 vs random entries
  -$0.040; but only 98 signal trades from about 20 pools in one 14-day period. Same direction, thin evidence.
- **[data] Memecoin-style pools that survive are still falling:** of 24 launchpad-style pools with at least 3 days of candles, the median last close is 67% below the window's
  peak and 67% are more than 50% below it. (Survivors only; dead pools are not in the sample.)
- **[data] The liquidity floor is very high for this market.** A fresh PumpSwap graduate holds roughly 85 SOL of liquidity per side (about $6k at SOL $74, so roughly $12k both
  sides) versus the $50k floor. The floor therefore selects the rare tokens that kept growing after graduation. [calculation from sourced figures; open: verify on live PumpSwap pools]

## Implications for strategy A (a hypothesis, not a conclusion)
1. "Relatively new but stable memecoin" is a thin slice of the market, and most tokens in it are survivors of a heavy-tailed process. A 14-day backtest in one regime cannot show an edge there.
2. The universe must be defined as memecoins explicitly before anything is calibrated. The launchpad proxy is a start, not a final definition.
3. Costs must come from measurement (recent priority fees, real Jupiter quotes at $1 and $5), not a flat guess; at $1 per trade they may decide the outcome.
4. Rug and sniper checks matter more than momentum filters for survival; they need the safety task's data (holder clusters, authorities, Token-2022).
5. Expect a modest conclusion: "inconclusive" or "no edge" is the likely honest outcome of a $5, one-week run, which the brief already states.

## Sources
- https://madeonsol.com/blog/pump-fun-graduation-bonding-curve-explained
- https://www.theblock.co/news/business/2025-03-20-pump-fun-launches-dex-called-pumpswap-to-instantly-migrate-graduated-tokens-347360
- https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/pump-fun-to-pump-swap/
- https://solanacompass.com/news/pumpfun-launched-42000-tokens-in-one-day-fewer-than-2-will-ever-reach-a-dex
- https://madeonsol.com/blog/pump-fun-deployer-stats-august-2026
- https://www.dextools.io/news/pump-fun-graduation-collapse-solana-fees-2026
- https://thedefiant.io/just-3-of-pump-fun-traders-have-made-over-usd1000
- https://www.soliduslabs.com/reports/solana-rug-pulls-pump-dumps-crypto-compliance
- https://docs.solanatracker.io/guides/sniper-detection
- https://www.helius.dev/blog/solana-mev-report
- https://www.quicknode.com/guides/solana-development/defi/mev-on-solana

> Update 2026-11-18: this note is superseded in parts by `docs/RESEARCH_MEMECOIN_SYSTEM.md` (primary papers read, live measurements, target design). In particular the network-fee
> range here was too high for plain priority fees (measured about $0.0015 per swap) but still applies when a Jito tip is paid.
