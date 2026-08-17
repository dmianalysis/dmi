"""ELI to DMI-node semantic validation.

Detailed Inflation Substrate v0.1, Milestone 2 (spec section 15).

Milestone 1 assigned every ELI reachable from the pinned concordance to a DMI
computation node using a two-character prefix rule with explicit overrides.
That rule was validated *structurally* (each prefix resolves to exactly one
node) but never *semantically* (the node is the right one for what BLS says
the ELI contains).

This module performs the semantic check by joining three pinned artifacts:

* the concordance, which fixes the set of reachable ELIs,
* ``eli_to_node_map_v0_1.json``, which supplies the DMI node and the
  resolution method,
* ``cpi_eli_descriptions_v0_1.tsv``, the normalized CPI Handbook of Methods
  Appendix 2, which supplies the BLS-authored ELI title and the BLS major
  expenditure grouping.

The check is a genuine cross-source test rather than a restatement: BLS
publishes 8 major groups and DMI defines 14 nodes, so the expected mapping is
many-to-one and a disagreement is detectable.

This module holds substrate metadata only. Nothing here is wired into
``dmi_calculator``, and Core DMI remains withdrawn and unimplemented.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional

from .taxonomy import ELI_RE, REGISTRY_DIR, load_eli_resolver, load_taxonomy

ELI_DESCRIPTIONS_PATH = REGISTRY_DIR / "cpi_eli_descriptions_v0_1.tsv"
CONCORDANCE_PATH = REGISTRY_DIR / "ucc_eli_concordance_2024_v0_1.tsv"


class SemanticsError(Exception):
    """The semantic validation inputs are malformed."""


class ReviewResult(str, Enum):
    """Outcome of comparing the DMI node against the BLS major group."""

    CONSISTENT = "CONSISTENT"
    CONSISTENT_BY_DESIGN = "CONSISTENT_BY_DESIGN"
    DIVERGENT = "DIVERGENT"
    NO_BLS_DESCRIPTION = "NO_BLS_DESCRIPTION"


#: Which BLS major expenditure groups a DMI computation node may legitimately
#: draw from. Most nodes sit inside exactly one BLS major group. The
#: multi-group entries are deliberate design decisions and are annotated in
#: :data:`NODE_DESIGN_NOTES`.
NODE_TO_BLS_MAJOR_GROUPS: Mapping = {
    "FOOD": frozenset({"Food and beverages"}),
    "ALCOHOLIC_BEVERAGES": frozenset({"Food and beverages"}),
    "SHELTER": frozenset({"Housing"}),
    "HOUSEHOLD_ENERGY": frozenset({"Housing"}),
    "WATER_SEWER_TRASH": frozenset({"Housing"}),
    "HOUSEHOLD_FURNISHINGS_OPERATIONS": frozenset({"Housing"}),
    "APPAREL": frozenset({"Apparel"}),
    "TRANSPORT_COMMODITIES_EX_MOTOR_FUEL": frozenset({"Transportation"}),
    "MOTOR_FUEL": frozenset({"Transportation"}),
    "TRANSPORT_SERVICES": frozenset({"Transportation"}),
    "MEDICAL_CARE": frozenset({"Medical care"}),
    "RECREATION": frozenset({"Recreation"}),
    "EDUCATION_COMMUNICATION": frozenset({"Education and communication"}),
    "OTHER_GOODS_SERVICES": frozenset({"Other goods and services"}),
}

#: Node-level design notes explaining why a node's BLS-group expectation is
#: what it is, where the reason is not self-evident.
NODE_DESIGN_NOTES: Mapping = {
    "ALCOHOLIC_BEVERAGES": (
        "BLS places alcohol inside the 'Food and beverages' major group, but "
        "excludes it from the CPI Food aggregate (SAF1). DMI therefore keeps a "
        "separate node whose BLS major group is still 'Food and beverages'."
    ),
    "MOTOR_FUEL": (
        "BLS has no 'motor fuel' major group; motor fuel sits inside "
        "'Transportation'. DMI splits it out because the Core-style "
        "classification treats it as ENERGY."
    ),
    "HOUSEHOLD_ENERGY": (
        "BLS places household energy inside 'Housing'. DMI splits it out for "
        "the same ENERGY classification reason as MOTOR_FUEL."
    ),
    "WATER_SEWER_TRASH": (
        "BLS places these services inside 'Housing'. DMI splits them out to "
        "keep them separable from shelter and from household energy."
    ),
}


@dataclass(frozen=True)
class EliSemanticRow:
    """One row of the section 15 semantic validation output."""

    eli: str
    bls_eli_title: str
    concordance_eli_title: str
    dmi_node: str
    resolution_method: str
    bls_major_group: Optional[str]
    expected_bls_major_groups: tuple
    review_result: ReviewResult
    reviewer_note: str
    ucc_count: int
    prefix: str
    prefix_is_heterogeneous: bool

    @property
    def is_divergent(self) -> bool:
        return self.review_result is ReviewResult.DIVERGENT


def load_eli_descriptions(path: Path = ELI_DESCRIPTIONS_PATH) -> dict:
    """Load the normalized CPI Handbook of Methods Appendix 2 table."""
    out: dict = {}
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            eli = row["eli"].strip()
            if not ELI_RE.match(eli):
                raise SemanticsError(f"{path.name}: {eli!r} is not a valid ELI")
            if eli in out:
                raise SemanticsError(f"{path.name}: duplicate ELI {eli}")
            out[eli] = {
                "eli_name": row["eli_name"].strip(),
                "bls_major_group": row["bls_major_group"].strip(),
                "definition": row["definition"].strip(),
                "source_code_as_published": row.get(
                    "source_code_as_published", ""
                ).strip(),
            }
    if not out:
        raise SemanticsError(f"{path.name}: no ELI rows")
    return out


def _concordance_elis(path: Path) -> dict:
    """Return {eli: (concordance_title, ucc_count)} for the pinned file."""
    titles: dict = {}
    counts: dict = defaultdict(int)
    with open(path, encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            eli = row["eli"].strip()
            titles.setdefault(eli, row["eli_title"].strip())
            counts[eli] += 1
    return {eli: (titles[eli], counts[eli]) for eli in titles}


def _heterogeneous_prefixes(eli_to_node: Mapping) -> dict:
    """Prefixes whose ELIs do not all resolve to a single node.

    Spec section 15: any heterogeneous prefix beyond the existing ``TA`` case
    must be surfaced.
    """
    by_prefix: dict = defaultdict(set)
    for eli, node in eli_to_node.items():
        by_prefix[eli[:2]].add(node)
    return {p: sorted(nodes) for p, nodes in by_prefix.items() if len(nodes) > 1}


#: Structural reasons an ELI can legitimately be absent from CPI Handbook of
#: Methods Appendix 2, which documents the *content of sampled* entry level
#: items. Each reason is derived from the BLS-authored ELI title in the pinned
#: concordance, not from a hand-maintained ELI list.
UNSAMPLED_RESIDUAL_NOTE = (
    "Not described in CPI Handbook of Methods Appendix 2 because Appendix 2 "
    "documents the content of sampled entry level items, and BLS titles this "
    "ELI 'Unsampled ...'. Unsampled residual ELIs carry weight but are not "
    "separately priced, so BLS publishes no content definition. The node "
    "assignment rests on the prefix rule; this is expected, not a gap."
)
RETAINED_EARNINGS_NOTE = (
    "Not described in CPI Handbook of Methods Appendix 2. BLS titles this ELI "
    "'... Retained Earnings'. Health insurance retained earnings is a CPI "
    "accounting construct used to allocate the insurance premium that is not "
    "paid out as benefits; it is not a sampled consumer item, so Appendix 2 "
    "publishes no content definition. Expected, not a gap."
)
UNEXPLAINED_GAP_NOTE = (
    "No entry in CPI Handbook of Methods Appendix 2 and no structural reason "
    "was derivable from the BLS ELI title. The node assignment could not be "
    "checked against a BLS major group and rests on the prefix rule alone. "
    "Requires reviewer adjudication."
)


def _no_description_note(eli: str, concordance_title: str) -> str:
    """Explain, from BLS's own title text, why Appendix 2 omits ``eli``."""
    title = concordance_title.strip().lower()
    if title.startswith("unsampled"):
        return UNSAMPLED_RESIDUAL_NOTE
    if "retained earnings" in title:
        return RETAINED_EARNINGS_NOTE
    return UNEXPLAINED_GAP_NOTE


def _assert_node_expectations_cover_taxonomy(nodes: Mapping) -> None:
    """Fail if the taxonomy and the BLS-group expectations drift apart."""
    missing = sorted(set(nodes) - set(NODE_TO_BLS_MAJOR_GROUPS))
    if missing:
        raise SemanticsError(
            f"NODE_TO_BLS_MAJOR_GROUPS omits taxonomy nodes: {missing}"
        )
    extra = sorted(set(NODE_TO_BLS_MAJOR_GROUPS) - set(nodes))
    if extra:
        raise SemanticsError(
            f"NODE_TO_BLS_MAJOR_GROUPS names nodes absent from the taxonomy: "
            f"{extra}"
        )


def build_semantic_validation(
    *,
    concordance_path: Path = CONCORDANCE_PATH,
    descriptions_path: Path = ELI_DESCRIPTIONS_PATH,
) -> tuple:
    """Validate every concordance-reachable ELI against BLS's own grouping.

    Returns ``(rows, summary)``. ``rows`` is a tuple of
    :class:`EliSemanticRow` sorted by ELI; ``summary`` is a plain dict
    suitable for JSON serialisation.
    """
    nodes = load_taxonomy()
    resolver = load_eli_resolver(nodes)
    _assert_node_expectations_cover_taxonomy(nodes)
    descriptions = load_eli_descriptions(descriptions_path)
    reachable = _concordance_elis(concordance_path)

    eli_to_node = {eli: resolver.resolve(eli) for eli in reachable}
    heterogeneous = _heterogeneous_prefixes(eli_to_node)

    rows = []
    for eli in sorted(reachable):
        conc_title, ucc_count = reachable[eli]
        node = eli_to_node[eli]
        method = "OVERRIDE" if eli in resolver.overrides else "PREFIX"
        expected = NODE_TO_BLS_MAJOR_GROUPS.get(node)
        if expected is None:
            raise SemanticsError(
                f"node {node!r} has no expected BLS major group; the taxonomy "
                f"and NODE_TO_BLS_MAJOR_GROUPS are out of step"
            )

        desc = descriptions.get(eli)
        if desc is None:
            result = ReviewResult.NO_BLS_DESCRIPTION
            bls_group = None
            bls_title = ""
            note = _no_description_note(eli, conc_title)
        else:
            bls_group = desc["bls_major_group"]
            bls_title = desc["eli_name"]
            if bls_group in expected:
                if len(NODE_TO_BLS_MAJOR_GROUPS[node]) == 1 and node in NODE_DESIGN_NOTES:
                    result = ReviewResult.CONSISTENT_BY_DESIGN
                    note = NODE_DESIGN_NOTES[node]
                else:
                    result = ReviewResult.CONSISTENT
                    note = ""
            else:
                result = ReviewResult.DIVERGENT
                note = (
                    f"BLS places this ELI in major group {bls_group!r}, but the "
                    f"DMI node {node} is expected to draw only from "
                    f"{sorted(expected)}. Requires reviewer adjudication."
                )
            if desc["source_code_as_published"]:
                note = (
                    f"BLS Appendix 2 prints this code as "
                    f"{desc['source_code_as_published']!r}; see "
                    f"cpi_eli_descriptions_v0_1.provenance.json code_corrections. "
                    + note
                ).strip()

        prefix = eli[:2]
        rows.append(
            EliSemanticRow(
                eli=eli,
                bls_eli_title=bls_title,
                concordance_eli_title=conc_title,
                dmi_node=node,
                resolution_method=method,
                bls_major_group=bls_group,
                expected_bls_major_groups=tuple(sorted(expected)),
                review_result=result,
                reviewer_note=note,
                ucc_count=ucc_count,
                prefix=prefix,
                prefix_is_heterogeneous=prefix in heterogeneous,
            )
        )

    by_result: dict = defaultdict(int)
    for row in rows:
        by_result[row.review_result.value] += 1

    summary = {
        "eli_count": len(rows),
        "review_result_counts": dict(sorted(by_result.items())),
        "divergent_elis": [r.eli for r in rows if r.is_divergent],
        "elis_without_bls_description": [
            r.eli for r in rows if r.review_result is ReviewResult.NO_BLS_DESCRIPTION
        ],
        "elis_without_bls_description_unexplained": [
            r.eli
            for r in rows
            if r.review_result is ReviewResult.NO_BLS_DESCRIPTION
            and r.reviewer_note == UNEXPLAINED_GAP_NOTE
        ],
        "heterogeneous_prefixes": heterogeneous,
        "heterogeneous_prefixes_beyond_ta": {
            p: nodes for p, nodes in heterogeneous.items() if p != "TA"
        },
        "override_count": sum(1 for r in rows if r.resolution_method == "OVERRIDE"),
        "bls_major_group_counts": dict(
            sorted(
                (
                    (group, sum(1 for r in rows if r.bls_major_group == group))
                    for group in {r.bls_major_group for r in rows if r.bls_major_group}
                )
            )
        ),
    }
    return tuple(rows), summary


SEMANTIC_CSV_COLUMNS = (
    "eli",
    "bls_eli_title",
    "concordance_eli_title",
    "dmi_node",
    "resolution_method",
    "bls_major_group",
    "expected_bls_major_groups",
    "review_result",
    "ucc_count",
    "prefix",
    "prefix_is_heterogeneous",
    "reviewer_note",
)


def write_semantic_validation_csv(rows, path: Path) -> Path:
    """Write ``eli_node_semantic_validation.csv`` (spec section 17)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SEMANTIC_CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.eli,
                    row.bls_eli_title,
                    row.concordance_eli_title,
                    row.dmi_node,
                    row.resolution_method,
                    "" if row.bls_major_group is None else row.bls_major_group,
                    "|".join(row.expected_bls_major_groups),
                    row.review_result.value,
                    row.ucc_count,
                    row.prefix,
                    "true" if row.prefix_is_heterogeneous else "false",
                    row.reviewer_note,
                ]
            )
    return path
