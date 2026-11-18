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
