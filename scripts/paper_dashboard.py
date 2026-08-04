#!/usr/bin/env python3
"""
Paper Trading Dashboard

Real-time monitoring dashboard for paper trading.
Shows live stats, recent trades, and capital curve.

Usage:
    python scripts/paper_dashboard.py
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def clear_screen():
    """Clear terminal screen."""
    os.system('clear' if os.name != 'nt' else 'cls')


def get_latest_csv():
    """Find the most recent paper trades CSV."""
    csv_files = sorted(project_root.glob("paper_trades_*.csv"))
    if not csv_files:
        return None
    return csv_files[-1]


def read_status():
    """Read current trading status."""
    status_file = project_root / "TRADING_STATUS.txt"
    if status_file.exists():
        with open(status_file, "r") as f:
            return f.read().strip()
    return "Status file not found"


def check_kill_switch():
    """Check if kill switch is active."""
    kill_switch_file = project_root / "KILL_SWITCH.txt"
    return kill_switch_file.exists()


def format_currency(value):
    """Format currency with Indian style."""
    if value >= 10000000:  # 1 Crore
        return f"₹{value/10000000:.2f}Cr"
    elif value >= 100000:  # 1 Lakh
        return f"₹{value/100000:.2f}L"
    elif value >= 1000:  # 1 Thousand
        return f"₹{value/1000:.1f}K"
    else:
        return f"₹{value:.0f}"


def display_dashboard():
    """Display the monitoring dashboard."""
    clear_screen()
    
    # Header
    print("=" * 100)
    print("📊 ATLAS PAPER TRADING DASHBOARD")
    print("=" * 100)
    print(f"Last Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Status
    status = read_status()
    kill_switch_active = check_kill_switch()
    
    if kill_switch_active:
        print("🛑 KILL SWITCH ACTIVE - Trading Stopped")
    else:
        print("✅ Trading Active")
    
    print(f"📡 Status: {status}")
    print()
    
    # Load latest CSV
    csv_file = get_latest_csv()
    
    if not csv_file:
        print("⚠️  No paper trades CSV found yet")
        print("   Start paper trading with: python scripts/run_paper.py")
        print()
        print("Press Ctrl+C to exit")
        return
    
    # Load data
    df = pd.DataFrame(pd.read_csv(csv_file))
    
    if df.empty:
        print("📝 No trades executed yet today")
        print()
        print("Press Ctrl+C to exit")
        return
    
    # Summary Stats
    print("-" * 100)
    print("📈 SESSION SUMMARY")
    print("-" * 100)
    
    starting_capital = 20000.0
    current_capital = df.iloc[-1]["capital_after"]
    total_pnl = current_capital - starting_capital
    total_trades = len(df)
    winners = len(df[df["net_pnl"] > 0])
    losers = len(df[df["net_pnl"] <= 0])
    win_rate = (winners / total_trades * 100) if total_trades > 0 else 0
    
    # Momentum vs Regular
    momentum_trades = len(df[df["signal_type"] == "momentum"])
    regular_trades = len(df[df["signal_type"] == "regular"])
    
    print(f"Starting Capital:  ₹20,000.00")
    print(f"Current Capital:   {format_currency(current_capital)}")
    print(f"Net P&L:           {format_currency(total_pnl)} ({total_pnl/starting_capital*100:+.1f}%)")
    print()
    print(f"Total Trades:      {total_trades}")
    print(f"Winners:           {winners} ({win_rate:.1f}%)")
    print(f"Losers:            {losers} ({100-win_rate:.1f}%)")
    print(f"Signal Types:      Momentum: {momentum_trades} | Regular: {regular_trades}")
    print()
    
    # Recent Trades (Last 5)
    print("-" * 100)
    print("📋 RECENT TRADES (Last 5)")
    print("-" * 100)
    
    recent = df.tail(5)[["exit_time", "signal_type", "direction", "lots", "entry_premium", 
                          "net_pnl", "exit_reason", "hold_minutes"]].copy()
    
    # Format for display
    recent["exit_time"] = pd.to_datetime(recent["exit_time"]).dt.strftime("%H:%M")
    recent["entry_premium"] = recent["entry_premium"].apply(lambda x: f"₹{x:.0f}")
    recent["net_pnl"] = recent["net_pnl"].apply(lambda x: f"{x:+.0f}")
    recent["hold_minutes"] = recent["hold_minutes"].apply(lambda x: f"{x:.0f}m")
    recent["signal_type"] = recent["signal_type"].apply(lambda x: x[:4].upper())  # MOM or REG
    
    print(recent.to_string(index=False))
    print()
    
    # P&L Distribution
    print("-" * 100)
    print("💰 P&L ANALYSIS")
    print("-" * 100)
    
    winners_df = df[df["net_pnl"] > 0]
    losers_df = df[df["net_pnl"] <= 0]
    
    if len(winners_df) > 0:
        avg_winner = winners_df["net_pnl"].mean()
        max_winner = winners_df["net_pnl"].max()
        total_wins = winners_df["net_pnl"].sum()
    else:
        avg_winner = max_winner = total_wins = 0
    
    if len(losers_df) > 0:
        avg_loser = losers_df["net_pnl"].mean()
        max_loser = losers_df["net_pnl"].min()
        total_losses = losers_df["net_pnl"].sum()
    else:
        avg_loser = max_loser = total_losses = 0
    
    print(f"Avg Winner:        ₹{avg_winner:+.0f}")
    print(f"Max Winner:        ₹{max_winner:+.0f}")
    print(f"Total Wins:        ₹{total_wins:+.0f}")
    print()
    print(f"Avg Loser:         ₹{avg_loser:+.0f}")
    print(f"Max Loser:         ₹{max_loser:+.0f}")
    print(f"Total Losses:      ₹{total_losses:+.0f}")
    print()
    
    profit_factor = abs(total_wins / total_losses) if total_losses != 0 else float('inf')
    print(f"Profit Factor:     {profit_factor:.2f}")
    print()
    
    # Exit Reasons
    print("-" * 100)
    print("🚪 EXIT REASONS")
    print("-" * 100)
    
    exit_counts = df["exit_reason"].value_counts()
    for reason, count in exit_counts.items():
        pct = count / total_trades * 100
        print(f"{reason:15} {count:3d} trades ({pct:5.1f}%)")
    print()
    
    # Hold Time Distribution
    print("-" * 100)
    print("⏱️  HOLD TIME DISTRIBUTION")
    print("-" * 100)
    
    df_copy = df.copy()
    df_copy["hold_bucket"] = pd.cut(
        df_copy["hold_minutes"],
        bins=[0, 5, 15, 30, 60, float('inf')],
        labels=["0-5min", "5-15min", "15-30min", "30-60min", ">60min"]
    )
    
    hold_dist = df_copy.groupby("hold_bucket").agg({
        "net_pnl": ["count", "mean", "sum"]
    })
    
    for bucket in hold_dist.index:
        count = int(hold_dist.loc[bucket, ("net_pnl", "count")])
        avg_pnl = hold_dist.loc[bucket, ("net_pnl", "mean")]
        total_pnl = hold_dist.loc[bucket, ("net_pnl", "sum")]
        pct = count / total_trades * 100
        print(f"{bucket:10} {count:3d} trades ({pct:5.1f}%) | Avg P&L: ₹{avg_pnl:+7.0f} | Total: ₹{total_pnl:+9.0f}")
    print()
    
    # Comparison to Backtest
    print("-" * 100)
    print("📊 BACKTEST COMPARISON")
    print("-" * 100)
    
    backtest_wr = 25.4
    backtest_trades_per_day = 9.9
    
    # Calculate trades per day (assuming 6.5 hour trading day)
    if total_trades > 0:
        # Estimate based on first and last trade times
        first_trade_time = pd.to_datetime(df.iloc[0]["exit_time"])
        last_trade_time = pd.to_datetime(df.iloc[-1]["exit_time"])
        hours_traded = (last_trade_time - first_trade_time).total_seconds() / 3600
        if hours_traded > 0:
            trades_per_day = total_trades / (hours_traded / 6.5)
        else:
            trades_per_day = 0
    else:
        trades_per_day = 0
    
    print(f"Win Rate:          {win_rate:.1f}% (Backtest: {backtest_wr:.1f}%)")
    wr_diff = win_rate - backtest_wr
    wr_status = "✅" if abs(wr_diff) < 5 else "⚠️"
    print(f"                   {wr_status} Difference: {wr_diff:+.1f}%")
    print()
    print(f"Trades/Day:        {trades_per_day:.1f} (Backtest: {backtest_trades_per_day:.1f})")
    td_diff = trades_per_day - backtest_trades_per_day
    td_status = "✅" if abs(td_diff) < 3 else "⚠️"
    print(f"                   {td_status} Difference: {td_diff:+.1f}")
    print()
    
    # Footer
    print("=" * 100)
    print("🔄 Auto-refreshing every 10 seconds | Press Ctrl+C to exit")
    print("=" * 100)


def main():
    """Run the dashboard with auto-refresh."""
    print("Starting Paper Trading Dashboard...")
    print("Loading...")
    time.sleep(2)
    
    try:
        while True:
            display_dashboard()
            time.sleep(10)  # Refresh every 10 seconds
    
    except KeyboardInterrupt:
        print("\n\n👋 Dashboard closed")
        sys.exit(0)


if __name__ == "__main__":
    main()
