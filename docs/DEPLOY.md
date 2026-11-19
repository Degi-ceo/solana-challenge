# Deployment notes (collectors first; full deployment in task 9)

Why now: the verdict needs forward, point-in-time data, and that only accumulates with wall-clock time. The web sandbox is ephemeral, so
start the collector on the VPS as early as possible. It places **no trades and needs no keys**.

## Start the collector (copy-paste, Linux with Python 3.11+)

```bash
git clone https://github.com/Degi-ceo/solana-challenge.git /opt/solana-challenge
cd /opt/solana-challenge/bot
python3 -m unittest -v test_bot test_backtest test_discovery   # 48 tests must pass
python3 bot.py collect --once                                  # one cycle, prints per-source counts
```

systemd unit `/etc/systemd/system/sol-collector.service`:

```ini
[Unit]
Description=Solana paper bot data collector (no trading)
After=network-online.target

[Service]
WorkingDirectory=/opt/solana-challenge/bot
ExecStart=/usr/bin/python3 bot.py collect
Restart=always
RestartSec=30
User=solbot

[Install]
WantedBy=multi-user.target
```

```bash
sudo useradd --system --create-home solbot && sudo chown -R solbot /opt/solana-challenge
sudo systemctl daemon-reload && sudo systemctl enable --now sol-collector
journalctl -u sol-collector -f                  # live log
cd /opt/solana-challenge/bot && python3 bot.py funnel   # per-source pass rates from collected snapshots
```

## What it writes
`bot/paper.db` (SQLite, ignored by git): `snapshots` (every candidate every 5 minutes with its features and which filters it failed),
`funnel_src` (per-source counts), `funnel`. About 90k rows per day. Back it up with `sqlite3 paper.db ".backup /backups/paper.db"`.

## Safety
No wallet, no keys, no transactions in collector mode (`cycle(..., trade=False)`). `live` stays `false` in `config.json`.
Create a file named `KILL` next to `bot.py` to stop new paper entries (the collector keeps collecting).

## Graduation collector (the one that matters for the verdict)

`bot/launches.py` watches every new non-curve pool, classifies it, snapshots it at fixed ages (1, 5, 15, 30, 60 min, 2, 6, 24, 48, 72 h), takes Jupiter cost probes (quotes only) and one
RugCheck report per launch. It is read-only: no wallet, no keys, no transactions. Rules for analysing the data are fixed in `docs/PREREGISTRATION.md`.

```ini
# /etc/systemd/system/sol-graduates.service
[Unit]
Description=Solana graduation collector (read-only)
After=network-online.target

[Service]
WorkingDirectory=/opt/solana-challenge/bot
ExecStart=/usr/bin/python3 launches.py run
Restart=always
RestartSec=30
User=solbot

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now sol-graduates
cd /opt/solana-challenge/bot && python3 launches.py stats       # counts, detection delay, snapshots by age, stream gaps
sqlite3 launches.db ".backup /backups/launches.db"              # daily backup
```

Needs outbound HTTPS to `api.geckoterminal.com`, `api.jup.ag`, `api.rugcheck.xyz`. Keep **one** collector per IP: GeckoTerminal allows roughly one request every 5 seconds
(the code enforces this); a second process would trigger rate-limit errors and gaps. Check `stream gaps` in `stats`: gaps mean pools may have been missed between polls.

## Running the collector without a VPS (options, in order of effort)

The sandbox cannot do it: measured on 2026-11-18, the collector stopped when the container was suspended between turns (last record 16:26, checked at 22:48).
Data only accumulates while a host runs the collector continuously; time with no collector is a gap (recorded, never imputed).

1. **Your own computer** (stdlib Python 3.11+, no installs, no keys): `git clone`, then `cd bot && python3 collect_backup.py restore && python3 launches.py run`. It must stay on and awake;
   every sleep is a gap. Good for the first experiments. Run `python3 collect_backup.py backup` now and then and commit `data/collected/` to keep the data in git.
2. **GitHub Actions** (scheduled long-running job that restores, collects for about 5.5 h, backs up, commits): costs Actions minutes (private repositories have a monthly allowance, public ones do not; check
   your plan) and shared runner IPs may be rate-limited by the data APIs. Not set up: it changes repository usage and needs your decision.
3. **A free-tier cloud VM** from a provider that offers one (account and card verification needed; check current terms).
4. **Scheduled Claude Code sessions** in your cloud environment (hourly, each restoring and backing up the database): works without any host but consumes your Claude usage and leaves small gaps each hour.

## Keeping the data (all hosts)
`python3 bot/collect_backup.py backup` writes a consistent `data/collected/launches.db.gz` plus `MANIFEST.json` (row counts, time range, checksum). `restore` verifies the checksum before restoring.

## GitHub Actions collector (chosen by the user on 2026-11-18, not yet enabled)

`.github/workflows/collector.yml` runs `bot/launches.py` on a GitHub-hosted runner. Each run restores the database from the rolling `data` branch, collects for about 5.5 hours, saves it back
(`bot/ci_persist.py`, one force-pushed commit so the repository does not grow), then starts the next run itself; a cron entry every 6 hours is only a safety net. Concurrency is serialised, so two collectors never run at once.
Expected gap between runs: a few minutes per 5.5 hours. No secrets are needed: the built-in `GITHUB_TOKEN` writes the data branch and starts the next run.

**Before it can work, three things must be true (they are your decisions):**
1. **The workflow file must be on the default branch (`main`).** GitHub runs schedules and manual dispatches only from there. Today `main` holds only the first skeleton; merging pull request #1 puts everything there.
2. **Cost.** The repository is private. A continuous collector uses about 43,000 Actions minutes per month, far above the monthly allowance of a private repository on a personal plan (check your plan; the figure for free accounts is about 2,000 minutes).
   The workflow therefore refuses to run on a private repository unless you set the repository variable `ALLOW_PRIVATE_MINUTES` to `yes`. Two safe ways: make the repository public (standard runners are free for public repositories; the code,
   journal and research become visible, and no keys are in the repository), or accept the usage knowingly and set a spending limit in your GitHub billing settings.
3. **Runner IPs.** GitHub runners use shared cloud addresses that some data APIs rate-limit or block. The first step of every run is a reachability test (`bot/ci_smoke.py`) and fails fast with a clear message if GeckoTerminal, Jupiter or RugCheck cannot be reached [not yet tested on a real runner].

**Controls.** Stop at any time: put a file named `STOP` on the `data` branch (the run in progress finishes, no new run is chained), or disable the workflow in the Actions tab. Start manually: Actions tab, graduation-collector, Run workflow.
**Using the data in a Claude session or locally:** `git fetch origin data`, then `git show origin/data:data/collected/launches.db.gz > data/collected/launches.db.gz` (and `MANIFEST.json`), then `python3 bot/collect_backup.py restore`.

### Added 2026-11-19 (pending merge): hourly saves and a daily report
- The collector now saves to the `data` branch 10 minutes after start and then every hour (it was every 2 hours), so a crashed runner costs at most about an hour.
- `.github/workflows/report.yml` runs the frozen analysis once a day (05:40 UTC) and publishes `REPORT.md` to a separate `report` branch (one rolling commit). It restores a copy of the database and never writes the `data` branch,
  because the collector force-pushes that one. Read it at `https://github.com/Degi-ceo/solana-challenge/blob/report/REPORT.md`.
