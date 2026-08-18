#!/usr/bin/env python3
"""Estimate the 2024 shelter rental-equivalence UCCs under a frozen plan.

Detailed Inflation Substrate v0.1, shelter task, Phases C2-C5.

RESEARCH ONLY. Writes under ``data/research/`` and ``registry/research/`` and
reads only research registries and the pinned PUMD archive. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

Two deliberately separate commands, because the ordering is the point::

    python3 scripts/estimate_shelter_2024.py freeze
    git commit registry/research/shelter_estimation_spec_v0_1.json
    python3 scripts/estimate_shelter_2024.py run --pumd-dir ...

``freeze`` reads no microdata and refuses to overwrite an existing plan.
``run`` refuses to start unless the plan is already in git history, and
refuses to continue if any pinned estimator module has changed since. An
estimation plan therefore cannot be adjusted after an inconvenient number has
been seen without the adjustment being visible in the commit graph.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_source as source  # noqa: E402
from dmi_research.detailed_inflation import shelter_estimation as est  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
ESTIMATES_PATH = OUTPUT_DIR / "shelter_estimates_2024.csv"
COUNTERPART_PATH = OUTPUT_DIR / "counterpart_validation_2024.csv"
SUMMARY_PATH = OUTPUT_DIR / "shelter_estimation_summary.json"
SPEC_PATH = est.SPEC_PATH

CELL_COLUMNS = (
    "ucc",
    "population",
    "cell_status",
    "unweighted_record_count",
    "reporting_consumer_units",
    "weighted_population",
    "annual_mean_per_consumer_unit",
    "annual_aggregate_dollars",
    "annual_aggregate_millions",
    "standard_error",
    "relative_standard_error_pct",
    "interval_low",
    "interval_high",
    "replicate_min",
    "replicate_max",
    "replicates_at_zero",
    "high_rse_informational_flag",
)


def _spec_is_committed() -> bool:
    result = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", str(SPEC_PATH.relative_to(REPO_ROOT))],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def freeze() -> int:
    if SPEC_PATH.exists():
        print(
            f"refusing to overwrite {SPEC_PATH.relative_to(REPO_ROOT)}.\n"
            "The plan is already frozen. Rewriting it after a run would "
            "defeat the freeze; supersede it with a new version instead."
        )
        return 1
    spec = est.build_spec()
    SPEC_PATH.parent.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {SPEC_PATH.relative_to(REPO_ROOT)}")
    print(f"  spec_version              {spec['spec_version']}")
    print(f"  estimator commit          {spec['estimator']['frozen_commit']}")
    print(f"  UCCs estimated            {len(spec['uccs']['estimated'])}")
    print(f"  archive sha256            {spec['source_archive']['sha256']}")
    for name, digest in sorted(spec["estimator"]["pinned_module_digests"].items()):
        print(f"  pinned {name}\n         {digest}")
    print("\nCommit this file before running. The runner will refuse otherwise.")
    return 0


def _write_cells(cells) -> None:
    with ESTIMATES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CELL_COLUMNS)
        for cell in cells:
            writer.writerow(
                [
                    cell.ucc,
                    cell.population,
                    cell.cell_status,
                    cell.unweighted_record_count,
                    cell.reporting_consumer_units,
                    f"{cell.weighted_population:.3f}",
                    _num(cell.annual_mean_per_consumer_unit),
                    _num(cell.annual_aggregate_dollars),
                    _num(cell.annual_aggregate_millions),
                    _num(cell.standard_error),
                    _num(cell.relative_standard_error_pct),
                    _num(cell.interval_low),
                    _num(cell.interval_high),
                    _num(cell.replicate_min),
                    _num(cell.replicate_max),
                    "" if cell.replicates_at_zero is None else cell.replicates_at_zero,
                    "true" if cell.high_rse else "false",
                ]
            )


def _num(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def _write_counterparts(comparisons) -> None:
    with COUNTERPART_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "ucc",
                "population",
                "published_periodicity",
                "published_mean",
                "estimated_annual_mean",
                "ratio_estimate_over_published",
            )
        )
        for c in comparisons:
            writer.writerow(
                [
                    c.ucc,
                    c.population,
                    c.published_periodicity,
                    f"{c.published_mean:.1f}",
                    f"{c.estimated_mean:.6f}",
                    f"{c.ratio:.6f}",
                ]
            )


def run(pumd_dir: str | None) -> int:
    spec = est.load_spec()

    if not _spec_is_committed():
        print(
            f"refusing to run: {SPEC_PATH.relative_to(REPO_ROOT)} is not in git "
            "history.\nCommit the frozen plan first, so that any later edit to "
            "it is visible as an edit made after the estimates existed."
        )
        return 1
    est.assert_estimator_untouched(spec)
    print("frozen plan verified")
    print(f"  spec_version      {spec['spec_version']}")
    print(f"  estimator commit  {spec['estimator']['frozen_commit']}")
    print("  pinned module digests all match")

    directory = pumd.locate_interview_csv_dir(pumd_dir)
    digests = source.verify_archive_members(directory)
    print(f"  archive members verified: {len(digests)} of {len(digests)}")

    units = pumd.read_all_fmli(directory)
    keep = frozenset(est.ESTIMATED_UCCS)
    records = pumd.read_all_mtbi(directory, keep)
    print(f"  consumer units {len(units)}, in-scope shelter records {len(records)}")

    cells = est.estimate_cells(units, records)
    comparisons = est.compare_counterparts(cells, spec)
    tolerance = float(spec["counterpart_validation"]["ratio_consistency_tolerance_pct"])
    consistency = est.ratio_consistency(comparisons, tolerance)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _write_cells(cells)
    _write_counterparts(comparisons)

    print("\nshelter UCC estimates, dollars per consumer unit per year")
    header = (
        f"  {'UCC':8}{'pop':6}{'status':11}{'recs':>6}{'CUs':>6}"
        f"{'mean':>12}{'SE':>10}{'RSE%':>8}{'rep=0':>7}"
    )
    print(header)
    for cell in cells:
        if cell.ucc not in est.SHELTER_UCCS:
            continue
        print(
            f"  {cell.ucc:8}{cell.population:6}{cell.cell_status:11}"
            f"{cell.unweighted_record_count:>6}{cell.reporting_consumer_units:>6}"
            f"{_fmt(cell.annual_mean_per_consumer_unit, 2):>12}"
            f"{_fmt(cell.standard_error, 2):>10}"
            f"{_fmt(cell.relative_standard_error_pct, 1):>8}"
            f"{'' if cell.replicates_at_zero is None else cell.replicates_at_zero:>7}"
        )

    print("\ncounterpart validation: estimate / published LB01")
    print(f"  {'UCC':8}{'periodicity':13}{'All CU ratio':>14}{'min':>10}{'max':>10}"
          f"{'max dev %':>11}  consistent")
    for ucc in est.PUBLISHED_COUNTERPART_UCCS:
        entry = consistency.get(ucc)
        if entry is None:
            print(f"  {ucc:8}  no comparison available")
            continue
        print(
            f"  {ucc:8}{str(entry.get('published_periodicity','')):13}"
            f"{entry['all_cu_ratio']:>14.4f}{entry['min_ratio']:>10.4f}"
            f"{entry['max_ratio']:>10.4f}"
            f"{entry.get('max_deviation_pct', float('nan')):>11.2f}"
            f"  {entry['consistent']}"
        )

    summary = {
        "phase": "C3-C5",
        "status": "RESEARCH_ONLY",
        "spec": str(SPEC_PATH.relative_to(REPO_ROOT)),
        "spec_version": spec["spec_version"],
        "frozen_estimator_commit": spec["estimator"]["frozen_commit"],
        "frozen_estimator_tag": spec["estimator"]["frozen_tag"],
        "confirmation_status": spec["estimator"]["confirmation"]["status"],
        "source_reproduction_status": spec["source_archive"]["reproduction"]["status"],
        "archive_sha256": spec["source_archive"]["sha256"],
        "consumer_units_read": len(units),
        "in_scope_records_read": len(records),
        "cells": len(cells),
        "cells_with_no_records": sum(1 for c in cells if c.cell_status == est.NO_RECORDS),
        "shelter_cells_with_no_records": sorted(
            f"{c.ucc}/{c.population}"
            for c in cells
            if c.cell_status == est.NO_RECORDS and c.ucc in est.SHELTER_UCCS
        ),
        "shelter_cells_high_rse": sorted(
            f"{c.ucc}/{c.population}"
            for c in cells
            if c.ucc in est.SHELTER_UCCS and c.high_rse
        ),
        "high_rse_informational_threshold_pct": (
            est.HIGH_RSE_INFORMATIONAL_THRESHOLD_PCT
        ),
        "counterpart_ratio_consistency": consistency,
        "counterpart_ratio_tolerance_pct": tolerance,
        "units": {
            "annual_mean_per_consumer_unit": "dollars per consumer unit per year",
            "annual_aggregate_dollars": "dollars per year",
            "annual_aggregate_millions": "millions of dollars per year",
            "standard_error": "dollars per consumer unit per year",
            "relative_standard_error_pct": "percent",
            "weighted_population": "consumer units",
        },
        "shelter_estimates": {
            f"{c.ucc}/{c.population}": {
                "cell_status": c.cell_status,
                "unweighted_record_count": c.unweighted_record_count,
                "reporting_consumer_units": c.reporting_consumer_units,
                "annual_mean_per_consumer_unit": c.annual_mean_per_consumer_unit,
                "annual_aggregate_dollars": c.annual_aggregate_dollars,
                "standard_error": c.standard_error,
                "relative_standard_error_pct": c.relative_standard_error_pct,
                "interval_low": c.interval_low,
                "interval_high": c.interval_high,
                "replicates_at_zero": c.replicates_at_zero,
                "high_rse_informational_flag": c.high_rse,
            }
            for c in cells
            if c.ucc in est.SHELTER_UCCS
        },
    }
    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for path in (ESTIMATES_PATH, COUNTERPART_PATH, SUMMARY_PATH):
        print(f"wrote {path.relative_to(REPO_ROOT)}")
    return 0


def _fmt(value: float | None, places: int) -> str:
    return "-" if value is None else f"{value:.{places}f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze", help="write the estimation plan; reads no microdata")
    runner = sub.add_parser("run", help="estimate under the frozen plan")
    runner.add_argument("--pumd-dir", default=None)
    args = parser.parse_args()

    if args.command == "freeze":
        return freeze()
    return run(args.pumd_dir)


if __name__ == "__main__":
    raise SystemExit(main())
