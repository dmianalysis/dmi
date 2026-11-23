"""Published DMI values must be reproducible from committed inputs.

A runtime or dependency change (a new Python interpreter, a NumPy or
pandas refresh in ``requirements-lock/``) must not move a published
number. This test recomputes every published release whose inputs are
committed under ``data/staging/`` and ``data/curated/`` and requires the
result to equal the published raw artifact EXACTLY: every per-quintile
DMI, inflation and slack value, every summary metric, and every
inflation contribution, compared as floats without tolerance.

Exact equality is deliberate. The Python 3.9 -> 3.12/3.13 migration was
verified to reproduce these artifacts bit for bit, so any difference now
means a library changed its arithmetic. That is a methodology-review
question, not something to absorb into a tolerance. If this test fails
after a dependency refresh, do not update the published files; revert the
refresh and report the differences (see requirements-lock/README.md).

The computation is in-memory: nothing is written and nothing touches the
network. Periods whose staged inputs were not committed are skipped by
construction and the non-vacuity test below requires that both
specifications are still exercised.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import unittest
from pathlib import Path

from scripts.compute_dmi import (
    compute_dmi_for_period,
    load_cpi_data,
    load_slack_data,
    load_weights,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "data" / "outputs"
STAGING = ROOT / "data" / "staging"
CURATED = ROOT / "data" / "curated"

#: Fields of the raw artifact that carry computed values. Metadata such
#: as ``computed_at`` is excluded; it records when, not what.
COMPUTED_FIELDS = ("dmi_by_group", "summary_metrics", "inflation_contributions")

SPECS = {
    # spec id: (raw artifact suffix, staged slack measure)
    "baseline": ("", "u3"),
    "slack_plus": ("_slack_plus", "u6"),
}


def _staging_window(period: str) -> tuple[int, int]:
    # Mirrors scripts.compute_dmi_release.staging_window_for_period, which
    # is not imported because that module also wires up network fetches.
    year, month = (int(x) for x in period.split("-"))
    return (year, year + 1) if month >= 11 else (year - 1, year)


def published_periods() -> list[str]:
    manifest = json.loads((OUTPUTS / "releases.json").read_text())
    return sorted({r["release_id"] for r in manifest["releases"]})


def reproducible_cases() -> list[tuple[str, str, Path]]:
    """(period, spec, published artifact) for every case with committed inputs."""
    cases = []
    for period in published_periods():
        start, end = _staging_window(period)
        cpi = STAGING / f"cpi_levels_{start}_{end}.json"
        for spec, (suffix, measure) in SPECS.items():
            artifact = OUTPUTS / f"dmi_release_{period}{suffix}.json"
            slack = STAGING / f"slack_{measure}_{start}_{end}.json"
            if not (artifact.is_file() and cpi.is_file() and slack.is_file()):
                continue
            cpi_periods = {row["period"] for row in json.loads(cpi.read_text())["data"]}
            slack_periods = {row["period"] for row in json.loads(slack.read_text())}
            if period in cpi_periods and period in slack_periods:
                cases.append((period, spec, artifact))
    return cases


def recompute(period: str, spec: str, published: dict) -> dict:
    start, end = _staging_window(period)
    _, measure = SPECS[spec]
    params = published["parameters"]
    weights_year = params["weights_year"]
    with contextlib.redirect_stdout(io.StringIO()):
        return compute_dmi_for_period(
            cpi_df=load_cpi_data(STAGING / f"cpi_levels_{start}_{end}.json"),
            weights_df=load_weights(CURATED / f"weights_by_group_{weights_year}.json"),
            slack_df=load_slack_data(STAGING / f"slack_{measure}_{start}_{end}.json"),
            reference_period=period,
            alpha=params["alpha"],
            scale_factor=params["scale_factor"],
            weights_year=weights_year,
            spec=spec,
        )


def _normalise(value):
    """Round-trip through JSON so types match what was published."""
    return json.loads(json.dumps(value))


def differences(published: dict, recomputed: dict) -> list[str]:
    found = []
    for field in COMPUTED_FIELDS:
        want = published.get(field)
        have = _normalise(recomputed.get(field))
        if want != have:
            found.append(f"{field}: published={want!r} recomputed={have!r}")
    return found


class TestPublishedValuesReproduce(unittest.TestCase):

    def test_every_reproducible_release_matches_exactly(self):
        for period, spec, artifact in reproducible_cases():
            with self.subTest(period=period, spec=spec):
                published = json.loads(artifact.read_text())
                found = differences(published, recompute(period, spec, published))
                self.assertEqual(
                    found, [],
                    f"{artifact.name} no longer reproduces from committed "
                    "inputs. A runtime or dependency change altered published "
                    "values; revert it and report the difference rather than "
                    "regenerating the release.",
                )

    def test_both_specifications_are_exercised(self):
        """Non-vacuity: the check must not pass by reproducing nothing."""
        specs = {spec for _, spec, _ in reproducible_cases()}
        self.assertEqual(specs, set(SPECS), "a specification has no reproducible case")
        self.assertGreaterEqual(len(reproducible_cases()), 5)

    def test_detector_flags_a_last_bit_change(self):
        """Non-vacuity: a one-ulp change to one value must be reported."""
        period, spec, artifact = reproducible_cases()[0]
        published = json.loads(artifact.read_text())
        recomputed = recompute(period, spec, published)
        self.assertEqual(differences(published, recomputed), [])
        dmi = recomputed["dmi_by_group"][0]["dmi"]
        recomputed["dmi_by_group"][0]["dmi"] = math.nextafter(dmi, math.inf)
        self.assertEqual(len(differences(published, recomputed)), 1)


if __name__ == "__main__":
    unittest.main()
