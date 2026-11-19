# Event-study report

Generated 2026-11-28 14:32 UTC. Data from 2026-11-18 23:14 UTC to 2026-11-28 13:42 UTC (230.5 h).

## Data coverage

- Launches by status: {'late': 279, 'observed': 37059, 'tiny': 24282}
- Observed by class: {'memecoin_confirmed': 6455, 'memecoin_probable': 11082, 'not_memecoin': 205, 'unknown': 19317}
- Detection delay (observed): median 94 s, p90 182 s
- Snapshots taken: 338148, missed (collector not running or late): 10394, pool gone: 0
- Cost probes: 39854; safety reports: 36903
- Stream polls: 10439; polls without overlap (possible missed pools): 305
- Quiet periods over 15 minutes: 4 totalling 1.6 h (2026-11-21 22:19 UTC to 2026-11-21 22:36 UTC, 2026-11-25 20:33 UTC to 2026-11-25 20:49 UTC, 2026-11-25 23:45 UTC to 2026-11-26 00:28 UTC, 2026-11-26 04:43 UTC to 2026-11-26 05:02 UTC)

## Price-source cross-check

- 124618 snapshots carry both prices; 13.3% disagree by more than 10%.

## Pre-registered tests (population: 17506 memecoin graduates, weeks: 2026-W47, 2026-W48)

| id | claim | sample | needed | result |
|---|---|---|---|---|
| H1 | median net return of buying at 24 h (exit 48 h) is negative | 11522 | 300 | passes (p = 0.000, Holm 0.000) |
| H2 | gated entry at 15 min (exit 6 h) has positive median and beats the unconditional set | 5323 | 300 | does not pass (p = 1.000, Holm 1.000) |
| H3 | insider-flagged launches have a higher share of net returns <= -50% | 13816 | 300 | does not pass (p = 1.000, Holm 1.000) |
| H4 | launches failing the sell gate have a higher share of un-sellable outcomes | 13816 | 300 | passes (p = 0.000, Holm 0.000) |
| H5 | entry at 6 h after a 50-70% fall from the early peak has a positive median (exit 24 h) | 409 | 300 | does not pass (p = 1.000, Holm 1.000) |

Launches excluded from each cell before any statistic (a large 'no_probe' or 'incomplete' count means a collection problem, not a market result):

- H2: ok 13840, not_enterable 1025, no_probe 2106, no_entry 142, incomplete 393
- H1: ok 11522, not_enterable 1715, no_probe 945, no_entry 1895, incomplete 1429
- H5: ok 12489, not_enterable 2028, no_probe 1435, no_entry 473, incomplete 1081

Go to paper trading (needs two separate passing weeks): **{'H1': True, 'H2': False, 'H3': False, 'H4': True, 'H5': False}**

- H1 desc: n=11522, median -100.0%, trimmed mean -91.2%, share <= -50%: 82%
- H2 desc: n=5323, median -100.0%, trimmed mean -93.1%, share <= -50%: 84%
- H2 desc_baseline: n=13840, median -100.0%, trimmed mean -96.8%, share <= -50%: 88%
- H3 desc_flagged: n=5777, median -100.0%, trimmed mean -94.0%, share <= -50%: 85%
- H3 desc_clean: n=8039, median -100.0%, trimmed mean -98.6%, share <= -50%: 89%
- H4 desc_pass: n=7648, median -100.0%, trimmed mean -86.3%, share <= -50%: 79%
- H4 desc_fail: n=6168, median -100.0%, trimmed mean -100.0%, share <= -50%: 99%
- H5 desc: n=409, median -100.0%, trimmed mean -87.3%, share <= -50%: 79%
- H5 desc_baseline: n=12489, median -100.0%, trimmed mean -90.6%, share <= -50%: 82%

Results below the pre-registered minimum sample are descriptive only and say nothing about the claims.

## Paper trading, rule set R1 (H7, forward, exploratory)

- Bankroll $5.00 -> equity $0.59 (net -4.41 USD); closed trades 6, open 0, skipped at the fresh sell gate 1.
- Win rate 17%, mean -0.735 USD per trade (95% bootstrap interval -2.102 to +1.186), median -1.305, best trade +3.28 USD (100% of all gains), max drawdown 5.19 USD.
- Exit reasons: {'liq_drop': 2, 'trail': 2, 'liq_drop_unsellable': 2}. Evidence level: not enough trades (fewer than 30): no statement about an edge.
  - AI / SOL: liq_drop_unsellable, -2.500 USD, held 0.7 h
  - AMD / SOL: liq_drop, -2.500 USD, held 0.4 h
  - Apocrycoin / SOL: trail, -0.077 USD, held 0.3 h
  - AudaCity / SOL: trail, -0.111 USD, held 0.2 h
  - NEX Ai / SOL: liq_drop, +3.280 USD, held 0.7 h
  - Green Cat / SOL: liq_drop_unsellable, -2.500 USD, held 0.6 h

## Caveats

- Observational data from public APIs; no trades were made. Quotes are not executed fills.
- Only pools listed by the data source are seen; detection delay is recorded per launch and the unit is the first observed pool per token.
- Prices come from GeckoTerminal; a second price from DexScreener is stored as a cross-check, never used in the primary tests.
- The analysis rules are in docs/PREREGISTRATION.md (amendments A1-A5). Anything not listed there is exploratory.
- Weeks with no collector running are gaps, recorded and never filled.
