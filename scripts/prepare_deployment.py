#!/usr/bin/env python3
"""Deterministic assembly of the public deployment tree (§5).

Historically, the deployment package was assembled inline by ad-hoc
shell steps inside `.github/workflows/monthly_dmi.yml` (and again, with
slightly different logic, inside `.github/workflows/deploy_web_dashboard.yml`).
Two workflows staging "the same" tree with two slightly different
recipes is a reliability defect: neither is reproducible outside CI,
and neither is testable in isolation.

This script gives a single deterministic recipe for the deployment
tree, driven purely by:

- `data/outputs/releases.json` and `data/outputs/latest.json`
  (the source of truth for which files are advertised publicly), and
- the dashboard shell (`web/dashboard.html`, `web/dashboard/.htaccess`,
  `web/health.json`) that carries every release.

The script is idempotent (running twice produces the same tree),
manifest-driven (every URL advertised by the shipped manifests must
resolve to a real file in `data/outputs/`, and every such file is
copied into the deploy tree at the identical path), and Core-safe (it
refuses to stage anything whose path or filename mentions Core).

Historical archive under `data/outputs/published/historical/` is
deliberately excluded from the routine deployment — it is handled by
a separate delta-upload step to keep the routine tree thin.

Usage:

    python -m scripts.prepare_deployment                      # write ./deploy/
    python -m scripts.prepare_deployment --output-dir deploy  # explicit
    python -m scripts.prepare_deployment --dry-run            # report only
    python -m scripts.prepare_deployment --verify             # rebuild + verify

The `--verify` mode rebuilds the tree, then asserts that every URL in
the manifests is present in the deploy tree with byte-identical content
to the corresponding source file under `data/outputs/`. Non-zero exit
on any mismatch.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent


# Files whose repository path does not match the deployed path.
# The site serves `/dashboard.html`, `/.htaccess`, and `/health.json`
# from the site root (not under `web/`).
DASHBOARD_SHELL = {
    "web/dashboard.html": "dashboard.html",
    "web/dashboard/.htaccess": "dashboard/.htaccess",
    "web/health.json": "health.json",
}


# Manifests published at fixed URLs. These are copied verbatim in
# addition to being scanned for advertised release URLs.
TOP_LEVEL_MANIFESTS = (
    "data/outputs/releases.json",
    "data/outputs/latest.json",
    "data/outputs/specifications.json",
)


class StageError(RuntimeError):
    """Any deterministic-staging invariant violation."""


def _iter_advertised_urls(manifest: dict) -> Iterable[str]:
    """Yield every `/data/outputs/...` URL advertised by a manifest.

    Covers the top-level `release_note` field (§2 topology) and every
    `spec_urls.<spec_id>.{csv,parquet}` entry.
    """
    for release in manifest.get("releases", []):
        note = release.get("release_note")
        if note:
            yield note
        for block in release.get("spec_urls", {}).values():
            for key in ("csv", "parquet"):
                url = block.get(key)
                if url:
                    yield url


def _url_to_source(url: str, repo_root: Path) -> Path:
    prefix = "/data/outputs/"
    if not url.startswith(prefix):
        raise StageError(f"unexpected URL prefix: {url!r}")
    return repo_root / "data" / "outputs" / url[len(prefix):]


def _url_to_dest(url: str, deploy_dir: Path) -> Path:
    # The deploy tree mirrors the site root, so `/data/outputs/foo`
    # maps to `<deploy>/data/outputs/foo`.
    return deploy_dir / url.lstrip("/")


def _guard_core(path: Path) -> None:
    name = path.name.lower()
    if "core" in name:
        raise StageError(
            f"refusing to stage file whose name references the withdrawn "
            f"Core spec: {path}"
        )


def _copy(source: Path, dest: Path, dry_run: bool) -> None:
    _guard_core(dest)
    if not source.exists():
        raise StageError(f"source file missing: {source}")
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def prepare_deployment(
    deploy_dir: Path,
    repo_root: Path = REPO_ROOT,
    dry_run: bool = False,
) -> list[Path]:
    """Assemble the deployment tree deterministically.

    Returns the sorted list of destination paths that would be (or
    were) written. In dry-run mode no files are copied but the same
    list is returned, and every source-file existence check still runs.
    """
    if not dry_run:
        if deploy_dir.exists():
            shutil.rmtree(deploy_dir)
        deploy_dir.mkdir(parents=True)

    written: list[Path] = []

    # 1. Dashboard shell (fixed set)
    for src_rel, dst_rel in DASHBOARD_SHELL.items():
        src = repo_root / src_rel
        dst = deploy_dir / dst_rel
        _copy(src, dst, dry_run)
        written.append(dst)

    # 2. Top-level manifests (verbatim)
    for rel in TOP_LEVEL_MANIFESTS:
        src = repo_root / rel
        dst = deploy_dir / rel
        _copy(src, dst, dry_run)
        written.append(dst)

    # 3. Every URL advertised by releases.json / latest.json.
    seen: set[Path] = set()
    for manifest_rel in ("data/outputs/releases.json", "data/outputs/latest.json"):
        manifest = json.loads((repo_root / manifest_rel).read_text())
        for url in _iter_advertised_urls(manifest):
            src = _url_to_source(url, repo_root)
            dst = _url_to_dest(url, deploy_dir)
            if dst in seen:
                continue
            seen.add(dst)
            _copy(src, dst, dry_run)
            written.append(dst)

    return sorted(written)


def verify_deployment(
    deploy_dir: Path,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Return a list of problems with the assembled deploy tree.

    Empty list means the tree is consistent with the manifests.
    """
    problems: list[str] = []

    for manifest_rel in ("data/outputs/releases.json", "data/outputs/latest.json"):
        manifest = json.loads((repo_root / manifest_rel).read_text())
        for url in _iter_advertised_urls(manifest):
            src = _url_to_source(url, repo_root)
            dst = _url_to_dest(url, deploy_dir)
            if not dst.exists():
                problems.append(f"missing in deploy tree: {url}")
                continue
            if not filecmp.cmp(src, dst, shallow=False):
                problems.append(
                    f"deploy tree diverges from source for {url}"
                )

    # Guard against any Core artifact having slipped in via any path.
    for path in deploy_dir.rglob("*"):
        if not path.is_file():
            continue
        if "core" in path.name.lower():
            problems.append(
                f"Core-named artifact present in deploy tree: "
                f"{path.relative_to(deploy_dir)}"
            )

    return problems


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output-dir",
        default="deploy",
        help="Where to write the deploy tree (default: ./deploy).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report planned writes without touching the filesystem.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After building, verify every advertised URL is present and "
             "byte-identical to its source.",
    )
    args = parser.parse_args(argv)

    deploy_dir = Path(args.output_dir).resolve()

    try:
        written = prepare_deployment(deploy_dir, dry_run=args.dry_run)
    except StageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "would write" if args.dry_run else "wrote"
    for path in written:
        rel = path.relative_to(deploy_dir.parent) if deploy_dir.is_absolute() else path
        print(f"  {verb} {rel}")

    if args.verify and not args.dry_run:
        problems = verify_deployment(deploy_dir)
        if problems:
            print("verification failed:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("✅ verification passed: deploy tree matches manifests.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
