#!/usr/bin/env python3
"""Regenerate published release notes with three-spec robustness tables."""

import argparse
import json
from pathlib import Path

from scripts.build_specifications_manifest import (
    SPEC_META,
    SPEC_ORDER,
    build_specifications_manifest,
)
from scripts.compute_dmi import (
    compute_dmi_for_period,
    load_cpi_data,
    load_slack_data,
    load_weights,
)
from scripts.compute_dmi_release import (
    generate_release_note_for_period,
    staging_window_for_period,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "periods",
        nargs="*",
        help="Periods to backfill (default: every existing release-note HTML file).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/outputs"),
        help="Directory containing release outputs (default: data/outputs).",
    )
    return parser.parse_args()


def discover_periods(output_dir: Path) -> list[str]:
    periods = []
    for path in (output_dir / "releases").glob("????-??.html"):
        try:
            year, month = path.stem.split("-")
            if len(year) == 4 and 1 <= int(month) <= 12:
                periods.append(path.stem)
        except ValueError:
            continue
    return sorted(periods)


def normalize_release(release: dict, spec_id: str) -> dict:
    """Supply metadata absent from pre-three-spec raw releases in memory."""
    release.setdefault("parameters", {})
    release["parameters"].setdefault(
        "slack_measure", "u6" if spec_id == "slack_plus" else "u3"
    )
    return release


def recompute_companion_release(
    reference_period: str,
    spec_id: str,
    output_dir: Path,
) -> dict:
    """Recompute a missing historical companion from committed inputs only."""
    baseline_path = output_dir / f"dmi_release_{reference_period}.json"
    if not baseline_path.exists():
        raise SystemExit(f"Missing baseline release file: {baseline_path}")
    baseline = json.loads(baseline_path.read_text())
    weights_year = baseline.get("parameters", {}).get("weights_year", 2023)
    start_year, end_year = staging_window_for_period(reference_period)

    weights_path = Path(f"data/curated/weights_by_group_{weights_year}.json")
    cpi_path = Path(f"data/staging/cpi_levels_{start_year}_{end_year}.json")
    slack_measure = "u6" if spec_id == "slack_plus" else "u3"
    slack_path = Path(
        f"data/staging/slack_{slack_measure}_{start_year}_{end_year}.json"
    )
    for path in (weights_path, cpi_path, slack_path):
        if not path.exists():
            raise SystemExit(
                f"Cannot reconstruct {reference_period} {spec_id}: missing {path}"
            )

    release = compute_dmi_for_period(
        cpi_df=load_cpi_data(cpi_path),
        weights_df=load_weights(weights_path),
        slack_df=load_slack_data(slack_path),
        reference_period=reference_period,
        weights_year=weights_year,
        spec=spec_id,
    )
    release["parameters"].update({
        "spec_id": spec_id,
        "slack_measure": slack_measure,
        "inflation_measure": "CORE_CPI" if spec_id == "core" else "HEADLINE_CPI",
    })
    return release


def load_releases_for_period(reference_period: str, output_dir: Path) -> dict:
    releases = {}
    for spec_id in SPEC_ORDER:
        suffix = SPEC_META[spec_id]["suffix"]
        release_path = output_dir / f"dmi_release_{reference_period}{suffix}.json"
        if release_path.exists():
            release = json.loads(release_path.read_text())
        elif spec_id == "baseline":
            raise SystemExit(f"Missing baseline release file: {release_path}")
        else:
            print(
                f"  ! {release_path.name} is absent; "
                "recomputing its metrics in memory from committed inputs."
            )
            release = recompute_companion_release(
                reference_period, spec_id, output_dir
            )
        releases[spec_id] = normalize_release(release, spec_id)
    return releases


def main() -> int:
    args = parse_args()
    periods = args.periods or discover_periods(args.output_dir)
    if not periods:
        raise SystemExit("No release notes found to backfill.")

    for period in periods:
        print(f"Backfilling {period}...")
        releases = load_releases_for_period(period, args.output_dir)
        specifications = build_specifications_manifest(
            period,
            args.output_dir,
            releases_by_spec=releases,
        )
        generate_release_note_for_period(
            period,
            specifications=specifications,
            output_dir=args.output_dir,
        )

    print(f"✓ Backfilled {len(periods)} release note(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
