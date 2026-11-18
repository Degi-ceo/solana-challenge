# TASKS (revised 2026-11-18 after the memecoin research; see docs/RESEARCH_MEMECOIN_SYSTEM.md)

Done earlier: 0 network check; 1 backtester engine (universe was contaminated, kept only for price-path questions); 2 tagged discovery + collector.

## 3. Memecoin classifier and universe  (replaces "calibration")
Classify every candidate: confirmed / probable / not_memecoin / unknown, with the reason stored. Age = time since graduation AND token launch time where known.
**Done when:** unit tests cover each class; the existing 211 pools are re-classified and the counts and examples are in the journal.

## 4. Graduation stream + fixed-age snapshots  (`bot/launches.py`)
Poll GeckoTerminal new_pools every 2 minutes (10 pages), keep non-curve pools, de-duplicate, classify, then snapshot each at fixed ages; Jupiter cost probes; one RugCheck full report.
Record detection delay and stream gaps. **Done when:** mocked tests pass and a live run in the sandbox records graduates with snapshots, probes and safety fields.

## 5. Event-study analysis  (`bot/eventstudy.py`)
Implements `docs/PREREGISTRATION.md` exactly: returns, baseline, bootstrap, Holm, minimum sample, "inconclusive" handling. **Done when:** tests on synthetic data show it detects a planted effect,
does not invent one in noise, and reports inconclusive below the minimum n.

## 6. Realistic paper execution + safety gates
Quote-based fills at decision time, measured network fee, failure probability, position-size choice; RugCheck/Token-2022/sell gates as code with fixture tests. Only for rules that passed task 5.

## 7. Live executor (written, mocked, DISABLED)  `bot/executor.py` on `api.jup.ag`. Never run with real funds from the web session.

## 8. Reporting and dashboard  `bot/report.py` -> REPORT.md; dashboard shows the stream, per-age samples and the pre-registered tests.

## 9. Deployment notes  `docs/DEPLOY.md`: run the graduation collector on the VPS first (data only grows with time), then the rest.
