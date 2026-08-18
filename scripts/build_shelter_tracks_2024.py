#!/usr/bin/env python3
"""Build the Track-A / Track-B shelter substrate and adjudicate the scope rules.

Detailed Inflation Substrate v0.1, shelter task, Phase D.

RESEARCH ONLY. Writes under ``data/research/`` and ``registry/research/`` and
reads only research artifacts and pinned registries. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree. It computes no index,
normalises no weight and produces no category inflation rate.

Usage::

    python3 scripts/build_shelter_tracks_2024.py

The predecessor registries are read and never written. Successors are written
at new paths, so the Milestone-2 and Phase-B states survive intact and a reader
can diff them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_adjudication as adj  # noqa: E402
from dmi_research.detailed_inflation import shelter_tracks as tracks  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    registry = tracks.load_scope_rules()
    provenance = json.loads(
        tracks.PROVENANCE_V0_1_PATH.read_text(encoding="utf-8")
    )
    adjudication = json.loads(
        adj.ADJUDICATION_PATH.read_text(encoding="utf-8")
    )
    reconciliation = tracks.load_reconciliation()
    aggregates = tracks.load_shelter_aggregates()
    basis = tracks.load_basis()

    verdicts = tracks.adjudicate_rules(registry, adjudication, aggregates, basis)

    print("rule adjudication (D4)")
    print(f"  {'rule':46}{'status':10}{'state':11}{'millions':>14}")
    for rule_id, verdict in verdicts.items():
        print(
            f"  {rule_id:46}{verdict.review_status:10}"
            f"{verdict.resolution_state:11}{verdict.materiality_all_cu:14,.0f}"
        )
        if verdict.blocker:
            print(f"      blocked: {verdict.blocker[:150]}...")

    track_a, track_b = tracks.build_tracks(
        registry, verdicts, aggregates, basis, adjudication
    )
    accounting = tracks.build_accounting(
        reconciliation, verdicts, registry, aggregates, basis, adjudication
    )
    audit = tracks.build_double_counting_audit(
        registry, verdicts, aggregates, basis, adjudication
    )

    print("\naccounting (D2), millions of dollars")
    header = (
        f"  {'population':11}{'E_source':>13}{'E_CPI':>13}{'Delta_scope':>13}"
        f"{'rent equiv':>13}{'removed':>12}{'Delta_shelter':>15}"
    )
    print(header)
    for population in pumd.POPULATIONS:
        e = accounting[population]
        print(
            f"  {population:11}{e.e_source:13,.0f}{e.e_cpi:13,.0f}"
            f"{e.delta_scope:13,.0f}{e.rental_equivalence_introduced:13,.0f}"
            f"{e.owner_outlays_removed:12,.0f}{e.delta_shelter:15,.0f}"
        )
    stranded = accounting["ALL_CU"].secondary_residence_outlays_removed_without_replacement
    print(
        f"\n  owned-vacation outlays removed with no replacement in effect: "
        f"{stranded:,.0f}"
    )
    withheld = accounting["ALL_CU"].rental_equivalence_withheld
    print(
        "  rental equivalence withheld from Track A: "
        + (f"{withheld:,.0f}" if withheld is not None else "no estimate")
    )

    print("\ndouble-counting audit (D3)")
    for row in audit:
        print(f"  {row.category:52}{row.track_a_disposition[:34]}")

    tracks.write_track_csv(tracks.CPI_TRACK_PATH, track_a)
    tracks.write_track_csv(tracks.PAYMENTS_TRACK_PATH, track_b)
    tracks.write_comparison_csv(tracks.COMPARISON_PATH, accounting)
    tracks.write_audit_csv(tracks.DOUBLE_COUNTING_PATH, audit)
    tracks.write_rule_adjudication(
        tracks.RULE_ADJUDICATION_PATH, verdicts, registry
    )
    tracks.write_accounting_summary(
        tracks.ACCOUNTING_PATH, accounting, verdicts, audit
    )

    scope_v0_2 = tracks.build_scope_rules_v0_2(
        registry, verdicts, aggregates, adjudication
    )
    tracks.SCOPE_RULES_V0_2_PATH.write_text(
        json.dumps(scope_v0_2, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    provenance_v0_3 = tracks.build_provenance_v0_3(
        provenance, adjudication, verdicts
    )
    tracks.PROVENANCE_V0_3_PATH.write_text(
        json.dumps(provenance_v0_3, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    written = (
        tracks.CPI_TRACK_PATH,
        tracks.PAYMENTS_TRACK_PATH,
        tracks.COMPARISON_PATH,
        tracks.DOUBLE_COUNTING_PATH,
        tracks.RULE_ADJUDICATION_PATH,
        tracks.ACCOUNTING_PATH,
        tracks.SCOPE_RULES_V0_2_PATH,
        tracks.PROVENANCE_V0_3_PATH,
    )
    print("\nwrote")
    for path in written:
        print(f"  {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
