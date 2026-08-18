#!/usr/bin/env python3
"""Inventory-only companion to ``scripts/withdraw_remote_artifacts.py``
(Round-3 §10; supersedes the retired ``scripts/withdraw_core_artifacts.sh``
this file previously named).

The remote withdrawal tool operates against the iFastNet site over SSH
and therefore cannot help an operator answer the offline question:
"What withdrawn-Core artifacts are still present in my local working
tree, and does the withdrawal record describe them accurately?"

This module answers that question with **zero side effects**. It never
deletes, moves, renames, or writes to any file; there is no
``--confirm`` flag, no mutating code path, and no network I/O. The tool
walks the local working tree, enumerates every path that matches the
withdrawn-artifact patterns, and prints them (plus a JSON summary if
requested). It exits ``0`` regardless of how many matches are found;
callers that need to fail a CI job on non-empty inventories can gate on
the JSON output themselves.

Patterns are reported in TWO separate authorization classes (Round-3
§10). Collapsing them into one "withdrawn" list was the original
defect, because it let U-6 and confidence-interval files be treated as
Core.

``CORE_PATTERNS`` — the withdrawn Core specification, eligible for the
remote Core-withdrawal procedure. Identical to
``scripts.withdraw_remote_artifacts.WITHDRAWN_PATTERNS``:

- ``dmi_release_*_core.json``
- ``dmi-*-core.csv``
- ``dmi-*-core.parquet``
- ``qa_report_*_core.json``

``LEGACY_NON_CORE_PATTERNS`` — pre-v0.1.12 artifacts that are NOT Core:

- ``dmi_release_*_u6.json``
- ``dmi_release_*_with_ci.json``

These are historical evidence. Local copies are quarantined under
``data/quarantine/pre_v0.1.12/`` rather than deleted, and their remote
disposition is explicitly OUTSIDE the Core-withdrawal authorization.
They are listed so an operator can see them, never so they can be
withdrawn as Core.

Excluded roots (never traversed): ``.git``, ``node_modules``,
``__pycache__``, ``.venv``, ``venv``, ``deploy`` — the last of these
because it is a machine-generated staging area that is expected to
contain mirrored copies during a build, and we only care about the
source tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path


# Round-3 §10 (classification correction). These two sets are kept
# SEPARATE because they carry different authorizations, and collapsing
# them was the original defect: a single "withdrawn" list let U-6 and
# confidence-interval files be treated as Core.
#
# CORE_PATTERNS — the withdrawn Core specification. Eligible for the
# remote Core-withdrawal procedure
# (``scripts.withdraw_remote_artifacts``). This set is deliberately
# identical to that tool's ``WITHDRAWN_PATTERNS``.
CORE_PATTERNS: tuple[str, ...] = (
    "dmi_release_*_core.json",
    "dmi-*-core.csv",
    "dmi-*-core.parquet",
    "qa_report_*_core.json",
)

# LEGACY_NON_CORE_PATTERNS — pre-v0.1.12 artifacts that are NOT Core.
# They are historical evidence of superseded methodology runs. Local
# copies are quarantined under ``data/quarantine/pre_v0.1.12/`` rather
# than deleted, and their remote disposition is OUTSIDE the
# Core-withdrawal authorization. They are reported here so an operator
# can see them, and labelled so nobody mistakes them for Core.
LEGACY_NON_CORE_PATTERNS: tuple[str, ...] = (
    "dmi_release_*_u6.json",
    "dmi_release_*_with_ci.json",
)

# Union, used only for "what should this scan look at".
WITHDRAWN_PATTERNS: tuple[str, ...] = (
    CORE_PATTERNS + LEGACY_NON_CORE_PATTERNS
)


def classify(name: str) -> str:
    """Return ``"core"``, ``"legacy_non_core"``, or ``"unmatched"``.

    The distinction is the whole point of this module: ``core`` files
    may be withdrawn remotely; ``legacy_non_core`` files may not.
    """
    if any(fnmatch.fnmatch(name, pat) for pat in CORE_PATTERNS):
        return "core"
    if any(fnmatch.fnmatch(name, pat) for pat in LEGACY_NON_CORE_PATTERNS):
        return "legacy_non_core"
    return "unmatched"


EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "deploy",
})


def iter_withdrawn_paths(root: Path) -> list[Path]:
    """Yield every file under ``root`` whose name matches a withdrawn pattern.

    Result is deterministically sorted so successive runs are comparable
    by diff.
    """
    matches: list[Path] = []
    root = root.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Cheap prefix check: skip anything under an excluded directory.
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts):
            continue
        name = path.name
        if any(fnmatch.fnmatch(name, pat) for pat in WITHDRAWN_PATTERNS):
            matches.append(path)
    matches.sort()
    return matches


def build_report(root: Path) -> dict:
    """Build a JSON-serialisable inventory report.

    Matches are split by authorization class so the report can never be
    read as "these are all Core". ``core`` entries are withdrawal-
    eligible; ``legacy_non_core`` entries are historical evidence whose
    remote disposition is outside the Core-withdrawal authorization.
    """
    resolved = root.resolve()
    matches = iter_withdrawn_paths(root)
    core: list[str] = []
    legacy: list[str] = []
    for path in matches:
        rel = str(path.relative_to(resolved))
        if classify(path.name) == "core":
            core.append(rel)
        else:
            legacy.append(rel)
    return {
        "root": str(resolved),
        "core_patterns": list(CORE_PATTERNS),
        "legacy_non_core_patterns": list(LEGACY_NON_CORE_PATTERNS),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
        "match_count": len(matches),
        "core_match_count": len(core),
        "legacy_non_core_match_count": len(legacy),
        "core_matches": core,
        "legacy_non_core_matches": legacy,
        # Preserved for consumers of the previous report shape.
        "matches": [str(p.relative_to(resolved)) for p in matches],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only inventory of local withdrawn-Core artifacts. "
            "Never deletes, moves, or writes any file."
        ),
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(),
        help="Directory to scan (default: current working directory).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit a JSON report instead of a plain file listing.",
    )
    args = parser.parse_args(argv)

    report = build_report(args.root)

    if args.json:
        json.dump(report, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")
    else:
        print(f"Inventory root: {report['root']}")
        print(f"Matches:        {report['match_count']}")
        print()
        print(
            f"Core (withdrawal-eligible): "
            f"{report['core_match_count']}"
        )
        for rel in report["core_matches"]:
            print(f"  {rel}")
        print()
        print(
            f"Pre-v0.1.12 legacy, NOT Core "
            f"(outside Core-withdrawal authorization): "
            f"{report['legacy_non_core_match_count']}"
        )
        for rel in report["legacy_non_core_matches"]:
            print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
