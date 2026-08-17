"""Out-of-sample confirmation of the frozen 2024 PUMD estimator.

Detailed Inflation Substrate v0.1, research only. This module never touches
``dmi_calculator``, the Baseline, Slack-Plus, release workflows, production
manifests or the deployment output tree.

The Phase-B benchmark passed on a fifteen-UCC development roster, but that
roster was rebuilt from eighteen after two defects in the selection rule were
found and corrected. A roster that was present while a rule was being repaired
cannot by itself establish that the estimator generalises. This module asks a
different question, on data that played no part in that repair:

    does the estimator frozen at 95111fd continue to reproduce published 2024
    LB01 values when applied to eligible UCCs it has never been run against?

Two properties make the answer meaningful, and both are structural rather than
conventional.

First, **the estimator is not re-implemented here.** Every number is produced
by :func:`dmi_research.detailed_inflation.pumd_benchmark.run_benchmark` and
judged by :func:`~dmi_research.detailed_inflation.pumd_benchmark.summarize`.
This module contributes a roster and nothing else. It cannot change the
annualization, the ``MO_SCOPE`` treatment, the weight variable, the quintile
boundaries, the BRR replication or the small-value branch, because it does not
contain any of them.

Second, **the acceptance rule is not re-stated here.** :func:`confirmation_spec`
takes the frozen v0.2 :class:`~dmi_research.detailed_inflation.pumd_benchmark.BenchmarkSpec`
and returns ``dataclasses.replace(frozen, roster_hash=...)``. The roster hash
is the only field it is permitted to touch, and that is enforced by
construction: every threshold is carried over by object identity of value, not
by being typed a second time. A test compares the two specs field by field.

The confirmation set is the whole remaining eligible pool, not a sample. There
is no selection step in which a UCC could be dropped for reproducing badly,
because there is no selection step at all.
"""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .pumd import StubEntry
from .pumd_benchmark import (
    CHARACTERISTICS_ALL_CU,
    EXCLUDED_FROM_CALIBRATION,
    MAGNITUDE_STRATA,
    REQUIRED_CE_SOURCE,
    REQUIRED_CHARACTERISTICS,
    REQUIRED_PROVENANCE_CLASS,
    REQUIRED_STUB_SECTION,
    ROSTER_VERSION,
    BenchmarkResult,
    BenchmarkSpec,
    Candidate,
    RosterEntry,
    RosterError,
    assign_magnitude_strata,
    eligible_candidates,
    roster_hash,
    select_roster,
)

#: Version of the confirmation-set construction rule in this module. The
#: eligibility rule itself is not versioned here: it is
#: :data:`~dmi_research.detailed_inflation.pumd_benchmark.ROSTER_VERSION`,
#: reused unchanged.
CONFIRMATION_ROSTER_VERSION = "v0.1"
CONFIRMATION_SPEC_VERSION = "v0.1"

#: The commit at which the estimator and the acceptance rule were frozen, and
#: the annotated tag that preserves it. Nothing in the confirmation may be run
#: against a different estimator, so the run records what it ran against.
FROZEN_ESTIMATOR_COMMIT = "95111fd675f2d0287e5cc89398411e3322ad65a3"
FROZEN_ESTIMATOR_TAG = "dmi-detailed-inflation-v0.1-pumd-benchmark-2024"

#: Annualization factors the confirmation is willing to run. The frozen
#: estimator multiplies a UCC's summed cost by its hierarchical-grouping
#: factor; a factor other than one is a special transformation whose
#: correctness the Phase-B benchmark never exercised, because every UCC in the
#: development roster carried a factor of one. Rather than quietly assume the
#: untested path is sound, a UCC needing it is excluded and the exclusion is
#: recorded. In 2024 this excludes nothing, and the ledger says so.
RESOLVED_ANNUALIZATION_FACTORS = (1,)

#: Exclusion reasons, in the order they are tested. The order matters: a UCC
#: excluded for more than one reason is recorded under the first, so the tally
#: partitions the universe instead of double-counting it.
EXCLUSION_REASONS = (
    "MILESTONE_2_SHELTER_UCC",
    "NOT_DIRECT_CONCORDANCE_UCC",
    "CE_SOURCE_NOT_INTERVIEW",
    "MILESTONE_1_EXCEPTION",
    "ABSENT_FROM_INTERVIEW_STUB",
    "INTERVIEW_STUB_SECTION_NOT_EXPEND",
    "ABSENT_FROM_INTEGRATED_STUB",
    "INTEGRATED_STUB_SECTION_NOT_EXPEND",
    "INTEGRATED_STUB_SURVEY_NOT_INTERVIEW",
    "INCOMPLETE_LB01_PUBLICATION",
    "BLANK_PUBLISHED_MEAN",
    "UNRESOLVED_ANNUALIZATION_TRANSFORMATION",
    "IN_DEVELOPMENT_ROSTER",
)

#: Reasons the confirmation adds on top of the frozen eligibility rule. A UCC
#: excluded for one of these is still eligible under the frozen rule; it is
#: held out because the confirmation asks a narrower question. Keeping the two
#: kinds of exclusion distinct is what lets the agreement check in
#: :func:`confirmation_roster` be exact.
CONFIRMATION_ADDED_REASONS = (
    "UNRESOLVED_ANNUALIZATION_TRANSFORMATION",
    "IN_DEVELOPMENT_ROSTER",
)

#: Status of a UCC in the confirmation universe ledger.
INCLUDED = "INCLUDED_IN_CONFIRMATION"
EXCLUDED = "EXCLUDED"

UNIVERSE_COLUMNS = (
    "ucc",
    "status",
    "exclusion_reason",
    "provenance_class",
    "ce_source",
    "dmi_node",
    "all_cu_published_mean",
    "magnitude_stratum",
    "annualization_factor",
)


class ConfirmationError(ValueError):
    """The confirmation set could not be built from the frozen inputs."""


@dataclass(frozen=True)
class UniverseRow:
    """One UCC in the complete candidate universe, included or not.

    Every UCC carried by the Milestone-2 provenance classification appears
    exactly once, so the ledger is a partition and its included count can be
    reconciled against the eligible pool.
    """

    ucc: str
    status: str
    exclusion_reason: str
    provenance_class: str
    ce_source: str
    dmi_node: str
    all_cu_published_mean: float | None
    magnitude_stratum: str
    annualization_factor: int | None

    def __post_init__(self) -> None:
        if self.status not in (INCLUDED, EXCLUDED):
            raise ConfirmationError(f"unknown universe status {self.status!r}")
        if self.status == EXCLUDED and self.exclusion_reason not in EXCLUSION_REASONS:
            raise ConfirmationError(
                f"UCC {self.ucc} is excluded for unstated reason "
                f"{self.exclusion_reason!r}"
            )
        if self.status == INCLUDED and self.exclusion_reason:
            raise ConfirmationError(
                f"UCC {self.ucc} is included but carries exclusion reason "
                f"{self.exclusion_reason!r}"
            )


def classify_universe(
    provenance_rows: Iterable[Mapping[str, str]],
    basis_rows: Iterable[Mapping[str, str]],
    exception_uccs: Iterable[str],
    interview_stub: Mapping[str, StubEntry],
    integrated_stub: Mapping[str, StubEntry],
) -> list[UniverseRow]:
    """Attribute an outcome to every UCC in the candidate universe.

    The tests below are the frozen Phase-B eligibility tests, applied in the
    frozen order, with one addition at the end: a UCC that survives them all
    is still excluded if it sits in the fifteen-UCC development roster, since
    the point of the confirmation is that it has not been seen.

    This function reproduces the eligibility logic in order to say *why* each
    UCC failed, which :func:`~dmi_research.detailed_inflation.pumd_benchmark.eligible_candidates`
    does not report. That duplication is a real risk, so it is checked rather
    than trusted: :func:`confirmation_roster` asserts that the set this
    function calls eligible is exactly the set the frozen function returns,
    and raises :class:`ConfirmationError` if the two ever disagree.
    """
    provenance_rows = list(provenance_rows)
    basis_rows = list(basis_rows)
    exceptions = set(exception_uccs)
    development = {
        entry.ucc
        for entry in select_roster(
            provenance_rows, basis_rows, exceptions, interview_stub, integrated_stub
        )
    }
    pool = eligible_candidates(
        provenance_rows, basis_rows, exceptions, interview_stub, integrated_stub
    )
    strata = assign_magnitude_strata(pool)

    cells: dict[str, dict[str, Mapping[str, str]]] = {}
    for row in basis_rows:
        cells.setdefault(row["ucc"], {})[row["characteristics_code"]] = row

    rows: list[UniverseRow] = []
    for row in provenance_rows:
        ucc = row["ucc"]
        reason = _exclusion_reason(
            row, exceptions, interview_stub, integrated_stub, cells.get(ucc, {}),
            development,
        )
        published = cells.get(ucc, {}).get(CHARACTERISTICS_ALL_CU)
        mean_text = (published or {}).get("mean_expenditure", "").strip()
        entry = interview_stub.get(ucc)
        rows.append(
            UniverseRow(
                ucc=ucc,
                status=EXCLUDED if reason else INCLUDED,
                exclusion_reason=reason,
                provenance_class=row["provenance_class"],
                ce_source=row["ce_source"],
                dmi_node=row["dmi_node"],
                all_cu_published_mean=float(mean_text) if mean_text else None,
                magnitude_stratum=strata.get(ucc, ""),
                annualization_factor=entry.factor if entry is not None else None,
            )
        )
    rows.sort(key=lambda item: item.ucc)
    return rows


def _exclusion_reason(
    row: Mapping[str, str],
    exceptions: set[str],
    interview_stub: Mapping[str, StubEntry],
    integrated_stub: Mapping[str, StubEntry],
    published_cells: Mapping[str, Mapping[str, str]],
    development: set[str],
) -> str:
    """First reason this UCC is not in the confirmation set, or ``""``."""
    ucc = row["ucc"]
    if ucc in EXCLUDED_FROM_CALIBRATION:
        return "MILESTONE_2_SHELTER_UCC"
    if row["provenance_class"] != REQUIRED_PROVENANCE_CLASS:
        return "NOT_DIRECT_CONCORDANCE_UCC"
    if row["ce_source"] != REQUIRED_CE_SOURCE:
        return "CE_SOURCE_NOT_INTERVIEW"
    if ucc in exceptions:
        return "MILESTONE_1_EXCEPTION"
    entry = interview_stub.get(ucc)
    if entry is None:
        return "ABSENT_FROM_INTERVIEW_STUB"
    if entry.section != REQUIRED_STUB_SECTION:
        return "INTERVIEW_STUB_SECTION_NOT_EXPEND"
    integrated = integrated_stub.get(ucc)
    if integrated is None:
        return "ABSENT_FROM_INTEGRATED_STUB"
    if integrated.section != REQUIRED_STUB_SECTION:
        return "INTEGRATED_STUB_SECTION_NOT_EXPEND"
    if integrated.survey != REQUIRED_CE_SOURCE:
        return "INTEGRATED_STUB_SURVEY_NOT_INTERVIEW"
    if set(published_cells) != set(REQUIRED_CHARACTERISTICS):
        return "INCOMPLETE_LB01_PUBLICATION"
    if any(not published_cells[code]["mean_expenditure"].strip() for code in published_cells):
        return "BLANK_PUBLISHED_MEAN"
    if entry.factor not in RESOLVED_ANNUALIZATION_FACTORS:
        return "UNRESOLVED_ANNUALIZATION_TRANSFORMATION"
    if ucc in development:
        return "IN_DEVELOPMENT_ROSTER"
    return ""


def confirmation_roster(
    provenance_rows: Iterable[Mapping[str, str]],
    basis_rows: Iterable[Mapping[str, str]],
    exception_uccs: Iterable[str],
    interview_stub: Mapping[str, StubEntry],
    integrated_stub: Mapping[str, StubEntry],
) -> list[RosterEntry]:
    """Return the confirmation roster: every eligible UCC not already used.

    There is no sampling and no stratified draw. The frozen development rule
    kept one median UCC per (node, stratum) cell and dropped nodes that did
    not span all three strata; neither device is applied here, because both
    exist to build a small balanced roster and the confirmation is not small.
    Taking the entire remainder is the choice that leaves least room for the
    set to have been shaped by anything.

    Magnitude strata are still recorded, computed by the frozen
    :func:`~dmi_research.detailed_inflation.pumd_benchmark.assign_magnitude_strata`
    over the full eligible pool, so confirmation results can be read against
    development results stratum by stratum. The stratum is a label on the
    output, not a filter on the input.
    """
    provenance_rows = list(provenance_rows)
    basis_rows = list(basis_rows)
    exceptions = set(exception_uccs)

    pool = eligible_candidates(
        provenance_rows, basis_rows, exceptions, interview_stub, integrated_stub
    )
    universe = classify_universe(
        provenance_rows, basis_rows, exceptions, interview_stub, integrated_stub
    )

    # The ledger duplicates the frozen eligibility logic in order to report a
    # reason. Prove the duplicate agrees with the original before trusting it.
    ledger_eligible = {
        row.ucc
        for row in universe
        if row.status == INCLUDED or row.exclusion_reason in CONFIRMATION_ADDED_REASONS
    }
    frozen_eligible = {candidate.ucc for candidate in pool}
    if ledger_eligible != frozen_eligible:
        raise ConfirmationError(
            "the confirmation universe ledger disagrees with the frozen "
            "eligibility rule: "
            f"ledger-only {sorted(ledger_eligible - frozen_eligible)}, "
            f"frozen-only {sorted(frozen_eligible - ledger_eligible)}"
        )

    strata = assign_magnitude_strata(pool)
    cells: dict[tuple[str, str], list[Candidate]] = {}
    for candidate in pool:
        cells.setdefault((candidate.dmi_node, strata[candidate.ucc]), []).append(candidate)

    selected = {row.ucc for row in universe if row.status == INCLUDED}
    if not selected:
        raise ConfirmationError("the confirmation roster is empty")

    roster: list[RosterEntry] = []
    for candidate in pool:
        if candidate.ucc not in selected:
            continue
        stratum = strata[candidate.ucc]
        members = cells[(candidate.dmi_node, stratum)]
        roster.append(
            RosterEntry(
                ucc=candidate.ucc,
                published_title=candidate.published_title,
                dmi_node=candidate.dmi_node,
                domain_label=candidate.domain_label,
                stub_title=candidate.stub_title,
                annualization_factor=candidate.annualization_factor,
                magnitude_stratum=stratum,
                all_cu_published_mean=candidate.all_cu_published_mean,
                all_cu_published_rse=candidate.all_cu_published_rse,
                selection_rank_in_cell=members.index(candidate),
                cell_size=len(members),
            )
        )
    roster.sort(key=lambda entry: entry.ucc)
    return roster


def confirmation_spec(frozen: BenchmarkSpec, roster: Sequence[RosterEntry]) -> BenchmarkSpec:
    """The frozen v0.2 acceptance rule, repointed at the confirmation roster.

    ``summarize`` refuses any roster whose content hash differs from the one
    the spec pins, which is exactly the protection that stops a development
    roster drifting past a frozen rule. A confirmation run has to get past it
    with a different roster, and the safe way to do that is to change the
    pinned hash and nothing else.

    Using :func:`dataclasses.replace` rather than constructing a new spec is
    the point. No threshold is retyped, so no threshold can be mistyped, and
    the only edit that can occur is the one named in the call.
    """
    if frozen.spec_version != "v0.2":
        raise ConfirmationError(
            f"the confirmation must run the v0.2 acceptance rule; got "
            f"{frozen.spec_version!r}"
        )
    if frozen.roster_version != ROSTER_VERSION:
        raise ConfirmationError(
            f"frozen spec roster version {frozen.roster_version!r} does not "
            f"match the selection rule version {ROSTER_VERSION!r}"
        )
    return dataclasses.replace(frozen, roster_hash=roster_hash(roster))


#: Threshold fields of :class:`BenchmarkSpec`. A test asserts that
#: :func:`confirmation_spec` leaves every one of them alone.
THRESHOLD_FIELDS = (
    "spec_version",
    "roster_version",
    "estimand",
    "population_tolerance_pct",
    "quintile_population_tolerance_pct",
    "median_abs_pct_error_max",
    "p75_abs_pct_error_max",
    "p90_abs_pct_error_max",
    "per_ucc_abs_pct_error_max",
    "per_ucc_pass_fraction_min",
    "mean_signed_pct_error_abs_max",
    "small_value_absolute_floor",
    "small_value_abs_diff_max",
    "excluded_from_calibration",
)


def universe_rows(universe: Sequence[UniverseRow]) -> list[dict[str, str]]:
    return [
        {
            "ucc": row.ucc,
            "status": row.status,
            "exclusion_reason": row.exclusion_reason,
            "provenance_class": row.provenance_class,
            "ce_source": row.ce_source,
            "dmi_node": row.dmi_node,
            "all_cu_published_mean": (
                "" if row.all_cu_published_mean is None
                else f"{row.all_cu_published_mean:.1f}"
            ),
            "magnitude_stratum": row.magnitude_stratum,
            "annualization_factor": (
                "" if row.annualization_factor is None else str(row.annualization_factor)
            ),
        }
        for row in universe
    ]


def universe_hash(universe: Sequence[UniverseRow]) -> str:
    """Content hash of the universe ledger, in UCC order."""
    payload = "\n".join(
        "|".join((row.ucc, row.status, row.exclusion_reason))
        for row in sorted(universe, key=lambda item: item.ucc)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def exclusion_tally(universe: Sequence[UniverseRow]) -> dict[str, int]:
    """Count of excluded UCCs by reason, in the declared reason order."""
    counts = {reason: 0 for reason in EXCLUSION_REASONS}
    for row in universe:
        if row.status == EXCLUDED:
            counts[row.exclusion_reason] += 1
    return counts


def file_digest(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Confirmation-only diagnostics
# ---------------------------------------------------------------------------
#
# Nothing below feeds the acceptance rule. ``summarize`` reads none of it, and
# the confirmation verdict is whatever ``summarize`` returns. These exist
# because Phase B asks for failures broken out by DMI node, and because a
# confirmation over 111 UCCs is worth reading stratum by stratum, not because
# any of it can change PASS into FAIL.


def failures_by_node(results: Sequence[BenchmarkResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.benchmark_status == "FAIL":
            counts[result.dmi_node] = counts.get(result.dmi_node, 0) + 1
    return dict(sorted(counts.items()))


def cells_by_node(results: Sequence[BenchmarkResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.dmi_node] = counts.get(result.dmi_node, 0) + 1
    return dict(sorted(counts.items()))


def small_value_outcome(results: Sequence[BenchmarkResult]) -> dict[str, float | int]:
    """How the cells judged on absolute difference behaved.

    Reported separately because they are excluded from the percentage
    distribution by the frozen rule, which means a summary that quoted only
    the percentile statistics would be silent about them.
    """
    small = [r for r in results if r.judged_on == "ABSOLUTE_DIFFERENCE"]
    if not small:
        return {"count": 0}
    differences = [abs(r.absolute_difference) for r in small]
    ordered = sorted(differences)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2.0
    )
    return {
        "count": len(small),
        "pass_count": sum(1 for r in small if r.benchmark_status == "PASS"),
        "fail_count": sum(1 for r in small if r.benchmark_status == "FAIL"),
        "median_absolute_difference": median,
        "max_absolute_difference": max(differences),
    }


def stratum_breakdown(results: Sequence[BenchmarkResult]) -> dict[str, dict[str, float]]:
    """Cell count, pass fraction and median absolute error, by stratum."""
    breakdown: dict[str, dict[str, float]] = {}
    for stratum in MAGNITUDE_STRATA:
        cells = [r for r in results if r.magnitude_stratum == stratum]
        if not cells:
            continue
        comparable = sorted(
            abs(r.percentage_difference)
            for r in cells
            if r.judged_on == "PERCENTAGE_DIFFERENCE" and r.percentage_difference is not None
        )
        middle = len(comparable) // 2
        median = (
            float("nan")
            if not comparable
            else comparable[middle]
            if len(comparable) % 2
            else (comparable[middle - 1] + comparable[middle]) / 2.0
        )
        breakdown[stratum] = {
            "cells": len(cells),
            "pass_fraction": sum(1 for r in cells if r.benchmark_status == "PASS") / len(cells),
            "median_abs_pct_error": median,
        }
    return breakdown


def rse_corroboration(results: Sequence[BenchmarkResult]) -> dict[str, float | int]:
    """Agreement between the BRR relative standard error and LB01's.

    LB01 publishes an RSE that BLS computes independently of the mean, so
    agreement here is evidence about the replicate weights rather than about
    the point estimate. It is a diagnostic; no threshold reads it.
    """
    gaps = sorted(
        100.0 * r.pumd_standard_error / r.pumd_value - r.published_rse
        for r in results
        if r.published_rse is not None
        and r.pumd_standard_error is not None
        and r.pumd_value > 0
    )
    if not gaps:
        return {"count": 0}
    middle = len(gaps) // 2
    median = gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2.0
    return {
        "count": len(gaps),
        "median_gap_pp": median,
        "min_gap_pp": gaps[0],
        "max_gap_pp": gaps[-1],
        "within_5pp_fraction": sum(1 for gap in gaps if abs(gap) <= 5.0) / len(gaps),
    }
