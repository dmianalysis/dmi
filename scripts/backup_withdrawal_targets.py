#!/usr/bin/env python3
"""Back up exactly the inventoried Core artifacts before deletion.

This runs between verification and deletion, and deletion may not start
unless it succeeded and its artifact uploaded.

Two properties matter more than the backup itself:

**Exactness.** The remote file list is derived only from the already
validated inventory. There is no directory copy, no glob, and no second
enumeration — a backup that fetched "the Core files" by pattern could
disagree with the set about to be deleted, which is precisely the failure
a backup is supposed to insure against. Files are streamed through a
single ``tar -T -`` reading the explicit path list from stdin.

**Agreement.** Every downloaded file's size and SHA-256 must equal the
inventory's. A backup that does not match what is about to be deleted is
worse than none: it looks like insurance while covering different bytes.
Missing, extra, or changed files all fail closed.

The archive is deterministic — sorted entries, normalised metadata,
gzip mtime pinned — so two runs over unchanged remote state produce
byte-identical archives and the backup can itself be hashed and cited.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class BackupError(RuntimeError):
    """The backup could not be created or did not match the inventory."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_files(ssh_argv: list[str], paths: list[str]) -> dict[str, bytes]:
    """Stream exactly ``paths`` from the remote in one SSH session.

    ``tar -T -`` reads the file list from stdin, so the set transferred is
    literally the reviewed list: no wildcard is ever expanded remotely.
    """
    if not paths:
        raise BackupError("no paths to back up")

    listing = "\n".join(paths) + "\n"
    proc = subprocess.run(
        [*ssh_argv, "tar -cf - -T - 2>/dev/null"],
        input=listing.encode(), capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise BackupError(
            f"remote tar failed (rc={proc.returncode}): "
            f"{proc.stderr.decode(errors='replace').strip()[:400]}"
        )

    fetched: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            # tar strips the leading slash; restore it for comparison.
            name = member.name
            fetched["/" + name.lstrip("/")] = handle.read()
    return fetched


def verify_against_inventory(
    fetched: dict[str, bytes], files: list[dict],
) -> list[str]:
    """Every inventoried file present, byte-exact, and nothing extra."""
    problems: list[str] = []
    expected = {record["path"]: record for record in files}

    missing = sorted(set(expected) - set(fetched))
    for path in missing:
        problems.append(f"missing from backup: {path}")

    extra = sorted(set(fetched) - set(expected))
    for path in extra:
        problems.append(
            f"backup contains a file that is not in the inventory: {path}"
        )

    for path in sorted(set(expected) & set(fetched)):
        data = fetched[path]
        record = expected[path]
        if len(data) != record["size"]:
            problems.append(
                f"size mismatch for {path}: inventory {record['size']}, "
                f"downloaded {len(data)}"
            )
        actual = _sha256(data)
        if actual != record["sha256"]:
            problems.append(
                f"sha256 mismatch for {path}: inventory {record['sha256']}, "
                f"downloaded {actual}. The remote file changed since the "
                f"inventory was sealed."
            )
    return problems


def write_archive(fetched: dict[str, bytes], destination: Path) -> str:
    """Write a deterministic .tar.gz and return its SHA-256.

    Determinism matters because the archive is cited as evidence: the
    same remote state must always produce the same digest, so entries are
    sorted, ownership and mtime normalised, and gzip's own timestamp
    pinned to 0.
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path in sorted(fetched):
            data = fetched[path]
            info = tarfile.TarInfo(name=path.lstrip("/"))
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))

    raw = buffer.getvalue()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "wb") as handle:
        # `filename=""` matters: given only a fileobj, GzipFile copies
        # `fileobj.name` into the gzip header, so an archive written to
        # `a.tar.gz` would differ from the same bytes written to
        # `b.tar.gz`. Pinning it (with mtime=0) makes the digest depend
        # on content alone, which is what lets the archive be cited as
        # evidence.
        with gzip.GzipFile(
            filename="", fileobj=handle, mode="wb", mtime=0
        ) as gz:
            gz.write(raw)
    return _sha256(destination.read_bytes())


def build_manifest(
    fetched: dict[str, bytes], inventory: dict, archive: Path,
    archive_sha256: str,
) -> dict:
    return {
        "schema_version": "1.0.0",
        "created_at_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "purpose": (
            "Pre-deletion backup of the Core artifacts named by the sealed "
            "withdrawal inventory. Contains no credentials: these files "
            "were already public, and are withdrawn because they are "
            "invalid, not because they are sensitive."
        ),
        "source_inventory": {
            "integrity_sha256": inventory.get("integrity_sha256"),
            "remote_base": inventory.get("remote_base"),
            "remote_outputs": inventory.get("remote_outputs"),
            "file_count": len(inventory.get("files", [])),
        },
        "archive": {
            "name": archive.name,
            "sha256": archive_sha256,
            "bytes": archive.stat().st_size,
            "deterministic": True,
        },
        "files": [
            {
                "path": path,
                "size": len(fetched[path]),
                "sha256": _sha256(fetched[path]),
            }
            for path in sorted(fetched)
        ],
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", required=True,
                        help="Directory for the archive and manifest.")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    from scripts.verify_withdrawal_inventory import INVENTORY_PATH, verify

    inventory_path = repo_root / INVENTORY_PATH
    problems, _report = verify(inventory_path)
    if problems:
        print("refusing to back up: the inventory failed verification.",
              file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    inventory = json.loads(inventory_path.read_text())
    files = inventory["files"]
    paths = [record["path"] for record in files]

    from scripts.withdraw_remote_artifacts import _load_ssh_config
    ssh_argv, _base = _load_ssh_config()

    print(f"backing up {len(paths)} inventoried file(s) ...")
    fetched = fetch_files(ssh_argv, paths)
    print(f"  downloaded {len(fetched)} file(s)")

    verification = verify_against_inventory(fetched, files)
    if verification:
        print("\nBACKUP VERIFICATION FAILED — no deletion may occur:",
              file=sys.stderr)
        for problem in verification:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("  every file matches the inventory by size and sha256")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / "core-withdrawal-backup.tar.gz"
    archive_sha = write_archive(fetched, archive)
    manifest = build_manifest(fetched, inventory, archive, archive_sha)
    (out_dir / "backup-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    print(f"  archive  : {archive.name} ({archive.stat().st_size} bytes)")
    print(f"  sha256   : {archive_sha}")
    print(f"  manifest : backup-manifest.json")
    print("\nBACKUP COMPLETE and verified against the sealed inventory.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
