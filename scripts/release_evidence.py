#!/usr/bin/env python3
"""Evidence-based artifact verification and manifest URL construction (§5).

Why this module exists
----------------------
Before this module there were two independent ways to decide what a
release manifest advertises:

- ``scripts/compute_dmi.py`` emitted a ``spec_urls`` block containing
  BOTH ``baseline`` and ``slack_plus`` entries unconditionally, as
  literal f-strings, with no check that either artifact existed;
- ``scripts/rebuild_release_manifests.py`` checked that the CSV existed
  on disk, but nothing more.

The first produces phantom URLs — manifest entries that 404 on the live
site. The second is existence-only: a truncated, mis-periodised, or
wrong-specification artifact still got advertised.

This module is the single authority. A specification URL may be emitted
only when the artifact clears all four evidence tests (§5):

1. **exists**            — the file is present on disk;
2. **parses**            — it is well-formed JSON;
3. **validates**         — it satisfies ``dmi_output.schema.json``;
4. **identifies itself** — its internal ``reference_period`` and
   ``specification`` match the manifest entry being written.

Test 4 is the one a filename cannot provide. ``dmi_release_2026-07.json``
is a claim made by whoever named the file; ``reference_period`` inside it
is a claim made by the code that computed it. Only the second is
evidence.

Legacy releases
---------------
Releases before 2026-03 predate the multi-spec contract. Their raw files
carry ``specification: null`` and their tabular exports use the
unsuffixed ``dmi-YYYY-MM.{csv,parquet}`` naming. Both are accepted for
the ``baseline`` specification and for those periods only, because that
is what actually exists — §9's rule that a manifest advertises only real
files applies to history as much as to the current period.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

#: The two operational specifications. Core is withdrawn (see
#: docs/repair/CORE_WITHDRAWAL.md) and can never appear here.
OPERATIONAL_SPECS = ("baseline", "slack_plus")

#: Periods from this release onward carry explicit specification
#: identity and suffixed tabular exports.
MULTI_SPEC_FROM = "2026-03"


class EvidenceError(RuntimeError):
    """A required artifact failed an evidence test."""


def raw_release_filename(release_id: str, spec: str) -> str:
    """Canonical raw-release filename for ``spec`` in ``release_id``."""
    if spec == "baseline":
        return f"dmi_release_{release_id}.json"
    if spec == "slack_plus":
        return f"dmi_release_{release_id}_slack_plus.json"
    raise EvidenceError(
        f"{spec!r} is not an operational specification; "
        f"expected one of {OPERATIONAL_SPECS}"
    )


def raw_release_url(release_id: str, spec: str) -> str:
    return f"/data/outputs/{raw_release_filename(release_id, spec)}"


def uses_legacy_naming(release_id: str) -> bool:
    """True for periods that predate the suffixed multi-spec naming."""
    return release_id < MULTI_SPEC_FROM


def tabular_stem(release_id: str, spec: str) -> str:
    """Filename stem for the CSV/Parquet exports of ``spec``.

    Pre-2026-03 Baseline exports are unsuffixed; everything else carries
    the specification suffix.
    """
    if spec == "baseline" and uses_legacy_naming(release_id):
        return f"dmi-{release_id}"
    if spec == "baseline":
        return f"dmi-{release_id}-baseline"
    if spec == "slack_plus":
        return f"dmi-{release_id}-slack_plus"
    raise EvidenceError(f"{spec!r} is not an operational specification")


def _validator():
    """Draft 2020-12 validator for ``dmi_output.schema.json``."""
    from jsonschema import Draft202012Validator

    schema = json.loads((SCHEMAS_DIR / "dmi_output.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def verify_raw_artifact(
    path: Path,
    release_id: str,
    spec: str,
) -> list[str]:
    """Run all four evidence tests. Returns a list of problems.

    An empty list means the artifact may be advertised. The list is
    ordered so the first entry is the earliest failure, because a parse
    failure makes the later checks meaningless.
    """
    problems: list[str] = []

    # 1. exists
    if not path.is_file():
        return [f"{spec}: artifact does not exist: {path}"]

    # 2. parses
    try:
        instance = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return [f"{spec}: artifact is not valid JSON ({path.name}): {exc}"]

    # 3. validates against the current schema
    errors = sorted(
        _validator().iter_errors(instance),
        key=lambda e: list(e.absolute_path),
    )
    for err in errors:
        problems.append(
            f"{spec}: {path.name} violates dmi_output.schema.json at "
            f"{list(err.absolute_path)}: {err.message}"
        )
    if problems:
        return problems

    # 4. identifies itself
    actual_period = instance.get("reference_period")
    if actual_period != release_id:
        problems.append(
            f"{spec}: {path.name} declares reference_period "
            f"{actual_period!r}, expected {release_id!r}"
        )

    declared = instance.get("specification")
    if spec == "baseline":
        # Legacy Baseline releases predate explicit spec identity.
        permitted = {"baseline", None} if uses_legacy_naming(release_id) \
            else {"baseline"}
    else:
        permitted = {"slack_plus"}
    if declared not in permitted:
        expected = " or ".join(sorted(repr(p) for p in permitted))
        problems.append(
            f"{spec}: {path.name} declares specification {declared!r}, "
            f"expected {expected}"
        )

    return problems


def artifact_is_publishable(
    output_dir: Path,
    release_id: str,
    spec: str,
) -> bool:
    """True iff the raw artifact for ``spec`` clears every evidence test."""
    path = output_dir / raw_release_filename(release_id, spec)
    return not verify_raw_artifact(path, release_id, spec)


def build_spec_urls(
    release_id: str,
    output_dir: Path,
    require: Iterable[str] = (),
) -> dict:
    """Build the evidence-based ``spec_urls`` block for a release entry.

    A specification appears only when its raw artifact passes every
    evidence test AND its tabular exports exist. ``require`` names
    specifications whose absence is a hard error rather than an omission
    — finalization passes both operational specs so the current release
    can never be published half-formed (§5).

    Under schema 3.0.0 no ``release_note`` key is nested here; the note
    is a top-level field on the release entry.
    """
    required = set(require)
    unknown = required - set(OPERATIONAL_SPECS)
    if unknown:
        raise EvidenceError(
            f"cannot require non-operational specification(s): "
            f"{sorted(unknown)}"
        )

    spec_urls: dict = {}
    failures: list[str] = []

    for spec in OPERATIONAL_SPECS:
        raw_path = output_dir / raw_release_filename(release_id, spec)
        problems = verify_raw_artifact(raw_path, release_id, spec)

        stem = tabular_stem(release_id, spec)
        missing_tabular = [
            f"{spec}: missing tabular export {stem}.{ext}"
            for ext in ("csv", "parquet")
            if not (output_dir / f"{stem}.{ext}").is_file()
        ]
        problems = problems + missing_tabular

        if problems:
            if spec in required:
                failures.extend(problems)
            continue

        spec_urls[spec] = {
            "csv": f"/data/outputs/{stem}.csv",
            "parquet": f"/data/outputs/{stem}.parquet",
        }

    if failures:
        raise EvidenceError(
            f"release {release_id} is missing required artifacts; refusing "
            f"to write a partial manifest entry:\n  - "
            + "\n  - ".join(failures)
        )

    return spec_urls


def release_note_url(release_id: str) -> str:
    """Canonical release-note URL (top-level field under schema 3.0.0)."""
    return f"/data/outputs/releases/{release_id}.html"
