# ☁️ EC2 Setup for Paper Trading

## Why EC2?

- ✅ Runs 24/7 without laptop
- ✅ Static IP (required for Upstox API whitelisting)
- ✅ Better internet reliability
- ✅ Can SSH in to check status anytime

---

## EC2 Instance Requirements

### Minimum Specs:
- **Instance Type**: t2.micro or t3.micro (sufficient for paper trading)
- **OS**: Ubuntu 22.04 LTS
- **Storage**: 8GB SSD
- **Region**: ap-south-1 (Mumbai) - closest to NSE
- **Network**: VPC with public IP (for static IP)

### Cost Estimate:
- **t2.micro**: ~₹750/month (free tier eligible if new AWS account)
- **t3.micro**: ~₹600/month (better performance)
- **Static IP (Elastic IP)**: Free if attached, ₹300/month if unattached

---

## Setup Steps

### 1. Launch EC2 Instance

```bash
# Via AWS Console:
1. Go to EC2 Dashboard
2. Click "Launch Instance"
3. Choose Ubuntu 22.04 LTS
4. Select t3.micro
5. Create/select key pair (save .pem file!)
6. Security Group: Allow SSH (port 22) from your IP only
7. Launch
```

### 2. Allocate Elastic IP (Static IP)

```bash
# Via AWS Console:
1. Go to EC2 → Elastic IPs
2. Click "Allocate Elastic IP address"
3. Associate it with your EC2 instance
4. Note down the Elastic IP address
```

**IMPORTANT**: Whitelist this Elastic IP on Upstox developer portal!

### 3. Connect to EC2

```bash
# From your laptop:
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@YOUR_ELASTIC_IP
```

### 4. Install Dependencies

```bash
# On EC2:
sudo apt update
sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip git

# Verify Python version
python3.11 --version  # Should show 3.11+
```

### 5. Clone Your Project

```bash
# On EC2:
cd ~
git clone https://github.com/YOUR_USERNAME/atlas.git  # Or use your repo
cd atlas

# Or if you don't have Git repo yet, copy files:
# From laptop, run:
# scp -i your-key.pem -r /home/piyush/workspace/trading/atlas ubuntu@YOUR_ELASTIC_IP:~/
```

### 6. Set Up Virtual Environment

```bash
# On EC2:
cd ~/atlas
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 7. Configure Environment Variables

```bash
# On EC2:
cd ~/atlas

# Copy the template
cp .env.example .env

# Edit with your actual credentials
nano .env  # Or use vim

# Fill in your credentials from Upstox developer portal:
# - UPSTOX_ANALYTICS_TOKEN (from Analytics tab)
# - UPSTOX_SANDBOX_* credentials (from Sandbox tab)
# - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (optional)

# Save and exit (Ctrl+X, Y, Enter)

# Verify .env is not tracked by Git
git check-ignore .env
# Should output: .env
```

### 8. Test Paper Trading

```bash
# On EC2:
source venv/bin/activate
python scripts/run_paper.py --duration 5  # Test for 5 minutes

# If it works, Ctrl+C and proceed to production setup
```

---

## Running Paper Trading on EC2

### Option A: Using tmux (Recommended)

Tmux keeps the session running even if you disconnect.

```bash
# Install tmux
sudo apt install -y tmux

# Start tmux session
tmux new -s paper_trading

# Inside tmux, run paper trading
cd ~/atlas
source venv/bin/activate
python scripts/run_paper.py

# Detach from tmux: Press Ctrl+B, then D
# Session keeps running!

# Reconnect later:
ssh -i your-key.pem ubuntu@YOUR_ELASTIC_IP
tmux attach -t paper_trading

# Stop paper trading:
# Reattach to tmux, press Ctrl+C
```

### Option B: Using systemd service (Production)

Create a service that auto-starts on boot.

```bash
# On EC2, create service file:
sudo nano /etc/systemd/system/paper-trading.service
```

Add this content:

```ini
[Unit]
Description=Atlas Paper Trading
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/atlas
Environment="PATH=/home/ubuntu/atlas/venv/bin"
ExecStart=/home/ubuntu/atlas/venv/bin/python /home/ubuntu/atlas/scripts/run_paper.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable paper-trading.service
sudo systemctl start paper-trading.service

# Check status:
sudo systemctl status paper-trading.service

# View logs:
sudo journalctl -u paper-trading.service -f

# Stop:
sudo systemctl stop paper-trading.service
```

---

## Daily Monitoring Routine

### From Laptop:

```bash
# 1. SSH into EC2
ssh -i your-key.pem ubuntu@YOUR_ELASTIC_IP

# 2. Check if paper trading is running
tmux attach -t paper_trading
# Or for systemd:
sudo systemctl status paper-trading.service

# 3. View logs
tail -f ~/atlas/paper_trades_*.csv

# 4. Check latest trade
ls -lht ~/atlas/paper_trades_*.csv | head -1

# 5. Download results to laptop
# (Exit SSH first)
scp -i your-key.pem ubuntu@YOUR_ELASTIC_IP:~/atlas/paper_trades_*.csv .
```

### Schedule Daily Download:

```bash
# On laptop, create script:
nano ~/download_paper_trades.sh
```

Add:

```bash
#!/bin/bash
scp -i /path/to/your-key.pem ubuntu@YOUR_ELASTIC_IP:~/atlas/paper_trades_$(date +%Y%m%d)_*.csv ~/trading_results/
```

```bash
chmod +x ~/download_paper_trades.sh

# Run daily at 4 PM (after market close):
crontab -e
# Add:
0 16 * * 1-5 /home/piyush/download_paper_trades.sh
```

---

## Troubleshooting EC2

### Issue 1: Can't SSH
```bash
# Check security group allows your current IP
# Your IP might have changed - update security group
```

### Issue 2: Paper trading stopped
```bash
# Check logs
tmux attach -t paper_trading
# Or
sudo journalctl -u paper-trading.service -n 100

# Common causes:
# - Internet disconnected
# - Upstox API down
# - Analytics token expired
```

### Issue 3: Out of memory
```bash
# Check memory usage
free -h

# If low, restart instance:
sudo reboot
```

### Issue 4: Elastic IP not working
```bash
# Verify it's associated with instance
# Check Upstox whitelist includes this IP
```

---

## Cost Optimization

### During Paper Trading (2-4 weeks):
- Use t3.micro: ₹600/month
- Elastic IP: Free (when attached)
- **Total**: ~₹600/month

### After Paper Trading:
- **STOP the instance** when not using
- Elastic IP: ₹300/month even when stopped
- Consider releasing Elastic IP if taking a break

### Before Live Trading:
- Keep instance running 24/7
- Upgrade to t3.small for better reliability
- Set up monitoring and alerts

---

## Security Checklist

- [ ] SSH key is secured (chmod 400)
- [ ] Security group allows SSH only from your IP
- [ ] `.env` file is gitignored (never commit secrets)
- [ ] Elastic IP whitelisted on Upstox
- [ ] Regular backups of trade logs
- [ ] Different credentials for sandbox vs production

---

## Next: Set Up Telegram Kill Switch

See `TELEGRAM_KILLSWITCH.md` for instructions.
