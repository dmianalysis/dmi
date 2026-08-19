#!/usr/bin/env python3
"""Transactional release finalization (Round-4 §1).

The problem this replaces
-------------------------
Publication used to happen *during* computation. ``compute_dmi_release``
with ``--spec baseline`` wrote ``releases.json``, ``latest.json``,
``web/health.json`` and the public timeseries as a side effect of
computing a number, and both specs wrote their CSV/Parquet exports the
same way. The monthly workflow then built ``specifications.json``, the
release note and the timeseries *before* it looked at QA at all — and
when it did look, it validated that the QA report was well-formed JSON,
never that it had passed.

So a run whose QA reported five hard failures would still have mutated
every public manifest by the time anyone noticed, leaving the site
advertising a release that failed its own checks, with no way back but
manual repair.

The order this enforces
-----------------------
1. Baseline raw output + QA report  (produced by ``compute_dmi_release``)
2. Slack-Plus raw output + QA report (produced by ``compute_dmi_release``)
3. validate both raw outputs against their schema
4. validate both QA reports against their schema
5. enforce QA outcome policy
6. enforce Baseline/Slack-Plus identity
7. only now: publish CSV/Parquet, releases.json, latest.json,
   specifications.json, the release note, the timeseries, health.json,
   and deployment staging
8. re-validate the finalized public tree

Steps 1 and 2 are inputs here, not actions: this module never computes a
DMI. It reads what computation produced, decides whether it may be
published, and publishes it as one unit.

Why it is transactional
-----------------------
Gates 3-6 are read-only, so an ordinary run that fails a gate has not
written anything yet. That is necessary but not sufficient: a failure
*during* step 7 — a disk error, a writer raising on its third of eight
files — would leave the public tree half-updated, which is the same
inconsistent state by a different route.

So every mutable public path is snapshotted before step 7 and restored
on any exception. "Restored" includes deleting files that did not exist
before, because a stray new artifact is as much a corruption of the
published set as a modified one.

Diagnostic output from a failed run is written under a clearly-marked
``.finalize-candidate/`` directory that no manifest references and the
deployment builder never walks, so it cannot be mistaken for published
output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

from scripts.release_evidence import (
    OPERATIONAL_SPECS,
    raw_release_filename,
    verify_raw_artifact,
)
from scripts.release_policy import GateFailure, check_cross_spec, evaluate_qa_report

#: Directory for diagnostics from a failed run. Deliberately dot-prefixed
#: and named so nothing mistakes it for published output; no manifest
#: references it and `prepare_deployment` never walks it.
CANDIDATE_DIR = Path(".finalize-candidate")


def qa_report_path(output_dir: Path, period: str, spec: str) -> Path:
    return output_dir / f"qa_report_{period}_{spec}.json"


def raw_path(output_dir: Path, period: str, spec: str) -> Path:
    return output_dir / raw_release_filename(period, spec)


# ---------------------------------------------------------------------------
# The mutable public surface
# ---------------------------------------------------------------------------

def mutable_public_paths(period: str, repo_root: Path = REPO_ROOT) -> list[Path]:
    """Every path step 7 may write, for snapshot/restore.

    Raw release JSON and QA reports are NOT here: they are inputs to
    finalization, produced by computation, and finalization never
    rewrites them.
    """
    out = repo_root / "data" / "outputs"
    paths = [
        out / "releases.json",
        out / "latest.json",
        out / "specifications.json",
        out / "published" / "dmi_timeseries.json",
        out / "releases" / f"{period}.html",
        repo_root / "web" / "health.json",
    ]
    # Tabular publication artifacts for both specs, under either naming.
    from scripts.release_evidence import tabular_stem
    for spec in OPERATIONAL_SPECS:
        stem = tabular_stem(period, spec)
        paths.append(out / f"{stem}.csv")
        paths.append(out / f"{stem}.parquet")
    return paths


def _snapshot_file(path: Path) -> Optional[bytes]:
    return path.read_bytes() if path.is_file() else None


def _snapshot_tree(root: Path) -> Optional[dict]:
    if not root.is_dir():
        return None
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def snapshot(period: str, repo_root: Path = REPO_ROOT) -> dict:
    """Capture the pre-run bytes of everything step 7 may touch."""
    return {
        "files": {
            str(p): _snapshot_file(p)
            for p in mutable_public_paths(period, repo_root)
        },
        "deploy": _snapshot_tree(repo_root / "deploy"),
    }


def restore(snap: dict, repo_root: Path = REPO_ROOT) -> list[str]:
    """Put every snapshotted path back exactly as it was.

    Returns the list of paths that had to be reverted, so a failed run
    can report what it undid rather than claiming a clean rollback it
    never verified.
    """
    reverted: list[str] = []

    for path_str, original in snap["files"].items():
        path = Path(path_str)
        if original is None:
            if path.exists():
                path.unlink()
                reverted.append(f"removed {path} (did not exist before)")
        else:
            if not path.is_file() or path.read_bytes() != original:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
                reverted.append(f"restored {path}")

    deploy_root = repo_root / "deploy"
    original_tree = snap["deploy"]
    if original_tree is not None:
        current = _snapshot_tree(deploy_root) or {}
        if current != original_tree:
            if deploy_root.exists():
                shutil.rmtree(deploy_root)
            for rel, data in original_tree.items():
                target = deploy_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            reverted.append(f"restored {deploy_root} ({len(original_tree)} files)")
    elif deploy_root.exists():
        shutil.rmtree(deploy_root)
        reverted.append(f"removed {deploy_root} (did not exist before)")

    return reverted


def public_digest(period: str, repo_root: Path = REPO_ROOT) -> dict[str, Optional[str]]:
    """SHA-256 of every mutable public path (None when absent).

    Used by tests to prove a failed run changed nothing.
    """
    digests: dict[str, Optional[str]] = {}
    for path in mutable_public_paths(period, repo_root):
        digests[str(path.relative_to(repo_root))] = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file() else None
        )
    deploy_root = repo_root / "deploy"
    tree = _snapshot_tree(deploy_root)
    if tree is None:
        digests["deploy/"] = None
    else:
        joined = b"".join(
            rel.encode() + b"\0" + data for rel, data in sorted(tree.items())
        )
        digests["deploy/"] = hashlib.sha256(joined).hexdigest()
    return digests


# ---------------------------------------------------------------------------
# Gates 3-6
# ---------------------------------------------------------------------------

def run_gates(
    period: str,
    output_dir: Path,
    require_subject: bool = True,
) -> tuple[list[str], list[str]]:
    """Run gates 3-6. Returns ``(problems, warnings)``; empty problems = pass.

    Read-only by construction: nothing here writes to the repository.
    """
    problems: list[str] = []
    warnings: list[str] = []
    raws: dict[str, dict] = {}

    # --- gate 3: raw outputs validate and identify themselves -----------
    for spec in OPERATIONAL_SPECS:
        path = raw_path(output_dir, period, spec)
        found = verify_raw_artifact(path, period, spec)
        problems.extend(found)
        if not found:
            raws[spec] = json.loads(path.read_text())

    # --- gates 4 + 5: QA schema and outcome policy ----------------------
    for spec in OPERATIONAL_SPECS:
        qa_problems, qa_warnings = evaluate_qa_report(
            qa_report_path(output_dir, period, spec),
            expected_period=period,
            expected_spec=spec,
            raw_artifact_path=raw_path(output_dir, period, spec),
            require_subject=require_subject,
        )
        problems.extend(qa_problems)
        warnings.extend(qa_warnings)

    # --- gate 6: cross-specification identity ---------------------------
    if len(raws) == len(OPERATIONAL_SPECS):
        problems.extend(check_cross_spec(raws["baseline"], raws["slack_plus"]))
    else:
        problems.append(
            "cross-spec: skipped because one or both raw outputs failed "
            "validation; treated as a failure so a half-computed release "
            "cannot pass by omission"
        )

    return (problems, warnings)


# ---------------------------------------------------------------------------
# Step 7: publication
# ---------------------------------------------------------------------------

def publish(period: str, output_dir: Path, repo_root: Path = REPO_ROOT) -> None:
    """Generate every mutable public artifact. Only called after gates pass."""
    from scripts.build_specifications_manifest import build_specifications_manifest
    from scripts.compute_dmi import (
        export_csv_parquet,
        update_health_json,
        update_latest_json,
        update_releases_json,
        update_timeseries_json,
        build_release_summary,
    )
    from scripts.compute_dmi_release import (
        MONTH_NAMES,
        build_metrics_payload,
        generate_release_note_for_period,
        load_prior_release,
    )

    # 7a. tabular publication artifacts
    for spec in OPERATIONAL_SPECS:
        results = json.loads(raw_path(output_dir, period, spec).read_text())
        export_csv_parquet(results, period, spec)

    baseline = json.loads(raw_path(output_dir, period, "baseline").read_text())

    # 7b. specifications.json (before manifests, so the release note and
    #     manifests describe a consistent specification set)
    manifest = build_specifications_manifest(period, output_dir)
    (output_dir / "specifications.json").write_text(
        json.dumps(manifest, indent=2)
    )

    # 7c. releases.json + latest.json
    year, month = period.split("-")
    current_release = {
        "release_id": period,
        "data_through_label": f"{MONTH_NAMES[int(month) - 1]} {year}",
        "metrics": build_metrics_payload(baseline),
    }
    prior_release = load_prior_release(period)
    summary_facts, summary = build_release_summary(current_release, prior_release)
    metrics_payload = build_metrics_payload(baseline)

    update_releases_json(
        reference_period=period,
        metrics=metrics_payload,
        summary=summary,
        summary_facts=summary_facts,
    )
    update_latest_json(
        reference_period=period,
        metrics=metrics_payload,
        summary=summary,
        summary_facts=summary_facts,
    )

    # 7d. release note HTML
    generate_release_note_for_period(period)

    # 7e. public timeseries
    update_timeseries_json(period)

    # 7f. health.json
    update_health_json(period)

    # 7g. deployment staging, via the canonical builder only
    from scripts.prepare_deployment import prepare_deployment
    prepare_deployment(repo_root / "deploy", repo_root=repo_root)


# ---------------------------------------------------------------------------
# Step 8 + orchestration
# ---------------------------------------------------------------------------

def verify_published(repo_root: Path = REPO_ROOT) -> list[str]:
    """Re-validate the finalized public tree (step 8)."""
    from scripts.prepare_deployment import verify_deployment
    return verify_deployment(repo_root / "deploy", repo_root=repo_root)


def finalize(
    period: str,
    output_dir: Optional[Path] = None,
    repo_root: Path = REPO_ROOT,
    require_subject: bool = True,
    dry_run: bool = False,
) -> tuple[int, list[str], list[str]]:
    """Run the full finalization. Returns ``(rc, problems, warnings)``.

    On any failure — gate or publication — every mutable public artifact
    and the deployment staging tree are left byte-identical to their
    pre-run state.
    """
    output_dir = output_dir or (repo_root / "data" / "outputs")

    problems, warnings = run_gates(period, output_dir, require_subject)

    for warning in warnings:
        print(f"  QA WARNING: {warning}", file=sys.stderr)

    if problems:
        print(
            f"\nRELEASE GATES FAILED for {period}: "
            f"{len(problems)} problem(s). Nothing was published.",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return (1, problems, warnings)

    if dry_run:
        print(f"All gates passed for {period}. Dry run: nothing published.")
        return (0, [], warnings)

    snap = snapshot(period, repo_root)
    try:
        publish(period, output_dir, repo_root)
        post = verify_published(repo_root)
        if post:
            raise GateFailure(
                "finalized public tree failed verification:\n  - "
                + "\n  - ".join(post)
            )
    except Exception as exc:
        reverted = restore(snap, repo_root)
        print(
            f"\nPUBLICATION FAILED for {period}: {exc}\n"
            f"Rolled back {len(reverted)} path(s); the public tree is "
            f"unchanged.",
            file=sys.stderr,
        )
        for item in reverted:
            print(f"  - {item}", file=sys.stderr)
        return (1, [str(exc)], warnings)

    print(f"\nRelease {period} finalized. All gates passed before publication.")
    if warnings:
        print(f"{len(warnings)} QA warning(s) recorded above — triage before merge.")
    return (0, [], warnings)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference_period", help="Reference period (YYYY-MM).")
    parser.add_argument(
        "--output-dir", default="data/outputs",
        help="Directory holding raw releases and QA reports.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run every gate and report, but publish nothing.",
    )
    parser.add_argument(
        "--allow-unbound-qa", action="store_true",
        help=(
            "Permit QA reports that carry no `subject` binding. For "
            "re-finalizing historical releases whose reports predate the "
            "binding; never for a current release."
        ),
    )
    args = parser.parse_args(argv)

    rc, _problems, _warnings = finalize(
        args.reference_period,
        output_dir=Path(args.output_dir),
        require_subject=not args.allow_unbound_qa,
        dry_run=args.dry_run,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
