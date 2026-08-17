"""Which BLS universe does a UCC belong to?

Detailed Inflation Substrate v0.1, Milestone 2.

Milestone 1 built its accounting basis from the published CE item file
``cx.item`` and treated a UCC missing from that file as a fatal error. That is
right for the basis and wrong as a general assumption: the CPI's own UCC->ELI
concordance names UCCs that ``cx.item`` does not contain, and every one of them
resolves to a live DMI computation node. A pipeline keyed on ``cx.item`` would
omit them without raising anything.

This module names the two universes and their overlap so that assumption cannot
be made silently:

``DIRECT_CONCORDANCE_UCC``
    In both. A published annual aggregate and a CPI destination both exist.
``PUBLISHED_CE_UCC``
    Published only. Usable as a validation counterpart, but the CPI draws no
    weight directly from it.
``CPI_ADJUSTED_PUMD_UCC``
    Concordance only. The CPI uses it; LABSTAT publishes no aggregate for it.

The class is *derived* from set membership, never hand-assigned, so it cannot
drift from the sources. The registry pins the expected result so that a change
of concordance vintage or ``cx.item`` extract is caught rather than absorbed.

This classification is descriptive. It authorizes no expenditure amount and
changes no Milestone-1 or Milestone-2 result.

Attribution: ``cx.item`` and the concordance are publications of the U.S.
Bureau of Labor Statistics. The three class names are DMI research vocabulary.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .concordance import Concordance
from .sources import is_numeric_ucc
from .taxonomy import EliNodeResolver, UnknownEliError

PROVENANCE_CLASSES_PATH = (
    Path(__file__).resolve().parents[2]
    / "registry"
    / "research"
    / "ucc_provenance_classes_v0_1.json"
)

#: Columns of the emitted classification artifact.
PROVENANCE_CSV_COLUMNS = (
    "ucc",
    "provenance_class",
    "in_published_ce",
    "in_concordance",
    "published_title",
    "concordance_title",
    "elis",
    "dmi_node",
    "ce_source",
)


class UccProvenanceError(ValueError):
    """Raised when the derived classification contradicts the pinned registry."""


class UccProvenanceClass(str, Enum):
    """Which BLS universe a UCC belongs to."""

    #: Published in cx.item and mapped by the concordance.
    DIRECT_CONCORDANCE_UCC = "DIRECT_CONCORDANCE_UCC"
    #: Published in cx.item, absent from the concordance.
    PUBLISHED_CE_UCC = "PUBLISHED_CE_UCC"
    #: Named by the concordance, absent from cx.item.
    CPI_ADJUSTED_PUMD_UCC = "CPI_ADJUSTED_PUMD_UCC"


@dataclass(frozen=True)
class UccProvenanceRow:
    """The provenance class of one UCC, with the evidence for it."""

    ucc: str
    provenance_class: UccProvenanceClass
    in_published_ce: bool
    in_concordance: bool
    published_title: str
    concordance_title: str
    elis: tuple
    dmi_node: Optional[str]
    ce_source: str


@dataclass(frozen=True)
class UccProvenanceReport:
    """The full partition, plus the counts the registry pins."""

    rows: tuple
    counts: Mapping

    def by_class(self, provenance_class: UccProvenanceClass) -> tuple:
        return tuple(
            row for row in self.rows if row.provenance_class is provenance_class
        )

    def uccs_in(self, provenance_class: UccProvenanceClass) -> tuple:
        return tuple(row.ucc for row in self.by_class(provenance_class))


def load_provenance_classes(path: Path = PROVENANCE_CLASSES_PATH) -> dict:
    """Load the pinned classification registry."""
    if not path.is_file():
        raise FileNotFoundError(f"UCC provenance registry not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def published_ucc_universe(item_codes: Iterable[str]) -> frozenset:
    """The six-digit numeric UCCs among ``cx.item`` item codes.

    Non-numeric codes in ``cx.item`` are parent aggregates such as ``FOODTOTL``,
    not UCCs, so including them would compare two different kinds of thing.
    """
    return frozenset(code for code in item_codes if is_numeric_ucc(code))


def classify_ucc_provenance(
    concordance: Concordance,
    item_codes: Iterable[str],
    *,
    item_titles: Optional[Mapping] = None,
    resolver: Optional[EliNodeResolver] = None,
) -> UccProvenanceReport:
    """Partition the union of the two BLS universes into the three classes.

    ``item_codes`` is every ``item_code`` in ``cx.item``; the numeric filter is
    applied here so callers cannot forget it. ``item_titles`` optionally maps a
    UCC to its published ``item_text``, and ``resolver`` optionally resolves the
    concordance destinations to a DMI node, so the artifact can show what would
    be lost by ignoring a class.
    """
    published = published_ucc_universe(item_codes)
    mapped = frozenset(concordance.entries)
    titles = item_titles or {}

    rows = []
    for ucc in sorted(published | mapped):
        in_published = ucc in published
        in_concordance = ucc in mapped
        if in_published and in_concordance:
            provenance_class = UccProvenanceClass.DIRECT_CONCORDANCE_UCC
        elif in_published:
            provenance_class = UccProvenanceClass.PUBLISHED_CE_UCC
        else:
            provenance_class = UccProvenanceClass.CPI_ADJUSTED_PUMD_UCC

        entry = concordance.get(ucc)
        elis = entry.elis if entry else ()
        rows.append(
            UccProvenanceRow(
                ucc=ucc,
                provenance_class=provenance_class,
                in_published_ce=in_published,
                in_concordance=in_concordance,
                published_title=titles.get(ucc, ""),
                concordance_title=entry.ucc_title if entry else "",
                elis=elis,
                dmi_node=_resolve_node(elis, resolver),
                ce_source=entry.ce_source if entry else "",
            )
        )

    counts = {
        "published_ce_universe": len(published),
        "concordance_universe": len(mapped),
        "union": len(published | mapped),
    }
    for member in UccProvenanceClass:
        counts[member.value] = sum(
            1 for row in rows if row.provenance_class is member
        )
    return UccProvenanceReport(rows=tuple(rows), counts=counts)


def _resolve_node(elis: tuple, resolver: Optional[EliNodeResolver]) -> Optional[str]:
    """The single DMI node the destinations agree on, or None.

    A UCC whose destinations straddle two nodes has no single node, and saying
    so is more useful than picking one.
    """
    if resolver is None or not elis:
        return None
    nodes = set()
    for eli in elis:
        try:
            nodes.add(resolver.resolve(eli))
        except UnknownEliError:
            return None
    return nodes.pop() if len(nodes) == 1 else None


def verify_against_registry(
    report: UccProvenanceReport, registry: Optional[Mapping] = None
) -> None:
    """Fail if the derived partition disagrees with the pinned registry.

    Two things are checked. The counts must match, so a change of concordance
    vintage or ``cx.item`` extract surfaces as an error instead of quietly
    reclassifying UCCs. And the ``CPI_ADJUSTED_PUMD_UCC`` roster must match
    exactly, because that is the class whose members are invisible to a
    ``cx.item``-keyed pipeline and therefore the one worth naming individually.
    """
    registry = registry if registry is not None else load_provenance_classes()

    expected_counts = registry.get("counts", {})
    for key, expected in expected_counts.items():
        if not isinstance(expected, int):
            continue
        actual = report.counts.get(key)
        if actual != expected:
            raise UccProvenanceError(
                f"pinned count {key}={expected} but derived {actual}. The "
                f"concordance vintage or cx.item extract has changed; update "
                f"{PROVENANCE_CLASSES_PATH.name} deliberately rather than "
                f"loosening this check."
            )

    expected_roster = tuple(
        item["ucc"]
        for item in registry.get("cpi_adjusted_pumd_uccs", {}).get("roster", ())
    )
    derived_roster = report.uccs_in(UccProvenanceClass.CPI_ADJUSTED_PUMD_UCC)
    if tuple(sorted(expected_roster)) != tuple(sorted(derived_roster)):
        difference = sorted(set(expected_roster) ^ set(derived_roster))
        raise UccProvenanceError(
            f"CPI_ADJUSTED_PUMD_UCC roster disagrees with the registry; "
            f"symmetric difference {difference}"
        )


def provenance_csv_rows(report: UccProvenanceReport) -> list:
    """Render the report as rows for ``PROVENANCE_CSV_COLUMNS``."""
    return [
        [
            row.ucc,
            row.provenance_class.value,
            "true" if row.in_published_ce else "false",
            "true" if row.in_concordance else "false",
            row.published_title,
            row.concordance_title,
            ";".join(row.elis),
            row.dmi_node or "",
            row.ce_source,
        ]
        for row in report.rows
    ]


def write_provenance_csv(report: UccProvenanceReport, path: Path) -> Path:
    """Write ``ucc_provenance_classes_2024.csv``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(PROVENANCE_CSV_COLUMNS)
        writer.writerows(provenance_csv_rows(report))
    return path


def build_ucc_provenance(
    concordance: Concordance,
    items: Mapping,
    *,
    resolver: Optional[EliNodeResolver] = None,
) -> UccProvenanceReport:
    """Classify from a loaded ``cx.item`` mapping and check it against the registry.

    ``items`` is keyed ``(subcategory_code, item_code)`` as :func:`load_items`
    returns it. A UCC can appear under several subcategories with the same text,
    so the first title seen is kept.
    """
    item_codes = []
    titles: dict = {}
    for (_subcategory, code), record in items.items():
        item_codes.append(code)
        titles.setdefault(code, record.item_text)

    report = classify_ucc_provenance(
        concordance, item_codes, item_titles=titles, resolver=resolver
    )
    verify_against_registry(report)
    return report
