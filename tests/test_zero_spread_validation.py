#!/usr/bin/env python3
"""Regression coverage for the zero-spread validation contract (§9).

`income_pressure_spread = max(DMI_q) - min(DMI_q)` across the five
quintiles is mathematically nonnegative. A value of exactly zero is
legitimate: it means all five quintiles carry identical DMI (perfect
equality across the income distribution). Earlier code rejected
`spread <= 0`, which conflated the empirically-unlikely equality case
with a broken calculation.

These tests pin the corrected contract:

- `dmi_calculator.core.compute_summary_metrics` returns exactly
  `spread == 0.0` for an equal-quintile input, and does not raise.
- `scripts.rebuild_release_manifests.verify_against_raw` accepts a plan
  whose derived `income_pressure_spread` is exactly 0 (does NOT raise)
  and still rejects a strictly-negative spread (defence in depth: the
  formula cannot produce it, but a corrupted plan dict must not slip
  through).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from dmi_calculator.core import compute_summary_metrics
from scripts.rebuild_release_manifests import verify_against_raw


class TestCalculatorAllowsZeroSpread(unittest.TestCase):

    def test_equal_quintiles_produce_zero_spread(self):
        df = pd.DataFrame([
            {"group_id": "Q1", "dmi": 8.5},
            {"group_id": "Q2", "dmi": 8.5},
            {"group_id": "Q3", "dmi": 8.5},
            {"group_id": "Q4", "dmi": 8.5},
            {"group_id": "Q5", "dmi": 8.5},
        ])
        metrics = compute_summary_metrics(df)
        self.assertEqual(metrics["income_pressure_spread"], 0.0)
        self.assertEqual(metrics["income_pressure_tilt"], 0.0)

    def test_spread_is_always_nonnegative(self):
        # Regardless of ordering, spread must be >= 0. Uses an ascending
        # and a descending arrangement to guard against a `min - max`
        # regression that would silently produce a negative spread.
        for values in ([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]):
            df = pd.DataFrame(
                [{"group_id": f"Q{i+1}", "dmi": float(v)}
                 for i, v in enumerate(values)]
            )
            metrics = compute_summary_metrics(df)
            self.assertGreaterEqual(metrics["income_pressure_spread"], 0.0)


class TestVerifyAgainstRawAcceptsZeroSpread(unittest.TestCase):
    """§9: verify_against_raw must accept `spread == 0` as legitimate."""

    def _make_plan(self, tmp_path: Path, spread: float, tilt: float):
        raw_path = tmp_path / "raw.json"
        raw_path.write_text(json.dumps({
            "summary_metrics": {"dmi_income_pressure_gap": tilt}
        }))
        return SimpleNamespace(
            raw_path=raw_path,
            release_id="test-zero-spread",
            metrics={
                "income_pressure_tilt": tilt,
                "income_pressure_spread": spread,
            },
        )

    def test_zero_spread_does_not_raise(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._make_plan(Path(tmp), spread=0.0, tilt=0.0)
            # No SystemExit: this is the exact case previously rejected.
            verify_against_raw([plan])

    def test_positive_spread_does_not_raise(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._make_plan(Path(tmp), spread=1.5, tilt=1.0)
            verify_against_raw([plan])

    def test_negative_spread_still_rejected(self):
        # Defence in depth: the formula cannot emit a negative spread,
        # but a corrupted plan dict must not slip through.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._make_plan(Path(tmp), spread=-0.01, tilt=0.0)
            with self.assertRaises(SystemExit) as cm:
                verify_against_raw([plan])
            self.assertIn("income_pressure_spread", str(cm.exception))
            self.assertIn(">= 0", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
