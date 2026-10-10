"""
Central config loader.

Reads config/instruments.yaml and config/risk.yaml at startup.
All engine and strategy code calls these functions — never reads YAML inline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Locate config dir relative to this file's location (src/ → project root → config/).
_CONFIG_DIR = Path(__file__).parent.parent / "config"


def load_instruments() -> dict[str, Any]:
    """Return parsed content of config/instruments.yaml."""
    return _load(_CONFIG_DIR / "instruments.yaml")


def load_risk() -> dict[str, Any]:
    """Return parsed content of config/risk.yaml."""
    return _load(_CONFIG_DIR / "risk.yaml")


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    logger.debug("Loaded config: %s", path.name)
    return data or {}
