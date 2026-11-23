"""Reviewed exceptions: reference periods with no published DMI observation.

``registry/unavailable_periods.json`` lists each calendar month for which
no DMI is published, why, the evidence for it, and the review that
approved the exception. ``scripts.finalize_release`` refuses to publish a
release when any month between it and the most recent earlier published
release is not listed here, and release summaries name each listed month
with its reason.

An entry is a human decision, made in a reviewed pull request. Nothing in
the pipeline writes this file: a failed monthly run is not a reason to
add one. This module only reads and checks it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

REGISTRY_RELATIVE_PATH = Path("registry") / "unavailable_periods.json"

_PERIOD = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_REVIEW = re.compile(r"[\w.-]+/[\w.-]+#\d+")
_URL = re.compile(r"https://\S+")
ENTRY_FIELDS = {"release_id", "reason", "detail", "sources", "approved_in"}
SOURCE_FIELDS = {"title", "url"}
MIN_REASON_CHARS = 20
MIN_DETAIL_CHARS = 40
#: Text that marks a placeholder rather than a reviewed explanation.
PLACEHOLDERS = ("todo", "tbd", "fixme", "unknown", "placeholder", "n/a",
                "job failed", "run failed", "workflow failed", "to be determined")


def month_index(release_id: str) -> int:
    year, month = release_id.split("-")
    return int(year) * 12 + int(month) - 1


def release_id_for(index: int) -> str:
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def intervening_months(prior_id: str, current_id: str) -> list[str]:
    """Calendar months strictly between two release ids."""
    return [release_id_for(i)
            for i in range(month_index(prior_id) + 1, month_index(current_id))]


def _text_problems(where: str, field: str, value, minimum: int) -> list[str]:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        return [f"{where}: '{field}' must be a substantive explanation of at "
                f"least {minimum} characters"]
    lowered = value.lower()
    hits = [p for p in PLACEHOLDERS if re.search(rf"(?<!\w){re.escape(p)}(?!\w)", lowered)]
    if hits:
        return [f"{where}: '{field}' reads as a placeholder ({', '.join(hits)}), "
                "not a reviewed explanation"]
    return []


def check_registry(doc) -> tuple[dict[str, dict], list[str]]:
    """Validate the registry document. Returns ``(entries by id, problems)``."""
    problems: list[str] = []
    entries: dict[str, dict] = {}
    if not isinstance(doc, dict) or not isinstance(doc.get("periods"), list):
        return {}, ["registry must be an object with a 'periods' list"]
    unknown_top = set(doc) - {"description", "periods"}
    if unknown_top:
        problems.append(f"registry has unknown top-level fields {sorted(unknown_top)}")

    for n, entry in enumerate(doc["periods"]):
        where = f"periods[{n}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: must be an object")
            continue
        rid = entry.get("release_id")
        if isinstance(rid, str) and _PERIOD.fullmatch(rid):
            where = f"periods[{n}] ({rid})"
        else:
            problems.append(f"{where}: 'release_id' must be YYYY-MM, got {rid!r}")
            rid = None
        missing = ENTRY_FIELDS - set(entry)
        extra = set(entry) - ENTRY_FIELDS
        if missing:
            problems.append(f"{where}: missing {sorted(missing)}")
        if extra:
            problems.append(f"{where}: unknown fields {sorted(extra)}")
        problems += _text_problems(where, "reason", entry.get("reason"), MIN_REASON_CHARS)
        problems += _text_problems(where, "detail", entry.get("detail"), MIN_DETAIL_CHARS)

        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            problems.append(f"{where}: 'sources' must list at least one source")
        else:
            for k, source in enumerate(sources):
                if not isinstance(source, dict) or set(source) != SOURCE_FIELDS:
                    problems.append(f"{where}: sources[{k}] must have exactly "
                                    f"{sorted(SOURCE_FIELDS)}")
                    continue
                if not (isinstance(source["title"], str) and source["title"].strip()):
                    problems.append(f"{where}: sources[{k}] needs a title")
                if not (isinstance(source["url"], str) and _URL.fullmatch(source["url"])):
                    problems.append(f"{where}: sources[{k}] url must be an https URL")

        approved = entry.get("approved_in")
        if not (isinstance(approved, str) and _REVIEW.fullmatch(approved)):
            problems.append(f"{where}: 'approved_in' must name the reviewing pull "
                            f"request as owner/repo#N, got {approved!r}")

        if rid is not None:
            if rid in entries:
                problems.append(f"{where}: duplicate entry for {rid}")
            else:
                entries[rid] = entry
    return entries, problems


def load_registry(path: Path) -> tuple[dict[str, dict], list[str]]:
    """Read and validate the registry. A missing file is an empty registry."""
    if not path.exists():
        return {}, []
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return {}, [f"{path.name} is not readable JSON: {exc}"]
    return check_registry(doc)


def reasons(path: Path) -> dict[str, str]:
    """Reason text by release_id, for release summaries."""
    entries, _ = load_registry(path)
    return {rid: e["reason"] for rid, e in entries.items() if isinstance(e.get("reason"), str)}


def gap_problems(
    period: str,
    published_ids: set[str],
    registry_path: Path,
) -> list[str]:
    """The finalization gate. Empty means the gap, if any, is documented.

    Checks, for the release being finalized:

    - the registry is well formed, with no duplicate entries;
    - no entry names a published month or the month being finalized;
    - every month between the most recent earlier published release and
      ``period`` has an entry.
    """
    entries, problems = load_registry(registry_path)
    problems = [f"unavailable-periods: {p}" for p in problems]
    label = REGISTRY_RELATIVE_PATH.as_posix()

    for rid in sorted(set(entries) & published_ids):
        problems.append(
            f"unavailable-periods: {rid} is listed in {label} as having no "
            "published DMI, but it is published. Remove the entry or the release.")
    if period in entries:
        problems.append(
            f"unavailable-periods: {period} is listed in {label} as having no "
            "published DMI, so it cannot be finalized. Remove the entry first, "
            "in a reviewed pull request, if the data are now available.")

    earlier = sorted(r for r in published_ids if r < period)
    if earlier:
        prior = earlier[-1]
        undocumented = [m for m in intervening_months(prior, period) if m not in entries]
        if undocumented:
            problems.append(
                f"unavailable-periods: {period} follows {prior}, the most recent "
                f"earlier published release, but these months have no published "
                f"release and no reviewed entry in {label}: {', '.join(undocumented)}. "
                "Publish the missing release(s) first, or, if the official data do "
                "not exist, add an entry for each with a reason, sources and the "
                "approving pull request (owner/repo#N) in a reviewed change. Do not "
                "add an entry only because a monthly run failed.")
    return problems
