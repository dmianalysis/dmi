#!/usr/bin/env python3
"""
Fetch and stage BLS CPI and U-3 data for one DMI reference period.

    python -m scripts.test_bls_api --reference-period YYYY-MM

The staging files are chosen from the reference period by
``scripts.reference_period``, the same code ``scripts.compute_dmi_release``
uses to read them. The execution date plays no part, so a rerun of any
period reads and writes the same files whenever it happens.

Nothing is written unless the fetched data can support the requested
release:

- every CPI category has an observation in the reference month and in the
  same month one year earlier, the base of 12-month inflation;
- U-3 has an observation in the reference month.

Missing official observations are reported and the script exits non-zero.
They are never estimated, interpolated or carried forward.

U-6, used by Slack-Plus, is fetched by ``scripts.compute_dmi_release
--spec slack_plus`` into the same staging window.

(The ``test_`` prefix is historical; this is the live acquisition step of
the monthly workflow, not a test module, and defines no test functions.)
"""

import argparse
import json
import sys
from pathlib import Path

from dmi_pipeline.agents.bls_api_client import (
    fetch_cpi_data,
    fetch_slack_data,
    convert_to_monthly_format,
    pivot_cpi_to_categories,
    save_cpi_data,
    validate_category_coverage,
)
from scripts.reference_period import (
    STAGING_DIR,
    parse_reference_period,
    staging_paths,
    staging_window_for_period,
    year_over_year_base,
)

CATALOG_PATH = Path("registry/series_catalog_v0_1.json")


class AcquisitionError(Exception):
    """Fetched data cannot support the requested reference period."""


def _reference_period_arg(value: str) -> str:
    try:
        parse_reference_period(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return value


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and stage BLS CPI and U-3 data for one DMI reference period."
    )
    parser.add_argument(
        "--reference-period",
        required=True,
        type=_reference_period_arg,
        help="DMI reference period in YYYY-MM format, for example 2026-11.",
    )
    return parser.parse_args(argv)


def fetch_window(reference_period: str) -> tuple[int, int]:
    """BLS years to request: the staging window plus one lookback year.

    The lookback year always contains the year-over-year base month.
    """
    start_year, end_year = staging_window_for_period(reference_period)
    return start_year - 1, end_year


def validate_acquisition(reference_period, cpi_wide, slack, required_categories) -> list[str]:
    """Every problem that prevents computing the reference period."""
    problems = []
    coverage = validate_category_coverage(
        cpi_df=cpi_wide,
        required_categories=required_categories,
        reference_period=reference_period,
        lookback_months=12,
    )
    for period in coverage["missing_periods"]:
        role = "reference month" if period == reference_period else "12-month CPI base month"
        problems.append(f"CPI has no observations for {period} ({role}).")
    for category in coverage["missing_categories"]:
        problems.append(f"CPI observation missing: {category}.")
    if reference_period not in set(slack["period"].astype(str)):
        problems.append(f"U-3 has no observation for {reference_period} (reference month).")
    return problems


def acquire(reference_period: str, staging_dir: Path = STAGING_DIR,
            catalog_path: Path = CATALOG_PATH) -> dict[str, Path]:
    """Fetch, validate and stage. Raises AcquisitionError before any write."""
    parse_reference_period(reference_period)
    base_period = year_over_year_base(reference_period)
    paths = staging_paths(reference_period, staging_dir)
    fetch_start, fetch_end = fetch_window(reference_period)

    print("=" * 70)
    print(f"BLS acquisition for reference period {reference_period}")
    print("=" * 70)
    print(f"  12-month CPI base month: {base_period}")
    print(f"  BLS years requested:     {fetch_start}-{fetch_end}")
    print(f"  CPI staging file:        {paths['cpi']}")
    print(f"  U-3 staging file:        {paths['u3']}")

    with open(catalog_path) as f:
        catalog = json.load(f)

    cpi_categories = [
        cat for cat in catalog["cpi"]["series_sets"][0]["categories"]
        if cat["category_id"] != "CPI_ALL_ITEMS"
    ]
    cpi_series_ids = [cat["series_id"] for cat in cpi_categories]
    required_categories = [cat["category_id"] for cat in cpi_categories]

    print(f"\n[1/3] Fetching CPI data for {len(cpi_series_ids)} major groups...")
    cpi_df = convert_to_monthly_format(
        fetch_cpi_data(series_ids=cpi_series_ids, start_year=fetch_start, end_year=fetch_end)
    )
    cpi_wide = pivot_cpi_to_categories(cpi_df, catalog)
    print(f"  Periods: {cpi_wide['period'].min()} to {cpi_wide['period'].max()}")

    print("\n[2/3] Fetching U-3 unemployment (slack) data...")
    u3_series_id = next(
        s["series_id"] for s in catalog["slack"]["national_series"] if s["metric"] == "U3"
    )
    slack_df = convert_to_monthly_format(
        fetch_slack_data(series_id=u3_series_id, start_year=fetch_start, end_year=fetch_end)
    )
    slack = slack_df[["period_yyyymm", "value"]].rename(columns={"period_yyyymm": "period"})
    print(f"  U-3 observations: {len(slack)}")

    print("\n[3/3] Validating required observations...")
    problems = validate_acquisition(reference_period, cpi_wide, slack, required_categories)
    if problems:
        raise AcquisitionError(
            f"BLS data cannot support DMI reference period {reference_period}; "
            "nothing was staged.\n  - " + "\n  - ".join(problems)
            + "\nMissing official observations are not estimated. "
            "See docs/deployment-workflows.md, troubleshooting."
        )
    print(f"  ✓ All {len(required_categories)} CPI categories present for "
          f"{reference_period} and {base_period}")
    print(f"  ✓ U-3 present for {reference_period}")

    print("\nSaving data...")
    save_cpi_data(
        cpi_wide,
        paths["cpi"],
        metadata={"dataset": "BLS CPI-U", "series_count": len(cpi_series_ids)},
    )
    paths["u3"].parent.mkdir(parents=True, exist_ok=True)
    slack.to_json(paths["u3"], orient="records", indent=2)
    print(f"Saved slack data to {paths['u3']}")
    return {"cpi": paths["cpi"], "u3": paths["u3"]}


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        acquire(args.reference_period)
    except AcquisitionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    print("\n✓ BLS acquisition completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
