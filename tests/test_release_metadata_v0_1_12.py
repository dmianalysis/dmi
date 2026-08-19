#!/usr/bin/env python3
"""Release-metadata controls for the formal v0.1.12 release.

Why this file exists
--------------------
Everything about the v0.1.12 *contract* is already tested elsewhere:
`tests/test_release_evidence.py` pins the operational-specification
authority, `tests/test_specifications_manifest_coherence.py` pins the
published manifest, `tests/test_documentation_alignment.py` pins the
prose, and `tests/test_phase2_withdrawal.py` pins the withdrawal
evidence. None of those cover the thing a *formal release* adds: the
citation metadata that names the release and dates it, and the
agreement between that metadata and the changelog entry it describes.

Three controls live here.

1. `CITATION.cff` identifies version 0.1.12 and carries the real
   release date `2026-08-19`. Before the release was cut this field was
   deliberately absent (see `tests/test_citation_cff.py`); a formal
   release inverts that requirement, so it has to be asserted, not
   merely permitted.
2. The changelog's top versioned entry names the same version and the
   same date. Release metadata that disagrees with the changelog is the
   ordinary way a release date rots.
3. The operational contract is exactly two specifications. Four
   independent surfaces declare it — the Python authority, the output
   schema enum, the specifications-manifest schema enum, and the
   published manifest — and a future edit that restores a third
   (specifically Core) must fail here even if it updates only one of
   them.

DOI discipline: `CITATION.cff` carries no `doi`. The DMI concept note
has its own DOI, but a concept-note DOI is not the software-release
DOI, and no DOI has been minted for this software release. Asserting
absence keeps a plausible-looking but wrong identifier from being
pasted in later.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent.parent

RELEASE_VERSION = "0.1.12"
RELEASE_DATE = date(2026, 8, 19)

#: The operational contract. Not a convenience alias — this tuple is the
#: value every surface below is compared against, so widening it is a
#: deliberate, visible act.
OPERATIONAL_CONTRACT = ("baseline", "slack_plus")


# ---------------------------------------------------------------------
# Detector for affirmative "Core is operational" claims.
#
# Deliberately a fixed phrase list rather than a proximity heuristic.
# The release-facing documents legitimately say things like "no valid
# operational Core series exists" and "Core is withdrawn"; a detector
# that fired on `core` near `operational` would flag exactly the prose
# that states the withdrawal. These are the phrasings that could only
# appear if someone re-advertised Core.
# ---------------------------------------------------------------------
OPERATIONAL_CORE_CLAIMS = (
    "three operational specifications",
    "three specifications",
    "baseline, slack-plus, and core",
    "baseline, slack_plus, and core",
    "baseline, slack-plus, core",
    "core is an operational specification",
    "core specification is operational",
    "operational core specification",
    "core cpi specification is",
)

#: Documents that a citing reader or a release consumer reads to learn
#: what this release contains.
RELEASE_FACING_DOCS = (
    "CITATION.cff",
    "CHANGELOG.md",
    "README.md",
)


def operational_core_claims(text: str) -> list[str]:
    """Return every affirmative operational-Core phrase found in `text`."""
    lowered = text.lower()
    return [phrase for phrase in OPERATIONAL_CORE_CLAIMS if phrase in lowered]


def changelog_top_entry() -> str:
    """The first versioned `## [...]` heading, skipping `Unreleased`."""
    for line in (ROOT / "CHANGELOG.md").read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("## ["):
            continue
        if "unreleased" in stripped.lower():
            continue
        return stripped
    raise AssertionError("CHANGELOG.md has no versioned entry")


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestCitationIdentifiesTheFormalRelease(unittest.TestCase):
    """Control 1: the citation file names and dates this release."""

    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load((ROOT / "CITATION.cff").read_text())

    def test_version_is_the_release_version(self):
        self.assertEqual(
            str(self.doc.get("version")), RELEASE_VERSION,
            "CITATION.cff must identify the released version.",
        )

    def test_date_released_is_present(self):
        self.assertIn(
            "date-released", self.doc,
            "a formal release must carry `date-released`; it was held "
            "absent only while no release existed.",
        )

    def test_date_released_is_the_release_date(self):
        self.assertEqual(
            self.doc.get("date-released"), RELEASE_DATE,
            f"CITATION.cff `date-released` must be {RELEASE_DATE.isoformat()}.",
        )

    def test_date_released_parses_as_a_real_date(self):
        """A quoted string would still validate as CFF but reads as text.

        CFF consumers (Zenodo, DataCite) want an ISO-8601 date. YAML
        parses a bare `2026-08-19` into `datetime.date`; anything that
        arrives here as `str` was quoted or malformed.
        """
        self.assertIsInstance(self.doc.get("date-released"), date)

    def test_no_doi_is_claimed_for_this_software_release(self):
        self.assertNotIn(
            "doi", self.doc,
            "no DOI has been minted for the v0.1.12 software release; "
            "the concept-note DOI is a different object and must not be "
            "presented as this release's identifier.",
        )


class TestChangelogAgreesWithCitation(unittest.TestCase):
    """Control 2: changelog top entry == citation version and date."""

    def test_top_entry_is_the_released_version_and_date(self):
        self.assertEqual(
            changelog_top_entry(),
            f"## [{RELEASE_VERSION}] - {RELEASE_DATE.isoformat()}",
        )

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_top_entry_date_matches_citation_date_released(self):
        doc = yaml.safe_load((ROOT / "CITATION.cff").read_text())
        match = re.search(r"\d{4}-\d{2}-\d{2}", changelog_top_entry())
        self.assertIsNotNone(
            match, "the top changelog entry must carry a release date"
        )
        self.assertEqual(
            date.fromisoformat(match.group(0)), doc.get("date-released"),
            "the changelog release date and CITATION.cff `date-released` "
            "must be the same date.",
        )


class TestExactlyTwoOperationalSpecifications(unittest.TestCase):
    """Control 3: no surface may restore a third operational spec."""

    def test_python_authority_declares_the_contract(self):
        from scripts.release_evidence import OPERATIONAL_SPECS
        self.assertEqual(tuple(OPERATIONAL_SPECS), OPERATIONAL_CONTRACT)

    def test_output_schema_enum_declares_the_contract(self):
        schema = json.loads(
            (ROOT / "schemas" / "dmi_output.schema.json").read_text()
        )
        enum = schema["properties"]["specification"]["enum"]
        self.assertEqual(
            sorted(v for v in enum if isinstance(v, str)),
            sorted(OPERATIONAL_CONTRACT),
        )

    def test_specifications_schema_enum_declares_the_contract(self):
        schema = json.loads(
            (ROOT / "schemas" / "specifications.schema.json").read_text()
        )
        enum = (schema["properties"]["specifications"]["items"]
                ["properties"]["spec_id"]["enum"])
        self.assertEqual(sorted(enum), sorted(OPERATIONAL_CONTRACT))

    def test_published_manifest_declares_the_contract(self):
        manifest = json.loads(
            (ROOT / "data" / "outputs" / "specifications.json").read_text()
        )
        self.assertEqual(
            [s["spec_id"] for s in manifest["specifications"]],
            list(OPERATIONAL_CONTRACT),
        )

    def test_core_is_absent_from_every_surface(self):
        """The specific third specification that was withdrawn."""
        from scripts.release_evidence import OPERATIONAL_SPECS
        manifest = json.loads(
            (ROOT / "data" / "outputs" / "specifications.json").read_text()
        )
        surfaces = {
            "release_evidence.OPERATIONAL_SPECS": list(OPERATIONAL_SPECS),
            "specifications.json": [
                s["spec_id"] for s in manifest["specifications"]
            ],
        }
        for name, values in surfaces.items():
            with self.subTest(surface=name):
                self.assertNotIn("core", values)


class TestReleaseFacingDocsDoNotAdvertiseCore(unittest.TestCase):
    """Release-facing metadata must not present Core as operational."""

    def test_no_release_facing_doc_advertises_core(self):
        offenders = {}
        for rel in RELEASE_FACING_DOCS:
            found = operational_core_claims((ROOT / rel).read_text())
            if found:
                offenders[rel] = found
        self.assertEqual(
            offenders, {},
            f"release-facing documents present Core as operational: "
            f"{offenders}",
        )

    def test_readme_states_the_two_specification_contract(self):
        text = (ROOT / "README.md").read_text().lower()
        self.assertIn(
            "two specifications", text,
            "the README must state the two-specification contract "
            "plainly for a release reader.",
        )

    def test_changelog_release_entry_records_the_withdrawal(self):
        """The released state includes Core being withdrawn."""
        text = (ROOT / "CHANGELOG.md").read_text().lower()
        head = text.split("## [0.1.11]")[0]
        self.assertIn("core is withdrawn and unimplemented", head)


class TestDetectorIsNotVacuous(unittest.TestCase):
    """Mutation demonstration: the detector must catch what it claims.

    Without this, `operational_core_claims` returning `[]` for every
    input would make the control above pass forever.
    """

    def test_every_claim_phrase_is_detected(self):
        for phrase in OPERATIONAL_CORE_CLAIMS:
            with self.subTest(phrase=phrase):
                sample = f"The release publishes {phrase.upper()} today."
                self.assertEqual(
                    operational_core_claims(sample), [phrase]
                )

    def test_a_restored_three_spec_sentence_is_caught(self):
        sample = (
            "v0.1.13 publishes three operational specifications: "
            "Baseline, Slack-Plus, and Core."
        )
        found = operational_core_claims(sample)
        self.assertIn("three operational specifications", found)
        self.assertIn("baseline, slack-plus, and core", found)

    def test_withdrawal_prose_is_not_flagged(self):
        """Non-vacuity in the other direction: no false positives.

        These are real sentences from the shipped documents. A detector
        that flagged them would force the withdrawal language out of the
        very documents that must carry it.
        """
        for sample in (
            "Core is withdrawn and unimplemented; it is not an "
            "operational specification and no valid operational Core "
            "series exists.",
            "Withdraws the \"Core\" specification that appeared in "
            "earlier releases.",
            "The previously advertised Core CPI specification was "
            "withdrawn in v0.1.12.",
        ):
            with self.subTest(sample=sample[:40]):
                self.assertEqual(operational_core_claims(sample), [])


if __name__ == "__main__":
    unittest.main()
