#!/usr/bin/env python3
"""Two-phase remote-withdrawal tool for retired DMI artifacts (§10).

Round-3 §10 established that the previous single-phase shell tool
(``scripts/withdraw_core_artifacts.sh``) had an unclosed safety gap:
enumeration and deletion happened inside the same SSH session, so a
human reviewer never had a chance to inspect (and if necessary prune)
the exact list of files that would be deleted before deletion occurred.
A remote file added after the operator started the run — for whatever
reason — could still be inside the delete set.

This module replaces that design with an explicit two-phase workflow:

  Phase 1 — ``inventory``. Read-only SSH enumeration. For every file
  under ``$DMI_REMOTE_BASE/data/outputs`` whose name matches a
  withdrawn-artifact pattern, records its remote path, size, and
  SHA-256. Refuses to include anything whose name matches a Baseline
  or Slack-Plus pattern. Writes a JSON inventory file to a local
  path the operator can review, diff, and prune before phase 2.

  Phase 2 — ``execute``. Reads the reviewed inventory file. For every
  entry: re-runs ``sha256sum`` on the remote and verifies the digest
  still matches what phase 1 recorded. If ALL digests match, runs
  ``rm --`` for each recorded path (batched, but only after full
  verification). If ANY digest mismatches, or any inventory path is
  outside ``$DMI_REMOTE_BASE`` / matches a protected pattern, the
  entire run is aborted with a non-zero exit and no deletions occur.

The hash verification defeats the race-condition failure mode where a
file's content on the remote changed between phase-1 review and
phase-2 execution: phase 2 will refuse to delete a file whose bytes
no longer match the reviewed inventory.

Environment (both phases):
  DMI_REMOTE_HOST   iFastNet SSH host
  DMI_REMOTE_USER   iFastNet SSH user
  DMI_REMOTE_PORT   SSH port (defaults to 1394)
  DMI_REMOTE_KEY    Path to private SSH key
  DMI_REMOTE_BASE   Remote base path (defaults to /home/agiraces/dmianalysis)
  DMI_KNOWN_HOSTS   Path to known_hosts file (defaults to ~/.ssh/known_hosts)

Usage:
  python -m scripts.withdraw_remote_artifacts inventory \\
      --output withdrawal-inventory.json
  # ... review withdrawal-inventory.json manually, optionally prune ...
  python -m scripts.withdraw_remote_artifacts execute \\
      --inventory withdrawal-inventory.json --confirm
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Filename patterns that identify withdrawn artifacts. Kept identical
# to the historical shell tool's `FIND_EXPR` for consumer parity.
WITHDRAWN_PATTERNS: tuple[str, ...] = (
    "dmi_release_*_core.json",
    "dmi_release_*_u6.json",
    "dmi_release_*_with_ci.json",
    "dmi-*-core.csv",
    "dmi-*-core.parquet",
)

# Filename regexes that MUST NEVER appear in an inventory. If any of
# these match, phase 1 aborts (refuses to write the inventory) and
# phase 2 aborts (refuses to delete). Belt-and-suspenders defence
# against a future pattern regression that would otherwise wipe
# published outputs.
PROTECTED_REGEXES: tuple[str, ...] = (
    r"^dmi_release_[0-9]{4}-[0-9]{2}\.json$",
    r"^dmi_release_[0-9]{4}-[0-9]{2}_slack_plus\.json$",
    r"^dmi-[0-9]{4}-[0-9]{2}-baseline\.(csv|parquet)$",
    r"^dmi-[0-9]{4}-[0-9]{2}-slack_plus\.(csv|parquet)$",
    r"^dmi-[0-9]{4}-[0-9]{2}\.(csv|parquet)$",
)


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    """Fetch an env var with clear error reporting."""
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise SystemExit(f"ERROR: {name} must be set")
    return value or ""


def _ensure_known_hosts(host: str, port: str, known_hosts: Path) -> None:
    """Ensure ``host`` is pinned in ``known_hosts``; keyscan if not.

    An ``ssh-keyscan`` failure is fatal (no ``|| true``). This matches
    the §3 policy: strict host verification is mandatory.
    """
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    if not known_hosts.exists():
        known_hosts.touch(mode=0o600)
    else:
        known_hosts.chmod(0o600)

    def _pinned(target: str) -> bool:
        return subprocess.run(
            ["ssh-keygen", "-F", target, "-f", str(known_hosts)],
            capture_output=True,
        ).returncode == 0

    if _pinned(f"[{host}]:{port}") or _pinned(host):
        return

    print(
        f"Host {host}:{port} not in {known_hosts}; pinning via ssh-keyscan ...",
        file=sys.stderr,
    )
    keyscan = subprocess.run(
        ["ssh-keyscan", "-p", port, host],
        capture_output=True, text=True,
    )
    if keyscan.returncode != 0 or not keyscan.stdout.strip():
        raise SystemExit(
            f"ERROR: ssh-keyscan failed for {host}:{port} "
            f"(rc={keyscan.returncode}): {keyscan.stderr.strip()}"
        )
    with known_hosts.open("a") as f:
        f.write(keyscan.stdout)


def _ssh_command(
    host: str, user: str, port: str, key: Path, known_hosts: Path,
) -> list[str]:
    """Build the base SSH argv with strict host verification."""
    if not key.is_file():
        raise SystemExit(f"ERROR: SSH key not found at {key}")
    return [
        "ssh",
        "-i", str(key),
        "-p", port,
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={known_hosts}",
        f"{user}@{host}",
    ]


def _load_ssh_config() -> tuple[list[str], str]:
    """Load and validate SSH config from env; return (ssh_argv, remote_base)."""
    host = _env("DMI_REMOTE_HOST", required=True)
    user = _env("DMI_REMOTE_USER", required=True)
    port = _env("DMI_REMOTE_PORT", default="1394")
    key = Path(_env("DMI_REMOTE_KEY", required=True))
    base = _env("DMI_REMOTE_BASE", default="/home/agiraces/dmianalysis")
    known_hosts = Path(
        _env(
            "DMI_KNOWN_HOSTS",
            default=str(Path.home() / ".ssh" / "known_hosts"),
        )
    )
    _ensure_known_hosts(host, port, known_hosts)
    ssh_argv = _ssh_command(host, user, port, key, known_hosts)
    return ssh_argv, base


def _remote_find_and_hash(ssh_argv: list[str], remote_outputs: str) -> list[dict]:
    """Enumerate + hash matching files under ``remote_outputs`` in one SSH call.

    Returns a list of ``{"path": str, "size": int, "sha256": str}`` records,
    sorted by path. Uses a single remote script so the number of SSH
    round-trips is O(1) regardless of match count.
    """
    # Build a portable find expression from WITHDRAWN_PATTERNS.
    name_clauses = " -o ".join(
        f"-name {shlex.quote(p)}" for p in WITHDRAWN_PATTERNS
    )
    # For each match, emit "<sha256>  <size>  <path>". We use
    # `sha256sum` (coreutils) which is present on iFastNet. The remote
    # script is kept small and quoted safely with shlex.
    remote_script = (
        f"set -eu; "
        f"find {shlex.quote(remote_outputs)} -maxdepth 1 -type f "
        f"\\( {name_clauses} \\) -print0 "
        f"| while IFS= read -r -d '' f; do "
        f"  sz=$(wc -c < \"$f\"); "
        f"  hash=$(sha256sum \"$f\" | awk '{{print $1}}'); "
        f"  printf '%s\\t%s\\t%s\\n' \"$hash\" \"$sz\" \"$f\"; "
        f"done"
    )
    proc = subprocess.run(
        [*ssh_argv, remote_script],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: remote enumeration failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    records: list[dict] = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            raise SystemExit(
                f"ERROR: unparseable remote-enumeration line: {line!r}"
            )
        sha256, size_s, path = parts
        try:
            size = int(size_s)
        except ValueError:
            raise SystemExit(
                f"ERROR: non-integer size in remote record: {line!r}"
            )
        records.append({"path": path, "size": size, "sha256": sha256})
    records.sort(key=lambda r: r["path"])
    return records


def _refuse_protected(records: list[dict], remote_base: str) -> None:
    """Fail if any record's basename matches a protected pattern or
    escapes ``remote_base``.
    """
    protected = [re.compile(p) for p in PROTECTED_REGEXES]
    offenders: list[str] = []
    for rec in records:
        path = rec["path"]
        if not path.startswith(remote_base.rstrip("/") + "/"):
            offenders.append(f"outside remote_base: {path}")
            continue
        name = path.rsplit("/", 1)[-1]
        if any(rx.match(name) for rx in protected):
            offenders.append(f"matches protected pattern: {path}")
    if offenders:
        msg = "\n  ".join(offenders)
        raise SystemExit(
            "ERROR: inventory contains protected or out-of-scope paths:\n  "
            + msg
        )


def cmd_inventory(args: argparse.Namespace) -> int:
    """Phase 1: enumerate + hash withdrawn artifacts into a reviewed inventory."""
    output_path = Path(args.output)
    if output_path.exists() and not args.overwrite:
        raise SystemExit(
            f"ERROR: {output_path} already exists; pass --overwrite to replace."
        )

    ssh_argv, remote_base = _load_ssh_config()
    remote_outputs = f"{remote_base.rstrip('/')}/data/outputs"

    print(f"Enumerating withdrawn artifacts under {remote_outputs} ...",
          file=sys.stderr)
    records = _remote_find_and_hash(ssh_argv, remote_outputs)
    print(f"Matched {len(records)} file(s).", file=sys.stderr)

    # Fail closed if any protected pattern slipped in.
    _refuse_protected(records, remote_base)

    inventory = {
        "schema_version": "1.0.0",
        "generated_at_utc": datetime.utcnow().isoformat() + "Z",
        "remote_base": remote_base,
        "remote_outputs": remote_outputs,
        "patterns": list(WITHDRAWN_PATTERNS),
        "protected_patterns": list(PROTECTED_REGEXES),
        "files": records,
    }
    # Write via temp-sibling-then-rename so a crash mid-write can't
    # leave a partial inventory behind.
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    tmp_path.write_text(json.dumps(inventory, indent=2) + "\n")
    tmp_path.replace(output_path)
    print(
        f"Wrote reviewed-inventory candidate to {output_path}\n"
        f"REVIEW the file (optionally prune entries), then run:\n"
        f"  python -m scripts.withdraw_remote_artifacts execute "
        f"--inventory {output_path} --confirm",
        file=sys.stderr,
    )
    return 0


def _remote_rehash(ssh_argv: list[str], paths: list[str]) -> dict[str, str]:
    """Re-hash a list of remote paths in one SSH call. Returns {path: sha256}."""
    if not paths:
        return {}
    # Ship the paths as newline-separated stdin so we don't blow the
    # argv size limit on large inventories, and we quote nothing on
    # the client side (the remote reads via `read`).
    remote_script = (
        "set -eu; "
        "while IFS= read -r f; do "
        "  h=$(sha256sum \"$f\" | awk '{print $1}'); "
        "  printf '%s\\t%s\\n' \"$h\" \"$f\"; "
        "done"
    )
    stdin_blob = "\n".join(paths) + "\n"
    proc = subprocess.run(
        [*ssh_argv, remote_script],
        input=stdin_blob, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: remote re-hash failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    result: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            raise SystemExit(
                f"ERROR: unparseable remote re-hash line: {line!r}"
            )
        sha, path = parts
        result[path] = sha
    return result


def _remote_delete(ssh_argv: list[str], paths: list[str]) -> None:
    """Delete a list of remote paths in one SSH call.

    Uses `rm -- <path>` (no `-r`, no `-f`, one path per invocation)
    driven by a while-read loop over stdin. `set -e` ensures we abort
    on the first failure and non-zero exits are propagated.
    """
    if not paths:
        return
    remote_script = (
        "set -eu; "
        "while IFS= read -r f; do "
        "  rm -- \"$f\"; "
        "  printf 'removed %s\\n' \"$f\"; "
        "done"
    )
    stdin_blob = "\n".join(paths) + "\n"
    proc = subprocess.run(
        [*ssh_argv, remote_script],
        input=stdin_blob, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: remote deletion failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    sys.stdout.write(proc.stdout)


def cmd_execute(args: argparse.Namespace) -> int:
    """Phase 2: verify hashes then delete files listed in reviewed inventory."""
    inventory_path = Path(args.inventory)
    if not inventory_path.is_file():
        raise SystemExit(f"ERROR: inventory not found: {inventory_path}")
    inventory = json.loads(inventory_path.read_text())

    files = inventory.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("ERROR: inventory has no 'files' list")
    if not files:
        print("Inventory is empty; nothing to withdraw.", file=sys.stderr)
        return 0

    # Fail fast on the --confirm gate BEFORE any network or filesystem
    # side effect. This means a user who forgot the flag gets immediate
    # feedback without triggering an ssh-keyscan of the remote host.
    if not args.confirm:
        raise SystemExit(
            "ERROR: execute requires --confirm (per §10 review gate). "
            "No files were touched."
        )

    ssh_argv, remote_base_env = _load_ssh_config()

    # Prefer the inventory's own recorded remote_base; require it to
    # match the environment's DMI_REMOTE_BASE so an operator can't
    # accidentally point phase 2 at a different host tree than phase 1
    # was recorded against.
    inv_base = inventory.get("remote_base")
    if inv_base and inv_base != remote_base_env:
        raise SystemExit(
            f"ERROR: inventory remote_base ({inv_base!r}) does not match "
            f"DMI_REMOTE_BASE ({remote_base_env!r}); refusing to execute."
        )
    remote_base = inv_base or remote_base_env

    # Fail closed if any inventory entry violates the safety invariants.
    _refuse_protected(files, remote_base)

    paths = [rec["path"] for rec in files]
    print(f"Re-hashing {len(paths)} file(s) on remote ...", file=sys.stderr)
    current = _remote_rehash(ssh_argv, paths)

    mismatches: list[str] = []
    missing: list[str] = []
    for rec in files:
        path = rec["path"]
        expected = rec["sha256"]
        actual = current.get(path)
        if actual is None:
            missing.append(path)
        elif actual != expected:
            mismatches.append(
                f"{path}: expected {expected}, got {actual}"
            )

    if missing or mismatches:
        parts: list[str] = []
        if missing:
            parts.append(
                "  missing on remote (deleted since inventory?):\n    "
                + "\n    ".join(missing)
            )
        if mismatches:
            parts.append(
                "  sha256 mismatch (content changed since inventory?):\n    "
                + "\n    ".join(mismatches)
            )
        raise SystemExit(
            "ERROR: inventory verification failed; refusing to delete "
            "anything.\n" + "\n".join(parts)
        )

    print(
        f"All {len(paths)} sha256 digests verified; proceeding with deletion.",
        file=sys.stderr,
    )
    _remote_delete(ssh_argv, paths)
    print(
        f"Withdrawal complete. Run the verification block in "
        f"docs/repair/REMOTE_WITHDRAWAL.md.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Two-phase remote-withdrawal tool for retired DMI artifacts (§10).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inv = sub.add_parser(
        "inventory",
        help="Phase 1: enumerate + hash withdrawn artifacts into a reviewed inventory.",
    )
    p_inv.add_argument(
        "--output", required=True,
        help="Local path to write the reviewed-inventory JSON.",
    )
    p_inv.add_argument(
        "--overwrite", action="store_true",
        help="Allow overwriting an existing inventory file.",
    )
    p_inv.set_defaults(func=cmd_inventory)

    p_exec = sub.add_parser(
        "execute",
        help="Phase 2: verify sha256 then delete files listed in reviewed inventory.",
    )
    p_exec.add_argument(
        "--inventory", required=True,
        help="Path to the reviewed inventory JSON produced by phase 1.",
    )
    p_exec.add_argument(
        "--confirm", action="store_true",
        help=(
            "Required. Without it, execute is a no-op that fails closed. "
            "Presence signals the operator has reviewed the inventory."
        ),
    )
    p_exec.set_defaults(func=cmd_execute)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
