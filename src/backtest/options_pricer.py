"""
Black-Scholes options pricer for backtest P&L overlay.

Used to estimate ATM option premium at entry and exit time, given:
  - Nifty spot price
  - Strike (rounded to nearest strike_step)
  - Days to expiry
  - Implied volatility (historical estimate or VIX-based)
  - Risk-free rate

This is an approximation — real premium differs due to bid-ask spread,
liquidity, and live IV. But it gives a far more realistic P&L than
raw index-point movement, because it correctly accounts for:
  - Delta (ATM ≈ 0.50, so not 1:1 with index)
  - Theta (time decay while holding)
  - Vega (IV changes)

For paper trading and live, we use actual option chain prices via Upstox API.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Configuration defaults (can be overridden at call site)
# ---------------------------------------------------------------------------

DEFAULT_IV       = 0.14    # ~14% annualised IV (reasonable for Nifty in normal markets)
DEFAULT_RISK_FREE = 0.065  # ~6.5% annualised risk-free rate (approx India 91-day T-bill)


# ---------------------------------------------------------------------------
# Core Black-Scholes functions
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call_price(
    spot: float,
    strike: float,
    T: float,          # time to expiry in years
    r: float,          # risk-free rate (annualised)
    sigma: float,      # implied volatility (annualised)
) -> float:
    """Black-Scholes European call price."""
    if T <= 0:
        return max(0.0, spot - strike)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return spot * _norm_cdf(d1) - strike * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(
    spot: float,
    strike: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """Black-Scholes European put price (via put-call parity)."""
    if T <= 0:
        return max(0.0, strike - spot)
    call = bs_call_price(spot, strike, T, r, sigma)
    return call - spot + strike * math.exp(-r * T)


# ---------------------------------------------------------------------------
# Expiry helpers
# ---------------------------------------------------------------------------

def next_expiry(
    from_date: date,
    expiry_weekday: int,   # 0=Mon … 6=Sun; Nifty weekly = 1 (Tuesday)
) -> date:
    """Return the nearest upcoming expiry on or after from_date."""
    days_ahead = (expiry_weekday - from_date.weekday()) % 7
    return from_date + timedelta(days=days_ahead)


def time_to_expiry_years(
    from_dt: pd.Timestamp,
    expiry_weekday: int,
    market_close_hour: int = 15,
    market_close_minute: int = 30,
) -> float:
    """
    Compute T (years) from a given intraday timestamp to the next expiry.
    Uses calendar days / 365 — simple but adequate for short-dated options.
    
    FIXED: Handles same-day expiry correctly by using real time remaining,
    not collapsing to near-zero floor due to negative delta_days - 1.
    """
    from_date = from_dt.date()
    expiry    = next_expiry(from_date, expiry_weekday)

    # If expiry is today but market has already closed, roll to next week.
    if expiry == from_date:
        mkt_close = from_dt.replace(
            hour=market_close_hour, minute=market_close_minute, second=0, microsecond=0
        )
        if from_dt >= mkt_close:
            expiry = next_expiry(from_date + timedelta(days=1), expiry_weekday)

    delta_days = (expiry - from_date).days
    
    # Add intraday fraction: time remaining today as fraction of a day.
    intraday_hours = (market_close_hour + market_close_minute / 60) - (
        from_dt.hour + from_dt.minute / 60
    )
    intraday_fraction = max(0.0, intraday_hours / 24.0)

    if delta_days == 0:
        # Same-day expiry: T is simply the real fraction of today remaining.
        # Floor at ~15 minutes (1/365/24/4) to avoid division by zero in BS formula,
        # not ~4 minutes-as-days (1/365) which was the bug.
        T_days = max(intraday_fraction, 1 / (365 * 24 * 4))
    else:
        # Multi-day: delta_days - 1 gives full additional days beyond today,
        # plus today's remaining fraction.
        T_days = max(delta_days - 1 + intraday_fraction, 1 / 365)
    
    return T_days / 365.0


# ---------------------------------------------------------------------------
# ATM strike selection
# ---------------------------------------------------------------------------

def atm_strike(spot: float, strike_step: int = 50) -> float:
    """Round spot to nearest strike_step (e.g. 24173 → 24150 with step=50)."""
    return round(spot / strike_step) * strike_step


# ---------------------------------------------------------------------------
# High-level pricer
# ---------------------------------------------------------------------------

@dataclass
class OptionLeg:
    """A single option position (one lot)."""
    option_type: str        # "call" or "put"
    strike: float
    expiry_date: date
    entry_premium: float
    exit_premium: float
    lot_size: int

    @property
    def pnl_per_lot(self) -> float:
        return (self.exit_premium - self.entry_premium) * self.lot_size

    @property
    def pnl_rupees(self) -> float:
        return self.pnl_per_lot  # already per-lot since lot_size is included


class OptionsPricer:
    """
    Prices ATM option legs for the backtest P&L overlay.

    Usage:
        pricer = OptionsPricer(lot_size=65, expiry_weekday=1, strike_step=50)
        leg = pricer.price_trade(
            direction="LONG",
            entry_spot=24150.0, entry_time=...,
            exit_spot=24200.0,  exit_time=...,
        )
        print(leg.pnl_rupees)   # e.g. +₹2,145
    """

    def __init__(
        self,
        lot_size: int,
        expiry_weekday: int,
        strike_step: int = 50,
        iv: float = DEFAULT_IV,
        risk_free_rate: float = DEFAULT_RISK_FREE,
    ) -> None:
        self.lot_size       = lot_size
        self.expiry_weekday = expiry_weekday
        self.strike_step    = strike_step
        self.iv             = iv
        self.r              = risk_free_rate

    def premium(
        self,
        option_type: str,
        spot: float,
        timestamp: pd.Timestamp,
    ) -> float:
        """Compute ATM option premium at a given spot and timestamp."""
        strike = atm_strike(spot, self.strike_step)
        T      = time_to_expiry_years(timestamp, self.expiry_weekday)

        if option_type == "call":
            return bs_call_price(spot, strike, T, self.r, self.iv)
        else:
            return bs_put_price(spot, strike, T, self.r, self.iv)

    def price_trade(
        self,
        direction: str,          # "LONG" or "SHORT"
        entry_spot: float,
        entry_time: pd.Timestamp,
        exit_spot: float,
        exit_time: pd.Timestamp,
        entry_strike: Optional[float] = None,  # override ATM if needed
    ) -> OptionLeg:
        """
        Price a complete trade (entry + exit) using ATM options.
        LONG signal → buy Call, SHORT signal → buy Put.
        """
        option_type = "call" if direction == "LONG" else "put"
        strike = entry_strike or atm_strike(entry_spot, self.strike_step)

        T_entry = time_to_expiry_years(entry_time, self.expiry_weekday)
        T_exit  = time_to_expiry_years(exit_time,  self.expiry_weekday)

        if option_type == "call":
            entry_premium = bs_call_price(entry_spot, strike, T_entry, self.r, self.iv)
            exit_premium  = bs_call_price(exit_spot,  strike, T_exit,  self.r, self.iv)
        else:
            entry_premium = bs_put_price(entry_spot, strike, T_entry, self.r, self.iv)
            exit_premium  = bs_put_price(exit_spot,  strike, T_exit,  self.r, self.iv)

        return OptionLeg(
            option_type   = option_type,
            strike        = strike,
            expiry_date   = next_expiry(entry_time.date(), self.expiry_weekday),
            entry_premium = round(entry_premium, 2),
            exit_premium  = round(exit_premium,  2),
            lot_size      = self.lot_size,
        )
