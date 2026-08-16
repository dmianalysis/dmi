#!/usr/bin/env python3
"""Regenerate per-period release notes from the raw release files + manifest.

Under repair spec §4 the release note is a shared per-period document
linked from the top-level ``release_note`` field of each release entry.
Historically the generator was invoked once per spec run and fabricated
rows for specifications (notably the withdrawn Core spec and, in
baseline-only periods, a synthesized Slack+) that were never actually
computed.

This script deterministically rebuilds every ``data/outputs/releases/
YYYY-MM.html`` file for every release listed in ``releases.json`` by:

1. Loading the raw baseline release file (``dmi_release_YYYY-MM.json``).
2. Loading the raw Slack+ release file if — and only if — a companion
   ``dmi_release_YYYY-MM_slack_plus.json`` exists on disk.
3. Constructing an ephemeral per-period ``specifications`` object
   containing only the specs actually present, and calling
   ``generate_release_note_html`` from ``scripts.compute_dmi``.

The generator itself has been repaired to skip any spec not present in
the supplied manifest, so baseline-only periods render a single-row
"Specification" table and no Slack+ or Core row can ever appear.

The script is read-only in ``--dry-run`` mode: it prints the periods it
would rewrite without touching the filesystem. The default is to write
the files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.compute_dmi import generate_release_note_html  # noqa: E402
from scripts.rebuild_release_manifests import derive_metrics_for_raw  # noqa: E402


def _load_raw(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _build_spec_entry(spec_id: str, raw: dict) -> dict:
    """Build a single per-period specification manifest entry.

    Sources every numeric value from the raw release file so we never
    invent values that were not actually computed for this period.
    """
    slack_measure = str(raw.get("parameters", {}).get("slack_measure", "")).lower()
    if not slack_measure:
        # Historical (pre-v0.1.12) files lack an explicit slack_measure.
        # We can still recover the label from the spec_id we're building:
        # baseline == U-3, slack_plus == U-6 (per the two published specs).
        slack_measure = "u3" if spec_id == "baseline" else "u6"

    dmi_by_group = raw["dmi_by_group"]
    # Slack is a per-period, spec-wide value in these files (identical
    # across income groups); read it off any group entry.
    slack_value = float(dmi_by_group[0]["slack"])

    derived = derive_metrics_for_raw(raw)
    return {
        "spec_id": spec_id,
        "metrics": {
            **derived,
            "slack": slack_value,
            "slack_measure": slack_measure,
        },
    }


def _build_specifications(reference_period: str, outputs_dir: Path) -> dict:
    """Assemble the per-period ephemeral specifications manifest.

    Only specs whose raw release file exists on disk are included.
    """
    baseline_path = outputs_dir / f"dmi_release_{reference_period}.json"
    slack_plus_path = outputs_dir / f"dmi_release_{reference_period}_slack_plus.json"

    baseline = _load_raw(baseline_path)
    if baseline is None:
        raise FileNotFoundError(
            f"raw baseline release file not found for {reference_period}: "
            f"{baseline_path}"
        )
    slack_plus = _load_raw(slack_plus_path)

    specifications = [_build_spec_entry("baseline", baseline)]
    if slack_plus is not None:
        specifications.append(_build_spec_entry("slack_plus", slack_plus))

    # Compute a truthful robustness_assessment: consistent when the
    # cross-spec tilt signs and highest-stress group agree, or when only
    # a single spec exists (vacuously consistent, but the generator will
    # suppress the warning either way since single-spec periods use the
    # "Specification" heading and no warning).
    tilt_signs = {
        s["metrics"]["income_pressure_tilt"] >= 0 for s in specifications
    }
    stress_groups = {s["metrics"]["most_pressured_group"] for s in specifications}

    return {
        "reference_period": reference_period,
        "specifications": specifications,
        "robustness_assessment": {
            "pressure_tilt_sign_consistent": len(tilt_signs) <= 1,
            "stress_group_consistent": len(stress_groups) <= 1,
        },
    }


def regenerate_one(
    release: dict,
    outputs_dir: Path,
    dry_run: bool,
) -> Path:
    reference_period = release["release_id"]
    specifications = _build_specifications(reference_period, outputs_dir)

    html = generate_release_note_html(
        reference_period=reference_period,
        metrics=release["metrics"],
        summary=release.get("summary", ""),
        specifications=specifications,
        published_at=release.get("published_at"),
    )

    out_path = outputs_dir / "releases" / f"{reference_period}.html"
    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(html)
    return out_path


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default="data/outputs",
        help="Directory containing manifests and raw releases (default: data/outputs).",
    )
    parser.add_argument(
        "--periods",
        nargs="+",
        metavar="YYYY-MM",
        help="Restrict regeneration to these reference periods.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned writes without touching the filesystem.",
    )
    args = parser.parse_args(argv)

    outputs_dir = Path(args.output_dir)
    releases = json.loads((outputs_dir / "releases.json").read_text())["releases"]

    if args.periods:
        wanted = set(args.periods)
        releases = [r for r in releases if r["release_id"] in wanted]
        missing = wanted - {r["release_id"] for r in releases}
        if missing:
            print(f"error: periods not present in releases.json: {sorted(missing)}")
            return 1

    if not releases:
        print("no releases to regenerate")
        return 0

    for release in releases:
        out_path = regenerate_one(release, outputs_dir, dry_run=args.dry_run)
        verb = "would write" if args.dry_run else "wrote"
        rel = out_path.relative_to(outputs_dir.parent.parent) if outputs_dir.is_absolute() else out_path
        print(f"  {verb} {rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
