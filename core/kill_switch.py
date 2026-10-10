"""
CLI kill-switch trigger (Rule 5 in trading-risk-rules.md).

Run from project root:
    python -m src.kill_switch activate
    python -m src.kill_switch deactivate
    python -m src.kill_switch status

This edits config/risk.yaml directly so the running engine picks it up
on its next poll cycle.

A Telegram bot integration can also call activate_kill_switch() in
RiskManager directly for sub-second response.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_RISK_YAML = Path(__file__).parent.parent / "config" / "risk.yaml"


def _read() -> dict:
    with _RISK_YAML.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _write(data: dict) -> None:
    with _RISK_YAML.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, default_flow_style=False, allow_unicode=True)


def activate() -> None:
    cfg = _read()
    cfg["kill_switch_active"] = True
    _write(cfg)
    print("✅  Kill switch ACTIVATED — new order placement halted.")


def deactivate() -> None:
    cfg = _read()
    cfg["kill_switch_active"] = False
    _write(cfg)
    print("✅  Kill switch deactivated — order placement re-enabled.")


def status() -> None:
    cfg = _read()
    state = cfg.get("kill_switch_active", False)
    print(f"Kill switch is currently: {'ACTIVE 🔴' if state else 'inactive 🟢'}")


if __name__ == "__main__":
    commands = {"activate": activate, "deactivate": deactivate, "status": status}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(f"Usage: python -m src.kill_switch [{' | '.join(commands)}]")
        sys.exit(1)
    commands[sys.argv[1]]()
