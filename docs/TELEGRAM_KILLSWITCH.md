# 🤖 Telegram Kill Switch Setup

## What is a Kill Switch?

A **kill switch** lets you **instantly stop trading** from your phone via Telegram:

- ✅ Stop new trades immediately
- ✅ Close any open positions
- ✅ Works from anywhere (just need Telegram on phone)
- ✅ Required by Rule 5 in `trading-risk-rules.md`

---

## Architecture

```
You (Phone) → Telegram Bot → EC2 Instance → Paper Trading Script → STOP
```

The bot creates a file called `KILL_SWITCH.txt`. The paper trading script checks for this file every loop. If found, it stops trading.

---

## Setup Steps

### 1. Create Telegram Bot

**On your phone/computer:**

1. Open Telegram
2. Search for `@BotFather`
3. Send `/newbot`
4. Choose a name: "Atlas Trading Bot"
5. Choose a username: "atlas_trading_bot" (must be unique, try variations if taken)
6. **Save the API token** - looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`

### 2. Get Your Chat ID

**Still in Telegram:**

1. Search for `@userinfobot`
2. Send `/start`
3. It will reply with your user ID
4. **Save this number** - this is your Chat ID (e.g., `987654321`)

### 3. Install Telegram Bot on EC2

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@YOUR_ELASTIC_IP

# Activate venv
cd ~/atlas
source venv/bin/activate

# Install python-telegram-bot
pip install python-telegram-bot==20.7

# Update requirements
pip freeze > requirements.txt
```

### 4. Add Bot Credentials to .env

```bash
# On EC2:
nano .env

# Add these lines:
TELEGRAM_BOT_TOKEN=your_bot_token_from_step_1
TELEGRAM_CHAT_ID=your_chat_id_from_step_2

# Save and exit
```

### 5. Create Kill Switch Bot Script

Create `scripts/telegram_bot.py`:


---

## Testing the Kill Switch

### 1. Start Telegram Bot on EC2

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@YOUR_ELASTIC_IP

# In a separate tmux window:
tmux new -s telegram_bot
cd ~/atlas
source venv/bin/activate
python scripts/telegram_bot.py

# Detach: Ctrl+B, then D
```

### 2. Test Commands from Phone

Open Telegram on your phone, find your bot:

```
/start
# Should reply with welcome message

/status
# Should show trading status

/kill
# Should activate kill switch

/status
# Should confirm trading stopped

/resume
# Should clear kill switch
```

### 3. Verify Kill Switch Works

```bash
# Start paper trading (in another tmux window)
tmux new -s paper_trading
cd ~/atlas
source venv/bin/activate
python scripts/run_paper.py --duration 10

# From phone, send: /kill
# Check EC2 logs - should stop within 30 seconds
```

---

## Production Setup (Both Bots Running)

### Using tmux (2 sessions):

```bash
# Session 1: Paper Trading
tmux new -s paper_trading
cd ~/atlas
source venv/bin/activate
python scripts/run_paper.py
# Detach: Ctrl+B, D

# Session 2: Telegram Bot
tmux new -s telegram_bot
cd ~/atlas
source venv/bin/activate
python scripts/telegram_bot.py
# Detach: Ctrl+B, D

# List sessions:
tmux ls

# Reattach to check:
tmux attach -t paper_trading
tmux attach -t telegram_bot
```

### Using systemd (Production - Both Services):

**1. Create Telegram Bot Service:**

```bash
sudo nano /etc/systemd/system/telegram-bot.service
```

Add:

```ini
[Unit]
Description=Atlas Telegram Kill Switch Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/atlas
Environment="PATH=/home/ubuntu/atlas/venv/bin"
ExecStart=/home/ubuntu/atlas/venv/bin/python /home/ubuntu/atlas/scripts/telegram_bot.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**2. Enable Both Services:**

```bash
# Enable telegram bot
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service

# Enable paper trading (from EC2_SETUP.md)
sudo systemctl enable paper-trading.service
sudo systemctl start paper-trading.service

# Check both are running:
sudo systemctl status telegram-bot.service
sudo systemctl status paper-trading.service
```

---

## Daily Usage

### Morning (Before Market):

```
📱 Telegram: /status
# Confirm bot is responding

🖥️ EC2: Check logs
sudo journalctl -u paper-trading.service -f
sudo journalctl -u telegram-bot.service -f
```

### During Market (If Needed):

```
📱 Emergency Stop:
/kill

# Paper trading stops within 30 seconds
# Positions closed at market

# To resume later:
/resume
# Then SSH and restart paper trading script
```

### After Market:

```
📱 Check final status:
/status

🖥️ Download results:
scp ubuntu@YOUR_ELASTIC_IP:~/atlas/paper_trades_*.csv .
```

---

## Kill Switch Scenarios

### Scenario 1: Something Looks Wrong

```
📱 You: /kill
🤖 Bot: Kill switch activated!
        Paper trading will stop within 30s

# Check what happened:
ssh ubuntu@YOUR_ELASTIC_IP
tmux attach -t paper_trading
# Review logs
```

### Scenario 2: Internet Issues

```
# Kill switch works ONLY if:
# 1. EC2 instance is reachable
# 2. Telegram bot is running
# 3. EC2 has internet

# If EC2 is down:
# - Paper trading will auto-stop (no data)
# - You need to SSH in to restart
```

### Scenario 3: Testing Kill Switch

```
# Don't test during real market hours!
# Test on weekends or after hours:

📱 /kill
# Wait 1 minute
📱 /status  # Should show stopped
📱 /resume
🖥️ Restart paper trading manually
```

---

## Security Best Practices

### 1. Keep Bot Token Secret

```bash
# Never commit to Git
echo "TELEGRAM_BOT_TOKEN" >> .gitignore
echo "TELEGRAM_CHAT_ID" >> .gitignore

# If accidentally exposed:
1. Go to @BotFather
2. Send /revoke
3. Select your bot
4. Generate new token
5. Update .env
```

### 2. Restrict Bot Access

The bot only responds to YOUR chat ID. Even if someone finds your bot username, they can't control it.

```python
# This is built into telegram_bot.py
# Bot only processes commands from TELEGRAM_CHAT_ID
```

### 3. Monitor Bot Logs

```bash
# Check for unauthorized access attempts
sudo journalctl -u telegram-bot.service | grep -i "unauthorized"
```

---

## Troubleshooting

### Issue 1: Bot doesn't respond

```bash
# Check if bot is running
sudo systemctl status telegram-bot.service

# Check logs
sudo journalctl -u telegram-bot.service -n 50

# Common fixes:
# - Invalid token: Update .env
# - Wrong chat ID: Use @userinfobot again
# - Bot not started: sudo systemctl start telegram-bot.service
```

### Issue 2: Kill switch doesn't work

```bash
# Check if KILL_SWITCH.txt was created
ls -la ~/atlas/KILL_SWITCH.txt

# Check if paper trading is checking for it
# (It checks every 30 seconds in the main loop)

# Manual kill switch (if bot fails):
ssh ubuntu@YOUR_ELASTIC_IP
touch ~/atlas/KILL_SWITCH.txt
```

### Issue 3: Can't resume trading

```bash
# After /resume, you must manually restart:
ssh ubuntu@YOUR_ELASTIC_IP
tmux attach -t paper_trading
# If stopped, restart:
python scripts/run_paper.py
```

---

## Telegram Bot Commands Reference

| Command | Description | Use Case |
|---------|-------------|----------|
| `/start` | Initialize bot | First time setup |
| `/status` | Check trading status | Daily check-in |
| `/kill` | STOP trading immediately | Emergency stop |
| `/resume` | Clear kill switch | After manual stop |
| `/help` | Show commands | Reference |

---

## Next Steps

1. [ ] Create Telegram bot with @BotFather
2. [ ] Get your Chat ID from @userinfobot  
3. [ ] Add credentials to EC2 .env file
4. [ ] Install python-telegram-bot on EC2
5. [ ] Test bot commands
6. [ ] Set up systemd services (or use tmux)
7. [ ] Test kill switch during off-hours

---

## Integration with Live Trading

When you move from paper to live trading:

1. **Same bot** - No changes needed
2. **Same commands** - /kill, /status work identically
3. **Add monitoring** - Bot can send you daily P&L reports
4. **Add alerts** - Bot can alert on large losses

See `LIVE_TRADING_SETUP.md` (to be created after paper trading passes) for advanced features.

---

**You're now ready to run paper trading on EC2 with kill switch!** 🚀

Test everything during off-hours before running in live market.
