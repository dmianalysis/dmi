#!/usr/bin/env python3
"""Deterministic assembly of the public deployment tree (§5 / Round-3 §4+§5).

Historically, the deployment package was assembled inline by ad-hoc
shell steps inside `.github/workflows/monthly_dmi.yml` (and again, with
slightly different logic, inside `.github/workflows/deploy_web_dashboard.yml`).
Two workflows staging "the same" tree with two slightly different
recipes is a reliability defect: neither is reproducible outside CI,
and neither is testable in isolation.

This script gives a single deterministic recipe for the deployment
tree. It is now the sole builder used by:

- `.github/workflows/deploy_production.yml`  (post-merge deployment)
- `.github/workflows/deploy_web_dashboard.yml`
- `.github/workflows/monthly_dmi.yml`         (local validation only)

Round-3 §4 (full endpoint closure). The builder now closes over every
publicly-advertised endpoint, not merely the CSV/Parquet URLs cited in
`releases.json`. Specifically it stages:

  - dashboard shell            (dashboard.html, .htaccess, health.json)
  - top-level manifests        (releases.json, latest.json,
                                specifications.json)
  - release notes              (releases[*].release_note)
  - raw release JSON           (dmi_release_YYYY-MM[_slack_plus].json)
                                for every listed release, for every
                                spec that release advertises
  - spec CSV + Parquet         (spec_urls[*].{csv,parquet})
  - specifications release_json entries (belt + braces against
                                releases.json drift)
  - health.json endpoints      (every /data/outputs/… URL cited by
                                web/health.json)
  - dashboard runtime fetches  (dashboard.html hardcodes
                                specifications.json, dmi_timeseries.json,
                                and per-period raw baseline JSON)
  - current-period QA reports  (baseline + slack_plus, when advertised)

Every staged JSON is schema-validated against its schema in
`schemas/` before the staged tree becomes visible.

Round-3 §5 (fail-closed staging deletion). Previous versions ran
`shutil.rmtree(deploy_dir)` unconditionally on the user-supplied
`--output-dir`. That is a foot-gun (e.g. `--output-dir /` or
`--output-dir $HOME`). The new builder:

  - refuses to stage at the filesystem root, at the user's home, at
    the repository root itself, at any ancestor of the repository
    root, and at any symlink target;
  - refuses to overwrite a pre-existing non-empty directory that does
    not carry the sentinel file `.dmi-staging-sentinel`;
  - builds the full tree into a temp sibling directory (`<name>.staging-<id>`),
    validates it, and only then atomically replaces the canonical
    target via `Path.replace()`.

Historical archive under `data/outputs/published/historical/` is
deliberately excluded from the routine deployment; it is served by a
separate delta-upload step to keep the routine tree thin.

Usage:

    python -m scripts.prepare_deployment                      # write ./deploy/
    python -m scripts.prepare_deployment --output-dir deploy  # explicit
    python -m scripts.prepare_deployment --dry-run            # report only
    python -m scripts.prepare_deployment --verify             # rebuild + verify

`--verify` re-runs the closure check + schema validation against the
final canonical tree and exits non-zero on any mismatch.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"


# Sentinel that marks a directory as builder-owned. The builder will
# refuse to delete or overwrite any pre-existing target that is not
# empty and does not carry this sentinel — this is what turns
# `--output-dir /` (or any other unrelated location) into a hard
# failure instead of a data-loss event.
STAGING_SENTINEL = ".dmi-staging-sentinel"


# Files whose repository path does not match the deployed path.
# The site serves `/dashboard.html`, `/dashboard/.htaccess`, and
# `/health.json` from the site root (not under `web/`).
DASHBOARD_SHELL = {
    "web/dashboard.html": "dashboard.html",
    "web/dashboard/.htaccess": "dashboard/.htaccess",
    "web/health.json": "health.json",
}


# Manifests published at fixed URLs. Copied verbatim in addition to
# being scanned for advertised release URLs.
TOP_LEVEL_MANIFESTS = (
    "data/outputs/releases.json",
    "data/outputs/latest.json",
    "data/outputs/specifications.json",
)


# URLs the dashboard fetches unconditionally at every load. These are
# hard-coded in `web/dashboard.html`; they MUST be in the deploy tree
# even if not explicitly advertised in a manifest. The period-
# parameterized raw baseline JSON is discovered separately from
# `latest.json`/`releases.json`.
DASHBOARD_FETCHES = (
    "/health.json",
    "/data/outputs/specifications.json",
    "/data/outputs/published/dmi_timeseries.json",
)


# JSON kind -> schema file under schemas/
SCHEMA_BINDINGS = {
    "releases_manifest":   "releases.schema.json",
    "specifications":      "specifications.schema.json",
    "dmi_output":          "dmi_output.schema.json",
    "qa_report":           "qa_report.schema.json",
    "dmi_timeseries":      "dmi_timeseries_schema.json",
}

_RELEASE_JSON_RE = re.compile(
    r"^dmi_release_\d{4}-\d{2}(?:_slack_plus)?\.json$"
)
_QA_REPORT_RE = re.compile(
    r"^qa_report_\d{4}-\d{2}(?:_baseline|_slack_plus)?\.json$"
)


class StageError(RuntimeError):
    """Any deterministic-staging invariant violation."""


# ---------------------------------------------------------------------------
# URL discovery (§4: full endpoint closure)
# ---------------------------------------------------------------------------

def _iter_advertised_urls(manifest: dict) -> Iterable[str]:
    """Yield every `/data/outputs/...` URL advertised by a manifest.

    Covers the top-level `release_note` field (§2 topology) and every
    `spec_urls.<spec_id>.{csv,parquet}` entry. Intentionally NARROW:
    additional URL categories (raw release JSON, timeseries, QA
    reports, health endpoints) are yielded by dedicated helpers below,
    so that this narrow view of "what the manifest text literally
    advertises" remains testable in isolation.
    """
    for release in manifest.get("releases", []) or []:
        note = release.get("release_note")
        if note:
            yield note
        for block in (release.get("spec_urls") or {}).values():
            for key in ("csv", "parquet"):
                url = (block or {}).get(key)
                if url:
                    yield url


def _iter_raw_release_json_urls(manifest: dict) -> Iterable[str]:
    """Yield the raw release-JSON URL for every listed release/spec.

    A release that advertises `spec_urls.baseline` implies the
    existence of `/data/outputs/dmi_release_<id>.json`. A release that
    advertises `spec_urls.slack_plus` implies
    `/data/outputs/dmi_release_<id>_slack_plus.json`. These files carry
    the primary payload the dashboard fetches for headline metrics;
    §4 requires them to be part of the staged closure.
    """
    for release in manifest.get("releases", []) or []:
        rid = release.get("release_id")
        if not rid:
            continue
        spec_urls = release.get("spec_urls") or {}
        if "baseline" in spec_urls:
            yield f"/data/outputs/dmi_release_{rid}.json"
        if "slack_plus" in spec_urls:
            yield f"/data/outputs/dmi_release_{rid}_slack_plus.json"


def _iter_spec_release_json_urls(spec_manifest: dict) -> Iterable[str]:
    """Yield `release_json` URLs from `specifications.json`."""
    for spec in spec_manifest.get("specifications", []) or []:
        rj = spec.get("release_json")
        if rj:
            yield rj


def _iter_health_endpoint_urls(health: dict) -> Iterable[str]:
    """Yield every `/data/outputs/…` URL cited by health.json.

    `/dashboard.html` and `/health.json` are covered separately by the
    dashboard shell + hardcoded fetches, so they are not re-yielded
    here.
    """
    for _key, url in (health.get("endpoints") or {}).items():
        if isinstance(url, str) and url.startswith("/data/outputs/"):
            yield url


def _iter_current_qa_reports(latest: dict) -> Iterable[str]:
    """Yield the per-spec QA reports for the current period.

    Only current-period QA reports are staged; historical QA reports
    are not part of the routine advertised surface.
    """
    for release in latest.get("releases", []) or []:
        rid = release.get("release_id")
        if not rid:
            continue
        spec_urls = release.get("spec_urls") or {}
        for spec_id in ("baseline", "slack_plus"):
            if spec_id in spec_urls:
                yield f"/data/outputs/qa_report_{rid}_{spec_id}.json"


def _collect_urls(repo_root: Path) -> list[str]:
    """Compute the full deterministic closure of URLs to stage."""
    urls: list[str] = []

    for manifest_rel in ("data/outputs/releases.json",
                         "data/outputs/latest.json"):
        manifest = json.loads((repo_root / manifest_rel).read_text())
        urls.extend(_iter_advertised_urls(manifest))
        urls.extend(_iter_raw_release_json_urls(manifest))

    spec_manifest = json.loads(
        (repo_root / "data/outputs/specifications.json").read_text()
    )
    urls.extend(_iter_spec_release_json_urls(spec_manifest))

    health = json.loads((repo_root / "web/health.json").read_text())
    urls.extend(_iter_health_endpoint_urls(health))

    urls.extend(DASHBOARD_FETCHES)

    latest = json.loads(
        (repo_root / "data/outputs/latest.json").read_text()
    )
    urls.extend(_iter_current_qa_reports(latest))

    # Deterministic order; de-duplicated.
    return sorted(set(urls))


# ---------------------------------------------------------------------------
# URL <-> path mapping
# ---------------------------------------------------------------------------

_URL_TO_REPO_PREFIXES = (
    ("/data/outputs/", "data/outputs/"),
    ("/dashboard.html", "web/dashboard.html"),
    ("/dashboard/",     "web/dashboard/"),
    ("/health.json",    "web/health.json"),
)


def _url_to_source(url: str, repo_root: Path) -> Path:
    if not url.startswith("/"):
        raise StageError(f"URL is not root-absolute: {url!r}")
    for site_prefix, repo_prefix in _URL_TO_REPO_PREFIXES:
        if url == site_prefix:
            return repo_root / repo_prefix
        if url.startswith(site_prefix):
            tail = url[len(site_prefix):]
            return repo_root / (repo_prefix + tail)
    raise StageError(f"unmapped URL: {url!r}")


def _url_to_dest(url: str, deploy_dir: Path) -> Path:
    if not url.startswith("/"):
        raise StageError(f"URL is not root-absolute: {url!r}")
    return deploy_dir / url.lstrip("/")


#: Filename markers that must never reach the public deployment tree.
#: `core` is the withdrawn Core spec. `_u6` and `_with_ci` are
#: pre-v0.1.12 legacy artifacts (quarantined under
#: data/quarantine/pre_v0.1.12/); they are NOT Core, but they are
#: equally not part of the v0.1.12 published contract, so they must not
#: be staged either. Guarding all three here means the builder cannot
#: publish a retired artifact even if some manifest advertised one.
RETIRED_NAME_MARKERS = ("core", "_u6", "_with_ci")


def _retired_marker(name: str) -> Optional[str]:
    """Return the retired marker present in ``name``, or None."""
    lowered = name.lower()
    for marker in RETIRED_NAME_MARKERS:
        if marker in lowered:
            return marker
    return None


def _guard_core(path: Path) -> None:
    marker = _retired_marker(path.name)
    if marker is not None:
        raise StageError(
            f"refusing to stage file whose name references a retired "
            f"artifact class ({marker!r}): {path}"
        )


# ---------------------------------------------------------------------------
# Safe target selection (§5: fail-closed deletion)
# ---------------------------------------------------------------------------

def _is_ancestor(candidate: Path, of_path: Path) -> bool:
    """True iff `candidate` is a strict ancestor of `of_path`."""
    try:
        return of_path.resolve().is_relative_to(candidate)
    except AttributeError:
        # Python < 3.9 shim (repo requires 3.9 but keep it defensive).
        try:
            of_path.resolve().relative_to(candidate)
            return True
        except ValueError:
            return False


#: The one pre-existing directory the builder is allowed to rebuild
#: without a sentinel: the repository's own committed staging tree.
CANONICAL_DEPLOY_DIRNAME = "deploy"


def _is_canonical_deploy(resolved: Path, repo: Path) -> bool:
    """True iff ``resolved`` is exactly ``<repo>/deploy``."""
    return resolved == (repo / CANONICAL_DEPLOY_DIRNAME).resolve(strict=False)


def _forbidden_target_reason(
    target: Path,
    repo_root: Path,
) -> Optional[str]:
    """Return a human-readable reason to refuse `target`, or None.

    Refuses (§5):
      - the filesystem root
      - the current user's home directory
      - the repository root
      - any strict ancestor of the repository root
      - symlinks (avoid following into unintended locations)
      - a non-empty pre-existing target that lacks the sentinel
    """
    resolved = target.resolve(strict=False)
    root = Path("/").resolve()
    home = Path.home().resolve()
    repo = repo_root.resolve()

    if resolved == root:
        return "refusing to stage at filesystem root '/'"
    if resolved == home:
        return f"refusing to stage at user home '{home}'"
    if resolved == repo:
        return f"refusing to stage at repository root '{repo}'"
    if resolved != repo and _is_ancestor(resolved, repo):
        return (
            f"refusing to stage at an ancestor of the repository "
            f"root: {resolved}"
        )
    if target.is_symlink():
        return f"refusing to stage into a symlink: {target}"
    if target.exists():
        if not target.is_dir():
            return f"target exists and is not a directory: {target}"
        contents = list(target.iterdir())
        # §5: the canonical repository `deploy/` target is permitted
        # explicitly, not merely because it happens to carry a
        # committed sentinel. Relying on the sentinel alone made the
        # whole deployment pipeline fail closed if that dotfile was
        # ever dropped from a commit or stripped by a reviewer.
        if contents and not _is_canonical_deploy(resolved, repo) \
                and not (target / STAGING_SENTINEL).exists():
            return (
                f"refusing to overwrite non-empty directory that is "
                f"neither the canonical deploy/ target nor carries "
                f"'{STAGING_SENTINEL}': {target}"
            )
    return None


def _write_sentinel(target: Path) -> None:
    """Mark ``target`` as builder-owned.

    Round-3 §6 requires the committed tree to equal a fresh build
    byte-for-byte, with an exception only for non-public packaging
    files "whose generated contents are deterministic". An earlier
    version stamped `created_at_utc` here, which made the sentinel the
    single file that could never match — every rebuild produced a
    different byte. A timestamp is not needed for the sentinel's job
    (proving the directory is ours to delete), so the contents are now
    fixed and the WHOLE tree, sentinel included, is reproducible.

    Provenance that genuinely varies per build belongs in the build
    log, not in a file that must compare equal.
    """
    target.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_by": "scripts.prepare_deployment",
        "purpose": (
            "Marks this directory as builder-owned staging. "
            "scripts.prepare_deployment refuses to delete or rebuild a "
            "non-empty directory that lacks this file, unless it is the "
            "canonical repository deploy/ target."
        ),
        "deterministic": True,
    }
    (target / STAGING_SENTINEL).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )


# ---------------------------------------------------------------------------
# File copy + schema validation
# ---------------------------------------------------------------------------

def _copy(source: Path, dest: Path, dry_run: bool) -> None:
    _guard_core(dest)
    if not source.exists():
        raise StageError(f"source file missing: {source}")
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def _classify_json(path: Path) -> Optional[str]:
    name = path.name
    if name in ("releases.json", "latest.json"):
        return "releases_manifest"
    if name == "specifications.json":
        return "specifications"
    if name == "dmi_timeseries.json":
        return "dmi_timeseries"
    if _RELEASE_JSON_RE.match(name):
        return "dmi_output"
    if _QA_REPORT_RE.match(name):
        return "qa_report"
    return None


def _validate_staged_json(deploy_dir: Path) -> list[str]:
    """Schema-validate every recognized JSON under `deploy_dir`.

    Returns a list of problems (empty when the tree validates cleanly).
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return [
            "jsonschema is required for staged-JSON validation "
            "(pip install jsonschema)"
        ]

    problems: list[str] = []
    validators: dict = {}
    for kind, schema_file in SCHEMA_BINDINGS.items():
        schema_path = SCHEMAS_DIR / schema_file
        if not schema_path.exists():
            continue
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        validators[kind] = Draft202012Validator(schema)

    for path in sorted(deploy_dir.rglob("*.json")):
        # Skip the builder sentinel.
        if path.name == STAGING_SENTINEL:
            continue
        kind = _classify_json(path)
        if kind is None:
            continue
        validator = validators.get(kind)
        if validator is None:
            problems.append(
                f"no schema available for "
                f"{path.relative_to(deploy_dir)} (kind={kind})"
            )
            continue
        try:
            instance = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            problems.append(
                f"{path.relative_to(deploy_dir)}: invalid JSON: {exc}"
            )
            continue
        errors = sorted(
            validator.iter_errors(instance),
            key=lambda e: list(e.absolute_path),
        )
        for err in errors:
            problems.append(
                f"{path.relative_to(deploy_dir)}: schema violation at "
                f"{list(err.absolute_path)}: {err.message}"
            )
    return problems


# ---------------------------------------------------------------------------
# Main staging entry point
# ---------------------------------------------------------------------------

def _stage_into(target: Path, repo_root: Path, dry_run: bool) -> list[Path]:
    """Stage the full closure into `target` (which must already exist
    as a builder-owned directory, or dry-run may skip that check)."""
    written: list[Path] = []

    # 1. Dashboard shell (fixed set)
    for src_rel, dst_rel in DASHBOARD_SHELL.items():
        src = repo_root / src_rel
        dst = target / dst_rel
        _copy(src, dst, dry_run)
        written.append(dst)

    # 2. Top-level manifests (verbatim)
    for rel in TOP_LEVEL_MANIFESTS:
        src = repo_root / rel
        dst = target / rel
        _copy(src, dst, dry_run)
        written.append(dst)

    # 3. Every URL in the full closure
    seen: set[Path] = set()
    for url in _collect_urls(repo_root):
        src = _url_to_source(url, repo_root)
        dst = _url_to_dest(url, target)
        if dst in seen:
            continue
        seen.add(dst)
        _copy(src, dst, dry_run)
        written.append(dst)

    # Deterministic ordering.
    return sorted(set(written), key=lambda p: str(p))


def prepare_deployment(
    deploy_dir: Path,
    repo_root: Path = REPO_ROOT,
    dry_run: bool = False,
) -> list[Path]:
    """Assemble the deployment tree deterministically (§4 + §5).

    In dry-run mode the target is not created or modified; each source
    file's existence is still asserted so a missing source is caught
    up front.

    In real mode the tree is built into a temp sibling directory,
    schema-validated, and only then atomically replaces the canonical
    target. Dangerous targets are refused before any writes.
    """
    # Preserve the caller's path-space (do not follow symlinks that the
    # caller intentionally passed through, e.g. /var -> /private/var
    # on macOS tempdirs). Safety checks below still resolve internally
    # for canonical-comparison correctness.
    deploy_dir = deploy_dir.absolute()

    if dry_run:
        return _stage_into(deploy_dir, repo_root, dry_run=True)

    # §5: refuse dangerous targets before any filesystem writes.
    reason = _forbidden_target_reason(deploy_dir, repo_root)
    if reason is not None:
        raise StageError(reason)

    parent = deploy_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temp_dir = parent / f".{deploy_dir.name}.staging-{uuid.uuid4().hex[:8]}"

    try:
        _write_sentinel(temp_dir)
        _stage_into(temp_dir, repo_root, dry_run=False)

        # Schema-validate the staged tree BEFORE swap.
        problems = _validate_staged_json(temp_dir)
        if problems:
            raise StageError(
                "staged JSON failed schema validation:\n  - "
                + "\n  - ".join(problems)
            )

        # Swap. The pre-check confirmed the existing target (if any)
        # is empty or builder-owned, so removing it is safe.
        if deploy_dir.exists():
            shutil.rmtree(deploy_dir)
        temp_dir.replace(deploy_dir)
    except Exception:
        # Best-effort cleanup of the temp sibling on failure.
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except OSError:
                pass
        raise

    # Return the final canonical file set (excluding the sentinel).
    return sorted(
        p for p in deploy_dir.rglob("*")
        if p.is_file() and p.name != STAGING_SENTINEL
    )


def verify_deployment(
    deploy_dir: Path,
    repo_root: Path = REPO_ROOT,
) -> list[str]:
    """Return a list of problems with the assembled deploy tree.

    Checks:
      - every URL in the full closure is present and byte-identical
        to its repository source;
      - no Core-named artifact has slipped in;
      - every recognized JSON validates against its schema.

    Empty list means the tree is consistent with the manifests and
    the shipped schemas.
    """
    problems: list[str] = []

    for url in _collect_urls(repo_root):
        src = _url_to_source(url, repo_root)
        dst = _url_to_dest(url, deploy_dir)
        if not dst.exists():
            problems.append(f"missing in deploy tree: {url}")
            continue
        if not filecmp.cmp(src, dst, shallow=False):
            problems.append(f"deploy tree diverges from source for {url}")

    for path in deploy_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.name == STAGING_SENTINEL:
            continue
        marker = _retired_marker(path.name)
        if marker is not None:
            problems.append(
                f"retired artifact ({marker!r}) present in deploy tree: "
                f"{path.relative_to(deploy_dir)}"
            )

    # §6: the tree must contain nothing beyond the closure. A builder
    # that only checks "is everything advertised present?" would pass
    # while shipping a stale extra file left over from a previous
    # layout, which is how `qa_report_2026-03_core.json` and the 2026-03
    # specifications snapshot survived earlier rebuilds.
    expected = {
        (deploy_dir / dst_rel).resolve()
        for dst_rel in DASHBOARD_SHELL.values()
    }
    expected |= {
        (deploy_dir / rel).resolve() for rel in TOP_LEVEL_MANIFESTS
    }
    expected |= {
        _url_to_dest(url, deploy_dir).resolve()
        for url in _collect_urls(repo_root)
    }
    for path in sorted(deploy_dir.rglob("*")):
        if not path.is_file() or path.name == STAGING_SENTINEL:
            continue
        if path.resolve() not in expected:
            problems.append(
                f"unexpected file in deploy tree (not in closure): "
                f"{path.relative_to(deploy_dir)}"
            )

    problems.extend(_validate_staged_json(deploy_dir))
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
        help="After building, verify closure + byte-identity + schemas.",
    )
    args = parser.parse_args(argv)

    deploy_dir = Path(args.output_dir).absolute()

    try:
        written = prepare_deployment(deploy_dir, dry_run=args.dry_run)
    except StageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "would write" if args.dry_run else "wrote"
    for path in written:
        try:
            rel = path.relative_to(deploy_dir)
        except ValueError:
            rel = path
        print(f"  {verb} {rel}")

    if args.verify and not args.dry_run:
        problems = verify_deployment(deploy_dir)
        if problems:
            print("verification failed:", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("verification passed: deploy tree matches closure + schemas.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
