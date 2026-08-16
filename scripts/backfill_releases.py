#!/usr/bin/env python3
"""Backfill releases.json/latest.json/health.json/timeseries from raw releases.

Round-3 §9: this script previously duplicated release-manifest construction
logic (parse, filter, spec-url naming, methodology-version tagging, entry
assembly) that also lived in ``scripts/rebuild_release_manifests.py``. The
two implementations drifted:

  - ``backfill_releases.py`` unconditionally emitted the modern
    ``dmi-YYYY-MM-baseline.{csv,parquet}`` URL pattern for every period,
    including pre-2026-03 releases (2025-12, 2026-01, 2026-02) which
    only publish the unsuffixed ``dmi-YYYY-MM.{csv,parquet}`` naming.
    The result: ``releases.json`` advertised URLs that 404 on the live
    site — a §3 (historical URL repair) failure.
  - ``backfill_releases.py`` hard-coded ``"methodology_version": "v0.1.12"``
    for every release entry, retroactively relabelling historical
    releases whose raw file lacks the v0.1.12 parameter block.
    ``rebuild_release_manifests.py`` correctly derives the label per
    release via ``derive_methodology_version`` (unknown -> ``legacy/unknown``).

Both defects are eliminated by having this script delegate manifest
assembly to the central helpers in ``rebuild_release_manifests``. This
module now only owns the side-effects that ``rebuild_release_manifests``
intentionally leaves out: updating ``web/health.json`` (endpoints sanitised
via ``sanitize_health_endpoints``) and ``data/outputs/published/dmi_timeseries.json``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.rebuild_release_manifests import (
    assemble_manifests,
    discover_releases,
)


def backfill_releases(output_dir: str = "data/outputs") -> None:
    """Rebuild releases.json + latest.json + health.json + timeseries.

    Manifest assembly (parsing, filtering to public releases, deriving
    metrics, choosing correct spec_url naming per period, deriving
    methodology_version per release) is delegated to
    ``rebuild_release_manifests`` so the two writers cannot drift.
    """
    output_path = Path(output_dir)

    # Discover every public release under the same rules the retrofit
    # tool uses; requested_periods=None -> "all public releases".
    plans = discover_releases(output_path, requested_periods=None)
    if not plans:
        print("No public releases found to backfill.")
        return

    releases_manifest, latest_manifest = assemble_manifests(plans)

    releases_path = output_path / "releases.json"
    latest_path = output_path / "latest.json"

    releases_path.write_text(json.dumps(releases_manifest, indent=2))
    latest_path.write_text(json.dumps(latest_manifest, indent=2))

    print(
        f"✓ Wrote {len(releases_manifest['releases'])} public releases to "
        f"{releases_path}"
    )
    print(f"✓ Wrote current release to {latest_path}")

    current_release_id = releases_manifest["current_release_id"]
    update_health_json(current_release_id)
    update_timeseries_json(current_release_id)


def update_health_json(reference_period: str) -> Path:
    """Update web/health.json with current release information.

    §7/§8: the endpoints block is passed through ``sanitize_health_endpoints``
    just before writing, so any retired key present on disk
    (``latest_core``, ``latest_u6``, ``latest_with_ci``, ``timeseries``,
    ``dmi_timeseries``) is stripped from the manifest. This defeats the
    round-trip resurrection failure mode where an out-of-date checkout
    carried a retired endpoint forward across releases.
    """
    from scripts.health_endpoints import sanitize_health_endpoints

    health_path = Path("web/health.json")

    with health_path.open() as f:
        health = json.load(f)

    health["latest_period"] = reference_period
    health["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d")
    health["build_timestamp"] = datetime.utcnow().isoformat() + "Z"
    health["git_sha"] = "production"  # Overwritten by deployment pipeline.
    health.setdefault("endpoints", {})
    health["endpoints"]["latest"] = (
        f"/data/outputs/dmi_release_{reference_period}.json"
    )
    health["endpoints"]["latest_slack_plus"] = (
        f"/data/outputs/dmi_release_{reference_period}_slack_plus.json"
    )

    if "observations_count" not in health:
        health["observations_count"] = 895  # Default based on recent data.

    # §7/§8: strip retired/unknown endpoint keys before writing.
    sanitize_health_endpoints(health)

    with health_path.open("w") as f:
        json.dump(health, f, indent=2)

    print(f"✓ Updated web/health.json with latest period {reference_period}")
    return health_path


def update_timeseries_json(reference_period: str) -> Path:
    """Update dmi_timeseries.json with new release observations."""
    timeseries_path = Path("data/outputs/published/dmi_timeseries.json")
    release_path = Path("data/outputs") / f"dmi_release_{reference_period}.json"
    quintile_order = ["Q1", "Q2", "Q3", "Q4", "Q5"]

    if not release_path.exists():
        return timeseries_path

    with release_path.open() as f:
        release = json.load(f)

    with timeseries_path.open() as f:
        timeseries = json.load(f)

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

    # Upsert: drop existing observations for this period, add the new ones.
    existing_obs = [
        o for o in timeseries["observations"] if o["period"] != reference_period
    ]
    existing_obs.extend(new_observations)

    def sort_key(obs: dict) -> tuple:
        q_idx = (
            quintile_order.index(obs["group_id"])
            if obs["group_id"] in quintile_order
            else 99
        )
        return (obs["period"], q_idx)

    existing_obs.sort(key=sort_key)

    all_periods = sorted({o["period"] for o in existing_obs})
    timeseries["observations"] = existing_obs
    timeseries["observations_count"] = len(existing_obs)
    timeseries["start_period"] = all_periods[0]
    timeseries["end_period"] = all_periods[-1]

    with timeseries_path.open("w") as f:
        json.dump(timeseries, f, indent=2)

    return timeseries_path


if __name__ == "__main__":
    backfill_releases()
