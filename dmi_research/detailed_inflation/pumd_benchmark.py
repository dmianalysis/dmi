"""LB01 benchmark of 2024 CE Interview PUMD estimates.

Detailed Inflation Substrate v0.1, research only. This module never touches
``dmi_calculator``, the Baseline, Slack-Plus, release workflows, production
manifests or the deployment output tree.

The question this module answers is narrow: can the public 2024 CE Interview
microdata be turned into annual All-CU and income-quintile mean expenditures
that reproduce the published LB01 series closely enough for PUMD to serve as a
defensible source? It is a validation gate. Nothing here authorises a
quantitative estimate for any UCC whose usability is not established.

Two disciplines are enforced structurally rather than by convention.

First, the benchmark roster is frozen before any comparison is computed.
:func:`select_roster` depends only on the Milestone-1 and Milestone-2
artifacts and the BLS hierarchical grouping file. It cannot see a PUMD value,
because no PUMD value is passed to it.

Second, the acceptance rule is frozen before any error is inspected.
:class:`BenchmarkSpec` is loaded from a versioned registry artifact, and
:func:`summarize` applies it. Shelter takes no part in either: the four
Milestone-2 shelter UCCs are excluded from the roster by construction, and
:data:`EXCLUDED_FROM_CALIBRATION` states that exclusion so a test can prove it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .pumd import (
    ALL_CONSUMER_UNITS,
    PUBLISHED_QUINTILE_LOWER_LIMITS_2024,
    QUINTILE_LABELS,
    ConsumerUnit,
    ExpenditureRecord,
    PopulationEstimate,
    PumdSchemaError,
    StubEntry,
    UccMeanEstimate,
    assign_quintile,
    months_in_scope,
    population_estimates,
    population_weight,
    reconstruct_quintile_limits,
    weighted_ucc_means,
)

#: Version of the selection rule in :func:`select_roster`. Any change to the
#: rule must increment this; a test compares it against the frozen artifact.
#:
#: v0.1 tested the survey-source code in the INTERVIEW hierarchical grouping
#: file, which is trivially ``I`` for every row in that file and therefore
#: proved nothing. LB01 is Table 1101, an INTEGRATED table, so the code that
#: determines which survey feeds the published value is the one in the
#: integrated file. Twenty-seven UCCs that appear in the Interview stub are
#: sourced from the Diary in the integrated table and can never be reproduced
#: from Interview microdata. v0.2 requires ``I`` in both files.
ROSTER_VERSION = "v0.2"

#: Provenance class a roster UCC must carry (Milestone 2).
REQUIRED_PROVENANCE_CLASS = "DIRECT_CONCORDANCE_UCC"

#: CE source code for the Interview survey in the Milestone-2 classification.
REQUIRED_CE_SOURCE = "I"

#: Data section of the hierarchical grouping file for ordinary expenditures.
#: ``ADDENDA`` (imputed rental equivalence) and ``ASSETS`` are not ordinary
#: expenditure concepts and are not eligible.
REQUIRED_STUB_SECTION = "EXPEND"

#: LABSTAT characteristics codes for the six LB01 populations.
CHARACTERISTICS_ALL_CU = "01"
REQUIRED_CHARACTERISTICS = ("01", "02", "03", "04", "05", "06")

#: Magnitude strata, largest published All-CU mean first.
MAGNITUDE_STRATA = ("LARGE", "MEDIUM", "SMALL")

#: UCCs that may never enter the roster and may never influence the acceptance
#: rule. Milestone 2 classified these as CONCORDANCE_ONLY_UCC with
#: ``pumd_quantitative_usability = NOT_ESTABLISHED``; this task does not
#: revisit that.
EXCLUDED_FROM_CALIBRATION = ("910104", "910105", "910106", "910107")

#: LABSTAT characteristics code -> the population label used in the
#: Milestone-1 accounting basis. ``population_estimates`` keys All CU as
#: ``ALL_CU``; the basis file writes it out in full, so the two are bridged
#: here rather than by renaming either side.
LABSTAT_POPULATION_BY_CODE = {
    "01": "All Consumer Units",
    "02": QUINTILE_LABELS[0],
    "03": QUINTILE_LABELS[1],
    "04": QUINTILE_LABELS[2],
    "05": QUINTILE_LABELS[3],
    "06": QUINTILE_LABELS[4],
}

#: The same six populations, keyed the way :mod:`pumd` keys them.
PUMD_POPULATION_BY_CODE = dict(LABSTAT_POPULATION_BY_CODE, **{"01": ALL_CONSUMER_UNITS})

#: Estimand of the LB01 series value. ``cx.series`` carries only process code
#: ``M`` for the LB01 demographics code, so a PUMD mean is compared with a
#: published mean and never with an aggregate.
ESTIMAND = "MEAN_ANNUAL_EXPENDITURE_PER_CONSUMER_UNIT"
ESTIMAND_UNITS = "US dollars per consumer unit per year"

#: LB01 publishes the mean as a whole number of dollars, so the published
#: value carries a rounding half-width of fifty cents. At a published mean of
#: ten dollars that is five percent of the value on its own, which is why the
#: spec's small-value floor sits there.
PUBLISHED_ROUNDING_HALF_WIDTH = 0.5


class RosterError(ValueError):
    """The roster could not be built, or was built from the wrong inputs."""


# ---------------------------------------------------------------------------
# Stage 1: roster selection, computed with no sight of any PUMD value
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterEntry:
    """One benchmark UCC, fixed before any comparison is run."""

    ucc: str
    published_title: str
    dmi_node: str
    domain_label: str
    stub_title: str
    annualization_factor: int
    magnitude_stratum: str
    all_cu_published_mean: float
    all_cu_published_rse: float | None
    selection_rank_in_cell: int
    cell_size: int

    def __post_init__(self) -> None:
        if self.ucc in EXCLUDED_FROM_CALIBRATION:
            raise RosterError(
                f"UCC {self.ucc} is one of the Milestone-2 shelter UCCs and "
                "must never enter the benchmark roster."
            )
        if self.magnitude_stratum not in MAGNITUDE_STRATA:
            raise RosterError(f"unknown magnitude stratum {self.magnitude_stratum!r}")


@dataclass(frozen=True)
class Candidate:
    """A UCC that passed every eligibility test, before stratification."""

    ucc: str
    published_title: str
    dmi_node: str
    domain_label: str
    stub_title: str
    annualization_factor: int
    all_cu_published_mean: float
    all_cu_published_rse: float | None


def eligible_candidates(
    provenance_rows: Iterable[Mapping[str, str]],
    basis_rows: Iterable[Mapping[str, str]],
    exception_uccs: Iterable[str],
    interview_stub: Mapping[str, StubEntry],
    integrated_stub: Mapping[str, StubEntry],
) -> list[Candidate]:
    """Apply the eligibility tests of the selection rule.

    A UCC is eligible when all of the following hold.

    1. Milestone 2 classified it ``DIRECT_CONCORDANCE_UCC``. Concordance-only
       UCCs are excluded here, which is what keeps 910104-910107 out.
    2. Its CE source is the Interview survey. Diary UCCs cannot be estimated
       from the Interview files at all.
    3. It is not one of the 58 Milestone-1 exception UCCs.
    4. The 2024 Interview hierarchical grouping file carries it in the
       ``EXPEND`` section, so it is an ordinary expenditure concept and not an
       addendum such as imputed rental equivalence, an asset flow or a
       consumer-unit characteristic.
    5. The 2024 INTEGRATED hierarchical grouping file also carries it in
       ``EXPEND`` with survey code ``I``. LB01 is Table 1101, an integrated
       table; the integrated file is what states which survey supplies the
       published value. Twenty-seven UCCs appear in the Interview stub but are
       coded ``D`` in the integrated file, and their published means come from
       the Diary. Interview microdata cannot reproduce those, and requiring
       agreement between the two files is what excludes them.
    6. LABSTAT publishes a mean for all six LB01 populations. Without a
       published mean there is nothing to compare against.
    """
    exceptions = set(exception_uccs)
    by_ucc: dict[str, dict[str, Mapping[str, str]]] = {}
    for row in basis_rows:
        by_ucc.setdefault(row["ucc"], {})[row["characteristics_code"]] = row

    candidates: list[Candidate] = []
    for row in provenance_rows:
        ucc = row["ucc"]
        if ucc in EXCLUDED_FROM_CALIBRATION:
            continue
        if row["provenance_class"] != REQUIRED_PROVENANCE_CLASS:
            continue
        if row["ce_source"] != REQUIRED_CE_SOURCE:
            continue
        if ucc in exceptions:
            continue
        entry = interview_stub.get(ucc)
        if entry is None or entry.section != REQUIRED_STUB_SECTION:
            continue
        integrated = integrated_stub.get(ucc)
        if integrated is None:
            continue
        if integrated.section != REQUIRED_STUB_SECTION:
            continue
        if integrated.survey != REQUIRED_CE_SOURCE:
            continue
        cells = by_ucc.get(ucc, {})
        if set(cells) != set(REQUIRED_CHARACTERISTICS):
            continue
        if any(not cells[code]["mean_expenditure"].strip() for code in cells):
            continue
        all_cu = cells[CHARACTERISTICS_ALL_CU]
        candidates.append(
            Candidate(
                ucc=ucc,
                published_title=all_cu["item_text"],
                dmi_node=row["dmi_node"],
                domain_label=all_cu["domain_label"],
                stub_title=entry.title,
                annualization_factor=entry.factor,
                all_cu_published_mean=float(all_cu["mean_expenditure"]),
                all_cu_published_rse=_optional_float(all_cu["rse"]),
            )
        )
    candidates.sort(key=_magnitude_order)
    return candidates


def _magnitude_order(candidate: Candidate) -> tuple[float, str]:
    return (-candidate.all_cu_published_mean, candidate.ucc)


def _optional_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def assign_magnitude_strata(candidates: Sequence[Candidate]) -> dict[str, str]:
    """Split the eligible pool into equal-count magnitude terciles.

    The split is on published magnitude, not on any PUMD quantity, and the
    ordering is total: mean descending, UCC ascending.
    """
    total = len(candidates)
    if total < len(MAGNITUDE_STRATA):
        raise RosterError(
            f"only {total} eligible UCCs; cannot form {len(MAGNITUDE_STRATA)} strata"
        )
    strata: dict[str, str] = {}
    for index, candidate in enumerate(candidates):
        if index * 3 < total:
            strata[candidate.ucc] = "LARGE"
        elif index * 3 < 2 * total:
            strata[candidate.ucc] = "MEDIUM"
        else:
            strata[candidate.ucc] = "SMALL"
    return strata


def select_roster(
    provenance_rows: Iterable[Mapping[str, str]],
    basis_rows: Iterable[Mapping[str, str]],
    exception_uccs: Iterable[str],
    interview_stub: Mapping[str, StubEntry],
    integrated_stub: Mapping[str, StubEntry],
) -> list[RosterEntry]:
    """Return the frozen benchmark roster.

    The selection rule, stated in full:

    * Build the eligible pool with :func:`eligible_candidates`.
    * Stratify the pool into equal-count magnitude terciles by published
      All-CU mean.
    * Keep only DMI nodes that have at least one eligible UCC in every
      stratum, so each retained node spans the full magnitude range rather
      than contributing only its largest items.
    * From each (node, stratum) cell take the median member, by rank within
      the cell ordered by mean descending then UCC ascending. The median
      avoids selecting only cell extremes and is fully determined by the
      published data.

    Nothing in this rule refers to a PUMD estimate or to an error.
    """
    candidates = eligible_candidates(
        provenance_rows, basis_rows, exception_uccs, interview_stub, integrated_stub
    )
    strata = assign_magnitude_strata(candidates)

    cells: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in candidates:
        cells.setdefault((candidate.dmi_node, strata[candidate.ucc]), []).append(candidate)

    complete_nodes = sorted(
        node
        for node in {candidate.dmi_node for candidate in candidates}
        if all((node, stratum) in cells for stratum in MAGNITUDE_STRATA)
    )
    if not complete_nodes:
        raise RosterError("no DMI node spans all three magnitude strata")

    roster: list[RosterEntry] = []
    for node in complete_nodes:
        for stratum in MAGNITUDE_STRATA:
            members = cells[(node, stratum)]
            rank = (len(members) - 1) // 2
            chosen = members[rank]
            roster.append(
                RosterEntry(
                    ucc=chosen.ucc,
                    published_title=chosen.published_title,
                    dmi_node=chosen.dmi_node,
                    domain_label=chosen.domain_label,
                    stub_title=chosen.stub_title,
                    annualization_factor=chosen.annualization_factor,
                    magnitude_stratum=stratum,
                    all_cu_published_mean=chosen.all_cu_published_mean,
                    all_cu_published_rse=chosen.all_cu_published_rse,
                    selection_rank_in_cell=rank,
                    cell_size=len(members),
                )
            )
    roster.sort(key=lambda entry: entry.ucc)
    return roster


ROSTER_COLUMNS = (
    "ucc",
    "published_title",
    "dmi_node",
    "domain_label",
    "magnitude_stratum",
    "annualization_factor",
    "all_cu_published_mean",
    "all_cu_published_rse",
    "selection_rank_in_cell",
    "cell_size",
    "stub_title",
)


def roster_rows(roster: Sequence[RosterEntry]) -> list[dict[str, str]]:
    return [
        {
            "ucc": entry.ucc,
            "published_title": entry.published_title,
            "dmi_node": entry.dmi_node,
            "domain_label": entry.domain_label,
            "magnitude_stratum": entry.magnitude_stratum,
            "annualization_factor": str(entry.annualization_factor),
            "all_cu_published_mean": f"{entry.all_cu_published_mean:.1f}",
            "all_cu_published_rse": (
                "" if entry.all_cu_published_rse is None
                else f"{entry.all_cu_published_rse:.2f}"
            ),
            "selection_rank_in_cell": str(entry.selection_rank_in_cell),
            "cell_size": str(entry.cell_size),
            "stub_title": entry.stub_title,
        }
        for entry in roster
    ]


def roster_hash(roster: Sequence[RosterEntry]) -> str:
    """Content hash of the roster, so a silent change is detectable.

    Only the identifying and selection fields participate, in UCC order.
    """
    payload = "\n".join(
        "|".join(
            (
                entry.ucc,
                entry.dmi_node,
                entry.magnitude_stratum,
                str(entry.annualization_factor),
                f"{entry.all_cu_published_mean:.1f}",
            )
        )
        for entry in sorted(roster, key=lambda item: item.ucc)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stage 2: the acceptance rule, frozen before any error is seen
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkSpec:
    """The precommitted acceptance rule.

    The thresholds are not tuned. They are derived from what BLS documents
    about why PUMD estimates differ from published tables: the published
    tables integrate the Diary survey and use confidential data, while PUMD is
    Interview-only and has been altered to satisfy non-disclosure
    requirements. The magnitudes below are the tolerances judged acceptable
    for a source that must reproduce published structure, chosen before the
    per-UCC errors were computed and applied unchanged afterwards.
    """

    spec_version: str
    roster_version: str
    roster_hash: str
    estimand: str
    population_tolerance_pct: float
    quintile_population_tolerance_pct: float
    median_abs_pct_error_max: float
    p75_abs_pct_error_max: float
    p90_abs_pct_error_max: float
    per_ucc_abs_pct_error_max: float
    per_ucc_pass_fraction_min: float
    mean_signed_pct_error_abs_max: float
    small_value_absolute_floor: float
    small_value_abs_diff_max: float
    excluded_from_calibration: tuple[str, ...]

    @classmethod
    def from_json(cls, path: str | os.PathLike[str]) -> "BenchmarkSpec":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rule = payload["acceptance_rule"]
        return cls(
            spec_version=payload["spec_version"],
            roster_version=payload["roster_version"],
            roster_hash=payload["roster_hash"],
            estimand=payload["estimand"]["code"],
            population_tolerance_pct=float(rule["population_tolerance_pct"]),
            quintile_population_tolerance_pct=float(
                rule["quintile_population_tolerance_pct"]
            ),
            median_abs_pct_error_max=float(rule["median_abs_pct_error_max"]),
            p75_abs_pct_error_max=float(rule["p75_abs_pct_error_max"]),
            p90_abs_pct_error_max=float(rule["p90_abs_pct_error_max"]),
            per_ucc_abs_pct_error_max=float(rule["per_ucc_abs_pct_error_max"]),
            per_ucc_pass_fraction_min=float(rule["per_ucc_pass_fraction_min"]),
            mean_signed_pct_error_abs_max=float(rule["mean_signed_pct_error_abs_max"]),
            small_value_absolute_floor=float(rule["small_value_absolute_floor"]),
            small_value_abs_diff_max=float(rule["small_value_abs_diff_max"]),
            excluded_from_calibration=tuple(payload["excluded_from_calibration"]),
        )

    def __post_init__(self) -> None:
        if tuple(self.excluded_from_calibration) != EXCLUDED_FROM_CALIBRATION:
            raise ValueError(
                "the benchmark spec must exclude exactly the four Milestone-2 "
                f"shelter UCCs; it excludes {self.excluded_from_calibration}"
            )
        if self.estimand != ESTIMAND:
            raise ValueError(
                f"spec estimand {self.estimand!r} does not match the LB01 "
                f"series estimand {ESTIMAND!r}"
            )


# ---------------------------------------------------------------------------
# Stage 3: population and quintile validation, reported before expenditures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationComparison:
    population: str
    characteristics_code: str
    published_consumer_units_thousands: float
    pumd_consumer_units_thousands: float
    absolute_difference: float
    percentage_difference: float
    published_mean_income_before_taxes: float
    pumd_mean_income_before_taxes: float
    income_percentage_difference: float


def compare_populations(
    estimates: Mapping[str, PopulationEstimate],
    units: Sequence[ConsumerUnit],
    published_consumer_units: Mapping[str, float],
    published_mean_income: Mapping[str, float],
) -> list[PopulationComparison]:
    """Compare weighted CU counts and mean incomes with LB01.

    This runs before any expenditure comparison so that a bad quintile
    reconstruction cannot be mistaken for a bad annualization.
    """
    incomes = _pumd_mean_incomes(units)
    rows: list[PopulationComparison] = []
    for code in REQUIRED_CHARACTERISTICS:
        label = LABSTAT_POPULATION_BY_CODE[code]
        key = PUMD_POPULATION_BY_CODE[code]
        estimate = estimates[key]
        published_cu = published_consumer_units[label]
        pumd_cu = estimate.consumer_units_thousands
        published_income = published_mean_income[label]
        pumd_income = incomes[key]
        rows.append(
            PopulationComparison(
                population=label,
                characteristics_code=code,
                published_consumer_units_thousands=published_cu,
                pumd_consumer_units_thousands=pumd_cu,
                absolute_difference=pumd_cu - published_cu,
                percentage_difference=_pct(pumd_cu, published_cu),
                published_mean_income_before_taxes=published_income,
                pumd_mean_income_before_taxes=pumd_income,
                income_percentage_difference=_pct(pumd_income, published_income),
            )
        )
    return rows


def _pumd_mean_incomes(units: Sequence[ConsumerUnit]) -> dict[str, float]:
    """Population-weighted mean income before taxes, by population.

    Uses the same MO_SCOPE-adjusted weight as the consumer-unit count, so the
    ratio is a mean per consumer unit and not a mean per interview.
    """
    totals: dict[str, list[float]] = {}
    for unit in units:
        months = months_in_scope(unit.quarter_role, unit.interview_month)
        weight = population_weight(unit.final_weight, months)
        if weight <= 0.0:
            continue
        quintile = assign_quintile(unit.income_before_taxes)
        for population in (ALL_CONSUMER_UNITS, quintile):
            bucket = totals.setdefault(population, [0.0, 0.0])
            bucket[0] += weight * unit.income_before_taxes
            bucket[1] += weight
    return {
        population: (bucket[0] / bucket[1] if bucket[1] else 0.0)
        for population, bucket in totals.items()
    }


def _pct(actual: float, published: float) -> float:
    if published == 0.0:
        return float("nan")
    return 100.0 * (actual - published) / published


@dataclass(frozen=True)
class QuintileReconstruction:
    """Diagnostic comparison of quintile boundaries.

    The published lower limits are what the benchmark uses to assign CUs. The
    reconstructed limits are computed only to show how far a weighted-rank
    rule lands from them; they never assign a consumer unit. BLS publishes the
    limits but not the algorithm that produced them, so inventing one would be
    filling an ambiguity with a plausible method.
    """

    boundary: str
    published_lower_limit: float
    reconstructed_lower_limit: float
    absolute_difference: float
    percentage_difference: float
    used_for_assignment: str


def reconstruct_boundaries(
    units: Sequence[ConsumerUnit],
    published_limits: Sequence[float] = PUBLISHED_QUINTILE_LOWER_LIMITS_2024,
) -> list[QuintileReconstruction]:
    reconstructed = reconstruct_quintile_limits(units)
    names = ("Q2 lower limit", "Q3 lower limit", "Q4 lower limit", "Q5 lower limit")
    return [
        QuintileReconstruction(
            boundary=name,
            published_lower_limit=published,
            reconstructed_lower_limit=derived,
            absolute_difference=derived - published,
            percentage_difference=_pct(derived, published),
            used_for_assignment="published",
        )
        for name, published, derived in zip(names, published_limits, reconstructed)
    ]


# ---------------------------------------------------------------------------
# Stage 4: the UCC expenditure comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchmarkResult:
    ucc: str
    published_title: str
    dmi_node: str
    domain_label: str
    magnitude_stratum: str
    population: str
    estimand: str
    estimand_units: str
    published_value: float
    pumd_value: float
    absolute_difference: float
    percentage_difference: float | None
    publication_rounding_pct: float | None
    judged_on: str
    absolute_difference_as_share_of_floor: float | None
    pumd_standard_error: float | None
    published_rse: float | None
    reporting_records: int
    benchmark_status: str
    explanation_if_known: str


def run_benchmark(
    roster: Sequence[RosterEntry],
    units: Sequence[ConsumerUnit],
    records: Sequence[ExpenditureRecord],
    basis_rows: Iterable[Mapping[str, str]],
    spec: BenchmarkSpec,
) -> tuple[list[BenchmarkResult], dict[str, PopulationEstimate]]:
    """Estimate every roster UCC for every LB01 population and compare.

    The whole roster is always run. A UCC is never dropped because it
    reproduces poorly.
    """
    roster_uccs = {entry.ucc for entry in roster}
    forbidden = roster_uccs & set(EXCLUDED_FROM_CALIBRATION)
    if forbidden:
        raise RosterError(
            f"roster contains excluded shelter UCCs: {sorted(forbidden)}"
        )

    published = _published_cells(basis_rows, roster_uccs)
    populations = population_estimates(units)
    factors = {entry.ucc: entry.annualization_factor for entry in roster}
    estimates = weighted_ucc_means(units, records, populations, factors)

    results: list[BenchmarkResult] = []
    for entry in sorted(roster, key=lambda item: item.ucc):
        for code in REQUIRED_CHARACTERISTICS:
            label = LABSTAT_POPULATION_BY_CODE[code]
            cell = published[(entry.ucc, code)]
            published_value = float(cell["mean_expenditure"])
            estimate = estimates.get((entry.ucc, PUMD_POPULATION_BY_CODE[code]))
            if estimate is None:
                raise PumdSchemaError(
                    f"no PUMD estimate produced for {entry.ucc} / {label}"
                )
            difference = estimate.mean - published_value
            results.append(
                _classify(
                    entry,
                    label,
                    published_value,
                    estimate,
                    difference,
                    _optional_float(cell["rse"]),
                    spec,
                )
            )
    return results, populations


def _classify(
    entry: RosterEntry,
    population: str,
    published_value: float,
    estimate: UccMeanEstimate,
    difference: float,
    published_rse: float | None,
    spec: BenchmarkSpec,
) -> BenchmarkResult:
    small = abs(published_value) < spec.small_value_absolute_floor
    percentage = None if published_value == 0.0 else _pct(estimate.mean, published_value)
    rounding = (
        None
        if published_value == 0.0
        else 100.0 * PUBLISHED_ROUNDING_HALF_WIDTH / abs(published_value)
    )
    if small:
        share = abs(difference) / spec.small_value_absolute_floor
        status = "PASS" if abs(difference) <= spec.small_value_abs_diff_max else "FAIL"
        judged_on = "ABSOLUTE_DIFFERENCE"
        explanation = (
            "published mean is below the small-value floor; judged on absolute "
            "difference because LB01 publishes the mean as a whole number, so "
            f"rounding alone can move it by {rounding:.1f} percent"
            if rounding is not None
            else "published mean is zero; judged on absolute difference"
        )
    else:
        share = None
        status = "PASS" if abs(percentage) <= spec.per_ucc_abs_pct_error_max else "FAIL"
        judged_on = "PERCENTAGE_DIFFERENCE"
        explanation = ""
    return BenchmarkResult(
        ucc=entry.ucc,
        published_title=entry.published_title,
        dmi_node=entry.dmi_node,
        domain_label=entry.domain_label,
        magnitude_stratum=entry.magnitude_stratum,
        population=population,
        estimand=ESTIMAND,
        estimand_units=ESTIMAND_UNITS,
        published_value=published_value,
        pumd_value=estimate.mean,
        absolute_difference=difference,
        percentage_difference=percentage,
        publication_rounding_pct=rounding,
        judged_on=judged_on,
        absolute_difference_as_share_of_floor=share,
        pumd_standard_error=estimate.standard_error,
        published_rse=published_rse,
        reporting_records=estimate.reporting_records,
        benchmark_status=status,
        explanation_if_known=explanation,
    )


def _published_cells(
    basis_rows: Iterable[Mapping[str, str]], roster_uccs: set[str]
) -> dict[tuple[str, str], Mapping[str, str]]:
    cells: dict[tuple[str, str], Mapping[str, str]] = {}
    for row in basis_rows:
        if row["ucc"] in roster_uccs:
            cells[(row["ucc"], row["characteristics_code"])] = row
    missing = [
        (ucc, code)
        for ucc in sorted(roster_uccs)
        for code in REQUIRED_CHARACTERISTICS
        if (ucc, code) not in cells
    ]
    if missing:
        raise RosterError(f"published LB01 cells missing for {missing}")
    return cells


# ---------------------------------------------------------------------------
# Stage 5: summary against the frozen acceptance rule
# ---------------------------------------------------------------------------


def _median_rse_gap(results: Sequence[BenchmarkResult]) -> float:
    """Median gap, in percentage points, between the BRR RSE and LB01's RSE.

    The replicate machinery is validated against something BLS publishes
    independently of the mean, so agreement here is evidence that the weights
    and the replication are the BLS ones and not merely that the means happen
    to land in the right place.
    """
    gaps = sorted(
        100.0 * result.pumd_standard_error / result.pumd_value - result.published_rse
        for result in results
        if result.published_rse is not None
        and result.pumd_standard_error is not None
        and result.pumd_value > 0
    )
    if not gaps:
        return float("nan")
    middle = len(gaps) // 2
    if len(gaps) % 2:
        return gaps[middle]
    return (gaps[middle - 1] + gaps[middle]) / 2.0


def percentile(values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of a non-empty sequence."""
    if not values:
        raise ValueError("percentile of an empty sequence")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


@dataclass(frozen=True)
class BenchmarkSummary:
    spec_version: str
    roster_version: str
    roster_hash: str
    roster_size: int
    comparison_count: int
    percentage_judged_count: int
    absolute_judged_count: int
    median_abs_pct_error: float
    p75_abs_pct_error: float
    p90_abs_pct_error: float
    max_abs_pct_error: float
    mean_signed_pct_error: float
    pass_fraction: float
    failures_by_population: dict[str, int]
    failures_by_domain: dict[str, int]
    mean_signed_pct_error_by_population: dict[str, float]
    population_status: str
    quintile_population_status: str
    #: Diagnostics, not criteria. The acceptance rule does not read these.
    all_cu_max_absolute_difference: float
    brr_rse_median_difference_pp: float
    failures_within_one_standard_error: int
    benchmark_status: str
    failed_criteria: tuple[str, ...]


def summarize(
    results: Sequence[BenchmarkResult],
    population_comparisons: Sequence[PopulationComparison],
    roster: Sequence[RosterEntry],
    spec: BenchmarkSpec,
) -> BenchmarkSummary:
    """Apply the frozen acceptance rule. No threshold is chosen here."""
    observed_hash = roster_hash(roster)
    if observed_hash != spec.roster_hash:
        raise RosterError(
            "the roster has changed since the acceptance rule was frozen: "
            f"spec pins {spec.roster_hash}, roster hashes to {observed_hash}. "
            "Increment the roster version and the spec version deliberately; "
            "do not let a roster drift past a frozen rule."
        )
    if spec.roster_version != ROSTER_VERSION:
        raise RosterError(
            f"spec roster version {spec.roster_version} does not match the "
            f"selection rule version {ROSTER_VERSION}"
        )

    # The spec states that cells below the small-value floor are judged on
    # absolute difference "instead", because a percentage against a near-zero
    # base is not informative. They therefore do not enter the percentage
    # distribution either; mixing them in would let publication rounding of a
    # two-dollar mean dominate a statistic meant to describe reproduction
    # quality. Their PASS/FAIL still counts in the pass fraction.
    comparable = [
        r
        for r in results
        if r.judged_on == "PERCENTAGE_DIFFERENCE" and r.percentage_difference is not None
    ]
    errors = [abs(r.percentage_difference) for r in comparable]
    if not errors:
        raise ValueError("no comparable results; the benchmark cannot be summarized")

    signed = [r.percentage_difference for r in comparable]
    median = percentile(errors, 0.50)
    p75 = percentile(errors, 0.75)
    p90 = percentile(errors, 0.90)
    mean_signed = sum(signed) / len(signed)
    passes = sum(1 for r in results if r.benchmark_status == "PASS")
    pass_fraction = passes / len(results)

    failures_by_population: dict[str, int] = {}
    failures_by_domain: dict[str, int] = {}
    signed_by_population: dict[str, list[float]] = {}
    for result in results:
        if result.benchmark_status == "FAIL":
            failures_by_population[result.population] = (
                failures_by_population.get(result.population, 0) + 1
            )
            failures_by_domain[result.domain_label] = (
                failures_by_domain.get(result.domain_label, 0) + 1
            )
    for result in comparable:
        signed_by_population.setdefault(result.population, []).append(
            result.percentage_difference
        )

    all_cu = next(
        row for row in population_comparisons if row.population == "All Consumer Units"
    )
    population_ok = abs(all_cu.percentage_difference) <= spec.population_tolerance_pct
    quintile_ok = all(
        abs(row.percentage_difference) <= spec.quintile_population_tolerance_pct
        for row in population_comparisons
        if row.population != "All Consumer Units"
    )

    failed: list[str] = []
    if not population_ok:
        failed.append("population_tolerance_pct")
    if not quintile_ok:
        failed.append("quintile_population_tolerance_pct")
    if median > spec.median_abs_pct_error_max:
        failed.append("median_abs_pct_error_max")
    if p75 > spec.p75_abs_pct_error_max:
        failed.append("p75_abs_pct_error_max")
    if p90 > spec.p90_abs_pct_error_max:
        failed.append("p90_abs_pct_error_max")
    if pass_fraction < spec.per_ucc_pass_fraction_min:
        failed.append("per_ucc_pass_fraction_min")
    if abs(mean_signed) > spec.mean_signed_pct_error_abs_max:
        failed.append("mean_signed_pct_error_abs_max")

    return BenchmarkSummary(
        spec_version=spec.spec_version,
        roster_version=spec.roster_version,
        roster_hash=roster_hash(roster),
        roster_size=len(roster),
        comparison_count=len(results),
        percentage_judged_count=len(comparable),
        absolute_judged_count=len(results) - len(comparable),
        median_abs_pct_error=median,
        p75_abs_pct_error=p75,
        p90_abs_pct_error=p90,
        max_abs_pct_error=max(errors),
        mean_signed_pct_error=mean_signed,
        pass_fraction=pass_fraction,
        failures_by_population=failures_by_population,
        failures_by_domain=failures_by_domain,
        mean_signed_pct_error_by_population={
            population: sum(values) / len(values)
            for population, values in sorted(signed_by_population.items())
        },
        population_status="PASS" if population_ok else "FAIL",
        quintile_population_status="PASS" if quintile_ok else "FAIL",
        all_cu_max_absolute_difference=max(
            (
                abs(r.absolute_difference)
                for r in results
                if r.population == "All Consumer Units"
            ),
            default=0.0,
        ),
        brr_rse_median_difference_pp=_median_rse_gap(results),
        failures_within_one_standard_error=sum(
            1
            for r in results
            if r.benchmark_status == "FAIL"
            and r.pumd_standard_error
            and abs(r.absolute_difference) <= r.pumd_standard_error
        ),
        benchmark_status="PASS" if not failed else "FAIL",
        failed_criteria=tuple(failed),
    )


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def write_csv(
    path: str | os.PathLike[str],
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
