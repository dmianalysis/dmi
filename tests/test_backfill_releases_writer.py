#!/usr/bin/env python3
"""Writer-level coverage for ``scripts/backfill_releases.py`` (Round-3 §9).

Why this file exists
--------------------
§9 records that ``backfill_releases.py`` "can currently recreate the
historical defects" by assigning ``v0.1.12`` to every release and by
generating suffixed Baseline URLs for periods whose actual files are
unsuffixed. The remedy was to delegate manifest assembly to the central
helpers in ``rebuild_release_manifests.py``.

Delegation alone is not evidence. Before this file, the entire test
suite contained no execution of the backfill writer at all — the only
reference to it anywhere in ``tests/`` was a source-string grep in the
health-endpoint tests. A refactor that reintroduced a local
``"methodology_version": "v0.1.12"`` literal, or that rebuilt its own
URL naming, would not have failed anything.

§9 therefore requires "a temporary-directory writer test that executes
the actual backfill writer against representative legacy and modern
fixtures and validates its complete output". That is what this file
does: it builds a throwaway ``data/outputs`` tree containing both a
legacy period (unsuffixed artifacts, no v0.1.12 parameter block) and
modern periods (suffixed Baseline + Slack-Plus, full parameter block),
runs ``backfill_releases()`` against it, and asserts on the manifests
it actually wrote — including schema validation.

Fixture design
--------------
The two fixture classes encode the two historical defects:

- ``2025-12`` is a LEGACY period. Its artifacts are
  ``dmi-2025-12.{csv,parquet}`` (no ``-baseline`` suffix) and its raw
  file carries only ``alpha``/``scale_factor``/``weights_year``. A
  correct writer must advertise the unsuffixed URLs and must label it
  ``legacy/unknown``.
- ``2026-06`` and ``2026-07`` are MODERN periods with
  ``dmi-YYYY-MM-baseline.*`` plus ``dmi-YYYY-MM-slack_plus.*`` and the
  full ``spec_id``/``slack_measure``/``inflation_measure`` block. A
  correct writer must use the suffixed URLs, label them ``v0.1.12``,
  and include Slack-Plus.
- ``2026-05`` is a modern-parameter period deliberately shipped WITHOUT
  Slack-Plus artifacts, to prove Slack-Plus is included only when the
  required files exist rather than assumed from the period.
"""

from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKFILL_SRC = REPO_ROOT / "scripts" / "backfill_releases.py"
RELEASES_SCHEMA = REPO_ROOT / "schemas" / "releases.schema.json"

GROUPS = ("Q1", "Q2", "Q3", "Q4", "Q5")


def _raw_release(period: str, *, modern: bool, spec: str = "baseline") -> dict:
    """A schema-shaped raw release file.

    ``modern`` controls the presence of the v0.1.12 parameter block,
    which is the evidence ``derive_methodology_version`` reads.

    ``spec`` controls the declared specification identity. It must be
    real: §5's evidence writer refuses to advertise an artifact whose
    internal ``specification`` does not match the slot it is being
    written into, so a Slack-Plus fixture that declares itself Baseline
    is correctly dropped from ``spec_urls``.
    """
    # Descending DMI so Q1 is most pressured and Q5 least — a realistic
    # distributional shape, and it makes tilt/spread non-zero.
    by_group = []
    for idx, gid in enumerate(GROUPS):
        by_group.append({
            "group_id": gid,
            "dmi": round(9.0 - idx * 0.5, 4),
            "inflation": round(3.0 - idx * 0.1, 4),
            "slack": 4.2,
        })
    parameters = {"alpha": 0.5, "scale_factor": 2.0, "weights_year": 2023}
    if modern:
        parameters.update({
            "spec_id": spec,
            "slack_measure": "u6" if spec == "slack_plus" else "u3",
            "inflation_measure": "HEADLINE_CPI",
        })
    dmis = [g["dmi"] for g in by_group]
    return {
        "reference_period": period,
        "specification": spec if modern else None,
        "parameters": parameters,
        "dmi_by_group": by_group,
        # Schema requires a non-empty contributions array. The evidence
        # writer validates fixtures against the real schema, so a
        # placeholder that does not validate would be silently dropped
        # from spec_urls rather than failing loudly.
        "inflation_contributions": [
            {"group_id": gid, "category_id": "CPI_HOUSING",
             "contribution": 1.0}
            for gid in GROUPS
        ],
        "summary_metrics": {
            "dmi_median": sorted(dmis)[len(dmis) // 2],
            "dmi_stress": max(dmis),
            "income_pressure_spread": max(dmis) - min(dmis),
            "income_pressure_tilt": dmis[0] - dmis[-1],
            "most_pressured_group": "Q1",
            "least_pressured_group": "Q5",
        },
        "metadata": {
            "computed_at": f"{period}-15T10:00:00",
            "num_categories": 8,
            "num_groups": 5,
        },
    }


class BackfillWriterFixture(unittest.TestCase):
    """Builds a throwaway outputs tree and runs the real writer once."""

    LEGACY = "2025-12"
    MODERN_NO_SLACK = "2026-05"
    MODERN = ("2026-06", "2026-07")

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        cls.outputs = cls.root / "data" / "outputs"
        (cls.outputs / "releases").mkdir(parents=True)
        (cls.root / "web").mkdir(parents=True)
        (cls.outputs / "published").mkdir(parents=True, exist_ok=True)

        # A timeseries file for the writer's update_timeseries_json step.
        # Seeded with one stale period so the upsert path is exercised.
        (cls.outputs / "published" / "dmi_timeseries.json").write_text(
            json.dumps({
                "schema_version": "1.0.0",
                "metadata": {"specification": "BASELINE"},
                "observations_count": 1,
                "start_period": "2025-11",
                "end_period": "2025-11",
                "observations": [{
                    "period": "2025-11",
                    "group_id": "Q1",
                    "dmi": 8.0,
                    "inflation": 3.0,
                    "slack": 4.0,
                    "weights_vintage": 2023,
                }],
            }, indent=2)
        )

        # A health.json for the writer's update_health_json step.
        (cls.root / "web" / "health.json").write_text(json.dumps({
            "status": "healthy",
            "endpoints": {
                "dashboard": "/dashboard.html",
                "releases": "/data/outputs/releases.json",
                "specifications": "/data/outputs/specifications.json",
            },
        }, indent=2))

        def write_release(period: str, *, modern: bool):
            (cls.outputs / f"dmi_release_{period}.json").write_text(
                json.dumps(_raw_release(period, modern=modern), indent=2)
            )
            (cls.outputs / "releases" / f"{period}.html").write_text(
                f"<html><body>{period}</body></html>"
            )

        # Legacy period: UNSUFFIXED artifacts, no v0.1.12 parameters.
        write_release(cls.LEGACY, modern=False)
        for ext in ("csv", "parquet"):
            (cls.outputs / f"dmi-{cls.LEGACY}.{ext}").write_text("x")

        # Modern period WITHOUT slack_plus artifacts.
        write_release(cls.MODERN_NO_SLACK, modern=True)
        for ext in ("csv", "parquet"):
            (cls.outputs / f"dmi-{cls.MODERN_NO_SLACK}-baseline.{ext}").write_text("x")

        # Modern periods WITH slack_plus artifacts.
        for period in cls.MODERN:
            write_release(period, modern=True)
            for ext in ("csv", "parquet"):
                (cls.outputs / f"dmi-{period}-baseline.{ext}").write_text("x")
                (cls.outputs / f"dmi-{period}-slack_plus.{ext}").write_text("x")
            (cls.outputs / f"dmi_release_{period}_slack_plus.json").write_text(
                json.dumps(
                    _raw_release(period, modern=True, spec="slack_plus"),
                    indent=2,
                )
            )

        # Run the REAL writer from inside the throwaway tree. The writer
        # resolves web/health.json and the timeseries relative to cwd.
        from scripts.backfill_releases import backfill_releases
        cwd = os.getcwd()
        try:
            os.chdir(cls.root)
            backfill_releases(output_dir=str(cls.outputs))
        finally:
            os.chdir(cwd)

        cls.releases = json.loads(
            (cls.outputs / "releases.json").read_text()
        )
        cls.latest = json.loads((cls.outputs / "latest.json").read_text())
        cls.by_id = {r["release_id"]: r for r in cls.releases["releases"]}

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class TestBackfillWriterOutputIsValid(BackfillWriterFixture):

    def test_writer_produced_both_manifests(self):
        self.assertTrue((self.outputs / "releases.json").is_file())
        self.assertTrue((self.outputs / "latest.json").is_file())

    def test_releases_manifest_validates_against_current_schema(self):
        schema = json.loads(RELEASES_SCHEMA.read_text())
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(self.releases),
            key=lambda e: list(e.absolute_path),
        )
        self.assertEqual(
            [f"{list(e.absolute_path)}: {e.message}" for e in errors], [],
            "§9: writer output must validate against releases.schema.json",
        )

    def test_latest_manifest_validates_against_current_schema(self):
        schema = json.loads(RELEASES_SCHEMA.read_text())
        errors = sorted(
            Draft202012Validator(schema).iter_errors(self.latest),
            key=lambda e: list(e.absolute_path),
        )
        self.assertEqual(
            [f"{list(e.absolute_path)}: {e.message}" for e in errors], [],
        )

    def test_all_fixture_periods_are_present(self):
        expected = {self.LEGACY, self.MODERN_NO_SLACK, *self.MODERN}
        self.assertEqual(set(self.by_id), expected)

    def test_latest_points_at_the_newest_period(self):
        self.assertEqual(self.latest["current_release_id"], "2026-07")
        self.assertEqual(
            [r["release_id"] for r in self.latest["releases"]], ["2026-07"]
        )

    def test_manifests_declare_schema_3_0_0(self):
        """Controlling decision: releases/latest use schema 3.0.0."""
        self.assertEqual(self.releases["schema_version"], "3.0.0")
        self.assertEqual(self.latest["schema_version"], "3.0.0")


class TestBackfillWriterUsesExactHistoricalFilenames(BackfillWriterFixture):
    """§9: advertise only files that exist, under their real names."""

    def test_legacy_period_advertises_unsuffixed_baseline_urls(self):
        urls = self.by_id[self.LEGACY]["spec_urls"]["baseline"]
        self.assertEqual(
            urls["csv"], f"/data/outputs/dmi-{self.LEGACY}.csv",
            "§9: December 2025–February 2026 use legacy UNSUFFIXED "
            "filenames; a -baseline URL would name a file that does not "
            "exist.",
        )
        self.assertEqual(
            urls["parquet"], f"/data/outputs/dmi-{self.LEGACY}.parquet",
        )

    def test_modern_period_advertises_suffixed_baseline_urls(self):
        urls = self.by_id["2026-07"]["spec_urls"]["baseline"]
        self.assertEqual(
            urls["csv"], "/data/outputs/dmi-2026-07-baseline.csv"
        )
        self.assertEqual(
            urls["parquet"], "/data/outputs/dmi-2026-07-baseline.parquet"
        )

    def test_every_advertised_url_resolves_to_a_real_file(self):
        """The core §9 invariant, checked over the whole manifest."""
        missing = []
        for release in self.releases["releases"]:
            note = release.get("release_note")
            if note:
                p = self.outputs / note.replace("/data/outputs/", "")
                if not p.is_file():
                    missing.append(note)
            for spec_id, block in (release.get("spec_urls") or {}).items():
                for kind in ("csv", "parquet"):
                    url = (block or {}).get(kind)
                    if not url:
                        continue
                    p = self.outputs / url.replace("/data/outputs/", "")
                    if not p.is_file():
                        missing.append(f"{release['release_id']}/{spec_id}/{kind}: {url}")
        self.assertEqual(
            missing, [],
            f"§9: writer advertised nonexistent file(s): {missing}",
        )

    def test_no_release_advertises_a_suffixed_url_for_a_legacy_period(self):
        """Directly pins the historical defect."""
        offenders = []
        for period in ("2025-12", "2026-01", "2026-02"):
            release = self.by_id.get(period)
            if not release:
                continue
            csv = (release.get("spec_urls", {})
                   .get("baseline", {}) or {}).get("csv", "")
            if "-baseline." in csv:
                offenders.append(f"{period}: {csv}")
        self.assertEqual(
            offenders, [],
            f"§9: legacy periods must not advertise -baseline URLs: "
            f"{offenders}",
        )


class TestBackfillWriterDerivesMethodologyFromEvidence(BackfillWriterFixture):
    """§9: derive the methodology version from evidence, not a constant."""

    def test_legacy_period_is_labelled_legacy_unknown(self):
        self.assertEqual(
            self.by_id[self.LEGACY]["methodology_version"], "legacy/unknown",
            "§9: a raw file lacking the v0.1.12 parameter block must not "
            "be retroactively claimed as v0.1.12.",
        )

    def test_modern_periods_are_labelled_v0_1_12(self):
        for period in self.MODERN:
            with self.subTest(period=period):
                self.assertEqual(
                    self.by_id[period]["methodology_version"], "v0.1.12"
                )

    def test_not_every_release_got_the_same_version(self):
        """The defect was a single hardcoded label for every release."""
        versions = {
            r["release_id"]: r["methodology_version"]
            for r in self.releases["releases"]
        }
        self.assertGreater(
            len(set(versions.values())), 1,
            f"§9: the writer assigned one version to every release, which "
            f"is the original defect: {versions}",
        )


class TestBackfillWriterSlackPlusIsConditional(BackfillWriterFixture):
    """§9: include Slack-Plus only when the required artifacts exist."""

    def test_slack_plus_present_when_artifacts_exist(self):
        for period in self.MODERN:
            with self.subTest(period=period):
                self.assertIn(
                    "slack_plus", self.by_id[period]["spec_urls"]
                )

    def test_slack_plus_absent_when_artifacts_missing(self):
        self.assertNotIn(
            "slack_plus", self.by_id[self.MODERN_NO_SLACK]["spec_urls"],
            "§9: Slack-Plus must be advertised only when its artifacts "
            "exist, never inferred from the period.",
        )

    def test_legacy_period_has_no_slack_plus(self):
        self.assertNotIn(
            "slack_plus", self.by_id[self.LEGACY]["spec_urls"]
        )

    def test_no_core_spec_is_ever_advertised(self):
        for release in self.releases["releases"]:
            with self.subTest(release=release["release_id"]):
                self.assertNotIn("core", release.get("spec_urls", {}))


class TestBackfillWriterPreservesTopLevelReleaseNote(BackfillWriterFixture):
    """§9: preserve the top-level shared ``release_note``."""

    def test_every_release_has_a_top_level_release_note(self):
        for release in self.releases["releases"]:
            with self.subTest(release=release["release_id"]):
                self.assertIn(
                    "release_note", release,
                    "§9: release_note is a top-level field under schema "
                    "3.0.0.",
                )
                self.assertEqual(
                    release["release_note"],
                    f"/data/outputs/releases/{release['release_id']}.html",
                )

    def test_release_note_is_not_nested_inside_spec_urls(self):
        for release in self.releases["releases"]:
            for spec_id, block in (release.get("spec_urls") or {}).items():
                with self.subTest(release=release["release_id"], spec=spec_id):
                    self.assertNotIn(
                        "release_note", block or {},
                        "§9/schema 3.0.0: release_note must not be nested "
                        "per-spec.",
                    )


class TestBackfillWriterDelegatesToCentralHelpers(BackfillWriterFixture):
    """§9: the writer must not reimplement naming or version rules."""

    def setUp(self):
        self.src = BACKFILL_SRC.read_text()
        self.tree = ast.parse(self.src)
        self.code_strings = self._code_strings(self.tree)

    @staticmethod
    def _code_strings(tree: ast.AST) -> list[str]:
        """Every string literal that is NOT a docstring.

        Docstrings are excluded deliberately. This module's docstring
        explains the historical defects it fixes, and therefore quotes
        both `-baseline.` and `"methodology_version": "v0.1.12"`. A scan
        that treated prose as code would flag the very documentation
        that records the repair, so the scan targets executable string
        literals only.
        """
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        return [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value not in docstrings
        ]

    def test_imports_the_central_helpers(self):
        imported = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    "rebuild_release_manifests" in node.module:
                imported |= {a.name for a in node.names}
        self.assertTrue(
            {"assemble_manifests", "discover_releases"} <= imported,
            f"§9: backfill must delegate to the central helpers; "
            f"imported: {sorted(imported)}",
        )

    def test_no_hardcoded_methodology_version_literal(self):
        """The exact defect: `"methodology_version": "v0.1.12"`."""
        offenders = [v for v in self.code_strings if v == "v0.1.12"]
        self.assertEqual(
            offenders, [],
            "§9: backfill must derive methodology_version from evidence, "
            "never carry a v0.1.12 literal.",
        )

    def test_does_not_build_its_own_spec_urls(self):
        """No local URL construction for baseline/slack_plus artifacts."""
        offenders = [v for v in self.code_strings if "-baseline." in v]
        self.assertEqual(
            offenders, [],
            f"§9: URL naming belongs to the central helpers; found local "
            f"literals: {offenders}",
        )

    def test_code_string_scan_is_not_vacuous(self):
        """The scan must actually see this module's executable literals.

        If `_code_strings` returned nothing, both scans above would pass
        for the wrong reason.
        """
        self.assertGreater(
            len(self.code_strings), 0,
            "no non-docstring string literals found; the defect scans "
            "above would pass vacuously.",
        )
        self.assertIn(
            "data/outputs", " ".join(self.code_strings),
            "expected the writer's own path literals to be visible to "
            "the scan.",
        )

    def test_no_stale_all_three_specifications_comment(self):
        """§9: remove stale comments about completing 'all three'."""
        lowered = self.src.lower()
        for phrase in ("all three specifications", "all three specs"):
            self.assertNotIn(
                phrase, lowered,
                f"§9: stale comment about {phrase!r} must be removed; "
                f"v0.1.12 has two operational specifications.",
            )


if __name__ == "__main__":
    unittest.main()
