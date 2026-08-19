#!/usr/bin/env python3
"""Pre-execution verification of the sealed Core-withdrawal inventory.

Every check here runs BEFORE any SSH connection is opened. The point is
that a destructive run must be impossible to start against an inventory
that is not the exact reviewed one.

The seal alone is not enough. A recomputing seal proves the file has not
been edited since it was sealed — it does not prove the file is the one a
human reviewed, that its contents are in scope, or that it is even
well-formed. So this module pins the file's own SHA-256 (identity), the
internal seal (integrity), the expected count and remote base (shape),
and then re-derives scope from the filenames rather than trusting that
Phase 1 got it right.

Anything that fails here fails closed, with a non-zero exit, before the
workflow has a key on disk.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

# The reviewed operation. These are constants, not parameters: a Phase-2
# run that can be pointed at a different inventory is not a reviewed
# operation.
EXPECTED_FILE_SHA256 = (
    "ce1e55939c2c10c04c18cb96b2457db802241f9bdfcdf484438f5250ba84e11c"
)
EXPECTED_INTEGRITY_SHA256 = (
    "3812991fa2ed52e4e3cfcc543c28c3f1769c20a3033c307abdb8085fd1887fd6"
)
EXPECTED_COUNT = 21
EXPECTED_TOTAL_BYTES = 63_598
EXPECTED_REMOTE_BASE = "/home/agiraces/dmianalysis"
EXPECTED_REMOTE_OUTPUTS = "/home/agiraces/dmianalysis/data/outputs"
EXPECTED_SCHEMA_VERSION = "1.0.0"
INVENTORY_PATH = "docs/repair/inventories/core-withdrawal-2026-08-19.json"

#: The only filename shapes a Core withdrawal may contain.
CORE_NAME_PATTERNS = (
    re.compile(r"^dmi_release_\d{4}-\d{2}_core\.json$"),
    re.compile(r"^dmi-\d{4}-\d{2}-core\.(csv|parquet)$"),
    re.compile(r"^qa_report_\d{4}-\d{2}_core\.json$"),
)

#: Substrings that must never appear in an inventoried path. Checked
#: independently of the positive match above, so a future pattern change
#: cannot quietly admit one of these.
FORBIDDEN_MARKERS = (
    "_u6", "_with_ci", "_slack_plus", "-baseline",
    "releases.json", "latest.json", "specifications.json",
    "health.json", "dmi_timeseries", "published/historical",
    "/releases/", "dashboard", "wp-content", "plugins",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class VerificationError(RuntimeError):
    """The inventory is not the reviewed one, or is not in scope."""


def _fail(problems: list[str], message: str) -> None:
    problems.append(message)


def verify(inventory_path: Path) -> tuple[list[str], dict]:
    """Run every pre-execution check. Returns ``(problems, report)``."""
    problems: list[str] = []
    report: dict = {"inventory_path": str(inventory_path)}

    # --- identity: is this the exact reviewed file? ---------------------
    if not inventory_path.is_file():
        return ([f"inventory file not found: {inventory_path}"], report)

    raw = inventory_path.read_bytes()
    file_sha = hashlib.sha256(raw).hexdigest()
    report["file_sha256"] = file_sha
    report["file_sha256_expected"] = EXPECTED_FILE_SHA256
    if file_sha != EXPECTED_FILE_SHA256:
        _fail(problems,
              f"inventory file SHA-256 is {file_sha}, expected "
              f"{EXPECTED_FILE_SHA256}. This is not the reviewed file.")
        # Everything below describes a file we have already rejected.
        return (problems, report)

    try:
        inv = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ([f"inventory is not valid JSON: {exc}"], report)

    # --- shape -----------------------------------------------------------
    report["schema_version"] = inv.get("schema_version")
    if inv.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        _fail(problems, f"schema_version is {inv.get('schema_version')!r}, "
                        f"expected {EXPECTED_SCHEMA_VERSION!r}")

    remote_base = inv.get("remote_base")
    remote_outputs = inv.get("remote_outputs")
    report["remote_base"] = remote_base
    report["remote_outputs"] = remote_outputs
    if remote_base != EXPECTED_REMOTE_BASE:
        _fail(problems, f"remote_base is {remote_base!r}, expected "
                        f"{EXPECTED_REMOTE_BASE!r}")
    if remote_outputs != EXPECTED_REMOTE_OUTPUTS:
        _fail(problems, f"remote_outputs is {remote_outputs!r}, expected "
                        f"{EXPECTED_REMOTE_OUTPUTS!r}")

    files = inv.get("files")
    if not isinstance(files, list):
        return (problems + ["inventory has no 'files' list"], report)

    report["file_count"] = len(files)
    if len(files) != EXPECTED_COUNT:
        _fail(problems, f"inventory lists {len(files)} file(s), expected "
                        f"{EXPECTED_COUNT}")

    # --- integrity: recompute the seal ----------------------------------
    from scripts.withdraw_remote_artifacts import _inventory_digest

    recorded = inv.get("integrity_sha256")
    report["integrity_sha256"] = recorded
    report["integrity_sha256_expected"] = EXPECTED_INTEGRITY_SHA256
    if recorded != EXPECTED_INTEGRITY_SHA256:
        _fail(problems, f"integrity_sha256 is {recorded!r}, expected "
                        f"{EXPECTED_INTEGRITY_SHA256!r}")
    if remote_base and remote_outputs:
        recomputed = _inventory_digest(remote_base, remote_outputs, files)
        report["integrity_sha256_recomputed"] = recomputed
        if recomputed != recorded:
            _fail(problems,
                  f"the seal does not recompute: recorded {recorded!r}, "
                  f"recomputed {recomputed!r}. The inventory was edited "
                  f"after sealing.")

    # --- per-entry checks -------------------------------------------------
    prefix = (remote_outputs or "") + "/"
    seen: set[str] = set()
    total = 0
    for index, record in enumerate(files):
        if not isinstance(record, dict):
            _fail(problems, f"entry {index} is not an object")
            continue
        path = record.get("path")
        size = record.get("size")
        digest = record.get("sha256")

        if not isinstance(path, str) or not path:
            _fail(problems, f"entry {index} has no usable path")
            continue

        if path in seen:
            _fail(problems, f"duplicate entry: {path}")
        seen.add(path)

        # direct child of the fixed outputs directory
        if not path.startswith(prefix):
            _fail(problems, f"path is outside {remote_outputs!r}: {path}")
            continue
        name = path[len(prefix):]
        if "/" in name:
            _fail(problems, f"path is not a direct child of the outputs "
                            f"directory (contains a separator): {path}")
            continue
        if not name or name in (".", ".."):
            _fail(problems, f"path resolves to a directory entry: {path}")
            continue

        # traversal / separators / whitespace
        if ".." in path or "//" in path or "\\" in path:
            _fail(problems, f"path contains traversal or unexpected "
                            f"separators: {path}")
        if path != path.strip() or any(c in path for c in "\n\r\t"):
            _fail(problems, f"path contains whitespace control characters: "
                            f"{path!r}")

        # positive Core match
        if not any(p.match(name) for p in CORE_NAME_PATTERNS):
            _fail(problems, f"filename does not match any Core artifact "
                            f"class: {name}")

        # forbidden classes, checked independently
        for marker in FORBIDDEN_MARKERS:
            if marker in path:
                _fail(problems, f"path contains a forbidden marker "
                                f"{marker!r}: {path}")

        # size
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            _fail(problems, f"size is not a nonnegative integer for {path}: "
                            f"{size!r}")
        else:
            total += size

        # digest
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            _fail(problems, f"sha256 is not a lowercase 64-char hex string "
                            f"for {path}: {digest!r}")

    report["unique_paths"] = len(seen)
    report["total_bytes"] = total
    report["total_bytes_expected"] = EXPECTED_TOTAL_BYTES
    if len(seen) != EXPECTED_COUNT:
        _fail(problems, f"{len(seen)} unique path(s), expected "
                        f"{EXPECTED_COUNT}")
    if total != EXPECTED_TOTAL_BYTES:
        _fail(problems, f"total size is {total}, expected "
                        f"{EXPECTED_TOTAL_BYTES}")

    # sorted order — Phase 1 sorts; a reordered file is an edited file
    paths = [r.get("path") for r in files if isinstance(r, dict)]
    if paths != sorted(paths):
        _fail(problems, "inventory entries are not in sorted path order")

    # --- resealing ------------------------------------------------------
    if "resealed_at_utc" in inv:
        _fail(problems, "inventory carries `resealed_at_utc`: it was pruned "
                        "and re-approved after review. This Phase-2 "
                        "operation is pinned to the original sealed set.")

    report["problems"] = problems
    report["verified"] = not problems
    return (problems, report)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # No --inventory flag: the path is fixed. A verifier that can be
    # pointed elsewhere verifies nothing about the reviewed operation.
    parser.add_argument(
        "--report", help="Write the verification report JSON here.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    problems, report = verify(repo_root / INVENTORY_PATH)

    print(f"inventory         : {INVENTORY_PATH}")
    print(f"file sha256       : {report.get('file_sha256')}")
    print(f"integrity seal    : {report.get('integrity_sha256')}")
    print(f"seal recomputed   : {report.get('integrity_sha256_recomputed')}")
    print(f"files             : {report.get('file_count')} "
          f"({report.get('unique_paths')} unique)")
    print(f"total bytes       : {report.get('total_bytes')}")
    print(f"remote base       : {report.get('remote_base')}")

    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"report written    : {args.report}")

    if problems:
        print(f"\nVERIFICATION FAILED — {len(problems)} problem(s); "
              f"no SSH connection will be opened:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("\nVERIFICATION PASSED — inventory is the exact reviewed set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
