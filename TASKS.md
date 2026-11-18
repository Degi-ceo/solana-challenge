# TASKS (do in order; commit after each; log in JOURNAL.md)

## 0. Network check
Test reachability from this environment of: DexScreener, GeckoTerminal, public Solana RPC, Jupiter (quote-api + lite-api), RugCheck.
Write results to `JOURNAL.md`. If something essential is blocked, stop and tell Kamil which hosts to allow.
**Done when:** a table of host -> status exists in the journal.

## 1. Historical data + backtester
- Pull historical OHLCV (1m/5m/1h) for Solana pools from GeckoTerminal (or best available source) into SQLite/Parquet.
- Build `bot/backtest.py` that replays candles through the *same* `check_filters` / `exit_reason` / cost model as the live loop (no duplicated logic).
- **Survivorship bias:** pool lists only show tokens that still exist. Include dead/rugged pools where possible, or state clearly how the sample is biased.
- Entry point-in-time only: a filter may use only data available at that candle (no look-ahead).
**Done when:** `python3 bot/backtest.py --days 14` prints trades, net PnL after costs, profit factor, max drawdown, and funnel counts; tests cover look-ahead.

## 2. Candidate discovery  <!-- next -->
Current discovery uses DexScreener boosts/profiles (= paid promotion, biased and tiny). Add broader sources (search/trending/top volume,
GeckoTerminal trending/new pools) and tag each candidate with its source so bias can be measured.
**Done when:** funnel report shows candidates per source and pass rates per filter; sample size per cycle is meaningfully larger.

## 3. Calibrate thresholds (without overfitting)
Choose filter/exit thresholds from data with a train/test (walk-forward) split. Report out-of-sample results only for the verdict.
Count how many parameter combinations you tried and say so (multiple-testing). Prefer coarse, robust settings over a sharp optimum.
**Done when:** `docs/CALIBRATION.md` lists chosen thresholds, in-sample vs out-of-sample results, and a plain verdict (edge / no edge / inconclusive).

## 4. Realistic execution simulation
Replace the optimistic fills: model polling latency (stop gaps), slippage from real Jupiter quotes where reachable (or a conservative
impact model otherwise), priority fees, failed/late fills, and token-account rent. Keep costs configurable.
**Done when:** a sensitivity table shows PnL under pessimistic / base / optimistic cost settings.

## 5. Rug / safety checks
Fix the crude on-chain check: Token-2022 extensions (transfer fee, transfer hook, permanent delegate), LP burn/lock status,
proper identification of LP vault vs real holders, RugCheck API cross-check if reachable, sell-simulation via Jupiter quote.
**Done when:** unit tests with fixture responses cover each rejection reason.

## 6. Live executor (written, tested with mocks, DISABLED)
`bot/executor.py`: Jupiter swap build/sign/send with a burner keypair from a file path env var; `"live": false` default; dry-run mode that
builds but doesn't send; hard limits enforced in code (position size, max open, daily loss, KILL file, max slippage).
Do NOT run it with real funds from the web session.
**Done when:** mocked tests prove limits are enforced and that nothing is sent when `live` is false.

## 7. Reporting
`bot/report.py` -> `REPORT.md`: funnel, trades, PnL after costs, drawdown, go/no-go with the thresholds in `config.json`, and a list of caveats.
**Done when:** one command regenerates `REPORT.md` from the DB.

## 8. Deployment notes (for Kamil to run later on the Hetzner VPS)
`docs/DEPLOY.md`: systemd unit for the collector/paper bot, log rotation, a daily cron to run the report, safe key handling, how to flip `live`.
**Done when:** a person can deploy by copy-paste; no secrets in the repo.
