"""
State Manager — SQLite-backed persistence for all trading state.

Replaces capital_state.json from Atlas.
Every write is atomic (single INSERT/UPDATE inside a transaction).
A crash mid-trade will never corrupt state — the DB rolls back automatically.

Tables:
  trades          — completed trade records
  positions       — currently open positions
  capital_history — point-in-time capital snapshots
  regime_log      — daily regime classification log
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Generator, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id            TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    direction     TEXT NOT NULL,
    signal_type   TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    regime        TEXT NOT NULL,
    entry_time    TEXT NOT NULL,
    exit_time     TEXT,
    entry_price   REAL NOT NULL,
    exit_price    REAL,
    lots          INTEGER NOT NULL,
    lot_size      INTEGER NOT NULL,
    pnl           REAL,
    exit_reason   TEXT,
    metadata      TEXT       -- JSON blob
);

CREATE TABLE IF NOT EXISTS positions (
    id            TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    direction     TEXT NOT NULL,
    entry_price   REAL NOT NULL,
    lots          INTEGER NOT NULL,
    stop_loss     REAL NOT NULL,
    entry_time    TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    regime        TEXT NOT NULL,
    is_open       INTEGER NOT NULL DEFAULT 1,
    metadata      TEXT
);

CREATE TABLE IF NOT EXISTS capital_history (
    ts      TEXT PRIMARY KEY,
    capital REAL NOT NULL,
    reason  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regime_log (
    date         TEXT PRIMARY KEY,
    regime       TEXT NOT NULL,
    confidence   REAL,
    features     TEXT    -- JSON blob of feature values
);
"""


class StateManager:
    """
    Manages all persistent state for the Astra trading system.

    Usage:
        sm = StateManager("astra_state.db")
        sm.update_capital(20000, "initial_deposit")
        sm.record_trade({...})
        curve = sm.get_equity_curve(days=30)
    """

    def __init__(self, db_path: str = "astra_state.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def get_capital(self) -> float:
        """Return the latest capital balance."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT capital FROM capital_history ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            return float(row[0]) if row else 0.0

    def update_capital(self, amount: float, reason: str) -> None:
        """Record a capital change (deposit, withdrawal, or P&L settlement)."""
        ts = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO capital_history (ts, capital, reason) VALUES (?, ?, ?)",
                (ts, amount, reason),
            )

    def record_trade(self, trade: dict) -> None:
        """
        Atomically insert a completed trade record.

        Required keys: id, symbol, direction, signal_type, strategy_name,
                       regime, entry_time, entry_price, lots, lot_size.
        Optional: exit_time, exit_price, pnl, exit_reason, metadata.
        """
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO trades
                   (id, symbol, direction, signal_type, strategy_name, regime,
                    entry_time, exit_time, entry_price, exit_price,
                    lots, lot_size, pnl, exit_reason, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade["id"],
                    trade["symbol"],
                    trade["direction"],
                    trade["signal_type"],
                    trade["strategy_name"],
                    trade["regime"],
                    trade["entry_time"],
                    trade.get("exit_time"),
                    trade["entry_price"],
                    trade.get("exit_price"),
                    trade["lots"],
                    trade["lot_size"],
                    trade.get("pnl"),
                    trade.get("exit_reason"),
                    json.dumps(trade.get("metadata", {})),
                ),
            )

    def get_open_positions(self) -> list[dict]:
        """Return all currently open positions."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM positions WHERE is_open = 1"
            ).fetchall()
            cols = [d[0] for d in conn.execute("SELECT * FROM positions LIMIT 0").description or []]
        if not rows:
            return []
        return [dict(zip(cols, row)) for row in rows]

    def open_position(self, position: dict) -> None:
        """Insert a new open position record."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO positions
                   (id, symbol, direction, entry_price, lots, stop_loss,
                    entry_time, strategy_name, regime, is_open, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    position["id"],
                    position["symbol"],
                    position["direction"],
                    position["entry_price"],
                    position["lots"],
                    position["stop_loss"],
                    position["entry_time"],
                    position["strategy_name"],
                    position["regime"],
                    json.dumps(position.get("metadata", {})),
                ),
            )

    def update_position(self, position_id: str, updates: dict) -> None:
        """Update fields on an existing position (e.g. trailing stop)."""
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [position_id]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE positions SET {set_clause} WHERE id = ?", values
            )

    def close_position(self, position_id: str) -> None:
        """Mark a position as closed."""
        self.update_position(position_id, {"is_open": 0})

    def get_daily_pnl(self, for_date: Optional[date] = None) -> float:
        """Return total realised P&L for a given date (defaults to today)."""
        target = (for_date or date.today()).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT SUM(pnl) FROM trades WHERE exit_time LIKE ? AND pnl IS NOT NULL",
                (f"{target}%",),
            ).fetchone()
            return float(row[0]) if row and row[0] is not None else 0.0

    def get_equity_curve(self, days: int = 30) -> pd.DataFrame:
        """
        Return a daily equity curve as a DataFrame.

        Columns: date (index), capital, daily_pnl, cumulative_return.
        """
        with self._connect() as conn:
            df = pd.read_sql_query(
                "SELECT ts, capital FROM capital_history ORDER BY ts DESC LIMIT ?",
                conn,
                params=(days * 24,),  # hourly snapshots
            )
        if df.empty:
            return pd.DataFrame(columns=["ts", "capital"])
        df["ts"] = pd.to_datetime(df["ts"])
        df = df.set_index("ts").sort_index()
        df["daily_pnl"] = df["capital"].diff()
        df["cumulative_return"] = (df["capital"] / df["capital"].iloc[0]) - 1
        return df

    def log_regime(self, for_date: date, regime: str, confidence: float, features: dict) -> None:
        """Record the daily regime classification."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO regime_log (date, regime, confidence, features) VALUES (?, ?, ?, ?)",
                (for_date.isoformat(), regime, confidence, json.dumps(features)),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._db_path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")  # safe for concurrent readers
        try:
            yield conn
        finally:
            conn.close()
