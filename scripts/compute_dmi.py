#!/usr/bin/env python3
"""
Full DMI Integration - Compute DMI using real data.

Combines:
- Phase 1: Calculator core
- Phase 2: CE weights (2023, or specified year)
- Phase 3: CPI + slack data (BLS API)
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd

from dmi_calculator.core import (
    compute_group_weighted_inflation,
    compute_slack,
    compute_dmi,
    compute_summary_metrics,
    validate_contributions_sum_to_total
)
from dmi_pipeline.agents.qa_validator import generate_qa_report, print_qa_summary


# Methodology version (also written to web/health.json without the leading 'v')
METHODOLOGY_VERSION = "v0.1.12"


# Threshold constants for summary generation
THRESHOLDS = {
    'little_changed': 0.05,
    'edged': 0.15,
    'modestly': 0.30,
    'spread_little_changed': 0.015,
    'spread_slightly': 0.08,
    'tilt_similar': 0.02,
    'unemployment_little_changed': 0.1,
    'unemployment_noticeably': 0.3,
}


def classify_direction(delta: float, thresholds: dict) -> str:
    """Classify direction based on delta and thresholds."""
    abs_delta = abs(delta)
    if abs_delta < thresholds['little_changed']:
        return 'little_changed'
    elif abs_delta < thresholds['edged']:
        return 'edged_up' if delta > 0 else 'edged_down'
    elif abs_delta < thresholds['modestly']:
        return 'rose_modestly' if delta > 0 else 'fell_modestly'
    else:
        return 'rose_sharply' if delta > 0 else 'fell_sharply'


def classify_spread_direction(spread_delta: float) -> str:
    """Classify how the Income Pressure Spread (max-min) is changing.

    Since the spread is non-negative, a negative delta means the
    bottom-to-top distribution narrowed; a positive delta means it widened.
    """
    abs_delta = abs(spread_delta)
    if abs_delta < THRESHOLDS['spread_little_changed']:
        return 'spread_little_changed'
    elif abs_delta < THRESHOLDS['spread_slightly']:
        return 'spread_narrowed_slightly' if spread_delta < 0 else 'spread_widened_slightly'
    else:
        return 'spread_narrowed_materially' if spread_delta < 0 else 'spread_widened_materially'


def classify_unemployment_direction(unemp_delta: float) -> str:
    """Classify unemployment direction."""
    abs_delta = abs(unemp_delta)
    if abs_delta < THRESHOLDS['unemployment_little_changed']:
        return 'unemployment_little_changed'
    elif abs_delta < THRESHOLDS['unemployment_noticeably']:
        return 'unemployment_edged_up' if unemp_delta > 0 else 'unemployment_edged_down'
    else:
        return 'unemployment_rose_noticeably' if unemp_delta > 0 else 'unemployment_fell_noticeably'


def build_release_summary(
    current_release: dict,
    prior_release: Optional[dict] = None,
    contributor_context: Optional[dict] = None,
) -> tuple[dict, str]:
    """
    Generate deterministic plain-English summary for a DMI release.

    Returns (summary_facts, summary_text)
    """
    metrics = current_release['metrics']
    dmi_median = metrics['dmi_median']
    dmi_stress = metrics['dmi_stress']
    spread = metrics['income_pressure_spread']
    tilt = metrics['income_pressure_tilt']
    most_pressured_group = metrics['most_pressured_group']
    least_pressured_group = metrics['least_pressured_group']
    unemployment = metrics['unemployment']

    tilt_similar = THRESHOLDS['tilt_similar']
    summary_facts = {
        'lower_income_more_pressure': tilt > tilt_similar,
        'higher_income_more_pressure': tilt < -tilt_similar,
        'pressure_similar_across_bottom_top': abs(tilt) <= tilt_similar,
        'most_pressured_group': most_pressured_group,
        'least_pressured_group': least_pressured_group,
    }

    data_through_label = current_release['data_through_label']

    # Compute deltas if prior exists
    if prior_release:
        prior_metrics = prior_release['metrics']
        median_delta_mom = dmi_median - prior_metrics['dmi_median']
        stress_delta_mom = dmi_stress - prior_metrics['dmi_stress']
        spread_delta_mom = spread - prior_metrics['income_pressure_spread']
        tilt_delta_mom = tilt - prior_metrics['income_pressure_tilt']
        unemployment_delta_mom = unemployment - prior_metrics['unemployment']

        summary_facts.update({
            'median_delta_mom': median_delta_mom,
            'stress_delta_mom': stress_delta_mom,
            'spread_delta_mom': spread_delta_mom,
            'tilt_delta_mom': tilt_delta_mom,
            'unemployment_delta_mom': unemployment_delta_mom,
            'overall_direction': classify_direction(median_delta_mom, THRESHOLDS),
            'spread_direction': classify_spread_direction(spread_delta_mom),
        })

        # Build summary with prior
        sentences = []

        # Sentence 1: overall movement
        direction = summary_facts['overall_direction']
        if direction == 'little_changed':
            sentences.append(f"Economic pressure was little changed in {data_through_label}.")
        elif direction == 'edged_up':
            sentences.append(f"Economic pressure edged up in {data_through_label}.")
        elif direction == 'edged_down':
            sentences.append(f"Economic pressure edged down in {data_through_label}.")
        elif direction == 'rose_modestly':
            sentences.append(f"Economic pressure rose modestly in {data_through_label}.")
        elif direction == 'fell_modestly':
            sentences.append(f"Economic pressure fell modestly in {data_through_label}.")
        elif direction == 'rose_sharply':
            sentences.append(f"Economic pressure rose sharply in {data_through_label}.")
        elif direction == 'fell_sharply':
            sentences.append(f"Economic pressure fell sharply in {data_through_label}.")

        # Sentence 2: distributional pattern
        spread_direction = summary_facts['spread_direction']
        if summary_facts['lower_income_more_pressure']:
            base = "Lower-income households continued to face more pressure than higher-income households"
        elif summary_facts['higher_income_more_pressure']:
            base = "Higher-income households faced more pressure than lower-income households"
        else:
            base = "Pressure was felt more similarly across the bottom and top income fifths"

        if spread_direction == 'spread_little_changed':
            sentences.append(f"{base}.")
        elif spread_direction == 'spread_narrowed_slightly':
            sentences.append(f"{base}, and the Income Pressure Spread narrowed slightly from the prior month.")
        elif spread_direction == 'spread_widened_slightly':
            sentences.append(f"{base}, and the Income Pressure Spread widened slightly from the prior month.")
        elif spread_direction == 'spread_narrowed_materially':
            sentences.append(f"{base}, and the Income Pressure Spread narrowed materially from the prior month.")
        elif spread_direction == 'spread_widened_materially':
            sentences.append(f"{base}, and the Income Pressure Spread widened materially from the prior month.")

        # Sentence 3: optional detail
        if contributor_context and 'top_contributors_q1' in contributor_context:
            contributors = contributor_context['top_contributors_q1']
            if len(contributors) == 1:
                sentences.append(f"{contributors[0].title()} remained the largest contributor for the bottom income fifth.")
            elif len(contributors) == 2:
                sentences.append(f"The main contributors for the bottom income fifth were {contributors[0].lower()} and {contributors[1].lower()}.")
            elif len(contributors) >= 3:
                contrib_str = ', '.join(c.lower() for c in contributors[:-1]) + f", and {contributors[-1].lower()}"
                sentences.append(f"For the bottom income fifth, the main contributors remained {contrib_str}.")
        else:
            unemp_direction = classify_unemployment_direction(unemployment_delta_mom)
            if unemp_direction != 'unemployment_little_changed':
                if unemp_direction == 'unemployment_edged_up':
                    sentences.append(f"The labor-market backdrop also softened slightly, with unemployment edging up to {unemployment}%.")
                elif unemp_direction == 'unemployment_edged_down':
                    sentences.append(f"The labor-market backdrop improved slightly, with unemployment edging down to {unemployment}%.")
                elif unemp_direction == 'unemployment_rose_noticeably':
                    sentences.append(f"The labor-market backdrop softened noticeably, with unemployment rising to {unemployment}%.")
                elif unemp_direction == 'unemployment_fell_noticeably':
                    sentences.append(f"The labor-market backdrop improved noticeably, with unemployment falling to {unemployment}%.")

        summary = ' '.join(sentences)
    else:
        # Fallback: no prior release
        summary_facts.update({
            'overall_direction': 'no_prior',
        })
        if summary_facts['lower_income_more_pressure']:
            who = "higher measured pressure for lower-income households than for higher-income households"
        elif summary_facts['higher_income_more_pressure']:
            who = "higher measured pressure for higher-income households than for lower-income households"
        else:
            who = "similar measured pressure across lower- and higher-income households"
        summary = (
            f"The {data_through_label} release shows {who}. "
            f"The current dashboard reports a DMI Median of {dmi_median:.2f}, "
            f"a DMI Stress reading of {dmi_stress:.2f}, "
            f"and an Income Pressure Spread of {spread:.2f}."
        )

    return summary_facts, summary


def load_weights(weights_path: Path) -> pd.DataFrame:
    """Load CE weights from JSON."""
    with open(weights_path) as f:
        data = json.load(f)
    
    df = pd.DataFrame(data['rows'])
    return df


def load_cpi_data(cpi_path: Path) -> pd.DataFrame:
    """Load CPI levels from JSON."""
    with open(cpi_path) as f:
        data = json.load(f)
    
    df = pd.DataFrame(data['data'])
    return df


def load_slack_data(slack_path: Path) -> pd.DataFrame:
    """Load unemployment data from JSON."""
    with open(slack_path) as f:
        data = json.load(f)
    
    df = pd.DataFrame(data)
    return df


def compute_dmi_for_period(
    cpi_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    slack_df: pd.DataFrame,
    reference_period: str,
    alpha: float = 0.5,
    scale_factor: float = 2.0,
    weights_year: int = 2023,
    spec: str="baseline"
) -> dict:
    """
    Compute DMI for a reference period using real data.
    
    Args:
        cpi_df: CPI data with columns [period, CPI_FOOD_BEVERAGES, ...]
        weights_df: Weights with columns [group_id, category_id, weight]
        slack_df: Slack data with columns [period, value]
        reference_period: Period to compute DMI for (YYYY-MM)
        alpha: Inflation vs slack weight (default: 0.5)
        scale_factor: DMI scaling factor (default: 2.0)
        weights_year: year weights were computed (default: 2023)
        spec: specification (baseline, slack-plus or core)
    
    Returns:
        Dictionary with DMI results
    """
    print(f"Computing DMI for {reference_period}...")
    
    # Step 1: Compute group-weighted inflation
    print(f"  [1/4] Computing inflation by quintile...")
    inflation_df, contributions_df = compute_group_weighted_inflation(
        cpi_levels=cpi_df,
        weights=weights_df,
        reference_period=reference_period,
        horizon_months=12
    )
    
    print(f"    ✓ Computed inflation for {len(inflation_df)} quintiles")
    for _, row in inflation_df.iterrows():
        print(f"      {row['group_id']}: {row['inflation']:.2f}%")
    
    # Validate contributions
    validate_contributions_sum_to_total(contributions_df, inflation_df)
    print(f"    ✓ Contributions validated (sum to total)")
    
    # Step 2: Extract slack
    print(f"  [2/4] Extracting unemployment rate...")

    if spec=="slack_plus":
        slack_measure = "u6"
        slack_measure_display = "U-6"
    else:
        slack_measure = "u3"
        slack_measure_display = "U-3"
    
    slack = compute_slack(
        slack_data=slack_df,
        reference_period=reference_period
    )
    print(f"    ✓ Unemployment ({slack_measure_display}): {slack:.1f}%")
    
    # Step 3: Compute DMI
    print(f"  [3/4] Computing DMI (α={alpha}, scale={scale_factor})...")
    dmi_df = compute_dmi(
        inflation_by_group=inflation_df,
        slack=slack,
        alpha=alpha,
        scale_factor=scale_factor
    )
    
    print(f"    ✓ DMI computed for {len(dmi_df)} quintiles")
    for _, row in dmi_df.iterrows():
        print(f"      {row['group_id']}: DMI={row['dmi']:.2f}")
    
    # Step 4: Summary metrics
    print(f"  [4/4] Computing summary metrics...")
    metrics = compute_summary_metrics(dmi_df)
    
    print(f"    ✓ Summary metrics:")
    print(f"      Median DMI: {metrics['dmi_median']:.2f}")
    print(f"      Stress (max): {metrics['dmi_stress']:.2f}")
    print(f"      Income Pressure Spread (max-min): {metrics['income_pressure_spread']:.2f}")
    if 'income_pressure_tilt' in metrics:
        print(f"      Income Pressure Tilt (Q1-Q5): {metrics['income_pressure_tilt']:.2f}")
    print(f"      Most pressured group: {metrics['most_pressured_group']}")
    print(f"      Least pressured group: {metrics['least_pressured_group']}")
    
    # Compile results
    results = {
        "reference_period": reference_period,
        "parameters": {
            "alpha": alpha,
            "scale_factor": scale_factor,
            "weights_year": weights_year
        },
        "dmi_by_group": dmi_df.to_dict(orient='records'),
        "summary_metrics": metrics,
        "inflation_contributions": contributions_df.to_dict(orient='records'),
        "metadata": {
            "computed_at": datetime.utcnow().isoformat() + "Z",
            "num_groups": len(dmi_df),
            "num_categories": len(contributions_df['category_id'].unique())
        }
    }
    
    return results


def save_dmi_output(results: dict, output_path: Path):
    """Save DMI results to JSON."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✓ Saved DMI output to {output_path}")


def export_csv_parquet(results: dict, reference_period: str, spec: str):
    """Export DMI results to CSV and Parquet files."""
    dmi_df = pd.DataFrame(results['dmi_by_group'])
    
    # CSV export
    csv_path = Path(f"data/outputs/dmi-{reference_period}-{spec}.csv")
    dmi_df.to_csv(csv_path, index=False)
    print(f"✓ Saved CSV to {csv_path}")
    
    # Parquet export
    parquet_path = Path(f"data/outputs/dmi-{reference_period}-{spec}.parquet")
    dmi_df.to_parquet(parquet_path, index=False)
    print(f"✓ Saved Parquet to {parquet_path}")
    
    return csv_path, parquet_path


def generate_release_note_html(
    reference_period: str,
    metrics: dict,
    summary: str = "",
    spec: str="baseline",
    slack_measure: str="U-3",
    specifications: Optional[dict] = None,
    published_at: Optional[str] = None,
) -> str:
    """Generate HTML release note for the current release.

    ``specifications`` is supplied only after all three published
    specifications have been computed.  Keeping it optional preserves the
    legacy single-spec command while allowing the monthly release workflow to
    defer the public note until the robustness assessment is complete.
    """
    # Parse reference period to human-readable format
    year, month = reference_period.split('-')
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    month_name = months[int(month) - 1]
    data_through = f"{month_name} {year}"

    robustness_html = ""
    if specifications is not None:
        manifest_period = specifications.get("reference_period")
        if manifest_period != reference_period:
            raise ValueError(
                "Specifications manifest period "
                f"{manifest_period!r} does not match release note period {reference_period!r}."
            )

        specs_by_id = {
            item["spec_id"]: item
            for item in specifications["specifications"]
        }
        spec_labels = {
            "baseline": "Baseline (U-3, headline CPI)",
            "slack_plus": "Slack+ (U-6, headline CPI)",
            "core": "Core (U-3, core CPI)",
        }
        rows = []
        for spec_id in ("baseline", "slack_plus", "core"):
            spec_metrics = specs_by_id[spec_id]["metrics"]
            measure = str(spec_metrics["slack_measure"]).upper()
            measure = {"U3": "U-3", "U6": "U-6"}.get(measure, measure)
            rows.append(
                """
                <tr>
                    <th scope="row">{label}</th>
                    <td>{median:.2f}</td>
                    <td>{stress:.2f}</td>
                    <td>{slack:.1f}% ({measure})</td>
                </tr>""".format(
                    label=spec_labels[spec_id],
                    median=spec_metrics["dmi_median"],
                    stress=spec_metrics["dmi_stress"],
                    slack=spec_metrics["slack"],
                    measure=measure,
                )
            )

        assessment = specifications["robustness_assessment"]
        flags_consistent = (
            assessment["pressure_tilt_sign_consistent"]
            and assessment["stress_group_consistent"]
        )
        warning_html = ""
        if not flags_consistent:
            warning_html = """    <p class="robustness-warning" role="alert">
        <strong>Warning:</strong> The distributional pattern or highest-pressure
        income group is not consistent across all three specifications.
    </p>
"""

        robustness_html = f"""    <h2>Robustness across specifications</h2>
{warning_html}
    <div class="table-wrap">
        <table>
            <thead>
                <tr>
                    <th scope="col">Specification</th>
                    <th scope="col">DMI Median</th>
                    <th scope="col">DMI Stress</th>
                    <th scope="col">Slack</th>
                </tr>
            </thead>
            <tbody>{''.join(rows)}
            </tbody>
        </table>
    </div>"""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DMI Release {reference_period}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem;
            color: #333;
        }}
        h1 {{
            color: #667eea;
            border-bottom: 2px solid #667eea;
            padding-bottom: 0.5rem;
        }}
        .metrics {{
            background: #f5f7fa;
            border-left: 4px solid #667eea;
            padding: 1rem;
            margin: 1.5rem 0;
        }}
        .metric-row {{
            display: flex;
            justify-content: space-between;
            padding: 0.5rem 0;
        }}
        .metric-label {{
            font-weight: 600;
        }}
        .metric-value {{
            color: #667eea;
            font-weight: 700;
        }}
        .summary {{
            background: #f9f9f9;
            padding: 1rem;
            border-radius: 4px;
            margin: 1.5rem 0;
        }}
        .table-wrap {{
            overflow-x: auto;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 1rem 0;
        }}
        th, td {{
            border: 1px solid #d7dce2;
            padding: 0.65rem;
            text-align: right;
        }}
        thead th, tbody th {{
            background: #f5f7fa;
            text-align: left;
        }}
        .robustness-warning {{
            background: #fff4e5;
            border-left: 4px solid #c05621;
            padding: 0.75rem 1rem;
        }}
    </style>
</head>
<body>
    <h1>DMI Release: {reference_period}-{spec}</h1>
    <p><strong>Data Through:</strong> {data_through}</p>
    <p><strong>Published:</strong> {published_at or datetime.now().strftime('%Y-%m-%d')}</p>

    <h2>Key Metrics</h2>
    <div class="metrics">
        <div class="metric-row">
            <span class="metric-label">DMI Median:</span>
            <span class="metric-value">{metrics['dmi_median']:.2f}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">DMI Stress:</span>
            <span class="metric-value">{metrics['dmi_stress']:.2f}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Income Pressure Spread (max&minus;min):</span>
            <span class="metric-value">{metrics['income_pressure_spread']:.2f}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Income Pressure Tilt (Q1&minus;Q5):</span>
            <span class="metric-value">{metrics['income_pressure_tilt']:+.2f}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Most pressured group:</span>
            <span class="metric-value">{metrics['most_pressured_group']}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Least pressured group:</span>
            <span class="metric-value">{metrics['least_pressured_group']}</span>
        </div>
        <div class="metric-row">
            <span class="metric-label">Unemployment ({slack_measure}):</span>
            <span class="metric-value">{metrics['unemployment']:.1f}%</span>
        </div>
    </div>

    <h2>Summary</h2>
    <div class="summary">
        <p>{summary if summary else 'Full release data available in the accompanying CSV and Parquet files.'}</p>
    </div>
{robustness_html}
</body>
</html>"""
    
    return html


def save_release_note(html_content: str, reference_period: str):
    """Save release note HTML file."""
    release_dir = Path("data/outputs/releases")
    release_dir.mkdir(parents=True, exist_ok=True)
    
    release_path = release_dir / f"{reference_period}.html"
    with open(release_path, 'w') as f:
        f.write(html_content)
    
    print(f"✓ Saved release note to {release_path}")
    return release_path


def update_releases_json(
    reference_period: str,
    metrics: dict,
    summary: str,
    summary_facts: dict,
    methodology_version: str = METHODOLOGY_VERSION,
    dashboard_url: str = None,
    repo_url: str = None,
    notes: list = None
):
    """Update releases.json with the new release metadata conforming to schema."""
    releases_path = Path("data/outputs/releases.json")

    # Load existing releases (always a manifest object under the current schema)
    releases = []
    if releases_path.exists():
        with open(releases_path, 'r') as f:
            existing = json.load(f)
        for release in existing.get('releases', []):
            if release.get('release_id') != reference_period:
                releases.append(release)

    # Convert reference period to data_through_label format
    year, month = reference_period.split('-')
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    month_name = months[int(month) - 1]
    data_through_label = f"{month_name} {year}"

    # Only baseline gets a release_note link. The released note is
    # spec-agnostic (driven by the robust distributional pattern), so
    # advertising it on slack_plus/core was misleading; the WP plugin
    # gracefully skips the link when the field is absent.
    spec_urls = {
        "baseline": {
            "csv": f"/data/outputs/dmi-{reference_period}-baseline.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-baseline.parquet",
            "release_note": f"/data/outputs/releases/{reference_period}.html",
        },
        "slack_plus": {
            "csv": f"/data/outputs/dmi-{reference_period}-slack_plus.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-slack_plus.parquet",
        },
        "core": {
            "csv": f"/data/outputs/dmi-{reference_period}-core.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-core.parquet",
        },
    }

    if dashboard_url:
        for spec_key in spec_urls:
            spec_urls[spec_key]["dashboard"] = dashboard_url

    if repo_url:
        for spec_key in spec_urls:
            spec_urls[spec_key]["repo"] = repo_url

    new_release = {
        "release_id": reference_period,
        "data_through_label": data_through_label,
        "published_at": datetime.now().strftime('%Y-%m-%d'),
        "status": "current",
        "methodology_version": methodology_version,
        "summary": summary,
        "summary_facts": summary_facts,
        "spec_urls": spec_urls,
        "metrics": {
            "dmi_median": metrics['dmi_median'],
            "dmi_stress": metrics['dmi_stress'],
            "income_pressure_spread": metrics['income_pressure_spread'],
            "income_pressure_tilt": metrics['income_pressure_tilt'],
            "most_pressured_group": metrics['most_pressured_group'],
            "least_pressured_group": metrics['least_pressured_group'],
            "unemployment": metrics['unemployment'],
        },
    }
    if notes:
        new_release["notes"] = notes

    # Mark any other current releases as superseded
    for release in releases:
        if release.get('status') == 'current':
            release['status'] = 'superseded'

    # Add new release at top
    releases.insert(0, new_release)

    releases_manifest = {
        "schema_version": "2.0.0",
        "generated_at": datetime.now().isoformat() + "Z",
        "current_release_id": reference_period,
        "releases": releases
    }

    with open(releases_path, 'w') as f:
        json.dump(releases_manifest, f, indent=2)

    print(f"✓ Updated releases.json with new release {reference_period}")
    return releases_path


def update_latest_json(
    reference_period: str,
    metrics: dict,
    summary: str,
    summary_facts: dict,
    methodology_version: str = METHODOLOGY_VERSION,
    dashboard_url: str = None,
    repo_url: str = None,
    notes: list = None
):
    """Update latest.json with the most recent release metadata conforming to schema."""
    latest_path = Path("data/outputs/latest.json")

    # Convert reference period to data_through_label format
    year, month = reference_period.split('-')
    months = ['January', 'February', 'March', 'April', 'May', 'June',
              'July', 'August', 'September', 'October', 'November', 'December']
    month_name = months[int(month) - 1]
    data_through_label = f"{month_name} {year}"

    # Only baseline gets a release_note link. The released note is
    # spec-agnostic (driven by the robust distributional pattern), so
    # advertising it on slack_plus/core was misleading; the WP plugin
    # gracefully skips the link when the field is absent.
    spec_urls = {
        "baseline": {
            "csv": f"/data/outputs/dmi-{reference_period}-baseline.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-baseline.parquet",
            "release_note": f"/data/outputs/releases/{reference_period}.html",
        },
        "slack_plus": {
            "csv": f"/data/outputs/dmi-{reference_period}-slack_plus.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-slack_plus.parquet",
        },
        "core": {
            "csv": f"/data/outputs/dmi-{reference_period}-core.csv",
            "parquet": f"/data/outputs/dmi-{reference_period}-core.parquet",
        },
    }

    if dashboard_url:
        for spec_key in spec_urls:
            spec_urls[spec_key]["dashboard"] = dashboard_url
    if repo_url:
        for spec_key in spec_urls:
            spec_urls[spec_key]["repo"] = repo_url

    latest_release = {
        "release_id": reference_period,
        "data_through_label": data_through_label,
        "published_at": datetime.now().strftime('%Y-%m-%d'),
        "status": "current",
        "methodology_version": methodology_version,
        "summary": summary,
        "summary_facts": summary_facts,
        "spec_urls": spec_urls,
        "metrics": {
            "dmi_median": metrics['dmi_median'],
            "dmi_stress": metrics['dmi_stress'],
            "income_pressure_spread": metrics['income_pressure_spread'],
            "income_pressure_tilt": metrics['income_pressure_tilt'],
            "most_pressured_group": metrics['most_pressured_group'],
            "least_pressured_group": metrics['least_pressured_group'],
            "unemployment": metrics['unemployment'],
        },
    }
    if notes:
        latest_release["notes"] = notes

    latest_manifest = {
        "schema_version": "2.0.0",
        "generated_at": datetime.now().isoformat() + "Z",
        "current_release_id": reference_period,
        "releases": [latest_release]
    }

    with open(latest_path, 'w') as f:
        json.dump(latest_manifest, f, indent=2)

    print(f"✓ Updated latest.json with release {reference_period}")
    return latest_path


def update_health_json(reference_period: str):
    """Update web/health.json with current release information."""
    health_path = Path("web/health.json")

    # Read current health.json
    with open(health_path, "r") as f:
        health = json.load(f)

    # Update basic fields
    health["version"] = METHODOLOGY_VERSION.lstrip("v")
    health["latest_period"] = reference_period
    health["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    health["build_timestamp"] = datetime.now().isoformat() + "Z"
    health["git_sha"] = "production"  # Will be updated by deployment

    # Ensure endpoints exists
    health.setdefault("endpoints", {})

    # Update current release endpoints
    health["endpoints"]["latest"] = f"/data/outputs/dmi_release_{reference_period}.json"
    health["endpoints"]["latest_slack_plus"] = f"/data/outputs/dmi_release_{reference_period}_slack_plus.json"
    health["endpoints"]["latest_u6"] = health["endpoints"]["latest_slack_plus"]    
    health["endpoints"]["latest_core"] = f"/data/outputs/dmi_release_{reference_period}_core.json"

    # Optional: only include latest_with_ci if current-period file exists
    latest_with_ci_path = Path(f"data/outputs/dmi_release_{reference_period}_with_ci.json")
    if latest_with_ci_path.exists():
        health["endpoints"]["latest_with_ci"] = f"/data/outputs/dmi_release_{reference_period}_with_ci.json"
    else:
        health["endpoints"].pop("latest_with_ci", None)

    # Update observations count if we can determine it
    if "observations_count" not in health:
        health["observations_count"] = 895  # Default based on recent data

    with open(health_path, "w") as f:
        json.dump(health, f, indent=2)

    print(f"✓ Updated web/health.json with latest period {reference_period}")
    return health_path


def update_timeseries_json(reference_period: str):
    """Update dmi_timeseries.json with new release observations."""
    timeseries_path = Path("data/outputs/published/dmi_timeseries.json")
    release_path = Path("data/outputs") / f"dmi_release_{reference_period}.json"
    quintile_order = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    
    # Load release file
    if not release_path.exists():
        print(f"⚠ Release file not found: {release_path}, skipping timeseries update")
        return timeseries_path
    
    with open(release_path, 'r') as f:
        release = json.load(f)
    
    # Load existing timeseries
    with open(timeseries_path, 'r') as f:
        timeseries = json.load(f)
    
    # Extract observations from release
    weights_vintage = release.get("parameters", {}).get("weights_year", 2023)
    new_observations = []
    for group in release["dmi_by_group"]:
        new_observations.append({
            "period": reference_period,
            "group_id": group["group_id"],
            "dmi": group["dmi"],
            "inflation": group["inflation"],
            "slack": group["slack"],
            "weights_vintage": weights_vintage,
        })
    
    # Remove existing observations for this period (upsert) and add new ones
    existing_obs = timeseries["observations"]
    existing_obs = [o for o in existing_obs if o["period"] != reference_period]
    existing_obs.extend(new_observations)
    
    # Sort observations by period, then by quintile order
    def sort_key(obs: dict) -> tuple:
        q_idx = quintile_order.index(obs["group_id"]) if obs["group_id"] in quintile_order else 99
        return (obs["period"], q_idx)
    
    existing_obs.sort(key=sort_key)
    
    # Update metadata
    all_periods = sorted(set(o["period"] for o in existing_obs))
    timeseries["observations"] = existing_obs
    timeseries["observations_count"] = len(existing_obs)
    timeseries["start_period"] = all_periods[0]
    timeseries["end_period"] = all_periods[-1]
    
    # Save updated timeseries
    with open(timeseries_path, 'w') as f:
        json.dump(timeseries, f, indent=2)
    
    print(f"✓ Updated dmi_timeseries.json with {reference_period} ({len(new_observations)} observations, {timeseries['start_period']} to {timeseries['end_period']})")
    return timeseries_path


def main(weights_year: int=2023):
    print("=" * 80)
    print("DMI v0.1.8 - Full Integration Test")
    print("=" * 80)
    
    # Determine the year range for data files based on current date
    # Data files span Oct-Nov of year N to Sep-Oct of year N+1
    # e.g., cpi_levels_2024_2025.json covers late 2024 through most of 2025
    now = datetime.now()
    # If we're in the later months (Nov-Dec), we need the current_year to next_year file
    if now.month >= 11:
        start_year = now.year
        end_year = now.year + 1
    else:
        start_year = now.year - 1
        end_year = now.year
    
    # Paths
    weights_path = Path("data/curated/weights_by_group_{weights_year}.json")
    cpi_path = Path(f"data/staging/cpi_levels_{start_year}_{end_year}.json")
    if spec == "slack_plus":
        slack_measure = "u6"
        slack_measure_display = "U-6"
    else:
        slack_measure = "u3" 
        slack_measure_display = "U-3"
        
    slack_path = Path(f"data/staging/slack_{slack_measure}_{start_year}_{end_year}.json")
    
    # Load data
    print("\nLoading data...")
    weights_df = load_weights(weights_path)
    print(f"  ✓ Weights: {len(weights_df)} records (5 quintiles × 8 categories)")
    
    cpi_df = load_cpi_data(cpi_path)
    print(f"  ✓ CPI data: {len(cpi_df)} periods, 8 categories")
    
    slack_df = load_slack_data(slack_path)
    print(f"  ✓ Slack data: {len(slack_df)} periods")

    # Determine reference period dynamically from CPI data
    # Use the most recent complete month available in the data
    print("\n" + "=" * 80)
    available_periods = sorted(cpi_df['period'].unique())
    reference_period = available_periods[-1]  # Latest available period
    print(f"Using reference period: {reference_period} (latest in data)")
    
    results = compute_dmi_for_period(
        cpi_df=cpi_df,
        weights_df=weights_df,
        slack_df=slack_df,
        reference_period=reference_period,
        alpha=0.5,
        scale_factor=2.0,
        spec=spec
    )
    
    # Save results
    output_path = Path(f"data/outputs/dmi_release_{reference_period}.json")
    save_dmi_output(results, output_path)
    
    # Generate QA report
    print("\n" + "=" * 80)
    print("Generating QA Report...")
    print("=" * 80)
    
    qa_report = generate_qa_report(
        dmi_output=results,
        cpi_data=cpi_df,
        weights_data=weights_df,
        slack_data=slack_df,
        output_path=Path(f"data/outputs/qa_report_{reference_period}_{spec}.json")
    )
    
    print_qa_summary(qa_report)
    
    # Create CSV and Parquet files
    print("\n" + "=" * 80)
    print("Creating CSV and Parquet files...")
    print("=" * 80)
    
    csv_path, parquet_path = export_csv_parquet(results, reference_period, spec)
    
    # Generate release note HTML
    print("\n" + "=" * 80)
    print("Generating release note HTML...")
    print("=" * 80)
    
    # Shared metrics payload for summary, HTML, and manifest updates
    metrics_payload = {
        'dmi_median': results['summary_metrics']['dmi_median'],
        'dmi_stress': results['summary_metrics']['dmi_stress'],
        'income_pressure_spread': results['summary_metrics']['income_pressure_spread'],
        'income_pressure_tilt': results['summary_metrics']['income_pressure_tilt'],
        'most_pressured_group': results['summary_metrics']['most_pressured_group'],
        'least_pressured_group': results['summary_metrics']['least_pressured_group'],
        'unemployment': results['dmi_by_group'][0]['slack'],
    }

    # Generate summary
    current_release = {
        'release_id': reference_period,
        'data_through_label': f"{['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][int(reference_period.split('-')[1]) - 1]} {reference_period.split('-')[0]}",
        'metrics': metrics_payload,
    }

    # Get prior release
    prior_release = None
    releases_path = Path("data/outputs/releases.json")
    if releases_path.exists():
        with open(releases_path, 'r') as f:
            existing = json.load(f)
        existing_releases = existing.get('releases', [])
        existing_releases = [r for r in existing_releases if r.get('release_id') != reference_period]
        if existing_releases:
            existing_releases.sort(key=lambda x: x['release_id'], reverse=True)
            prior_release = existing_releases[0]

    summary_facts, summary = build_release_summary(current_release, prior_release)

    release_html = generate_release_note_html(
        reference_period=reference_period,
        metrics=metrics_payload,
        summary=summary,
        slack_measure=slack_measure_display
    )
    save_release_note(release_html, reference_period)

    # Update releases.json
    print("\n" + "=" * 80)
    print("Updating releases.json and latest.json...")
    print("=" * 80)

    update_releases_json(
        reference_period=reference_period,
        metrics=metrics_payload,
        summary=summary,
        summary_facts=summary_facts
    )

    update_latest_json(
        reference_period=reference_period,
        metrics=metrics_payload,
        summary=summary,
        summary_facts=summary_facts
    )
    
    # Update health.json
    update_health_json(reference_period)
    
    # Update timeseries
    update_timeseries_json(reference_period)
    
    # Print summary
    print("\n" + "=" * 80)
    print("DMI SUMMARY")
    print("=" * 80)
    print(f"Period: {reference_period}")
    print(f"Weights Year: {weights_year}")
    print(f"\nDMI by Income Quintile:")
    for record in results['dmi_by_group']:
        print(f"  {record['group_id']}: DMI={record['dmi']:6.2f}  (inflation={record['inflation']:5.2f}%, slack={record['slack']:4.1f}%)")
    
    print(f"\nSummary Metrics:")
    print(f"  Median DMI: {results['summary_metrics']['dmi_median']:.2f}")
    print(f"  Stress: {results['summary_metrics']['dmi_stress']:.2f}")
    print(f"  Income Pressure Spread (max-min): {results['summary_metrics']['income_pressure_spread']:.2f}")
    print(f"  Income Pressure Tilt (Q1-Q5): {results['summary_metrics']['income_pressure_tilt']:+.2f}")
    print(f"  Most pressured group: {results['summary_metrics']['most_pressured_group']}")
    print(f"  Least pressured group: {results['summary_metrics']['least_pressured_group']}")
    
    print("\n" + "=" * 80)
    print("✓ Full DMI integration test completed successfully!")
    print("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
