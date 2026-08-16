"""Loaders for authoritative BLS Consumer Expenditure LABSTAT flat files.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt sections 3 and 4).

Design constraints carried from the prompt:

- Source paths are supplied by the caller; nothing is assumed to live inside
  the repository, and none of these files are committed.
- BLS LABSTAT columns and values are whitespace-padded to fixed widths. Every
  field is stripped on read; downstream joins are then exact string equality.
- Target series are derived from series metadata (``category_code``,
  ``subcategory_code``, ``demographics_code``, ``characteristics_code``,
  ``begin_year``/``end_year``), never from a hand-maintained list of series
  identifiers.
- No fuzzy matching and no silent exclusion. A row that cannot be interpreted
  raises with the offending value in the message.

Attribution: source data are published by the U.S. Bureau of Labor Statistics
Consumer Expenditure Surveys.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

# ---------------------------------------------------------------------------
# Milestone 1 selection constants (prompt section 4)
# ---------------------------------------------------------------------------

TARGET_YEAR = 2024
ANNUAL_PERIOD = "A01"

#: BLS demographic characteristic set for Income Quintiles.
INCOME_QUINTILE_DEMOGRAPHICS_CODE = "LB01"

#: Only expenditure series participate in the accounting basis.
EXPENDITURE_CATEGORY_CODE = "EXPEND"

#: The four CE domains audited in Milestone 1.
TARGET_SUBCATEGORY_CODES: tuple[str, ...] = (
    "FOODTOTL",
    "ALCBEVG",
    "HOUSING",
    "TRANS",
)

SUBCATEGORY_LABELS = {
    "FOODTOTL": "Food",
    "ALCBEVG": "Alcoholic beverages",
    "HOUSING": "Housing",
    "TRANS": "Transportation",
}

#: ``characteristics_code`` -> population label, within demographics ``LB01``.
POPULATIONS: dict[str, str] = {
    "01": "All Consumer Units",
    "02": "Q1",
    "03": "Q2",
    "04": "Q3",
    "05": "Q4",
    "06": "Q5",
}

#: CE aspect types used by this milestone.
ASPECT_AGGREGATE = "AG"  # aggregate expenditure
ASPECT_RSE = "R0"  # relative standard error

#: A UCC is a six-digit numeric CE item code. Non-numeric ``item_code`` values
#: in ``cx.item`` are descriptive parent aggregates (e.g. ``FOODTOTL``,
#: ``BAKERY``), which must not be summed alongside their children.
NUMERIC_UCC_RE = re.compile(r"^[0-9]{6}$")


def is_numeric_ucc(item_code: str) -> bool:
    """True when ``item_code`` is a six-digit numeric CE UCC."""
    return bool(NUMERIC_UCC_RE.match(item_code))


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesRecord:
    """One row of ``cx.series``."""

    series_id: str
    category_code: str
    subcategory_code: str
    item_code: str
    demographics_code: str
    characteristics_code: str
    process_code: str
    series_title: str
    begin_year: int
    end_year: int

    @property
    def population(self) -> str:
        return POPULATIONS[self.characteristics_code]


@dataclass(frozen=True)
class ItemRecord:
    """One row of ``cx.item``."""

    subcategory_code: str
    item_code: str
    item_text: str
    display_level: int
    selectable: bool
    sort_sequence: int


@dataclass(frozen=True)
class AspectRecord:
    """One row of ``cx.aspect``."""

    series_id: str
    year: int
    period: str
    aspect_type: str
    value: float | None


@dataclass(frozen=True)
class DataRecord:
    """One row of ``cx.data.1.AllData``."""

    series_id: str
    year: int
    period: str
    value: float | None


# ---------------------------------------------------------------------------
# Low-level TSV reading
# ---------------------------------------------------------------------------


def _read_tsv(path: Path) -> Iterator[dict[str, str]]:
    """Stream a BLS LABSTAT TSV, stripping every header and value.

    LABSTAT files are large (``cx.aspect`` is ~739 MB unfiltered), so rows are
    yielded rather than materialised.
    """
    if not path.is_file():
        raise FileNotFoundError(f"BLS source file not found: {path}")
    with path.open("r", encoding="utf-8", errors="strict", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        try:
            header = [column.strip() for column in next(reader)]
        except StopIteration:
            raise ValueError(f"BLS source file is empty: {path}")
        width = len(header)
        for line_number, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            if len(row) != width:
                raise ValueError(
                    f"{path.name} line {line_number}: expected {width} "
                    f"columns {header!r}, found {len(row)}."
                )
            yield {key: value.strip() for key, value in zip(header, row)}


def _require(row: dict[str, str], column: str, path: Path) -> str:
    try:
        return row[column]
    except KeyError:
        raise ValueError(
            f"{path.name}: expected column {column!r}; found "
            f"{sorted(row)!r}. The BLS layout may have changed."
        )


def _to_int(raw: str, column: str, path: Path) -> int:
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{path.name}: non-integer {column} value {raw!r}.")


#: LABSTAT markers for an estimate BLS did not publish. ``-`` is used in the
#: CE aspect file for estimates that do not meet publication standards; ``.``
#: is the general LABSTAT not-available marker. Both are represented as
#: ``None`` and reported downstream as missing -- never coerced to zero, which
#: would assert a certainty the source does not provide.
SUPPRESSED_VALUE_MARKERS = frozenset({"", ".", "-"})


def _to_optional_float(raw: str) -> float | None:
    """Parse a LABSTAT numeric value, mapping suppression markers to ``None``."""
    if raw in SUPPRESSED_VALUE_MARKERS:
        return None
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"Non-numeric BLS value {raw!r}; known suppression markers are "
            f"{sorted(SUPPRESSED_VALUE_MARKERS)}."
        )


# ---------------------------------------------------------------------------
# Public loaders
# ---------------------------------------------------------------------------


def load_series(path: Path) -> list[SeriesRecord]:
    """Load every row of ``cx.series`` (or a pre-filtered extract)."""
    records: list[SeriesRecord] = []
    for row in _read_tsv(path):
        records.append(
            SeriesRecord(
                series_id=_require(row, "series_id", path),
                category_code=_require(row, "category_code", path),
                subcategory_code=_require(row, "subcategory_code", path),
                item_code=_require(row, "item_code", path),
                demographics_code=_require(row, "demographics_code", path),
                characteristics_code=_require(row, "characteristics_code", path),
                process_code=_require(row, "process_code", path),
                series_title=_require(row, "series_title", path),
                begin_year=_to_int(_require(row, "begin_year", path), "begin_year", path),
                end_year=_to_int(_require(row, "end_year", path), "end_year", path),
            )
        )
    if not records:
        raise ValueError(f"{path.name}: no series rows parsed.")
    return records


def load_items(path: Path) -> dict[tuple[str, str], ItemRecord]:
    """Load ``cx.item``, keyed by ``(subcategory_code, item_code)``.

    ``cx.item`` reuses ``item_code`` across subcategories, so the composite key
    is required for an exact join.
    """
    items: dict[tuple[str, str], ItemRecord] = {}
    for row in _read_tsv(path):
        subcategory = _require(row, "subcategory_code", path)
        item_code = _require(row, "item_code", path)
        selectable = _require(row, "selectable", path).upper()
        if selectable not in ("T", "F"):
            raise ValueError(
                f"{path.name}: unexpected selectable flag {selectable!r} for "
                f"item {subcategory}/{item_code}; expected 'T' or 'F'."
            )
        items[(subcategory, item_code)] = ItemRecord(
            subcategory_code=subcategory,
            item_code=item_code,
            item_text=_require(row, "item_text", path),
            display_level=_to_int(
                _require(row, "display_level", path), "display_level", path
            ),
            selectable=selectable == "T",
            sort_sequence=_to_int(
                _require(row, "sort_sequence", path), "sort_sequence", path
            ),
        )
    if not items:
        raise ValueError(f"{path.name}: no item rows parsed.")
    return items


def load_aspects(
    path: Path,
    *,
    year: int = TARGET_YEAR,
    period: str = ANNUAL_PERIOD,
    aspect_types: Iterable[str] = (ASPECT_AGGREGATE, ASPECT_RSE),
    series_ids: set[str] | None = None,
) -> dict[tuple[str, str], AspectRecord]:
    """Load ``cx.aspect`` filtered to one year/period, keyed by
    ``(series_id, aspect_type)``.

    Filtering happens during the streaming read so that an unfiltered
    ``cx.aspect`` can be supplied without materialising it.
    """
    wanted = set(aspect_types)
    year_text = str(year)
    aspects: dict[tuple[str, str], AspectRecord] = {}
    for row in _read_tsv(path):
        if _require(row, "year", path) != year_text:
            continue
        if _require(row, "period", path) != period:
            continue
        aspect_type = _require(row, "aspect_type", path)
        if aspect_type not in wanted:
            continue
        series_id = _require(row, "series_id", path)
        if series_ids is not None and series_id not in series_ids:
            continue
        key = (series_id, aspect_type)
        if key in aspects:
            raise ValueError(
                f"{path.name}: duplicate aspect row for {series_id} / "
                f"{aspect_type} in {year} {period}."
            )
        aspects[key] = AspectRecord(
            series_id=series_id,
            year=year,
            period=period,
            aspect_type=aspect_type,
            value=_to_optional_float(_require(row, "value", path)),
        )
    if not aspects:
        raise ValueError(
            f"{path.name}: no aspect rows matched year={year} period={period} "
            f"aspect_types={sorted(wanted)}."
        )
    return aspects


def load_data(
    path: Path,
    *,
    year: int = TARGET_YEAR,
    period: str = ANNUAL_PERIOD,
    series_ids: set[str] | None = None,
) -> dict[str, DataRecord]:
    """Load ``cx.data.1.AllData`` filtered to one year/period, keyed by
    ``series_id``.

    These are the CE mean-expenditure estimates. Milestone 1 reconciles on
    aggregate expenditure (``AG``); the mean values are carried into the basis
    export for reference and for later milestones.
    """
    year_text = str(year)
    values: dict[str, DataRecord] = {}
    for row in _read_tsv(path):
        if _require(row, "year", path) != year_text:
            continue
        if _require(row, "period", path) != period:
            continue
        series_id = _require(row, "series_id", path)
        if series_ids is not None and series_id not in series_ids:
            continue
        if series_id in values:
            raise ValueError(
                f"{path.name}: duplicate data row for {series_id} in "
                f"{year} {period}."
            )
        values[series_id] = DataRecord(
            series_id=series_id,
            year=year,
            period=period,
            value=_to_optional_float(_require(row, "value", path)),
        )
    return values


# ---------------------------------------------------------------------------
# Metadata-driven target selection (prompt section 4)
# ---------------------------------------------------------------------------


def select_target_series(
    series: Iterable[SeriesRecord],
    *,
    year: int = TARGET_YEAR,
    demographics_code: str = INCOME_QUINTILE_DEMOGRAPHICS_CODE,
    subcategory_codes: Iterable[str] = TARGET_SUBCATEGORY_CODES,
    characteristics_codes: Iterable[str] | None = None,
) -> list[SeriesRecord]:
    """Derive the 2024 Income-Quintile target series purely from metadata.

    A series is in scope when it is an expenditure series, in one of the four
    target CE domains, coded to the Income-Quintile demographic set and one of
    the six populations, and active in the target year
    (``begin_year <= year <= end_year``).
    """
    subcategories = set(subcategory_codes)
    characteristics = set(
        characteristics_codes if characteristics_codes is not None else POPULATIONS
    )
    selected = [
        record
        for record in series
        if record.category_code == EXPENDITURE_CATEGORY_CODE
        and record.subcategory_code in subcategories
        and record.demographics_code == demographics_code
        and record.characteristics_code in characteristics
        and record.begin_year <= year <= record.end_year
    ]
    if not selected:
        raise ValueError(
            f"No 2024 target series selected for demographics={demographics_code} "
            f"subcategories={sorted(subcategories)}. Verify the source extract."
        )
    return selected
