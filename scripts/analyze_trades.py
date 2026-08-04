#!/usr/bin/env python3
"""
Analyze detailed trade CSV to find bleeding points.
Usage: python scripts/analyze_trades.py compounding_backtest_trades_detailed_2026-02-01.csv
"""

import sys
import pandas as pd
import numpy as np

def analyze_trades(csv_path):
    df = pd.read_csv(csv_path)
    
    print("=" * 100)
    print("TRADE ANALYSIS: Finding Where We're Bleeding Money")
    print("=" * 100)
    print(f"\nTotal trades: {len(df)}")
    print(f"Total net P&L: ₹{df['net_pnl_rs'].sum():,.2f}")
    print()
    
    # 1. MOMENTUM VS REGULAR
    print("=" * 100)
    print("1. MOMENTUM VS REGULAR PERFORMANCE")
    print("=" * 100)
    
    for signal_type in ['momentum', 'regular']:
        subset = df[df['signal_type'] == signal_type]
        if len(subset) == 0:
            continue
        winners = subset[subset['net_pnl_rs'] > 0]
        losers = subset[subset['net_pnl_rs'] <= 0]
        
        print(f"\n{signal_type.upper()}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Winners: {len(winners)} ({100*len(winners)/len(subset):.1f}%)")
        print(f"  Losers: {len(losers)} ({100*len(losers)/len(subset):.1f}%)")
        print(f"  Avg winner: ₹{winners['net_pnl_rs'].mean():.2f}" if len(winners) > 0 else "  Avg winner: N/A")
        print(f"  Avg loser: ₹{losers['net_pnl_rs'].mean():.2f}" if len(losers) > 0 else "  Avg loser: N/A")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
        print(f"  Gross profit: ₹{winners['net_pnl_rs'].sum():,.2f}" if len(winners) > 0 else "  Gross profit: ₹0")
        print(f"  Gross loss: ₹{losers['net_pnl_rs'].sum():,.2f}" if len(losers) > 0 else "  Gross loss: ₹0")
    
    # 2. TIME OF DAY ANALYSIS
    print("\n" + "=" * 100)
    print("2. TIME OF DAY / SESSION ANALYSIS")
    print("=" * 100)
    
    for session in ['MORNING_OPEN', 'MID_MORNING', 'AFTERNOON', 'CLOSING']:
        subset = df[df['session'] == session]
        if len(subset) == 0:
            continue
        winners = subset[subset['net_pnl_rs'] > 0]
        
        print(f"\n{session}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Win rate: {100*len(winners)/len(subset):.1f}%")
        print(f"  Avg P&L: ₹{subset['net_pnl_rs'].mean():.2f}")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
    
    # 3. ZONE TYPE ANALYSIS
    print("\n" + "=" * 100)
    print("3. ZONE TYPE ANALYSIS")
    print("=" * 100)
    
    for zone_type in ['CONFLUENCE', 'DAILY_CPR', 'STRONG_SINGLE', 'OTHER']:
        subset = df[df['zone_type'] == zone_type]
        if len(subset) == 0:
            continue
        winners = subset[subset['net_pnl_rs'] > 0]
        
        print(f"\n{zone_type}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Win rate: {100*len(winners)/len(subset):.1f}%")
        print(f"  Avg P&L: ₹{subset['net_pnl_rs'].mean():.2f}")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
    
    # 4. DIRECTION ANALYSIS
    print("\n" + "=" * 100)
    print("4. DIRECTION ANALYSIS (LONG vs SHORT)")
    print("=" * 100)
    
    for direction in ['LONG', 'SHORT']:
        subset = df[df['direction'] == direction]
        if len(subset) == 0:
            continue
        winners = subset[subset['net_pnl_rs'] > 0]
        
        print(f"\n{direction}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Win rate: {100*len(winners)/len(subset):.1f}%")
        print(f"  Avg P&L: ₹{subset['net_pnl_rs'].mean():.2f}")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
    
    # 5. HOLD DURATION ANALYSIS
    print("\n" + "=" * 100)
    print("5. HOLD DURATION ANALYSIS")
    print("=" * 100)
    
    df['hold_bucket'] = pd.cut(df['hold_minutes'], 
                                bins=[0, 5, 15, 30, 60, 999],
                                labels=['0-5min', '5-15min', '15-30min', '30-60min', '>60min'])
    
    for bucket in ['0-5min', '5-15min', '15-30min', '30-60min', '>60min']:
        subset = df[df['hold_bucket'] == bucket]
        if len(subset) == 0:
            continue
        winners = subset[subset['net_pnl_rs'] > 0]
        
        print(f"\n{bucket}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Win rate: {100*len(winners)/len(subset):.1f}%")
        print(f"  Avg P&L: ₹{subset['net_pnl_rs'].mean():.2f}")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
    
    # 6. EXIT REASON ANALYSIS
    print("\n" + "=" * 100)
    print("6. EXIT REASON ANALYSIS")
    print("=" * 100)
    
    for reason in df['exit_reason'].unique():
        subset = df[df['exit_reason'] == reason]
        winners = subset[subset['net_pnl_rs'] > 0]
        
        print(f"\n{reason}:")
        print(f"  Trades: {len(subset)}")
        print(f"  Win rate: {100*len(winners)/len(subset):.1f}%")
        print(f"  Avg P&L: ₹{subset['net_pnl_rs'].mean():.2f}")
        print(f"  Total P&L: ₹{subset['net_pnl_rs'].sum():,.2f}")
    
    # 7. WORST PERFORMERS
    print("\n" + "=" * 100)
    print("7. TOP 20 WORST TRADES (Biggest Losers)")
    print("=" * 100)
    worst = df.nsmallest(20, 'net_pnl_rs')[['trade_no', 'month', 'signal_type', 'direction', 
                                             'session', 'zone_type', 'hold_minutes', 
                                             'net_pnl_rs', 'exit_reason']]
    print(worst.to_string(index=False))
    
    # 8. SUMMARY RECOMMENDATIONS
    print("\n" + "=" * 100)
    print("8. KEY FINDINGS & RECOMMENDATIONS")
    print("=" * 100)
    
    momentum = df[df['signal_type'] == 'momentum']
    regular = df[df['signal_type'] == 'regular']
    
    morning_open = df[df['session'] == 'MORNING_OPEN']
    
    print("\n🔴 BLEEDING POINTS:")
    
    # Momentum profitability
    if len(momentum) > 0:
        mom_wr = 100 * len(momentum[momentum['net_pnl_rs'] > 0]) / len(momentum)
        mom_pnl = momentum['net_pnl_rs'].sum()
        print(f"  1. Momentum trades: {len(momentum)} trades, {mom_wr:.1f}% win rate, ₹{mom_pnl:,.2f} total")
        if mom_wr < 30:
            print(f"     ⚠️  LOW WIN RATE - Consider raising momentum threshold")
    
    # Morning session
    if len(morning_open) > 0:
        mo_wr = 100 * len(morning_open[morning_open['net_pnl_rs'] > 0]) / len(morning_open)
        mo_pnl = morning_open['net_pnl_rs'].sum()
        print(f"  2. Morning open (9-10am): {len(morning_open)} trades, {mo_wr:.1f}% win rate, ₹{mo_pnl:,.2f} total")
        if mo_pnl < 0:
            print(f"     ⚠️  LOSING SESSION - Consider skipping 9:15-9:45")
    
    # Quick exits
    quick = df[df['hold_minutes'] < 5]
    if len(quick) > 0:
        quick_wr = 100 * len(quick[quick['net_pnl_rs'] > 0]) / len(quick)
        quick_pnl = quick['net_pnl_rs'].sum()
        print(f"  3. Quick exits (<5min): {len(quick)} trades, {quick_wr:.1f}% win rate, ₹{quick_pnl:,.2f} total")
        if quick_pnl < 0:
            print(f"     ⚠️  CHOPPED OUT - Consider wider stops or time filter")
    
    print("\n✅ WHAT'S WORKING:")
    
    # Regular performance
    if len(regular) > 0:
        reg_wr = 100 * len(regular[regular['net_pnl_rs'] > 0]) / len(regular)
        reg_pnl = regular['net_pnl_rs'].sum()
        print(f"  1. Regular breakouts: {len(regular)} trades, {reg_wr:.1f}% win rate, ₹{reg_pnl:,.2f} total")
        if reg_wr > mom_wr:
            print(f"     ✓ BETTER than momentum - Focus on these")
    
    # Longer holds
    longer = df[df['hold_minutes'] >= 20]
    if len(longer) > 0:
        long_wr = 100 * len(longer[longer['net_pnl_rs'] > 0]) / len(longer)
        long_pnl = longer['net_pnl_rs'].sum()
        print(f"  2. Longer holds (≥20min): {len(longer)} trades, {long_wr:.1f}% win rate, ₹{long_pnl:,.2f} total")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_trades.py <csv_file>")
        sys.exit(1)
    
    analyze_trades(sys.argv[1])
