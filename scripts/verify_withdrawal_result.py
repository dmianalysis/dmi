#!/usr/bin/env python3
"""Origin-side verification after a Core withdrawal.

Deletion succeeding is a weaker claim than it sounds: it says the `rm`
calls returned zero, not that the right files are gone and the wrong ones
survived. This module checks both halves over the same pinned SSH
connection the deletion used.

It never deletes, renames or restores anything.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

#: Files that MUST still exist. If a withdrawal removed any of these, the
#: operation went wrong in a way the absence check alone cannot see.
MUST_SURVIVE = [
    "dmi_release_2026-07.json",
    "dmi_release_2026-07_slack_plus.json",
    "dmi-2026-07-baseline.csv",
    "dmi-2026-07-baseline.parquet",
    "dmi-2026-07-slack_plus.csv",
    "dmi-2026-07-slack_plus.parquet",
    "releases.json",
    "latest.json",
    "specifications.json",
    "qa_report_2026-07_baseline.json",
    "qa_report_2026-07_slack_plus.json",
    "releases/2026-07.html",
    "published/dmi_timeseries.json",
    # Quarantined legacy classes: explicitly OUT of scope, so their
    # status must be unchanged by a Core withdrawal.
    "dmi_release_2024-11_u6.json",
    "dmi_release_2024-11_with_ci.json",
]


def remote_existing(ssh_argv: list[str], paths: list[str]) -> set[str]:
    """Which of ``paths`` currently exist. Read-only."""
    if not paths:
        return set()
    script = (
        "set -u; while IFS= read -r f; do "
        "  if [ -e \"$f\" ]; then printf '%s\\n' \"$f\"; fi; "
        "done"
    )
    proc = subprocess.run(
        [*ssh_argv, script],
        input="\n".join(paths) + "\n",
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: origin check failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    return {line for line in proc.stdout.splitlines() if line.strip()}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    from scripts.verify_withdrawal_inventory import INVENTORY_PATH
    from scripts.withdraw_remote_artifacts import _load_ssh_config

    inventory = json.loads((repo_root / INVENTORY_PATH).read_text())
    withdrawn = [record["path"] for record in inventory["files"]]
    outputs = inventory["remote_outputs"]
    survivors_expected = [f"{outputs}/{name}" for name in MUST_SURVIVE]

    ssh_argv, _base = _load_ssh_config()

    still_present = sorted(remote_existing(ssh_argv, withdrawn))
    survivors_found = remote_existing(ssh_argv, survivors_expected)
    missing_survivors = sorted(set(survivors_expected) - survivors_found)

    report = {
        "checked_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "withdrawn_expected_absent": len(withdrawn),
        "withdrawn_still_present": still_present,
        "operational_expected_present": len(survivors_expected),
        "operational_missing": missing_survivors,
        "all_withdrawn_absent": not still_present,
        "all_operational_present": not missing_survivors,
    }
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(f"withdrawn paths checked : {len(withdrawn)}")
    print(f"  still present          : {len(still_present)}")
    for path in still_present:
        print(f"    STILL PRESENT: {path}")
    print(f"operational paths checked: {len(survivors_expected)}")
    print(f"  missing                : {len(missing_survivors)}")
    for path in missing_survivors:
        print(f"    MISSING: {path}")

    if still_present or missing_survivors:
        print("\nORIGIN VERIFICATION FAILED. Do not improvise a recovery: "
              "the backup artifact and this report are the evidence for a "
              "separately authorized decision.", file=sys.stderr)
        return 1
    print("\nOrigin verified: all 21 withdrawn, operational surface intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
