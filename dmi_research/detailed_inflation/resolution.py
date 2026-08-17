"""Milestone 2 scope resolution: suppression exposure, per-UCC resolution, reconciliation.

Detailed Inflation Substrate v0.1, Milestone 2 (prompt sections 16, 18, 19).

This module resolves each of the 58 Milestone-1 exception UCCs against the
pinned scope-rule registry and reports the result without normalizing weights,
acquiring CPI prices, or computing any inflation index. Core DMI remains
withdrawn and unimplemented, and nothing here is wired into ``dmi_calculator``.

Two rules govern the arithmetic here and are enforced rather than assumed:

* Spec section 16 -- a suppressed BLS observation is missing, not zero. It is
  never coerced to zero, never imputed, and always carried as a bounded
  unknown.
* Spec section 19.1 -- no expenditure may disappear. Observed CE expenditure
  must partition exactly into retained, transformed, out-of-scope and
  unresolved.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from .audit import assert_research_output_dir
from .basis import BLS_AGGREGATE_ROUNDING_UNIT, Basis
from .mapping import UccMapping
from .scope_rules import (
    RuleType,
    ScopeRule,
    ScopeRuleRegistry,
    SuppressionStatus,
    TrackBTreatment,
)
from .taxonomy import MappingStatus

ALL_CU = "All Consumer Units"
QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")
POPULATIONS = (ALL_CU, *QUINTILES)

#: A suppressed cell is judged material to the overall accounting when its
#: upper bound exceeds this share of that population's expenditure basis.
#: The bound is derived from published BLS parents, so this is a statement
#: about the published record, not a tolerance for guessing.
SUPPRESSION_BASIS_THRESHOLD_PCT = 0.05

#: A rule is judged to rely materially on suppressed data when this share or
#: more of its own possible total is unobserved. Spec section 16 requires such
#: a rule to find an alternative source, aggregate to a stable level, or stay
#: blocked.
SUPPRESSION_RULE_SHARE_THRESHOLD_PCT = 25.0


class ResolutionError(RuntimeError):
    """Raised when scope resolution cannot be completed as specified."""


# ---------------------------------------------------------------------------
# Section 16 -- suppression exposure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuppressionBound:
    """Upper bound on suppressed expenditure in one population and domain.

    BLS publishes the parent aggregate even where it suppresses child cells.
    The suppressed children therefore cannot jointly exceed the gap between the
    published parent and the sum of the published children, widened by the
    worst case of publication rounding. This bounds the unknown from the
    published record instead of assuming it away.
    """

    population: str
    subcategory_code: str
    domain_label: str
    suppressed_leaf_count: int
    published_leaf_count: int
    sum_active_aggregate: float
    published_parent_aggregate: Optional[float]
    rounding_bound: float

    @property
    def residual(self) -> Optional[float]:
        """Published parent minus the sum of published children."""
        if self.published_parent_aggregate is None:
            return None
        return self.published_parent_aggregate - self.sum_active_aggregate

    @property
    def upper_bound(self) -> Optional[float]:
        """Largest total the suppressed children could jointly take.

        A negative residual means the published children already exceed the
        parent by a rounding artifact, which bounds the suppressed total at
        zero plus the rounding allowance rather than at a negative number.
        """
        residual = self.residual
        if residual is None:
            return None
        return max(0.0, residual) + self.rounding_bound


def build_suppression_bounds(
    basis: Basis, *, rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT
) -> dict:
    """Bound suppressed expenditure for every (population, domain) pair."""
    bounds: dict = {}
    for recon in basis.reconciliations:
        key = (recon.population, recon.subcategory_code)
        if key in bounds:
            raise ResolutionError(
                f"duplicate reconciliation for {key}; the suppression bound "
                f"would be ambiguous"
            )
        bounds[key] = SuppressionBound(
            population=recon.population,
            subcategory_code=recon.subcategory_code,
            domain_label=recon.domain_label,
            suppressed_leaf_count=recon.missing_aggregate_count,
            published_leaf_count=recon.published_leaf_count,
            sum_active_aggregate=recon.sum_active_ucc_aggregate,
            published_parent_aggregate=recon.published_parent_aggregate,
            rounding_bound=recon.rounding_bound(rounding_unit),
        )
    return bounds


@dataclass(frozen=True)
class SuppressionExposure:
    """Section 16 exposure of one UCC or one rule to suppressed inputs."""

    status: SuppressionStatus
    suppressed_cells: tuple
    upper_bound_by_population: Mapping
    max_basis_share_pct: float
    max_unobserved_share_pct: float
    note: str

    @property
    def worst_upper_bound(self) -> float:
        values = [v for v in self.upper_bound_by_population.values() if v is not None]
        return max(values) if values else 0.0


def _basis_totals(basis: Basis) -> dict:
    """Observed expenditure total for each population.

    Suppressed cells contribute nothing, so these are observed totals, not
    claims about the true totals.
    """
    totals: dict = {population: 0.0 for population in POPULATIONS}
    for entry in basis.entries:
        if entry.aggregate_expenditure is not None:
            totals[entry.population] = (
                totals.get(entry.population, 0.0) + entry.aggregate_expenditure
            )
    return totals


def _classify(
    *,
    suppressed_cells: Sequence,
    bounds_by_population: Mapping,
    observed_by_population: Mapping,
    basis_totals: Mapping,
    subject: str,
    apply_unobserved_test: bool,
) -> SuppressionExposure:
    """Apply the section 16 three-way classification to one subject.

    ``apply_unobserved_test`` gates the second criterion, which asks what share
    of the subject's own possible total is unobserved. That question is only
    meaningful for a transformation spanning several cells, which is what
    section 16 asks to be classified. For a single suppressed cell the share is
    100% by construction, so applying it there would collapse the
    classification into "has a suppressed cell" and report nothing.
    """
    if not suppressed_cells:
        return SuppressionExposure(
            status=SuppressionStatus.NONE,
            suppressed_cells=(),
            upper_bound_by_population={},
            max_basis_share_pct=0.0,
            max_unobserved_share_pct=0.0,
            note=(
                f"{subject} carries a published aggregate in every population. "
                f"No suppressed input."
            ),
        )

    max_basis_share = 0.0
    max_unobserved_share = 0.0
    unbounded: list = []
    for population, bound in bounds_by_population.items():
        if bound is None:
            unbounded.append(population)
            continue
        basis_total = basis_totals.get(population)
        if basis_total:
            max_basis_share = max(max_basis_share, 100.0 * bound / basis_total)
        observed = observed_by_population.get(population, 0.0)
        denominator = observed + bound
        if denominator > 0:
            max_unobserved_share = max(
                max_unobserved_share, 100.0 * bound / denominator
            )

    if unbounded:
        return SuppressionExposure(
            status=SuppressionStatus.MATERIAL,
            suppressed_cells=tuple(suppressed_cells),
            upper_bound_by_population=dict(bounds_by_population),
            max_basis_share_pct=max_basis_share,
            max_unobserved_share_pct=100.0,
            note=(
                f"{subject} has suppressed cells in {sorted(unbounded)} where "
                f"BLS publishes no parent aggregate either, so the suppressed "
                f"amount cannot be bounded from the published record."
            ),
        )

    basis_material = max_basis_share > SUPPRESSION_BASIS_THRESHOLD_PCT
    rule_material = (
        apply_unobserved_test
        and max_unobserved_share >= SUPPRESSION_RULE_SHARE_THRESHOLD_PCT
    )
    if basis_material or rule_material:
        reasons = []
        if basis_material:
            reasons.append(
                f"the bound reaches {max_basis_share:.4f}% of the population "
                f"basis, above the {SUPPRESSION_BASIS_THRESHOLD_PCT}% threshold"
            )
        if rule_material:
            reasons.append(
                f"up to {max_unobserved_share:.1f}% of its own possible total "
                f"is unobserved, at or above the "
                f"{SUPPRESSION_RULE_SHARE_THRESHOLD_PCT}% threshold"
            )
        return SuppressionExposure(
            status=SuppressionStatus.MATERIAL,
            suppressed_cells=tuple(suppressed_cells),
            upper_bound_by_population=dict(bounds_by_population),
            max_basis_share_pct=max_basis_share,
            max_unobserved_share_pct=max_unobserved_share,
            note=(
                f"{subject} has {len(suppressed_cells)} suppressed cell(s) and "
                + " and ".join(reasons)
                + "."
            ),
        )

    return SuppressionExposure(
        status=SuppressionStatus.IMMATERIAL,
        suppressed_cells=tuple(suppressed_cells),
        upper_bound_by_population=dict(bounds_by_population),
        max_basis_share_pct=max_basis_share,
        max_unobserved_share_pct=max_unobserved_share,
        note=(
            f"{subject} has {len(suppressed_cells)} suppressed cell(s). "
            f"Bounding them by the published BLS parent caps the unknown at "
            f"{max_basis_share:.4f}% of the population basis and "
            f"{max_unobserved_share:.1f}% of its own possible total. The "
            f"suppressed cells are carried as unknown, not as zero."
        ),
    )


# ---------------------------------------------------------------------------
# Section 18 -- resolution output
# ---------------------------------------------------------------------------

RESOLUTION_CSV_COLUMNS = (
    "ucc",
    "label",
    "domain",
    "all_cu_expenditure",
    "q1_expenditure",
    "q2_expenditure",
    "q3_expenditure",
    "q4_expenditure",
    "q5_expenditure",
    "m1_status",
    "m2_track_a_status",
    "track_a_rule_id",
    "track_a_node",
    "track_b_treatment",
    "evidence_strength",
    "suppression_status",
    "notes",
)


@dataclass(frozen=True)
class ResolutionRow:
    """One resolved Milestone-1 exception, in spec section 18 column order."""

    ucc: str
    label: str
    domain: str
    expenditure_by_population: Mapping
    m1_status: MappingStatus
    m2_track_a_status: MappingStatus
    track_a_rule_id: str
    track_a_node: Optional[str]
    track_b_treatment: TrackBTreatment
    evidence_strength: str
    suppression: SuppressionExposure
    review_status: str
    rule_type: RuleType
    notes: str

    def as_csv_row(self) -> list:
        def cell(population: str) -> str:
            # Section 16: a suppressed observation is left blank. Writing 0
            # here would silently destroy expenditure.
            value = self.expenditure_by_population.get(population)
            return "" if value is None else f"{value:.1f}"

        return [
            self.ucc,
            self.label,
            self.domain,
            cell(ALL_CU),
            *(cell(q) for q in QUINTILES),
            self.m1_status.value,
            self.m2_track_a_status.value,
            self.track_a_rule_id,
            self.track_a_node or "",
            self.track_b_treatment.value,
            self.evidence_strength,
            self.suppression.status.value,
            self.notes,
        ]


# ---------------------------------------------------------------------------
# Section 19 -- reconciliation
# ---------------------------------------------------------------------------

#: Section 19.1 buckets, keyed by the final mapping status they arise from.
_RETAINED_STATUSES = frozenset({MappingStatus.DIRECT, MappingStatus.MULTI_SAME_NODE})

RECONCILIATION_CSV_COLUMNS = (
    "population",
    "ce_observed_basis",
    "retained",
    "transformed",
    "out_of_scope",
    "unresolved",
    "sum_of_buckets",
    "residual",
    "suppressed_leaf_count",
    "suppressed_upper_bound",
    "suppressed_upper_bound_pct_of_basis",
)


@dataclass(frozen=True)
class PopulationReconciliation:
    """Section 19.1 accounting identity for one population."""

    population: str
    ce_observed_basis: float
    retained: float
    transformed: float
    out_of_scope: float
    unresolved: float
    suppressed_leaf_count: int
    suppressed_upper_bound: float

    @property
    def sum_of_buckets(self) -> float:
        return self.retained + self.transformed + self.out_of_scope + self.unresolved

    @property
    def residual(self) -> float:
        return self.ce_observed_basis - self.sum_of_buckets

    @property
    def suppressed_upper_bound_pct_of_basis(self) -> float:
        if not self.ce_observed_basis:
            return 0.0
        return 100.0 * self.suppressed_upper_bound / self.ce_observed_basis

    def as_csv_row(self) -> list:
        return [
            self.population,
            f"{self.ce_observed_basis:.1f}",
            f"{self.retained:.1f}",
            f"{self.transformed:.1f}",
            f"{self.out_of_scope:.1f}",
            f"{self.unresolved:.1f}",
            f"{self.sum_of_buckets:.1f}",
            f"{self.residual:.6f}",
            str(self.suppressed_leaf_count),
            f"{self.suppressed_upper_bound:.1f}",
            f"{self.suppressed_upper_bound_pct_of_basis:.6f}",
        ]


@dataclass
class Resolution:
    """Everything Milestone 2 resolves for the non-shelter and shelter tracks."""

    rows: list = field(default_factory=list)
    rule_exposure: dict = field(default_factory=dict)
    reconciliations: list = field(default_factory=list)
    suppression_bounds: dict = field(default_factory=dict)
    replacement_accounting: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


def build_resolution(
    *,
    basis: Basis,
    mappings: Iterable[UccMapping],
    registry: ScopeRuleRegistry,
    rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT,
) -> Resolution:
    """Resolve every Milestone-1 exception against the scope-rule registry."""
    mappings = list(mappings)
    bounds = build_suppression_bounds(basis, rounding_unit=rounding_unit)
    basis_totals = _basis_totals(basis)

    # Index the basis by (ucc, population). Milestone 1 already proved UCCs are
    # unique within a population, so a collision here is a real defect.
    cells: dict = {}
    meta: dict = {}
    for entry in basis.entries:
        key = (entry.ucc, entry.population)
        if key in cells:
            raise ResolutionError(f"duplicate basis entry for {key}")
        cells[key] = entry
        meta.setdefault(
            entry.ucc, (entry.item_text, entry.domain_label, entry.subcategory_code)
        )

    exception_uccs = {m.ucc for m in mappings if m.status is MappingStatus.UNRESOLVED}
    claimed = registry.covered_uccs
    if exception_uccs != claimed:
        raise ResolutionError(
            "the scope-rule registry must claim exactly the Milestone-1 "
            "exception set; symmetric difference "
            f"{sorted(exception_uccs ^ claimed)}"
        )

    m1_status = {m.ucc: m.status for m in mappings}
    rows: list = []
    for ucc in sorted(exception_uccs):
        rule = registry.rule_for(ucc)
        label, domain, subcategory = meta[ucc]
        expenditure = {
            population: (
                cells[(ucc, population)].aggregate_expenditure
                if (ucc, population) in cells
                else None
            )
            for population in POPULATIONS
        }
        exposure = _ucc_exposure(
            ucc=ucc,
            subcategory=subcategory,
            expenditure=expenditure,
            bounds=bounds,
            basis_totals=basis_totals,
        )
        rows.append(
            ResolutionRow(
                ucc=ucc,
                label=label,
                domain=domain,
                expenditure_by_population=expenditure,
                m1_status=m1_status[ucc],
                m2_track_a_status=rule.final_status,
                track_a_rule_id=rule.rule_id,
                track_a_node=rule.resolved_node_for(ucc),
                track_b_treatment=rule.track_b_for(ucc),
                evidence_strength=rule.evidence_strength.value,
                suppression=exposure,
                review_status=rule.review_status.value,
                rule_type=rule.rule_type,
                notes=_row_note(rule, ucc, exposure),
            )
        )

    rule_exposure = {
        rule.rule_id: _rule_exposure(
            rule=rule,
            cells=cells,
            meta=meta,
            bounds=bounds,
            basis_totals=basis_totals,
        )
        for rule in registry.rules
    }

    reconciliations = _reconcile(
        basis=basis,
        mappings=mappings,
        registry=registry,
        rows=rows,
        bounds=bounds,
        basis_totals=basis_totals,
    )
    replacement = _replacement_accounting(registry=registry, rows=rows)

    resolution = Resolution(
        rows=rows,
        rule_exposure=rule_exposure,
        reconciliations=reconciliations,
        suppression_bounds=bounds,
        replacement_accounting=replacement,
    )
    resolution.summary = _build_summary(resolution, registry)
    return resolution


def _ucc_exposure(
    *, ucc, subcategory, expenditure, bounds, basis_totals
) -> SuppressionExposure:
    suppressed = [p for p, v in expenditure.items() if v is None]
    bounds_by_population = {}
    observed_by_population = {}
    for population in suppressed:
        bound = bounds.get((population, subcategory))
        bounds_by_population[population] = (
            None if bound is None else bound.upper_bound
        )
        observed_by_population[population] = 0.0
    return _classify(
        suppressed_cells=tuple(sorted(suppressed)),
        bounds_by_population=bounds_by_population,
        observed_by_population=observed_by_population,
        basis_totals=basis_totals,
        subject=f"UCC {ucc}",
        apply_unobserved_test=False,
    )


def _rule_exposure(
    *, rule: ScopeRule, cells, meta, bounds, basis_totals
) -> SuppressionExposure:
    """Section 16 exposure of a whole transformation, not just one UCC."""
    suppressed_cells: list = []
    bounds_by_population: dict = {}
    observed_by_population: dict = {}
    for population in POPULATIONS:
        touched_domains: set = set()
        observed = 0.0
        for ucc in rule.source_uccs:
            entry = cells.get((ucc, population))
            if entry is None:
                continue
            if entry.aggregate_expenditure is None:
                suppressed_cells.append((ucc, population))
                touched_domains.add(entry.subcategory_code)
            else:
                observed += entry.aggregate_expenditure
        if not touched_domains:
            continue
        # Conservative: the rule's suppressed members cannot jointly exceed the
        # bound for every domain they sit in, since that bound already covers
        # all suppressed leaves of the domain.
        total = 0.0
        for subcategory in sorted(touched_domains):
            bound = bounds.get((population, subcategory))
            if bound is None or bound.upper_bound is None:
                total = None
                break
            total += bound.upper_bound
        bounds_by_population[population] = total
        observed_by_population[population] = observed

    return _classify(
        suppressed_cells=tuple(suppressed_cells),
        bounds_by_population=bounds_by_population,
        observed_by_population=observed_by_population,
        basis_totals=basis_totals,
        subject=f"rule {rule.rule_id}",
        apply_unobserved_test=True,
    )


def _row_note(rule: ScopeRule, ucc: str, exposure: SuppressionExposure) -> str:
    parts = [f"{rule.rule_type.value} under {rule.rule_id} ({rule.review_status.value})."]
    if rule.review_blocker:
        parts.append(f"Blocked: {rule.review_blocker}")
    for member in rule.members:
        if member.get("ucc") == ucc and member.get("note"):
            parts.append(member["note"])
            break
    if exposure.status is not SuppressionStatus.NONE:
        parts.append(exposure.note)
    return " ".join(parts)


def _reconcile(
    *, basis, mappings, registry, rows, bounds, basis_totals
) -> list:
    """Section 19.1: prove no expenditure disappears, in every population."""
    by_ucc = {row.ucc: row for row in rows}
    exception_uccs = set(by_ucc)
    status_by_ucc = {m.ucc: m.status for m in mappings}

    results: list = []
    for population in POPULATIONS:
        retained = transformed = out_of_scope = unresolved = 0.0
        for entry in basis.entries:
            if entry.population != population:
                continue
            amount = entry.aggregate_expenditure
            if amount is None:
                continue
            if entry.ucc in exception_uccs:
                final = by_ucc[entry.ucc].m2_track_a_status
            else:
                final = status_by_ucc[entry.ucc]
            if final in _RETAINED_STATUSES:
                retained += amount
            elif final is MappingStatus.TRANSFORMED:
                transformed += amount
            elif final is MappingStatus.OUT_OF_SCOPE:
                out_of_scope += amount
            elif final is MappingStatus.UNRESOLVED:
                unresolved += amount
            else:
                raise ResolutionError(
                    f"{entry.ucc} in {population} has unbucketable status {final}"
                )

        suppressed_count = sum(
            b.suppressed_leaf_count
            for (pop, _), b in bounds.items()
            if pop == population
        )
        suppressed_bound = sum(
            (b.upper_bound or 0.0)
            for (pop, _), b in bounds.items()
            if pop == population and b.suppressed_leaf_count
        )
        result = PopulationReconciliation(
            population=population,
            ce_observed_basis=basis_totals[population],
            retained=retained,
            transformed=transformed,
            out_of_scope=out_of_scope,
            unresolved=unresolved,
            suppressed_leaf_count=suppressed_count,
            suppressed_upper_bound=suppressed_bound,
        )
        # Section 19.1 is an identity, not a tolerance. The only slack allowed
        # is floating-point summation error over ~2000 addends.
        if abs(result.residual) > 1e-6:
            raise ResolutionError(
                f"section 19.1 identity failed for {population}: residual "
                f"{result.residual:+.6f}. Expenditure has disappeared."
            )
        results.append(result)
    return results


def _replacement_accounting(*, registry, rows) -> dict:
    """Section 19.2: removed outlays vs replacement, reported separately."""
    by_ucc = {row.ucc: row for row in rows}
    report: dict = {}
    for rule in registry.rules_of_type(RuleType.REPLACE):
        removed = {}
        for population in POPULATIONS:
            total = 0.0
            suppressed = 0
            for ucc in rule.source_uccs:
                value = by_ucc[ucc].expenditure_by_population.get(population)
                if value is None:
                    suppressed += 1
                else:
                    total += value
            removed[population] = {
                "observed_removed_expenditure": round(total, 1),
                "suppressed_cell_count": suppressed,
            }
        report[rule.rule_id] = {
            "removed_owner_outlay": removed,
            "replacement_expenditure": None,
            "concept_difference": None,
            "status": "PENDING",
            "pending_reason": (
                "The replacement rental-equivalence amount is not computed in "
                "this run. It depends on the Track-A shelter rule, which is "
                "held until the PUMD annual-weighting and quintile procedure "
                "has been validated against published 2024 LB01 LABSTAT "
                "benchmarks. Spec section 19.2 does not expect the removed and "
                "replacement amounts to be equal, so neither may be inferred "
                "from the other."
            ),
        }
    return report


def _build_summary(resolution: Resolution, registry: ScopeRuleRegistry) -> dict:
    rows = resolution.rows
    by_status: dict = {}
    by_track_b: dict = {}
    by_suppression: dict = {}
    for row in rows:
        by_status[row.m2_track_a_status.value] = (
            by_status.get(row.m2_track_a_status.value, 0) + 1
        )
        by_track_b[row.track_b_treatment.value] = (
            by_track_b.get(row.track_b_treatment.value, 0) + 1
        )
        by_suppression[row.suppression.status.value] = (
            by_suppression.get(row.suppression.status.value, 0) + 1
        )

    track_b_retained = {}
    for population in POPULATIONS:
        total = 0.0
        suppressed = 0
        for row in rows:
            if row.track_b_treatment is not TrackBTreatment.RETAIN_CURRENT_PAYMENT:
                continue
            value = row.expenditure_by_population.get(population)
            if value is None:
                suppressed += 1
            else:
                total += value
        track_b_retained[population] = {
            "observed_expenditure": round(total, 1),
            "suppressed_cell_count": suppressed,
        }

    declared_vs_computed = {
        rule_id: {
            "declared": registry.rule_by_id(rule_id).suppression_status.value,
            "computed": exposure.status.value,
            "agrees": registry.rule_by_id(rule_id).suppression_status
            is exposure.status,
        }
        for rule_id, exposure in resolution.rule_exposure.items()
    }

    return {
        "milestone": "Detailed Inflation Substrate v0.1, Milestone 2",
        "status": "RESEARCH_ONLY",
        "core_dmi": "WITHDRAWN_AND_UNIMPLEMENTED",
        "index_computed": False,
        "weights_normalized": False,
        "exception_count": len(rows),
        "track_a_status_counts": by_status,
        "track_b_treatment_counts": by_track_b,
        "suppression_status_counts": by_suppression,
        "suppression_thresholds_pct": {
            "basis_share": SUPPRESSION_BASIS_THRESHOLD_PCT,
            "rule_unobserved_share": SUPPRESSION_RULE_SHARE_THRESHOLD_PCT,
        },
        "rule_suppression_declared_vs_computed": declared_vs_computed,
        "track_b_retained_expenditure": track_b_retained,
        "replacement_accounting": resolution.replacement_accounting,
        "reconciliation": [
            {
                "population": r.population,
                "ce_observed_basis": round(r.ce_observed_basis, 1),
                "retained": round(r.retained, 1),
                "transformed": round(r.transformed, 1),
                "out_of_scope": round(r.out_of_scope, 1),
                "unresolved": round(r.unresolved, 1),
                "residual": round(r.residual, 6),
                "suppressed_leaf_count": r.suppressed_leaf_count,
                "suppressed_upper_bound": round(r.suppressed_upper_bound, 1),
                "suppressed_upper_bound_pct_of_basis": round(
                    r.suppressed_upper_bound_pct_of_basis, 6
                ),
            }
            for r in resolution.reconciliations
        ],
        "pending_shelter_work": [
            "Track-A rental-equivalence rule for owner-occupied shelter is not "
            "finalized. Four shelter-coupled rules remain PROPOSED.",
            "PUMD annual-weighting and quintile procedure must be validated "
            "against published 2024 LB01 LABSTAT benchmarks before the "
            "910104-910107 aggregates are computed.",
            "shelter_cpi_track_2024.csv, shelter_payments_track_2024.csv and "
            "shelter_concept_comparison_2024.csv are not produced by this run.",
        ],
    }


# ---------------------------------------------------------------------------
# Artifact writers (spec section 17)
# ---------------------------------------------------------------------------

UNRESOLVED_CSV_COLUMNS = (
    "ucc",
    "label",
    "domain",
    "all_cu_expenditure",
    "pct_of_all_cu_basis",
    "candidate_eli_not_applied",
    "candidate_node_not_applied",
    "anomaly",
    "note",
)


def _write_csv(path: Path, header: Sequence, rows: Iterable) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        # Match the Milestone-1 writers: LF, not the csv module's default CRLF.
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_artifacts(
    resolution: Resolution, registry: ScopeRuleRegistry, output_dir: Path
) -> list:
    """Write the section 17 artifacts this milestone is authorized to produce.

    The three shelter CSVs are deliberately absent: the Track-A shelter rule is
    held pending PUMD benchmark validation, and emitting a placeholder would
    misrepresent an unfinished decision as a finished one.
    """
    output_dir = assert_research_output_dir(output_dir)
    written: list = []

    written.append(
        _write_csv(
            output_dir / "scope_resolution_2024.csv",
            RESOLUTION_CSV_COLUMNS,
            (row.as_csv_row() for row in resolution.rows),
        )
    )
    written.append(
        _write_csv(
            output_dir / "transformation_reconciliation.csv",
            RECONCILIATION_CSV_COLUMNS,
            (r.as_csv_row() for r in resolution.reconciliations),
        )
    )

    unresolved_rule = registry.rule_by_id("UNRESOLVED_v0_2")
    member_by_ucc = {m["ucc"]: m for m in unresolved_rule.members}
    all_cu_basis = next(
        r.ce_observed_basis
        for r in resolution.reconciliations
        if r.population == ALL_CU
    )
    unresolved_rows = []
    for row in resolution.rows:
        if row.m2_track_a_status is not MappingStatus.UNRESOLVED:
            continue
        member = member_by_ucc.get(row.ucc, {})
        amount = row.expenditure_by_population.get(ALL_CU)
        unresolved_rows.append(
            [
                row.ucc,
                row.label,
                row.domain,
                "" if amount is None else f"{amount:.1f}",
                "" if amount is None else f"{100.0 * amount / all_cu_basis:.6f}",
                member.get("candidate_eli", ""),
                member.get("candidate_node", ""),
                member.get("anomaly", ""),
                member.get("note", ""),
            ]
        )
    written.append(
        _write_csv(
            output_dir / "unresolved_ledger_v0_2.csv",
            UNRESOLVED_CSV_COLUMNS,
            unresolved_rows,
        )
    )

    summary_path = output_dir / "scope_resolution_summary.json"
    summary_path.write_text(
        json.dumps(resolution.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    written.append(summary_path)
    return written
