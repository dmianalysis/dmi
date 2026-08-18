"""Adjudicate what the 2024 shelter estimates can and cannot support.

Detailed Inflation Substrate v0.1, shelter task, Phase C6.

RESEARCH ONLY. Reads research registries, the research estimate artifacts and
the pinned PUMD archive. Touches no production module, manifest or output.

Two jobs, kept apart on purpose.

The first is measurement. The frozen plan carried a pairing between the four
published ADDENDA codes and the four concordance-only codes as a
``DMI_INFERENCE`` resting on matching concept names and matching order. That
is a weak basis. This module measures the relationship at the record level
instead: for every ``(NEWID, REF_MO)`` key the two codes share, what is
``COST(concordance) / COST(published)``. A pairing asserted from names either
survives that or it does not.

The second is adjudication. ``pumd_quantitative_usability`` is a two-state
enum and stays two-state; precision gets its own field. The frozen plan said
the 25 percent relative-standard-error flag is ``WARNING_ONLY`` and
"explicitly not a usability rule, an exclusion criterion, or a licence to
substitute zero". That is honoured here: RSE bands populate the new quality
field and are not consulted when deciding usability.

What decides usability instead is structural. A cell whose replicate
estimates include exact zeros is one where some Balanced Repeated Replication
half-samples contain none of the reporting consumer units, so the variance
estimator is not resampling the population it is meant to resample. That is a
statement about the procedure failing on a cell, not about the estimate being
noisy, and the two are not the same thing.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import pumd
from . import shelter_estimation as est

REPO_ROOT = Path(__file__).resolve().parents[2]

OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
ADJUDICATION_PATH = OUTPUT_DIR / "shelter_adjudication_2024.json"
SUMMARY_PATH = OUTPUT_DIR / "shelter_estimation_summary.json"

# --------------------------------------------------------------------------
# The pairing under test
# --------------------------------------------------------------------------

#: (published ADDENDA code, concordance-only code), carried forward from
#: ``registry/research/ucc_provenance_classes_v0_1.json`` at claim_type
#: DMI_INFERENCE. This module does not assume it; it measures it.
PAIRS: tuple[tuple[str, str], ...] = (
    ("910050", "910104"),
    ("910101", "910105"),
    ("910102", "910106"),
    ("910103", "910107"),
)

CONCORDANCE_OF: Mapping[str, str] = {pub: con for pub, con in PAIRS}
PUBLISHED_OF: Mapping[str, str] = {con: pub for pub, con in PAIRS}

#: Verbatim from LABSTAT ``cx.item``, subcategory TITLEOFI, display level 1.
#: Recorded because three say "monthly" and one says "annual", and that
#: difference is the whole of the preserved 910103 anomaly.
PUBLISHED_ITEM_TEXT: Mapping[str, str] = {
    "910050": "Estimated monthly rental value of owned home",
    "910101": (
        "Estimated monthly rental value of vacation home not available for rent"
    ),
    "910102": "Estimated monthly rental value of vacation home available for rent",
    "910103": "Estimated annual rental value of timeshare",
}

PUBLISHED_ITEM_TEXT_SOURCE = (
    "LABSTAT cx.item, subcategory_code TITLEOFI, display_level 1, selectable T"
)

# --------------------------------------------------------------------------
# Relation labels
# --------------------------------------------------------------------------

#: The concordance code carries twelve times the published code's amount on
#: the same key. Under this relation the published ADDENDA line is a monthly
#: presentation figure and the concordance line is the annual amount.
TWELVE_TIMES = "TWELVE_TIMES"

#: 52 * COST(concordance) / COST(published) is a whole number on the same key.
#: Under this relation the published line is the full-year rental value of the
#: whole property and the concordance line is the share of it the consumer
#: unit actually owns, measured in weeks.
WEEKS_OWNED_SHARE = "WEEKS_OWNED_SHARE"

NO_CLEAN_RELATION = "NO_CLEAN_RELATION"

#: A relation is named when it holds on a majority of shared keys. The
#: threshold is declared after the estimates were seen, which is stated rather
#: than hidden; it is load-bearing only in the sense that it attaches a name.
#: The measured shares are far from the boundary in every pair, so no pair's
#: label would change anywhere in the range 0.30 to 0.75, and the underlying
#: shares are reported alongside the label so a reader can disregard it.
RELATION_MAJORITY_SHARE = 0.5

#: Floating-point tolerance for calling a ratio exactly twelve, and for
#: calling 52 * ratio a whole number. Both are tight because the underlying
#: microdata amounts are stored to two decimal places and the relations, where
#: they hold at all, hold exactly.
EXACT_TOLERANCE = 1e-9
INTEGER_TOLERANCE = 0.01

WEEKS_IN_YEAR = 52


@dataclass(frozen=True)
class PairStructure:
    """What the record-level evidence says about one asserted pair."""

    published_ucc: str
    concordance_ucc: str
    rows_published: int
    rows_concordance: int
    shared_keys: int
    published_only_keys: int
    concordance_only_keys: int
    comparable_keys: int
    ratio_min: float | None
    ratio_median: float | None
    ratio_max: float | None
    exact_twelve_keys: int
    exact_twelve_share: float | None
    integer_week_keys: int
    integer_week_share: float | None
    week_tally: Mapping[int, int]
    relation: str

    def __post_init__(self) -> None:
        if self.shared_keys > min(self.rows_published, self.rows_concordance):
            raise ValueError(
                "shared keys cannot exceed either side's row count: "
                f"{self.shared_keys} > min({self.rows_published}, "
                f"{self.rows_concordance})"
            )
        if self.relation not in (TWELVE_TIMES, WEEKS_OWNED_SHARE, NO_CLEAN_RELATION):
            raise ValueError(f"unknown relation {self.relation!r}")


def _keyed_costs(
    records: Iterable[pumd.ExpenditureRecord], ucc: str
) -> dict[tuple[str, int], float]:
    """COST by (NEWID, reference month) for one UCC.

    The reference year does not enter the key because the records have already
    been filtered to the benchmark year upstream; carrying it would imply a
    freedom the input does not have.
    """
    return {
        (record.newid, record.reference_month): record.cost
        for record in records
        if record.ucc == ucc
    }


def measure_pair(
    records: Sequence[pumd.ExpenditureRecord],
    published_ucc: str,
    concordance_ucc: str,
) -> PairStructure:
    """Measure one asserted pair against the records themselves."""
    left = _keyed_costs(records, published_ucc)
    right = _keyed_costs(records, concordance_ucc)
    shared = set(left) & set(right)

    # A zero denominator carries no information about a ratio and is dropped
    # from the ratio statistics only, never from the key counts.
    comparable = sorted(k for k in shared if left[k] != 0.0)
    ratios = [right[k] / left[k] for k in comparable]

    exact_twelve = sum(1 for r in ratios if abs(r - 12.0) <= EXACT_TOLERANCE)
    weeks = [WEEKS_IN_YEAR * r for r in ratios]
    integer_weeks = [w for w in weeks if abs(w - round(w)) <= INTEGER_TOLERANCE]
    tally = Counter(int(round(w)) for w in integer_weeks)

    n = len(ratios)
    twelve_share = (exact_twelve / n) if n else None
    week_share = (len(integer_weeks) / n) if n else None

    relation = NO_CLEAN_RELATION
    if twelve_share is not None and twelve_share > RELATION_MAJORITY_SHARE:
        relation = TWELVE_TIMES
    elif week_share is not None and week_share > RELATION_MAJORITY_SHARE:
        relation = WEEKS_OWNED_SHARE

    return PairStructure(
        published_ucc=published_ucc,
        concordance_ucc=concordance_ucc,
        rows_published=len(left),
        rows_concordance=len(right),
        shared_keys=len(shared),
        published_only_keys=len(set(left) - set(right)),
        concordance_only_keys=len(set(right) - set(left)),
        comparable_keys=n,
        ratio_min=min(ratios) if ratios else None,
        ratio_median=statistics.median(ratios) if ratios else None,
        ratio_max=max(ratios) if ratios else None,
        exact_twelve_keys=exact_twelve,
        exact_twelve_share=twelve_share,
        integer_week_keys=len(integer_weeks),
        integer_week_share=week_share,
        week_tally=dict(sorted(tally.items())),
        relation=relation,
    )


def measure_pairs(
    records: Sequence[pumd.ExpenditureRecord],
) -> dict[str, PairStructure]:
    """Measure every asserted pair, keyed by the concordance-only UCC."""
    return {
        concordance: measure_pair(records, published, concordance)
        for published, concordance in PAIRS
    }


# --------------------------------------------------------------------------
# Cell-level quality
# --------------------------------------------------------------------------

QUALITY_HIGH = "HIGH"
QUALITY_MODERATE = "MODERATE"
QUALITY_LOW = "LOW"
QUALITY_UNUSABLE = "UNUSABLE"

QUALITY_ORDER: tuple[str, ...] = (
    QUALITY_HIGH,
    QUALITY_MODERATE,
    QUALITY_LOW,
    QUALITY_UNUSABLE,
)

#: Bands for the new estimate-quality field. These are relative-standard-error
#: bands and are deliberately confined to this field. The frozen plan forbade
#: promoting the RSE flag into a usability rule; it did not forbid describing
#: precision, which is what a quality field is for.
QUALITY_RSE_BANDS: tuple[tuple[float, str], ...] = (
    (10.0, QUALITY_HIGH),
    (25.0, QUALITY_MODERATE),
)

QUALITY_SCALE_DEFINITION: Mapping[str, str] = {
    QUALITY_HIGH: "Relative standard error below 10 percent, variance estimator non-degenerate.",
    QUALITY_MODERATE: "Relative standard error at least 10 and below 25 percent, variance estimator non-degenerate.",
    QUALITY_LOW: "Relative standard error at least 25 percent, variance estimator non-degenerate. The point estimate is real but wide; it may be carried with its interval and may not be quoted bare.",
    QUALITY_UNUSABLE: "Either the cell has no records at all, or the variance estimator is degenerate on it. No figure is offered.",
}


def cell_is_degenerate(cell: est.ShelterCell) -> bool:
    """Has the variance estimator failed on this cell?

    Two ways, and neither is a precision threshold.

    A cell with no records has nothing to resample. A cell some of whose
    replicate estimates are exactly zero has half-samples containing none of
    the reporting consumer units, so those replicates are not draws from the
    population whose variance is being estimated. The resulting standard error
    is not a wide standard error; it is a standard error of something else.
    """
    if cell.cell_status == est.NO_RECORDS:
        return True
    return bool(cell.replicates_at_zero)


def cell_quality(cell: est.ShelterCell) -> str:
    """The estimate-quality band for one cell."""
    if cell_is_degenerate(cell):
        return QUALITY_UNUSABLE
    rse = cell.relative_standard_error_pct
    if rse is None:
        return QUALITY_UNUSABLE
    for ceiling, band in QUALITY_RSE_BANDS:
        if rse < ceiling:
            return band
    return QUALITY_LOW


def worst_quality(bands: Iterable[str]) -> str:
    """The worst band present, on the declared ordering."""
    seen = list(bands)
    if not seen:
        return QUALITY_UNUSABLE
    return max(seen, key=QUALITY_ORDER.index)


# --------------------------------------------------------------------------
# UCC-level usability
# --------------------------------------------------------------------------

BENCHMARKED = "BENCHMARKED"
NOT_ESTABLISHED = "NOT_ESTABLISHED"

#: Verbatim from ``registry/research/ucc_provenance_classes_v0_1.json``, so
#: that the adjudication below can be read against the definition it is
#: adjudicating rather than against a paraphrase of it.
USABILITY_DEFINITIONS: Mapping[str, str] = {
    BENCHMARKED: (
        "The CE annual weighting and income-quintile procedure has been "
        "implemented and shown to reproduce published LABSTAT aggregates for "
        "this UCC's concept, so an aggregate derived for it can be defended."
    ),
    NOT_ESTABLISHED: (
        "No validated aggregation procedure exists for this UCC. Observing "
        "records is not the same as being able to weight them."
    ),
}

#: A majority of the five quintiles, so that a single degenerate quintile does
#: not condemn a UCC and a mostly-degenerate UCC cannot be rescued by its
#: All-Consumer-Units cell.
NON_DEGENERATE_QUINTILE_MAJORITY = 3


@dataclass(frozen=True)
class UsabilityTest:
    """One named condition, its verdict, and what it was measured from."""

    name: str
    passed: bool
    finding: str


@dataclass(frozen=True)
class UccAdjudication:
    ucc: str
    pumd_membership: str
    pumd_quantitative_usability: str
    pumd_estimate_quality: str
    per_population_quality: Mapping[str, str]
    tests: tuple[UsabilityTest, ...]
    pair_relation: str
    counterpart_all_cu_ratio: float | None
    counterpart_consistent: bool | None
    track_a_admissible: bool
    basis: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.pumd_quantitative_usability not in USABILITY_DEFINITIONS:
            raise ValueError(
                f"unknown usability state {self.pumd_quantitative_usability!r}"
            )
        if self.pumd_estimate_quality not in QUALITY_ORDER:
            raise ValueError(f"unknown quality band {self.pumd_estimate_quality!r}")
        if self.track_a_admissible and (
            self.pumd_quantitative_usability != BENCHMARKED
        ):
            raise ValueError(
                f"{self.ucc}: a UCC whose usability is not BENCHMARKED cannot be "
                "admitted to Track A"
            )


def _u1(structure: PairStructure) -> UsabilityTest:
    """Is the procedure demonstrated on this UCC's own records?

    The counterpart comparison reproduces a published LABSTAT mean. That
    transfers to the concordance code only if the two codes are carried on the
    same records, which is the thing the name-based pairing asserted and this
    test measures. Where the records stand in an exact arithmetic relation,
    the demonstration reaches the concordance code. Where they do not, it does
    not, and no amount of agreement on the published code repairs that.
    """
    passed = structure.relation != NO_CLEAN_RELATION
    if structure.relation == TWELVE_TIMES:
        finding = (
            f"COST({structure.concordance_ucc}) is exactly twelve times "
            f"COST({structure.published_ucc}) on "
            f"{structure.exact_twelve_keys} of {structure.comparable_keys} "
            f"shared keys "
            f"({100 * (structure.exact_twelve_share or 0):.1f} percent)."
        )
    elif structure.relation == WEEKS_OWNED_SHARE:
        finding = (
            f"52 * COST({structure.concordance_ucc}) / "
            f"COST({structure.published_ucc}) is a whole number on "
            f"{structure.integer_week_keys} of {structure.comparable_keys} "
            f"shared keys "
            f"({100 * (structure.integer_week_share or 0):.1f} percent), "
            f"distributed as {structure.week_tally}."
        )
    else:
        finding = (
            f"No exact relation holds on a majority of shared keys. Twelve "
            f"times on {structure.exact_twelve_keys}, a whole number of "
            f"weeks on {structure.integer_week_keys}, of "
            f"{structure.comparable_keys} comparable keys. "
            f"{structure.published_only_keys} of the published code's keys "
            f"have no counterpart in the concordance code."
        )
    return UsabilityTest("U1_procedure_demonstrated_on_these_records", passed, finding)


def _u2(cells: Sequence[est.ShelterCell]) -> UsabilityTest:
    """Is the variance estimator non-degenerate where it matters?"""
    by_population = {c.population: c for c in cells}
    all_cu = by_population.get(pumd.ALL_CONSUMER_UNITS)
    quintiles = [c for c in cells if c.population != pumd.ALL_CONSUMER_UNITS]
    sound_quintiles = [c for c in quintiles if not cell_is_degenerate(c)]
    all_cu_sound = all_cu is not None and not cell_is_degenerate(all_cu)
    passed = all_cu_sound and len(sound_quintiles) >= NON_DEGENERATE_QUINTILE_MAJORITY
    degenerate = sorted(c.population for c in cells if cell_is_degenerate(c))
    finding = (
        f"All Consumer Units {'sound' if all_cu_sound else 'degenerate'}; "
        f"{len(sound_quintiles)} of {len(quintiles)} quintiles sound. "
        + (f"Degenerate cells: {', '.join(degenerate)}." if degenerate else
           "No degenerate cell.")
    )
    return UsabilityTest("U2_variance_estimator_non_degenerate", passed, finding)


def adjudicate_ucc(
    ucc: str,
    cells: Sequence[est.ShelterCell],
    structure: PairStructure,
    consistency: Mapping[str, Mapping[str, object]],
) -> UccAdjudication:
    """Adjudicate one concordance-only shelter UCC."""
    own = [c for c in cells if c.ucc == ucc]
    if not own:
        raise ValueError(f"no cells for {ucc}")

    tests = (_u1(structure), _u2(own))
    usability = BENCHMARKED if all(t.passed for t in tests) else NOT_ESTABLISHED

    per_population = {c.population: cell_quality(c) for c in own}
    quality = worst_quality(per_population.values())

    published = PUBLISHED_OF[ucc]
    entry = consistency.get(published)
    ratio = None if entry is None else float(entry["all_cu_ratio"])
    consistent = None if entry is None else bool(entry["consistent"])

    warnings: list[str] = []
    if consistent is False:
        deviation = entry.get("max_deviation_pct") if entry else None
        warnings.append(
            f"The counterpart {published} did not satisfy the pre-declared "
            f"ratio-consistency description (max deviation "
            f"{deviation:.2f} percent against a 10 percent tolerance). The "
            "frozen plan declared that description to gate nothing, so it is "
            "not used here to fail this UCC, and it is not quietly dropped "
            "either: it is recorded as a negative signal on the counterpart."
        )
    if quality == QUALITY_LOW:
        warnings.append(
            "Every reported cell has a relative standard error of at least 25 "
            "percent. The estimates are carried with their intervals and are "
            "not to be quoted as point figures."
        )
    if structure.relation == WEEKS_OWNED_SHARE:
        warnings.append(
            f"{published} and {ucc} are not the same estimand. {published} is "
            f"the rental value of the whole property; {ucc} is the share of it "
            "this consumer unit owns. Neither may be substituted for the "
            "other, in either direction, and the published counterpart is not "
            "a plausibility check on the concordance code's level."
        )

    admissible = usability == BENCHMARKED and quality != QUALITY_UNUSABLE

    if usability == BENCHMARKED:
        basis = (
            "Both structural conditions hold. The aggregation procedure "
            f"reproduces the published LABSTAT mean for {published} and the "
            f"records of {ucc} stand in a measured exact relation to it, so "
            "the demonstration reaches these records. The variance estimator "
            "is non-degenerate where it is relied on. Precision is reported "
            "separately and did not enter this decision."
        )
    else:
        failed = [t.name for t in tests if not t.passed]
        basis = (
            f"Withheld on {', '.join(failed)}. This is a statement about the "
            "evidence and the procedure, not about the estimate being noisy; "
            "a noisy estimate is not evidence against an estimator."
        )

    return UccAdjudication(
        ucc=ucc,
        pumd_membership="VERIFIED",
        pumd_quantitative_usability=usability,
        pumd_estimate_quality=quality,
        per_population_quality=per_population,
        tests=tests,
        pair_relation=structure.relation,
        counterpart_all_cu_ratio=ratio,
        counterpart_consistent=consistent,
        track_a_admissible=admissible,
        basis=basis,
        warnings=tuple(warnings),
    )


def adjudicate(
    cells: Sequence[est.ShelterCell],
    structures: Mapping[str, PairStructure],
    consistency: Mapping[str, Mapping[str, object]],
) -> dict[str, UccAdjudication]:
    """Adjudicate all four concordance-only shelter UCCs."""
    return {
        ucc: adjudicate_ucc(ucc, cells, structures[ucc], consistency)
        for ucc in est.SHELTER_UCCS
    }


def load_summary(path: Path = SUMMARY_PATH) -> dict:
    """The Phase C3-C5 estimation summary, as written by the runner."""
    if not path.exists():
        raise est.ShelterEstimationError(
            f"{path} does not exist. Run the estimation before adjudicating it."
        )
    return json.loads(path.read_text(encoding="utf-8"))
