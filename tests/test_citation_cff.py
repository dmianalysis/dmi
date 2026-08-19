#!/usr/bin/env python3
"""Regression coverage for `CITATION.cff` metadata correctness (§11).

The Citation File Format (CFF) drives citation tooling on GitHub,
Zenodo, and DataCite. A `date-released` field is treated as the
authoritative release date for the version stamped on the same file.
Prior to §11 this repo shipped a placeholder date (`2026-08-15`) that
predated any real v0.1.12 tag. Downstream tools consumed it as fact.

§11 removed that placeholder and held the field absent until the
release was actually cut. The v0.1.12 release is now cut, so the field
carries the real release date; what these tests pin is that the
placeholder never returns and that no date other than a real release
date is asserted. The release date itself, and its agreement with the
changelog, are pinned in `tests/test_release_metadata_v0_1_12.py`.

Additional locked-in invariants (defensive, low-cost):

- The file must remain parseable YAML.
- `cff-version` must be a supported CFF version.
- `version` must be the current DMI version.
- The Core-withdrawal note must remain in the abstract so citation
  consumers see the caveat.
"""

from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

REPO_ROOT = Path(__file__).resolve().parent.parent
CFF_PATH = REPO_ROOT / "CITATION.cff"


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestCitationCff(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.raw = CFF_PATH.read_text()
        cls.doc = yaml.safe_load(cls.raw)

    def test_file_parses_as_yaml(self):
        self.assertIsInstance(self.doc, dict)

    def test_no_placeholder_date_released(self):
        # The specific pre-§11 offending value must never resurface as
        # a placeholder date. If a real release date happens to be
        # 2026-08-15 in the future, the surrounding audit will make
        # that plain; this test only guards the placeholder path.
        self.assertNotIn(
            "date-released: 2026-08-15", self.raw,
            "§11: the 2026-08-15 placeholder date must not resurface.",
        )

    def test_date_released_is_the_real_release_date(self):
        # The v0.1.12 release is cut, so the field must be present and
        # must hold the actual release date as a parsed ISO-8601 date —
        # not a string, and not the withdrawn placeholder.
        self.assertIn(
            "date-released", self.doc,
            "§11: date-released must be present now that the release "
            "is cut.",
        )
        self.assertEqual(self.doc["date-released"], date(2026, 8, 19))

    def test_cff_version_is_supported(self):
        self.assertEqual(
            self.doc.get("cff-version"), "1.2.0",
            "§11: cff-version must remain a recognised CFF release.",
        )

    def test_version_matches_repo(self):
        self.assertEqual(
            str(self.doc.get("version")), "0.1.12",
            "§11: version field must match the current DMI version.",
        )

    def test_abstract_documents_core_withdrawal(self):
        abstract = self.doc.get("abstract", "")
        self.assertIn(
            "withdrawn", abstract.lower(),
            "§11: abstract must retain the Core-withdrawal caveat "
            "so citation consumers see it.",
        )
        self.assertIn("Core", abstract)

    def test_no_bare_placeholder_dates_at_all(self):
        # Defensive: even a *different* placeholder like `TBD` or
        # `YYYY-MM-DD` must not sneak in.
        for token in ("TBD", "TODO", "PLACEHOLDER", "YYYY-MM-DD", "unreleased"):
            self.assertNotIn(
                token.lower(),
                self.raw.lower().split("§")[0]  # ignore anything after our own § comments
                if "§" in self.raw
                else self.raw.lower(),
                f"§11: placeholder token {token!r} must not appear in "
                f"CITATION.cff outside explanatory comments.",
            )


if __name__ == "__main__":
    unittest.main()
