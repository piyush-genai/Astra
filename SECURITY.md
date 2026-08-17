# Security & Credentials

## Environment Variables

This project uses `.env` for secret management. **Never commit `.env` to Git.**

### Setup Instructions

1. **Copy the template**:
   ```bash
   cp .env.example .env
   ```

2. **Fill in your credentials** from [Upstox Developer Portal](https://developer.upstox.com/):
   - Analytics Token: Developer Console > Analytics tab (valid 1 year)
   - Sandbox Credentials: Developer Console > Sandbox tab
   - Live Credentials: Developer Console > Live tab ⚠️ **Use only in production**

3. **Verify `.env` is ignored**:
   ```bash
   git check-ignore .env
   # Should output: .env
   ```

## Token Types

### Analytics Token
- **Purpose**: Read-only market data access (OHLCV, LTP, option chains)
- **Validity**: 1 year
- **Scope**: Historical data, WebSocket feed
- **Safety**: Safe for development and backtesting

### API Keys (Sandbox)
- **Purpose**: OAuth authentication for sandbox testing
- **Environment**: Simulated order book, real market data via Analytics Token
- **Safety**: Safe for development, no real money at risk

### API Keys (Live)
- **Purpose**: Production trading with real capital
- **Environment**: Real order execution
- **Safety**: ⚠️ **Only use when ready for live trading**

### Telegram Bot Token
- **Purpose**: Kill switch and trade alerts
- **Optional**: System works without Telegram integration
- **Setup**: Create bot via [@BotFather](https://t.me/botfather)

## Security Best Practices

### Never Commit Secrets
- ✅ `.env` is in `.gitignore` - Git will ignore it automatically
- ❌ Never run `git add .env`
- ❌ Never run `git commit -a` without checking `git status` first
- ✅ Use `.env.example` for documentation

### Token Rotation Schedule
- **Analytics Token**: Rotate every 6 months (expires automatically after 1 year)
- **API Keys**: Rotate annually
- **Telegram Bot**: Rotate on any suspected exposure

### If a Token is Compromised

1. **Revoke immediately** in Upstox developer portal
2. **Generate new token**
3. **Update `.env`** locally and on EC2
4. **Restart processes**: `pkill -f run_paper.py && python scripts/run_paper.py`

### Verification

Check that `.env` is properly ignored:
```bash
git status --porcelain .env
# Expected: (empty output - file is ignored)

git check-ignore -v .env
# Expected: .gitignore:11:.env	.env
```

## Deployment (EC2)

When deploying to EC2, follow the same process:
1. Copy `.env.example` to `.env` on the remote server
2. Fill in production credentials
3. Never commit the EC2 `.env` back to Git
4. Use separate tokens for development vs production

See [EC2_SETUP.md](EC2_SETUP.md) for detailed deployment instructions.
