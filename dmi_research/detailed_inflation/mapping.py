"""Concordance classification: UCC -> ELI destinations -> computation node.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt sections 6, 9, 10, 11).

Classification is derived, never enumerated. The rule is:

``DIRECT``
    Every concordance destination collapses to one computation node, and
    there is exactly one destination ELI.

``MULTI_SAME_NODE``
    More than one destination ELI, but all destinations collapse to the same
    computation node.

``UNRESOLVED`` (preliminary)
    No concordance row at all, or destinations that cross computation nodes.

``TRANSFORMED`` and ``OUT_OF_SCOPE`` are never assigned by Milestone 1. A UCC
with no concordance row is not synonymous with out-of-scope; it enters the
exception ledger for later economic analysis.

Expenditure is never renormalized here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .basis import BasisEntry
from .concordance import Concordance
from .taxonomy import EliNodeResolver, MappingStatus


class ExceptionReason(str, Enum):
    """Why a UCC landed in the exception ledger."""

    NO_CONCORDANCE = "NO_CONCORDANCE"
    CROSS_NODE_MULTI_MAP = "CROSS_NODE_MULTI_MAP"


@dataclass(frozen=True)
class UccMapping:
    """The derived mapping for one active UCC."""

    ucc: str
    ucc_title: str
    subcategory_code: str
    domain_label: str
    elis: tuple[str, ...]
    eli_titles: tuple[str, ...]
    nodes: tuple[str, ...]
    status: MappingStatus
    node: str | None
    exception_reason: ExceptionReason | None
    multi_eli_footnote: bool

    @property
    def destination_count(self) -> int:
        return len(self.elis)


def classify_ucc(
    ucc: str,
    concordance: Concordance,
    resolver: EliNodeResolver,
) -> tuple[MappingStatus, str | None, tuple[str, ...], ExceptionReason | None]:
    """Classify one UCC from its concordance destinations.

    Returns ``(status, node, destination_nodes, exception_reason)``.
    """
    entry = concordance.get(ucc)
    if entry is None or not entry.elis:
        return MappingStatus.UNRESOLVED, None, (), ExceptionReason.NO_CONCORDANCE

    # Preserve destination order; deduplicate node ids while keeping order so
    # the audit export is stable and readable.
    nodes: list[str] = []
    for eli in entry.elis:
        node = resolver.resolve(eli)
        if node not in nodes:
            nodes.append(node)
    destination_nodes = tuple(nodes)

    if len(destination_nodes) > 1:
        return (
            MappingStatus.UNRESOLVED,
            None,
            destination_nodes,
            ExceptionReason.CROSS_NODE_MULTI_MAP,
        )

    node = destination_nodes[0]
    if len(entry.elis) == 1:
        return MappingStatus.DIRECT, node, destination_nodes, None
    return MappingStatus.MULTI_SAME_NODE, node, destination_nodes, None


def build_mappings(
    basis_entries: Iterable[BasisEntry],
    concordance: Concordance,
    resolver: EliNodeResolver,
) -> list[UccMapping]:
    """Classify every distinct active UCC in the basis.

    Mapping is a property of the UCC, not of the population, so this collapses
    the per-population basis to its distinct UCCs.
    """
    seen: dict[str, BasisEntry] = {}
    for entry in basis_entries:
        seen.setdefault(entry.ucc, entry)

    mappings: list[UccMapping] = []
    for ucc in sorted(seen):
        source = seen[ucc]
        status, node, nodes, reason = classify_ucc(ucc, concordance, resolver)
        conc_entry = concordance.get(ucc)
        mappings.append(
            UccMapping(
                ucc=ucc,
                ucc_title=conc_entry.ucc_title if conc_entry else source.item_text,
                subcategory_code=source.subcategory_code,
                domain_label=source.domain_label,
                elis=conc_entry.elis if conc_entry else (),
                eli_titles=conc_entry.eli_titles if conc_entry else (),
                nodes=nodes,
                status=status,
                node=node,
                exception_reason=reason,
                multi_eli_footnote=(
                    conc_entry.multi_eli_footnote if conc_entry else False
                ),
            )
        )
    return mappings


@dataclass(frozen=True)
class StatusSummary:
    """Counts and expenditure shares for one mapping status, one population."""

    population: str
    status: MappingStatus
    ucc_count: int
    aggregate_expenditure: float
    expenditure_share_pct: float


def summarize_status(
    basis_entries: Iterable[BasisEntry],
    mappings: Iterable[UccMapping],
) -> list[StatusSummary]:
    """Summarize mapping status by count and by expenditure share.

    Shares are expressed against the total active-UCC aggregate expenditure
    for the population. Suppressed aggregates contribute zero to the numerator
    and the denominator alike; they are reported separately as missing rather
    than imputed.
    """
    status_by_ucc = {mapping.ucc: mapping.status for mapping in mappings}
    entries = list(basis_entries)

    populations: list[str] = []
    for entry in entries:
        if entry.population not in populations:
            populations.append(entry.population)

    summaries: list[StatusSummary] = []
    for population in populations:
        scoped = [e for e in entries if e.population == population]
        total = sum(e.aggregate_expenditure or 0.0 for e in scoped)
        for status in MappingStatus:
            members = [e for e in scoped if status_by_ucc.get(e.ucc) is status]
            if not members and status not in (
                MappingStatus.DIRECT,
                MappingStatus.MULTI_SAME_NODE,
                MappingStatus.UNRESOLVED,
            ):
                continue
            aggregate = sum(e.aggregate_expenditure or 0.0 for e in members)
            summaries.append(
                StatusSummary(
                    population=population,
                    status=status,
                    ucc_count=len(members),
                    aggregate_expenditure=aggregate,
                    expenditure_share_pct=(
                        100.0 * aggregate / total if total else 0.0
                    ),
                )
            )
    return summaries


@dataclass(frozen=True)
class ExceptionEntry:
    """One row of the exception ledger."""

    ucc: str
    ucc_title: str
    subcategory_code: str
    domain_label: str
    reason: ExceptionReason
    elis: tuple[str, ...]
    nodes: tuple[str, ...]
    all_cu_aggregate_expenditure: float | None
    preliminary_status: MappingStatus
    resolution_note: str


NO_CONCORDANCE_NOTE = (
    "No row in the pinned 2024 UCC-ELI concordance. Preliminary UNRESOLVED. "
    "Final classification as TRANSFORMED or OUT_OF_SCOPE requires CE/CPI "
    "scope rules that are out of scope for Milestone 1; it must not be "
    "assumed here."
)

CROSS_NODE_NOTE = (
    "Concordance destinations span more than one candidate computation node. "
    "Allocating expenditure across nodes requires the BLS special adjustment "
    "factors, which are not part of the published concordance."
)


def build_exception_ledger(
    mappings: Iterable[UccMapping],
    basis_entries: Iterable[BasisEntry],
    *,
    reference_population: str = "All Consumer Units",
) -> list[ExceptionEntry]:
    """Collect every UCC that Milestone 1 could not resolve."""
    reference = {
        entry.ucc: entry.aggregate_expenditure
        for entry in basis_entries
        if entry.population == reference_population
    }
    ledger: list[ExceptionEntry] = []
    for mapping in mappings:
        if mapping.exception_reason is None:
            continue
        note = (
            NO_CONCORDANCE_NOTE
            if mapping.exception_reason is ExceptionReason.NO_CONCORDANCE
            else CROSS_NODE_NOTE
        )
        ledger.append(
            ExceptionEntry(
                ucc=mapping.ucc,
                ucc_title=mapping.ucc_title,
                subcategory_code=mapping.subcategory_code,
                domain_label=mapping.domain_label,
                reason=mapping.exception_reason,
                elis=mapping.elis,
                nodes=mapping.nodes,
                all_cu_aggregate_expenditure=reference.get(mapping.ucc),
                preliminary_status=mapping.status,
                resolution_note=note,
            )
        )
    ledger.sort(key=lambda e: (e.reason.value, e.ucc))
    return ledger
