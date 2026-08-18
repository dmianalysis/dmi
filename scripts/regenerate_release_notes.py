#!/usr/bin/env python3
"""Regenerate per-period release notes from the manifest + raw artifacts.

The release note is a shared per-period document linked from the
top-level ``release_note`` field of each entry in ``releases.json``.
Historically the generator was invoked once per spec run and fabricated
rows for specifications — the withdrawn Core spec, and a synthesized
Slack+ in Baseline-only periods — that were never computed.

Manifest evidence (Round-4 cleanup §1)
--------------------------------------
The published specification set is defined by the release entry's
``spec_urls``, and the raw artifacts are the evidence that the claim is
true. An earlier version of this script had that backwards: it looked
for raw files on disk and treated whatever it found as published. That
left two silent errors:

- a release advertising Slack-Plus whose raw artifact was missing
  rendered a Baseline-only note and returned success, concealing a real
  publication gap;
- an unadvertised Slack-Plus artifact left over on disk — from an
  interrupted run, say — was promoted into a historical note, presenting
  as published a series the manifest never claimed.

For every selected release the script now:

1. reads the advertised specification set from ``spec_urls``;
2. requires Baseline to be advertised;
3. rejects any advertised specification that is not operational
   (``baseline`` / ``slack_plus``) — a manifest advertising Core is a
   defect in the manifest, not something to render around;
4. requires each advertised artifact to exist, parse, validate against
   ``dmi_output.schema.json``, and declare the matching reference period
   and specification identity — via ``scripts.release_evidence``, the
   single authority, not a second copy of those rules;
5. renders only the advertised specifications;
6. warns about an unadvertised artifact found on disk but never treats
   it as published.

It never calls a DMI computation function and never reconstructs a
missing release.

All-or-nothing
--------------
A multi-period run used to write each note as it went, so an invalid
later period left earlier notes already rewritten. Every selected
release is now validated and rendered before anything is written; if any
fails, nothing is written and the command returns non-zero. The write
phase itself goes through temporary siblings and restores every touched
note — deleting ones that did not exist before — if any step fails.

``--dry-run`` is completely read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.compute_dmi import generate_release_note_html  # noqa: E402
from scripts.rebuild_release_manifests import derive_metrics_for_raw  # noqa: E402
from scripts.release_evidence import (  # noqa: E402  §5: single authority
    OPERATIONAL_SPECS,
    raw_release_filename,
    verify_raw_artifact,
)


class RegenerationError(RuntimeError):
    """A selected release failed manifest-evidence validation."""


def _load_raw(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    return json.loads(path.read_text())


def advertised_specs(release: dict) -> list[str]:
    """The specification set this release entry claims to publish.

    Round-4 §1 (cleanup): the MANIFEST decides what was published; the
    files are evidence that the claim is true. The previous version had
    it backwards — it globbed the outputs directory and treated whatever
    it found as the published set. That produced two silent errors:

    - a release advertising Slack-Plus whose raw artifact was missing
      quietly rendered a Baseline-only note, hiding a real gap;
    - an unadvertised Slack-Plus artifact left over on disk was promoted
      into a historical note, publishing a series the manifest never
      claimed.

    Both are resolved by reading `spec_urls` and requiring the files to
    corroborate it.
    """
    return sorted((release.get("spec_urls") or {}).keys())


def _validate_release(release: dict, outputs_dir: Path) -> tuple[dict, list[str]]:
    """Validate one release against its manifest claim.

    Returns ``(specifications, warnings)``. Raises ``RegenerationError``
    with every problem found, so an operator sees the whole picture
    rather than one failure per re-run.
    """
    reference_period = release["release_id"]
    advertised = advertised_specs(release)
    problems: list[str] = []
    warnings: list[str] = []

    if not advertised:
        raise RegenerationError(
            f"{reference_period}: releases.json advertises no "
            f"specification for this release; nothing to render."
        )

    # Core, or anything else that is not operational, is rejected
    # outright rather than skipped — a manifest claiming it is a defect
    # in the manifest, not something to render around.
    unknown = [s for s in advertised if s not in OPERATIONAL_SPECS]
    if unknown:
        problems.append(
            f"{reference_period}: releases.json advertises "
            f"non-operational specification(s) {unknown}; permitted "
            f"specifications are {list(OPERATIONAL_SPECS)}."
        )

    if "baseline" not in advertised:
        problems.append(
            f"{reference_period}: Baseline must be advertised by every "
            f"release; advertised set was {advertised}."
        )

    specifications: list[dict] = []
    for spec_id in [s for s in OPERATIONAL_SPECS if s in advertised]:
        raw_path = outputs_dir / raw_release_filename(reference_period, spec_id)
        found = verify_raw_artifact(raw_path, reference_period, spec_id)
        if found:
            problems.extend(f"{reference_period}: {item}" for item in found)
            continue
        specifications.append(
            _build_spec_entry(spec_id, json.loads(raw_path.read_text()))
        )

    # An artifact on disk that the manifest does not advertise is worth
    # saying out loud — it usually means a run was interrupted — but it
    # is NOT published, so it never enters the note.
    for spec_id in OPERATIONAL_SPECS:
        if spec_id in advertised:
            continue
        orphan = outputs_dir / raw_release_filename(reference_period, spec_id)
        if orphan.exists():
            warnings.append(
                f"{reference_period}: {orphan.name} exists on disk but is "
                f"NOT advertised by releases.json. It is treated as "
                f"unpublished and excluded from the release note. Publish "
                f"it through scripts.finalize_release if it should appear."
            )

    if problems:
        raise RegenerationError(
            f"{reference_period}: release does not match its manifest "
            f"claim:\n  - " + "\n  - ".join(problems)
        )

    return (_assemble_specifications(reference_period, specifications),
            warnings)


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


def _assemble_specifications(
    reference_period: str, specifications: list[dict],
) -> dict:
    """Wrap validated spec entries in the ephemeral per-period manifest."""
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


def render_one(release: dict, outputs_dir: Path) -> tuple[Path, str, list[str]]:
    """Validate and render one release. Writes nothing.

    Returns ``(target_path, html, warnings)``.
    """
    reference_period = release["release_id"]
    specifications, warnings = _validate_release(release, outputs_dir)

    html = generate_release_note_html(
        reference_period=reference_period,
        metrics=release["metrics"],
        summary=release.get("summary", ""),
        specifications=specifications,
        published_at=release.get("published_at"),
    )
    out_path = outputs_dir / "releases" / f"{reference_period}.html"
    return (out_path, html, warnings)


class IncompleteRollbackError(RuntimeError):
    """A write failed AND the rollback that followed did not fully succeed.

    Kept distinct from the underlying failure so the caller can tell the
    operator the truth. "Everything was restored" and "the restore itself
    hit a problem" require different responses, and reporting the second
    as the first is how an operator ends up trusting a tree that needs
    inspecting.
    """

    def __init__(self, original: BaseException, problems: list[str]):
        self.original = original
        self.problems = problems
        super().__init__(
            f"{original}; rollback incomplete: " + "; ".join(problems)
        )


def _commit_notes(rendered: list[tuple[Path, str]]) -> list[Path]:
    """Write every rendered note, or leave all of them untouched.

    Each note is written to a temporary sibling and then moved into
    place, so a target is never observed half-written. If any write or
    replacement fails, every note touched in this run is restored to its
    exact pre-run bytes — including deleting one that did not exist
    before, since a stray new note is as much a corruption of the
    published set as a modified one.

    The temporary path is registered for cleanup BEFORE the write is
    attempted. This ordering is the whole point: ``write_text`` can
    create the file and then raise partway through — disk exhaustion is
    the obvious case — and if registration happened after a successful
    write, that partial ``.regen-*`` file would be invisible to the
    cleanup loop and survive the rollback. The notes themselves were
    restored correctly, so the run looked clean while leaving debris in
    the published directory and reporting complete restoration.
    """
    snapshot: dict[Path, Optional[bytes]] = {
        path: (path.read_bytes() if path.is_file() else None)
        for path, _html in rendered
    }
    temps: list[Path] = []
    written: list[Path] = []
    try:
        for path, html in rendered:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.regen-{uuid.uuid4().hex[:8]}")
            # Register BEFORE writing: a partial file from a failed
            # write must still be reachable by cleanup.
            temps.append(tmp)
            tmp.write_text(html)
            tmp.replace(path)
            temps.remove(tmp)
            written.append(path)
        return written
    except Exception as exc:
        problems: list[str] = []

        for path, original in snapshot.items():
            try:
                if original is None:
                    if path.exists():
                        path.unlink()
                elif not path.is_file() or path.read_bytes() != original:
                    path.write_bytes(original)
            except OSError as cleanup_exc:
                problems.append(f"could not restore {path}: {cleanup_exc}")

        for tmp in temps:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError as cleanup_exc:
                problems.append(
                    f"could not remove temporary file {tmp}: {cleanup_exc}"
                )

        if problems:
            raise IncompleteRollbackError(exc, problems) from exc
        raise


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

    # --- preflight: validate and render EVERY selected release first ---
    #
    # A multi-period run used to write each note as it went, so an
    # invalid later period left earlier notes already rewritten. Nothing
    # is written until every selected release has passed.
    rendered: list[tuple[Path, str]] = []
    failures: list[str] = []
    all_warnings: list[str] = []
    for release in releases:
        try:
            path, html, warnings = render_one(release, outputs_dir)
        except (RegenerationError, FileNotFoundError, KeyError) as exc:
            failures.append(str(exc))
            continue
        rendered.append((path, html))
        all_warnings.extend(warnings)

    for warning in all_warnings:
        print(f"  WARNING {warning}", file=sys.stderr)

    if failures:
        print(
            f"error: {len(failures)} selected release(s) failed validation; "
            f"NO release note was written.",
            file=sys.stderr,
        )
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    if args.dry_run:
        for path, _html in rendered:
            print(f"  would write {path}")
        return 0

    try:
        written = _commit_notes(rendered)
    except IncompleteRollbackError as exc:
        print(
            f"error: writing release notes failed ({exc.original}), and the "
            f"rollback did NOT fully succeed. Inspect the release-note "
            f"directory before relying on it:",
            file=sys.stderr,
        )
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"error: writing release notes failed ({exc}); all notes were "
            f"restored to their pre-run state and no temporary file "
            f"remains.",
            file=sys.stderr,
        )
        return 1

    for path in written:
        print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
