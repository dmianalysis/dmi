#!/usr/bin/env python3
"""Detailed Inflation Substrate v0.1, Milestone 2 -- CE->CPI scope resolution.

Research-only. This command resolves the 58 Milestone-1 exception UCCs against
the pinned scope-rule registry, classifies their exposure to suppressed BLS
observations, validates the ELI->node mapping semantically, and proves that no
expenditure disappears. It does not normalize weights, acquire CPI prices, or
compute any inflation index. Core DMI remains withdrawn and unimplemented, and
nothing here is wired into ``dmi_calculator``.

The Track-A owner-occupied shelter rule is deliberately not finalized here. The
four shelter-coupled rules remain PROPOSED and the three shelter CSVs named in
spec section 17 are not written, because the PUMD annual-weighting and quintile
procedure has not yet been validated against published 2024 LB01 LABSTAT
benchmarks.

Example
-------
    python scripts/resolve_detailed_inflation_2024.py \
        --series   /path/to/cx.series_2024_dmi_target.tsv \
        --data     /path/to/cx.data.1.AllData \
        --items    /path/to/cx.item \
        --aspects  /path/to/cx.aspect_2024_dmi_target.tsv

Attribution: source data are published by the U.S. Bureau of Labor Statistics
(Consumer Expenditure Surveys; Consumer Price Index; UCC-ELI concordance;
Handbook of Methods Appendix 2).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dmi_research.detailed_inflation.audit import run_audit  # noqa: E402
from dmi_research.detailed_inflation.concordance import (  # noqa: E402
    DEFAULT_CONCORDANCE_PATH,
)
from dmi_research.detailed_inflation.provenance import (  # noqa: E402
    UccProvenanceClass,
    build_ucc_provenance,
    write_provenance_csv,
)
from dmi_research.detailed_inflation.resolution import (  # noqa: E402
    ALL_CU,
    build_resolution,
    write_artifacts,
)
from dmi_research.detailed_inflation.scope_rules import (  # noqa: E402
    ReviewStatus,
    load_scope_rules,
)
from dmi_research.detailed_inflation.semantics import (  # noqa: E402
    build_semantic_validation,
    write_semantic_validation_csv,
)
from dmi_research.detailed_inflation.sources import (  # noqa: E402
    TARGET_YEAR,
    load_items,
)
from dmi_research.detailed_inflation.taxonomy import (  # noqa: E402
    load_eli_resolver,
    load_taxonomy,
)

DEFAULT_OUTPUT_DIR = Path("data/research/detailed_inflation/milestone_2")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--series", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--aspects", type=Path, required=True)
    parser.add_argument("--concordance", type=Path, default=DEFAULT_CONCORDANCE_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--year", type=int, default=TARGET_YEAR)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and report without writing artifacts.",
    )
    return parser


def _print_report(resolution, sem, provenance, registry, written) -> None:
    summary = resolution.summary
    print("Detailed Inflation Substrate v0.1 — Milestone 2 scope resolution")
    print(f"  exceptions resolved:   {summary['exception_count']}")
    print(f"  index computed:        {summary['index_computed']}")
    print(f"  weights normalized:    {summary['weights_normalized']}")

    print("\n  Track A disposition (proposed is not the same claim as effective):")
    print(f"    {'status':16s} {'proposed':>9s} {'effective':>10s}")
    statuses = sorted(
        set(summary["track_a_proposed_status_counts"])
        | set(summary["track_a_effective_status_counts"])
    )
    for key in statuses:
        print(
            f"    {key:16s} "
            f"{summary['track_a_proposed_status_counts'].get(key, 0):9d} "
            f"{summary['track_a_effective_status_counts'].get(key, 0):10d}"
        )
    print("    resolution state:")
    for key, count in sorted(summary["resolution_state_counts"].items()):
        print(f"      {key:14s} {count:3d}")

    print("\n  Headline (All Consumer Units, % of observed CE basis):")
    all_cu = summary["headline"]["by_population"][ALL_CU]
    for label, key in (
        ("left unexplained by Milestone 1", "milestone_1_unexplained"),
        ("now has a proposed disposition", "with_a_proposed_disposition"),
        ("accepted, transformed", "accepted_transformed"),
        ("accepted, out of scope", "accepted_out_of_scope"),
        ("effective in force overall", "effective_now"),
        ("PENDING proposed shelter rules", "pending_proposed"),
        ("still open, no disposition", "unresolved_open"),
    ):
        block = all_cu[key]
        print(
            f"    {label:32s} {block['expenditure']:12,.0f} $M  "
            f"{block['pct_of_basis']:8.4f}%"
        )
    print(f"    {summary['headline']['statement']}")

    print("\n  Track B treatment (section 7, payments concept):")
    for key, count in sorted(summary["track_b_treatment_counts"].items()):
        print(f"    {key:30s} {count:3d}")
    retained = summary["track_b_retained_expenditure"][ALL_CU]
    print(
        f"    All-CU expenditure retained by Track B but not Track A: "
        f"{retained['observed_expenditure']:,.0f} ($M observed, "
        f"{retained['suppressed_cell_count']} suppressed cells)"
    )

    print("\n  Section 16 suppression exposure, per UCC:")
    for key, count in sorted(summary["suppression_status_counts"].items()):
        print(f"    {key:12s} {count:3d}")

    print("\n  Section 16 suppression exposure, per rule (declared vs computed):")
    mismatches = 0
    for rule_id, check in sorted(summary["rule_suppression_declared_vs_computed"].items()):
        flag = "ok" if check["agrees"] else "MISMATCH"
        if not check["agrees"]:
            mismatches += 1
        print(
            f"    {flag:8s} {rule_id:44s} declared {check['declared']:11s} "
            f"computed {check['computed']}"
        )

    print("\n  Section 19.1 accounting identity (no expenditure may disappear):")
    for row in summary["reconciliation"]:
        print(
            f"    {row['population']:20s} basis {row['ce_observed_basis']:12,.0f}  "
            f"= retained {row['retained']:12,.0f} "
            f"+ accepted-transformed {row['accepted_transformed']:9,.0f} "
            f"+ accepted-out-of-scope {row['accepted_out_of_scope']:9,.0f} "
            f"+ pending-proposed {row['pending_proposed']:11,.0f} "
            f"+ unresolved-open {row['unresolved_open']:8,.0f}   "
            f"residual {row['residual']:+.6f}"
        )
    print(
        "    suppressed expenditure is bounded from published BLS parents at no "
        f"more than "
        f"{max(r['suppressed_upper_bound_pct_of_basis'] for r in summary['reconciliation']):.4f}%"
        " of basis in any population, and is never coerced to zero."
    )

    print("\n  Section 19.2 replacement accounting:")
    for rule_id, block in sorted(summary["replacement_accounting"].items()):
        removed = block["removed_owner_outlay"][ALL_CU]
        print(
            f"    {rule_id}: removed owner outlay "
            f"{removed['observed_removed_expenditure']:,.0f} ($M All-CU); "
            f"replacement {block['status']}"
        )

    print("\n  Section 15 ELI→node semantic validation:")
    print(f"    ELIs reviewed:        {sem['eli_count']}")
    for key in ("CONSISTENT", "CONSISTENT_BY_DESIGN", "DIVERGENT", "NO_BLS_DESCRIPTION"):
        print(f"    {key:22s} {sem['review_result_counts'].get(key, 0):3d}")
    unexplained = sem["elis_without_bls_description_unexplained"]
    print(f"    undescribed & unexplained: {len(unexplained)}")

    print("\n  UCC provenance classes (cx.item is not the whole CPI universe):")
    for member in UccProvenanceClass:
        print(f"    {member.value:24s} {provenance.counts[member.value]:4d}")
    hidden = provenance.by_class(UccProvenanceClass.CONCORDANCE_ONLY_UCC)
    print(
        f"    {len(hidden)} concordance UCC(s) are absent from cx.item and would "
        f"be invisible to a cx.item-keyed pipeline. The class is source-file "
        f"membership only; PUMD availability and CPI adjustment are separate "
        f"claims and are shown per UCC. Note that pumd=VERIFIED means the code "
        f"was found in the microdata, not that an amount can be derived for it: "
        f"that is the separate aggregable= column, which is NOT_ESTABLISHED "
        f"everywhere because no weighting procedure has been benchmarked."
    )
    for row in hidden:
        print(
            f"      {row.ucc}  {row.dmi_node or '-':36s} "
            f"pumd={row.pumd_membership.value:12s} "
            f"aggregable={row.pumd_quantitative_usability.value:15s} "
            f"cpi_adj={row.cpi_adjustment_status.value:8s} "
            f"why_unpublished={row.publication_reason.value:12s} "
            f"{row.concordance_title}"
        )

    proposed = [r.rule_id for r in registry.rules if r.review_status is ReviewStatus.PROPOSED]
    print(f"\n  Shelter-coupled rules still PROPOSED ({len(proposed)}):")
    for rule_id in proposed:
        print(f"    {rule_id}")
    for note in summary["pending_shelter_work"]:
        print(f"    - {note}")

    if written:
        print(f"\n  Artifacts written to {written[0].parent}:")
        for path in written:
            print(f"    {path.name}")
    else:
        print("\n  --dry-run: no artifacts written.")

    if mismatches:
        print(
            f"\nRESOLUTION FAILED: {mismatches} rule(s) declare a suppression "
            f"status that the computation does not reproduce.",
            file=sys.stderr,
        )


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)

    audit = run_audit(
        series_path=args.series,
        data_path=args.data,
        items_path=args.items,
        aspects_path=args.aspects,
        concordance_path=args.concordance,
        year=args.year,
    )
    registry = load_scope_rules()
    resolution = build_resolution(
        basis=audit.basis, mappings=audit.mappings, registry=registry
    )
    semantic_rows, semantic_summary = build_semantic_validation()
    provenance = build_ucc_provenance(
        audit.concordance,
        load_items(args.items),
        resolver=load_eli_resolver(load_taxonomy()),
    )

    written: list = []
    if not args.dry_run:
        written = write_artifacts(resolution, registry, args.output_dir)
        written.append(
            write_semantic_validation_csv(
                semantic_rows,
                args.output_dir / "eli_node_semantic_validation.csv",
            )
        )
        written.append(
            write_provenance_csv(
                provenance,
                args.output_dir / "ucc_provenance_classes_2024.csv",
            )
        )

    _print_report(resolution, semantic_summary, provenance, registry, written)

    checks = resolution.summary["rule_suppression_declared_vs_computed"]
    if any(not c["agrees"] for c in checks.values()):
        return 1
    if semantic_summary["review_result_counts"].get("DIVERGENT", 0):
        print(
            "\nRESOLUTION FAILED: the ELI→node mapping is semantically "
            "divergent for at least one ELI.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
