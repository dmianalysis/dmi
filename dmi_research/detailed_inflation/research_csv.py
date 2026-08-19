"""The CSV writer for committed research artifacts.

Detailed Inflation Substrate v0.1, research only. Writes nothing itself; it
gives the research scripts one way to serialise a table so that the bytes they
hash are the bytes the repository keeps.

Why this is a separate module
-----------------------------
:func:`pumd_benchmark.write_csv` did the same job and got it wrong: it built a
``csv.DictWriter`` without naming a line terminator, so Python emitted CRLF,
while ``.gitattributes`` declares ``* text=auto`` and git stored LF. The 2024
confirmation freeze hashed the file between those two moments and pinned a
digest that no object in the repository has. The universe was never wrong --
the rows, their order and their semantic hash all reproduce exactly -- but the
raw digest describes a file that existed for the length of one function call.
``registry/research/pumd_lb01_confirmation_serialization_correction_v0_1.json``
records that in full.

The obvious repair was to add the argument where the defect lives. That is not
available: ``pumd_lb01_confirmation_spec_v0_1.json`` pins the sha256 of
``pumd_benchmark.py`` as the frozen estimator, and the confirmation refuses to
run against a module whose digest has moved. Editing it would have broken the
control that makes the frozen result meaningful, to fix a serialisation bug --
trading a real guarantee for a cosmetic one. So the corrected writer lives
here, the frozen module keeps its digest, and the scripts that produce
committed artifacts call this one.

The invariant
-------------
For any table written through :func:`write_csv`::

    writer output bytes
      == bytes git stores under the current .gitattributes
      == bytes materialised after checkout

so a raw sha256 taken at write time is still true after a round trip through
the repository. ``tests/test_research_csv_serialization.py`` asserts this by
committing a generated file into a throwaway repository and reading it back,
and asserts that the same experiment fails against a CRLF writer.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

#: Named rather than defaulted. :mod:`csv` writes ``\r\n`` unless told
#: otherwise, which is the whole of the defect this module exists to prevent.
LINE_TERMINATOR = "\n"

__all__ = ["LINE_TERMINATOR", "write_csv"]


def write_csv(
    path: str | os.PathLike[str],
    columns: Sequence[str],
    rows: Iterable[Mapping[str, object]],
) -> None:
    """Write ``rows`` to ``path`` as UTF-8 CSV with LF line endings.

    ``newline=""`` is kept because :mod:`csv` requires it: the module emits
    its own terminator and the io layer must not translate what it emits. The
    terminator is then stated explicitly, so the two settings together mean
    exactly one thing rather than leaving the result to a library default.
    """
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(columns), lineterminator=LINE_TERMINATOR
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
