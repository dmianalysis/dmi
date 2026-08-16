#!/usr/bin/env python3
"""
Backfill releases.json from existing DMI release files.
Only includes publicly distributed releases (2025-12 and later).
"""

import sys
import json
from pathlib import Path
from datetime import datetime

# Reuse summary helpers from compute_dmi to avoid drift between two implementations.
from scripts.compute_dmi import build_release_summary
from scripts.schema_versions import RELEASES_SCHEMA_VERSION


def parse_release_id(filename: str) -> tuple:
    """Parse release_id from filename. Returns (year, month) or None if invalid."""
    # Format: dmi_release_2026-02.json
    try:
        release_id = filename.replace("dmi_release_", "").replace(".json", "")
        year, month = release_id.split('-')
        return (int(year), int(month))
    except:
        return None

def is_public_release(year: int, month: int) -> bool:
    """Check if release is publicly distributed (2025-12 and later)."""
    if year < 2025:
        return False
    if year == 2025 and month < 12:
        return False
    return True

def backfill_releases(output_dir: str = "data/outputs"):
    """Backfill releases.json from existing dmi_release_*.json files (public releases only)."""
    output_path = Path(output_dir)
    
    # Find all dmi_release_*.json files
    release_files = sorted(output_path.glob("dmi_release_*.json"))
    
    if not release_files:
        print("No release files found to backfill")
        return
    
    print(f"Found {len(release_files)} release files, filtering for public releases (2025-12+)")
    
    releases = []
    latest_release = None
    
    # Process each release file
    for release_file in release_files:
        # Extract release_id from filename (e.g., dmi_release_2026-02.json -> 2026-02)
        parsed = parse_release_id(release_file.name)
        if not parsed:
            continue
        
        year, month = parsed
        release_id = f"{year:04d}-{month:02d}"
        
        # Skip non-public releases
        if not is_public_release(year, month):
            print(f"  ⊘ {release_id}: Not in public distribution (pre-2025-12)")
            continue
        
        try:
            with open(release_file, 'r') as f:
                data = json.load(f)

            # Derive distribution metrics directly from dmi_by_group so output is
            # consistent regardless of which summary_metrics fields were written
            # at compute time.
            dmi_by_group = data['dmi_by_group']
            dmis = {g['group_id']: g['dmi'] for g in dmi_by_group}
            max_group = max(dmi_by_group, key=lambda g: g['dmi'])
            min_group = min(dmi_by_group, key=lambda g: g['dmi'])
            spread = max_group['dmi'] - min_group['dmi']
            tilt = dmis['Q1'] - dmis['Q5']
            unemployment = dmi_by_group[0]['slack']

            # Convert release_id to data_through_label
            months = ['January', 'February', 'March', 'April', 'May', 'June',
                      'July', 'August', 'September', 'October', 'November', 'December']
            month_name = months[month - 1]
            data_through_label = f"{month_name} {year}"

            # published_at from metadata when available
            computed_at = data['metadata']['computed_at']
            published_at = computed_at.split('T')[0]

            # Core has been withdrawn (see docs/repair/CORE_WITHDRAWAL.md).
            # Slack-Plus is only advertised when its CSV actually exists.
            # release_note lives at the top of the release entry per
            # releases.schema.json 3.0.0.
            #
            # NOTE: §3 (historical URL repair) will further require every
            # emitted spec_url to resolve to an existing file on disk;
            # for now we preserve the pre-§2 baseline-block naming and
            # only relocate release_note.
            spec_urls = {
                "baseline": {
                    "csv": f"/data/outputs/dmi-{release_id}-baseline.csv",
                    "parquet": f"/data/outputs/dmi-{release_id}-baseline.parquet",
                },
            }
            slack_plus_json = output_path / f"dmi_release_{release_id}_slack_plus.json"
            if slack_plus_json.exists():
                spec_urls["slack_plus"] = {
                    "csv": f"/data/outputs/dmi-{release_id}-slack_plus.csv",
                    "parquet": f"/data/outputs/dmi-{release_id}-slack_plus.parquet",
                }

            release = {
                "release_id": release_id,
                "data_through_label": data_through_label,
                "published_at": published_at,
                "status": "superseded",  # Updated to current for the latest
                "methodology_version": "v0.1.12",
                "summary": "Full release data available in the accompanying CSV and Parquet files.",
                "release_note": f"/data/outputs/releases/{release_id}.html",
                "spec_urls": spec_urls,
                "metrics": {
                    "dmi_median": data['summary_metrics']['dmi_median'],
                    "dmi_stress": data['summary_metrics']['dmi_stress'],
                    "income_pressure_spread": spread,
                    "income_pressure_tilt": tilt,
                    "most_pressured_group": max_group['group_id'],
                    "least_pressured_group": min_group['group_id'],
                    "unemployment": unemployment,
                },
            }

            releases.append(release)
            
            # Generate summary
            prior_release = releases[-2] if len(releases) > 1 else None
            summary_facts, summary = build_release_summary(release, prior_release)
            release['summary'] = summary
            release['summary_facts'] = summary_facts
            
            latest_release = release  # Keep track of the latest
            
            print(f"  ✓ {release_id}: {data_through_label}")
            
        except Exception as e:
            print(f"  ✗ Error processing {release_id}: {e}")
    
    if not releases:
        print("No public releases found to save")
        return
    
    # Mark the latest as current
    if latest_release:
        latest_release['status'] = 'current'
        current_release_id = latest_release['release_id']
    else:
        current_release_id = releases[0]['release_id']
    
    # Sort in reverse chronological order
    releases.sort(key=lambda x: x['release_id'], reverse=True)
    
    # Build the releases.json structure
    releases_manifest = {
        "schema_version": RELEASES_SCHEMA_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "current_release_id": current_release_id,
        "releases": releases
    }

    # Save releases.json
    releases_path = output_path / "releases.json"
    with open(releases_path, 'w') as f:
        json.dump(releases_manifest, f, indent=2)

    print(f"\n✓ Saved {len(releases)} public releases to {releases_path}")

    # Build latest.json with only the current release
    latest_manifest = {
        "schema_version": RELEASES_SCHEMA_VERSION,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "current_release_id": current_release_id,
        "releases": [latest_release]
    }
    
    latest_path = output_path / "latest.json"
    with open(latest_path, 'w') as f:
        json.dump(latest_manifest, f, indent=2)
    
    print(f"✓ Saved latest release to {latest_path}")
    
    # Update health.json
    update_health_json(current_release_id)
    
    # Update timeseries
    update_timeseries_json(current_release_id)


def update_health_json(reference_period: str):
    """Update web/health.json with current release information."""
    health_path = Path("web/health.json")
    
    # Read current health.json
    with open(health_path, 'r') as f:
        health = json.load(f)
    
    # Update fields
    health['latest_period'] = reference_period
    health['last_updated'] = datetime.utcnow().strftime('%Y-%m-%d')
    health['build_timestamp'] = datetime.utcnow().isoformat() + "Z"
    health['git_sha'] = "production"  # Will be updated by deployment
    health['endpoints']['latest'] = f"/data/outputs/dmi_release_{reference_period}.json"
    
    # Update observations count if we can determine it
    if 'observations_count' not in health:
        health['observations_count'] = 895  # Default based on recent data
    
    with open(health_path, 'w') as f:
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
    
    return timeseries_path


if __name__ == "__main__":
    backfill_releases()
