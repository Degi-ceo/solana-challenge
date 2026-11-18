# Dashboard specification (v4)

Purpose of the challenge: a one-week, $5 Solana experiment whose deliverable is **a trustworthy system and a data-backed verdict**, not a promise
of profit. So the dashboard must answer five questions without being asked: **(1) Is it safe? (2) What is it doing? (3) What did it earn or lose and
why? (4) Can the result be trusted? (5) Is it ready for real money, and if not, what is missing?**

v3 answered (1) and (2) only. v4 adds the modules below. "Now" = buildable from data that exists today; "Task N" = appears when that task
produces data. Empty states say exactly which task fills them. Nothing is mocked or invented.

## A. Challenge control room (Overview)
| # | Module | Shows | Data | When |
|---|---|---|---|---|
| A1 | Challenge strip | bankroll, equity, P&L, day X of 7, SOL price, run status ("paper run not started") | summary, SOL quote | Now |
| A2 | Right now + what changed | current task, ETA, deltas since last visit (pools, candles, tasks) | summary, browser memory | Now |
| A3 | Equity curve + drawdown | equity over time vs $5 start, daily-loss budget used | paper trades | Task 2 (paper loop) |
| A4 | Open positions | symbol, entry, now, P&L %, distance to stop/TP, time held | paper DB | Task 2 |
| A5 | Trade log | every trade: entry/exit, reason, gross, costs, net | paper DB | Task 2 |
| A6 | Verdict gates | criteria vs current values | config + results | Now (pending) |

## B. Strategy lab (new tab)
| # | Module | Shows | Data | When |
|---|---|---|---|---|
| B1 | Trade math | net P&L vs price move at three liquidity levels, with stop, take-profit and break-even marked; round-trip cost; rent as % of position | cost model (computed) | Now |
| B2 | Why pools are rejected | rejects per filter on the pools downloaded so far | candles + filters | Now |
| B3 | Watchlist | every downloaded pool x every filter, pass/fail per filter, the blocking filter | candles + filters | Now |
| B4 | Backtest results | trades, net P&L, profit factor, drawdown, win rate, exit mix, equity curve | backtest.json | Task 1 (when download ends) |
| B5 | Edge test | signal mean vs random-entry distribution, bootstrap CI | backtest.json | Task 1 |
| B6 | Calibration | in-sample vs out-of-sample, number of combos tried, chosen plateau | calibration.json | Task 3 |
| B7 | Cost sensitivity | pessimistic / base / optimistic P&L | backtest.json | Task 4 |
| B8 | Readiness checklist | every gate before live trading, pass / pending / fail | tasks + results | Now |

## C. Evidence quality (Data tab)
| # | Module | Shows | When |
|---|---|---|---|
| C1 | Coverage + ETA | pools and candles downloaded, rate, time left | Now |
| C2 | Funnel and liquidity bands | pools surviving each rule | Now |
| C3 | Bias and data-quality panel | survivorship share, filters not evaluable historically, look-ahead proxies, candle range, source mix | Now |
| C4 | Source mix and per-source pass rate | which discovery source finds tradable pools | Task 2 |
| C5 | Pool explorer | search, filter, sort, copy as CSV | Now |

## D. Safety and transparency
| # | Module | Shows | When |
|---|---|---|---|
| D1 | Hard limits and switches | live flag, kill file, size, max open, daily loss | Now |
| D2 | Rule book | every threshold with its plain-language reason | Now |
| D3 | Pipeline | six steps with build status | Now |
| D4 | Source health | every API probed, latency | Now |
| D5 | Journal | decisions and results, newest first | Now |
| D6 | Glossary | profit factor, drawdown, slippage, look-ahead, survivorship, walk-forward, out-of-sample, null model, Token-2022, rent | Now |
| D7 | Incidents | API failures, rate limits, cycle errors | Task 2 |

## Rules for every module
Every number shows its source and its scope (today's liquidity vs historical; downloaded pools vs all). Negative and inconclusive results get the
same prominence as positive ones. Every chart has a table view. No dashed gridlines, no serif figures, text >= 13px, touch targets >= 44px.
Built from a template plus JSON snapshots; verified by screenshots at 1280 and 390 px in light and dark before each publish.

## Build order
1. This turn: A1, A2 (deltas), A6, B1, B2, B3, B8, C3, D6 (all computable now), plus empty-state layouts for B4/B5.
2. When the download ends: B4/B5 from the real backtest.
3. Tasks 2-4: A3-A5, C4, B6, B7, D7.
