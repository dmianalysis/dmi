"""Loader for the pinned, normalized BLS UCC -> ELI concordance.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt section 3).

The audit joins against the normalized TSV produced by
``scripts/import_ucc_eli_concordance.py`` rather than re-parsing the BLS
workbook on every run. Provenance back to the official publication lives in
the sidecar ``*.provenance.json``.

Attribution: the concordance is a publication of the U.S. Bureau of Labor
Statistics.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONCORDANCE_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "research"
    / "ucc_eli_concordance_2024_v0_1.tsv"
)

UCC_RE = re.compile(r"^[0-9]{6}$")
ELI_RE = re.compile(r"^[A-Z]{2}[0-9]{3}$")

EXPECTED_COLUMNS = (
    "ucc",
    "eli",
    "ucc_title",
    "eli_title",
    "ce_source",
    "multi_eli_footnote",
)


@dataclass(frozen=True)
class ConcordanceEntry:
    """All ELI destinations pinned for one UCC."""

    ucc: str
    ucc_title: str
    elis: tuple[str, ...]
    eli_titles: tuple[str, ...]
    ce_source: str
    multi_eli_footnote: bool


@dataclass(frozen=True)
class Concordance:
    """The pinned concordance, keyed by UCC."""

    entries: dict[str, ConcordanceEntry]
    source_path: str
    provenance: dict

    def get(self, ucc: str) -> ConcordanceEntry | None:
        return self.entries.get(ucc)

    def destinations(self, ucc: str) -> tuple[str, ...]:
        entry = self.entries.get(ucc)
        return entry.elis if entry else ()

    @property
    def distinct_elis(self) -> frozenset[str]:
        return frozenset(eli for entry in self.entries.values() for eli in entry.elis)


class ConcordanceError(ValueError):
    """Raised when the pinned concordance artifact is malformed."""


def load_concordance(path: Path = DEFAULT_CONCORDANCE_PATH) -> Concordance:
    """Load the normalized concordance TSV and its provenance sidecar."""
    if not path.is_file():
        raise FileNotFoundError(
            f"Pinned concordance not found: {path}. Generate it with "
            "scripts/import_ucc_eli_concordance.py."
        )

    grouped: dict[str, list[tuple[str, str]]] = {}
    titles: dict[str, str] = {}
    sources: dict[str, str] = {}
    footnotes: dict[str, bool] = {}

    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise ConcordanceError(
                f"{path.name}: expected columns {EXPECTED_COLUMNS}, found "
                f"{tuple(reader.fieldnames or ())}."
            )
        for line_number, row in enumerate(reader, start=2):
            ucc = (row["ucc"] or "").strip()
            eli = (row["eli"] or "").strip()
            if not UCC_RE.match(ucc):
                raise ConcordanceError(
                    f"{path.name} line {line_number}: malformed UCC {ucc!r}."
                )
            if not ELI_RE.match(eli):
                raise ConcordanceError(
                    f"{path.name} line {line_number}: malformed ELI {eli!r}."
                )
            pairs = grouped.setdefault(ucc, [])
            if any(existing_eli == eli for existing_eli, _ in pairs):
                raise ConcordanceError(
                    f"{path.name} line {line_number}: duplicate destination "
                    f"{eli} for UCC {ucc}."
                )
            pairs.append((eli, (row["eli_title"] or "").strip()))
            titles.setdefault(ucc, (row["ucc_title"] or "").strip())
            sources.setdefault(ucc, (row["ce_source"] or "").strip())
            footnotes[ucc] = footnotes.get(ucc, False) or (
                (row["multi_eli_footnote"] or "").strip().lower() == "true"
            )

    if not grouped:
        raise ConcordanceError(f"{path.name}: no concordance rows parsed.")

    entries = {
        ucc: ConcordanceEntry(
            ucc=ucc,
            ucc_title=titles[ucc],
            elis=tuple(eli for eli, _ in sorted(pairs)),
            eli_titles=tuple(title for _, title in sorted(pairs)),
            ce_source=sources[ucc],
            multi_eli_footnote=footnotes[ucc],
        )
        for ucc, pairs in grouped.items()
    }

    provenance_path = path.with_suffix(".provenance.json")
    provenance = (
        json.loads(provenance_path.read_text(encoding="utf-8"))
        if provenance_path.is_file()
        else {}
    )

    return Concordance(
        entries=entries, source_path=str(path), provenance=provenance
    )
