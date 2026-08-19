#!/usr/bin/env python3
"""Regression tests: Baseline+Slack-Plus internal-coherence identity.

Under the current DMI formula (see dmi_calculator/core.py:compute_dmi):

    DMI(g) = scale_factor * [alpha * pi(g) + (1 - alpha) * S]

With the published defaults `scale_factor = 2.0` and `alpha = 0.5`, this
simplifies to:

    DMI(g) = pi(g) + S

Baseline and Slack-Plus specifications share every input except the
slack measure (U-3 vs U-6). Therefore the Slack-Plus DMI for each group
must equal the Baseline DMI for that group plus (U6 - U3), a constant
shift across all groups. Immediate consequences on the summary metrics:

  - dmi_median      differs by exactly (U6 - U3)
  - dmi_stress      differs by exactly (U6 - U3)
  - income_pressure_spread   is identical (max - min invariant to shift)
  - income_pressure_tilt     is identical (Q1 - Q5 invariant to shift)
  - most_pressured_group     is the same (argmax invariant to shift)
  - least_pressured_group    is the same (argmin invariant to shift)

Two complementary test classes below:

  1. TestIdentityAgainstFormula: runs `compute_dmi` in-process on
     synthesised inflation+slack inputs and asserts the identity.
     Guards the mathematical relationship in code.

  2. TestIdentityAgainstPublishedReleases: walks every Baseline +
     Slack-Plus pair present in data/outputs/ and asserts the identity
     on the published values. Guards against post-hoc file corruption
     or divergent-parameter regressions (e.g., someone accidentally
     using a different alpha for Slack-Plus).
"""

import json
import math
import unittest
from pathlib import Path

import pandas as pd

from dmi_calculator.core import compute_dmi, compute_summary_metrics


TOLERANCE_ABS = 1e-9
NUMERIC_INVARIANT_KEYS = ("income_pressure_spread", "income_pressure_tilt")
CATEGORICAL_INVARIANT_KEYS = ("most_pressured_group", "least_pressured_group")


def _inflation_frame(values_by_group: dict) -> pd.DataFrame:
    return pd.DataFrame(
        [{"group_id": g, "inflation": v} for g, v in values_by_group.items()]
    )


class TestIdentityAgainstFormula(unittest.TestCase):
    def test_per_group_dmi_shifts_by_u6_minus_u3(self):
        inflation = _inflation_frame({
            "Q1": 3.2, "Q2": 3.5, "Q3": 3.6, "Q4": 3.9, "Q5": 3.7,
        })
        u3, u6 = 4.1, 7.9
        baseline = compute_dmi(inflation, slack=u3).set_index("group_id")
        slack_plus = compute_dmi(inflation, slack=u6).set_index("group_id")

        for group_id in baseline.index:
            per_group_delta = (
                slack_plus.loc[group_id, "dmi"] - baseline.loc[group_id, "dmi"]
            )
            self.assertAlmostEqual(per_group_delta, u6 - u3, places=9,
                msg=f"{group_id}: per-group DMI delta must equal U6 - U3")

    def test_summary_metrics_obey_shift_identity(self):
        inflation = _inflation_frame({
            "Q1": 3.2, "Q2": 3.5, "Q3": 3.6, "Q4": 3.9, "Q5": 3.7,
        })
        u3, u6 = 4.1, 7.9
        baseline_sm = compute_summary_metrics(compute_dmi(inflation, slack=u3))
        slack_plus_sm = compute_summary_metrics(compute_dmi(inflation, slack=u6))

        # dmi_median and dmi_stress shift by exactly (U6 - U3)
        self.assertAlmostEqual(
            slack_plus_sm["dmi_median"] - baseline_sm["dmi_median"], u6 - u3,
            places=9,
        )
        self.assertAlmostEqual(
            slack_plus_sm["dmi_stress"] - baseline_sm["dmi_stress"], u6 - u3,
            places=9,
        )
        # spread and tilt are invariant
        for key in NUMERIC_INVARIANT_KEYS:
            self.assertAlmostEqual(baseline_sm[key], slack_plus_sm[key],
                places=9, msg=f"{key} must be invariant under Baseline↔Slack-Plus")
        # argmax/argmin categorical labels invariant
        for key in CATEGORICAL_INVARIANT_KEYS:
            self.assertEqual(baseline_sm[key], slack_plus_sm[key],
                msg=f"{key} must be invariant under Baseline↔Slack-Plus")

    def test_identity_fails_if_alpha_diverges(self):
        """Divergent alpha across specs breaks the identity — the test
        must catch that regression."""
        inflation = _inflation_frame({
            "Q1": 3.2, "Q2": 3.5, "Q3": 3.6, "Q4": 3.9, "Q5": 3.7,
        })
        u3, u6 = 4.1, 7.9
        baseline = compute_dmi(inflation, slack=u3, alpha=0.5).set_index("group_id")
        slack_plus_wrong = compute_dmi(inflation, slack=u6, alpha=0.4).set_index("group_id")
        # At least one group's per-group delta must NOT equal (U6-U3)
        mismatches = [
            g for g in baseline.index
            if not math.isclose(
                slack_plus_wrong.loc[g, "dmi"] - baseline.loc[g, "dmi"],
                u6 - u3,
                abs_tol=TOLERANCE_ABS,
            )
        ]
        self.assertGreater(len(mismatches), 0,
            "Divergent-alpha regression should break the identity")


class TestIdentityAgainstPublishedReleases(unittest.TestCase):
    """Assert the identity on every Baseline+Slack-Plus pair in data/outputs/."""

    @classmethod
    def _discover_pairs(cls) -> list[str]:
        output_dir = Path("data/outputs")
        pairs = []
        for baseline_path in sorted(output_dir.glob("dmi_release_????-??.json")):
            period = baseline_path.stem.replace("dmi_release_", "")
            slack_plus_path = output_dir / f"dmi_release_{period}_slack_plus.json"
            if slack_plus_path.exists():
                pairs.append(period)
        return pairs

    def test_at_least_one_pair_present(self):
        pairs = self._discover_pairs()
        self.assertGreater(len(pairs), 0,
            "Expected at least one Baseline+Slack-Plus release pair in data/outputs/")

    def test_all_paired_releases_satisfy_identity(self):
        pairs = self._discover_pairs()
        failures = []
        for period in pairs:
            b = json.loads(Path(f"data/outputs/dmi_release_{period}.json").read_text())
            s = json.loads(
                Path(f"data/outputs/dmi_release_{period}_slack_plus.json").read_text()
            )
            b_slack = b["dmi_by_group"][0]["slack"]
            s_slack = s["dmi_by_group"][0]["slack"]
            delta = s_slack - b_slack

            b_by_group = {g["group_id"]: g["dmi"] for g in b["dmi_by_group"]}
            s_by_group = {g["group_id"]: g["dmi"] for g in s["dmi_by_group"]}

            # Per-group shift identity
            for group_id, b_dmi in b_by_group.items():
                if group_id not in s_by_group:
                    failures.append(f"{period}: {group_id} present in baseline, missing in slack_plus")
                    continue
                observed = s_by_group[group_id] - b_dmi
                if not math.isclose(observed, delta, abs_tol=TOLERANCE_ABS):
                    failures.append(
                        f"{period} {group_id}: per-group delta {observed:.12f} "
                        f"!= U6-U3 = {delta:.12f}"
                    )

            b_sm = b["summary_metrics"]
            s_sm = s["summary_metrics"]

            # Shifted summary metrics
            for key in ("dmi_median", "dmi_stress"):
                observed = s_sm[key] - b_sm[key]
                if not math.isclose(observed, delta, abs_tol=TOLERANCE_ABS):
                    failures.append(
                        f"{period}: summary_metrics.{key} delta {observed:.12f} "
                        f"!= U6-U3 = {delta:.12f}"
                    )
            # Invariant summary metrics
            for key in NUMERIC_INVARIANT_KEYS:
                if not math.isclose(b_sm[key], s_sm[key], abs_tol=TOLERANCE_ABS):
                    failures.append(
                        f"{period}: summary_metrics.{key} not invariant "
                        f"(Baseline={b_sm[key]}, Slack-Plus={s_sm[key]})"
                    )
            for key in CATEGORICAL_INVARIANT_KEYS:
                if b_sm[key] != s_sm[key]:
                    failures.append(
                        f"{period}: summary_metrics.{key} not invariant "
                        f"(Baseline={b_sm[key]!r}, Slack-Plus={s_sm[key]!r})"
                    )

        if failures:
            self.fail(
                f"Baseline+Slack-Plus identity violated in {len(failures)} check(s):\n  "
                + "\n  ".join(failures)
            )

    def test_all_paired_releases_share_alpha_and_scale_factor(self):
        """Baseline and Slack-Plus must be produced with identical alpha and
        scale_factor for each period, or the identity does not hold."""
        pairs = self._discover_pairs()
        failures = []
        for period in pairs:
            b = json.loads(Path(f"data/outputs/dmi_release_{period}.json").read_text())
            s = json.loads(
                Path(f"data/outputs/dmi_release_{period}_slack_plus.json").read_text()
            )
            b_params = b.get("parameters", {})
            s_params = s.get("parameters", {})
            for key in ("alpha", "scale_factor"):
                if key in b_params or key in s_params:
                    if b_params.get(key) != s_params.get(key):
                        failures.append(
                            f"{period}: parameters.{key} diverges "
                            f"(Baseline={b_params.get(key)!r}, "
                            f"Slack-Plus={s_params.get(key)!r})"
                        )
        if failures:
            self.fail(
                "Baseline+Slack-Plus parameter drift:\n  " + "\n  ".join(failures)
            )


if __name__ == "__main__":
    unittest.main()
