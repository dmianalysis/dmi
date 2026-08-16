"""Relative-standard-error audit.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt section 12).

CE aspect type ``R0`` carries the relative standard error. A UCC is flagged
``HIGH_RSE`` when ``RSE >= 25.0``; 24.99 is not high, 25.00 is. High-RSE
records are flagged, never removed.

A missing RSE is reported as missing. It is never coerced to zero, because
zero would assert certainty that the source does not provide. Missing RSEs in
this extract coincide exactly with suppressed aggregate expenditures: BLS
suppresses both fields together for estimates that do not meet publication
standards.

Shares are computed from aggregate expenditure, not from UCC counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .basis import BasisEntry

HIGH_RSE_THRESHOLD = 25.0

#: Label used for the combined four-domain universe.
COMBINED_DOMAIN_LABEL = "ALL_DOMAINS"


def is_high_rse(rse: float | None, threshold: float = HIGH_RSE_THRESHOLD) -> bool:
    """True when ``rse`` meets or exceeds the high-RSE threshold.

    A missing RSE is not high; it is missing, and is counted separately.
    """
    return rse is not None and rse >= threshold


@dataclass(frozen=True)
class RseSummary:
    """RSE statistics for one population and one domain (or all domains)."""

    population: str
    domain_label: str
    subcategory_code: str
    active_ucc_count: int
    high_rse_ucc_count: int
    missing_rse_count: int
    missing_aggregate_count: int
    total_aggregate_expenditure: float
    high_rse_aggregate_expenditure: float
    high_rse_expenditure_share_pct: float


def _summarize(
    entries: list[BasisEntry],
    population: str,
    domain_label: str,
    subcategory_code: str,
    threshold: float,
) -> RseSummary:
    total = sum(e.aggregate_expenditure or 0.0 for e in entries)
    high = [e for e in entries if is_high_rse(e.rse, threshold)]
    high_total = sum(e.aggregate_expenditure or 0.0 for e in high)
    return RseSummary(
        population=population,
        domain_label=domain_label,
        subcategory_code=subcategory_code,
        active_ucc_count=len(entries),
        high_rse_ucc_count=len(high),
        missing_rse_count=sum(1 for e in entries if e.rse is None),
        missing_aggregate_count=sum(
            1 for e in entries if e.aggregate_expenditure is None
        ),
        total_aggregate_expenditure=total,
        high_rse_aggregate_expenditure=high_total,
        high_rse_expenditure_share_pct=(100.0 * high_total / total if total else 0.0),
    )


def build_rse_audit(
    basis_entries: Iterable[BasisEntry],
    *,
    threshold: float = HIGH_RSE_THRESHOLD,
) -> list[RseSummary]:
    """Produce per-population/per-domain and combined-domain RSE summaries."""
    entries = list(basis_entries)

    populations: list[str] = []
    for entry in entries:
        if entry.population not in populations:
            populations.append(entry.population)

    summaries: list[RseSummary] = []
    for population in populations:
        scoped = [e for e in entries if e.population == population]

        domains: list[tuple[str, str]] = []
        for entry in scoped:
            key = (entry.subcategory_code, entry.domain_label)
            if key not in domains:
                domains.append(key)
        for subcategory_code, domain_label in sorted(domains):
            members = [e for e in scoped if e.subcategory_code == subcategory_code]
            summaries.append(
                _summarize(
                    members, population, domain_label, subcategory_code, threshold
                )
            )

        summaries.append(
            _summarize(
                scoped,
                population,
                COMBINED_DOMAIN_LABEL,
                COMBINED_DOMAIN_LABEL,
                threshold,
            )
        )
    return summaries
