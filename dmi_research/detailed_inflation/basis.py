"""Active numeric-UCC accounting basis and parent reconciliation.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt section 5).

The accounting basis is the set of 2024-active *numeric* CE item codes (UCCs)
across the four target domains, for each of the six Income-Quintile
populations.

Why numeric-only selection is the correct rule
----------------------------------------------
``cx.item`` mixes two kinds of ``item_code``:

* six-digit numeric UCCs -- the leaf expenditure items BLS collects;
* alphabetic descriptive aggregates (``FOODTOTL``, ``BAKERY``, ``CEREAL``,
  ``FOODAWAY``, ...) -- published roll-ups of those leaves.

Selecting only numeric UCCs therefore satisfies the requirement that parent
descriptive aggregates and their children are never summed together, without
needing a bespoke hierarchy walk. The rule is validated empirically rather
than assumed: :func:`reconcile_to_parents` sums the selected leaves and
compares them against the published domain-root aggregate. If the numeric set
nested, the sums would overshoot materially; they do not.

Reconciliation tolerance
------------------------
Prompt section 5 requires the residual to be "explainable by BLS rounding
only" and forbids hard-coding a large tolerance. A percentage tolerance is the
wrong instrument here: a one-unit rounding residual is 0.0001% of the Housing
parent but 0.015% of the Alcoholic-beverages parent for Q1, so any single
percentage threshold either fails on rounding or passes on real errors.

The gate used instead is the exact worst case of the rounding itself. BLS
publishes aggregate expenditures rounded to whole units, so each published
figure carries at most half a unit of error. Summing ``n`` published leaves
and differencing against one published parent therefore admits a residual of
at most ``0.5 * (n + 1)`` units, and no more. Any residual beyond that bound
is provably not rounding -- a double-count of even the smallest leaf in this
universe exceeds it by orders of magnitude.

The bound is derived from the publication rounding unit, not tuned to the
data. Both the absolute and the percentage difference are still reported, as
section 5 requires.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .sources import (
    ASPECT_AGGREGATE,
    ASPECT_RSE,
    POPULATIONS,
    SUBCATEGORY_LABELS,
    AspectRecord,
    DataRecord,
    ItemRecord,
    SeriesRecord,
    is_numeric_ucc,
)

#: The unit to which BLS rounds published CE aggregate expenditures. This is a
#: documented property of the source, not a tuning parameter.
BLS_AGGREGATE_ROUNDING_UNIT = 1.0


@dataclass(frozen=True)
class BasisEntry:
    """One active numeric UCC observed for one population."""

    ucc: str
    subcategory_code: str
    domain_label: str
    population: str
    characteristics_code: str
    series_id: str
    series_title: str
    item_text: str
    display_level: int
    selectable: bool
    aggregate_expenditure: float | None
    mean_expenditure: float | None
    rse: float | None

    @property
    def has_aggregate(self) -> bool:
        return self.aggregate_expenditure is not None


@dataclass(frozen=True)
class ReconciliationResult:
    """Sum of active leaves vs the published domain-root aggregate."""

    subcategory_code: str
    domain_label: str
    population: str
    active_ucc_count: int
    missing_aggregate_count: int
    sum_active_ucc_aggregate: float
    published_parent_aggregate: float | None
    parent_series_id: str | None

    @property
    def absolute_difference(self) -> float | None:
        if self.published_parent_aggregate is None:
            return None
        return self.sum_active_ucc_aggregate - self.published_parent_aggregate

    @property
    def percent_difference(self) -> float | None:
        if self.published_parent_aggregate in (None, 0):
            return None
        return 100.0 * self.absolute_difference / self.published_parent_aggregate

    @property
    def published_leaf_count(self) -> int:
        """Leaves that actually carry a published aggregate.

        Suppressed leaves contribute neither a value nor a rounding error.
        """
        return self.active_ucc_count - self.missing_aggregate_count

    def rounding_bound(
        self, rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT
    ) -> float:
        """Worst-case residual attributable to publication rounding alone."""
        return 0.5 * rounding_unit * (self.published_leaf_count + 1)

    def within_rounding(
        self, rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT
    ) -> bool:
        difference = self.absolute_difference
        if difference is None:
            return False
        return abs(difference) <= self.rounding_bound(rounding_unit)


@dataclass
class Basis:
    """The full accounting basis plus its reconciliation diagnostics."""

    entries: list[BasisEntry] = field(default_factory=list)
    reconciliations: list[ReconciliationResult] = field(default_factory=list)

    @property
    def active_uccs(self) -> list[str]:
        """Distinct active UCCs, sorted. Identical across populations."""
        return sorted({entry.ucc for entry in self.entries})

    @property
    def active_ucc_count(self) -> int:
        return len(self.active_uccs)

    def for_population(self, population: str) -> list[BasisEntry]:
        return [entry for entry in self.entries if entry.population == population]

    def failed_reconciliations(
        self, rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT
    ) -> list[ReconciliationResult]:
        return [
            r for r in self.reconciliations if not r.within_rounding(rounding_unit)
        ]


class DuplicateUccError(ValueError):
    """Raised when one population would contribute a UCC more than once."""


def build_basis(
    target_series: Iterable[SeriesRecord],
    items: dict[tuple[str, str], ItemRecord],
    aspects: dict[tuple[str, str], AspectRecord],
    data: dict[str, DataRecord] | None = None,
) -> Basis:
    """Assemble the active numeric-UCC basis and reconcile it to parents."""
    target_series = list(target_series)
    data = data or {}

    entries: list[BasisEntry] = []
    seen: set[tuple[str, str]] = set()

    for record in target_series:
        if not is_numeric_ucc(record.item_code):
            continue
        key = (record.characteristics_code, record.item_code)
        if key in seen:
            raise DuplicateUccError(
                f"UCC {record.item_code} appears more than once for population "
                f"{POPULATIONS[record.characteristics_code]} "
                f"(series {record.series_id}). The accounting basis must "
                "contain each UCC exactly once per population."
            )
        seen.add(key)

        item = items.get((record.subcategory_code, record.item_code))
        if item is None:
            raise KeyError(
                f"UCC {record.item_code} in subcategory "
                f"{record.subcategory_code} (series {record.series_id}) has no "
                "row in cx.item. Refusing to include an item with no "
                "authoritative description."
            )

        aggregate = aspects.get((record.series_id, ASPECT_AGGREGATE))
        rse = aspects.get((record.series_id, ASPECT_RSE))
        mean = data.get(record.series_id)

        entries.append(
            BasisEntry(
                ucc=record.item_code,
                subcategory_code=record.subcategory_code,
                domain_label=SUBCATEGORY_LABELS[record.subcategory_code],
                population=record.population,
                characteristics_code=record.characteristics_code,
                series_id=record.series_id,
                series_title=record.series_title,
                item_text=item.item_text,
                display_level=item.display_level,
                selectable=item.selectable,
                aggregate_expenditure=aggregate.value if aggregate else None,
                mean_expenditure=mean.value if mean else None,
                rse=rse.value if rse else None,
            )
        )

    entries.sort(key=lambda e: (e.characteristics_code, e.subcategory_code, e.ucc))

    reconciliations = reconcile_to_parents(target_series, entries, aspects)
    return Basis(entries=entries, reconciliations=reconciliations)


def find_parent_series(
    target_series: Iterable[SeriesRecord],
    subcategory_code: str,
    characteristics_code: str,
) -> SeriesRecord | None:
    """Return the published domain-root series for a domain and population.

    The domain root is the series whose ``item_code`` equals the
    ``subcategory_code`` itself (e.g. ``FOODTOTL``/``FOODTOTL``).
    """
    for record in target_series:
        if (
            record.subcategory_code == subcategory_code
            and record.item_code == subcategory_code
            and record.characteristics_code == characteristics_code
        ):
            return record
    return None


def reconcile_to_parents(
    target_series: Iterable[SeriesRecord],
    entries: Iterable[BasisEntry],
    aspects: dict[tuple[str, str], AspectRecord],
) -> list[ReconciliationResult]:
    """Compare summed active leaves against published parent aggregates."""
    target_series = list(target_series)
    entries = list(entries)

    results: list[ReconciliationResult] = []
    for characteristics_code, population in POPULATIONS.items():
        for subcategory_code, domain_label in SUBCATEGORY_LABELS.items():
            scoped = [
                entry
                for entry in entries
                if entry.characteristics_code == characteristics_code
                and entry.subcategory_code == subcategory_code
            ]
            if not scoped:
                continue
            parent = find_parent_series(
                target_series, subcategory_code, characteristics_code
            )
            parent_aspect = (
                aspects.get((parent.series_id, ASPECT_AGGREGATE)) if parent else None
            )
            results.append(
                ReconciliationResult(
                    subcategory_code=subcategory_code,
                    domain_label=domain_label,
                    population=population,
                    active_ucc_count=len(scoped),
                    missing_aggregate_count=sum(
                        1 for entry in scoped if not entry.has_aggregate
                    ),
                    sum_active_ucc_aggregate=sum(
                        entry.aggregate_expenditure or 0.0 for entry in scoped
                    ),
                    published_parent_aggregate=(
                        parent_aspect.value if parent_aspect else None
                    ),
                    parent_series_id=parent.series_id if parent else None,
                )
            )
    return results
