#!/usr/bin/env python3
"""Build the C3 reconciliation and coverage artifacts.

Detailed Inflation Substrate v0.1, task C3. Research only.

    python3 scripts/build_c3_2024.py --bls-dir ~/dev/dmi-data
    python3 scripts/build_c3_2024.py --bls-dir ~/dev/dmi-data --check

``--check`` rebuilds every artifact in memory and compares it byte for byte
against what is on disk. Rendering and writing go through the same code, so a
check cannot pass while a real build would differ. Nothing here carries a
timestamp, hostname, user or absolute path: rebuilding from the same frozen
C1+C2 state and the same pinned BLS files produces the same bytes, so a diff
means an input moved.

The BLS LABSTAT flat files are not committed to this repository and their
location is supplied by the caller. Their sha256 digests are recorded in the
summary so that the artifacts name the bytes they were built from.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import c3_coverage as cov  # noqa: E402
from dmi_research.detailed_inflation import c3_reconciliation as rec  # noqa: E402
from dmi_research.detailed_inflation import research_csv  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/c3_2024"
ACCOUNTING_SPEC_PATH = REPO_ROOT / "registry/research/c3_accounting_spec_v0_1.json"
COVERAGE_SPEC_PATH = REPO_ROOT / "registry/research/c3_coverage_spec_v0_1.json"

CHECKPOINT_TAG = "dmi-detailed-inflation-v0.1-canonical-ledger-2024"
CHECKPOINT_SHA = "47ff8513205635851fc5979f7a771003c9295bc9"

MANIFEST_PATH = REPO_ROOT / "registry/research/canonical_substrate_manifest_2024_v0_1.json"

AUDITED_DOMAINS = ("ALCBEVG", "FOODTOTL", "HOUSING", "TRANS")

POPS = rec.POPULATIONS


def _d(value: Decimal | None, places: int = 6) -> str:
    """Fixed-point text, or blank. Blank is never a stand-in for zero."""
    if value is None:
        return ""
    return f"{value:.{places}f}"


def _b(value: bool) -> str:
    return "true" if value else "false"


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _render_csv(columns, rows) -> str:
    """Serialise to the exact bytes ``research_csv.write_csv`` would write."""
    import csv as _csv

    buffer = io.StringIO(newline="")
    writer = _csv.DictWriter(
        buffer,
        fieldnames=list(columns),
        lineterminator=research_csv.LINE_TERMINATOR,
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# C3-A renderers
# ---------------------------------------------------------------------------

POPULATION_COLUMNS = (
    "population",
    "e_source_published_basis",
    *(f"source_{b}" for b in rec.SOURCE_BUCKETS),
    "source_residual",
    "effective_retained",
    "effective_replacement",
    "effective_transformed",
    "e_track_a_effective",
    "effective_residual",
    "excluded_effective_all_rows",
    "pending_source_amount",
    "pending_replacement_amount",
    "pending_total_admitted_amount",
    "open_all_rows",
    "withheld_replacement_amount",
    "withheld_total_amount",
    "delta_scope",
    "published_basis_cells_with_amount",
    "published_basis_cells_without_amount",
)


def render_population(accounting) -> str:
    rows = []
    for a in accounting:
        row = {
            "population": a.population,
            "e_source_published_basis": _d(a.source_total),
            "source_residual": _d(a.source_residual),
            "effective_retained": _d(a.effective_retained),
            "effective_replacement": _d(a.effective_replacement),
            "effective_transformed": _d(a.effective_transformed),
            "e_track_a_effective": _d(a.effective_total),
            "effective_residual": _d(a.effective_residual),
            "excluded_effective_all_rows": _d(a.excluded_effective),
            "pending_source_amount": _d(a.pending_source_amount),
            "pending_replacement_amount": _d(a.pending_replacement_amount),
            "pending_total_admitted_amount": _d(a.pending),
            "open_all_rows": _d(a.open_),
            "withheld_replacement_amount": _d(a.withheld_replacement_amount),
            "withheld_total_amount": _d(a.withheld),
            "delta_scope": _d(a.delta_scope),
            "published_basis_cells_with_amount": str(a.cells_with_amount),
            "published_basis_cells_without_amount": str(a.cells_without_amount),
        }
        for bucket in rec.SOURCE_BUCKETS:
            row[f"source_{bucket}"] = _d(a.source_buckets[bucket])
        rows.append(row)
    return _render_csv(POPULATION_COLUMNS, rows)


NODE_COLUMNS = (
    "dmi_node",
    "population",
    "ucc_count",
    "source_expenditure",
    "effective_retained",
    "effective_transformed",
    "effective_replacement",
    "excluded_effective",
    "pending",
    "open",
    "withheld",
    "effective_track_a_basis",
    "cells_without_amount",
)


def render_node(node_rows) -> str:
    rows = [
        {
            "dmi_node": n.node,
            "population": n.population,
            "ucc_count": str(n.ucc_count),
            "source_expenditure": _d(n.source_expenditure),
            "effective_retained": _d(n.effective_retained),
            "effective_transformed": _d(n.effective_transformed),
            "effective_replacement": _d(n.effective_replacement),
            "excluded_effective": _d(n.excluded_effective),
            "pending": _d(n.pending),
            "open": _d(n.open_),
            "withheld": _d(n.withheld),
            "effective_track_a_basis": _d(n.effective_track_a_basis),
            "cells_without_amount": str(n.cells_without_amount),
        }
        for n in node_rows
    ]
    return _render_csv(NODE_COLUMNS, rows)


REPLACEMENT_COLUMNS = (
    "replacement_group_id",
    "population",
    "source_side_amount",
    "replacement_side_amount",
    "source_side_state",
    "replacement_side_state",
    "removed_for_replacement_effective",
    "replacement_effective",
    "delta_replacement",
    "delta_is_applicable",
    "note",
)


def render_replacement(groups) -> str:
    rows = [
        {
            "replacement_group_id": g.replacement_group_id,
            "population": g.population,
            "source_side_amount": _d(g.source_side_amount),
            "replacement_side_amount": _d(g.replacement_side_amount),
            "source_side_state": g.source_side_state,
            "replacement_side_state": g.replacement_side_state,
            "removed_for_replacement_effective": _d(
                g.removed_for_replacement_effective
            ),
            "replacement_effective": _d(g.replacement_effective),
            "delta_replacement": _d(g.delta_replacement),
            "delta_is_applicable": _b(g.delta_is_applicable),
            "note": g.note,
        }
        for g in groups
    ]
    return _render_csv(REPLACEMENT_COLUMNS, rows)


SHELTER_COLUMNS = (
    "population",
    "e_source",
    "e_cpi",
    "delta_scope",
    "rental_equivalence_introduced",
    "owner_outlays_removed_frozen_membership",
    "delta_shelter_frozen_membership",
    "owner_outlays_removed_current_state",
    "delta_shelter_current_state",
    "definition_difference",
    "frozen_membership_interpretation",
    "current_state_interpretation",
)

#: What each of the two delta_shelter readings is *for*. Carried in the
#: artifact rather than left to the write-up: the two numbers differ by
#: 199,079 and a consumer holding only the CSV must not have to guess which
#: one answers which question.
FROZEN_MEMBERSHIP_INTERPRETATION = (
    "HISTORICAL_CHECKPOINT_COMPARABILITY. Owner-outlay membership pinned at "
    "the shelter checkpoint. Reproduces the frozen published value and is not "
    "a statement about the current rule state."
)
CURRENT_STATE_INTERPRETATION = (
    "CURRENT_GOVERNING_RULE_STATE. Every owner outlay that has left the basis "
    "under a rule accepted as of this commit, including owner maintenance "
    "services. This is the reading that describes the substrate today."
)


def render_shelter(deltas) -> str:
    rows = [
        {
            "population": d.population,
            "e_source": _d(d.e_source),
            "e_cpi": _d(d.e_cpi),
            "delta_scope": _d(d.delta_scope),
            "rental_equivalence_introduced": _d(d.rental_equivalence_introduced),
            "owner_outlays_removed_frozen_membership": _d(
                d.owner_outlays_removed_frozen_membership
            ),
            "delta_shelter_frozen_membership": _d(d.delta_shelter_frozen_membership),
            "owner_outlays_removed_current_state": _d(
                d.owner_outlays_removed_current_state
            ),
            "delta_shelter_current_state": _d(d.delta_shelter_current_state),
            "definition_difference": _d(d.definition_difference),
            "frozen_membership_interpretation": FROZEN_MEMBERSHIP_INTERPRETATION,
            "current_state_interpretation": CURRENT_STATE_INTERPRETATION,
        }
        for d in deltas
    ]
    return _render_csv(SHELTER_COLUMNS, rows)


# ---------------------------------------------------------------------------
# C3-B renderers
# ---------------------------------------------------------------------------

ADDITIVITY_COLUMNS = (
    "ce_domain",
    "population",
    "leaf_ucc_count",
    "leaves_with_amount",
    "leaf_sum",
    "published_parent",
    "difference",
    "rounding_bound",
    "additive",
)


def render_additivity(domain_results, grand_results) -> str:
    rows = [
        {
            "ce_domain": r.domain,
            "population": r.population,
            "leaf_ucc_count": str(r.leaf_count),
            "leaves_with_amount": str(r.leaves_with_amount),
            "leaf_sum": _d(r.leaf_sum, 0),
            "published_parent": _d(r.published_parent, 0),
            "difference": _d(r.difference, 0),
            "rounding_bound": _d(r.bound, 1),
            "additive": _b(r.additive),
        }
        for r in domain_results
    ]
    rows += [
        {
            "ce_domain": "__ALL_DOMAIN_ROOTS__",
            "population": g.population,
            "leaf_ucc_count": "",
            "leaves_with_amount": "",
            "leaf_sum": _d(g.domain_root_sum, 0),
            "published_parent": _d(g.published_grand_total, 0),
            "difference": _d(g.difference, 0),
            "rounding_bound": _d(g.bound, 1),
            "additive": _b(g.additive),
        }
        for g in grand_results
    ]
    return _render_csv(ADDITIVITY_COLUMNS, rows)


OMITTED_COLUMNS = (
    "ucc",
    "label",
    "published_ce_domain",
    "candidate_dmi_node",
    "node_resolution_status",
    "ce_source",
    *(f"{p.lower()}_expenditure" for p in POPS),
    "currently_in_canonical_ledger",
    "omission_classification",
    "concordance_status",
    "requires_scope_adjudication",
    "requires_pumd",
    "requires_new_domain_audit",
    "note",
)


def render_omitted(rows) -> str:
    out = []
    for r in rows:
        record = {
            "ucc": r.ucc,
            "label": r.label,
            "published_ce_domain": r.published_ce_domain,
            "candidate_dmi_node": r.candidate_dmi_node,
            "node_resolution_status": r.node_resolution_status,
            "ce_source": r.ce_source,
            "currently_in_canonical_ledger": _b(r.currently_in_canonical_ledger),
            "omission_classification": r.omission_classification,
            "concordance_status": r.concordance_status,
            "requires_scope_adjudication": _b(r.requires_scope_adjudication),
            "requires_pumd": _b(r.requires_pumd),
            "requires_new_domain_audit": _b(r.requires_new_domain_audit),
            "note": r.note,
        }
        for p in POPS:
            record[f"{p.lower()}_expenditure"] = _d(r.amounts[p], 0)
        out.append(record)
    return _render_csv(OMITTED_COLUMNS, out)


COVERAGE_POP_COLUMNS = (
    "population",
    "universe_expenditure",
    "consumption_universe_expenditure",
    "canonical_source_expenditure",
    "covered_share_of_universe",
    "covered_share_of_consumption_universe",
    "omitted_expenditure",
    "omitted_nonconsumption_expenditure",
)


def render_coverage_population(rows) -> str:
    return _render_csv(
        COVERAGE_POP_COLUMNS,
        [
            {
                "population": r.population,
                "universe_expenditure": _d(r.universe_expenditure, 0),
                "consumption_universe_expenditure": _d(
                    r.consumption_universe_expenditure, 0
                ),
                "canonical_source_expenditure": _d(r.canonical_source_expenditure, 0),
                "covered_share_of_universe": _d(r.covered_share_of_universe),
                "covered_share_of_consumption_universe": _d(
                    r.covered_share_of_consumption_universe
                ),
                "omitted_expenditure": _d(r.omitted_expenditure, 0),
                "omitted_nonconsumption_expenditure": _d(
                    r.omitted_nonconsumption_expenditure, 0
                ),
            }
            for r in rows
        ],
    )


COVERAGE_NODE_COLUMNS = (
    "dmi_node",
    "coverage_state",
    "canonical_ucc_count",
    "canonical_source_all_cu",
    "omitted_candidate_ucc_count",
    "omitted_candidate_all_cu",
    "audited_domain_origin",
    "note",
)


def render_coverage_node(rows) -> str:
    return _render_csv(
        COVERAGE_NODE_COLUMNS,
        [
            {
                "dmi_node": r.node,
                "coverage_state": r.coverage_state,
                "canonical_ucc_count": str(r.canonical_ucc_count),
                "canonical_source_all_cu": _d(r.canonical_source_all_cu),
                "omitted_candidate_ucc_count": str(r.omitted_candidate_ucc_count),
                "omitted_candidate_all_cu": _d(r.omitted_candidate_all_cu, 0),
                "audited_domain_origin": _b(r.audited_domain_origin),
                "note": r.note,
            }
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build(bls_dir: Path) -> dict[Path, str]:
    ledger_rows = rec.load_ledger()
    accounting = rec.population_accounting(ledger_rows)
    nodes = rec.node_accounting(ledger_rows)
    groups = rec.replacement_groups(ledger_rows)
    owner_outlays = rec.owner_outlay_uccs()
    deltas = rec.shelter_deltas(ledger_rows, owner_outlays)

    universe = cov.build_universe(
        bls_dir / "cx.series", bls_dir / "cx.item", bls_dir / "cx.aspect"
    )
    domain_add = cov.validate_additivity(universe)
    grand_add = cov.validate_grand_total(universe)
    additive = cov.additivity_established(domain_add, grand_add)

    canonical_uccs = {r.ucc for r in ledger_rows if r.is_published_basis}
    concordance = cov.load_concordance()
    omitted = cov.omitted_ledger(
        universe, canonical_uccs, AUDITED_DOMAINS, concordance
    )

    source_by_pop = {a.population: a.source_total for a in accounting}
    coverage_pop = cov.population_coverage(
        universe, canonical_uccs, source_by_pop, additive
    )

    canonical_node_uccs: dict[str, set[str]] = defaultdict(set)
    canonical_node_all_cu: dict[str, Decimal | None] = {}
    for row in ledger_rows:
        if row.is_published_basis and row.dmi_node:
            canonical_node_uccs[row.dmi_node].add(row.ucc)
    for node_row in nodes:
        if node_row.population == "ALL_CU":
            canonical_node_all_cu[node_row.node] = node_row.source_expenditure
    taxonomy = cov.taxonomy_nodes()
    coverage_node = cov.node_coverage(
        taxonomy, canonical_node_uccs, canonical_node_all_cu, omitted, additive
    )

    summary = build_summary(
        bls_dir=bls_dir,
        accounting=accounting,
        deltas=deltas,
        groups=groups,
        universe=universe,
        domain_add=domain_add,
        grand_add=grand_add,
        additive=additive,
        omitted=omitted,
        coverage_pop=coverage_pop,
        coverage_node=coverage_node,
        canonical_uccs=canonical_uccs,
    )

    return {
        OUTPUT_DIR / "population_accounting_reconciliation.csv": render_population(
            accounting
        ),
        OUTPUT_DIR / "node_accounting_reconciliation.csv": render_node(nodes),
        OUTPUT_DIR / "replacement_group_reconciliation.csv": render_replacement(groups),
        OUTPUT_DIR / "shelter_delta_reconciliation.csv": render_shelter(deltas),
        OUTPUT_DIR / "universe_additivity_validation.csv": render_additivity(
            domain_add, grand_add
        ),
        OUTPUT_DIR / "omitted_published_ucc_ledger.csv": render_omitted(omitted),
        OUTPUT_DIR / "universe_coverage_by_population.csv": render_coverage_population(
            coverage_pop
        ),
        OUTPUT_DIR / "universe_coverage_by_node.csv": render_coverage_node(
            coverage_node
        ),
        OUTPUT_DIR / "c3_summary.json": json.dumps(summary, indent=2, sort_keys=True)
        + "\n",
    }


def build_summary(**kw) -> dict:
    accounting = kw["accounting"]
    coverage_pop = kw["coverage_pop"]
    coverage_node = kw["coverage_node"]
    omitted = kw["omitted"]
    additive = kw["additive"]
    universe = kw["universe"]
    bls_dir = kw["bls_dir"]

    reconciliation_pass = all(a.closes for a in accounting)

    by_classification: dict[str, int] = defaultdict(int)
    for row in omitted:
        by_classification[row.omission_classification] += 1

    omitted_all_cu = None
    if additive:
        omitted_all_cu = sum(
            (r.amounts["ALL_CU"] for r in omitted if r.amounts["ALL_CU"] is not None),
            Decimal(0),
        )

    unaudited_nodes = [
        n.node
        for n in coverage_node
        if n.coverage_state
        in ("ABSENT_FROM_CANONICAL_BASIS", "PARTIALLY_REPRESENTED")
    ]

    return {
        "artifact_id": "C3_SUMMARY_2024_V0_1",
        "version": "0.1",
        "status": "RESEARCH_ONLY",
        "milestone": "Detailed Inflation Substrate v0.1, task C3",
        "scope": (
            "Research only. C3 reconciles the frozen canonical ledger against "
            "itself and measures its coverage of the published expenditure "
            "universe. It normalises nothing, prices nothing, adjudicates no "
            "omitted UCC and assigns no Track-A treatment."
        ),
        "checkpoint": {
            "tag": CHECKPOINT_TAG,
            "commit": CHECKPOINT_SHA,
            "canonical_manifest_sha256": _digest(MANIFEST_PATH),
            "canonical_ledger_sha256": _digest(rec.LEDGER_PATH),
        },
        "source_vintages": {
            "ce_labstat_year": 2024,
            "ce_period": "A01",
            "ce_demographics_code": "LB01",
            "cx_series_sha256": _digest(bls_dir / "cx.series"),
            "cx_item_sha256": _digest(bls_dir / "cx.item"),
            "cx_aspect_sha256": _digest(bls_dir / "cx.aspect"),
        },
        "methodology": {
            "population_order": list(POPS),
            "node_taxonomy_version": json.loads(
                cov.TAXONOMY_PATH.read_text(encoding="utf-8")
            )["version"],
            "arithmetic_policy": (
                "Ledger amounts are fixed-point decimal strings read as "
                "decimal.Decimal, so C3-A sums are exact and its residuals are "
                "exactly zero. No tolerance is used or offered in C3-A."
            ),
            "coverage_tolerance_policy": (
                "The universe comparison is against BLS figures published "
                "rounded to whole millions, so a residual of at most "
                "0.5 * (leaves + 1) is admitted. The bound is derived from the "
                "publication rounding rule, not tuned to the data."
            ),
            "full_universe_construction_rule": (
                "Numeric six-digit item codes of series with category_code "
                "EXPEND, demographics_code LB01, characteristics_code in the "
                "six Income-Quintile populations, and begin_year <= 2024 <= "
                "end_year. Derived from cx.series metadata; no UCC list is "
                "written down."
            ),
            "full_universe_inclusion_exclusion": [
                "Included: every 2024-active numeric UCC in an EXPEND "
                "subcategory, across all fourteen CE domains.",
                "Excluded: non-numeric item codes, which are published "
                "roll-ups of the numeric leaves and would double count.",
                "Excluded: ADDENDA, INCOME and CUCHARS categories, which are "
                "not expenditure.",
                "Excluded: series not active in 2024, which is why 581 of the "
                "998 numeric codes in cx.item are in the universe.",
                "TOTALEXP is the published grand-total root and is used only "
                "as the parent in the additivity check, never as a domain.",
            ],
            "candidate_node_attribution": (
                "Omitted UCCs carry a candidate DMI node derived from their CE "
                "domain. It is a diagnostic convenience so omitted dollars can "
                "be reported by node, not a mapping decision. Every omitted "
                "UCC is flagged requires_scope_adjudication."
            ),
        },
        "internal_reconciliation": {
            "status": "PASS" if reconciliation_pass else "FAIL",
            "source_residual_by_population": {
                a.population: _d(a.source_residual) for a in accounting
            },
            "effective_residual_by_population": {
                a.population: _d(a.effective_residual) for a in accounting
            },
            "e_source_by_population": {
                a.population: _d(a.source_total) for a in accounting
            },
            "e_track_a_effective_by_population": {
                a.population: _d(a.effective_total) for a in accounting
            },
            "pending_source_amount_by_population": {
                a.population: _d(a.pending_source_amount) for a in accounting
            },
            "pending_replacement_amount_by_population": {
                a.population: _d(a.pending_replacement_amount) for a in accounting
            },
            "pending_total_admitted_amount_by_population": {
                a.population: _d(a.pending) for a in accounting
            },
            "open_by_population": {a.population: _d(a.open_) for a in accounting},
            "withheld_replacement_amount_by_population": {
                a.population: _d(a.withheld_replacement_amount) for a in accounting
            },
            "withheld_total_amount_by_population": {
                a.population: _d(a.withheld) for a in accounting
            },
            "amounts_not_in_force_identity": (
                "pending_total_admitted_amount = pending_source_amount + "
                "pending_replacement_amount, exactly, in every population. "
                "Withheld is not part of pending: it is an amount that was "
                "produced and failed a declared quality gate. For All Consumer "
                "Units the identity reads 46,322.000000 + 102,234.815688 = "
                "148,556.815688, and the withheld 665.471372 sits outside it. "
                "The secondary-residence replacement side therefore totals "
                "102,900.287060, of which the pending part is admitted as an "
                "estimate and the withheld part is not."
            ),
            "no_balancing_bucket_exists": True,
            "note": (
                "Source residuals are exactly zero because every published-basis "
                "row sits in exactly one disposition bucket carrying its own "
                "source amount. That is a property of the C2 construction, "
                "asserted cell by cell rather than assumed."
            ),
        },
        "shelter_deltas": {
            "reproduced_from_ledger": True,
            "delta_scope_all_cu": _d(kw["deltas"][0].delta_scope),
            "delta_shelter_frozen_membership_all_cu": _d(
                kw["deltas"][0].delta_shelter_frozen_membership
            ),
            "delta_shelter_frozen_membership_interpretation": (
                FROZEN_MEMBERSHIP_INTERPRETATION
            ),
            "delta_shelter_current_state_interpretation": CURRENT_STATE_INTERPRETATION,
            "no_unqualified_delta_shelter_is_published": (
                "Every delta_shelter figure in this summary and in "
                "shelter_delta_reconciliation.csv names which removal "
                "membership it was computed over. The two differ by 199,079 "
                "million dollars, so an unqualified field would be ambiguous "
                "in exactly the case where it matters."
            ),
            "delta_shelter_current_state_all_cu": _d(
                kw["deltas"][0].delta_shelter_current_state
            ),
            "definition_difference_all_cu": _d(kw["deltas"][0].definition_difference),
            "classification": "DIFFERENCE_IN_ACCOUNTING_DEFINITION",
            "finding": (
                "delta_scope reproduces the frozen shelter checkpoint exactly. "
                "delta_shelter reproduces it exactly only under the removal "
                "membership frozen at that checkpoint. Owner maintenance "
                "services, 199,079 million dollars, was OWNER_OUTLAY and "
                "PROPOSED then and is ACCEPTED and out of scope now, so a "
                "current-state reading of 'owner outlays removed' gives a "
                "delta_shelter smaller by exactly that amount. The residual "
                "task recorded delta_shelter as unchanged and justified it by "
                "noting that pending and accepted-out-of-scope both sit "
                "outside the CPI basis. That argument is sufficient for "
                "delta_scope, whose second term is the CPI basis, and it is "
                "not sufficient for delta_shelter, whose second term is a "
                "removal set. The invariance is real but rests on the "
                "membership being pinned at the shelter checkpoint rather than "
                "on the bucket-movement argument given. Both readings are "
                "reported and neither number is adjusted."
            ),
        },
        "coverage": {
            "full_universe_additivity_established": additive,
            "full_universe_ucc_count": len(universe.uccs),
            "canonical_published_basis_ucc_count": len(kw["canonical_uccs"]),
            "omitted_ucc_count": len(omitted),
            "structural_ucc_coverage": _d(
                Decimal(len(kw["canonical_uccs"])) / Decimal(len(universe.uccs))
            ),
            "omitted_expenditure_all_cu": _d(omitted_all_cu, 0),
            "covered_share_of_universe_all_cu": _d(
                coverage_pop[0].covered_share_of_universe
            ),
            "covered_share_of_consumption_universe_all_cu": _d(
                coverage_pop[0].covered_share_of_consumption_universe
            ),
            "omission_classification_counts": dict(sorted(by_classification.items())),
            "audited_ce_domains": list(AUDITED_DOMAINS),
            "unaudited_ce_domains": [
                d for d in universe.domains if d not in AUDITED_DOMAINS
            ],
            "nodes_not_fully_represented": unaudited_nodes,
            "status": "MATERIAL_EXPANSION_REQUIRED",
            "why": (
                "Ten of the fourteen CE expenditure domains have never been "
                "through the mapping, provenance and scope discipline the four "
                "audited domains received. They carry roughly a third of "
                "published total expenditure. Every one of the fourteen "
                "taxonomy nodes that is not fully represented is a node whose "
                "expenditure sits in those domains, and Apparel has no "
                "canonical representation at all. Whether the current ledger "
                "is an adequate normalisation denominator is a judgement for "
                "human review; the evidence here does not support calling it "
                "sufficient."
            ),
        },
        "non_goals_observed": [
            "No normalised weight is computed anywhere in C3.",
            "No CPI price index is acquired.",
            "No inflation figure is calculated.",
            "No omitted UCC receives a Track-A rule, disposition or node "
            "adjudication.",
            "The frozen C1+C2 artifacts are read and never written.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bls-dir",
        default="~/dev/dmi-data",
        help="directory holding cx.series, cx.item and cx.aspect",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory and fail on any difference from disk",
    )
    args = parser.parse_args()
    bls_dir = Path(args.bls_dir).expanduser()

    rendered = build(bls_dir)

    if args.check:
        differing = []
        for path, content in sorted(rendered.items()):
            if not path.exists():
                differing.append((path, "missing"))
            elif path.read_text(encoding="utf-8") != content:
                differing.append((path, "differs"))
        for path, why in differing:
            print(f"CHANGED {path.relative_to(REPO_ROOT)}: {why}", file=sys.stderr)
        if differing:
            print(
                "\nThese artifacts are deterministic and carry no timestamp, "
                "so a difference means an input moved.",
                file=sys.stderr,
            )
            return 1
        print(f"unchanged: {len(rendered)} artifacts")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path, content in sorted(rendered.items()):
        path.write_text(content, encoding="utf-8")
    print("wrote")
    for path in sorted(rendered):
        print(f"  {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
