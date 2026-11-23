"""Reference periods and the staging files that hold them.

Every step of a monthly release that reads or writes ``data/staging/``
derives the file window from the release's reference period through this
module. The execution date never selects a window, so a historical rerun
reads and writes the same files whenever it runs.

The convention is unchanged from the original pipeline. A window runs
from November of its start year to October of its end year:

    2026-09, 2026-10           -> 2025_2026
    2026-11, 2026-12, 2027-01  -> 2026_2027

This module has no third-party or network dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path

STAGING_DIR = Path("data/staging")

_PERIOD = re.compile(r"(\d{4})-(0[1-9]|1[0-2])")


def parse_reference_period(reference_period: str) -> tuple[int, int]:
    """Return (year, month) for a ``YYYY-MM`` string, or raise ValueError."""
    match = _PERIOD.fullmatch(str(reference_period))
    if not match:
        raise ValueError(
            f"Invalid reference period {reference_period!r}: expected YYYY-MM "
            "with a month from 01 to 12, for example 2026-11."
        )
    return int(match.group(1)), int(match.group(2))


def staging_window_for_period(reference_period: str) -> tuple[int, int]:
    """Map a release period to the staged data file window that should contain it."""
    year, month = parse_reference_period(reference_period)
    if month >= 11:
        return year, year + 1
    return year - 1, year


def year_over_year_base(reference_period: str) -> str:
    """The same month one year earlier: the base of 12-month CPI inflation."""
    year, month = parse_reference_period(reference_period)
    return f"{year - 1:04d}-{month:02d}"


def staging_paths(reference_period: str, staging_dir: Path = STAGING_DIR) -> dict[str, Path]:
    """Staged input files for a reference period, keyed by dataset."""
    start, end = staging_window_for_period(reference_period)
    return {
        "cpi": staging_dir / f"cpi_levels_{start}_{end}.json",
        "u3": staging_dir / f"slack_u3_{start}_{end}.json",
        "u6": staging_dir / f"slack_u6_{start}_{end}.json",
    }
