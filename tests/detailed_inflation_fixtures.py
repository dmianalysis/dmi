"""Shared fixtures for the Detailed Inflation Substrate Milestone 1 tests.

Synthetic BLS-shaped extracts are written to a temporary directory so the unit
tests exercise the real loaders without depending on the multi-hundred-megabyte
external LABSTAT files. Fields are deliberately whitespace-padded, mixed in
column order and salted with suppression markers, because that is what the
real files look like.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: External BLS inputs. Present on a research workstation, absent in CI.
EXTERNAL_DATA_DIR = REPO_ROOT.parent / "dmi-data"
EXTERNAL_SOURCES = {
    "series": EXTERNAL_DATA_DIR / "cx.series_2024_dmi_target.tsv",
    "data": EXTERNAL_DATA_DIR / "cx.data.1.AllData",
    "items": EXTERNAL_DATA_DIR / "cx.item",
    "aspects": EXTERNAL_DATA_DIR / "cx.aspect_2024_dmi_target.tsv",
}


def external_sources_available() -> bool:
    return all(path.is_file() for path in EXTERNAL_SOURCES.values())


SERIES_HEADER = (
    "series_id\tseasonal\tcategory_code\tsubcategory_code\titem_code\t"
    "demographics_code\tcharacteristics_code\tprocess_code\tseries_title\t"
    "footnote_codes\tbegin_year\tbegin_period\tend_year\tend_period"
)

ITEM_HEADER = (
    "subcategory_code\titem_code\titem_text\tdisplay_level\tselectable\t"
    "sort_sequence"
)

ASPECT_HEADER = "series_id\tyear\tperiod\taspect_type\tvalue\tfootnote_codes"

DATA_HEADER = "series_id\tyear\tperiod\tvalue\tfootnote_codes"


def _series_row(
    item_code: str,
    subcategory: str,
    characteristics: str,
    title: str,
    *,
    begin_year: int = 1984,
    end_year: int = 2024,
    category: str = "EXPEND",
    demographics: str = "LB01",
) -> str:
    series_id = f"CXU{item_code}{demographics}{characteristics}M"
    # Whitespace padding mirrors the real LABSTAT layout.
    return (
        f"{series_id}  \tU\t{category} \t{subcategory}  \t{item_code} \t"
        f"{demographics}\t{characteristics}\tM\t{title}\t\t"
        f"{begin_year}\tA01\t{end_year}\tA01"
    )


def write_minimal_sources(tmp_dir: Path) -> dict[str, Path]:
    """Write a small, self-consistent synthetic CE extract.

    Layout, for the single population ``01`` (All Consumer Units):

    * ``FOODTOTL`` domain root (descriptive parent, aggregate 300)
    * ``FOODHOME`` intermediate descriptive parent (aggregate 300) -- present
      precisely so the tests prove descriptive aggregates are excluded
    * numeric leaves ``010119`` (100), ``020219`` (200)
    * ``TRANS`` domain root (aggregate 50) and leaf ``470111`` (50)
    * one out-of-scope series (``APPAREL`` domain) that must not be selected
    * one series that ended before 2024 and must not be selected
    """
    tmp_dir = Path(tmp_dir)

    series_lines = [
        SERIES_HEADER,
        _series_row("FOODTOTL", "FOODTOTL", "01", "Food"),
        _series_row("FOODHOME", "FOODTOTL", "01", "Food at home"),
        _series_row("010119", "FOODTOTL", "01", "Flour"),
        _series_row("020219", "FOODTOTL", "01", "Bread"),
        _series_row("TRANS", "TRANS", "01", "Transportation"),
        _series_row("470111", "TRANS", "01", "Gasoline"),
        _series_row("010119", "FOODTOTL", "02", "Flour, Q1"),
        _series_row("020219", "FOODTOTL", "02", "Bread, Q1"),
        _series_row("FOODTOTL", "FOODTOTL", "02", "Food, Q1"),
        # Out of scope: different CE domain.
        _series_row("380110", "APPAREL", "01", "Men's coats"),
        # Out of scope: not active in 2024.
        _series_row("019999", "FOODTOTL", "01", "Retired item", end_year=2019),
        # Out of scope: different demographic set.
        _series_row("010119", "FOODTOTL", "01", "Flour, by age", demographics="LB04"),
    ]

    item_lines = [
        ITEM_HEADER,
        "FOODTOTL\tFOODTOTL\tFood\t0\tT\t10",
        "FOODTOTL\tFOODHOME\tFood at home\t1\tT\t20",
        "FOODTOTL\t010119 \tFlour and prepared flour mixes\t3\tT\t30",
        "FOODTOTL\t020219 \tBread\t3\tT\t40",
        "FOODTOTL\t019999\tRetired item\t3\tT\t50",
        "TRANS\tTRANS\tTransportation\t0\tT\t60",
        "TRANS\t470111\tGasoline\t2\tT\t70",
        "APPAREL\t380110\tMen's coats\t2\tT\t80",
    ]

    aspect_lines = [ASPECT_HEADER]
    aggregates = {
        "CXUFOODTOTLLB0101M": ("300", "1.5"),
        "CXUFOODHOMELB0101M": ("300", "1.5"),
        "CXU010119LB0101M": ("100", "24.99"),
        "CXU020219LB0101M": ("200", "25.00"),
        "CXUTRANSLB0101M": ("50", "3.0"),
        "CXU470111LB0101M": ("50", "3.0"),
        # Q1: one leaf suppressed in both aggregate and RSE.
        "CXUFOODTOTLLB0102M": ("40", "8.0"),
        "CXU010119LB0102M": ("40", "30.0"),
        "CXU020219LB0102M": ("-", "-"),
    }
    for series_id, (aggregate, rse) in aggregates.items():
        aspect_lines.append(f"{series_id}\t2024\tA01\tAG\t{aggregate}\t")
        aspect_lines.append(f"{series_id}\t2024\tA01\tR0\t{rse}\t")
        # A different year and a different period, both of which must be
        # filtered out by the loader.
        aspect_lines.append(f"{series_id}\t2023\tA01\tAG\t999999\t")
        aspect_lines.append(f"{series_id}\t2024\tM01\tAG\t888888\t")

    data_lines = [DATA_HEADER]
    for series_id in aggregates:
        data_lines.append(f"{series_id}\t2024\tA01\t   12.5\t")
        data_lines.append(f"{series_id}\t2023\tA01\t   99.9\t")

    paths = {
        "series": tmp_dir / "cx.series",
        "items": tmp_dir / "cx.item",
        "aspects": tmp_dir / "cx.aspect",
        "data": tmp_dir / "cx.data.1.AllData",
    }
    paths["series"].write_text("\n".join(series_lines) + "\n", encoding="utf-8")
    paths["items"].write_text("\n".join(item_lines) + "\n", encoding="utf-8")
    paths["aspects"].write_text("\n".join(aspect_lines) + "\n", encoding="utf-8")
    paths["data"].write_text("\n".join(data_lines) + "\n", encoding="utf-8")
    return paths


CONCORDANCE_HEADER = "ucc\teli\tucc_title\teli_title\tce_source\tmulti_eli_footnote"


def write_concordance(tmp_dir: Path, rows: list[tuple[str, str, str, str]]) -> Path:
    """Write a synthetic normalized concordance TSV.

    ``rows`` are ``(ucc, eli, ucc_title, eli_title)`` tuples.
    """
    path = Path(tmp_dir) / "concordance.tsv"
    lines = [CONCORDANCE_HEADER]
    for ucc, eli, ucc_title, eli_title in rows:
        lines.append(f"{ucc}\t{eli}\t{ucc_title}\t{eli_title}\tD\tfalse")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
