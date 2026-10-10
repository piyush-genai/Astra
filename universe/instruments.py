"""
Instrument registry — all tradeable instruments in the Astra universe.

Covers:
  - NSE Index futures/options: Nifty 50, BankNifty, FinNifty, MidcapNifty
  - Top 20 Nifty 50 large-cap equities (by market cap / liquidity)
  - Equity options on the same large-caps

Add new instruments here; the scanner picks them up automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class InstrumentType(Enum):
    INDEX = "index"
    INDEX_OPTION = "index_option"
    EQUITY = "equity"
    EQUITY_OPTION = "equity_option"


class Exchange(Enum):
    NSE = "NSE"
    NFO = "NFO"   # NSE futures & options segment


@dataclass
class Instrument:
    symbol: str
    name: str
    instrument_type: InstrumentType
    exchange: Exchange
    lot_size: int
    tick_size: float
    strike_step: float = 50.0        # strike interval for options
    expiry_weekday: int = 3          # 0=Mon … 4=Fri; 3=Thursday for most NSE contracts
    upstox_symbol: str = ""          # Upstox API symbol key
    is_active: bool = True
    tags: list[str] = field(default_factory=list)


class InstrumentRegistry:
    """
    Central registry of all instruments Astra can trade.

    Usage:
        registry = InstrumentRegistry()
        indices = registry.get_all(InstrumentType.INDEX)
        options = registry.get_options_universe()
    """

    def __init__(self) -> None:
        self._instruments: list[Instrument] = []
        self._build()

    def get_all(self, instrument_type: Optional[InstrumentType] = None) -> list[Instrument]:
        """Return all active instruments, optionally filtered by type."""
        instruments = [i for i in self._instruments if i.is_active]
        if instrument_type:
            instruments = [i for i in instruments if i.instrument_type == instrument_type]
        return instruments

    def get_options_universe(self) -> list[Instrument]:
        """Return all index and equity options instruments."""
        return [
            i for i in self._instruments
            if i.is_active and i.instrument_type in (InstrumentType.INDEX_OPTION, InstrumentType.EQUITY_OPTION)
        ]

    def get_equity_universe(self) -> list[Instrument]:
        """Return all equity cash instruments."""
        return [i for i in self._instruments if i.is_active and i.instrument_type == InstrumentType.EQUITY]

    def get_index_universe(self) -> list[Instrument]:
        """Return index instruments (for pivot computation)."""
        return [i for i in self._instruments if i.is_active and i.instrument_type == InstrumentType.INDEX]

    def get_by_symbol(self, symbol: str) -> Optional[Instrument]:
        return next((i for i in self._instruments if i.symbol == symbol), None)

    # ------------------------------------------------------------------
    # Registry population
    # ------------------------------------------------------------------

    def _build(self) -> None:
        self._instruments = [
            # ── Indices ────────────────────────────────────────────────
            Instrument("NIFTY",    "Nifty 50",          InstrumentType.INDEX,        Exchange.NSE, lot_size=0,  tick_size=0.05, upstox_symbol="NSE_INDEX|Nifty 50",    tags=["index", "primary"]),
            Instrument("BANKNIFTY","Bank Nifty",         InstrumentType.INDEX,        Exchange.NSE, lot_size=0,  tick_size=0.05, upstox_symbol="NSE_INDEX|Nifty Bank",  tags=["index"]),
            Instrument("FINNIFTY", "Fin Nifty",          InstrumentType.INDEX,        Exchange.NSE, lot_size=0,  tick_size=0.05, upstox_symbol="NSE_INDEX|Nifty Fin Service", tags=["index"]),
            Instrument("MIDCPNIFTY","Midcap Nifty",      InstrumentType.INDEX,        Exchange.NSE, lot_size=0,  tick_size=0.05, upstox_symbol="NSE_INDEX|NIFTY MID SELECT", tags=["index"]),

            # ── Index Options ───────────────────────────────────────────
            Instrument("NIFTY",    "Nifty 50 Options",  InstrumentType.INDEX_OPTION, Exchange.NFO, lot_size=75,  tick_size=0.05, strike_step=50,  expiry_weekday=3, tags=["index_option", "primary"]),
            Instrument("BANKNIFTY","BankNifty Options",  InstrumentType.INDEX_OPTION, Exchange.NFO, lot_size=30,  tick_size=0.05, strike_step=100, expiry_weekday=2, tags=["index_option"]),
            Instrument("FINNIFTY", "FinNifty Options",   InstrumentType.INDEX_OPTION, Exchange.NFO, lot_size=65,  tick_size=0.05, strike_step=50,  expiry_weekday=1, tags=["index_option"]),
            Instrument("MIDCPNIFTY","MidcapNifty Options",InstrumentType.INDEX_OPTION,Exchange.NFO, lot_size=120, tick_size=0.05, strike_step=25,  expiry_weekday=0, tags=["index_option"]),

            # ── Top 20 Nifty 50 Equities (by liquidity) ────────────────
            Instrument("RELIANCE",  "Reliance Industries",     InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("TCS",       "Tata Consultancy Services",InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("HDFCBANK",  "HDFC Bank",               InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("INFY",      "Infosys",                 InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("ICICIBANK", "ICICI Bank",              InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("HINDUNILVR","Hindustan Unilever",       InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("ITC",       "ITC Limited",             InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("SBIN",      "State Bank of India",     InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("BAJFINANCE","Bajaj Finance",            InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("BHARTIARTL","Bharti Airtel",            InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("KOTAKBANK", "Kotak Mahindra Bank",      InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("LT",        "Larsen & Toubro",          InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("AXISBANK",  "Axis Bank",               InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("ASIANPAINT","Asian Paints",             InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("MARUTI",    "Maruti Suzuki",            InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("SUNPHARMA", "Sun Pharmaceutical",       InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("TATAMOTORS","Tata Motors",              InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("WIPRO",     "Wipro",                   InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("ULTRACEMCO","UltraTech Cement",         InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),
            Instrument("POWERGRID", "Power Grid Corporation",   InstrumentType.EQUITY, Exchange.NSE, lot_size=0, tick_size=0.05, tags=["equity", "nifty50"]),

            # ── Equity Options (same large-caps) ───────────────────────
            Instrument("RELIANCE",  "Reliance Options",   InstrumentType.EQUITY_OPTION, Exchange.NFO, lot_size=250,  tick_size=0.05, strike_step=20,  expiry_weekday=3, tags=["equity_option"]),
            Instrument("TCS",       "TCS Options",        InstrumentType.EQUITY_OPTION, Exchange.NFO, lot_size=150,  tick_size=0.05, strike_step=50,  expiry_weekday=3, tags=["equity_option"]),
            Instrument("HDFCBANK",  "HDFC Bank Options",  InstrumentType.EQUITY_OPTION, Exchange.NFO, lot_size=550,  tick_size=0.05, strike_step=10,  expiry_weekday=3, tags=["equity_option"]),
            Instrument("INFY",      "Infosys Options",    InstrumentType.EQUITY_OPTION, Exchange.NFO, lot_size=400,  tick_size=0.05, strike_step=20,  expiry_weekday=3, tags=["equity_option"]),
            Instrument("ICICIBANK", "ICICI Bank Options", InstrumentType.EQUITY_OPTION, Exchange.NFO, lot_size=700,  tick_size=0.05, strike_step=10,  expiry_weekday=3, tags=["equity_option"]),
        ]
