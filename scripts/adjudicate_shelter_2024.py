#!/usr/bin/env python3
"""Adjudicate the usability and quality of the 2024 shelter estimates.

Detailed Inflation Substrate v0.1, shelter task, Phase C6.

RESEARCH ONLY. Writes under ``data/research/`` and reads only research
registries, research artifacts and the pinned PUMD archive. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

Usage::

    python3 scripts/adjudicate_shelter_2024.py --pumd-dir ...

The estimation is recomputed rather than read back from the CSV, and the
recomputed means are checked against the committed summary. An adjudication
built on an artifact that no longer reproduces would be an adjudication of
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_source as source  # noqa: E402
from dmi_research.detailed_inflation import shelter_estimation as est  # noqa: E402
from dmi_research.detailed_inflation import shelter_adjudication as adj  # noqa: E402

REPRODUCTION_TOLERANCE = 1e-9


def _check_reproduces(cells) -> list[str]:
    """Do the recomputed shelter means match the committed summary?"""
    summary = adj.load_summary()
    recorded = summary["shelter_estimates"]
    problems: list[str] = []
    for cell in cells:
        if cell.ucc not in est.SHELTER_UCCS:
            continue
        key = f"{cell.ucc}/{cell.population}"
        if key not in recorded:
            problems.append(f"{key} absent from the committed summary")
            continue
        was = recorded[key]["annual_mean_per_consumer_unit"]
        now = cell.annual_mean_per_consumer_unit
        if was is None or now is None:
            if was is not now:
                problems.append(f"{key}: {was!r} then, {now!r} now")
            continue
        if abs(was - now) > REPRODUCTION_TOLERANCE:
            problems.append(f"{key}: {was} then, {now} now")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pumd-dir", default=None)
    args = parser.parse_args()

    spec = est.load_spec()
    est.assert_estimator_untouched(spec)
    print("frozen plan verified, pinned module digests all match")

    directory = pumd.locate_interview_csv_dir(args.pumd_dir)
    source.verify_archive_members(directory)
    units = pumd.read_all_fmli(directory)
    records = pumd.read_all_mtbi(directory, frozenset(est.ESTIMATED_UCCS))
    cells = est.estimate_cells(units, records)

    problems = _check_reproduces(cells)
    if problems:
        print("\nthe committed estimates no longer reproduce:")
        for problem in problems:
            print(f"  {problem}")
        print("\nrefusing to adjudicate estimates that have moved.")
        return 1
    print("committed estimates reproduce exactly")

    structures = adj.measure_pairs(records)
    tolerance = float(spec["counterpart_validation"]["ratio_consistency_tolerance_pct"])
    comparisons = est.compare_counterparts(cells, spec)
    consistency = est.ratio_consistency(comparisons, tolerance)

    print("\nasserted pairing, measured at the record level")
    print(f"  {'pair':18}{'shared':>8}{'=12x':>12}{'whole weeks':>13}  relation")
    for concordance, s in structures.items():
        twelve = "-" if s.exact_twelve_share is None else f"{100*s.exact_twelve_share:.1f}%"
        weeks = "-" if s.integer_week_share is None else f"{100*s.integer_week_share:.1f}%"
        print(
            f"  {s.published_ucc}->{s.concordance_ucc:9}{s.comparable_keys:>8}"
            f"{twelve:>12}{weeks:>13}  {s.relation}"
        )
    for concordance, s in structures.items():
        if s.relation == adj.WEEKS_OWNED_SHARE:
            print(f"  {s.published_ucc}->{concordance} weeks owned: {s.week_tally}")

    verdicts = adj.adjudicate(cells, structures, consistency)

    print("\nadjudication")
    print(f"  {'UCC':8}{'usability':18}{'quality':11}{'Track A':>9}")
    for ucc, v in verdicts.items():
        print(
            f"  {ucc:8}{v.pumd_quantitative_usability:18}"
            f"{v.pumd_estimate_quality:11}"
            f"{'admitted' if v.track_a_admissible else 'withheld':>9}"
        )
        for test in v.tests:
            print(f"      {'ok  ' if test.passed else 'FAIL'} {test.name}")
        for population, band in v.per_population_quality.items():
            print(f"          {population:8}{band}")

    payload = {
        "phase": "C6",
        "status": "RESEARCH_ONLY",
        "spec_version": spec["spec_version"],
        "frozen_estimator_commit": spec["estimator"]["frozen_commit"],
        "published_item_text": dict(adj.PUBLISHED_ITEM_TEXT),
        "published_item_text_source": adj.PUBLISHED_ITEM_TEXT_SOURCE,
        "pair_structure": {
            concordance: asdict(structure)
            for concordance, structure in structures.items()
        },
        "pair_structure_note": (
            "The pairing came into this task as a DMI_INFERENCE resting on "
            "matching concept names and matching order. These are measurements "
            "of it, made after the estimates existed, which is stated rather "
            "than hidden. They changed no estimate: the runner's outputs were "
            "written before any of this was computed and are byte-identical on "
            "recomputation."
        ),
        "usability_definitions": dict(adj.USABILITY_DEFINITIONS),
        "quality_scale_definition": dict(adj.QUALITY_SCALE_DEFINITION),
        "quality_is_not_usability": (
            "pumd_quantitative_usability describes whether a validated "
            "aggregation procedure reaches this UCC's records. "
            "pumd_estimate_quality describes how precise the resulting cell "
            "is. The frozen plan required these to stay apart and forbade the "
            "25 percent RSE flag from becoming a usability rule. The RSE "
            "bands appear only in the quality field; the usability tests do "
            "not read an RSE anywhere."
        ),
        "counterpart_ratio_consistency": consistency,
        "adjudication": {
            ucc: {
                **{
                    k: v
                    for k, v in asdict(verdict).items()
                    if k not in ("tests",)
                },
                "tests": [asdict(t) for t in verdict.tests],
            }
            for ucc, verdict in verdicts.items()
        },
        "track_a_admitted": sorted(
            ucc for ucc, v in verdicts.items() if v.track_a_admissible
        ),
        "track_a_withheld": sorted(
            ucc for ucc, v in verdicts.items() if not v.track_a_admissible
        ),
    }
    adj.ADJUDICATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    adj.ADJUDICATION_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"\nwrote {adj.ADJUDICATION_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
