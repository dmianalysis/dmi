#!/usr/bin/env python3
"""Tests for the shelter task (Phase C of the shelter milestone).

Milestone 2 recorded the shelter-UCC record counts as a preserved manual
observation and said so plainly: ``reproduced_by_test: false``. This file is
the check that record was missing. Its job is not to agree with the preserved
numbers - agreement is cheap and a test that only agreed would pass equally
well against a broken reader - but to fail when the pinned source, the reader
or the comparison stops supporting them.

Four disciplines are checked structurally.

*The archive is verified before it is believed.* A count from an unpinned file
reproduces nothing, so tampering with a member must be detected by hash rather
than by the count looking wrong.

*Measuring and judging are separate.* The reader tallies; the comparator
decides. Mutation tests feed the comparator a measurement that disagrees with
the preserved claim and assert it says so.

*The two record counts stay distinguishable.* The preserved observation
counted all reference years; the estimator consumes only ``REF_YR == 2024``.
Those differ for every shelter UCC, and a reader that conflated them would
still reproduce the preserved number while misdescribing the estimator's
input.

*The dictionary is read, not restated.* The PUBFLAG meanings must come out of
the BLS workbook, from currently-open rows only, with the workbook's hash
checked against the source registry.
"""

from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_source as source  # noqa: E402

SHELTER_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
OBSERVATION_PATH = SHELTER_DIR / "shelter_source_observation.json"
SOURCE_REGISTRY = REPO_ROOT / "registry/research/pumd_2024_interview_source_v0_1.json"
PROVENANCE_REGISTRY = (
    REPO_ROOT / "registry/research/ucc_provenance_classes_v0_1.json"
)
DICTIONARY_PATH = (
    Path.home() / "dev/dmi-data/pumd/2024/docs/ce-pumd-interview-diary-dictionary.xlsx"
)

MTBI_COLUMNS = ["NEWID", "REF_MO", "REF_YR", "UCC", "COST", "PUBFLAG"]


def write_mtbi(directory: Path, rows_by_file: dict[str, list[dict[str, object]]]) -> None:
    """Write a synthetic MTBI file set covering every quarter the reader reads."""
    for _fmli, mtbi_name, _role in pumd.QUARTER_FILES:
        rows = rows_by_file.get(mtbi_name, [])
        with (directory / mtbi_name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MTBI_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)


def mtbi_row(newid: str, ucc: str, year: int, pubflag: str, month: int = 6) -> dict:
    return {
        "NEWID": newid,
        "REF_MO": month,
        "REF_YR": year,
        "UCC": ucc,
        "COST": "100.00",
        "PUBFLAG": pubflag,
    }


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------


class TestShelterSourceReader(unittest.TestCase):
    """The reader must tally what is there, split by year, and not judge."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_a_rows_are_counted_across_every_quarter_file(self) -> None:
        rows = {
            name: [mtbi_row(f"n{i}", "910104", 2024, "1")]
            for i, (_f, name, _r) in enumerate(pumd.QUARTER_FILES)
        }
        write_mtbi(self.directory, rows)
        observations = source.read_shelter_source(self.directory)
        observation = observations["910104"]
        self.assertEqual(
            observation.records_all_reference_years, len(pumd.QUARTER_FILES)
        )
        self.assertEqual(
            set(observation.records_by_file),
            {name for _f, name, _r in pumd.QUARTER_FILES},
        )

    def test_b_the_two_record_counts_are_reported_separately(self) -> None:
        """The estimator's input is not the preserved observation's basis.

        This is the distinction the preserved record did not draw. If the
        reader ever collapses the two, this test fails rather than the
        milestone quietly describing 45 records as the estimator's input.
        """
        write_mtbi(
            self.directory,
            {
                "mtbi241x.csv": [
                    mtbi_row("n1", "910106", 2023, "1"),
                    mtbi_row("n2", "910106", 2024, "1"),
                    mtbi_row("n3", "910106", 2025, "1"),
                ]
            },
        )
        observation = source.read_shelter_source(self.directory)["910106"]
        self.assertEqual(observation.records_all_reference_years, 3)
        self.assertEqual(observation.records_in_benchmark_year, 1)
        self.assertEqual(
            observation.records_by_reference_year, {2023: 1, 2024: 1, 2025: 1}
        )

    def test_c_distinct_newids_are_counted_not_rows(self) -> None:
        write_mtbi(
            self.directory,
            {
                "mtbi242.csv": [
                    mtbi_row("n1", "910104", 2024, "1", month=1),
                    mtbi_row("n1", "910104", 2024, "1", month=2),
                    mtbi_row("n2", "910104", 2024, "1", month=1),
                ]
            },
        )
        observation = source.read_shelter_source(self.directory)["910104"]
        self.assertEqual(observation.records_in_benchmark_year, 3)
        self.assertEqual(observation.distinct_newids_in_benchmark_year, 2)

    def test_d_a_mixed_pubflag_is_tallied_not_flattened(self) -> None:
        write_mtbi(
            self.directory,
            {
                "mtbi243.csv": [
                    mtbi_row("n1", "910104", 2024, "1"),
                    mtbi_row("n2", "910104", 2024, "2"),
                ]
            },
        )
        observation = source.read_shelter_source(self.directory)["910104"]
        self.assertEqual(observation.pubflag_tally, {"1": 1, "2": 1})
        self.assertFalse(observation.pubflag_is_uniform)
        self.assertIsNone(observation.sole_pubflag)

    def test_e_unrequested_uccs_are_ignored(self) -> None:
        write_mtbi(
            self.directory,
            {"mtbi244.csv": [mtbi_row("n1", "210110", 2024, "2")]},
        )
        observations = source.read_shelter_source(self.directory)
        self.assertNotIn("210110", observations)
        self.assertEqual(
            set(observations), set(source.OBSERVED_UCCS)
        )

    def test_f_a_missing_pubflag_column_is_a_schema_error(self) -> None:
        for _fmli, name, _role in pumd.QUARTER_FILES:
            with (self.directory / name).open("w", newline="", encoding="utf-8") as h:
                writer = csv.writer(h)
                writer.writerow(["NEWID", "REF_MO", "REF_YR", "UCC", "COST"])
        with self.assertRaises(pumd.PumdSchemaError):
            source.read_shelter_source(self.directory)

    def test_g_a_missing_member_is_unavailable_not_zero(self) -> None:
        write_mtbi(self.directory, {})
        (self.directory / pumd.QUARTER_FILES[0][1]).unlink()
        with self.assertRaises(pumd.PumdDataUnavailable):
            source.read_shelter_source(self.directory)


# --------------------------------------------------------------------------
# The archive verification
# --------------------------------------------------------------------------


class TestArchiveVerification(unittest.TestCase):
    """A count is only evidence if it came from the pinned file."""

    def test_a_the_registry_pins_every_member_the_estimator_reads(self) -> None:
        pinned = source.pinned_member_digests()
        expected = {name for _f, name, _r in pumd.QUARTER_FILES}
        self.assertEqual(set(pinned), expected)

    def test_b_a_tampered_member_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            write_mtbi(directory, {})
            with self.assertRaises(source.ShelterSourceError) as caught:
                source.verify_archive_members(directory)
            self.assertIn("not the pinned archive members", str(caught.exception))

    def test_c_an_absent_member_is_unavailable_not_a_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaises(pumd.PumdDataUnavailable):
                source.verify_archive_members(Path(name))

    def test_d_file_digest_agrees_with_hashlib(self) -> None:
        import hashlib

        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "probe.bin"
            payload = b"shelter" * 1000
            path.write_bytes(payload)
            self.assertEqual(
                source.file_digest(path), hashlib.sha256(payload).hexdigest()
            )


# --------------------------------------------------------------------------
# The comparison, and mutations of it
# --------------------------------------------------------------------------


class TestComparisonAgainstThePreservedClaim(unittest.TestCase):
    """The comparator must detect a disagreement, not merely report one."""

    def _observations(self, overrides: dict[str, dict] | None = None) -> dict:
        overrides = overrides or {}
        built = {}
        for ucc in source.OBSERVED_UCCS:
            settings = {
                "records_all_reference_years": source.PRIOR_MANUAL_RECORD_COUNTS.get(
                    ucc, 100
                ),
                "pubflag_tally": {source.PRIOR_MANUAL_PUBFLAG[ucc]: 1},
            }
            settings.update(overrides.get(ucc, {}))
            built[ucc] = source.ShelterSourceObservation(
                ucc=ucc,
                records_all_reference_years=settings["records_all_reference_years"],
                records_in_benchmark_year=1,
                distinct_newids_all_reference_years=1,
                distinct_newids_in_benchmark_year=1,
                pubflag_tally=settings["pubflag_tally"],
                records_by_file={},
                records_by_reference_year={2024: 1},
            )
        return built

    def test_a_a_faithful_measurement_reproduces(self) -> None:
        checks = source.compare_with_prior_observation(self._observations())
        self.assertEqual(source.source_verdict(checks), source.REPRODUCED)
        self.assertTrue(all(c.reproduced for c in checks))

    def test_b_every_preserved_claim_is_actually_checked(self) -> None:
        """Twelve claims exist; a comparator that checked eight would pass."""
        checks = source.compare_with_prior_observation(self._observations())
        counted = {(c.claim, c.ucc) for c in checks}
        expected = {("RECORD_COUNT", u) for u in source.SHELTER_UCCS}
        expected |= {("PUBFLAG", u) for u in source.PRIOR_MANUAL_PUBFLAG}
        self.assertEqual(counted, expected)

    def test_c_a_record_count_off_by_one_is_detected(self) -> None:
        for ucc in source.SHELTER_UCCS:
            with self.subTest(ucc=ucc):
                wrong = self._observations(
                    {
                        ucc: {
                            "records_all_reference_years": (
                                source.PRIOR_MANUAL_RECORD_COUNTS[ucc] + 1
                            )
                        }
                    }
                )
                checks = source.compare_with_prior_observation(wrong)
                self.assertEqual(source.source_verdict(checks), source.NOT_REPRODUCED)

    def test_d_a_flipped_pubflag_is_detected(self) -> None:
        for ucc in source.PRIOR_MANUAL_PUBFLAG:
            with self.subTest(ucc=ucc):
                flipped = "2" if source.PRIOR_MANUAL_PUBFLAG[ucc] == "1" else "1"
                wrong = self._observations({ucc: {"pubflag_tally": {flipped: 1}}})
                checks = source.compare_with_prior_observation(wrong)
                self.assertEqual(source.source_verdict(checks), source.NOT_REPRODUCED)

    def test_e_a_pubflag_that_is_no_longer_uniform_is_detected(self) -> None:
        """The preserved record claimed uniformity within each UCC.

        A UCC that became mixed would still contain the claimed value, so a
        comparator testing only membership would pass. It must not.
        """
        wrong = self._observations({"910106": {"pubflag_tally": {"1": 40, "2": 5}}})
        checks = source.compare_with_prior_observation(wrong)
        self.assertEqual(source.source_verdict(checks), source.NOT_REPRODUCED)
        offending = [c for c in checks if c.ucc == "910106" and c.claim == "PUBFLAG"]
        self.assertEqual(len(offending), 1)
        self.assertIn("not uniform", offending[0].note)

    def test_f_a_missing_ucc_is_a_failure_not_a_skip(self) -> None:
        observations = self._observations()
        del observations["910106"]
        checks = source.compare_with_prior_observation(observations)
        self.assertEqual(source.source_verdict(checks), source.NOT_REPRODUCED)

    def test_g_no_checks_at_all_is_not_reproduced(self) -> None:
        """An empty check list must not vacuously pass the gate."""
        self.assertEqual(source.source_verdict([]), source.NOT_REPRODUCED)

    def test_h_the_comparison_uses_the_all_reference_year_basis(self) -> None:
        """Comparing against the calendar-year count would manufacture a miss.

        The basis is fixed in advance. This asserts the comparator uses it,
        by giving a measurement whose calendar-year count equals the claim
        and whose all-year count does not.
        """
        observations = self._observations()
        observations["910106"] = source.ShelterSourceObservation(
            ucc="910106",
            records_all_reference_years=999,
            records_in_benchmark_year=source.PRIOR_MANUAL_RECORD_COUNTS["910106"],
            distinct_newids_all_reference_years=1,
            distinct_newids_in_benchmark_year=1,
            pubflag_tally={"1": 999},
            records_by_file={},
            records_by_reference_year={2024: 45},
        )
        checks = source.compare_with_prior_observation(observations)
        self.assertEqual(source.source_verdict(checks), source.NOT_REPRODUCED)
        self.assertEqual(source.PRIOR_MANUAL_COUNTING_BASIS, "ALL_REFERENCE_YEARS")

    def test_i_the_partition_corroboration_is_falsifiable(self) -> None:
        self.assertTrue(source.partition_is_corroborated(self._observations()))
        for ucc in source.OBSERVED_UCCS:
            with self.subTest(ucc=ucc):
                flipped = "2" if source.PRIOR_MANUAL_PUBFLAG[ucc] == "1" else "1"
                wrong = self._observations({ucc: {"pubflag_tally": {flipped: 1}}})
                self.assertFalse(source.partition_is_corroborated(wrong))


# --------------------------------------------------------------------------
# The preserved claims are transcribed faithfully
# --------------------------------------------------------------------------


class TestPreservedClaimsMatchTheRegistry(unittest.TestCase):
    """The target of the check must be the registry's claim, not a copy of it.

    If the module's constants drifted from the Milestone-2 registry, the check
    would reproduce something nobody ever claimed.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(PROVENANCE_REGISTRY.read_text(encoding="utf-8"))
        cls.observation = cls.registry["pumd_observations"][
            "CE_2024_INTERVIEW_MTBI_SHELTER_RENTAL_EQUIVALENCE"
        ]

    def test_a_record_counts_match_the_registry(self) -> None:
        self.assertEqual(
            {k: int(v) for k, v in self.observation["record_counts"].items()},
            dict(source.PRIOR_MANUAL_RECORD_COUNTS),
        )

    def test_b_pubflag_claims_match_the_registry(self) -> None:
        block = self.observation["pubflag"]
        transcribed = {
            ucc: block[ucc] for ucc in source.SHELTER_UCCS
        }
        transcribed.update(block["published_counterparts_for_contrast"])
        self.assertEqual(transcribed, dict(source.PRIOR_MANUAL_PUBFLAG))

    def test_c_the_four_shelter_uccs_are_the_registry_roster(self) -> None:
        correspondence = self.registry["shelter_rental_equivalence_correspondence"]
        structural = correspondence["structural_result"]
        self.assertEqual(tuple(structural["concordance_only"]), source.SHELTER_UCCS)
        self.assertEqual(
            tuple(structural["published_ce"]), source.PUBLISHED_COUNTERPART_UCCS
        )

    def test_d_the_correspondence_is_still_a_dmi_inference(self) -> None:
        """C2 must preserve this. A relabel to a BLS crosswalk is forbidden."""
        correspondence = self.registry["shelter_rental_equivalence_correspondence"]
        self.assertEqual(correspondence["claim_type"], "DMI_INFERENCE")

    def test_e_the_expected_pubflag_meanings_match_the_source_registry(self) -> None:
        registry = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
        passages = registry["documents"]["PUMD_DICTIONARY"]["passages_relied_on"]
        self.assertEqual(passages["pubflag_code_1"], "1 = Not published")
        self.assertEqual(
            passages["pubflag_code_2"], "2 = Published in Integrated Bulletin"
        )
        self.assertEqual(
            source.EXPECTED_PUBFLAG_MEANINGS["1"], "Not published"
        )
        self.assertEqual(
            source.EXPECTED_PUBFLAG_MEANINGS["2"], "Published in Integrated Bulletin"
        )


# --------------------------------------------------------------------------
# Against the real pinned archive, skipped when it is absent
# --------------------------------------------------------------------------


class TestAgainstThePinnedArchive(unittest.TestCase):
    """The check C1 exists to install. Skips cleanly when PUMD is not local."""

    @classmethod
    def setUpClass(cls) -> None:
        if not pumd.pumd_is_available():
            raise unittest.SkipTest("the 2024 Interview PUMD is not present")
        cls.directory = pumd.locate_interview_csv_dir()
        cls.digests = source.verify_archive_members(cls.directory)
        cls.observations = source.read_shelter_source(cls.directory)
        cls.checks = source.compare_with_prior_observation(cls.observations)

    def test_a_every_member_hashes_to_the_pinned_value(self) -> None:
        self.assertEqual(self.digests, source.pinned_member_digests())

    def test_b_the_preserved_record_counts_reproduce(self) -> None:
        for ucc, claimed in source.PRIOR_MANUAL_RECORD_COUNTS.items():
            with self.subTest(ucc=ucc):
                self.assertEqual(
                    self.observations[ucc].records_all_reference_years, claimed
                )

    def test_c_the_preserved_pubflag_values_reproduce(self) -> None:
        for ucc, claimed in source.PRIOR_MANUAL_PUBFLAG.items():
            with self.subTest(ucc=ucc):
                self.assertEqual(self.observations[ucc].sole_pubflag, claimed)

    def test_d_the_pubflag_partition_is_corroborated(self) -> None:
        self.assertTrue(source.partition_is_corroborated(self.observations))

    def test_e_the_verdict_is_reproduced(self) -> None:
        self.assertEqual(source.source_verdict(self.checks), source.REPRODUCED)

    def test_f_the_estimator_sees_fewer_records_than_the_preserved_claim(self) -> None:
        """The distinction is real in this archive, not hypothetical.

        Every shelter UCC has strictly fewer calendar-year-eligible rows than
        the preserved all-reference-year count. If that ever stopped being
        true the two counts would be interchangeable and the warning attached
        to them could be dropped - but it is true, so it cannot.
        """
        for ucc in source.SHELTER_UCCS:
            with self.subTest(ucc=ucc):
                observation = self.observations[ucc]
                self.assertLess(
                    observation.records_in_benchmark_year,
                    observation.records_all_reference_years,
                )

    def test_g_910106_is_the_thin_cell_and_is_thinner_still_in_scope(self) -> None:
        """C5 forbids hiding this. The test states the number it forbids hiding."""
        observation = self.observations["910106"]
        self.assertEqual(observation.records_all_reference_years, 45)
        self.assertEqual(observation.records_in_benchmark_year, 40)
        self.assertEqual(observation.distinct_newids_in_benchmark_year, 15)
        thinnest = min(
            self.observations[u].records_in_benchmark_year
            for u in source.SHELTER_UCCS
        )
        self.assertEqual(thinnest, observation.records_in_benchmark_year)


class TestPubflagDictionaryReading(unittest.TestCase):
    """The meaning of PUBFLAG=1 comes from BLS documentation, read locally."""

    @classmethod
    def setUpClass(cls) -> None:
        if not DICTIONARY_PATH.exists():
            raise unittest.SkipTest("the PUMD data dictionary is not present")
        try:
            import openpyxl  # noqa: F401
        except ImportError:  # pragma: no cover - openpyxl is a declared dep
            raise unittest.SkipTest("openpyxl is not installed")
        cls.reading = source.read_pubflag_dictionary(DICTIONARY_PATH)

    def test_a_the_workbook_is_the_pinned_one(self) -> None:
        self.assertTrue(self.reading.workbook_sha256_matches_registry)
        self.assertEqual(
            self.reading.workbook_sha256, source.pinned_dictionary_digest()
        )

    def test_b_pubflag_1_means_not_published(self) -> None:
        self.assertEqual(self.reading.code_meanings["1"], "Not published")

    def test_c_pubflag_2_means_published_in_the_integrated_bulletin(self) -> None:
        self.assertEqual(
            self.reading.code_meanings["2"], "Published in Integrated Bulletin"
        )

    def test_d_the_reading_is_of_mtbi_and_agrees_with_expectation(self) -> None:
        self.assertTrue(self.reading.agrees_with_expectation)
        self.assertEqual(
            self.reading.variable_description,
            "Is amount included in published reports?",
        )

    def test_e_only_currently_open_code_rows_were_read(self) -> None:
        """The workbook carries superseded 1980-1981 rows for the same codes.

        Reading a closed row as current would be a provenance error even
        though its meaning happens to agree, so the reader filters on an
        empty ``Last year``. This asserts the filter did work: the dictionary
        has four MTBI PUBFLAG code rows and only two are open.
        """
        self.assertEqual(len(self.reading.rows_read), 2)
        self.assertEqual(set(self.reading.code_meanings), {"1", "2"})


# --------------------------------------------------------------------------
# The emitted artifact
# --------------------------------------------------------------------------


class TestShelterSourceArtifact(unittest.TestCase):
    """What was written down must say what was measured."""

    @classmethod
    def setUpClass(cls) -> None:
        if not OBSERVATION_PATH.exists():
            raise unittest.SkipTest("the C1 source observation has not been emitted")
        cls.payload = json.loads(OBSERVATION_PATH.read_text(encoding="utf-8"))

    def test_a_the_artifact_records_reproduction(self) -> None:
        self.assertEqual(self.payload["source_reproduction_status"], source.REPRODUCED)

    def test_b_every_preserved_claim_is_recorded_as_checked(self) -> None:
        checks = self.payload["preserved_claim_checks"]
        self.assertEqual(len(checks), len(source.SHELTER_UCCS) + len(source.PRIOR_MANUAL_PUBFLAG))
        for check in checks:
            with self.subTest(claim=check["claim"], ucc=check["ucc"]):
                self.assertEqual(check["status"], source.MATCH)

    def test_c_the_artifact_pins_the_archive_members(self) -> None:
        self.assertEqual(
            self.payload["archive_members_verified"], source.pinned_member_digests()
        )

    def test_d_the_artifact_names_the_counting_basis(self) -> None:
        self.assertEqual(
            self.payload["prior_manual_counting_basis"], "ALL_REFERENCE_YEARS"
        )

    def test_e_the_artifact_carries_both_record_counts(self) -> None:
        for ucc in source.SHELTER_UCCS:
            with self.subTest(ucc=ucc):
                observation = self.payload["observations"][ucc]
                self.assertEqual(
                    observation["records_all_reference_years"],
                    source.PRIOR_MANUAL_RECORD_COUNTS[ucc],
                )
                self.assertLess(
                    observation["records_in_benchmark_year"],
                    observation["records_all_reference_years"],
                )

    def test_f_the_artifact_records_the_dictionary_reading(self) -> None:
        dictionary = self.payload["pubflag_dictionary"]
        if dictionary is None:
            self.skipTest("the dictionary was not present when C1 was run")
        self.assertTrue(dictionary["workbook_sha256_matches_registry"])
        self.assertEqual(dictionary["code_meanings"]["1"], "Not published")
        self.assertTrue(dictionary["agrees_with_expectation"])

    def test_g_no_expenditure_amount_was_written(self) -> None:
        """C1 establishes membership. Amounts are C3/C4's business.

        An unweighted COST sum written here would be read as an estimate, so
        the artifact must carry no amount field at all. The check is on keys
        rather than on the serialised text, because the text legitimately
        contains the word "meanings" and a substring scan would either fire on
        that or have to be weakened until it fired on nothing.
        """
        forbidden = {
            "cost",
            "costs",
            "expenditure",
            "expenditures",
            "amount",
            "mean",
            "aggregate",
            "total",
            "sum",
            "dollars",
        }

        def keys(node: object) -> set[str]:
            if isinstance(node, dict):
                found = {str(k).lower() for k in node}
                for value in node.values():
                    found |= keys(value)
                return found
            if isinstance(node, list):
                found: set[str] = set()
                for item in node:
                    found |= keys(item)
                return found
            return set()

        present = keys(self.payload)
        self.assertTrue(present, "the artifact has no keys; the walk is broken")
        self.assertIn("records_in_benchmark_year", present)
        self.assertEqual(sorted(present & forbidden), [])

    def test_h_each_observation_carries_only_the_declared_fields(self) -> None:
        """A field added to the observation must be considered, not absorbed."""
        import dataclasses

        expected = {f.name for f in dataclasses.fields(source.ShelterSourceObservation)}
        for ucc, observation in self.payload["observations"].items():
            with self.subTest(ucc=ucc):
                self.assertEqual(set(observation), expected)


# --------------------------------------------------------------------------
# Firewall
# --------------------------------------------------------------------------


class TestResearchFirewall(unittest.TestCase):
    """Research code stays out of the operational tree."""

    FORBIDDEN_ROOTS = ("data/outputs", "deploy/data/outputs")

    def test_a_the_shelter_module_imports_nothing_operational(self) -> None:
        text = (
            REPO_ROOT / "dmi_research/detailed_inflation/shelter_source.py"
        ).read_text(encoding="utf-8")
        for forbidden in ("dmi_calculator", "dmi_pipeline", "deploy"):
            with self.subTest(token=forbidden):
                self.assertNotIn(f"import {forbidden}", text)
                self.assertNotIn(f"from {forbidden}", text)

    def test_b_shelter_artifacts_live_under_data_research(self) -> None:
        if not SHELTER_DIR.exists():
            self.skipTest("no shelter artifacts yet")
        self.assertTrue(
            str(SHELTER_DIR.relative_to(REPO_ROOT)).startswith(
                "data/research/detailed_inflation"
            )
        )

    def test_c_nothing_was_written_to_a_forbidden_root(self) -> None:
        for root in self.FORBIDDEN_ROOTS:
            directory = REPO_ROOT / root
            if not directory.exists():
                continue
            with self.subTest(root=root):
                stray = [
                    p for p in directory.rglob("*shelter*") if p.is_file()
                ]
                self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
