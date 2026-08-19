#!/usr/bin/env python3
"""Evidence-based manifest URL construction (Round-4 §5).

The defect this covers
----------------------
``scripts/compute_dmi.py`` emitted a ``spec_urls`` block containing both
``baseline`` and ``slack_plus`` as literal f-strings, unconditionally.
Nothing checked that either artifact existed. A release computed before
Slack-Plus ran — or one where Slack-Plus failed — still advertised a
Slack-Plus CSV, so the public manifest pointed at a URL that 404s.

``scripts/rebuild_release_manifests.py`` did check existence, but only
existence: a truncated file, a file for the wrong period, or a
Slack-Plus artifact sitting under a Baseline filename all passed.

There is now one authority, ``scripts/release_evidence.py``, and a URL
is emitted only when the artifact exists, parses, validates, and
identifies itself as the right period and specification. These tests
exercise each of those four tests independently, because a single
"does it work" test would pass while three of them were dead code.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.release_evidence import (
    EvidenceError,
    OPERATIONAL_SPECS,
    build_spec_urls,
    raw_release_filename,
    tabular_stem,
    uses_legacy_naming,
    verify_raw_artifact,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_OUTPUTS = REPO_ROOT / "data" / "outputs"

LEGACY_PERIOD = "2025-12"      # Baseline-only, unsuffixed exports
CURRENT_PERIOD = "2026-07"     # Both specs, suffixed exports


class _Outputs:
    """A temporary ``data/outputs`` seeded from real artifacts."""

    def __init__(self, periods=(CURRENT_PERIOD,)):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        for period in periods:
            for spec in OPERATIONAL_SPECS:
                name = raw_release_filename(period, spec)
                src = REAL_OUTPUTS / name
                if src.is_file():
                    shutil.copy2(src, self.dir / name)
                stem = tabular_stem(period, spec)
                for ext in ("csv", "parquet"):
                    tab = REAL_OUTPUTS / f"{stem}.{ext}"
                    if tab.is_file():
                        shutil.copy2(tab, self.dir / f"{stem}.{ext}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False

    def raw(self, period, spec) -> Path:
        return self.dir / raw_release_filename(period, spec)

    def edit(self, period, spec, mutate):
        path = self.raw(period, spec)
        doc = json.loads(path.read_text())
        mutate(doc)
        path.write_text(json.dumps(doc, indent=2))


class TestNamingRules(unittest.TestCase):
    """Historical naming must be described by the code, not by luck."""

    def test_legacy_periods_use_unsuffixed_baseline_exports(self):
        for period in ("2025-12", "2026-01", "2026-02"):
            with self.subTest(period=period):
                self.assertTrue(uses_legacy_naming(period))
                self.assertEqual(tabular_stem(period, "baseline"),
                                 f"dmi-{period}")

    def test_modern_periods_use_suffixed_baseline_exports(self):
        for period in ("2026-03", "2026-07"):
            with self.subTest(period=period):
                self.assertFalse(uses_legacy_naming(period))
                self.assertEqual(tabular_stem(period, "baseline"),
                                 f"dmi-{period}-baseline")

    def test_slack_plus_is_always_suffixed(self):
        self.assertEqual(tabular_stem("2026-07", "slack_plus"),
                         "dmi-2026-07-slack_plus")

    def test_core_is_not_an_operational_specification(self):
        self.assertNotIn("core", OPERATIONAL_SPECS)
        with self.assertRaises(EvidenceError):
            raw_release_filename("2026-07", "core")
        with self.assertRaises(EvidenceError):
            tabular_stem("2026-07", "core")

    def test_core_cannot_be_required(self):
        with self.assertRaises(EvidenceError):
            build_spec_urls("2026-07", REAL_OUTPUTS, require=("core",))


class TestBaselineOnlyHistoricalRelease(unittest.TestCase):
    """§5: older Baseline-only releases advertise only what exists."""

    def test_legacy_release_advertises_baseline_only(self):
        urls = build_spec_urls(LEGACY_PERIOD, REAL_OUTPUTS)
        self.assertEqual(sorted(urls), ["baseline"])

    def test_legacy_release_uses_the_real_unsuffixed_filenames(self):
        urls = build_spec_urls(LEGACY_PERIOD, REAL_OUTPUTS)
        self.assertEqual(
            urls["baseline"]["csv"],
            f"/data/outputs/dmi-{LEGACY_PERIOD}.csv",
        )
        self.assertTrue(
            (REAL_OUTPUTS / f"dmi-{LEGACY_PERIOD}.csv").is_file(),
            "the advertised file must actually exist",
        )

    def test_legacy_release_never_advertises_a_phantom_slack_plus(self):
        urls = build_spec_urls(LEGACY_PERIOD, REAL_OUTPUTS)
        self.assertNotIn(
            "slack_plus", urls,
            "§5: Slack-Plus did not exist before 2026-03; advertising it "
            "would publish a URL that 404s.",
        )

    def test_legacy_baseline_without_specification_is_accepted(self):
        """Pre-multi-spec files predate specification identity entirely.

        They omit the key rather than setting it to null, so the check
        reads it with ``.get()``; both spellings mean "legacy Baseline"
        and both are accepted for pre-2026-03 periods only.
        """
        raw = REAL_OUTPUTS / raw_release_filename(LEGACY_PERIOD, "baseline")
        doc = json.loads(raw.read_text())
        self.assertIsNone(
            doc.get("specification"),
            "fixture assumption: legacy releases declare no specification",
        )
        self.assertEqual(
            verify_raw_artifact(raw, LEGACY_PERIOD, "baseline"), []
        )


class TestCompleteCurrentRelease(unittest.TestCase):
    """§5: the current release advertises both specifications."""

    def test_current_release_advertises_both_specs(self):
        urls = build_spec_urls(CURRENT_PERIOD, REAL_OUTPUTS)
        self.assertEqual(sorted(urls), ["baseline", "slack_plus"])

    def test_current_release_uses_suffixed_filenames(self):
        urls = build_spec_urls(CURRENT_PERIOD, REAL_OUTPUTS)
        self.assertEqual(
            urls["baseline"]["csv"],
            f"/data/outputs/dmi-{CURRENT_PERIOD}-baseline.csv",
        )
        self.assertEqual(
            urls["slack_plus"]["parquet"],
            f"/data/outputs/dmi-{CURRENT_PERIOD}-slack_plus.parquet",
        )

    def test_every_advertised_url_resolves(self):
        urls = build_spec_urls(CURRENT_PERIOD, REAL_OUTPUTS)
        for spec, block in urls.items():
            for kind, url in block.items():
                with self.subTest(spec=spec, kind=kind):
                    self.assertTrue(
                        (REPO_ROOT / url.lstrip("/")).is_file(),
                        f"advertised {url} does not exist",
                    )

    def test_requiring_both_specs_succeeds_on_a_complete_release(self):
        urls = build_spec_urls(
            CURRENT_PERIOD, REAL_OUTPUTS, require=OPERATIONAL_SPECS
        )
        self.assertEqual(sorted(urls), ["baseline", "slack_plus"])


class TestMissingArtifact(unittest.TestCase):
    """§5: a missing required artifact fails; a missing optional one omits."""

    def test_missing_slack_plus_is_omitted_when_not_required(self):
        with _Outputs() as out:
            out.raw(CURRENT_PERIOD, "slack_plus").unlink()
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertEqual(sorted(urls), ["baseline"])

    def test_missing_slack_plus_fails_when_required(self):
        """§5: the current release must never be published half-formed."""
        with _Outputs() as out:
            out.raw(CURRENT_PERIOD, "slack_plus").unlink()
            with self.assertRaises(EvidenceError) as ctx:
                build_spec_urls(
                    CURRENT_PERIOD, out.dir, require=OPERATIONAL_SPECS
                )
            self.assertIn("does not exist", str(ctx.exception))

    def test_missing_tabular_export_prevents_advertising(self):
        """A raw artifact without its exports must not be advertised."""
        with _Outputs() as out:
            (out.dir / f"dmi-{CURRENT_PERIOD}-slack_plus.csv").unlink()
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("slack_plus", urls)

    def test_missing_tabular_export_fails_when_required(self):
        with _Outputs() as out:
            (out.dir / f"dmi-{CURRENT_PERIOD}-baseline.parquet").unlink()
            with self.assertRaises(EvidenceError) as ctx:
                build_spec_urls(
                    CURRENT_PERIOD, out.dir, require=OPERATIONAL_SPECS
                )
            self.assertIn("missing tabular export", str(ctx.exception))


class TestMalformedArtifact(unittest.TestCase):
    """§5 test 2 and 3: parses, and validates."""

    def test_unparseable_artifact_is_not_advertised(self):
        with _Outputs() as out:
            out.raw(CURRENT_PERIOD, "slack_plus").write_text("{ nope")
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("slack_plus", urls)

    def test_unparseable_artifact_reports_a_parse_problem(self):
        with _Outputs() as out:
            path = out.raw(CURRENT_PERIOD, "slack_plus")
            path.write_text("{ nope")
            problems = verify_raw_artifact(path, CURRENT_PERIOD, "slack_plus")
            self.assertTrue(any("not valid JSON" in p for p in problems),
                            problems)

    def test_schema_invalid_artifact_is_not_advertised(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "baseline",
                     lambda d: d.pop("dmi_by_group"))
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("baseline", urls)

    def test_schema_invalid_artifact_reports_a_schema_problem(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "baseline",
                     lambda d: d.pop("dmi_by_group"))
            problems = verify_raw_artifact(
                out.raw(CURRENT_PERIOD, "baseline"), CURRENT_PERIOD, "baseline"
            )
            self.assertTrue(
                any("dmi_output.schema.json" in p for p in problems), problems
            )

    def test_truncated_artifact_fails_when_required(self):
        with _Outputs() as out:
            out.raw(CURRENT_PERIOD, "baseline").write_text("{}")
            with self.assertRaises(EvidenceError):
                build_spec_urls(
                    CURRENT_PERIOD, out.dir, require=OPERATIONAL_SPECS
                )


class TestWrongPeriodArtifact(unittest.TestCase):
    """§5 test 4a: the artifact must declare the period it is filed under."""

    def test_wrong_period_is_not_advertised(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "slack_plus",
                     lambda d: d.__setitem__("reference_period", "2026-01"))
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn(
                "slack_plus", urls,
                "§5: a file named for one period that declares another "
                "must not be advertised; the filename is not evidence.",
            )

    def test_wrong_period_reports_the_mismatch(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "slack_plus",
                     lambda d: d.__setitem__("reference_period", "2026-01"))
            problems = verify_raw_artifact(
                out.raw(CURRENT_PERIOD, "slack_plus"),
                CURRENT_PERIOD, "slack_plus",
            )
            self.assertTrue(
                any("declares reference_period" in p for p in problems),
                problems,
            )

    def test_wrong_period_fails_when_required(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "baseline",
                     lambda d: d.__setitem__("reference_period", "1999-01"))
            with self.assertRaises(EvidenceError):
                build_spec_urls(
                    CURRENT_PERIOD, out.dir, require=OPERATIONAL_SPECS
                )


class TestWrongSpecificationArtifact(unittest.TestCase):
    """§5 test 4b: the artifact must declare the specification slot it fills.

    This is the check a filename cannot perform. Copying the Slack-Plus
    output over the Baseline filename produces a file that exists,
    parses, validates, and carries the right period — and is still the
    wrong series.
    """

    def test_slack_plus_content_under_baseline_name_is_rejected(self):
        with _Outputs() as out:
            shutil.copy2(
                out.raw(CURRENT_PERIOD, "slack_plus"),
                out.raw(CURRENT_PERIOD, "baseline"),
            )
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("baseline", urls)

    def test_baseline_content_under_slack_plus_name_is_rejected(self):
        with _Outputs() as out:
            shutil.copy2(
                out.raw(CURRENT_PERIOD, "baseline"),
                out.raw(CURRENT_PERIOD, "slack_plus"),
            )
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("slack_plus", urls)

    def test_wrong_specification_reports_the_mismatch(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "slack_plus",
                     lambda d: d.__setitem__("specification", "baseline"))
            problems = verify_raw_artifact(
                out.raw(CURRENT_PERIOD, "slack_plus"),
                CURRENT_PERIOD, "slack_plus",
            )
            self.assertTrue(
                any("declares specification" in p for p in problems), problems
            )

    def test_modern_baseline_may_not_declare_null(self):
        """Only pre-2026-03 files may omit specification identity."""
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "baseline",
                     lambda d: d.__setitem__("specification", None))
            problems = verify_raw_artifact(
                out.raw(CURRENT_PERIOD, "baseline"),
                CURRENT_PERIOD, "baseline",
            )
            self.assertTrue(
                any("declares specification" in p for p in problems), problems
            )

    def test_core_labelled_artifact_is_never_accepted(self):
        with _Outputs() as out:
            out.edit(CURRENT_PERIOD, "baseline",
                     lambda d: d.__setitem__("specification", "core"))
            urls = build_spec_urls(CURRENT_PERIOD, out.dir)
            self.assertNotIn("baseline", urls)


class TestSingleAuthority(unittest.TestCase):
    """§5: no duplicated URL-construction logic anywhere."""

    def test_active_writers_do_not_build_spec_urls_themselves(self):
        """No module but the authority may compose a /data/outputs/dmi- URL."""
        import ast
        offenders = []
        for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
            if path.name == "release_evidence.py":
                continue
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                # f-strings composing an artifact URL
                if isinstance(node, ast.JoinedStr):
                    literal = "".join(
                        v.value for v in node.values
                        if isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    )
                    if "/data/outputs/dmi-" in literal:
                        offenders.append(f"{path.name}: f-string {literal!r}")
                elif isinstance(node, ast.Constant) and \
                        isinstance(node.value, str) and \
                        node.value not in docstrings and \
                        "/data/outputs/dmi-" in node.value:
                    offenders.append(f"{path.name}: literal {node.value!r}")
        self.assertEqual(
            offenders, [],
            f"§5: artifact URL construction belongs to "
            f"scripts/release_evidence.py alone. Offenders: {offenders}",
        )

    def test_rebuild_manifests_uses_the_authority(self):
        import scripts.rebuild_release_manifests as m
        self.assertEqual(
            m.build_spec_urls.__module__, "scripts.release_evidence"
        )

    def test_compute_dmi_uses_the_authority(self):
        import ast
        src = (REPO_ROOT / "scripts" / "compute_dmi.py").read_text()
        imported = set()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.ImportFrom) and node.module and \
                    "release_evidence" in node.module:
                imported |= {a.name for a in node.names}
        self.assertIn("build_spec_urls", imported)


if __name__ == "__main__":
    unittest.main()
