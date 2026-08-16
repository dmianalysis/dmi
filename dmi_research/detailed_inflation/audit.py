"""Milestone 1 audit orchestration and artifact emission.

Detailed Inflation Substrate v0.1, Milestone 1 (prompt sections 5, 13, 14).

This module wires the loaders, the accounting basis, the concordance
classification and the RSE audit together, and writes the machine-readable
artifacts. It performs no index computation and constructs no weights.

Research firewall: :func:`assert_research_output_dir` refuses to write
anywhere under ``data/outputs/`` or ``deploy/data/outputs/``.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import FORBIDDEN_OUTPUT_ROOTS
from .basis import BLS_AGGREGATE_ROUNDING_UNIT, Basis, build_basis
from .concordance import DEFAULT_CONCORDANCE_PATH, Concordance, load_concordance
from .mapping import (
    UccMapping,
    build_exception_ledger,
    build_mappings,
    summarize_status,
)
from .rse import COMBINED_DOMAIN_LABEL, HIGH_RSE_THRESHOLD, build_rse_audit
from .sources import (
    ASPECT_AGGREGATE,
    ASPECT_RSE,
    TARGET_YEAR,
    load_aspects,
    load_data,
    load_items,
    load_series,
    select_target_series,
)
from .taxonomy import load_eli_resolver, load_taxonomy

#: Prompt section 14 validation targets. These are compared against, and
#: reported alongside, the derived values. They are never substituted for a
#: derived value and never used inside computation.
EXPECTED_BASELINES = {
    "active_ucc_count": 337,
    "expenditure_share_pct": {
        "DIRECT": 71.39,
        "MULTI_SAME_NODE": 9.20,
        "CROSS_NODE_MULTI_MAP": 0.0,
        "NO_CONCORDANCE": 19.41,
    },
    "high_rse_expenditure_share_pct": {
        "All Consumer Units": 0.98,
        "Q1": 11.47,
        "Q2": 9.81,
        "Q3": 7.93,
        "Q4": 6.52,
        "Q5": 2.79,
    },
}


class ResearchFirewallError(RuntimeError):
    """Raised when a research run would write into an operational output tree."""


def assert_research_output_dir(output_dir: Path, repo_root: Path | None = None) -> Path:
    """Reject output directories inside operational output trees."""
    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    resolved = Path(output_dir).resolve()
    for forbidden in FORBIDDEN_OUTPUT_ROOTS:
        forbidden_path = (repo_root / forbidden).resolve()
        if resolved == forbidden_path or forbidden_path in resolved.parents:
            raise ResearchFirewallError(
                f"Refusing to write research artifacts to {resolved}: the "
                f"Milestone 1 audit must never create or modify files under "
                f"{forbidden}/."
            )
    return resolved


@dataclass
class AuditResult:
    basis: Basis
    mappings: list[UccMapping]
    concordance: Concordance
    summary: dict


def run_audit(
    *,
    series_path: Path,
    data_path: Path,
    items_path: Path,
    aspects_path: Path,
    concordance_path: Path = DEFAULT_CONCORDANCE_PATH,
    year: int = TARGET_YEAR,
    rounding_unit: float = BLS_AGGREGATE_ROUNDING_UNIT,
    rse_threshold: float = HIGH_RSE_THRESHOLD,
) -> AuditResult:
    """Execute the Milestone 1 audit and return its results in memory."""
    nodes = load_taxonomy()
    resolver = load_eli_resolver(nodes)
    concordance = load_concordance(concordance_path)

    all_series = load_series(series_path)
    target_series = select_target_series(all_series, year=year)
    target_ids = {record.series_id for record in target_series}

    items = load_items(items_path)
    aspects = load_aspects(
        aspects_path,
        year=year,
        aspect_types=(ASPECT_AGGREGATE, ASPECT_RSE),
        series_ids=target_ids,
    )
    data = load_data(data_path, year=year, series_ids=target_ids)

    basis = build_basis(target_series, items, aspects, data)
    mappings = build_mappings(basis.entries, concordance, resolver)

    # Fail loudly rather than silently reporting an unreconciled basis.
    failures = basis.failed_reconciliations(rounding_unit)

    status_summaries = summarize_status(basis.entries, mappings)
    rse_summaries = build_rse_audit(basis.entries, threshold=rse_threshold)
    ledger = build_exception_ledger(mappings, basis.entries)

    summary = _build_summary(
        basis=basis,
        mappings=mappings,
        concordance=concordance,
        status_summaries=status_summaries,
        rse_summaries=rse_summaries,
        ledger=ledger,
        reconciliation_failures=failures,
        rounding_unit=rounding_unit,
        rse_threshold=rse_threshold,
        year=year,
        sources={
            "series": str(series_path),
            "data": str(data_path),
            "items": str(items_path),
            "aspects": str(aspects_path),
            "concordance": str(concordance_path),
        },
    )
    summary["_status_summaries"] = status_summaries
    summary["_rse_summaries"] = rse_summaries
    summary["_ledger"] = ledger

    return AuditResult(
        basis=basis, mappings=mappings, concordance=concordance, summary=summary
    )


def _build_summary(
    *,
    basis,
    mappings,
    concordance,
    status_summaries,
    rse_summaries,
    ledger,
    reconciliation_failures,
    rounding_unit,
    rse_threshold,
    year,
    sources,
) -> dict:
    from .mapping import ExceptionReason

    reference = "All Consumer Units"
    ref_status = {
        s.status.value: s for s in status_summaries if s.population == reference
    }
    ref_total = sum(
        e.aggregate_expenditure or 0.0
        for e in basis.entries
        if e.population == reference
    )
    ref_aggregates = {
        e.ucc: e.aggregate_expenditure or 0.0
        for e in basis.entries
        if e.population == reference
    }

    by_reason: dict[str, dict] = {}
    for reason in ExceptionReason:
        members = [m for m in mappings if m.exception_reason is reason]
        aggregate = sum(ref_aggregates.get(m.ucc, 0.0) for m in members)
        by_reason[reason.value] = {
            "ucc_count": len(members),
            "aggregate_expenditure": aggregate,
            "expenditure_share_pct": (
                100.0 * aggregate / ref_total if ref_total else 0.0
            ),
            "uccs": [m.ucc for m in members],
        }

    derived_shares = {
        "DIRECT": ref_status["DIRECT"].expenditure_share_pct
        if "DIRECT" in ref_status
        else 0.0,
        "MULTI_SAME_NODE": ref_status["MULTI_SAME_NODE"].expenditure_share_pct
        if "MULTI_SAME_NODE" in ref_status
        else 0.0,
        "CROSS_NODE_MULTI_MAP": by_reason["CROSS_NODE_MULTI_MAP"][
            "expenditure_share_pct"
        ],
        "NO_CONCORDANCE": by_reason["NO_CONCORDANCE"]["expenditure_share_pct"],
    }

    combined_rse = {
        s.population: s.high_rse_expenditure_share_pct
        for s in rse_summaries
        if s.subcategory_code == COMBINED_DOMAIN_LABEL
    }

    multi_same_node = [
        {
            "ucc": m.ucc,
            "ucc_title": m.ucc_title,
            "node": m.node,
            "elis": list(m.elis),
        }
        for m in mappings
        if m.status.value == "MULTI_SAME_NODE"
    ]

    return {
        "artifact_id": "detailed_inflation_audit_2024",
        "milestone": "Detailed Inflation Substrate v0.1, Milestone 1",
        "status": "RESEARCH_ONLY",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "core_dmi": "WITHDRAWN — not implemented, not computed by this audit",
        "year": year,
        "sources": sources,
        "concordance_provenance": concordance.provenance,
        "parameters": {
            "bls_aggregate_rounding_unit": rounding_unit,
            "reconciliation_rule": (
                "|sum(active leaves) - published parent| <= "
                "0.5 * rounding_unit * (published_leaf_count + 1), the exact "
                "worst case of publication rounding."
            ),
            "high_rse_threshold": rse_threshold,
            "reference_population_for_shares": reference,
        },
        "active_ucc_count": basis.active_ucc_count,
        "populations": sorted({e.population for e in basis.entries}),
        "reconciliation": {
            "checks": len(basis.reconciliations),
            "failures": [
                {
                    "domain": r.domain_label,
                    "population": r.population,
                    "sum_active_ucc_aggregate": r.sum_active_ucc_aggregate,
                    "published_parent_aggregate": r.published_parent_aggregate,
                    "absolute_difference": r.absolute_difference,
                    "percent_difference": r.percent_difference,
                    "rounding_bound": r.rounding_bound(rounding_unit),
                }
                for r in reconciliation_failures
            ],
            "passed": not reconciliation_failures,
            "max_abs_difference": max(
                (abs(r.absolute_difference) for r in basis.reconciliations
                 if r.absolute_difference is not None),
                default=None,
            ),
            "max_abs_percent_difference": max(
                (abs(r.percent_difference) for r in basis.reconciliations
                 if r.percent_difference is not None),
                default=None,
            ),
            "min_rounding_bound": min(
                (r.rounding_bound(rounding_unit) for r in basis.reconciliations),
                default=None,
            ),
        },
        "mapping_status_counts": {
            s.status.value: s.ucc_count
            for s in status_summaries
            if s.population == reference
        },
        "mapping_expenditure_share_pct": derived_shares,
        "exceptions_by_reason": by_reason,
        "multi_same_node_cases": multi_same_node,
        "cross_node_multi_map_found": by_reason["CROSS_NODE_MULTI_MAP"]["ucc_count"] > 0,
        "high_rse_expenditure_share_pct": combined_rse,
        "missing_data": {
            "note": (
                "BLS suppresses estimates that do not meet publication "
                "standards. Suppressed values are reported as missing and are "
                "never coerced to zero."
            ),
            "missing_aggregate_by_population": {
                s.population: s.missing_aggregate_count
                for s in rse_summaries
                if s.subcategory_code == COMBINED_DOMAIN_LABEL
            },
            "missing_rse_by_population": {
                s.population: s.missing_rse_count
                for s in rse_summaries
                if s.subcategory_code == COMBINED_DOMAIN_LABEL
            },
        },
        "expected_baselines": EXPECTED_BASELINES,
        "baseline_deltas": {
            "active_ucc_count": basis.active_ucc_count
            - EXPECTED_BASELINES["active_ucc_count"],
            "expenditure_share_pct": {
                key: round(derived_shares[key] - expected, 4)
                for key, expected in EXPECTED_BASELINES[
                    "expenditure_share_pct"
                ].items()
            },
            "high_rse_expenditure_share_pct": {
                key: round(combined_rse.get(key, 0.0) - expected, 4)
                for key, expected in EXPECTED_BASELINES[
                    "high_rse_expenditure_share_pct"
                ].items()
            },
        },
        "exception_ledger_size": len(ledger),
    }


# ---------------------------------------------------------------------------
# Artifact writers
# ---------------------------------------------------------------------------


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _num(value: float | None) -> str:
    return "" if value is None else repr(value) if isinstance(value, float) else str(value)


def write_artifacts(result: AuditResult, output_dir: Path) -> list[Path]:
    """Write every Milestone 1 artifact. Returns the paths written."""
    output_dir = assert_research_output_dir(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = dict(result.summary)
    status_summaries = summary.pop("_status_summaries")
    rse_summaries = summary.pop("_rse_summaries")
    ledger = summary.pop("_ledger")

    written: list[Path] = []

    summary_path = output_dir / "audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    written.append(summary_path)

    basis_path = output_dir / "active_ucc_basis.csv"
    _write_csv(
        basis_path,
        [
            "population",
            "characteristics_code",
            "subcategory_code",
            "domain_label",
            "ucc",
            "item_text",
            "display_level",
            "series_id",
            "aggregate_expenditure",
            "mean_expenditure",
            "rse",
            "high_rse",
        ],
        [
            [
                e.population,
                e.characteristics_code,
                e.subcategory_code,
                e.domain_label,
                e.ucc,
                e.item_text,
                e.display_level,
                e.series_id,
                _num(e.aggregate_expenditure),
                _num(e.mean_expenditure),
                _num(e.rse),
                "" if e.rse is None else str(e.rse >= HIGH_RSE_THRESHOLD).lower(),
            ]
            for e in result.basis.entries
        ],
    )
    written.append(basis_path)

    recon_path = output_dir / "parent_reconciliation.csv"
    _write_csv(
        recon_path,
        [
            "population",
            "subcategory_code",
            "domain_label",
            "parent_series_id",
            "active_ucc_count",
            "missing_aggregate_count",
            "sum_active_ucc_aggregate",
            "published_parent_aggregate",
            "absolute_difference",
            "percent_difference",
            "rounding_bound",
            "within_rounding",
        ],
        [
            [
                r.population,
                r.subcategory_code,
                r.domain_label,
                r.parent_series_id or "",
                r.active_ucc_count,
                r.missing_aggregate_count,
                _num(r.sum_active_ucc_aggregate),
                _num(r.published_parent_aggregate),
                _num(r.absolute_difference),
                _num(r.percent_difference),
                _num(r.rounding_bound()),
                str(r.within_rounding()).lower(),
            ]
            for r in result.basis.reconciliations
        ],
    )
    written.append(recon_path)

    mapping_path = output_dir / "ucc_mapping_audit.csv"
    _write_csv(
        mapping_path,
        [
            "ucc",
            "ucc_title",
            "subcategory_code",
            "domain_label",
            "mapping_status",
            "computation_node",
            "destination_eli_count",
            "destination_elis",
            "destination_nodes",
            "exception_reason",
            "bls_multi_eli_footnote",
        ],
        [
            [
                m.ucc,
                m.ucc_title,
                m.subcategory_code,
                m.domain_label,
                m.status.value,
                m.node or "",
                m.destination_count,
                "|".join(m.elis),
                "|".join(m.nodes),
                m.exception_reason.value if m.exception_reason else "",
                str(m.multi_eli_footnote).lower(),
            ]
            for m in result.mappings
        ],
    )
    written.append(mapping_path)

    status_path = output_dir / "mapping_status_summary.csv"
    _write_csv(
        status_path,
        [
            "population",
            "mapping_status",
            "ucc_count",
            "aggregate_expenditure",
            "expenditure_share_pct",
        ],
        [
            [
                s.population,
                s.status.value,
                s.ucc_count,
                _num(s.aggregate_expenditure),
                _num(s.expenditure_share_pct),
            ]
            for s in status_summaries
        ],
    )
    written.append(status_path)

    rse_path = output_dir / "rse_audit.csv"
    _write_csv(
        rse_path,
        [
            "population",
            "subcategory_code",
            "domain_label",
            "active_ucc_count",
            "high_rse_ucc_count",
            "missing_rse_count",
            "missing_aggregate_count",
            "total_aggregate_expenditure",
            "high_rse_aggregate_expenditure",
            "high_rse_expenditure_share_pct",
        ],
        [
            [
                s.population,
                s.subcategory_code,
                s.domain_label,
                s.active_ucc_count,
                s.high_rse_ucc_count,
                s.missing_rse_count,
                s.missing_aggregate_count,
                _num(s.total_aggregate_expenditure),
                _num(s.high_rse_aggregate_expenditure),
                _num(s.high_rse_expenditure_share_pct),
            ]
            for s in rse_summaries
        ],
    )
    written.append(rse_path)

    ledger_path = output_dir / "exception_ledger.csv"
    _write_csv(
        ledger_path,
        [
            "ucc",
            "ucc_title",
            "subcategory_code",
            "domain_label",
            "reason",
            "preliminary_status",
            "destination_elis",
            "destination_nodes",
            "all_cu_aggregate_expenditure",
            "resolution_note",
        ],
        [
            [
                e.ucc,
                e.ucc_title,
                e.subcategory_code,
                e.domain_label,
                e.reason.value,
                e.preliminary_status.value,
                "|".join(e.elis),
                "|".join(e.nodes),
                _num(e.all_cu_aggregate_expenditure),
                e.resolution_note,
            ]
            for e in ledger
        ],
    )
    written.append(ledger_path)

    return written
