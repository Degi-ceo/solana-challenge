# Solana $5 Challenge — project context for Claude Code

## What this is
Kamil's one-week experiment: a Phantom (burner) wallet with **$5**, Solana memecoins, goal = make as much as possible in 7 days.
Loss is acceptable; the point is to see **how** it's done end to end (system vs yolo). The honest expectation is no edge / small loss —
the deliverable is a trustworthy system plus a data-backed verdict, not a promise of profit.

## Strategy under test ("strategy A")
Relatively new but "stable" Solana memecoins listed on DexScreener that pass filters (age 2–14 days, liquidity >= $50k, sane vol/liq,
buy pressure, mint/freeze authority revoked, holder concentration), entered after consolidation/breakout, not during a pump.
Everything is a hypothesis to be refuted by data. Do not assume it works.

## Hard rules (never violate)
1. **Never ask for or handle a seed phrase.** Live trading (later, outside this web session) uses a dedicated burner keypair funded with $5 only.
2. **Paper first.** Live execution is OFF by default (`"live": false`); only Kamil flips it, and never inside a Claude Code web session.
3. Risk limits live in code, not in prompts: max position size, max open positions, daily loss limit, KILL file.
4. Do not build or help with token launches, rug pulls or pump-and-dump (dev dumping). Out of scope.
5. Never disable TLS verification, never commit keys, never log private keys.
6. No claim of profitability without out-of-sample evidence. Report negative results plainly.

## Working style
- Kamil writes a Polish/English mix. Chat in Polish; code, comments, docs and deliverables in English.
- He is direct and impatient: work continuously, ship concrete results, don't stop for confirmation on decisions covered by this brief.
- He criticised the first build as "too fast, not thorough". Prioritise rigor over speed: validate, test, write down assumptions.

## Environment (Claude Code on the web, for now)
- Runs in a cloud sandbox from a GitHub repo. No SSH to Kamil's Hetzner VPS from here; deployment is a later step (see task 8).
- **Network is allowlisted by default.** Task 0 is to check what is reachable. Needed hosts: `api.dexscreener.com`, `api.geckoterminal.com`,
  `api.mainnet-beta.solana.com`, `quote-api.jup.ag` / `lite-api.jup.ag`, `api.rugcheck.xyz`. If blocked, tell Kamil to change the
  environment's network access (custom allowlist or full) instead of working around it.
- Existing code in `bot/` is stdlib-only Python 3.13. Keep it dependency-light; add deps only when needed (`solders`, `solana`, `pytest`).
- The earlier cloud session reached DexScreener and public Solana RPC but NOT Jupiter.

## State between sessions
Sessions can be fresh and the web sandbox is ephemeral. **Commit often and keep `JOURNAL.md` updated** (decisions, parameters,
results, open issues). It is the source of truth for continuity.

## Start here
Read `TASKS.md` and `docs/KNOWN_GAPS.md`, then start at task 0. Run `cd bot && python3 -m unittest -v test_bot` before and after changes.
