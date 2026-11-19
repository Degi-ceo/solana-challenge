# Event-study report

Generated 2026-11-21 13:41 UTC. Data from 2026-11-18 23:14 UTC to 2026-11-21 13:30 UTC (62.3 h).

## Data coverage

- Launches by status: {'observed': 11435, 'tiny': 7120}
- Observed by class: {'memecoin_confirmed': 1066, 'memecoin_probable': 4071, 'not_memecoin': 48, 'unknown': 6250}
- Detection delay (observed): median 117 s, p90 219 s
- Snapshots taken: 84203, missed (collector not running or late): 4062, pool gone: 0
- Cost probes: 15181; safety reports: 11401
- Stream polls: 2487; polls without overlap (possible missed pools): 95
- Quiet periods over 15 minutes: 0 totalling 0.0 h

## Price-source cross-check

- 27232 snapshots carry both prices; 11.8% disagree by more than 10%.

## Pre-registered tests (population: 5132 memecoin graduates, weeks: 2026-W47)

| id | claim | sample | needed | result |
|---|---|---|---|---|
| H1 | median net return of buying at 24 h (exit 48 h) is negative | 695 | 300 | passes (p = 0.000, Holm 0.000) |
| H2 | gated entry at 15 min (exit 6 h) has positive median and beats the unconditional set | 1040 | 300 | does not pass (p = 1.000, Holm 1.000) |
| H3 | insider-flagged launches have a higher share of net returns <= -50% | 2468 | 300 | does not pass (p = 1.000, Holm 1.000) |
| H4 | launches failing the sell gate have a higher share of un-sellable outcomes | 2468 | 300 | passes (p = 0.000, Holm 0.000) |
| H5 | entry at 6 h after a 50-70% fall from the early peak has a positive median (exit 24 h) | 47 | 300 | inconclusive (sample below the pre-registered minimum) |

Launches excluded from each cell before any statistic (a large 'no_probe' or 'incomplete' count means a collection problem, not a market result):

- H2: ok 2468, not_enterable 111, no_probe 2106, no_entry 93, incomplete 354
- H1: ok 695, not_enterable 252, no_probe 945, no_entry 1653, incomplete 1587
- H5: ok 1820, not_enterable 363, no_probe 1435, no_entry 395, incomplete 1119

Go to paper trading (needs two separate passing weeks): **{'H1': False, 'H2': False, 'H3': False, 'H4': False, 'H5': False}**

- H1 desc: n=695, median -100.0%, trimmed mean -97.8%, share <= -50%: 88%
- H2 desc: n=1040, median -100.0%, trimmed mean -98.8%, share <= -50%: 90%
- H2 desc_baseline: n=2468, median -100.0%, trimmed mean -99.5%, share <= -50%: 91%
- H3 desc_flagged: n=954, median -100.0%, trimmed mean -96.7%, share <= -50%: 88%
- H3 desc_clean: n=1514, median -100.0%, trimmed mean -100.0%, share <= -50%: 93%
- H4 desc_pass: n=1394, median -100.0%, trimmed mean -93.2%, share <= -50%: 85%
- H4 desc_fail: n=1074, median -100.0%, trimmed mean -100.0%, share <= -50%: 99%
- H5 desc: n=47, median -100.0%, trimmed mean -87.2%, share <= -50%: 83%
- H5 desc_baseline: n=1820, median -100.0%, trimmed mean -95.5%, share <= -50%: 86%

Results below the pre-registered minimum sample are descriptive only and say nothing about the claims.

## Paper trading, rule set R1 (H7, forward, exploratory)

- Bankroll $5.00 -> equity $0.59 (net -4.41 USD); closed trades 6, open 0, skipped at the fresh sell gate 1.
- Win rate 17%, mean -0.735 USD per trade (95% bootstrap interval -2.102 to +1.186), median -1.305, best trade +3.28 USD (100% of all gains), max drawdown 5.19 USD.
- Exit reasons: {'liq_drop_unsellable': 2, 'trail': 2, 'liq_drop': 2}. Evidence level: not enough trades (fewer than 30): no statement about an edge.
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
