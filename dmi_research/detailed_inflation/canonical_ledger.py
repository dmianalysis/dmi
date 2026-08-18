"""Canonical UCC x population accounting ledger for the 2024 substrate.

Detailed Inflation Substrate v0.1, task C2.

RESEARCH ONLY. Reads committed research registries and committed research
artifacts. Writes only under ``registry/research`` and
``data/research/detailed_inflation``. Touches no production module, manifest
or output.

What this ledger is
-------------------
One row per (UCC, population). Every row says where its amount came from,
what the current governing rule does with it, and which single accounting
bucket it lands in. Six populations are always present for every UCC, whether
or not an amount exists, because a row that disappears when its value is
unavailable turns a measurement gap into an apparent absence of the item.

What this ledger is not
-----------------------
It is not a weighting basis. No column here is a weight, a share or a
denominator, and ``normalization_state`` is a classification of whether an
amount *could* one day enter a normalisation, not a step toward one.
``test_no_normalization_arithmetic_leaks_into_c2`` reads this module's syntax
tree and fails if such a field appears.

It is not a reconciliation. It does not sum amounts across UCCs, does not
compare a total against a published total, and asserts no identity between
buckets. That is the next task's job, and doing it early would let a
convenient identity decide a disposition.

The three distinctions that carry the weight
--------------------------------------------
*Proposed is not effective.* A rule with review status PROPOSED may never put
an amount into ``excluded_amount``, ``transformed_amount``,
``removed_for_replacement_amount`` or ``replacement_amount``. That is enforced
in one place, :func:`_disposition_for`, which reads the canonical state and
never the rule's own ``final_status``.

*Null is not zero.* A blank amount means the amount is unavailable, withheld,
suppressed or undefined. A numeric ``0.0`` means BLS observed zero. UCC 910106
carries both in the same column across its six populations, and is the
regression case the null/zero tests are built on.

*Removal is not replacement.* When a source amount leaves because a different
concept prices the same thing, the amount removed and the amount introduced
are two facts, not one. They share a ``replacement_group_id`` and are never
assumed equal.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum
from pathlib import Path

from . import canonical_state as cstate
from .canonical_state import (
    POPULATIONS,
    CanonicalRuleState,
    CanonicalRules,
    UccRuleRole,
)

REPO_ROOT = cstate.REPO_ROOT
REGISTRY_DIR = cstate.REGISTRY_DIR
RESEARCH_DIR = REPO_ROOT / "data/research/detailed_inflation"
OUTPUT_DIR = RESEARCH_DIR / "canonical_substrate_2024"

LEDGER_PATH = OUTPUT_DIR / "ucc_population_accounting_ledger.csv"
LEDGER_SUMMARY_PATH = OUTPUT_DIR / "canonical_ledger_summary.json"
SCHEMA_PATH = REGISTRY_DIR / "canonical_ledger_schema_v0_1.json"

SCHEMA_ARTIFACT_ID = "CANONICAL_LEDGER_SCHEMA_V0_1"
SCHEMA_VERSION = "0.1"

BASIS_PATH = RESEARCH_DIR / "audit_2024/active_ucc_basis.csv"
MAPPING_AUDIT_PATH = RESEARCH_DIR / "audit_2024/ucc_mapping_audit.csv"
PROVENANCE_ROSTER_PATH = RESEARCH_DIR / "milestone_2/ucc_provenance_classes_2024.csv"
SHELTER_ESTIMATES_PATH = RESEARCH_DIR / "shelter_2024/shelter_estimates_2024.csv"

#: Populations as the LABSTAT-derived basis names them, mapped onto the
#: canonical labels. The all-consumer-units row is the only one that differs,
#: and coercing it by string munging rather than by an explicit table is how
#: a population silently goes missing.
_BASIS_POPULATION = {
    cstate.BASIS_ALL_CU_LABEL: "ALL_CU",
    "Q1": "Q1",
    "Q2": "Q2",
    "Q3": "Q3",
    "Q4": "Q4",
    "Q5": "Q5",
}


class LedgerError(RuntimeError):
    """A ledger invariant does not hold."""


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class SourceClass(str, Enum):
    """Which kind of thing a UCC is, for accounting purposes."""

    #: A member of the 2024 active numeric-UCC accounting basis. Its amount is
    #: a published LABSTAT aggregate.
    PUBLISHED_CE_BASIS = "PUBLISHED_CE_BASIS"
    #: Named by the CE->CPI concordance and absent from the published CE item
    #: file, so no published aggregate exists and any amount must be estimated
    #: from microdata under a documented procedure.
    CONCORDANCE_ONLY_ESTIMATED = "CONCORDANCE_ONLY_ESTIMATED"
    #: A destination that a rule combines other UCCs into. It has no source
    #: amount of its own; the amount is carried on the rows it comes from.
    TRANSFORMATION_DESTINATION = "TRANSFORMATION_DESTINATION"
    #: A published CE addendum that the accounting basis deliberately excludes
    #: to avoid double counting the concept it duplicates. It is a validation
    #: counterpart, never an accounting input.
    PUBLISHED_ADDENDUM_OUTSIDE_BASIS = "PUBLISHED_ADDENDUM_OUTSIDE_BASIS"


class AmountSource(str, Enum):
    """Where a row's amount would come from, if it has one.

    The first four members are the vocabulary the task specified. The two
    that follow exist because collapsing them into those four would assert
    something false.
    """

    #: Published by BLS in the LABSTAT CE aggregate series.
    LABSTAT_PUBLISHED = "LABSTAT_PUBLISHED"
    #: Estimated from the CE Public Use Microdata by an estimator whose
    #: quantitative usability is BENCHMARKED in the governing provenance
    #: registry.
    PUMD_BENCHMARKED = "PUMD_BENCHMARKED"
    #: Estimated from the same microdata by the same estimator, on a UCC whose
    #: quantitative usability is still NOT_ESTABLISHED. Separated from
    #: PUMD_BENCHMARKED because method validity is a property of the cell, not
    #: only of the procedure: the estimator is the same one and the cell it
    #: is applied to has not cleared the gate.
    PUMD_NOT_BENCHMARKED = "PUMD_NOT_BENCHMARKED"
    #: Produced by applying a rule's transformation to other UCCs' amounts.
    DERIVED_TRANSFORMATION = "DERIVED_TRANSFORMATION"
    #: An amount exists and the governing registry forbids taking a Track-A
    #: figure from it. Separated from NO_AMOUNT_AVAILABLE because "we have a
    #: number we may not use" and "we have no number" are different states and
    #: only one of them is a measurement gap.
    NOT_ADMISSIBLE_VALIDATION_ONLY = "NOT_ADMISSIBLE_VALIDATION_ONLY"
    #: No amount exists from any admitted source.
    NO_AMOUNT_AVAILABLE = "NO_AMOUNT_AVAILABLE"


class AmountStatus(str, Enum):
    """Why a source amount cell holds what it holds.

    Zero is never the encoding for any member but ``OBSERVED``. A blank cell
    with one of the other four statuses is the only correct way to record an
    amount that is not there.
    """

    #: A numeric amount exists and is admitted. ``0.0`` under this status is a
    #: genuine observed zero, and the basis contains seven of them.
    OBSERVED = "OBSERVED"
    #: BLS publishes the series and did not publish this cell.
    SUPPRESSED = "SUPPRESSED"
    #: An amount was produced and is not admitted, because it failed a
    #: declared quality gate. The amount is still shown: withheld means not
    #: admitted, not unknown.
    WITHHELD = "WITHHELD"
    #: No amount was produced at all. For 910106 in Q1 this is because no
    #: consumer unit in the quintile reported the item.
    NOT_AVAILABLE = "NOT_AVAILABLE"
    #: No source amount is defined for this UCC by construction.
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: The statuses under which the amount column must be blank. ``WITHHELD`` is
#: absent on purpose: a withheld amount is known and not admitted.
_MUST_BE_BLANK = frozenset(
    {AmountStatus.SUPPRESSED, AmountStatus.NOT_AVAILABLE, AmountStatus.NOT_APPLICABLE}
)


class Disposition(str, Enum):
    """The single accounting state of one (UCC, population) cell.

    These are accounting states, not quality rankings. ``PENDING`` does not
    mean the evidence is weak and ``EXCLUDED`` does not mean the item is
    unimportant. Each says only where the amount currently sits.
    """

    #: Stays in the CPI-comparable basis at its source value.
    RETAINED = "RETAINED"
    #: Leaves because the CPI does not price it. Nothing replaces it.
    EXCLUDED = "EXCLUDED"
    #: Leaves because a different concept prices the same thing. The
    #: replacement is a separate row and is not assumed equal.
    REMOVED_FOR_REPLACEMENT = "REMOVED_FOR_REPLACEMENT"
    #: The amount stays, reassigned or combined, under an effective rule.
    TRANSFORMED = "TRANSFORMED"
    #: An amount entering under a concept that replaces removed source
    #: amounts.
    REPLACEMENT = "REPLACEMENT"
    #: The governing rule proposes a disposition that is not in force, and
    #: there is no rule-free baseline to fall back to. Neither retained nor
    #: removed.
    PENDING = "PENDING"
    #: No disposition is proposed at all.
    OPEN = "OPEN"
    #: An amount that would belong here is not admitted, because its estimate
    #: failed adjudication. The ledger is incomplete by exactly this item and
    #: says so.
    WITHHELD = "WITHHELD"
    #: No Track-A disposition applies to this row.
    NOT_APPLICABLE = "NOT_APPLICABLE"


#: The amount column each disposition is allowed to populate. A disposition
#: absent from this map populates none. Exactly one column may be non-blank on
#: any row, and it must be this one.
AMOUNT_COLUMN_FOR: Mapping[Disposition, str] = {
    Disposition.RETAINED: "retained_amount",
    Disposition.EXCLUDED: "excluded_amount",
    Disposition.REMOVED_FOR_REPLACEMENT: "removed_for_replacement_amount",
    Disposition.REPLACEMENT: "replacement_amount",
    Disposition.TRANSFORMED: "transformed_amount",
    Disposition.PENDING: "pending_amount",
    Disposition.OPEN: "open_amount",
    Disposition.WITHHELD: "withheld_amount",
}

AMOUNT_COLUMNS: tuple[str, ...] = (
    "retained_amount",
    "excluded_amount",
    "removed_for_replacement_amount",
    "replacement_amount",
    "transformed_amount",
    "pending_amount",
    "open_amount",
    "withheld_amount",
)

#: The four dispositions that put an amount into the CPI-comparable basis
#: under a rule that is actually in force. Only these may be reached from a
#: rule in state CURRENT_EFFECTIVE, and none of them may be reached from a
#: rule in state CURRENT_PENDING.
_EFFECTIVE_ONLY_DISPOSITIONS = frozenset(
    {
        Disposition.EXCLUDED,
        Disposition.REMOVED_FOR_REPLACEMENT,
        Disposition.REPLACEMENT,
        Disposition.TRANSFORMED,
    }
)


class PendingEffect(str, Enum):
    """What a rule that is not in force does to the amount it claims."""

    #: There is no rule-free baseline: the UCC has no CPI mapping, or the rule
    #: would have introduced a concept that does not otherwise exist. The
    #: amount is held in its own bucket, neither in the basis nor removed.
    AMOUNT_HELD_IN_PENDING_BUCKET = "AMOUNT_HELD_IN_PENDING_BUCKET"
    #: The UCC is mapped to a CPI entry-level item, so absent the rule it
    #: would simply be retained. Not applying a partial-retention transform
    #: leaves the amount as recorded, and moving it to the pending bucket
    #: would remove it from the basis entirely -- a larger claim than the
    #: rule makes. The retained amount is an upper bound.
    AMOUNT_REVERTS_TO_MAPPED_BASELINE = "AMOUNT_REVERTS_TO_MAPPED_BASELINE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class NormalizationState(str, Enum):
    """Whether an amount could one day enter a normalisation.

    Classification only. Nothing in this module computes a normalised weight,
    a share or a denominator, and no C2 artifact contains one.
    """

    #: The amount is in the CPI-comparable basis under a rule in force.
    ELIGIBLE = "ELIGIBLE"
    #: The amount is deliberately outside the basis.
    EXCLUDED_FROM_BASIS = "EXCLUDED_FROM_BASIS"
    #: A disposition is proposed and not in force.
    BLOCKED_PENDING_ADJUDICATION = "BLOCKED_PENDING_ADJUDICATION"
    #: No disposition is proposed.
    BLOCKED_UNRESOLVED_METHODOLOGY = "BLOCKED_UNRESOLVED_METHODOLOGY"
    #: A disposition exists but the amount does not.
    BLOCKED_AMOUNT_UNAVAILABLE = "BLOCKED_AMOUNT_UNAVAILABLE"
    #: The amount exists and is not admitted, because its estimate failed a
    #: declared quality gate. Kept distinct from
    #: ``BLOCKED_AMOUNT_UNAVAILABLE`` because the two are unblocked by
    #: different work: one needs a measurement, the other needs an estimate
    #: good enough to admit. Collapsing them would lose the fact that the
    #: number exists.
    BLOCKED_AMOUNT_NOT_ADMITTED = "BLOCKED_AMOUNT_NOT_ADMITTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReplacementRole(str, Enum):
    """Which side of a replacement a row sits on."""

    REMOVAL = "REMOVAL"
    REPLACEMENT = "REPLACEMENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True)
class ReplacementGroup:
    """A removal side and a replacement side that price the same concept."""

    group_id: str
    removal_rule_id: str | None
    replacement_rule_id: str
    linkage_basis: str
    note: str


#: The replacement relationships the governing registry supports.
#:
#: Both are DMI readings in one specific respect, stated here rather than
#: buried: the registry names the counterpart concept in prose
#: ("Secondary-residence rental equivalence, supplied by the Track-A shelter
#: rule") and does not carry the counterpart rule's identifier in a field.
#: Mapping that sentence onto a rule id is a reading. It is a narrow one --
#: there is exactly one Track-A secondary rental-equivalence rule -- and it is
#: validated against the registry at load time.
REPLACEMENT_GROUPS: tuple[ReplacementGroup, ...] = (
    ReplacementGroup(
        group_id="RG_PRIMARY_RESIDENCE_RENTAL_EQUIVALENCE",
        removal_rule_id=None,
        replacement_rule_id="TA_OWNER_RENTAL_EQUIVALENCE_PRIMARY_v0_1",
        linkage_basis="NO_REMOVAL_SIDE_DECLARED",
        note=(
            "The registry states that this rule removes nothing and that the "
            "outlays it displaces are removed by their own rules, on "
            "out-of-scope grounds, with no arithmetic depending on their "
            "amounts. A removal side is therefore not asserted here. Reading "
            "the primary owner outlays as this concept's removal side would "
            "create a linkage the registry explicitly declines to create."
        ),
    ),
    ReplacementGroup(
        group_id="RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE",
        removal_rule_id="RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        replacement_rule_id="TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1",
        linkage_basis="REGISTRY_DECLARED_IN_PROSE",
        note=(
            "Both sides are currently PENDING, so neither populates an "
            "effective amount. The linkage is recorded anyway: it is a fact "
            "about the rules that survives their being blocked, and losing it "
            "would make the two blockers look independent when they are not."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float_or_none(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


@dataclass(frozen=True)
class LedgerInputs:
    """Every committed artifact the ledger is built from.

    All of them are inside the repository. The LABSTAT extracts the accounting
    basis was originally derived from live outside it, at ``../dmi-data``, and
    are deliberately not read here: a canonical artifact that cannot be
    rebuilt from the repository alone is not canonical.
    """

    rules: CanonicalRules
    basis: Mapping[tuple[str, str], dict[str, str]]
    basis_meta: Mapping[str, dict[str, str]]
    mapping_audit: Mapping[str, dict[str, str]]
    provenance: Mapping[str, dict[str, str]]
    shelter_estimates: Mapping[tuple[str, str], dict[str, str]]
    usability_transitions: Mapping[str, str]
    addendum_uccs: frozenset[str]


def load_inputs(registry_dir: Path = REGISTRY_DIR) -> LedgerInputs:
    """Read every input and index it."""
    basis_rows = _read_csv(BASIS_PATH)
    basis: dict[tuple[str, str], dict[str, str]] = {}
    basis_meta: dict[str, dict[str, str]] = {}
    for row in basis_rows:
        label = row["population"]
        if label not in _BASIS_POPULATION:
            raise LedgerError(
                f"{BASIS_PATH.name}: unknown population {label!r}; the "
                f"canonical labels are {sorted(_BASIS_POPULATION)}"
            )
        key = (row["ucc"], _BASIS_POPULATION[label])
        if key in basis:
            raise LedgerError(f"{BASIS_PATH.name}: duplicate cell {key}")
        basis[key] = row
        basis_meta.setdefault(row["ucc"], row)

    mapping_audit = {r["ucc"]: r for r in _read_csv(MAPPING_AUDIT_PATH)}
    provenance = {r["ucc"]: r for r in _read_csv(PROVENANCE_ROSTER_PATH)}

    shelter_estimates: dict[tuple[str, str], dict[str, str]] = {}
    for row in _read_csv(SHELTER_ESTIMATES_PATH):
        if row["population"] not in POPULATIONS:
            raise LedgerError(
                f"{SHELTER_ESTIMATES_PATH.name}: unknown population "
                f"{row['population']!r}"
            )
        shelter_estimates[(row["ucc"], row["population"])] = row

    provenance_head = cstate.governing_version(
        "ucc_provenance_classes", registry_dir=registry_dir
    )
    payload = json.loads(
        (registry_dir / Path(provenance_head.relative_path).name).read_text(
            encoding="utf-8"
        )
    )
    addenda = frozenset(
        pair["published_ce_ucc"]
        for pair in payload["shelter_rental_equivalence_correspondence"]["pairs"]
    )

    return LedgerInputs(
        rules=cstate.load_canonical_rules(registry_dir=registry_dir),
        basis=basis,
        basis_meta=basis_meta,
        mapping_audit=mapping_audit,
        provenance=provenance,
        shelter_estimates=shelter_estimates,
        usability_transitions=cstate.current_pumd_usability(registry_dir=registry_dir),
        addendum_uccs=addenda,
    )


def _validate_replacement_groups(rules: CanonicalRules) -> None:
    """Fail if a declared group does not match the governing registry."""
    seen: set[str] = set()
    for group in REPLACEMENT_GROUPS:
        if group.group_id in seen:
            raise LedgerError(f"duplicate replacement group {group.group_id}")
        seen.add(group.group_id)
        replacement = rules.rule(group.replacement_rule_id)
        if replacement.final_status != "INTRODUCED":
            raise LedgerError(
                f"{group.group_id}: replacement rule "
                f"{group.replacement_rule_id} has final_status "
                f"{replacement.final_status!r}, not INTRODUCED"
            )
        if group.removal_rule_id is None:
            if group.linkage_basis != "NO_REMOVAL_SIDE_DECLARED":
                raise LedgerError(
                    f"{group.group_id}: no removal rule but linkage_basis is "
                    f"{group.linkage_basis!r}"
                )
            continue
        removal = rules.rule(group.removal_rule_id)
        if removal.rule_type != "REPLACE":
            raise LedgerError(
                f"{group.group_id}: removal rule {group.removal_rule_id} has "
                f"rule_type {removal.rule_type!r}, not REPLACE"
            )
        if not removal.replacement_concept:
            raise LedgerError(
                f"{group.group_id}: removal rule {group.removal_rule_id} "
                f"declares no replacement_concept, so the linkage recorded "
                f"here has no basis in the registry"
            )


def _group_for(rule_id: str | None) -> tuple[str | None, ReplacementRole]:
    if rule_id is None:
        return None, ReplacementRole.NOT_APPLICABLE
    for group in REPLACEMENT_GROUPS:
        if rule_id == group.replacement_rule_id:
            return group.group_id, ReplacementRole.REPLACEMENT
        if rule_id == group.removal_rule_id:
            return group.group_id, ReplacementRole.REMOVAL
    return None, ReplacementRole.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

LEDGER_COLUMNS: tuple[str, ...] = (
    # A. Identity
    "ucc",
    "population",
    "ucc_label",
    "ce_stub_parent",
    "domain_label",
    # B. Source and provenance
    "provenance_class",
    "source_class",
    "amount_source",
    "pumd_membership",
    "pumd_quantitative_usability",
    "cpi_adjustment_status",
    "concordance_elis",
    "dmi_node",
    "m1_mapping_status",
    # C. Source amount
    "source_amount_millions",
    "source_amount_status",
    "source_amount_rse_pct",
    "source_amount_high_rse_flag",
    # D. Governing rule state
    "governing_rule_id",
    "governing_registry_artifact_id",
    "rule_type",
    "review_status",
    "canonical_rule_state",
    "ucc_rule_role",
    "proposed_track_a_status",
    "effective_track_a_status",
    "rule_blocker_kind",
    "predecessor_rule_id",
    "pending_rule_effect_on_amount",
    # E. Track-A disposition and explicit amounts
    "track_a_disposition",
    "retained_amount",
    "excluded_amount",
    "removed_for_replacement_amount",
    "replacement_amount",
    "transformed_amount",
    "pending_amount",
    "open_amount",
    "withheld_amount",
    "replacement_group_id",
    "replacement_role",
    # Classification
    "normalization_state",
    "note",
)


@dataclass(frozen=True)
class LedgerRow:
    """One (UCC, population) cell of the canonical accounting ledger."""

    ucc: str
    population: str
    ucc_label: str
    ce_stub_parent: str
    domain_label: str
    provenance_class: str
    source_class: SourceClass
    amount_source: AmountSource
    pumd_membership: str
    pumd_quantitative_usability: str
    cpi_adjustment_status: str
    concordance_elis: str
    dmi_node: str
    m1_mapping_status: str
    source_amount_millions: float | None
    source_amount_status: AmountStatus
    source_amount_rse_pct: float | None
    source_amount_high_rse_flag: str
    governing_rule_id: str | None
    governing_registry_artifact_id: str | None
    rule_type: str | None
    review_status: str | None
    canonical_rule_state: CanonicalRuleState
    ucc_rule_role: UccRuleRole
    proposed_track_a_status: str | None
    effective_track_a_status: str | None
    rule_blocker_kind: str | None
    predecessor_rule_id: str | None
    pending_rule_effect_on_amount: PendingEffect
    track_a_disposition: Disposition
    retained_amount: float | None
    excluded_amount: float | None
    removed_for_replacement_amount: float | None
    replacement_amount: float | None
    transformed_amount: float | None
    pending_amount: float | None
    open_amount: float | None
    withheld_amount: float | None
    replacement_group_id: str | None
    replacement_role: ReplacementRole
    normalization_state: NormalizationState
    note: str

    @property
    def sort_key(self) -> tuple[str, int]:
        return (self.ucc, POPULATIONS.index(self.population))


def _disposition_for(
    *,
    resolution,
    amount_status: AmountStatus,
    m1_mapping_status: str,
    source_class: SourceClass,
) -> tuple[Disposition, PendingEffect]:
    """Decide the single accounting state of one cell.

    This is the only function that turns a rule state into a disposition, and
    it reads ``canonical_rule_state`` rather than the rule's declared
    ``final_status``. That is what makes "a PROPOSED rule has no effect" a
    property of the code rather than a convention someone has to remember.

    The pending branch is the subtle one. "No effect" means the amount goes
    where it would have gone had the rule never been written -- not into a
    holding bucket by default. For a UCC the CE->CPI concordance maps, that
    baseline is retention, and the governing registry says so explicitly for
    UCC 220121: not applying a partial-retention transform leaves the amount
    as recorded, while moving it to the pending bucket would remove it from
    the basis altogether and so assert more than the rule does. For a UCC the
    concordance does not map, there is no baseline to revert to, and the
    amount is genuinely held.
    """
    if source_class is SourceClass.TRANSFORMATION_DESTINATION:
        return Disposition.NOT_APPLICABLE, PendingEffect.NOT_APPLICABLE
    if source_class is SourceClass.PUBLISHED_ADDENDUM_OUTSIDE_BASIS:
        return Disposition.NOT_APPLICABLE, PendingEffect.NOT_APPLICABLE
    if resolution.is_withheld_by_rule:
        return Disposition.WITHHELD, PendingEffect.NOT_APPLICABLE

    state = resolution.canonical_rule_state
    if state is CanonicalRuleState.NOT_APPLICABLE:
        return Disposition.RETAINED, PendingEffect.NOT_APPLICABLE
    if state is CanonicalRuleState.CURRENT_OPEN:
        return Disposition.OPEN, PendingEffect.NOT_APPLICABLE
    if state is CanonicalRuleState.CURRENT_EFFECTIVE:
        proposed = resolution.proposed_track_a_status
        if proposed == "OUT_OF_SCOPE":
            return Disposition.EXCLUDED, PendingEffect.NOT_APPLICABLE
        if proposed == "INTRODUCED":
            return Disposition.REPLACEMENT, PendingEffect.NOT_APPLICABLE
        if proposed == "TRANSFORMED":
            if resolution.rule_type == "REPLACE":
                return (
                    Disposition.REMOVED_FOR_REPLACEMENT,
                    PendingEffect.NOT_APPLICABLE,
                )
            return Disposition.TRANSFORMED, PendingEffect.NOT_APPLICABLE
        raise LedgerError(
            f"UCC {resolution.ucc}: rule {resolution.governing_rule_id} is "
            f"effective with proposed status {proposed!r}, which this ledger "
            f"has no accounting state for"
        )
    if state is CanonicalRuleState.CURRENT_PENDING:
        if m1_mapping_status in ("DIRECT", "MULTI_SAME_NODE"):
            return (
                Disposition.RETAINED,
                PendingEffect.AMOUNT_REVERTS_TO_MAPPED_BASELINE,
            )
        return Disposition.PENDING, PendingEffect.AMOUNT_HELD_IN_PENDING_BUCKET
    raise LedgerError(
        f"UCC {resolution.ucc} resolves to state {state.value}, which may not "
        f"govern a ledger row"
    )


def _normalization_state(
    disposition: Disposition, amount_status: AmountStatus
) -> NormalizationState:
    if disposition is Disposition.NOT_APPLICABLE:
        return NormalizationState.NOT_APPLICABLE
    if disposition is Disposition.WITHHELD:
        if amount_status is AmountStatus.WITHHELD:
            return NormalizationState.BLOCKED_AMOUNT_NOT_ADMITTED
        return NormalizationState.BLOCKED_AMOUNT_UNAVAILABLE
    if disposition is Disposition.OPEN:
        return NormalizationState.BLOCKED_UNRESOLVED_METHODOLOGY
    if disposition is Disposition.PENDING:
        return NormalizationState.BLOCKED_PENDING_ADJUDICATION
    if disposition in (Disposition.EXCLUDED, Disposition.REMOVED_FOR_REPLACEMENT):
        return NormalizationState.EXCLUDED_FROM_BASIS
    if amount_status is not AmountStatus.OBSERVED:
        return NormalizationState.BLOCKED_AMOUNT_UNAVAILABLE
    return NormalizationState.ELIGIBLE


def _shelter_amount(row: Mapping[str, str] | None) -> tuple[float | None, str | None]:
    """Return (millions, cell_status) for a shelter estimate cell."""
    if row is None:
        return None, None
    return _float_or_none(row["annual_aggregate_millions"]), row["cell_status"]


def _build_row(
    *,
    ucc: str,
    population: str,
    inputs: LedgerInputs,
) -> LedgerRow:
    resolution = inputs.rules.resolve(ucc)
    prov = inputs.provenance.get(ucc, {})
    audit = inputs.mapping_audit.get(ucc, {})
    basis_cell = inputs.basis.get((ucc, population))
    basis_any = inputs.basis_meta.get(ucc)
    estimate = inputs.shelter_estimates.get((ucc, population))

    in_basis = basis_any is not None
    is_addendum = ucc in inputs.addendum_uccs
    is_output_only = resolution.role is UccRuleRole.OUTPUT_ONLY

    note_parts: list[str] = []

    if in_basis:
        source_class = SourceClass.PUBLISHED_CE_BASIS
        amount_source = AmountSource.LABSTAT_PUBLISHED
    elif is_addendum:
        source_class = SourceClass.PUBLISHED_ADDENDUM_OUTSIDE_BASIS
        amount_source = AmountSource.NOT_ADMISSIBLE_VALIDATION_ONLY
        note_parts.append(
            "Published CE addendum. The governing provenance registry states "
            "that no Track-A amount may be taken from it; it is a validation "
            "counterpart to the concordance-side code for the same concept."
        )
    elif is_output_only:
        source_class = SourceClass.TRANSFORMATION_DESTINATION
        amount_source = AmountSource.DERIVED_TRANSFORMATION
        note_parts.append(
            "Transformation destination. The amount is carried on the rows of "
            "the UCCs it is combined from, so that it appears once."
        )
    else:
        source_class = SourceClass.CONCORDANCE_ONLY_ESTIMATED
        usability = inputs.usability_transitions.get(
            ucc, prov.get("pumd_quantitative_usability", "NOT_ESTABLISHED")
        )
        amount_source = (
            AmountSource.PUMD_BENCHMARKED
            if usability == "BENCHMARKED"
            else AmountSource.PUMD_NOT_BENCHMARKED
        )

    # --- source amount -----------------------------------------------------
    amount: float | None = None
    rse: float | None = None
    high_rse = ""
    if source_class is SourceClass.PUBLISHED_CE_BASIS:
        if basis_cell is None:
            raise LedgerError(f"UCC {ucc} is in the basis but has no {population} row")
        amount = _float_or_none(basis_cell["aggregate_expenditure"])
        rse = _float_or_none(basis_cell["rse"])
        high_rse = basis_cell["high_rse"]
        status = AmountStatus.OBSERVED if amount is not None else AmountStatus.SUPPRESSED
        if status is AmountStatus.SUPPRESSED:
            note_parts.append(
                "BLS publishes this series and did not publish this cell. The "
                "amount is unknown and is not zero."
            )
    elif source_class is SourceClass.CONCORDANCE_ONLY_ESTIMATED:
        amount, cell_status = _shelter_amount(estimate)
        rse = (
            _float_or_none(estimate["relative_standard_error_pct"])
            if estimate is not None
            else None
        )
        high_rse = estimate["high_rse_informational_flag"] if estimate is not None else ""
        if amount is None:
            status = AmountStatus.NOT_AVAILABLE
            note_parts.append(
                f"No estimate exists for this cell (cell_status "
                f"{cell_status or 'ABSENT'}). The amount is unavailable and is "
                f"not zero."
            )
        elif resolution.is_withheld_by_rule:
            status = AmountStatus.WITHHELD
            note_parts.append(
                "An estimate exists and the governing rule withholds it. The "
                "amount is shown because withheld means not admitted, not "
                "unknown."
            )
        else:
            status = AmountStatus.OBSERVED
    else:
        status = AmountStatus.NOT_APPLICABLE

    m1_status = audit.get("mapping_status", "")

    disposition, pending_effect = _disposition_for(
        resolution=resolution,
        amount_status=status,
        m1_mapping_status=m1_status,
        source_class=source_class,
    )
    if pending_effect is PendingEffect.AMOUNT_REVERTS_TO_MAPPED_BASELINE:
        note_parts.append(
            "The governing rule is not in force. The UCC is mapped to a CPI "
            "entry-level item, so absent the rule the amount is simply "
            "retained; the retained figure is therefore an upper bound of what "
            "the rule would leave."
        )

    amounts: dict[str, float | None] = dict.fromkeys(AMOUNT_COLUMNS, None)
    target = AMOUNT_COLUMN_FOR.get(disposition)
    if target is not None and amount is not None:
        amounts[target] = amount

    group_id, role = _group_for(resolution.governing_rule_id)

    return LedgerRow(
        ucc=ucc,
        population=population,
        ucc_label=(
            (basis_any or {}).get("item_text")
            or audit.get("ucc_title")
            or prov.get("published_title")
            or prov.get("concordance_title")
            or ""
        ),
        ce_stub_parent=(basis_any or {}).get("subcategory_code", ""),
        domain_label=(basis_any or {}).get("domain_label", ""),
        provenance_class=prov.get("provenance_class", ""),
        source_class=source_class,
        amount_source=amount_source,
        pumd_membership=prov.get("pumd_membership", ""),
        pumd_quantitative_usability=inputs.usability_transitions.get(
            ucc, prov.get("pumd_quantitative_usability", "")
        ),
        cpi_adjustment_status=prov.get("cpi_adjustment_status", ""),
        concordance_elis=prov.get("elis", ""),
        dmi_node=prov.get("dmi_node", ""),
        m1_mapping_status=m1_status,
        source_amount_millions=amount,
        source_amount_status=status,
        source_amount_rse_pct=rse,
        source_amount_high_rse_flag=high_rse,
        governing_rule_id=resolution.governing_rule_id,
        governing_registry_artifact_id=resolution.governing_registry_artifact_id,
        rule_type=resolution.rule_type,
        review_status=resolution.review_status,
        canonical_rule_state=resolution.canonical_rule_state,
        ucc_rule_role=resolution.role,
        proposed_track_a_status=resolution.proposed_track_a_status,
        effective_track_a_status=resolution.effective_track_a_status,
        rule_blocker_kind=resolution.blocker_kind,
        predecessor_rule_id=(
            inputs.rules.rule(resolution.governing_rule_id).predecessor_rule_id
            if resolution.governing_rule_id
            else None
        ),
        pending_rule_effect_on_amount=pending_effect,
        track_a_disposition=disposition,
        retained_amount=amounts["retained_amount"],
        excluded_amount=amounts["excluded_amount"],
        removed_for_replacement_amount=amounts["removed_for_replacement_amount"],
        replacement_amount=amounts["replacement_amount"],
        transformed_amount=amounts["transformed_amount"],
        pending_amount=amounts["pending_amount"],
        open_amount=amounts["open_amount"],
        withheld_amount=amounts["withheld_amount"],
        replacement_group_id=group_id,
        replacement_role=role,
        normalization_state=_normalization_state(disposition, status),
        note=" ".join(note_parts),
    )


def ledger_universe(inputs: LedgerInputs) -> tuple[str, ...]:
    """Every UCC the ledger covers, sorted.

    Four sets, unioned and stated so the count is checkable: the accounting
    basis; every UCC a current rule claims as a source; every UCC a current
    rule names as an output; and the published CE addenda that duplicate the
    rental-equivalence concepts. The addenda carry no accounting amount and
    are included so that their absence reads as a recorded decision rather
    than as an omission.
    """
    return tuple(
        sorted(
            set(inputs.basis_meta)
            | set(inputs.rules.claimed_source_uccs)
            | set(inputs.rules.claimed_output_uccs)
            | set(inputs.addendum_uccs)
        )
    )


def build_ledger(inputs: LedgerInputs | None = None) -> tuple[LedgerRow, ...]:
    """Build every (UCC, population) row and validate the result."""
    inputs = inputs or load_inputs()
    _validate_replacement_groups(inputs.rules)
    rows = [
        _build_row(ucc=ucc, population=population, inputs=inputs)
        for ucc in ledger_universe(inputs)
        for population in POPULATIONS
    ]
    ordered = tuple(sorted(rows, key=lambda r: r.sort_key))
    validate_ledger(ordered)
    return ordered


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_ledger(rows: Sequence[LedgerRow]) -> None:
    """Every invariant the ledger claims, checked rather than assumed.

    Called on every build. It is also the unit under test for the mutation
    injections: each named mutation is applied to a row and this function must
    raise.
    """
    if not rows:
        raise LedgerError("the ledger is empty")

    seen: set[tuple[str, str]] = set()
    per_ucc: dict[str, set[str]] = {}
    for row in rows:
        key = (row.ucc, row.population)
        if key in seen:
            raise LedgerError(f"duplicate ledger row for {key}")
        seen.add(key)
        per_ucc.setdefault(row.ucc, set()).add(row.population)

    for ucc, populations in sorted(per_ucc.items()):
        if populations != set(POPULATIONS):
            missing = sorted(set(POPULATIONS) - populations)
            raise LedgerError(
                f"UCC {ucc} is missing populations {missing}; a population row "
                f"is never omitted merely because its value is unavailable"
            )

    for row in rows:
        _validate_row(row)

    _validate_replacement_consistency(rows)


def _validate_row(row: LedgerRow) -> None:
    where = f"{row.ucc}/{row.population}"

    # -- null is not zero ---------------------------------------------------
    if row.source_amount_status in _MUST_BE_BLANK:
        if row.source_amount_millions is not None:
            raise LedgerError(
                f"{where}: source_amount_status is "
                f"{row.source_amount_status.value} but an amount "
                f"{row.source_amount_millions!r} is present; that status means "
                f"there is no admitted amount and the cell must be blank"
            )
    elif row.source_amount_millions is None:
        raise LedgerError(
            f"{where}: source_amount_status is "
            f"{row.source_amount_status.value} but the amount is blank"
        )

    # -- exactly one amount column ------------------------------------------
    populated = [
        name for name in AMOUNT_COLUMNS if getattr(row, name) is not None
    ]
    if len(populated) > 1:
        raise LedgerError(
            f"{where}: {populated} are all populated; a cell has exactly one "
            f"accounting state and so at most one amount"
        )
    expected = AMOUNT_COLUMN_FOR.get(row.track_a_disposition)
    if populated:
        if populated[0] != expected:
            raise LedgerError(
                f"{where}: disposition {row.track_a_disposition.value} "
                f"populates {populated[0]}, but that disposition's column is "
                f"{expected!r}"
            )
        if row.source_amount_millions is None:
            raise LedgerError(
                f"{where}: {populated[0]} is populated while the source amount "
                f"is blank; an accounting amount cannot exist without a source "
                f"amount"
            )
        if row.source_amount_millions != getattr(row, populated[0]):
            raise LedgerError(
                f"{where}: {populated[0]} does not equal the source amount; "
                f"C2 moves amounts between buckets and never rescales them"
            )

    # -- proposed is not effective ------------------------------------------
    if row.track_a_disposition in _EFFECTIVE_ONLY_DISPOSITIONS:
        if row.canonical_rule_state is not CanonicalRuleState.CURRENT_EFFECTIVE:
            raise LedgerError(
                f"{where}: disposition {row.track_a_disposition.value} requires "
                f"a rule in force, but the governing rule "
                f"{row.governing_rule_id} is in state "
                f"{row.canonical_rule_state.value}"
            )
        if row.effective_track_a_status in (None, "UNRESOLVED"):
            raise LedgerError(
                f"{where}: disposition {row.track_a_disposition.value} with "
                f"effective_track_a_status "
                f"{row.effective_track_a_status!r}"
            )
    if row.canonical_rule_state is CanonicalRuleState.CURRENT_PENDING:
        if row.track_a_disposition in _EFFECTIVE_ONLY_DISPOSITIONS:
            raise LedgerError(
                f"{where}: the governing rule is PENDING and the disposition "
                f"is {row.track_a_disposition.value}; a proposed rule has no "
                f"effect"
            )
        if row.effective_track_a_status not in (None, "UNRESOLVED"):
            raise LedgerError(
                f"{where}: the governing rule is PENDING but its effective "
                f"status is {row.effective_track_a_status!r}"
            )

    # -- a UCC never resolves through a replaced rule ------------------------
    if row.canonical_rule_state not in cstate.RESOLVABLE_STATES:
        raise LedgerError(
            f"{where}: governing rule {row.governing_rule_id} is in state "
            f"{row.canonical_rule_state.value}, which may not govern a UCC"
        )

    # -- classification only -------------------------------------------------
    expected_norm = _normalization_state(
        row.track_a_disposition, row.source_amount_status
    )
    if row.normalization_state is not expected_norm:
        raise LedgerError(
            f"{where}: normalization_state {row.normalization_state.value} does "
            f"not follow from disposition {row.track_a_disposition.value} and "
            f"amount status {row.source_amount_status.value}"
        )


def _validate_replacement_consistency(rows: Sequence[LedgerRow]) -> None:
    """No group may both keep a source amount and introduce its replacement.

    Retaining X while introducing Y for the same concept counts the concept
    twice. The check is per population, because a group can be effective in
    one population and blocked in another.
    """
    by_group: dict[tuple[str, str], list[LedgerRow]] = {}
    for row in rows:
        if row.replacement_group_id is None:
            continue
        by_group.setdefault((row.replacement_group_id, row.population), []).append(row)

    for (group_id, population), members in sorted(by_group.items()):
        introduces = [r for r in members if r.replacement_amount is not None]
        if not introduces:
            continue
        retained = [
            r
            for r in members
            if r.replacement_role is ReplacementRole.REMOVAL
            and r.retained_amount is not None
        ]
        if retained:
            raise LedgerError(
                f"{group_id}/{population}: "
                f"{sorted(r.ucc for r in retained)} are retained while "
                f"{sorted(r.ucc for r in introduces)} introduce the concept "
                f"that replaces them; the concept would be counted twice"
            )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _row_values(row: LedgerRow) -> list[str]:
    return [_cell(getattr(row, name)) for name in LEDGER_COLUMNS]


def render_ledger(rows: Sequence[LedgerRow]) -> str:
    """The exact bytes of the ledger CSV.

    ``lineterminator`` is set explicitly. The default is CRLF, which the
    repository's ``.gitattributes`` would normalise on the way in, so the
    bytes written and the bytes committed would differ and a byte-for-byte
    determinism check would compare the wrong thing.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LEDGER_COLUMNS)
    for row in rows:
        writer.writerow(_row_values(row))
    return buffer.getvalue()


def write_ledger(rows: Sequence[LedgerRow], path: Path = LEDGER_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_ledger(rows), encoding="utf-8")
    return path


def summarise(rows: Sequence[LedgerRow]) -> dict:
    """Counts only.

    Row counts, not amount totals. Summing amounts by bucket is the first step
    of the reconciliation this task is explicitly not doing, and a total
    computed here would be read as one whether or not it was labelled.
    """

    def tally(attr: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            value = getattr(row, attr)
            key = value.value if isinstance(value, Enum) else str(value)
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items()))

    per_population: dict[str, dict[str, int]] = {}
    for population in POPULATIONS:
        subset = [r for r in rows if r.population == population]
        counts: dict[str, int] = {}
        for row in subset:
            key = row.source_amount_status.value
            counts[key] = counts.get(key, 0) + 1
        per_population[population] = dict(sorted(counts.items()))

    return {
        "artifact_id": "CANONICAL_LEDGER_SUMMARY_2024",
        "counts_are_rows_not_amounts": (
            "Every number below counts rows. No amount is summed anywhere in "
            "C1 or C2. Population-level reconciliation of amounts is a later "
            "task, and a total published here would be read as its answer."
        ),
        "distinct_uccs": len({r.ucc for r in rows}),
        "populations": list(POPULATIONS),
        "row_count": len(rows),
        "rows_by_amount_source": tally("amount_source"),
        "rows_by_canonical_rule_state": tally("canonical_rule_state"),
        "rows_by_disposition": tally("track_a_disposition"),
        "rows_by_normalization_state": tally("normalization_state"),
        "rows_by_pending_effect": tally("pending_rule_effect_on_amount"),
        "rows_by_replacement_role": tally("replacement_role"),
        "rows_by_source_amount_status": tally("source_amount_status"),
        "rows_by_source_class": tally("source_class"),
        "source_amount_status_by_population": per_population,
        "status": "RESEARCH_ONLY",
    }


def build_schema() -> dict:
    """The machine-readable contract the ledger satisfies."""
    field_types = {f.name: f.type for f in fields(LedgerRow)}
    unknown = [c for c in LEDGER_COLUMNS if c not in field_types]
    if unknown:
        raise LedgerError(f"columns with no field on LedgerRow: {unknown}")
    missing = [f for f in field_types if f not in LEDGER_COLUMNS]
    if missing:
        raise LedgerError(f"fields on LedgerRow with no column: {missing}")

    return {
        "amount_columns": list(AMOUNT_COLUMNS),
        "amount_column_by_disposition": {
            d.value: AMOUNT_COLUMN_FOR.get(d) for d in Disposition
        },
        "artifact_id": SCHEMA_ARTIFACT_ID,
        "columns": [
            {"name": name, "type": str(field_types[name])} for name in LEDGER_COLUMNS
        ],
        "grain": "one row per (ucc, population)",
        "invariants": [
            "Every UCC has exactly six rows, one per population, whether or "
            "not an amount exists for it.",
            "At most one amount column is non-blank on any row, and it is the "
            "column the row's disposition maps to.",
            "An accounting amount always equals the row's source amount. C2 "
            "moves amounts between buckets and never rescales them.",
            "A rule in state CURRENT_PENDING may never produce an EXCLUDED, "
            "REMOVED_FOR_REPLACEMENT, REPLACEMENT or TRANSFORMED disposition.",
            "A UCC never resolves through a SUPERSEDED or HISTORICAL_ONLY "
            "rule.",
            "A blank amount is not zero. Under statuses SUPPRESSED, "
            "NOT_AVAILABLE and NOT_APPLICABLE the amount column must be "
            "blank; under OBSERVED and WITHHELD it must not be.",
            "Within one replacement group and one population, no removal-side "
            "UCC may be retained while any UCC introduces the replacement.",
            "normalization_state follows from the disposition and the amount "
            "status and is a classification only.",
        ],
        "milestone": "Detailed Inflation Substrate v0.1, task C2",
        "null_semantics": {
            "blank": (
                "The amount is unavailable, suppressed, withheld from "
                "production or undefined for this UCC. Which of those it is "
                "is in source_amount_status. Blank is never a stand-in for "
                "zero."
            ),
            "regression_case": (
                "UCC 910106 carries both encodings in the same column: Q1 is "
                "blank at status NOT_AVAILABLE because no consumer unit in "
                "the quintile reported the item, and the other five "
                "populations carry numeric amounts at status WITHHELD. Coerce "
                "the Q1 blank to zero and the ledger stops saying that a "
                "measurement is missing."
            ),
            "zero": "BLS or the estimator observed zero.",
        },
        "output_path": "data/research/detailed_inflation/canonical_substrate_2024/ucc_population_accounting_ledger.csv",
        "row_order": (
            "UCC ascending as a string, then population in the fixed order "
            "ALL_CU, Q1, Q2, Q3, Q4, Q5. Nothing depends on dictionary or "
            "filesystem iteration order."
        ),
        "scope": (
            "Research only. This ledger records where each source amount "
            "currently sits. It computes no weight, no share and no index, "
            "and it reconciles nothing."
        ),
        "status": "RESEARCH_ONLY",
        "vocabularies": {
            "AmountSource": _enum_doc(AmountSource),
            "AmountStatus": _enum_doc(AmountStatus),
            "Disposition": _enum_doc(Disposition),
            "NormalizationState": _enum_doc(NormalizationState),
            "PendingEffect": _enum_doc(PendingEffect),
            "ReplacementRole": _enum_doc(ReplacementRole),
            "SourceClass": _enum_doc(SourceClass),
        },
        "replacement_groups": [
            {
                "group_id": g.group_id,
                "linkage_basis": g.linkage_basis,
                "note": g.note,
                "removal_rule_id": g.removal_rule_id,
                "replacement_rule_id": g.replacement_rule_id,
            }
            for g in REPLACEMENT_GROUPS
        ],
        "version": SCHEMA_VERSION,
    }


#: Semantics of each vocabulary member, written out here because a CSV consumer
#: cannot read a Python docstring. Kept beside the enum so the two go stale
#: together or not at all; ``test_every_vocabulary_member_is_documented``
#: fails if a member is added without a line here.
_ENUM_SEMANTICS: Mapping[str, Mapping[str, str]] = {
    "SourceClass": {
        "PUBLISHED_CE_BASIS": (
            "A member of the 2024 active numeric-UCC accounting basis, with a "
            "published LABSTAT aggregate."
        ),
        "CONCORDANCE_ONLY_ESTIMATED": (
            "Named by the CE->CPI concordance and absent from the published CE "
            "item file. No published aggregate exists, so any amount is "
            "estimated from microdata."
        ),
        "TRANSFORMATION_DESTINATION": (
            "A destination a rule combines other UCCs into. It has no source "
            "amount of its own."
        ),
        "PUBLISHED_ADDENDUM_OUTSIDE_BASIS": (
            "A published CE addendum the accounting basis excludes to avoid "
            "double counting the concept it duplicates."
        ),
    },
    "AmountSource": {
        "LABSTAT_PUBLISHED": "Published by BLS in the LABSTAT CE aggregate series.",
        "PUMD_BENCHMARKED": (
            "Estimated from the CE Public Use Microdata by an estimator whose "
            "quantitative usability is BENCHMARKED for this UCC."
        ),
        "PUMD_NOT_BENCHMARKED": (
            "Estimated by the same estimator on a UCC whose quantitative "
            "usability is still NOT_ESTABLISHED. Method validity is a property "
            "of the cell as well as of the procedure."
        ),
        "DERIVED_TRANSFORMATION": (
            "Produced by applying a rule's transformation to other UCCs' "
            "amounts."
        ),
        "NOT_ADMISSIBLE_VALIDATION_ONLY": (
            "An amount exists and the governing registry forbids taking a "
            "Track-A figure from it."
        ),
        "NO_AMOUNT_AVAILABLE": "No amount exists from any admitted source.",
    },
    "AmountStatus": {
        "OBSERVED": (
            "A numeric amount exists and is admitted. Zero under this status "
            "is a genuine observed zero."
        ),
        "SUPPRESSED": "BLS publishes the series and did not publish this cell.",
        "WITHHELD": (
            "An amount was produced and is not admitted because it failed a "
            "declared quality gate. The amount is still shown."
        ),
        "NOT_AVAILABLE": "No amount was produced at all.",
        "NOT_APPLICABLE": "No source amount is defined for this UCC.",
    },
    "Disposition": {
        "RETAINED": "Stays in the CPI-comparable basis at its source value.",
        "EXCLUDED": (
            "Leaves because the CPI does not price it. Nothing replaces it."
        ),
        "REMOVED_FOR_REPLACEMENT": (
            "Leaves because a different concept prices the same thing. The "
            "replacement is a separate row and is not assumed equal."
        ),
        "REPLACEMENT": (
            "An amount entering under a concept that replaces removed source "
            "amounts."
        ),
        "TRANSFORMED": (
            "The amount stays, reassigned or combined, under an effective "
            "rule."
        ),
        "PENDING": (
            "The governing rule proposes a disposition that is not in force, "
            "and no rule-free baseline exists to fall back to."
        ),
        "OPEN": "No disposition is proposed at all.",
        "WITHHELD": (
            "An amount that would belong here is not admitted because its "
            "estimate failed adjudication."
        ),
        "NOT_APPLICABLE": "No Track-A disposition applies to this row.",
    },
    "PendingEffect": {
        "AMOUNT_HELD_IN_PENDING_BUCKET": (
            "No rule-free baseline exists, so the amount is held: neither in "
            "the basis nor removed from it."
        ),
        "AMOUNT_REVERTS_TO_MAPPED_BASELINE": (
            "The UCC is mapped to a CPI entry-level item, so absent the rule "
            "the amount is retained. The retained figure is an upper bound of "
            "what the rule would leave."
        ),
        "NOT_APPLICABLE": "The governing rule is in force, or there is none.",
    },
    "NormalizationState": {
        "ELIGIBLE": "The amount is in the basis under a rule in force.",
        "EXCLUDED_FROM_BASIS": "The amount is deliberately outside the basis.",
        "BLOCKED_PENDING_ADJUDICATION": (
            "A disposition is proposed and not in force."
        ),
        "BLOCKED_UNRESOLVED_METHODOLOGY": "No disposition is proposed.",
        "BLOCKED_AMOUNT_UNAVAILABLE": (
            "A disposition exists but the amount does not."
        ),
        "BLOCKED_AMOUNT_NOT_ADMITTED": (
            "The amount exists and is not admitted, because its estimate "
            "failed a declared quality gate. Distinct from "
            "BLOCKED_AMOUNT_UNAVAILABLE: one is unblocked by a measurement, "
            "the other by a better estimate."
        ),
        "NOT_APPLICABLE": "No normalisation question arises for this row.",
    },
    "ReplacementRole": {
        "REMOVAL": "The row's amount is the one a replacement would displace.",
        "REPLACEMENT": "The row's amount is the one that would displace it.",
        "NOT_APPLICABLE": "The row is in no replacement group.",
    },
}


def _enum_doc(enum_cls: type[Enum]) -> dict[str, str]:
    table = _ENUM_SEMANTICS[enum_cls.__name__]
    missing = [m.name for m in enum_cls if m.name not in table]
    if missing:
        raise LedgerError(
            f"{enum_cls.__name__}: members {missing} have no documented "
            f"semantics; a CSV consumer cannot read a docstring"
        )
    return {m.value: table[m.name] for m in enum_cls}


def render_schema() -> str:
    """The exact bytes of the schema."""
    return json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"


def write_schema(path: Path = SCHEMA_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_schema(), encoding="utf-8")
    return path


def render_summary(rows: Sequence[LedgerRow]) -> str:
    """The exact bytes of the summary."""
    return json.dumps(summarise(rows), indent=2, sort_keys=True) + "\n"


def write_summary(rows: Sequence[LedgerRow], path: Path = LEDGER_SUMMARY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_summary(rows), encoding="utf-8")
    return path


__all__ = [
    "AMOUNT_COLUMNS",
    "AMOUNT_COLUMN_FOR",
    "AmountSource",
    "AmountStatus",
    "Disposition",
    "LEDGER_COLUMNS",
    "LEDGER_PATH",
    "LedgerError",
    "LedgerInputs",
    "LedgerRow",
    "NormalizationState",
    "PendingEffect",
    "REPLACEMENT_GROUPS",
    "SCHEMA_PATH",
    "ReplacementGroup",
    "ReplacementRole",
    "SourceClass",
    "build_ledger",
    "build_schema",
    "ledger_universe",
    "load_inputs",
    "render_ledger",
    "render_schema",
    "render_summary",
    "summarise",
    "validate_ledger",
    "write_ledger",
    "write_schema",
    "write_summary",
]
