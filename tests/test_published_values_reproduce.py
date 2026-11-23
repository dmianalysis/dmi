"""Published DMI values must be reproducible from committed inputs.

A runtime or dependency change, such as a new Python interpreter or a
NumPy or pandas refresh in ``requirements-lock/``, must not move a
published number. This test recomputes every published release whose
inputs are committed under ``data/staging/`` and ``data/curated/`` and
compares the result with the published raw artifact: every per-quintile
DMI, inflation and slack value, every summary metric, and every inflation
contribution.

Structure must match exactly: the same keys, the same groups and
categories in the same order, and identical non-float values. Each float must lie within
``MAX_ULPS`` units in the last place (ulp) of the published value.

Why not exact equality. numpy dispatches ``log`` and ``exp`` to
CPU-specific SIMD code. On x86 runners with AVX-512, the last bit of some
inflation contributions differs from runners without it: by one ulp at
most on Linux, two on Windows. A same-VM experiment on GitHub runners
during the Python 3.12 migration showed Python 3.9, 3.12 and 3.13 giving
identical results on any one machine, with the variation following the
CPU. Disabling AVX-512 dispatch removed it. DMI values and summary
metrics were exact everywhere. Published releases already carry whichever
last bits their runner produced.

``MAX_ULPS`` absorbs that and nothing more. It is about 1e-15 relative,
far tighter than the 1e-9 the release gate uses for price-side values in
``scripts/release_policy.py``. A library change that alters the
arithmetic moves values by much more. If this test fails after a
dependency refresh, do not update the published files. Revert the refresh
and report the differences (see requirements-lock/README.md).

The computation is in-memory: nothing is written and nothing touches the
network. Periods whose staged inputs were not committed are skipped by
construction, and the non-vacuity tests below require that both
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

#: Largest accepted float difference, in ulps of the published value.
#: See the module docstring for the measured basis.
MAX_ULPS = 4

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


def _compare(path: str, want, have, found: list[str]) -> None:
    if isinstance(want, dict) and isinstance(have, dict):
        # JSON object key order carries no meaning; list order does.
        if set(want) != set(have):
            found.append(f"{path}: keys {sorted(want)} != {sorted(have)}")
            return
        for key in want:
            _compare(f"{path}.{key}", want[key], have[key], found)
    elif isinstance(want, list) and isinstance(have, list):
        if len(want) != len(have):
            found.append(f"{path}: length {len(want)} != {len(have)}")
            return
        for i, (a, b) in enumerate(zip(want, have)):
            _compare(f"{path}[{i}]", a, b, found)
    elif isinstance(want, float) and isinstance(have, float):
        if want != have and abs(want - have) > MAX_ULPS * math.ulp(want):
            ulps = abs(want - have) / math.ulp(want)
            found.append(f"{path}: published={want!r} recomputed={have!r} ({ulps:.0f} ulp)")
    elif type(want) is not type(have) or want != have:
        found.append(f"{path}: published={want!r} recomputed={have!r}")


def differences(published: dict, recomputed: dict) -> list[str]:
    """Every structural difference, and every float beyond MAX_ULPS."""
    found: list[str] = []
    for field in COMPUTED_FIELDS:
        _compare(field, published.get(field), _normalise(recomputed.get(field)), found)
    return found


class TestPublishedValuesReproduce(unittest.TestCase):

    def test_every_reproducible_release_matches(self):
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
        cases = reproducible_cases()
        self.assertEqual({spec for _, spec, _ in cases}, set(SPECS),
                         "a specification has no reproducible case")
        self.assertGreaterEqual(len(cases), 5)


class TestComparisonIsNotVacuous(unittest.TestCase):
    """The comparison must accept CPU-level noise and reject anything more."""

    def _case(self):
        _, _, artifact = reproducible_cases()[0]
        published = json.loads(artifact.read_text())
        return published, _normalise(published)

    @staticmethod
    def _nudge(value: float, ulps: int) -> float:
        for _ in range(ulps):
            value = math.nextafter(value, math.inf)
        return value

    def test_differences_within_max_ulps_are_accepted(self):
        published, recomputed = self._case()
        self.assertEqual(differences(published, recomputed), [])
        row = recomputed["inflation_contributions"][0]
        row["contribution"] = self._nudge(row["contribution"], MAX_ULPS)
        self.assertEqual(differences(published, recomputed), [])

    def test_flags_a_change_just_beyond_max_ulps(self):
        published, recomputed = self._case()
        row = recomputed["dmi_by_group"][0]
        row["dmi"] = self._nudge(row["dmi"], MAX_ULPS + 1)
        found = differences(published, recomputed)
        self.assertEqual(len(found), 1, found)
        self.assertIn("dmi_by_group[0].dmi", found[0])

    def test_flags_a_real_arithmetic_change(self):
        published, recomputed = self._case()
        recomputed["summary_metrics"]["dmi_median"] *= 1 + 1e-12
        self.assertEqual(len(differences(published, recomputed)), 1)

    def test_flags_structural_changes(self):
        published, recomputed = self._case()
        recomputed["dmi_by_group"][0]["group_id"] = "Q9"
        recomputed["inflation_contributions"].pop()
        recomputed["summary_metrics"]["extra"] = 1.0
        self.assertEqual(len(differences(published, recomputed)), 3)

    def test_bound_is_far_tighter_than_the_release_gate(self):
        from scripts.release_policy import PRICE_TOLERANCE
        largest = max(
            abs(value)
            for _, _, artifact in reproducible_cases()
            for field in COMPUTED_FIELDS
            for value in _float_leaves(json.loads(artifact.read_text())[field])
        )
        self.assertLess(MAX_ULPS * math.ulp(largest), PRICE_TOLERANCE / 1e5)


def _float_leaves(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from _float_leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from _float_leaves(v)
    elif isinstance(value, float):
        yield value


if __name__ == "__main__":
    unittest.main()
