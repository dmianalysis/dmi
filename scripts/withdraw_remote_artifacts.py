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
  under ``$DMI_REMOTE_BASE/data/outputs`` whose name matches a Core
  artifact pattern, records its remote path, size, and SHA-256. The
  resulting set is checked against the scope rules (see below) and
  sealed with an ``integrity_sha256`` over the exact reviewed
  decision. Writes a JSON inventory file to a local path the operator
  can review, diff, and prune before phase 2. Performs NO deletion.

  Phase 2 — ``execute``. Requires ``--confirm``. Reads the reviewed
  inventory file and consumes it EXACTLY: it never re-runs ``find`` to
  discover targets, so a file that appeared on the remote after review
  cannot enter the delete set. It validates the inventory's integrity
  hash, re-validates every path against the scope rules, re-runs
  ``sha256sum`` on the remote and verifies each digest still matches.
  Only if every check passes does it run ``rm --`` for each recorded
  path. Afterwards it verifies that every inventoried path is actually
  absent, and fails if any survived.

  ``reseal`` — local, read-only helper that re-approves a manually
  pruned inventory by recomputing its integrity hash. Never contacts
  the remote; never deletes.

The hash verification defeats two distinct failure modes: content
drift (a file's bytes changed between review and execution) and
inventory tampering (the reviewed list itself was edited).

Scope (Round-3 §10). The Core-withdrawal inventory may contain ONLY
``dmi_release_*_core.json``, ``dmi-*-core.csv``, ``dmi-*-core.parquet``
and ``qa_report_*_core.json``. Enforcement is threefold and fails
closed: protected Baseline/Slack-Plus/manifest/release-note names are
refused, non-Core legacy names (``_u6``, ``_with_ci``) are refused, and
every remaining name must POSITIVELY match a Core pattern.

``_u6`` and ``_with_ci`` files are NOT Core. They are pre-v0.1.12
legacy artifacts retained as historical evidence (quarantined locally
under ``data/quarantine/pre_v0.1.12/``), and their remote disposition
is outside this tool's authorization.

Environment (both phases):
  DMI_REMOTE_HOST   iFastNet SSH host
  DMI_REMOTE_USER   iFastNet SSH user
  DMI_REMOTE_PORT   SSH port (defaults to 1394)
  DMI_REMOTE_KEY    Path to private SSH key
  DMI_REMOTE_BASE   Remote base path (defaults to /home/agiraces/dmianalysis)
  DMI_KNOWN_HOSTS   Path to the pinned known_hosts file
                    (defaults to ~/.ssh/known_hosts)
  DMI_KNOWN_HOSTS_DATA  Literal pinned known_hosts content (preferred).
                    REQUIRED unless DMI_KNOWN_HOSTS already holds a
                    pinned entry for the configured host and port.
                    There is no ssh-keyscan fallback: this tool
                    deletes remote files and must not be where trust
                    is first established.
  DMI_HOST_FINGERPRINT  Pinned SHA-256 host-key fingerprint (weaker
                    alternative; also needs DMI_ALLOW_FINGERPRINT_SCAN=1)

Usage:
  python -m scripts.withdraw_remote_artifacts inventory \\
      --output withdrawal-inventory.json
  # ... review withdrawal-inventory.json manually, optionally prune ...
  python -m scripts.withdraw_remote_artifacts execute \\
      --inventory withdrawal-inventory.json --confirm
  # if entries were pruned during review, re-approve first:
  python -m scripts.withdraw_remote_artifacts reseal \\
      --inventory withdrawal-inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Filename patterns that identify CORE artifacts eligible for remote
# withdrawal.
#
# Round-3 §10 (scope correction). An earlier revision of this tool kept
# these patterns "identical to the historical shell tool's `FIND_EXPR`
# for consumer parity". That parity was itself the defect: the shell
# tool classified `_u6.json` and `_with_ci.json` as Core, and omitted
# `qa_report_*_core.json` entirely. Both errors are corrected here.
#
# The controlling decision for this repair is that the Core-withdrawal
# inventory may contain ONLY Core artifacts:
#
#   - dmi_release_*_core.json
#   - dmi-*-core.csv
#   - dmi-*-core.parquet
#   - qa_report_*_core.json
#
# `_u6` and `_with_ci` are pre-v0.1.12 LEGACY artifacts, not Core. They
# are historical evidence of superseded methodology runs, their remote
# disposition is explicitly OUTSIDE this tool's authorization, and the
# local copies are quarantined (not deleted) under
# `data/quarantine/pre_v0.1.12/`. Deleting them through the Core
# procedure would destroy evidence under a false classification, so
# they are refused by `NON_CORE_REGEXES` below rather than merely
# omitted from the match patterns.
WITHDRAWN_PATTERNS: tuple[str, ...] = (
    "dmi_release_*_core.json",
    "dmi-*-core.csv",
    "dmi-*-core.parquet",
    "qa_report_*_core.json",
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
    # Manifests and release notes are never Core artifacts.
    r"^releases\.json$",
    r"^latest\.json$",
    r"^specifications\.json$",
    r"^health\.json$",
    r"^[0-9]{4}-[0-9]{2}\.html$",
)


# Round-3 §10. Names that are explicitly NOT Core and whose remote
# disposition is outside this tool's authorization. These are refused
# even if some future pattern regression were to match them, so the
# misclassification that the historical shell tool shipped cannot
# recur silently.
#
# `_u6` and `_with_ci` are pre-v0.1.12 legacy artifacts (see
# `data/quarantine/pre_v0.1.12/README.md`). They are historical
# evidence, they are not Core, and this tool must never delete them.
NON_CORE_REGEXES: tuple[str, ...] = (
    r"_u6\.(json|csv|parquet)$",
    r"_with_ci\.(json|csv|parquet)$",
)


# Round-3 §10. Positive allow-list: every inventoried basename MUST
# match one of these. An omission-based scope (only pruning the match
# patterns) fails open — anything the remote `find` happens to return
# would be deleted. This allow-list makes the scope fail CLOSED: a
# manifest, a release note, a historical directory entry, or any other
# unexpected name is refused because it does not positively match.
CORE_NAME_REGEXES: tuple[str, ...] = (
    r"^dmi_release_[0-9]{4}-[0-9]{2}_core\.json$",
    r"^dmi-[0-9]{4}-[0-9]{2}-core\.(csv|parquet)$",
    r"^qa_report_[0-9]{4}-[0-9]{2}_core\.json$",
)


def _env(name: str, default: str | None = None, required: bool = False) -> str:
    """Fetch an env var with clear error reporting."""
    value = os.environ.get(name, default)
    if required and (value is None or value == ""):
        raise SystemExit(f"ERROR: {name} must be set")
    return value or ""


def _ensure_known_hosts(host: str, port: str, known_hosts: Path) -> None:
    """Install PINNED host material; never acquire trust dynamically (§3).

    An earlier version ran ``ssh-keyscan`` when the host was not already
    in ``known_hosts`` and treated a non-empty result as trustworthy.
    That is trust-on-first-use: ``ssh-keyscan`` asks whoever answers the
    connection to introduce itself and believes the reply, so an
    intercepting party simply answers and their key becomes the pinned
    one. ``StrictHostKeyChecking=yes`` then verifies the session against
    the attacker's key, faithfully.

    This is a DESTRUCTIVE tool — it deletes files on the remote — so it
    must not be the place where trust is established. The expected key is
    supplied out of band through ``DMI_KNOWN_HOSTS_DATA`` (preferred) or
    a pinned fingerprint, and validated against the configured host and
    port before use.
    """
    from scripts.install_known_hosts import HostPinError, install

    if known_hosts.is_file() and known_hosts.stat().st_size > 0:
        # An operator-managed pinned file already exists; verify it names
        # the host we are about to contact rather than assuming it does.
        from scripts.install_known_hosts import (
            parse_known_hosts,
            validate_hosts_match,
        )
        try:
            entries = parse_known_hosts(known_hosts.read_text())
            validate_hosts_match(entries, host, port)
        except HostPinError as exc:
            raise SystemExit(
                f"ERROR: existing {known_hosts} is not usable for "
                f"{host}:{port}: {exc}"
            )
        return

    try:
        install(
            host=host,
            port=port,
            known_hosts=known_hosts,
            known_hosts_data=os.environ.get("DMI_KNOWN_HOSTS_DATA"),
            fingerprint=os.environ.get("DMI_HOST_FINGERPRINT"),
            allow_fingerprint_scan=(
                os.environ.get("DMI_ALLOW_FINGERPRINT_SCAN") == "1"
            ),
        )
    except HostPinError as exc:
        raise SystemExit(
            f"ERROR: cannot establish pinned host authentication for "
            f"{host}:{port}: {exc}"
        )


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
        # Offer ONLY the deployment identity. Without this, ssh also
        # presents every key in the agent and every default identity it
        # finds, so an unrelated key could authenticate a destructive
        # run and the audit trail would name the wrong credential.
        "-o", "IdentitiesOnly=yes",
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


def _inventory_digest(
    remote_base: str, remote_outputs: str, files: list[dict],
) -> str:
    """Integrity hash over the reviewed part of an inventory (§10).

    Covers the remote base, the enumerated directory, and the exact
    ``(path, size, sha256)`` triple of every entry — i.e. precisely
    what a reviewer approves. Excludes ``generated_at_utc`` and the
    pattern lists so that the digest identifies the DECISION, not the
    run that produced it.

    Phase 2 recomputes this and refuses to execute on a mismatch, so
    an inventory edited after review cannot be consumed silently. A
    reviewer who legitimately prunes entries re-approves the result
    with the ``reseal`` subcommand, which is a local, read-only
    operation against the file.
    """
    payload = {
        "remote_base": remote_base,
        "remote_outputs": remote_outputs,
        "files": [
            {
                "path": f["path"],
                "size": f["size"],
                "sha256": f["sha256"],
            }
            for f in files
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _refuse_protected(records: list[dict], remote_base: str) -> None:
    """Enforce the Core-withdrawal inventory scope (Round-3 §10).

    Every record must satisfy ALL of:

    1. its path lies under ``remote_base``;
    2. its basename does NOT match a protected Baseline/Slack-Plus/
       manifest/release-note pattern;
    3. its basename does NOT match a non-Core legacy pattern
       (``_u6`` / ``_with_ci``) — these are historical evidence whose
       remote disposition is outside this tool's authorization;
    4. its basename DOES positively match a Core name pattern.

    Condition 4 is what makes the scope fail closed. Relying only on
    the remote ``find`` expression would fail open: any name the remote
    returned would be trusted. Both phases call this function, so an
    inventory that was hand-edited between review and execution is
    rejected on the same rules that produced it.
    """
    protected = [re.compile(p) for p in PROTECTED_REGEXES]
    non_core = [re.compile(p) for p in NON_CORE_REGEXES]
    core_names = [re.compile(p) for p in CORE_NAME_REGEXES]
    offenders: list[str] = []
    for rec in records:
        path = rec["path"]
        if not path.startswith(remote_base.rstrip("/") + "/"):
            offenders.append(f"outside remote_base: {path}")
            continue
        name = path.rsplit("/", 1)[-1]
        if any(rx.match(name) for rx in protected):
            offenders.append(f"matches protected pattern: {path}")
            continue
        if any(rx.search(name) for rx in non_core):
            offenders.append(
                f"not Core (pre-v0.1.12 legacy; outside this tool's "
                f"authorization): {path}"
            )
            continue
        if not any(rx.match(name) for rx in core_names):
            offenders.append(
                f"does not match any Core artifact pattern: {path}"
            )
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
        "non_core_patterns": list(NON_CORE_REGEXES),
        "core_name_patterns": list(CORE_NAME_REGEXES),
        "files": records,
        # §10: integrity hash over the reviewed decision. Phase 2
        # validates this before deleting anything.
        "integrity_sha256": _inventory_digest(
            remote_base, remote_outputs, records
        ),
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


def _remote_existing(ssh_argv: list[str], paths: list[str]) -> list[str]:
    """Return the subset of ``paths`` that still exist on the remote.

    Used for post-deletion verification (§10). Prints one line per
    surviving path; an empty result means every inventoried path is
    gone.
    """
    if not paths:
        return []
    remote_script = (
        "set -u; "
        "while IFS= read -r f; do "
        "  if [ -e \"$f\" ]; then printf '%s\\n' \"$f\"; fi; "
        "done"
    )
    stdin_blob = "\n".join(paths) + "\n"
    proc = subprocess.run(
        [*ssh_argv, remote_script],
        input=stdin_blob, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(
            f"ERROR: post-deletion verification could not run "
            f"(rc={proc.returncode}): {proc.stderr.strip()}"
        )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


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

    # §10: validate the inventory's integrity hash BEFORE anything
    # else. This is what makes phase 2 consume the EXACT reviewed
    # inventory: if a single path, size, or digest was edited after
    # review, the recomputed hash differs and we refuse.
    recorded_digest = inventory.get("integrity_sha256")
    if not recorded_digest:
        raise SystemExit(
            "ERROR: inventory has no 'integrity_sha256'. It was produced "
            "by an older tool version or hand-authored; re-run phase 1 "
            "(inventory) or 'reseal' the reviewed file. Refusing to "
            "execute."
        )
    actual_digest = _inventory_digest(
        remote_base,
        inventory.get("remote_outputs", f"{remote_base.rstrip('/')}/data/outputs"),
        files,
    )
    if actual_digest != recorded_digest:
        raise SystemExit(
            "ERROR: inventory integrity hash mismatch; refusing to "
            "delete anything.\n"
            f"  recorded: {recorded_digest}\n"
            f"  actual:   {actual_digest}\n"
            "The inventory was modified after it was sealed. Review the "
            "changes, then re-approve with:\n"
            f"  python -m scripts.withdraw_remote_artifacts reseal "
            f"--inventory {inventory_path}"
        )

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

    # §10: verify every inventoried path afterward. A deletion loop
    # that exits 0 is not proof of absence; we assert absence directly
    # so a silently-surviving file fails the run.
    survivors = _remote_existing(ssh_argv, paths)
    if survivors:
        raise SystemExit(
            "ERROR: post-deletion verification failed; the following "
            "inventoried path(s) still exist on the remote:\n  "
            + "\n  ".join(survivors)
        )
    print(
        f"Withdrawal complete: all {len(paths)} inventoried path(s) "
        f"verified absent on the remote.\n"
        f"Run the verification block in docs/repair/REMOTE_WITHDRAWAL.md "
        f"for the public-surface checks.",
        file=sys.stderr,
    )
    return 0


def cmd_reseal(args: argparse.Namespace) -> int:
    """Re-approve a pruned inventory by recomputing its integrity hash.

    Local and read-only with respect to the remote: no SSH, no
    deletion. This exists so that the legitimate review workflow
    ("inventory, then prune entries you do not want deleted") stays
    possible WITHOUT weakening phase 2's exact-consumption guarantee.
    Resealing is an explicit, auditable act: it rewrites the hash and
    reports what changed.
    """
    inventory_path = Path(args.inventory)
    if not inventory_path.is_file():
        raise SystemExit(f"ERROR: inventory not found: {inventory_path}")
    inventory = json.loads(inventory_path.read_text())

    files = inventory.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("ERROR: inventory has no 'files' list")

    remote_base = inventory.get("remote_base")
    if not remote_base:
        raise SystemExit("ERROR: inventory has no 'remote_base'")
    remote_outputs = inventory.get(
        "remote_outputs", f"{remote_base.rstrip('/')}/data/outputs"
    )

    # Reseal must not be a way to smuggle out-of-scope paths past the
    # scope rules, so enforce them here too.
    _refuse_protected(files, remote_base)

    old_digest = inventory.get("integrity_sha256")
    new_digest = _inventory_digest(remote_base, remote_outputs, files)
    if old_digest == new_digest:
        print(
            f"Inventory already sealed and unchanged ({new_digest}); "
            f"nothing to do.",
            file=sys.stderr,
        )
        return 0

    inventory["integrity_sha256"] = new_digest
    inventory["resealed_at_utc"] = datetime.utcnow().isoformat() + "Z"
    tmp_path = inventory_path.with_name(inventory_path.name + ".tmp")
    tmp_path.write_text(json.dumps(inventory, indent=2) + "\n")
    tmp_path.replace(inventory_path)
    print(
        f"Resealed {inventory_path} with {len(files)} entry(ies).\n"
        f"  previous hash: {old_digest}\n"
        f"  new hash:      {new_digest}",
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

    p_reseal = sub.add_parser(
        "reseal",
        help=(
            "Re-approve a manually pruned inventory by recomputing its "
            "integrity hash. Local only; never contacts the remote and "
            "never deletes anything."
        ),
    )
    p_reseal.add_argument(
        "--inventory", required=True,
        help="Path to the reviewed inventory JSON to reseal.",
    )
    p_reseal.set_defaults(func=cmd_reseal)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
