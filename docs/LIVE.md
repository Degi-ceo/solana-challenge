# Going live: what exists, how to run it, what is NOT verified

**Read this fully before putting any money in.** Paper trading comes first (see `REPORT.md` and the dashboard). Real trading can lose the whole amount. Nothing here predicts profit, and the evidence level is stated by the report, not promised.

## What is built (all in this repository, all tested with mocks, switched OFF by default)
- `bot/executor.py`: quotes, builds, **validates**, simulates, signs, sends and confirms Jupiter swaps; closes the empty token account afterwards to get the rent back.
- `bot/live.py`: the live engine. It takes the same signals as the paper engine (rule set R1) and executes them through the executor. Paper trading keeps running next to it, so real and paper fills can be compared.
- Safety in code, not in prompts. Hard caps live in `executor.CAPS`; `config.json` can only make them stricter.

## Rules that cannot be bypassed from configuration
1. **Never from an agent sandbox.** The executor refuses when it detects one (`CLAUDE_CODE*`, `CCR_*`, `AI_AGENT`, `/root/.ccr`). This project's hard rule: nobody asks for or handles your key, and live trading is only ever started by you, on your machine.
2. **All four must be true** or no transaction can be signed or sent: `config.json` has `"live": true`; env `CONFIRM_LIVE=yes-burner-only`; env `BURNER_KEYPAIR_PATH` points to a keypair file; the machine is not a sandbox.
3. **Burner wallet only.** The wallet must hold at most $15 (a stricter cap than the $25 in code); otherwise every entry is refused ("does not look like a burner wallet").
4. **The transaction is inspected before signing.** Only known programs; you are the only signer and the fee payer; no transfer to any address except your own wrapped-SOL account; token accounts opened and closed only for you. A compromised or malicious API answer is refused, not signed.
5. **Limits:** $2.50 per position, at most 2 open, daily loss limit $1.50, slippage cap 3%, price-impact cap, always keep 0.01 SOL for fees. A `KILL` file next to `bot.py` stops new entries; exits keep working.
6. **The keypair file** must be outside the repository, owner-only (`chmod 600`), in Solana CLI format. It is never printed, copied or logged. No seed phrase is ever read.

## Steps (on your own computer)
```bash
git clone https://github.com/Degi-ceo/solana-challenge.git && cd solana-challenge
pip install solders                      # the only extra dependency, needed for signing and for dry-run checks
```
1. **Make a NEW burner key. Do not use your main wallet and do not paste a seed phrase anywhere.**
   ```bash
   python3 -c "from solders.keypair import Keypair; import json, os; kp = Keypair(); p = os.path.expanduser('~/burner.json'); open(p, 'w').write(json.dumps(list(bytes(kp)))); os.chmod(p, 0o600); print('address:', kp.pubkey())"
   ```
   Send about $5 of SOL plus 0.02 SOL for fees to that address from your own wallet. Keep the file private; losing it loses the money, sharing it gives the money away.
2. **Dry run first, at least a day.** This needs only the PUBLIC address and sends nothing:
   ```bash
   export BURNER_PUBKEY=<the address printed above>
   python3 bot/live.py check                           # preflight list; says what is missing
   LIVE_ENGINE=dry python3 bot/launches.py run         # collector + engine that quotes, builds, validates and SIMULATES swaps
   ```
   You should see `LIVE-DRY would buy ...` lines. If you never see them, no candidate passed the gates yet, which is normal.
3. **Optional but recommended: your own RPC endpoint.** The public one is rate-limited. `export SOLANA_RPC_URL=...` (a key inside the URL stays in your shell, never in the repository).
4. **Live, only when you decide to:**
   ```bash
   # config.json: "live": true
   export CONFIRM_LIVE=yes-burner-only
   export BURNER_KEYPAIR_PATH=~/burner.json
   python3 bot/live.py check                           # must end with: REAL TRADING WOULD BE ALLOWED
   LIVE_ENGINE=live python3 bot/launches.py run
   ```
5. **Watch it:** `python3 bot/live.py positions`, the log lines `LIVE OPEN` / `LIVE CLOSE`, and compare with the paper results.
6. **Stop:** create a file named `KILL` next to `bot.py` (no new entries, exits continue). If you stop the program, open positions stay in the wallet: sell them yourself in your wallet app or on Jupiter. There is no automatic liquidation command yet.

## Not verified (cannot be checked from the sandbox)
- Real transaction landing, failure rates and fees on mainnet: the code was never run with a funded wallet. **Run the dry mode first, then start with the smallest size.**
- The unit of Jupiter's `priceImpactPct` is not documented to me; the cap treats it as a fraction (stricter). The swap request parameters were checked against the live API, not against its documentation (the docs host was blocked).
- Sandwiching and MEV on small swaps; the quoted costs are quotes, not fills. Paper results use quotes, so real results will usually be a little worse.
- Closing token accounts for Token-2022 tokens; the safety gates exclude the risky extensions, but this path was only tested with mocks.
- The agent-sandbox detection is best-effort; it is not a security boundary against someone who edits the code. It is a guard against accidents.

## What would make me advise against going live
Fewer than 30 closed paper trades; a 95% interval of the mean net return per trade that includes zero; almost all gains from a single trade; or quiet periods and stream gaps in the report that suggest the data are incomplete. The decision is yours; the report states the evidence level.
