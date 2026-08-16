#!/usr/bin/env python3
"""Detailed Inflation Substrate v0.1, Milestone 1 -- 2024 CE -> CPI mapping audit.

Research-only. This command does not compute an inflation index, does not
build weights, does not acquire CPI data, and does not produce any DMI
release. Core DMI remains withdrawn and unimplemented.

The audit reads authoritative BLS Consumer Expenditure LABSTAT files from
paths supplied on the command line (they are never assumed to live in this
repository and are never committed) and writes machine-readable artifacts to a
research directory. Writing anywhere under ``data/outputs/`` or
``deploy/data/outputs/`` is refused.

Example
-------
    python scripts/audit_detailed_inflation_2024.py \
        --series   /path/to/cx.series_2024_dmi_target.tsv \
        --data     /path/to/cx.data.1.AllData \
        --items    /path/to/cx.item \
        --aspects  /path/to/cx.aspect_2024_dmi_target.tsv \
        --concordance registry/research/ucc_eli_concordance_2024_v0_1.tsv \
        --output-dir data/research/detailed_inflation/audit_2024

Attribution: source data are published by the U.S. Bureau of Labor Statistics
(Consumer Expenditure Surveys; Consumer Price Index; UCC-ELI concordance).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dmi_research.detailed_inflation.audit import (  # noqa: E402
    EXPECTED_BASELINES,
    run_audit,
    write_artifacts,
)
from dmi_research.detailed_inflation.basis import (  # noqa: E402
    BLS_AGGREGATE_ROUNDING_UNIT,
)
from dmi_research.detailed_inflation.concordance import (  # noqa: E402
    DEFAULT_CONCORDANCE_PATH,
)
from dmi_research.detailed_inflation.rse import (  # noqa: E402
    COMBINED_DOMAIN_LABEL,
    HIGH_RSE_THRESHOLD,
)
from dmi_research.detailed_inflation.sources import TARGET_YEAR  # noqa: E402

DEFAULT_OUTPUT_DIR = Path("data/research/detailed_inflation/audit_2024")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--series", type=Path, required=True, help="Path to cx.series (or a filtered extract).")
    parser.add_argument("--data", type=Path, required=True, help="Path to cx.data.1.AllData.")
    parser.add_argument("--items", type=Path, required=True, help="Path to cx.item.")
    parser.add_argument("--aspects", type=Path, required=True, help="Path to cx.aspect (or a filtered extract).")
    parser.add_argument(
        "--concordance", type=Path, default=DEFAULT_CONCORDANCE_PATH,
        help="Pinned normalized UCC->ELI concordance TSV.",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Research output directory.",
    )
    parser.add_argument("--year", type=int, default=TARGET_YEAR)
    parser.add_argument(
        "--rounding-unit", type=float, default=BLS_AGGREGATE_ROUNDING_UNIT,
        help=(
            "Unit to which BLS rounds published aggregate expenditures. The "
            "parent reconciliation passes when the residual stays within "
            "0.5 * unit * (published leaves + 1), the exact worst case of "
            "publication rounding."
        ),
    )
    parser.add_argument(
        "--rse-threshold", type=float, default=HIGH_RSE_THRESHOLD,
        help="Relative standard error at or above which a UCC is flagged HIGH_RSE.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run the audit and print the report without writing artifacts.",
    )
    return parser


def _print_report(result, written: list[Path]) -> None:
    summary = result.summary
    print("Detailed Inflation Substrate v0.1 — Milestone 1 audit")
    print(f"  year:              {summary['year']}")
    print(f"  active UCC count:  {summary['active_ucc_count']} "
          f"(expected {EXPECTED_BASELINES['active_ucc_count']}, "
          f"delta {summary['baseline_deltas']['active_ucc_count']:+d})")

    recon = summary["reconciliation"]
    verdict = "PASS" if recon["passed"] else "FAIL"
    print(f"\n  Parent reconciliation: {verdict} "
          f"({recon['checks']} checks, max |diff| "
          f"{recon['max_abs_difference']:,.0f} units / "
          f"{recon['max_abs_percent_difference']:.6f}%, "
          f"tightest rounding bound {recon['min_rounding_bound']:,.1f})")
    for failure in recon["failures"]:
        print(f"    FAIL {failure['domain']} / {failure['population']}: "
              f"{failure['absolute_difference']:+,.0f} exceeds rounding bound "
              f"{failure['rounding_bound']:,.1f} "
              f"({failure['percent_difference']:+.6f}%)")

    print("\n  Mapping status by expenditure share (All Consumer Units):")
    for key, share in summary["mapping_expenditure_share_pct"].items():
        expected = EXPECTED_BASELINES["expenditure_share_pct"][key]
        delta = summary["baseline_deltas"]["expenditure_share_pct"][key]
        print(f"    {key:22s} {share:7.2f}%   expected {expected:6.2f}%   "
              f"delta {delta:+.4f}")

    print(f"\n  MULTI_SAME_NODE cases ({len(summary['multi_same_node_cases'])}):")
    for case in summary["multi_same_node_cases"]:
        print(f"    {case['ucc']}  {case['ucc_title'][:44]:44s} -> "
              f"{case['node']}  [{', '.join(case['elis'])}]")

    cross = summary["exceptions_by_reason"]["CROSS_NODE_MULTI_MAP"]
    print(f"\n  Cross-DMI-node multi-map cases: {cross['ucc_count']}")

    no_conc = summary["exceptions_by_reason"]["NO_CONCORDANCE"]
    print(f"  No-concordance UCCs: {no_conc['ucc_count']} "
          f"({no_conc['expenditure_share_pct']:.2f}% of expenditure)")

    print(f"\n  High-RSE expenditure share (RSE >= {HIGH_RSE_THRESHOLD}), "
          f"{COMBINED_DOMAIN_LABEL}:")
    for population, share in summary["high_rse_expenditure_share_pct"].items():
        expected = EXPECTED_BASELINES["high_rse_expenditure_share_pct"].get(population)
        delta = summary["baseline_deltas"]["high_rse_expenditure_share_pct"].get(population)
        print(f"    {population:20s} {share:6.2f}%   expected {expected:5.2f}%   "
              f"delta {delta:+.4f}")

    missing = summary["missing_data"]
    print("\n  Suppressed (missing, not zero) by population:")
    for population, count in missing["missing_aggregate_by_population"].items():
        rse_count = missing["missing_rse_by_population"][population]
        print(f"    {population:20s} aggregate {count:3d}   rse {rse_count:3d}")

    if written:
        print(f"\n  Artifacts written to {written[0].parent}:")
        for path in written:
            print(f"    {path.name}")
    else:
        print("\n  --dry-run: no artifacts written.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    result = run_audit(
        series_path=args.series,
        data_path=args.data,
        items_path=args.items,
        aspects_path=args.aspects,
        concordance_path=args.concordance,
        year=args.year,
        rounding_unit=args.rounding_unit,
        rse_threshold=args.rse_threshold,
    )

    written = [] if args.dry_run else write_artifacts(result, args.output_dir)
    _print_report(result, written)

    if not result.summary["reconciliation"]["passed"]:
        print(
            "\nAUDIT FAILED: parent accounting reconciliation exceeded the "
            "tolerance. See parent_reconciliation.csv for diagnostics.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
