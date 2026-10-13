# Deployment — EC2 paper trading

Unit files live in the repo so they install with `cp`. Do not paste systemd units
through a terminal heredoc: on 2026-10-13 two consecutive attempts were corrupted by
the paste, producing files that ended `EOFtedBy=multi-user.target` and silently lost
their `StandardOutput` and `[Install]` lines. `systemd-analyze verify` passed anyway —
it only checks that systemd can parse the file, not that the file says what you meant.

## Install

```bash
cd /home/ubuntu/atlas
git pull
mkdir -p logs

sudo cp deploy/astra-paper.service deploy/astra-paper.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now astra-paper.timer
```

## Verify what actually landed

```bash
# Byte-identical to the repo copies? Prints nothing if correct.
diff deploy/astra-paper.service /etc/systemd/system/astra-paper.service
diff deploy/astra-paper.timer   /etc/systemd/system/astra-paper.timer

systemctl list-timers astra-paper.timer     # NEXT should be the next weekday 03:45 UTC
systemctl cat astra-paper.service           # read it; confirm no ExecStartPre=git pull
```

`diff` printing nothing is the only check that proves the content is right.

## Capital, and why it bites

`--capital` seeds the account **only when the state DB is empty**. A `--preflight` run
on an explicit `--db` will seed it, after which `--capital` is permanently ignored and
the circuit-breaker limit is computed from the wrong base — ₹1,500 instead of ₹3,750 at
7.5%.

```bash
# Starting fresh (discards paper history — check for trades first):
sqlite3 astra_paper_state.db 'select count(*) from trades;'   # 0 = safe to delete
rm -f astra_paper_state.db

# Or set it explicitly without losing history:
python3 scripts/run_paper_astra.py --preflight --db astra_paper_state.db --set-capital 50000
```

Since 2026-10-13 `--preflight` defaults to a throwaway `/tmp` DB and no longer touches
real state. Pass `--db` to preflight only when you intend to write to that account.

## Monitoring

```bash
tail -f logs/astra-paper.log                 # session output
journalctl -u astra-paper.service -f         # systemd's view (start/stop/exit codes)
systemctl status astra-paper.service
```

Check the first few lines of a session for `Day-start capital` and the regime state.
`Intraday: no candles yet (market may not be open)` once a minute is normal outside
market hours and on NSE holidays — the timer does not know the holiday calendar.

## Stopping

```bash
sudo systemctl stop astra-paper.timer        # stop future runs
sudo systemctl stop astra-paper.service      # stop the running session
touch /home/ubuntu/atlas/KILL_SWITCH.txt     # hard stop: blocks all order placement
```

`KILL_SWITCH.txt` is checked every loop and overrides everything. If you find one
present, read it before deleting — per AGENTS.md it marks a halt someone meant.
