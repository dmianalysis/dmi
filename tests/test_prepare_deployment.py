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


if __name__ == "__main__":
    unittest.main()
