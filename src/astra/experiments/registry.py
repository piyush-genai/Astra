"""
Experiment Registry — immutable record of every research experiment.

Rules:
- Every experiment gets a unique, sequential ID: EXP-NNNN
- Results are NEVER overwritten — only new experiments created
- Configuration, dataset version, and git commit are captured automatically
- Failed experiments are recorded too — selection bias accounting requires it

Usage:
    from src.astra.experiments.registry import ExperimentRegistry, ExperimentStatus

    reg = ExperimentRegistry()
    exp_id = reg.create(
        hypothesis="High IV percentile predicts directional momentum",
        strategy="pivot_cpr",
        train_range=("2026-02-01", "2026-04-30"),
        test_range=("2026-05-01", "2026-07-31"),
        config={"tolerance_pct": 0.18, "momentum_enabled": True},
        notes="Testing whether IV > 80th pct improves win rate"
    )
    reg.record_results(exp_id, metrics={...}, conclusion="...")
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional


EXPERIMENTS_DIR = Path(__file__).parent.parent.parent.parent / "research" / "experiments"


class ExperimentStatus(str, Enum):
    PROPOSED  = "PROPOSED"   # hypothesis registered, not yet run
    RUNNING   = "RUNNING"    # currently executing
    COMPLETED = "COMPLETED"  # ran to completion with results
    REJECTED  = "REJECTED"   # failed validation (leakage, bias, etc.)
    FAILED    = "FAILED"     # technical failure (code error, missing data)
    ARCHIVED  = "ARCHIVED"   # superseded by a better experiment


@dataclass
class ExperimentRecord:
    exp_id:        str
    hypothesis:    str
    status:        ExperimentStatus
    created_at:    str
    updated_at:    str
    git_commit:    str
    strategy:      str
    dataset_version: str
    train_range:   tuple[str, str]
    test_range:    tuple[str, str]
    config:        dict
    notes:         str = ""

    # Filled in when complete
    metrics:      dict = field(default_factory=dict)
    conclusion:   str = ""
    leakage_checked: bool = False
    walk_forward_done: bool = False
    monte_carlo_done: bool = False

    def is_production_candidate(self) -> bool:
        """True only if the experiment meets all validation gates."""
        return (
            self.status == ExperimentStatus.COMPLETED
            and self.leakage_checked
            and self.walk_forward_done
            and self.monte_carlo_done
            and self.metrics.get("out_of_sample_sharpe", 0) > 0.5
            and self.metrics.get("profit_factor", 0) > 1.3
        )


class ExperimentRegistry:
    """
    File-backed experiment registry.

    Each experiment is stored as an individual JSON file in
    research/experiments/EXP-NNNN.json for easy git tracking and diffing.
    """

    def __init__(self, experiments_dir: Path = EXPERIMENTS_DIR) -> None:
        self._dir = experiments_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(
        self,
        hypothesis: str,
        strategy: str,
        train_range: tuple[str, str],
        test_range: tuple[str, str],
        config: dict,
        notes: str = "",
        dataset_version: str = "auto",
    ) -> str:
        """Register a new experiment and return its ID."""
        exp_id = self._next_id()
        now = datetime.utcnow().isoformat()
        record = ExperimentRecord(
            exp_id=exp_id,
            hypothesis=hypothesis,
            status=ExperimentStatus.PROPOSED,
            created_at=now,
            updated_at=now,
            git_commit=self._git_commit(),
            strategy=strategy,
            dataset_version=dataset_version,
            train_range=train_range,
            test_range=test_range,
            config=config,
            notes=notes,
        )
        self._save(record)
        return exp_id

    def record_results(
        self,
        exp_id: str,
        metrics: dict[str, Any],
        conclusion: str,
        leakage_checked: bool = False,
        walk_forward_done: bool = False,
        monte_carlo_done: bool = False,
    ) -> None:
        """Record results for a completed experiment."""
        record = self.load(exp_id)
        record.status = ExperimentStatus.COMPLETED
        record.metrics = metrics
        record.conclusion = conclusion
        record.leakage_checked = leakage_checked
        record.walk_forward_done = walk_forward_done
        record.monte_carlo_done = monte_carlo_done
        record.updated_at = datetime.utcnow().isoformat()
        self._save(record)

    def reject(self, exp_id: str, reason: str) -> None:
        """Mark an experiment as rejected with an explanation."""
        record = self.load(exp_id)
        record.status = ExperimentStatus.REJECTED
        record.conclusion = f"REJECTED: {reason}"
        record.updated_at = datetime.utcnow().isoformat()
        self._save(record)

    def load(self, exp_id: str) -> ExperimentRecord:
        path = self._dir / f"{exp_id}.json"
        if not path.exists():
            raise KeyError(f"Experiment {exp_id} not found.")
        raw = json.loads(path.read_text())
        raw["status"] = ExperimentStatus(raw["status"])
        raw["train_range"] = tuple(raw["train_range"])
        raw["test_range"] = tuple(raw["test_range"])
        return ExperimentRecord(**raw)

    def list_all(self) -> list[ExperimentRecord]:
        records = []
        for p in sorted(self._dir.glob("EXP-*.json")):
            try:
                records.append(self.load(p.stem))
            except Exception:
                pass
        return records

    def production_candidates(self) -> list[ExperimentRecord]:
        return [r for r in self.list_all() if r.is_production_candidate()]

    def summary_table(self) -> str:
        """Return a markdown table of all experiments."""
        rows = ["| ID | Status | Strategy | Hypothesis | Sharpe | WF | MC |",
                "|---|---|---|---|---|---|---|"]
        for r in self.list_all():
            sharpe = r.metrics.get("out_of_sample_sharpe", "—")
            wf = "✓" if r.walk_forward_done else "✗"
            mc = "✓" if r.monte_carlo_done else "✗"
            hyp = r.hypothesis[:50] + "..." if len(r.hypothesis) > 50 else r.hypothesis
            rows.append(f"| {r.exp_id} | {r.status.value} | {r.strategy} | {hyp} | {sharpe} | {wf} | {mc} |")
        return "\n".join(rows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        existing = sorted(self._dir.glob("EXP-*.json"))
        if not existing:
            return "EXP-0001"
        last = existing[-1].stem  # e.g. "EXP-0023"
        n = int(last.split("-")[1]) + 1
        return f"EXP-{n:04d}"

    def _save(self, record: ExperimentRecord) -> None:
        path = self._dir / f"{record.exp_id}.json"
        data = asdict(record)
        data["status"] = record.status.value
        path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def _git_commit() -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else "unknown"
        except Exception:
            return "unknown"
