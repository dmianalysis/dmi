#!/usr/bin/env python3
"""
Build public robustness/specifications manifest for the current DMI release.

Reads:
- data/outputs/dmi_release_YYYY-MM.json
- data/outputs/dmi_release_YYYY-MM_slack_plus.json

Writes:
- data/outputs/specifications.json
"""

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


SPEC_ORDER = ["baseline", "slack_plus"]

SPEC_META = {
    "baseline": {
        "label": "DMI Baseline",
        "summary": "Headline DMI using current inflation inputs and U-3 unemployment.",
        "suffix": "",
    },
    "slack_plus": {
        "label": "DMI Slack+",
        "summary": "Companion DMI using broader labor-market slack.",
        "suffix": "_slack_plus",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build DMI specifications manifest.")
    parser.add_argument("reference_period", help="Reference period in YYYY-MM format.")
    return parser.parse_args()


def load_release(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Missing release file: {path}")
    with open(path, "r") as f:
        return json.load(f)


def metrics_from_release(release: dict) -> dict:
    summary = release["summary_metrics"]
    params = release["parameters"]
    return {
        "dmi_median": summary["dmi_median"],
        "dmi_stress": summary["dmi_stress"],
        "income_pressure_spread": summary["income_pressure_spread"],
        "income_pressure_tilt": summary["income_pressure_tilt"],
        "most_pressured_group": summary["most_pressured_group"],
        "least_pressured_group": summary["least_pressured_group"],
        "slack": release["dmi_by_group"][0]["slack"],
        "slack_measure": params["slack_measure"],
    }


def pressure_pattern(release: dict) -> str:
    tilt = release["summary_metrics"]["income_pressure_tilt"]
    if tilt > 0.02:
        return "lower_income_more_pressure"
    if tilt < -0.02:
        return "higher_income_more_pressure"
    return "similar_pressure"


def stress_group(release: dict) -> str:
    return release["summary_metrics"]["most_pressured_group"]


def build_notes(releases_by_spec: dict) -> tuple[dict, list[str]]:
    baseline = releases_by_spec["baseline"]
    baseline_pattern = pressure_pattern(baseline)
    baseline_stress_group = stress_group(baseline)

    tilt_consistent = True
    stress_consistent = True

    for spec_id in ("slack_plus",):
        release = releases_by_spec[spec_id]
        if pressure_pattern(release) != baseline_pattern:
            tilt_consistent = False
        if stress_group(release) != baseline_stress_group:
            stress_consistent = False

    notes = []
    if tilt_consistent:
        notes.append("The distributional pattern is consistent across the published specifications.")
    else:
        notes.append("The distributional pattern varies across the published specifications.")

    if stress_consistent:
        notes.append(f"The highest-pressure income fifth remains {baseline_stress_group} across the published specifications.")
    else:
        notes.append("The highest-pressure income fifth changes across the published specifications.")

    robustness = {
        "pressure_tilt_sign_consistent": tilt_consistent,
        "stress_group_consistent": stress_consistent,
    }

    return robustness, notes


def build_specifications_manifest(
    reference_period: str,
    output_dir: Path = Path("data/outputs"),
    releases_by_spec: Optional[dict] = None,
) -> dict:
    """Build the three-spec manifest, optionally from preloaded releases."""
    if releases_by_spec is None:
        releases_by_spec = {}
        for spec_id in SPEC_ORDER:
            suffix = SPEC_META[spec_id]["suffix"]
            release_path = output_dir / f"dmi_release_{reference_period}{suffix}.json"
            releases_by_spec[spec_id] = load_release(release_path)

    manifest_specs = []
    for spec_id in SPEC_ORDER:
        suffix = SPEC_META[spec_id]["suffix"]
        release = releases_by_spec[spec_id]

        manifest_specs.append({
            "spec_id": spec_id,
            "label": SPEC_META[spec_id]["label"],
            "summary": SPEC_META[spec_id]["summary"],
            "release_json": f"/data/outputs/dmi_release_{reference_period}{suffix}.json",
            "metrics": metrics_from_release(release),
        })

    robustness_assessment, notes = build_notes(releases_by_spec)

    manifest = {
        "schema_version": "0.2.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "reference_period": reference_period,
        "headline_spec": "baseline",
        "specifications": manifest_specs,
        "robustness_assessment": {
            **robustness_assessment,
            "notes": notes,
        }
    }

    return manifest


def main():
    args = parse_args()
    output_dir = Path("data/outputs")
    manifest = build_specifications_manifest(args.reference_period, output_dir)

    output_path = output_dir / "specifications.json"
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"✓ Wrote specifications manifest: {output_path}")
    for note in manifest["robustness_assessment"]["notes"]:
        print(f"  - {note}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
