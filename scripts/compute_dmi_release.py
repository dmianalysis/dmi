#!/usr/bin/env python3
"""
Compute and publish a DMI release for an explicit reference period.

This wrapper exists so scheduled and manually-triggered release runs honor the
reference period chosen by the workflow, rather than silently falling back to
"latest staged data available" behavior.
"""

import argparse
import json
import sys
import pandas as pd
from datetime import datetime
from pathlib import Path

from dmi_pipeline.agents.qa_validator import generate_qa_report, print_qa_summary
from scripts.compute_dmi import (
    build_release_summary,
    compute_dmi_for_period,
    export_csv_parquet,
    generate_release_note_html,
    load_cpi_data,
    load_slack_data,
    load_weights,
    save_dmi_output,
    update_health_json,
    update_latest_json,
    update_releases_json,
    update_timeseries_json,
)

MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]


def staging_window_for_period(reference_period: str) -> tuple[int, int]:
    """Map a release period to the staged data file window that should contain it."""
    year_str, month_str = reference_period.split('-')
    year = int(year_str)
    month = int(month_str)

    if month >= 11:
        return year, year + 1
    return year - 1, year


def ensure_period_available(reference_period: str, cpi_df, slack_df) -> None:
    """Fail fast with a clear message if the requested period is not staged."""
    cpi_periods = sorted(cpi_df['period'].unique())
    slack_periods = sorted(slack_df['period'].unique())

    if reference_period not in cpi_periods:
        raise SystemExit(
            f"Requested reference period {reference_period} is not present in staged CPI data. "
            f"Latest staged CPI period: {cpi_periods[-1]}"
        )

    if reference_period not in slack_periods:
        raise SystemExit(
            f"Requested reference period {reference_period} is not present in staged slack data. "
            f"Latest staged slack period: {slack_periods[-1]}"
        )


def load_prior_release(
    reference_period: str,
    releases_path: Path = Path("data/outputs/releases.json"),
):
    """Load the most recent release strictly before the target period."""
    if not releases_path.exists():
        return None

    with open(releases_path, 'r') as f:
        existing = json.load(f)

    if isinstance(existing, dict) and 'releases' in existing:
        releases = existing.get('releases', [])
    elif isinstance(existing, list):
        releases = existing
    else:
        releases = []

    releases = [
        r for r in releases
        if r.get('release_id') and r['release_id'] < reference_period
    ]
    if not releases:
        return None

    releases.sort(key=lambda x: x['release_id'], reverse=True)
    return releases[0]


def build_metrics_payload(results: dict) -> dict:
    """Return the standardized metrics payload used across release artifacts."""
    summary = results['summary_metrics']
    return {
        'dmi_median': summary['dmi_median'],
        'dmi_stress': summary['dmi_stress'],
        'income_pressure_spread': summary['income_pressure_spread'],
        'income_pressure_tilt': summary['income_pressure_tilt'],
        'most_pressured_group': summary['most_pressured_group'],
        'least_pressured_group': summary['least_pressured_group'],
        'unemployment': results['dmi_by_group'][0]['slack'],
    }


def load_release_manifest_entry(
    reference_period: str,
    releases_path: Path = Path("data/outputs/releases.json"),
):
    """Return the published manifest entry for a period when one exists."""
    if not releases_path.exists():
        return None
    with open(releases_path, "r") as f:
        manifest = json.load(f)
    return next(
        (
            release
            for release in manifest.get("releases", [])
            if release.get("release_id") == reference_period
        ),
        None,
    )


def generate_release_note_for_period(
    reference_period: str,
    specifications: dict = None,
    output_dir: Path = Path("data/outputs"),
):
    """Render the baseline note after the three-spec manifest is available."""
    baseline_path = output_dir / f"dmi_release_{reference_period}.json"
    if not baseline_path.exists():
        raise SystemExit(f"Missing baseline release file: {baseline_path}")
    with open(baseline_path, "r") as f:
        baseline = json.load(f)

    if specifications is None:
        specifications_path = output_dir / "specifications.json"
        if not specifications_path.exists():
            raise SystemExit(
                f"Missing specifications manifest: {specifications_path}. "
                "Compute all three specifications first."
            )
        with open(specifications_path, "r") as f:
            specifications = json.load(f)

    releases_path = output_dir / "releases.json"
    release_entry = load_release_manifest_entry(reference_period, releases_path)
    if release_entry:
        summary = release_entry.get("summary", "")
        published_at = release_entry.get("published_at")
    else:
        year, month = reference_period.split("-")
        current_release = {
            "release_id": reference_period,
            "data_through_label": f"{MONTH_NAMES[int(month) - 1]} {year}",
            "metrics": build_metrics_payload(baseline),
        }
        prior_release = load_prior_release(reference_period, releases_path)
        _, summary = build_release_summary(current_release, prior_release)
        published_at = None

    release_html = generate_release_note_html(
        reference_period=reference_period,
        metrics=build_metrics_payload(baseline),
        summary=summary,
        specifications=specifications,
        published_at=published_at,
    )

    release_dir = output_dir / "releases"
    release_dir.mkdir(parents=True, exist_ok=True)
    release_path = release_dir / f"{reference_period}.html"
    release_path.write_text(release_html)
    print(f"✓ Saved release note to {release_path}")
    return release_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute and publish a DMI release for an explicit reference period."
    )
    parser.add_argument(
        'reference_period',
        help='Reference period to publish, in YYYY-MM format (for example 2026-03).',
    )
    parser.add_argument(
    "--spec",
    choices=["baseline", "slack_plus"],
    default="baseline",
    help="Which DMI specification to compute."
    )
    parser.add_argument(
        "--weights-year",
        type=int,
        default=2023,
        help='Year weights were published, in YYYY format (for example 2023).',
    )
    parser.add_argument(
        "--release-note-only",
        action="store_true",
        help="Generate the baseline release note from completed three-spec outputs.",
    )
    return parser.parse_args()

def output_suffix_for_spec(spec: str) -> str:
    return "" if spec == "baseline" else f"_{spec}"


def load_slack_for_spec(reference_period: str, spec: str, start_year: int, end_year: int) -> pd.DataFrame:
    # baseline: use staged U-3
    if spec == "baseline":
        slack_path = Path(f"data/staging/slack_u3_{start_year}_{end_year}.json")
        if not slack_path.exists():
            raise SystemExit(f"Missing staged U-3 slack file: {slack_path}")
        return load_slack_data(slack_path)

    # slack_plus: use staged U-6 if current enough; otherwise fetch and cache
    slack_u6_path = Path(f"data/staging/slack_u6_{start_year}_{end_year}.json")

    if slack_u6_path.exists():
        slack_df = load_slack_data(slack_u6_path)

        # Refresh if the requested period is missing
        available_periods = set(slack_df["period"].astype(str))
        if reference_period in available_periods:
            return slack_df

        print(
            f"Requested reference period {reference_period} is not present in staged slack data. "
            f"Latest staged slack period: {max(available_periods)}. Refreshing U-6 data..."
        )

    from dmi_pipeline.agents.bls_api_client import fetch_slack_data, convert_to_monthly_format

    catalog_path = Path("registry/series_catalog_v0_1.json")
    with open(catalog_path) as f:
        catalog = json.load(f)

    u6_series = [s for s in catalog["slack"]["national_series"] if s["metric"] == "U6"][0]
    slack_df = fetch_slack_data(u6_series["series_id"], start_year, end_year)
    slack_df = convert_to_monthly_format(slack_df)
    slack_df = slack_df[["period_yyyymm", "value"]].rename(columns={"period_yyyymm": "period"})

    # cache for reproducibility
    slack_u6_path.parent.mkdir(parents=True, exist_ok=True)
    with open(slack_u6_path, "w") as f:
        json.dump(slack_df.to_dict(orient="records"), f, indent=2)

    return slack_df


def spec_description(spec: str) -> str:
    return {
        "baseline": "Headline DMI using current inflation inputs and U-3 unemployment.",
        "slack_plus": "Companion DMI using broader labor-market slack.",
    }[spec]


def main() -> int:
    args = parse_args()
    reference_period = args.reference_period

    if args.release_note_only:
        print(f"Generating deferred release note for {reference_period}...")
        generate_release_note_for_period(reference_period)
        return 0

    spec = args.spec
    weights_year = args.weights_year
    suffix = output_suffix_for_spec(spec)

    print("=" * 80)
    print("DMI Release Runner")
    print("=" * 80)
    print(f"Requested reference period: {reference_period}")
    print(f"Requested weights year: {weights_year}")
    
    start_year, end_year = staging_window_for_period(reference_period)

    weights_path = Path(f"data/curated/weights_by_group_{weights_year}.json")

    if not weights_path.exists():
        raise SystemExit(f"Missing weights file for requested weights_year={weights_year}: {weights_path}")
    
    cpi_path = Path(f"data/staging/cpi_levels_{start_year}_{end_year}.json")
    
    if spec == "slack_plus": 
        slack_measure = "u6"
    else:
        slack_measure = "u3" 
    
    slack_path = Path(f"data/staging/slack_{slack_measure}_{start_year}_{end_year}.json")

    if not cpi_path.exists():
        raise SystemExit(f"Missing staged CPI file for {reference_period}: {cpi_path}")

    print("\nLoading data...")
    weights_df = load_weights(weights_path)
    print(f"  ✓ Weights: {len(weights_df)} records")

    cpi_df = load_cpi_data(cpi_path)
    print(f"  ✓ CPI data: {len(cpi_df)} periods from {cpi_path.name}")

    # Load slack according to spec (U-3 for baseline, U-6 for slack_plus).
    slack_df = load_slack_for_spec(reference_period, spec, start_year, end_year)
    print(f"  ✓ Slack data: {len(slack_df)} periods from {slack_path.name}")

    ensure_period_available(reference_period, cpi_df, slack_df)

    print("\n" + "=" * 80)
    print(f"Computing release for explicit period {reference_period}")
    print(f"Spec is {spec}")
    results = compute_dmi_for_period(
        cpi_df=cpi_df,
        weights_df=weights_df,
        slack_df=slack_df,
        reference_period=reference_period,
        alpha=0.5,
        scale_factor=2.0,
        spec=spec
    )

    # Add spec metadata
    results["specification"] = spec
    results["description"] = spec_description(spec)
    results["parameters"]["spec_id"] = spec
    results["parameters"]["slack_measure"] = slack_measure  # slack_measure is set earlier based on the spec type
    results["parameters"]["inflation_measure"] = "HEADLINE_CPI"


    # NEW: write outputs with suffix so specs don't overwrite each other
    suffix = output_suffix_for_spec(spec)
    output_path = Path(f"data/outputs/dmi_release_{reference_period}{suffix}.json")
    save_dmi_output(results, output_path)

    print("\n" + "=" * 80)
    print("Generating QA Report...")
    print("=" * 80)
    qa_report = generate_qa_report(
        dmi_output=results,
        cpi_data=cpi_df,
        weights_data=weights_df,
        slack_data=slack_df,
        output_path=Path(f"data/outputs/qa_report_{reference_period}_{spec}.json"),
    )
    print_qa_summary(qa_report)

    print("\n" + "=" * 80)
    print("Creating CSV and Parquet files...")
    print("=" * 80)
    export_csv_parquet(results, reference_period, spec)

    # Baseline owns manifests + health + timeseries. The release note is
    # generated separately after all three specs and specifications.json land.
    if spec == "baseline":
        year, month = reference_period.split('-')
        current_release = {
            'release_id': reference_period,
            'data_through_label': f"{MONTH_NAMES[int(month) - 1]} {year}",
            'metrics': build_metrics_payload(results),
        }
        prior_release = load_prior_release(reference_period)
        summary_facts, summary = build_release_summary(current_release, prior_release)
    
        print("\n" + "=" * 80)
        print("Updating release manifests...")
        print("=" * 80)
        metrics_payload = build_metrics_payload(results)
        update_releases_json(
            reference_period=reference_period,
            metrics=metrics_payload,
            summary=summary,
            summary_facts=summary_facts,
        )
        update_latest_json(
            reference_period=reference_period,
            metrics=metrics_payload,
            summary=summary,
            summary_facts=summary_facts,
        )
        update_health_json(reference_period)
        update_timeseries_json(reference_period)
    else:
        print(f"Saved companion specification: {spec} -> {output_path}")
        
    print("\n" + "=" * 80)
    print("DMI RELEASE SUMMARY")
    print("=" * 80)
    print(f"Period: {reference_period}")
    print(f"Computed at: {datetime.utcnow().isoformat()}Z")
    for record in results['dmi_by_group']:
        print(
            f"  {record['group_id']}: DMI={record['dmi']:6.2f}  "
            f"(inflation={record['inflation']:5.2f}%, slack={record['slack']:4.1f}%)"
        )
    print(f"  Median DMI: {results['summary_metrics']['dmi_median']:.2f}")
    print(f"  Stress: {results['summary_metrics']['dmi_stress']:.2f}")
    print(
        f"  Income Pressure Spread (max-min): "
        f"{results['summary_metrics']['income_pressure_spread']:.2f}"
    )
    print(
        f"  Income Pressure Tilt (Q1-Q5): "
        f"{results['summary_metrics']['income_pressure_tilt']:+.2f}"
    )
    print(f"  Most pressured group: {results['summary_metrics']['most_pressured_group']}")
    print(f"  Least pressured group: {results['summary_metrics']['least_pressured_group']}")

    print("\n✓ Explicit-period DMI release run completed successfully!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
