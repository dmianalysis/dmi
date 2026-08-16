#!/usr/bin/env python3
"""Inventory-only companion to ``scripts/withdraw_core_artifacts.sh`` (§10).

The shell withdrawal tool operates against the remote iFastNet site over
SSH and therefore cannot help an operator answer the offline question:
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

Patterns matched (identical to the remote script's ``FIND_EXPR``):

- ``dmi_release_*_core.json``
- ``dmi_release_*_u6.json``
- ``dmi_release_*_with_ci.json``
- ``dmi-*-core.csv``
- ``dmi-*-core.parquet``
- ``qa_report_*_core.json``  (documented in
  ``docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`` §1 but omitted from
  the remote script because QA reports are not deployed)

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


WITHDRAWN_PATTERNS: tuple[str, ...] = (
    "dmi_release_*_core.json",
    "dmi_release_*_u6.json",
    "dmi_release_*_with_ci.json",
    "dmi-*-core.csv",
    "dmi-*-core.parquet",
    "qa_report_*_core.json",
)


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
    """Build a JSON-serialisable inventory report."""
    matches = iter_withdrawn_paths(root)
    return {
        "root": str(root.resolve()),
        "patterns": list(WITHDRAWN_PATTERNS),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
        "match_count": len(matches),
        "matches": [str(p.relative_to(root.resolve())) for p in matches],
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
        print(f"Patterns:       {', '.join(report['patterns'])}")
        print(f"Matches:        {report['match_count']}")
        for rel in report["matches"]:
            print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
