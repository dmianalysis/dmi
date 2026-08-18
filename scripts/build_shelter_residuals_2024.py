#!/usr/bin/env python3
"""Adjudicate the residual Track-A shelter allocation questions.

Detailed Inflation Substrate v0.1, shelter residuals task, Phase B.

RESEARCH ONLY. Writes under ``data/research/`` and ``registry/research/`` and
reads only research artifacts and pinned registries. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree. It computes no index,
normalises no weight and produces no category inflation rate.

Usage::

    python3 scripts/build_shelter_residuals_2024.py

The shelter-milestone registries are read and never written. Successors are
written at new paths, so re-running ``scripts/build_shelter_tracks_2024.py``
still reproduces the frozen milestone state exactly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_residuals as res  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    basis = res.load_basis()
    predecessor_rules = res.load_predecessor_rules()
    predecessor_provenance = res.load_predecessor_provenance()
    summary = res.load_accounting_summary()

    rows = res.build_ucc_matrix(basis)
    before_after = res.build_before_after(summary, basis)
    verdict = res.build_verdict(basis, before_after)

    print("evidence by vintage (B2)")
    for cls, count in res.build_evidence_registry()["counts_by_vintage"].items():
        print(f"  {cls:26}{count:3}")

    print("\nowner-structure split (B4/B9), millions of dollars")
    print(f"  {'successor rule':46}{'status':10}{'members':>8}{'all CU':>12}")
    for rule in res.SUCCESSOR_RULES:
        amount = sum(basis[(u, "ALL_CU")] or 0.0 for u in rule.source_uccs)
        print(
            f"  {rule.rule_id:46}{rule.successor_status:10}"
            f"{len(rule.source_uccs):8}{amount:12,.0f}"
        )
        if rule.blocker_kind:
            print(f"      held: {rule.blocker_kind}")

    print("\nheld rules, evidence updated without status change")
    for spec in res.HELD_RULE_UPDATES:
        print(f"  {spec['rule_id']:52}{spec['successor_status']:10}{spec['blocker_kind']}")

    print("\nbefore/after accounting (B11), millions of dollars")
    keys = ("accepted_out_of_scope", "pending_proposed", "unresolved_open")
    print(f"  {'population':11}" + "".join(f"{k:>28}" for k in keys))
    lookup = {(r.population, r.quantity): r for r in before_after}
    for population in pumd.POPULATIONS:
        cells = []
        for key in keys:
            row = lookup[(population, key)]
            cells.append(f"{row.before:12,.0f} ->{row.after:12,.0f}")
        print(f"  {population:11}" + "".join(f"{c:>28}" for c in cells))

    print("\nquantities this task did not move (B7)")
    for quantity, change in verdict["quantities_unchanged_by_this_task"].items():
        row = lookup[("ALL_CU", quantity)]
        print(f"  {quantity:16}{row.before:16,.0f}{row.after:16,.0f}{change:12,.0f}")

    print(f"\nresidual_shelter_status: {verdict['residual_shelter_status']}")

    res.write_ucc_matrix(res.UCC_MATRIX_PATH, rows)
    res.write_before_after(res.BEFORE_AFTER_PATH, before_after)
    res.write_rule_transitions(res.RULE_TRANSITIONS_PATH, basis)
    res.write_json(res.VERDICT_PATH, verdict)
    res.write_json(res.EVIDENCE_PATH, res.build_evidence_registry())
    res.write_json(
        res.SCOPE_RULES_V0_3_PATH,
        res.build_scope_rules_v0_3(predecessor_rules, basis),
    )
    res.write_json(
        res.PROVENANCE_V0_4_PATH,
        res.build_provenance_v0_4(predecessor_provenance),
    )

    written = (
        res.UCC_MATRIX_PATH,
        res.BEFORE_AFTER_PATH,
        res.RULE_TRANSITIONS_PATH,
        res.VERDICT_PATH,
        res.EVIDENCE_PATH,
        res.SCOPE_RULES_V0_3_PATH,
        res.PROVENANCE_V0_4_PATH,
    )
    print("\nwrote")
    for path in written:
        print(f"  {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
