#!/usr/bin/env python3
"""Regression: every URL advertised by the public manifests must resolve to
a file that actually exists in `data/outputs/`.

Under repair spec §3 the public site must never advertise a URL whose
file is not present. This test loads `releases.json` and `latest.json`
and, for every release entry:

- verifies the top-level `release_note` URL points at an existing HTML
  file under `data/outputs/releases/`;
- verifies every URL inside `spec_urls.<spec_id>.{csv,parquet}` points
  at an existing file under `data/outputs/`.

Additionally, the historical baseline-only periods 2025-12..2026-02 are
expected to be labelled `legacy/unknown` (their raw release files do
not record the v0.1.12 parameter block, so retro-claiming v0.1.12 would
be dishonest).
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT / "data" / "outputs"

HISTORICAL_LEGACY_UNKNOWN = {"2025-12", "2026-01", "2026-02"}


def _url_to_path(url: str) -> Path:
    """Translate an advertised /data/outputs/... URL to a local Path."""
    prefix = "/data/outputs/"
    assert url.startswith(prefix), f"unexpected URL prefix: {url!r}"
    return OUTPUTS_DIR / url[len(prefix):]


class TestManifestUrlsResolve(unittest.TestCase):

    def _check_manifest(self, name: str) -> None:
        instance = json.loads((OUTPUTS_DIR / name).read_text())
        missing: list[str] = []
        for release in instance["releases"]:
            rid = release["release_id"]

            note_url = release.get("release_note")
            self.assertIsNotNone(
                note_url,
                f"{name}: {rid} missing top-level release_note",
            )
            if not _url_to_path(note_url).exists():
                missing.append(f"{rid}.release_note -> {note_url}")

            for spec_id, block in release.get("spec_urls", {}).items():
                for key in ("csv", "parquet"):
                    url = block.get(key)
                    self.assertIsNotNone(
                        url,
                        f"{name}: {rid}.{spec_id}.{key} missing",
                    )
                    if not _url_to_path(url).exists():
                        missing.append(
                            f"{rid}.{spec_id}.{key} -> {url}"
                        )

        if missing:
            self.fail(
                f"{name}: {len(missing)} advertised URL(s) resolve to "
                f"missing files:\n  " + "\n  ".join(missing)
            )

    def test_releases_json_urls_all_exist(self):
        self._check_manifest("releases.json")

    def test_latest_json_urls_all_exist(self):
        self._check_manifest("latest.json")


class TestHistoricalMethodologyVersion(unittest.TestCase):
    """Historical baseline-only periods must be labelled `legacy/unknown`.

    Their raw release files lack the v0.1.12 parameter block (`spec_id`,
    `slack_measure`, `inflation_measure`), so retroactively labelling
    them `v0.1.12` would misrepresent what was actually computed.
    """

    def test_historical_entries_are_legacy_unknown(self):
        releases = json.loads((OUTPUTS_DIR / "releases.json").read_text())
        by_id = {r["release_id"]: r for r in releases["releases"]}
        for rid in HISTORICAL_LEGACY_UNKNOWN:
            self.assertIn(rid, by_id, f"{rid} not present in releases.json")
            self.assertEqual(
                by_id[rid]["methodology_version"], "legacy/unknown",
                f"{rid}: historical entry must be labelled legacy/unknown "
                f"until raw file evidence supports a stronger claim",
            )

    def test_modern_entries_carry_v0_1_12(self):
        releases = json.loads((OUTPUTS_DIR / "releases.json").read_text())
        modern = [
            r for r in releases["releases"]
            if r["release_id"] not in HISTORICAL_LEGACY_UNKNOWN
        ]
        self.assertGreater(
            len(modern), 0,
            "expected at least one modern (post-2026-02) release entry",
        )
        for r in modern:
            self.assertEqual(
                r["methodology_version"], "v0.1.12",
                f"{r['release_id']}: modern entry must be labelled v0.1.12",
            )


if __name__ == "__main__":
    unittest.main()
