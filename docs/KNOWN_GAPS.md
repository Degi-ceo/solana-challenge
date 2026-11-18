# Known gaps in the first build (honest list)

The first build was a skeleton produced quickly. Treat everything below as unresolved.

1. **Thresholds are guesses.** No historical data was used. The first live cycle produced 0 entries out of 51 tokens
   (rejects: h1 change 46, liquidity 44, age 43, vol/liq 34, flow 29, h24 29, vol24 20).
2. **Biased candidate source.** Discovery uses DexScreener boosts/profiles (paid promotion). Small and skewed to young, shallow tokens.
3. **Optimistic simulation.** 60 s polling means real stop-losses would gap worse; slippage is a simple formula, no Jupiter quotes
   (Jupiter was unreachable from the sandbox); no token-account rent, no failed fills, no latency model.
4. **Crude on-chain check.** "Top holders excluding the largest" assumes the largest holder is the LP vault, which can be wrong.
   Token-2022 extensions (transfer fee/hook, permanent delegate) are not handled. No LP burn/lock check. No sell simulation.
5. **No live execution code.** Only the paper loop exists.
6. **Sample size.** Even with many cycles, a handful of trades says almost nothing; a go/no-go from <15 trades is noise
   (the verdict function already refuses below `min_closed_trades`).
7. **One-week, $5 result is a single random sample.** It cannot prove or disprove an edge by itself — the backtest and logs matter more.

What *is* solid: cost model arithmetic, exit rules, risk limits, DB logging, and 12 passing unit tests (`bot/test_bot.py`).
