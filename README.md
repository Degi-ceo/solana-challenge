# solana-challenge

Paper-trading harness for a one-week, $5 Solana memecoin experiment (strategy A: filtered, relatively new but "stable" tokens from DexScreener).

```
CLAUDE.md          context + hard rules for Claude Code
TASKS.md           ordered work plan with acceptance criteria
PROMPT.md          starter prompt to paste into Claude Code
JOURNAL.md         running log / source of truth between sessions
docs/KNOWN_GAPS.md honest list of what is weak in the first build
bot/               bot.py (paper trader), config.json, test_bot.py
```

Quick check: `cd bot && python3 -m unittest -v test_bot` (12 tests), `python3 bot.py once`, `python3 bot.py report`.

Setup for Claude Code web: push this folder to a **private** GitHub repo, open it in Claude Code on the web, and in the environment settings
allow network access to `api.dexscreener.com`, `api.geckoterminal.com`, `api.mainnet-beta.solana.com`, `quote-api.jup.ag`,
`lite-api.jup.ag`, `api.jup.ag`, `api.rugcheck.xyz`. Never commit keys; `.gitignore` already excludes databases and key files.
