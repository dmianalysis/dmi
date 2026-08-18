#!/usr/bin/env python3
"""Regression coverage for the deterministic staging script (§5).

The `scripts.prepare_deployment` module is the single source of truth
for what the site is supposed to serve. These tests exercise its
invariants without touching the real `./deploy/` tree.
"""

from __future__ import annotations

import filecmp
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_deployment import (
    DASHBOARD_SHELL,
    TOP_LEVEL_MANIFESTS,
    _iter_advertised_urls,
    prepare_deployment,
    verify_deployment,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPrepareDeploymentDeterministic(unittest.TestCase):

    def test_running_twice_produces_identical_tree(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            a_paths = prepare_deployment(Path(a))
            b_paths = prepare_deployment(Path(b))

            a_rel = sorted(p.relative_to(a) for p in a_paths)
            b_rel = sorted(p.relative_to(b) for p in b_paths)
            self.assertEqual(
                a_rel, b_rel,
                "prepare_deployment must produce the same file set on every run",
            )
            for rel in a_rel:
                fa = Path(a) / rel
                fb = Path(b) / rel
                self.assertTrue(
                    filecmp.cmp(fa, fb, shallow=False),
                    f"{rel}: deploy tree not byte-identical between runs",
                )

    def test_every_manifest_url_is_present_in_deploy_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_deployment(Path(tmp))
            problems = verify_deployment(Path(tmp))
            self.assertEqual(
                problems, [],
                f"verify_deployment reported problems: {problems}",
            )

    def test_dashboard_shell_files_are_staged(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_deployment(Path(tmp))
            for dst_rel in DASHBOARD_SHELL.values():
                self.assertTrue(
                    (Path(tmp) / dst_rel).exists(),
                    f"dashboard shell file missing from deploy tree: {dst_rel}",
                )

    def test_top_level_manifests_are_staged_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_deployment(Path(tmp))
            for manifest_rel in TOP_LEVEL_MANIFESTS:
                src = REPO_ROOT / manifest_rel
                dst = Path(tmp) / manifest_rel
                self.assertTrue(dst.exists(), f"{manifest_rel} not staged")
                self.assertTrue(
                    filecmp.cmp(src, dst, shallow=False),
                    f"{manifest_rel} staged copy differs from source",
                )

    def test_deploy_tree_excludes_historical_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_deployment(Path(tmp))
            historical = Path(tmp) / "data" / "outputs" / "published" / "historical"
            self.assertFalse(
                historical.exists(),
                "historical archive must not be part of the routine deploy tree",
            )

    def test_deploy_tree_contains_no_core_named_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_deployment(Path(tmp))
            offenders = [
                str(p.relative_to(tmp))
                for p in Path(tmp).rglob("*")
                if p.is_file() and "core" in p.name.lower()
            ]
            self.assertEqual(
                offenders, [],
                f"Core-named artifacts must never appear in deploy tree: {offenders}",
            )

    def test_dry_run_leaves_output_dir_untouched(self):
        with tempfile.TemporaryDirectory() as parent:
            target = Path(parent) / "would_be_deploy"
            # Directory does not exist beforehand
            self.assertFalse(target.exists())
            planned = prepare_deployment(target, dry_run=True)
            self.assertFalse(
                target.exists(),
                "dry-run must not create the output directory",
            )
            # But it must still return the planned file set
            self.assertGreater(len(planned), 0)


class TestIterAdvertisedUrls(unittest.TestCase):

    def test_yields_release_note_and_all_spec_url_variants(self):
        manifest = {
            "releases": [
                {
                    "release_id": "2026-07",
                    "release_note": "/data/outputs/releases/2026-07.html",
                    "spec_urls": {
                        "baseline": {
                            "csv": "/data/outputs/dmi-2026-07-baseline.csv",
                            "parquet": "/data/outputs/dmi-2026-07-baseline.parquet",
                        },
                        "slack_plus": {
                            "csv": "/data/outputs/dmi-2026-07-slack_plus.csv",
                            "parquet": "/data/outputs/dmi-2026-07-slack_plus.parquet",
                        },
                    },
                },
            ]
        }
        urls = sorted(_iter_advertised_urls(manifest))
        self.assertEqual(urls, [
            "/data/outputs/dmi-2026-07-baseline.csv",
            "/data/outputs/dmi-2026-07-baseline.parquet",
            "/data/outputs/dmi-2026-07-slack_plus.csv",
            "/data/outputs/dmi-2026-07-slack_plus.parquet",
            "/data/outputs/releases/2026-07.html",
        ])

    def test_tolerates_missing_release_note(self):
        # Manifest without release_note should still yield spec URLs.
        manifest = {
            "releases": [
                {
                    "release_id": "x",
                    "spec_urls": {
                        "baseline": {
                            "csv": "/data/outputs/a.csv",
                        }
                    },
                }
            ]
        }
        urls = list(_iter_advertised_urls(manifest))
        self.assertEqual(urls, ["/data/outputs/a.csv"])


# ---------------------------------------------------------------------------
# Round-3 §4 / §5 / §6 / §14.
#
# The tests above assert that the builder produces a self-consistent
# tree. They could not have caught the defects this section exists for,
# because they only ever asked "is what the builder staged consistent
# with what the builder decided to stage?" — a question that stays
# green while the closure itself is incomplete.
#
# These tests instead pin the closure against external ground truth
# (the manifests, health.json, and dashboard.html's literal fetch
# calls), pin the committed tree against a fresh build, and prove the
# destructive-safety guards fire without touching a marker file.
# ---------------------------------------------------------------------------

import json as _json
import os as _os
import re as _re
import subprocess as _subprocess
import sys as _sys

from scripts.prepare_deployment import (  # noqa: E402
    DASHBOARD_FETCHES,
    STAGING_SENTINEL,
    StageError,
    _collect_urls,
    _forbidden_target_reason,
    _retired_marker,
    _url_to_dest,
)

COMMITTED_DEPLOY = REPO_ROOT / "deploy"


class TestEndpointClosureRegressions(unittest.TestCase):
    """§4: named regressions for the three endpoints the builder omitted.

    The audit recorded that the builder "incorrectly passes while
    omitting" these exact three files. Each gets its own test so a
    regression names the missing endpoint rather than failing a generic
    closure assertion.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tree = Path(cls._tmp.name) / "deploy"
        prepare_deployment(cls.tree)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_raw_baseline_release_json_is_staged(self):
        target = self.tree / "data/outputs/dmi_release_2026-07.json"
        self.assertTrue(
            target.is_file(),
            "§4: /data/outputs/dmi_release_2026-07.json must be staged; "
            "the dashboard fetches the raw baseline release directly.",
        )

    def test_raw_slack_plus_release_json_is_staged(self):
        target = (
            self.tree / "data/outputs/dmi_release_2026-07_slack_plus.json"
        )
        self.assertTrue(
            target.is_file(),
            "§4: /data/outputs/dmi_release_2026-07_slack_plus.json must "
            "be staged.",
        )

    def test_public_timeseries_is_staged(self):
        target = (
            self.tree / "data/outputs/published/dmi_timeseries.json"
        )
        self.assertTrue(
            target.is_file(),
            "§4: /data/outputs/published/dmi_timeseries.json must be "
            "staged; the dashboard fetches it on every load.",
        )

    def test_every_release_has_its_raw_json_for_every_advertised_spec(self):
        """Generalised form of the three regressions above."""
        manifest = _json.loads(
            (REPO_ROOT / "data/outputs/releases.json").read_text()
        )
        missing = []
        for release in manifest["releases"]:
            rid = release["release_id"]
            specs = release.get("spec_urls") or {}
            if "baseline" in specs:
                p = self.tree / f"data/outputs/dmi_release_{rid}.json"
                if not p.is_file():
                    missing.append(str(p.relative_to(self.tree)))
            if "slack_plus" in specs:
                p = (
                    self.tree
                    / f"data/outputs/dmi_release_{rid}_slack_plus.json"
                )
                if not p.is_file():
                    missing.append(str(p.relative_to(self.tree)))
        self.assertEqual(missing, [], f"§4: raw release JSON missing: {missing}")

    def test_current_period_qa_reports_are_staged(self):
        """§4: applicable current Baseline and Slack-Plus QA reports."""
        latest = _json.loads(
            (REPO_ROOT / "data/outputs/latest.json").read_text()
        )
        rid = latest["releases"][0]["release_id"]
        for spec in ("baseline", "slack_plus"):
            with self.subTest(spec=spec):
                p = (
                    self.tree
                    / f"data/outputs/qa_report_{rid}_{spec}.json"
                )
                self.assertTrue(
                    p.is_file(),
                    f"§4: QA report for {rid}/{spec} must be staged.",
                )

    def test_specifications_release_json_entries_are_staged(self):
        """§4: every Baseline/Slack-Plus release JSON in specifications.json."""
        spec = _json.loads(
            (REPO_ROOT / "data/outputs/specifications.json").read_text()
        )
        missing = []
        for entry in spec.get("specifications", []):
            url = entry.get("release_json")
            if url and not _url_to_dest(url, self.tree).is_file():
                missing.append(url)
        self.assertEqual(missing, [], f"§4: unstaged release_json: {missing}")

    def test_every_health_endpoint_resolves_in_the_tree(self):
        """§4: do not limit verification to releases.json / latest.json."""
        health = _json.loads((REPO_ROOT / "web/health.json").read_text())
        missing = []
        for key, url in (health.get("endpoints") or {}).items():
            if not isinstance(url, str) or not url.startswith("/"):
                continue
            if not _url_to_dest(url, self.tree).is_file():
                missing.append(f"{key} -> {url}")
        self.assertEqual(
            missing, [],
            f"§4: health.json advertises unstaged endpoint(s): {missing}",
        )

    def test_every_manifest_release_note_resolves(self):
        for name in ("releases.json", "latest.json"):
            manifest = _json.loads(
                (REPO_ROOT / "data/outputs" / name).read_text()
            )
            for release in manifest["releases"]:
                note = release.get("release_note")
                if not note:
                    continue
                with self.subTest(manifest=name, release=release["release_id"]):
                    self.assertTrue(
                        _url_to_dest(note, self.tree).is_file(),
                        f"§4: release note {note} not staged",
                    )

    def test_every_csv_and_parquet_resolves(self):
        for name in ("releases.json", "latest.json"):
            manifest = _json.loads(
                (REPO_ROOT / "data/outputs" / name).read_text()
            )
            for release in manifest["releases"]:
                for spec_id, block in (release.get("spec_urls") or {}).items():
                    for kind in ("csv", "parquet"):
                        url = (block or {}).get(kind)
                        if not url:
                            continue
                        with self.subTest(url=url):
                            self.assertTrue(
                                _url_to_dest(url, self.tree).is_file(),
                                f"§4: {url} not staged",
                            )


class TestDashboardDependencyClosure(unittest.TestCase):
    """§4: the closure must cover what dashboard.html actually fetches.

    `DASHBOARD_FETCHES` is a hand-maintained constant. This test reads
    the literal `fetch(...)` targets out of the shipped dashboard and
    asserts each one resolves in the staged tree, so editing the
    dashboard to fetch a new file cannot silently escape the closure.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tree = Path(cls._tmp.name) / "deploy"
        prepare_deployment(cls.tree)
        cls.dashboard = (REPO_ROOT / "web/dashboard.html").read_text()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _fetch_targets(self):
        """Literal fetch targets, with `${...}` interpolations generalised."""
        targets = set()
        for raw in _re.findall(r"""fetch\(\s*['"`]([^'"`]+)['"`]""",
                               self.dashboard):
            targets.add(raw)
        return targets

    def test_dashboard_has_discoverable_fetch_calls(self):
        """Guard against the extraction silently matching nothing."""
        self.assertGreater(
            len(self._fetch_targets()), 0,
            "could not extract any fetch() target from dashboard.html; "
            "this test would otherwise pass vacuously.",
        )

    def test_every_static_dashboard_fetch_is_staged(self):
        latest = _json.loads(
            (REPO_ROOT / "data/outputs/latest.json").read_text()
        )
        period = latest["releases"][0]["release_id"]
        missing = []
        for target in sorted(self._fetch_targets()):
            # Resolve the one period-parameterised fetch against the
            # current period advertised by latest.json.
            resolved = _re.sub(r"\$\{[^}]+\}", period, target)
            rel = resolved.lstrip("./")
            if not (self.tree / rel).is_file():
                missing.append(f"{target} -> {rel}")
        self.assertEqual(
            missing, [],
            f"§4: dashboard fetches file(s) absent from staging: {missing}",
        )

    def test_declared_dashboard_fetches_are_all_in_the_closure(self):
        closure = set(_collect_urls(REPO_ROOT))
        for url in DASHBOARD_FETCHES:
            with self.subTest(url=url):
                if url == "/health.json":
                    # Staged via DASHBOARD_SHELL, not the URL closure.
                    self.assertTrue((self.tree / "health.json").is_file())
                else:
                    self.assertIn(url, closure)


class TestNoRetiredArtifactsStaged(unittest.TestCase):
    """§6/§14: no Core, U-6 alias, or with-CI artifact may be staged."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.tree = Path(cls._tmp.name) / "deploy"
        prepare_deployment(cls.tree)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_no_retired_marker_in_any_staged_filename(self):
        offenders = [
            str(p.relative_to(self.tree))
            for p in self.tree.rglob("*")
            if p.is_file()
            and p.name != STAGING_SENTINEL
            and _retired_marker(p.name) is not None
        ]
        self.assertEqual(
            offenders, [],
            f"§6: retired artifacts staged: {offenders}",
        )

    def test_retired_marker_detector_is_not_vacuous(self):
        """The guard must actually fire on the names it targets."""
        for name, expected in (
            ("dmi_release_2026-03_core.json", "core"),
            ("dmi-2026-03-core.csv", "core"),
            ("qa_report_2026-03_core.json", "core"),
            ("dmi_release_2024-11_u6.json", "_u6"),
            ("dmi_release_2024-11_with_ci.json", "_with_ci"),
        ):
            with self.subTest(name=name):
                self.assertEqual(_retired_marker(name), expected)

    def test_current_artifacts_are_not_flagged(self):
        for name in (
            "dmi_release_2026-07.json",
            "dmi_release_2026-07_slack_plus.json",
            "dmi-2026-07-baseline.csv",
            "dmi-2026-07-slack_plus.parquet",
            "releases.json",
            "latest.json",
            "specifications.json",
            "health.json",
            "dmi_timeseries.json",
            "2026-07.html",
        ):
            with self.subTest(name=name):
                self.assertIsNone(
                    _retired_marker(name),
                    f"{name} must not be flagged as retired",
                )

    def test_quarantine_directory_is_never_staged(self):
        """§8: the quarantine location must not be discoverable."""
        self.assertFalse(
            (self.tree / "data" / "quarantine").exists(),
            "§8: quarantine directory must never appear in staging",
        )


class TestStagedJsonValidates(unittest.TestCase):
    """§4: every staged JSON instance validates against its schema."""

    def test_no_schema_problems_in_a_fresh_tree(self):
        from scripts.prepare_deployment import _validate_staged_json
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp) / "deploy"
            prepare_deployment(tree)
            problems = _validate_staged_json(tree)
            self.assertEqual(
                problems, [], f"§4: staged JSON failed schemas: {problems}"
            )

    def test_committed_deploy_json_validates(self):
        """§15: schema validation of every committed deployment JSON."""
        from scripts.prepare_deployment import _validate_staged_json
        problems = _validate_staged_json(COMMITTED_DEPLOY)
        self.assertEqual(
            problems, [],
            f"§15: committed deploy/ JSON failed schemas: {problems}",
        )

    def test_every_staged_json_is_parseable(self):
        bad = []
        for path in sorted(COMMITTED_DEPLOY.rglob("*.json")):
            try:
                _json.loads(path.read_text())
            except _json.JSONDecodeError as exc:
                bad.append(f"{path.relative_to(COMMITTED_DEPLOY)}: {exc}")
        self.assertEqual(bad, [], f"unparseable JSON in deploy/: {bad}")


class TestCommittedDeployEqualsFreshBuild(unittest.TestCase):
    """§6: the committed tree must equal a fresh deterministic build.

    No exemption list. An earlier revision stamped a build timestamp
    into the staging sentinel, which made the committed tree provably
    unequal to any rebuild — the one file that could never match. The
    sentinel is now deterministic, so this compares the WHOLE tree.
    """

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.fresh = Path(cls._tmp.name) / "deploy"
        prepare_deployment(cls.fresh)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _rel_files(self, root: Path):
        return sorted(
            str(p.relative_to(root))
            for p in root.rglob("*") if p.is_file()
        )

    def test_committed_deploy_exists(self):
        self.assertTrue(
            COMMITTED_DEPLOY.is_dir(),
            "§6: deploy/ must be committed",
        )

    def test_file_sets_are_identical(self):
        committed = self._rel_files(COMMITTED_DEPLOY)
        fresh = self._rel_files(self.fresh)
        self.assertEqual(
            committed, fresh,
            "§6: committed deploy/ file set differs from a fresh build. "
            "Regenerate with `python -m scripts.prepare_deployment "
            "--output-dir deploy --verify`; do not hand-edit deploy/.",
        )

    def test_every_file_is_byte_identical(self):
        differing = []
        for rel in self._rel_files(self.fresh):
            a = COMMITTED_DEPLOY / rel
            b = self.fresh / rel
            if not a.exists():
                differing.append(f"{rel} (absent from committed tree)")
            elif not filecmp.cmp(a, b, shallow=False):
                differing.append(rel)
        self.assertEqual(
            differing, [],
            f"§6: committed deploy/ is not byte-identical to a fresh "
            f"build: {differing}",
        )

    def test_sentinel_is_deterministic(self):
        """§6: the sentinel is the only non-public packaging file.

        It is exempt from nothing; its generated contents must be
        deterministic, which is what makes the whole-tree comparison
        above possible.
        """
        a = (COMMITTED_DEPLOY / STAGING_SENTINEL).read_text()
        b = (self.fresh / STAGING_SENTINEL).read_text()
        self.assertEqual(a, b)
        payload = _json.loads(b)
        self.assertNotIn(
            "created_at_utc", payload,
            "§6: the sentinel must not carry a build timestamp; it makes "
            "the committed tree unequal to every rebuild.",
        )

    def test_committed_tree_verifies(self):
        problems = verify_deployment(COMMITTED_DEPLOY)
        self.assertEqual(
            problems, [],
            f"§6: committed deploy/ failed verification: {problems}",
        )

    def test_two_successive_builds_are_byte_identical(self):
        """§6: prove the second build is identical."""
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one"
            second = Path(tmp) / "two"
            prepare_deployment(first)
            prepare_deployment(second)
            self.assertEqual(
                self._rel_files(first), self._rel_files(second)
            )
            for rel in self._rel_files(first):
                with self.subTest(rel=rel):
                    self.assertTrue(
                        filecmp.cmp(first / rel, second / rel, shallow=False),
                        f"{rel} differs between two successive builds",
                    )


class TestDestructiveSafety(unittest.TestCase):
    """§5: fail-closed staging. The builder must refuse dangerous targets.

    Every case seeds a marker file (or relies on the repository's own
    contents) and asserts it survives, so a test failure means real
    data loss was possible rather than merely that a message changed.
    """

    def test_refuses_filesystem_root(self):
        with self.assertRaises(StageError) as ctx:
            prepare_deployment(Path("/"))
        self.assertIn("filesystem root", str(ctx.exception))

    def test_refuses_user_home(self):
        with self.assertRaises(StageError) as ctx:
            prepare_deployment(Path.home())
        self.assertIn("home", str(ctx.exception))

    def test_refuses_repository_root_without_touching_it(self):
        marker = REPO_ROOT / "README.md"
        before = marker.read_bytes()
        with self.assertRaises(StageError) as ctx:
            prepare_deployment(REPO_ROOT)
        self.assertIn("repository root", str(ctx.exception))
        self.assertEqual(
            marker.read_bytes(), before,
            "§5: refusing the repository root must not modify it",
        )

    def test_refuses_parent_of_repository(self):
        with self.assertRaises(StageError) as ctx:
            prepare_deployment(REPO_ROOT.parent)
        self.assertIn("ancestor", str(ctx.exception))

    def test_refuses_dot_when_cwd_is_the_repo(self):
        """§5: `.` must be refused (it resolves to the repository root)."""
        cwd = _os.getcwd()
        try:
            _os.chdir(REPO_ROOT)
            with self.assertRaises(StageError):
                prepare_deployment(Path("."))
        finally:
            _os.chdir(cwd)

    def test_refuses_unrelated_seeded_directory_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            victim = Path(tmp) / "someone_elses_data"
            victim.mkdir()
            marker = victim / "PRECIOUS.txt"
            marker.write_text("do not delete me")
            (victim / "nested").mkdir()
            (victim / "nested" / "also_precious.txt").write_text("keep")

            with self.assertRaises(StageError) as ctx:
                prepare_deployment(victim)
            self.assertIn(STAGING_SENTINEL, str(ctx.exception))

            self.assertTrue(marker.is_file(), "§5: marker file was deleted")
            self.assertEqual(marker.read_text(), "do not delete me")
            self.assertTrue((victim / "nested" / "also_precious.txt").is_file())

    def test_refuses_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            marker = real / "PRECIOUS.txt"
            marker.write_text("keep")
            link = Path(tmp) / "link"
            link.symlink_to(real, target_is_directory=True)

            with self.assertRaises(StageError) as ctx:
                prepare_deployment(link)
            self.assertIn("symlink", str(ctx.exception))
            self.assertTrue(marker.is_file(), "§5: symlink target was touched")

    def test_refuses_existing_file_as_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a_file"
            target.write_text("content")
            with self.assertRaises(StageError):
                prepare_deployment(target)
            self.assertEqual(target.read_text(), "content")

    def test_permits_newly_created_temporary_directory(self):
        """§5: newly created temporary test directories are permitted."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "brand_new"
            files = prepare_deployment(target)
            self.assertGreater(len(files), 0)
            self.assertTrue((target / STAGING_SENTINEL).is_file())

    def test_permits_rebuilding_a_sentinel_bearing_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "staging"
            prepare_deployment(target)
            # Second build over the same (now sentinel-bearing) target.
            files = prepare_deployment(target)
            self.assertGreater(len(files), 0)

    def test_permits_canonical_deploy_even_without_a_sentinel(self):
        """§5: the canonical deploy/ target is permitted explicitly.

        Relying on the committed sentinel alone would make the whole
        deployment pipeline fail closed if that dotfile were ever
        dropped from a commit. Verified through the guard rather than by
        rebuilding, so the test never mutates the committed tree.
        """
        reason = _forbidden_target_reason(COMMITTED_DEPLOY, REPO_ROOT)
        self.assertIsNone(
            reason,
            f"§5: canonical deploy/ must be a permitted target, got: {reason}",
        )

    def test_canonical_deploy_permission_does_not_leak_to_siblings(self):
        """A directory merely NAMED deploy/ elsewhere is not canonical."""
        with tempfile.TemporaryDirectory() as tmp:
            impostor = Path(tmp) / "deploy"
            impostor.mkdir()
            (impostor / "PRECIOUS.txt").write_text("keep")
            reason = _forbidden_target_reason(impostor, REPO_ROOT)
            self.assertIsNotNone(
                reason,
                "§5: only <repo>/deploy is canonical; a same-named "
                "directory elsewhere must still require a sentinel",
            )

    def test_failed_build_leaves_no_partial_tree(self):
        """§5: never leave a partially rebuilt tree after failure.

        The build is driven from a repo_root that has no artifacts, so
        staging raises partway through; the target must not survive.
        """
        with tempfile.TemporaryDirectory() as tmp:
            empty_repo = Path(tmp) / "empty_repo"
            (empty_repo / "data" / "outputs").mkdir(parents=True)
            target = Path(tmp) / "out"
            with self.assertRaises(Exception):
                prepare_deployment(target, repo_root=empty_repo)
            self.assertFalse(
                target.exists(),
                "§5: a failed build must not leave a partial tree",
            )
            leftovers = [
                p.name for p in Path(tmp).iterdir()
                if p.name.startswith(".out.staging-")
            ]
            self.assertEqual(
                leftovers, [], f"§5: temp staging dirs leaked: {leftovers}"
            )

    def test_dry_run_on_a_dangerous_target_is_still_harmless(self):
        marker = REPO_ROOT / "README.md"
        before = marker.read_bytes()
        prepare_deployment(REPO_ROOT, dry_run=True)
        self.assertEqual(marker.read_bytes(), before)


class TestBuilderCliSafety(unittest.TestCase):
    """The CLI must fail non-zero (not traceback) on a refused target."""

    def _run(self, *args):
        return _subprocess.run(
            [_sys.executable, "-m", "scripts.prepare_deployment", *args],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )

    def test_cli_refuses_repo_root_with_nonzero_exit(self):
        proc = self._run("--output-dir", str(REPO_ROOT))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("repository root", proc.stderr)

    def test_cli_refuses_filesystem_root_with_nonzero_exit(self):
        proc = self._run("--output-dir", "/")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("filesystem root", proc.stderr)

    def test_cli_verify_passes_on_committed_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._run(
                "--output-dir", str(Path(tmp) / "d"), "--verify"
            )
            self.assertEqual(
                proc.returncode, 0,
                f"builder --verify failed: {proc.stderr}",
            )
            self.assertIn("verification passed", proc.stdout)


if __name__ == "__main__":
    unittest.main()
