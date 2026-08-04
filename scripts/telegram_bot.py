#!/usr/bin/env python3
"""
Telegram Kill Switch Bot

Allows you to stop trading remotely via Telegram commands.

Usage:
    python scripts/telegram_bot.py
"""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Kill switch file path
KILL_SWITCH_FILE = project_root / "KILL_SWITCH.txt"
STATUS_FILE = project_root / "TRADING_STATUS.txt"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message."""
    await update.message.reply_text(
        "🤖 Atlas Trading Bot Active\n\n"
        "Commands:\n"
        "/status - Check trading status\n"
        "/kill - STOP trading immediately\n"
        "/resume - Resume trading\n"
        "/help - Show this message"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Check trading status."""
    if KILL_SWITCH_FILE.exists():
        await update.message.reply_text(
            "🛑 Trading is STOPPED\n\n"
            "Use /resume to restart"
        )
    else:
        # Check if actually running by looking for recent status
        if STATUS_FILE.exists():
            with open(STATUS_FILE, "r") as f:
                last_status = f.read()
            await update.message.reply_text(
                f"✅ Trading is ACTIVE\n\n"
                f"Last update:\n{last_status}\n\n"
                f"Use /kill to stop"
            )
        else:
            await update.message.reply_text(
                "⚠️ Trading status unknown\n\n"
                "Paper trading script might not be running.\n"
                "Check EC2 instance."
            )


async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Activate kill switch."""
    # Create kill switch file
    with open(KILL_SWITCH_FILE, "w") as f:
        f.write(f"KILL SWITCH ACTIVATED\n")
        f.write(f"Time: {update.message.date}\n")
        f.write(f"By: {update.effective_user.username or update.effective_user.id}\n")
    
    logger.warning("🛑 KILL SWITCH ACTIVATED by %s", update.effective_user.username)
    
    await update.message.reply_text(
        "🛑 KILL SWITCH ACTIVATED!\n\n"
        "✅ Stop signal sent\n"
        "✅ Paper trading will stop within 30 seconds\n"
        "✅ Any open positions will be closed\n\n"
        "Use /resume to restart trading\n"
        "Use /status to confirm stopped"
    )


async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deactivate kill switch."""
    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()
        logger.info("✅ Kill switch deactivated by %s", update.effective_user.username)
        
        await update.message.reply_text(
            "✅ Kill switch DEACTIVATED\n\n"
            "Trading will resume on next run.\n\n"
            "⚠️ Note: You need to restart the paper trading script:\n"
            "ssh into EC2 and run:\n"
            "tmux attach -t paper_trading\n"
            "python scripts/run_paper.py"
        )
    else:
        await update.message.reply_text(
            "ℹ️ Kill switch is not active\n\n"
            "Nothing to resume."
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show help message."""
    await update.message.reply_text(
        "🤖 Atlas Trading Bot - Commands:\n\n"
        "/status - Check if trading is active\n"
        "/kill - STOP trading immediately (emergency)\n"
        "/resume - Clear kill switch (must restart script)\n"
        "/help - Show this message\n\n"
        "📝 How it works:\n"
        "The /kill command creates a file that the paper trading script checks.\n"
        "When detected, it stops taking new trades and closes open positions.\n\n"
        "⚠️ Important:\n"
        "- Kill switch stops the current run\n"
        "- To restart, you need to run the script again\n"
        "- Use /resume first to clear the kill switch"
    )


def main() -> None:
    """Start the bot."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment")
        sys.exit(1)
    
    if not allowed_chat_id:
        logger.error("TELEGRAM_CHAT_ID not found in environment")
        sys.exit(1)
    
    # Create the Application
    application = Application.builder().token(token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("kill", kill))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CommandHandler("help", help_command))
    
    # Start the Bot
    logger.info("🤖 Telegram bot started. Listening for commands...")
    logger.info("📱 Authorized chat ID: %s", allowed_chat_id)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
