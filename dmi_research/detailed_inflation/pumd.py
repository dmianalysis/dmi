"""2024 CE Interview PUMD estimation stages.

Detailed Inflation Substrate v0.1, PUMD/LB01 benchmark (Phase B).

RESEARCH ONLY. Nothing in this module is imported by ``dmi_calculator``, by
the operational Baseline or Slack-Plus paths, or by any release workflow. It
exists to answer one question and no other: can the public 2024 CE Interview
PUMD be turned into annual All-CU and income-quintile estimates that reproduce
published Table 1101 / LABSTAT LB01 closely enough to be a defensible source?

Answering "yes" would still not authorize any DMI figure to be sourced from
PUMD. That is a separate decision recorded elsewhere.

Every constant here is traceable to a primary BLS document recorded in
``registry/research/pumd_2024_interview_source_v0_1.json``. Where BLS
documentation and the actual 2024 files disagree, the files win and the
disagreement is recorded rather than absorbed.

The stages are deliberately separate and separately inspectable, in this
order, so that a wrong answer can be localised:

    1. locate       - resolve the extracted CSV directory, or fail loudly
    2. read_stub    - UCC publication roster, survey source, annualization
    3. read_fmli    - consumer-unit records, weights, income
    4. months_in_scope / population_weight - the weighting stage
    5. assign_quintile                     - the quintile stage
    6. read_mtbi    - calendar-year-eligible expenditure records
    7. weighted_ucc_means                  - the estimation stage

No single function performs more than one of these.
"""

from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

# --------------------------------------------------------------------------
# Constants, each traceable to a primary source
# --------------------------------------------------------------------------

#: Calendar year under benchmark.
BENCHMARK_YEAR = 2024

#: "for an annual estimate (4 quarters) QNUM is 4" - PUMD Getting Started
#: Guide section 6.3.1.
QNUM = 4

#: The 44 balanced half-sample replicate weights - Getting Started Guide 6.3.2.
REPLICATE_WEIGHT_COUNT = 44

#: Final consumer-unit weight - Getting Started Guide 6.3.
FINAL_WEIGHT_VARIABLE = "FINLWT21"

#: Income before taxes, imputation mean. This is the variable the BLS PUMD
#: sample program itself uses to form income groups. Precommitted; not the
#: winner of a search over candidates.
INCOME_VARIABLE = "FINCBTXM"

#: Role of each FMLI/MTBI file within the calendar-year estimate. The first
#: and fifth quarters are only partly in scope; see ``months_in_scope``.
FIRST_QUARTER = "FIRST_QUARTER"
MIDDLE_QUARTER = "MIDDLE_QUARTER"
FIFTH_QUARTER = "FIFTH_QUARTER"

#: The five quarters of the 2024 calendar year, in the order the BLS sample
#: program reads them. The "x" variant of the first quarter is used because
#: the BLS sample program uses it (``SET I&YR1..FMLI&YR1.1X ...``).
#:
#: Note: the Getting Started Guide states that releases from 2020 onward omit
#: the first quarter of the release year. The 2024 archive contradicts this -
#: it does contain fmli241x/mtbi241x. The archive was believed.
QUARTER_FILES: tuple[tuple[str, str, str], ...] = (
    ("fmli241x.csv", "mtbi241x.csv", FIRST_QUARTER),
    ("fmli242.csv", "mtbi242.csv", MIDDLE_QUARTER),
    ("fmli243.csv", "mtbi243.csv", MIDDLE_QUARTER),
    ("fmli244.csv", "mtbi244.csv", MIDDLE_QUARTER),
    ("fmli251.csv", "mtbi251.csv", FIFTH_QUARTER),
)

#: Population labels. "All CU" plus the five published quintiles.
ALL_CONSUMER_UNITS = "ALL_CU"
QUINTILE_LABELS: tuple[str, ...] = ("Q1", "Q2", "Q3", "Q4", "Q5")
POPULATIONS: tuple[str, ...] = (ALL_CONSUMER_UNITS,) + QUINTILE_LABELS

#: Quintile lower limits as PUBLISHED by BLS in Table 1101 for 2024, in
#: dollars of income before taxes. These are used to ASSIGN consumer units.
#:
#: This is not a reconstruction. BLS does not publish the algorithm by which
#: it derives these limits, and the algorithm is deliberately not guessed
#: here; the published output of that algorithm is used instead.
PUBLISHED_QUINTILE_LOWER_LIMITS_2024: tuple[float, float, float, float] = (
    29932.0,
    57452.0,
    94511.0,
    155925.0,
)

#: Environment variable naming the directory of extracted Interview CSVs.
PUMD_DIR_ENV = "DMI_PUMD_2024_INTERVIEW_DIR"


class PumdDataUnavailable(RuntimeError):
    """The PUMD microdata are not present.

    Raised, never swallowed. The benchmark must fail clearly rather than
    quietly produce a partial or fabricated result.
    """


class PumdSchemaError(ValueError):
    """A PUMD file does not have the structure this module requires."""


# --------------------------------------------------------------------------
# Stage 1: locate
# --------------------------------------------------------------------------


def locate_interview_csv_dir(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the directory holding the extracted 2024 Interview CSVs.

    There is no download step here by design. The archive is fetched once, by
    hand, and its SHA-256 recorded in the source registry.
    """
    candidate = explicit if explicit is not None else os.environ.get(PUMD_DIR_ENV)
    if candidate is None:
        raise PumdDataUnavailable(
            "PUMD directory not supplied. Pass an explicit path or set "
            f"{PUMD_DIR_ENV}. The 2024 Interview PUMD is not committed to "
            "this repository and is not downloaded automatically."
        )
    path = Path(candidate).expanduser()
    if not path.is_dir():
        raise PumdDataUnavailable(f"PUMD directory does not exist: {path}")
    missing = [
        name
        for fmli, mtbi, _role in QUARTER_FILES
        for name in (fmli, mtbi)
        if not (path / name).is_file()
    ]
    if missing:
        raise PumdDataUnavailable(
            f"PUMD directory {path} is missing required files: {', '.join(missing)}"
        )
    return path


def pumd_is_available(explicit: str | os.PathLike[str] | None = None) -> bool:
    """True when the microdata are present. Used to skip integration tests."""
    try:
        locate_interview_csv_dir(explicit)
    except PumdDataUnavailable:
        return False
    return True


# --------------------------------------------------------------------------
# Stage 2: the hierarchical grouping (stub) file
# --------------------------------------------------------------------------

#: Survey-source codes in stub column 5, per the PUMD documentation page.
STUB_SURVEY_INTERVIEW = "I"
STUB_SURVEY_DIARY = "D"
STUB_SURVEY_TITLE_CODES = frozenset({"G", "T"})
STUB_SURVEY_STATISTICAL = "S"

_UCC_PATTERN = re.compile(r"\d{6}")


@dataclass(frozen=True)
class StubEntry:
    """One UCC line of a CE hierarchical grouping file.

    ``factor`` is BLS's own words: "Factor by which the mean has to be
    multiplied to match the annualized data in the published tables." The
    documentation gives the options as 1 and 4. The 2024 files additionally
    carry a sign character immediately to the left of the digit; the eleven
    negative rows all sit in the ASSETS section, where the amount is
    subtracted rather than added. The magnitude is what annualizes.
    """

    ucc: str
    title: str
    level: int
    survey: str
    factor: int
    section: str

    def __post_init__(self) -> None:
        if not _UCC_PATTERN.fullmatch(self.ucc):
            raise PumdSchemaError(f"stub UCC is not six digits: {self.ucc!r}")
        if abs(self.factor) not in (1, 4):
            raise PumdSchemaError(
                f"stub annualization factor for {self.ucc} is {self.factor}; "
                "the documented options are 1 and 4"
            )


@dataclass(frozen=True)
class StubLayout:
    """Detected column offsets of a stub file.

    The PUMD documentation page gives 1-based start positions 83 / 86 / 89 for
    the survey, factor and section fields. The 2018 file matches. The 2024
    file is shifted three characters left. Offsets are therefore detected per
    file and never hardcoded.
    """

    ucc_start: int
    survey_start: int
    factor_start: int
    section_start: int


_STUB_SECTIONS = ("CUCHARS", "FOOD", "EXPEND", "INCOME", "ASSETS", "ADDENDA")

#: Stub columns 1 and 2 are the record type and the hierarchy level; the
#: title text begins immediately after them.
_STUB_TITLE_START = 6


def detect_stub_layout(lines: Sequence[str]) -> StubLayout:
    """Locate the UCC, survey, factor and section fields by inspection."""
    ucc_start = _detect_ucc_start(lines)
    section_start = _detect_section_start(lines)
    # Between the UCC field and the section field lie the survey code and the
    # factor, in that order, each one character wide and separated by blanks.
    survey_start = _detect_single_char_field(
        lines, ucc_start + 6, section_start, {"I", "D", "G", "T", "S", "H"}
    )
    factor_start = _detect_single_char_field(
        lines, survey_start + 1, section_start, {"1", "4"}
    )
    return StubLayout(ucc_start, survey_start, factor_start, section_start)


def _detect_ucc_start(lines: Sequence[str]) -> int:
    best, best_hits = None, 0
    for start in range(0, 120):
        hits = sum(
            1
            for line in lines
            if len(line) >= start + 6 and _UCC_PATTERN.fullmatch(line[start : start + 6])
        )
        if hits > best_hits:
            best, best_hits = start, hits
    if best is None or best_hits < 100:
        raise PumdSchemaError("could not locate the six-digit UCC column in the stub file")
    return best


def _detect_section_start(lines: Sequence[str]) -> int:
    for start in range(0, 140):
        hits = sum(
            1
            for line in lines
            if any(line[start:].startswith(section) for section in _STUB_SECTIONS)
        )
        if hits > 100:
            return start
    raise PumdSchemaError("could not locate the data-section column in the stub file")


def _detect_single_char_field(
    lines: Sequence[str], lo: int, hi: int, allowed: set[str]
) -> int:
    for start in range(lo, hi):
        values = {line[start] for line in lines if len(line) > start}
        non_blank = values - {" "}
        if non_blank and non_blank <= allowed:
            return start
    raise PumdSchemaError(
        f"could not locate a column in [{lo},{hi}) restricted to {sorted(allowed)}"
    )


def read_stub_file(path: str | os.PathLike[str]) -> dict[str, StubEntry]:
    """Read a CE hierarchical grouping file into UCC -> StubEntry.

    Only ``TYPE == '1'`` rows carrying a six-digit UCC become entries. Title
    continuation lines and pseudo-codes such as ``CONSUNIT`` are not UCCs.
    """
    text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        raise PumdSchemaError(f"stub file is empty: {path}")
    layout = detect_stub_layout(lines)

    entries: dict[str, StubEntry] = {}
    for line in lines:
        if not line.startswith("1"):
            continue
        if len(line) <= layout.section_start:
            continue
        ucc = line[layout.ucc_start : layout.ucc_start + 6]
        if not _UCC_PATTERN.fullmatch(ucc):
            continue
        survey = line[layout.survey_start]
        # The factor digit may be preceded by a sign character.
        factor_text = line[max(0, layout.factor_start - 1) : layout.factor_start + 1].strip()
        if not factor_text:
            continue
        entry = StubEntry(
            ucc=ucc,
            title=line[_STUB_TITLE_START : layout.ucc_start].strip(),
            level=int(line[3]) if line[3].isdigit() else 0,
            survey=survey,
            factor=int(factor_text),
            section=line[layout.section_start :].strip(),
        )
        # A UCC can appear on more than one line of the hierarchy; the first
        # occurrence carries the same survey and factor as any later one.
        entries.setdefault(ucc, entry)
    if not entries:
        raise PumdSchemaError(f"stub file yielded no UCC entries: {path}")
    return entries


# --------------------------------------------------------------------------
# Stage 3: consumer-unit records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumerUnit:
    """One FMLI record: one consumer unit for one quarter.

    Records are NOT collapsed across quarters. "Data collected by each
    interview are treated as statistically independent - each quarter's
    interview is separately weighted to be representative of the population"
    (Getting Started Guide 6.1). Collapsing by CUID would double-count the
    weighting design, not remove duplication.
    """

    newid: str
    quarter_role: str
    interview_month: int
    final_weight: float
    income_before_taxes: float
    replicate_weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if not 1 <= self.interview_month <= 12:
            raise PumdSchemaError(
                f"QINTRVMO out of range for NEWID {self.newid}: {self.interview_month}"
            )
        if len(self.replicate_weights) != REPLICATE_WEIGHT_COUNT:
            raise PumdSchemaError(
                f"expected {REPLICATE_WEIGHT_COUNT} replicate weights, "
                f"got {len(self.replicate_weights)}"
            )


_REPLICATE_COLUMNS = tuple(f"WTREP{i:02d}" for i in range(1, REPLICATE_WEIGHT_COUNT + 1))


def _float_or_zero(raw: str | None) -> float:
    """Blank replicate weights mean 'this CU is not in this half-sample'.

    The BLS program maps weights that are missing or not positive to zero
    (``IF REPS_A(i) > 0 THEN ... ELSE REPS_B(i) = 0``). Blank is not an error.
    """
    if raw is None:
        return 0.0
    text = raw.strip()
    if not text:
        return 0.0
    return float(text)


def read_fmli(path: str | os.PathLike[str], quarter_role: str) -> list[ConsumerUnit]:
    """Read one FMLI quarter file into consumer-unit records."""
    required = ("NEWID", FINAL_WEIGHT_VARIABLE, "QINTRVMO", INCOME_VARIABLE)
    units: list[ConsumerUnit] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [c for c in required + _REPLICATE_COLUMNS if c not in fieldnames]
        if missing:
            raise PumdSchemaError(
                f"{Path(path).name} is missing columns: {', '.join(missing)}"
            )
        for row in reader:
            units.append(
                ConsumerUnit(
                    newid=row["NEWID"].strip(),
                    quarter_role=quarter_role,
                    interview_month=int(row["QINTRVMO"]),
                    final_weight=_float_or_zero(row[FINAL_WEIGHT_VARIABLE]),
                    income_before_taxes=_float_or_zero(row[INCOME_VARIABLE]),
                    replicate_weights=tuple(
                        _float_or_zero(row[c]) for c in _REPLICATE_COLUMNS
                    ),
                )
            )
    if not units:
        raise PumdSchemaError(f"FMLI file yielded no records: {path}")
    duplicates = len(units) - len({u.newid for u in units})
    if duplicates:
        raise PumdSchemaError(
            f"{Path(path).name} has {duplicates} duplicate NEWID values; "
            "NEWID is the documented primary key of FMLI"
        )
    return units


def read_all_fmli(directory: str | os.PathLike[str]) -> list[ConsumerUnit]:
    """Read all five calendar-year quarters of FMLI."""
    base = Path(directory)
    units: list[ConsumerUnit] = []
    for fmli_name, _mtbi_name, role in QUARTER_FILES:
        units.extend(read_fmli(base / fmli_name, role))
    return units


# --------------------------------------------------------------------------
# Stage 4: weighting
# --------------------------------------------------------------------------


def months_in_scope(quarter_role: str, interview_month: int) -> int:
    """Months of the benchmark year that this interview reports on.

    From the BLS sample program:

        IF FIRSTQTR THEN MO_SCOPE = (QINTRVMO - 1);
        ELSE IF LASTQTR THEN MO_SCOPE = (4 - QINTRVMO);
        ELSE MO_SCOPE = 3;

    A January interview in the first quarter reports only on the previous
    year, so it contributes nothing: MO_SCOPE is 0, not 3.
    """
    if quarter_role == FIRST_QUARTER:
        return max(0, min(3, interview_month - 1))
    if quarter_role == FIFTH_QUARTER:
        return max(0, min(3, 4 - interview_month))
    if quarter_role == MIDDLE_QUARTER:
        return 3
    raise PumdSchemaError(f"unknown quarter role: {quarter_role!r}")


def population_weight(final_weight: float, months: int) -> float:
    """Weight contributing to the denominator population.

    ``FINLWT21 / QNUM * MO_SCOPE / 3``, which is ``FINLWT21 * MO_SCOPE / 12``,
    the form the BLS sample program uses. Non-positive weights contribute
    nothing, as in the BLS program.
    """
    if final_weight <= 0:
        return 0.0
    return final_weight * months / (QNUM * 3)


def population_weights(unit: ConsumerUnit) -> tuple[float, ...]:
    """Full-sample and 44 replicate population weights for one CU.

    Index 0 is the full sample; indices 1..44 are the replicates. This keeps
    the point estimate and its replicates on exactly the same code path.
    """
    months = months_in_scope(unit.quarter_role, unit.interview_month)
    return tuple(
        population_weight(w, months)
        for w in (unit.final_weight,) + unit.replicate_weights
    )


# --------------------------------------------------------------------------
# Stage 5: quintile assignment
# --------------------------------------------------------------------------


def assign_quintile(
    income: float,
    lower_limits: Sequence[float] = PUBLISHED_QUINTILE_LOWER_LIMITS_2024,
) -> str:
    """Assign a consumer unit to a published income quintile.

    ``lower_limits`` are BLS's own published boundaries, not a reconstruction.
    A consumer unit whose income equals a lower limit falls in the HIGHER
    quintile, which is what "lower limit" means.
    """
    if len(lower_limits) != len(QUINTILE_LABELS) - 1:
        raise PumdSchemaError(
            f"expected {len(QUINTILE_LABELS) - 1} lower limits, got {len(lower_limits)}"
        )
    if list(lower_limits) != sorted(lower_limits):
        raise PumdSchemaError(f"quintile lower limits are not ascending: {lower_limits}")
    for index, limit in enumerate(lower_limits):
        if income < limit:
            return QUINTILE_LABELS[index]
    return QUINTILE_LABELS[-1]


def reconstruct_quintile_limits(
    units: Iterable[ConsumerUnit],
) -> tuple[float, ...]:
    """DIAGNOSTIC ONLY: weighted-rank reconstruction of the quintile limits.

    This exists to be compared against the published limits and reported. Its
    output is never used to assign a consumer unit to a quintile, because the
    BLS algorithm is not documented and this is only one plausible guess at
    it. Guessing it and then using it is exactly what this benchmark must not
    do.
    """
    ranked = sorted(
        (u.income_before_taxes, population_weights(u)[0]) for u in units
    )
    total = sum(weight for _income, weight in ranked)
    if total <= 0:
        raise PumdSchemaError("total population weight is not positive")
    limits: list[float] = []
    cumulative = 0.0
    targets = [0.2, 0.4, 0.6, 0.8]
    index = 0
    for income, weight in ranked:
        cumulative += weight
        while index < len(targets) and cumulative >= targets[index] * total:
            limits.append(income)
            index += 1
    return tuple(limits)


# --------------------------------------------------------------------------
# Stage 6: calendar-year-eligible expenditure records
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpenditureRecord:
    """One MTBI row: one consumer unit, one UCC, one reference month."""

    newid: str
    ucc: str
    cost: float
    reference_year: int
    reference_month: int


def is_in_benchmark_year(reference_year: int, year: int = BENCHMARK_YEAR) -> bool:
    """Calendar-year eligibility.

    The BLS sample program filters on reference year alone
    (``IF REFYR = "&YEAR" OR REF_YR = "&YEAR"``). Reference month is carried
    for inspection but does not restrict.
    """
    return reference_year == year


def read_mtbi(
    path: str | os.PathLike[str],
    keep_uccs: frozenset[str] | None = None,
    year: int = BENCHMARK_YEAR,
) -> list[ExpenditureRecord]:
    """Read the calendar-year-eligible rows of one MTBI quarter file.

    ``keep_uccs`` restricts the read to a roster. It is a memory economy and
    nothing else: it is applied after the calendar-year filter and never
    changes any surviving row.
    """
    required = ("NEWID", "UCC", "COST", "REF_YR", "REF_MO")
    records: list[ExpenditureRecord] = []
    with open(path, newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        missing = [c for c in required if c not in fieldnames]
        if missing:
            raise PumdSchemaError(
                f"{Path(path).name} is missing columns: {', '.join(missing)}"
            )
        for row in reader:
            reference_year = int(row["REF_YR"])
            if not is_in_benchmark_year(reference_year, year):
                continue
            ucc = row["UCC"].strip()
            if keep_uccs is not None and ucc not in keep_uccs:
                continue
            records.append(
                ExpenditureRecord(
                    newid=row["NEWID"].strip(),
                    ucc=ucc,
                    cost=_float_or_zero(row["COST"]),
                    reference_year=reference_year,
                    reference_month=int(row["REF_MO"]),
                )
            )
    return records


def read_all_mtbi(
    directory: str | os.PathLike[str],
    keep_uccs: frozenset[str] | None = None,
    year: int = BENCHMARK_YEAR,
) -> list[ExpenditureRecord]:
    """Read all five calendar-year quarters of MTBI."""
    base = Path(directory)
    records: list[ExpenditureRecord] = []
    for _fmli_name, mtbi_name, _role in QUARTER_FILES:
        records.extend(read_mtbi(base / mtbi_name, keep_uccs, year))
    return records


# --------------------------------------------------------------------------
# Stage 7: estimation
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationEstimate:
    """Weighted consumer units in one population, with replicates."""

    population: str
    consumer_units: float
    replicate_consumer_units: tuple[float, ...]

    @property
    def consumer_units_thousands(self) -> float:
        """Published tables report consumer units in thousands."""
        return self.consumer_units / 1000.0


def population_estimates(
    units: Sequence[ConsumerUnit],
    lower_limits: Sequence[float] = PUBLISHED_QUINTILE_LOWER_LIMITS_2024,
) -> dict[str, PopulationEstimate]:
    """Weighted consumer units for All CU and each published quintile."""
    totals = {p: [0.0] * (REPLICATE_WEIGHT_COUNT + 1) for p in POPULATIONS}
    for unit in units:
        weights = population_weights(unit)
        quintile = assign_quintile(unit.income_before_taxes, lower_limits)
        for index, weight in enumerate(weights):
            totals[ALL_CONSUMER_UNITS][index] += weight
            totals[quintile][index] += weight
    return {
        population: PopulationEstimate(
            population=population,
            consumer_units=values[0],
            replicate_consumer_units=tuple(values[1:]),
        )
        for population, values in totals.items()
    }


@dataclass(frozen=True)
class UccMeanEstimate:
    """Annual mean expenditure per consumer unit for one UCC and population."""

    ucc: str
    population: str
    mean: float
    standard_error: float
    reporting_records: int

    @property
    def relative_standard_error_pct(self) -> float | None:
        if self.mean == 0:
            return None
        return 100.0 * self.standard_error / abs(self.mean)


def _standard_error(point: float, replicates: Sequence[float]) -> float:
    """Balanced Repeated Replication standard error.

    ``SE = SQRT((1/44) * SUM (MEAN_r - MEAN)**2)`` - Getting Started Guide
    6.3.2 and the BLS sample program.
    """
    if not replicates:
        return 0.0
    total = sum((r - point) ** 2 for r in replicates)
    return (total / len(replicates)) ** 0.5


def weighted_ucc_means(
    units: Sequence[ConsumerUnit],
    records: Sequence[ExpenditureRecord],
    populations: Mapping[str, PopulationEstimate],
    annualization_factors: Mapping[str, int],
    lower_limits: Sequence[float] = PUBLISHED_QUINTILE_LOWER_LIMITS_2024,
) -> dict[tuple[str, str], UccMeanEstimate]:
    """Annual mean expenditure per CU, by UCC and population.

    Numerator: ``sum(FINLWT21 * COST * factor)`` over records, using the
    UNADJUSTED final weight. Denominator: the MO_SCOPE-adjusted population.
    That asymmetry is the BLS sample program's, not an oversight - the
    program applies ``MO_SCOPE / 12`` when building ``REPWT`` for the
    population and applies the raw weights when building ``RCOST``.

    A consumer unit with no record for a UCC contributes to the denominator
    and not to the numerator, which is what makes this a mean over all
    consumer units rather than a mean over purchasers.
    """
    by_newid = {u.newid: u for u in units}
    orphans = {r.newid for r in records} - by_newid.keys()
    if orphans:
        raise PumdSchemaError(
            f"{len(orphans)} MTBI records reference a NEWID absent from FMLI; "
            f"first few: {sorted(orphans)[:5]}"
        )

    slots = REPLICATE_WEIGHT_COUNT + 1
    aggregates: dict[tuple[str, str], list[float]] = {}
    counts: dict[tuple[str, str], int] = {}

    for record in records:
        unit = by_newid[record.newid]
        factor = annualization_factors.get(record.ucc, 1)
        quintile = assign_quintile(unit.income_before_taxes, lower_limits)
        weights = (unit.final_weight,) + unit.replicate_weights
        for population in (ALL_CONSUMER_UNITS, quintile):
            key = (record.ucc, population)
            bucket = aggregates.setdefault(key, [0.0] * slots)
            counts[key] = counts.get(key, 0) + 1
            for index, weight in enumerate(weights):
                if weight > 0:
                    bucket[index] += weight * record.cost * factor

    estimates: dict[tuple[str, str], UccMeanEstimate] = {}
    for (ucc, population), bucket in aggregates.items():
        estimate = populations[population]
        denominators = (estimate.consumer_units,) + estimate.replicate_consumer_units
        means = [
            (bucket[i] / denominators[i]) if denominators[i] > 0 else 0.0
            for i in range(slots)
        ]
        estimates[(ucc, population)] = UccMeanEstimate(
            ucc=ucc,
            population=population,
            mean=means[0],
            standard_error=_standard_error(means[0], means[1:]),
            reporting_records=counts[(ucc, population)],
        )
    return estimates
