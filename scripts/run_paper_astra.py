#!/usr/bin/env python3
"""
PAPER-001 / TASK-1: paper trading with the full validated ASTRA stack.

scripts/run_paper.py runs the bare ATLAS baseline — PivotCPR signals, no regime filter,
no VIX awareness, no compounding engine. Paper trading that would measure the wrong
system. This runner adds the four validated layers on top of it, by subclassing the
tested PaperTradingEngine rather than reimplementing it:

  1. Signal        PivotCPR momentum breakout            (ATLAS baseline, unchanged)
  2. Regime gate   P70_L40d adaptive ATR                 (EXP-0010/0011)
  3. Sizing tilt   VIX bucket multiplier                 (EXP-0015)
  4. Lot engine    step-down 4-tier + cap growth         (EXP-0017, src/astra/risk)

IV pricing is deliberately NOT wired. The VIX×1.1 model (EXP-0014) exists to price
options in a backtest; paper trading fetches REAL option quotes from the broker. Using
real premiums means this session *tests* the IV model instead of depending on it, which
is most of the point of paper trading at all.

RISK LIMITS. Runs at the limits in config/risk.yaml as written — 25% deployment,
hard_cap_lots 10 — which EXP-0020 showed costs nothing in deployment terms and EXP-0021
showed cuts P(ruin) from 16.4% to 9.5%. No limit change is needed to paper trade, and
none is made here. Raising them later is a human decision (DECISION-010, AGENTS.md s6).

WHAT THIS SESSION ACTUALLY MEASURES. At ₹50,000 with 25% deployment and ~₹6,600 average
premium per lot, the engine sizes 1-2 lots per trade. The step-down tiers and VIX tilt are
therefore close to inert for the first few months — they only bite at larger capital. That
is fine, because the number worth measuring now is **realised ₹/trade against the
backtest's ₹307/lot**. If live comes in at half that, the real expectation is half of
everything on record. The lot-scaling machinery gets exercised later, not now.

No real orders are placed. PaperTradingEngine simulates every fill.

Usage:
    python3 scripts/run_paper_astra.py                      # full session
    python3 scripts/run_paper_astra.py --preflight          # checks only, no trading
    python3 scripts/run_paper_astra.py --duration 60
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.config_loader import load_instruments, load_risk
from core.engine.base_strategy import Signal
from src.astra.alpha.regime_filter import BARS_PER_SESSION_5MIN, AdaptiveAtrFilter
from src.astra.risk.lot_manager import LotManager, LotManagerConfig, RiskLimitConflict
from src.astra.risk.vix_sizing import vix_bucket_name, vix_percentile, vix_size_mult

# Importing the tested engine and its Telegram helper rather than copying them.
from scripts.run_paper import PaperTradingEngine, send_telegram_alert  # noqa: E402

from backtest.options_pricer import OptionsPricer  # noqa: E402
from core.broker.upstox_adapter import UpstoxAdapter  # noqa: E402
from live.state_manager import StateManager  # noqa: E402
from strategies.pivot_cpr_strategy import PivotCprStrategy  # noqa: E402

logger = logging.getLogger("astra.paper")

NIFTY_SYMBOL = "NSE_INDEX|Nifty 50"
VIX_SYMBOL = "NSE_INDEX|India VIX"      # only accepted spelling — see DATA-002
WARMUP_CALENDAR_DAYS = 75               # ~50 sessions, comfortably over the 3000-bar need
CHUNK_DAYS = 25                         # Upstox intraday history caps at 30 days per call
SIZING_STATE_FILE = "astra_sizing_state.json"


# ──────────────────────────────────────────────────────────────────────────────
# Cross-session sizing state
# ──────────────────────────────────────────────────────────────────────────────
class SizingState:
    """
    Persists the compounding engine's memory between daily sessions.

    StateManager tracks capital but knows nothing about the high-water mark, tax reserve,
    lot cap or profitable-month streak — and all four must survive a restart or the
    drawdown tiers reset to "no drawdown" every morning, which would quietly disable the
    entire risk brake over a multi-month paper run.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
                logger.info("Loaded sizing state from %s", path)
            except Exception:
                logger.exception("Could not read %s — starting fresh", path)

    def apply_to(self, mgr: LotManager) -> None:
        if not self.data:
            return
        mgr.tax_reserve = float(self.data.get("tax_reserve", mgr.tax_reserve))
        mgr._hwm = max(float(self.data.get("hwm", mgr.high_water_mark)), 0.0)
        mgr._max_lots_cap = int(self.data.get("max_lots_cap", mgr.max_lots_cap))
        mgr._consecutive_profitable_months = int(
            self.data.get("consecutive_profitable_months", 0)
        )
        logger.info(
            "Restored sizing state: HWM ₹%.0f | reserve ₹%.0f | cap %d lots | streak %d",
            mgr.high_water_mark, mgr.tax_reserve, mgr.max_lots_cap,
            mgr.consecutive_profitable_months,
        )

    def save_from(self, mgr: LotManager, month: str) -> None:
        self.data = {
            "hwm": mgr.high_water_mark,
            "tax_reserve": mgr.tax_reserve,
            "max_lots_cap": mgr.max_lots_cap,
            "consecutive_profitable_months": mgr.consecutive_profitable_months,
            "last_month": month,
            "updated_at": datetime.now().isoformat(),
        }
        self.path.write_text(json.dumps(self.data, indent=2) + "\n", encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────
class AstraPaperEngine(PaperTradingEngine):
    """PaperTradingEngine plus the regime gate and the ASTRA sizing engine."""

    def __init__(
        self,
        *args,
        regime_filter: AdaptiveAtrFilter,
        warmup_bars: pd.DataFrame,
        vix_daily: pd.Series,
        lot_manager: LotManager,
        sizing_state: SizingState,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._filter = regime_filter
        self._bars = warmup_bars.copy()
        self._vix = vix_daily
        self._lot_mgr = lot_manager
        self._sizing_state = sizing_state
        self._gated_count = 0
        self._entered_count = 0

    # ── regime series upkeep ────────────────────────────────────────────────
    def _manage(self, bar: pd.Series, history: pd.DataFrame) -> None:
        """Called every loop before signal evaluation — the hook for bar upkeep."""
        self._append_bar(bar)
        super()._manage(bar, history)

    def _append_bar(self, bar: pd.Series) -> None:
        ts = bar.name
        row = {k: float(bar.get(k, 0.0)) for k in ("open", "high", "low", "close", "volume")}
        self._bars.loc[ts] = row
        # The forming bar is re-sent each poll with updated high/low/close, so overwrite
        # rather than append, then keep the frame bounded.
        self._bars = self._bars[~self._bars.index.duplicated(keep="last")].sort_index()
        max_keep = self._filter.lookback_bars + 5 * BARS_PER_SESSION_5MIN
        if len(self._bars) > max_keep:
            self._bars = self._bars.iloc[-max_keep:]

    # ── regime gate ─────────────────────────────────────────────────────────
    def _enter(self, signal: Signal, bar_time: datetime, entry_price: float) -> None:
        state = self._filter.describe(self._bars)
        if not state["open"]:
            self._gated_count += 1
            logger.info("⏸ Signal GATED by P70_L40d regime filter — %s", state["reason"])
            self._update_status(f"Signal gated: {state['reason']}")
            return
        logger.info("✅ Regime OPEN — %s", state["reason"])
        self._entered_count += 1
        super()._enter(signal, bar_time, entry_price)

    # ── sizing ──────────────────────────────────────────────────────────────
    def _calc_lots(self, entry_premium: float) -> int:
        """
        ASTRA sizing: step-down tier engine, then the VIX tilt, then the hard cap.

        The research applied the VIX multiplier to per-lot P&L at a 1-lot baseline, which
        is equivalent to trading `lots × mult` with no rounding. Lots are integral in
        reality, so the discrete analogue truncates — and at 1-2 lots a 1.5x tilt rounds
        away entirely. That is a real deviation from the backtest at small capital, and it
        biases toward *smaller* positions, which is the safe direction.
        """
        lot_size = self.instruments_cfg["instruments"]["NIFTY"]["lot_size"]
        hard_cap = self.risk_cfg["position_limits"]["hard_cap_lots"]
        premium_per_lot = entry_premium * lot_size
        if premium_per_lot <= 0:
            logger.warning("Non-positive premium (%.4f) — refusing to size", entry_premium)
            return 0

        # Keep the engine's capital view in step with persisted capital before sizing.
        self._lot_mgr.gross_capital = self.capital + self._lot_mgr.tax_reserve

        base_lots = self._lot_mgr.lots_for(premium_per_lot)
        pctile = vix_percentile(self._vix, pd.Timestamp(datetime.now()))
        mult = vix_size_mult(pctile)
        lots = max(1, int(base_lots * mult))
        lots = min(lots, hard_cap)

        logger.info(
            "Sizing: ₹%.0f net | ₹%.0f/lot | DD %.1f%% → %.2fx tier | cap %d | "
            "VIX %s (%s) → %.1fx | %d lots",
            self._lot_mgr.net_capital, premium_per_lot, self._lot_mgr.drawdown * 100,
            self._lot_mgr.dd_multiplier, self._lot_mgr.effective_lot_cap,
            "n/a" if pctile is None else f"p{pctile:.0f}", vix_bucket_name(pctile),
            mult, lots,
        )
        return lots

    # ── session close ───────────────────────────────────────────────────────
    def finalise_session(self) -> None:
        """Book the session's P&L into the sizing engine and persist it."""
        realised = self.capital - self._day_start_capital
        self._lot_mgr.record_trade_pnl(0.0)  # keep HWM marking consistent
        self._lot_mgr.gross_capital = self.capital + self._lot_mgr.tax_reserve

        month = datetime.now().strftime("%Y-%m")
        last_month = self._sizing_state.data.get("last_month")
        if last_month and last_month != month:
            summary = self._lot_mgr.close_month()
            logger.info("Month rolled %s → %s: %s", last_month, month, summary)
            send_telegram_alert(
                f"📅 <b>ASTRA month close {last_month}</b>\n"
                f"Net ₹{summary['net_capital']:,.0f} | tax reserve "
                f"₹{summary['tax_reserve']:,.0f}\nDD {summary['drawdown_pct']:.1f}% → "
                f"{summary['dd_multiplier']:.2f}x | cap {summary['max_lots_cap']} lots"
            )

        self._sizing_state.save_from(self._lot_mgr, month)
        logger.info(
            "Session: %d signals entered, %d gated by regime filter | session P&L ₹%+.2f",
            self._entered_count, self._gated_count, realised,
        )
        send_telegram_alert(
            f"🏁 <b>ASTRA paper session end</b>\n"
            f"Entered {self._entered_count} | gated {self._gated_count}\n"
            f"Session P&L ₹{realised:+,.2f} | capital ₹{self.capital:,.2f}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Warmup
# ──────────────────────────────────────────────────────────────────────────────
def fetch_warmup_bars(adapter: UpstoxAdapter, days: int = WARMUP_CALENDAR_DAYS) -> pd.DataFrame:
    """Fetch 5-minute history in <=30-day chunks (Upstox intraday history limit)."""
    end = datetime.now().date() - timedelta(1)
    start = end - timedelta(days)
    frames: list[pd.DataFrame] = []

    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(CHUNK_DAYS - 1), end)
        logger.info("  warmup chunk %s → %s", cursor, chunk_end)
        df = adapter.get_ohlcv(
            symbol=NIFTY_SYMBOL, interval="5minute",
            from_date=cursor.strftime("%Y-%m-%d"), to_date=chunk_end.strftime("%Y-%m-%d"),
        )
        if df is not None and not df.empty:
            frames.append(df)
        cursor = chunk_end + timedelta(1)

    if not frames:
        return pd.DataFrame()
    bars = pd.concat(frames)
    bars = bars[~bars.index.duplicated(keep="last")].sort_index()
    return bars


def fetch_vix_daily(adapter: UpstoxAdapter, days: int = 120) -> pd.Series:
    """India VIX daily closes — needs >=40 sessions for the percentile."""
    end = datetime.now().date()
    start = end - timedelta(days)
    df = adapter.get_ohlcv(
        symbol=VIX_SYMBOL, interval="day",
        from_date=start.strftime("%Y-%m-%d"), to_date=end.strftime("%Y-%m-%d"),
    )
    if df is None or df.empty:
        return pd.Series(dtype=float, name="vix")
    return df["close"].rename("vix")


# ──────────────────────────────────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="ASTRA paper trading (validated stack)")
    parser.add_argument("--duration", type=int, default=390, help="session minutes")
    parser.add_argument("--db", default=None, help="SQLite state file")
    parser.add_argument("--capital", type=float, default=None,
                        help="seed capital on first run (default: risk.yaml)")
    parser.add_argument("--set-capital", type=float, default=None,
                        help="OVERWRITE persisted capital, even if already seeded")
    parser.add_argument("--preflight", action="store_true",
                        help="run all readiness checks and exit without trading")
    args = parser.parse_args()

    # Preflight must never mutate real trading state. Constructing the engine seeds
    # capital from risk.yaml if the DB is empty, so an earlier --preflight run would
    # silently pin the account at ₹20,000 and make a later --capital flag a no-op.
    # Default it to a throwaway file unless a DB was named explicitly.
    if args.db is None:
        args.db = "/tmp/astra_preflight_scratch.db" if args.preflight else "astra_paper_state.db"

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    instruments_cfg = load_instruments()
    risk_cfg = load_risk()
    nifty_cfg = instruments_cfg["instruments"]["NIFTY"]

    print("=" * 78)
    print("ASTRA PAPER TRADING — validated stack (PAPER-001)")
    print("=" * 78)

    # ── sizing config, validated against risk.yaml ───────────────────────────
    deploy = risk_cfg["per_trade"]["max_capital_deployed_pct"]
    hard_cap = risk_cfg["position_limits"]["hard_cap_lots"]
    try:
        lot_cfg = LotManagerConfig.from_risk_config(
            risk_cfg, risk_per_trade_pct=deploy, initial_max_lots=hard_cap
        )
    except RiskLimitConflict as exc:
        print(f"\n❌ REFUSING TO START — {exc}")
        return 1
    print(f"  Risk limits (from config/risk.yaml): {deploy:.0f}% deployment, "
          f"{hard_cap} lots hard cap")

    # ── SEBI Algo-ID (paper does not require it; warn loudly anyway) ─────────
    algo_id = (risk_cfg.get("algo_ids") or {}).get("pivot_cpr_strategy")
    if algo_id:
        print(f"  SEBI Algo-ID: {algo_id}")
    else:
        print("  ⚠️  SEBI Algo-ID: NOT SET (config/risk.yaml algo_ids). Not required for")
        print("      paper trading, but mandatory for automated LIVE orders since Apr 2026.")

    adapter = UpstoxAdapter(config={
        "api_key": os.environ.get("UPSTOX_SANDBOX_API_KEY", ""),
        "api_secret": os.environ.get("UPSTOX_SANDBOX_API_SECRET", ""),
        "redirect_uri": os.environ.get("UPSTOX_SANDBOX_REDIRECT_URI", ""),
        "analytics_token": os.environ.get("UPSTOX_ANALYTICS_TOKEN", ""),
        "sandbox": True,
    })

    # ── warmup ───────────────────────────────────────────────────────────────
    regime = AdaptiveAtrFilter()
    print(f"\n  Fetching 5-min warmup history (need >= {regime.min_warmup_bars} bars "
          f"for the P70 threshold)...")
    bars = fetch_warmup_bars(adapter)
    if bars.empty:
        print("  ❌ No warmup bars returned — check UPSTOX_ANALYTICS_TOKEN.")
        return 1
    print(f"  ✓ {len(bars):,} bars  {bars.index[0]} → {bars.index[-1]}")

    if len(bars) < regime.min_warmup_bars:
        short = regime.min_warmup_bars - len(bars)
        print(f"  ❌ REFUSING TO START — {short} bars short of the {regime.min_warmup_bars} "
              f"needed.\n     Without the full window there is no P70 threshold, so the "
              f"regime filter\n     would gate every signal and the session would measure "
              f"nothing. Raise\n     WARMUP_CALENDAR_DAYS and retry.")
        return 1

    state = regime.describe(bars)
    print(f"  ✓ Regime filter warm: {state['reason']}")
    print(f"    currently {'OPEN' if state['open'] else 'CLOSED'} as of the last warmup bar")

    print("\n  Fetching India VIX daily history...")
    vix = fetch_vix_daily(adapter)
    if len(vix) < 40:
        print(f"  ⚠️  only {len(vix)} VIX sessions (<40) — the tilt will size 1.0x "
              f"(fail-safe), not 1.5x/0.5x")
    else:
        pctile = vix_percentile(vix, pd.Timestamp(datetime.now()))
        print(f"  ✓ {len(vix)} sessions | latest {vix.iloc[-1]:.2f} | "
              f"percentile p{pctile:.0f} ({vix_bucket_name(pctile)}) → "
              f"{vix_size_mult(pctile):.1f}x")

    # ── engine assembly ──────────────────────────────────────────────────────
    if args.preflight and args.db.startswith("/tmp/"):
        Path(args.db).unlink(missing_ok=True)  # always a clean scratch DB

    sm = StateManager(args.db)
    if args.set_capital is not None:
        previous = sm.get_capital()
        # update_capital() is an absolute setter, not a delta — PaperTradingEngine calls it
        # as update_capital(capital, "initial_deposit") with the full amount.
        sm.update_capital(args.set_capital, "manual_capital_reset")
        print(f"\n  ⚠️  Capital OVERWRITTEN: ₹{previous:,.2f} → ₹{sm.get_capital():,.2f}")
        logger.warning("Capital manually reset ₹%.2f → ₹%.2f", previous, sm.get_capital())
    elif args.capital is not None:
        if sm.get_capital() == 0.0:
            sm.update_capital(args.capital, "initial_deposit")
        elif abs(sm.get_capital() - args.capital) > 0.01:
            print(f"\n  ⚠️  --capital ₹{args.capital:,.0f} IGNORED — this account is already"
                  f" seeded at ₹{sm.get_capital():,.2f}.")
            print("      Use --set-capital to overwrite it deliberately, or delete the DB"
                  " to start fresh.")

    lot_mgr = LotManager(config=lot_cfg, gross_capital=max(sm.get_capital(), 1.0))
    sizing_state = SizingState(project_root / SIZING_STATE_FILE)
    sizing_state.apply_to(lot_mgr)

    strategy = PivotCprStrategy(config={
        "tolerance_pct": 0.18, "min_levels_for_confluence": 2, "momentum_enabled": True,
        "momentum_body_pct": 0.50, "momentum_accel_multiplier": 1.8,
        "momentum_min_criteria": 2,
    })
    # Flat IV only feeds the pricer's fallback path; live option quotes take precedence.
    pricer = OptionsPricer(
        lot_size=nifty_cfg["lot_size"], expiry_weekday=nifty_cfg["weekly_expiry_weekday"],
        strike_step=nifty_cfg["strike_step"], iv=0.14,
    )

    engine = AstraPaperEngine(
        strategy=strategy, adapter=adapter, pricer=pricer,
        instruments_cfg=instruments_cfg, risk_cfg=risk_cfg, state_manager=sm,
        strategy_id="astra_pivot_cpr_p70",
        regime_filter=regime, warmup_bars=bars, vix_daily=vix,
        lot_manager=lot_mgr, sizing_state=sizing_state,
    )

    sample_premium = 100.0
    print(f"\n  Sizing dry-check at ₹{sample_premium:.0f} premium/unit: "
          f"{engine._calc_lots(sample_premium)} lot(s)")
    print(f"  Capital ₹{sm.get_capital():,.2f} | HWM ₹{lot_mgr.high_water_mark:,.2f} | "
          f"tier {lot_mgr.dd_multiplier:.2f}x")

    if args.preflight:
        print("\n  ✓ PREFLIGHT PASSED — no trading performed.")
        print("    Remove --preflight to run a live paper session during market hours.")
        return 0

    print("\n" + "=" * 78)
    send_telegram_alert(
        f"🚀 <b>ASTRA paper session start</b>\n"
        f"Capital ₹{sm.get_capital():,.2f} | {deploy:.0f}% deploy | {hard_cap}-lot cap\n"
        f"Regime {'OPEN' if state['open'] else 'CLOSED'} | {len(bars):,} warmup bars"
    )
    try:
        engine.run(duration_minutes=args.duration)
    finally:
        engine.finalise_session()
    return 0


if __name__ == "__main__":
    sys.exit(main())
