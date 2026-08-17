"""CE->CPI scope-rule registry loader and validator.

Detailed Inflation Substrate v0.1, Milestone 2 (spec sections 5, 12, 13, 17).

This module loads ``registry/research/ce_cpi_scope_rules_v0_1.json`` and
validates it strictly. It holds *substrate metadata*, not Core logic. Nothing
here is wired into ``dmi_calculator`` or any operational specification, and
Core DMI remains withdrawn and unimplemented.

Design constraints taken directly from the specification:

* Section 5.2 -- ``OUT_OF_SCOPE`` requires positive authoritative evidence.
  The loader therefore refuses to accept an ``EXCLUDE`` rule that cites no
  authoritative source.
* Section 5.3 -- a classification must never be invented to drive unresolved
  expenditure to zero. Candidate destinations recorded against ``UNRESOLVED``
  members are research leads only; :meth:`ScopeRule.resolved_node_for` never
  returns them.
* Section 13 -- every rule carries the mandated metadata fields.
* Section 6.5 -- rules whose effect is coupled to the Track-A shelter
  transformation are marked ``PROPOSED`` and are not applied on their own.

There are no silent defaults. Every failure raises.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional, Sequence

from .taxonomy import ELI_RE, MappingStatus

REGISTRY_DIR = Path(__file__).resolve().parents[2] / "registry" / "research"
SCOPE_RULES_PATH = REGISTRY_DIR / "ce_cpi_scope_rules_v0_1.json"

#: Structural form of a CE Universal Classification Code.
UCC_RE = re.compile(r"^[0-9]{6}$")


class ScopeRuleError(Exception):
    """The scope-rule registry is malformed or internally inconsistent."""


class UnknownUccError(ScopeRuleError):
    """A UCC was requested that no rule in the registry claims."""


class RuleType(str, Enum):
    """Transformation kinds permitted by spec section 13."""

    EXCLUDE = "EXCLUDE"
    REPLACE = "REPLACE"
    COMBINE = "COMBINE"
    REASSIGN = "REASSIGN"
    RETAIN = "RETAIN"
    UNRESOLVED = "UNRESOLVED"


class ReviewStatus(str, Enum):
    """Whether a rule may be applied on its own."""

    ACCEPTED = "ACCEPTED"
    PROPOSED = "PROPOSED"
    OPEN = "OPEN"


class EvidenceStrength(str, Enum):
    """Evidence grading defined in the registry preamble."""

    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class SuppressionStatus(str, Enum):
    """Spec section 16 suppression exposure classes."""

    NONE = "NONE"
    IMMATERIAL = "IMMATERIAL"
    MATERIAL = "MATERIAL"


class TrackBTreatment(str, Enum):
    """Spec section 7 household-payments shelter classifications.

    Track B is a research comparison only. Spec section 3.3 forbids reading it
    as authorization to change Baseline, and section 7 forbids computing an
    index from it in this milestone.
    """

    NOT_APPLICABLE = "NOT_APPLICABLE"
    RETAIN_CURRENT_PAYMENT = "RETAIN_CURRENT_PAYMENT"
    EXCLUDE_CAPITAL_ACQUISITION = "EXCLUDE_CAPITAL_ACQUISITION"
    UNRESOLVED = "UNRESOLVED"


#: Track-B treatments that keep expenditure inside a payments-based measure.
TRACK_B_RETAINING_TREATMENTS = frozenset({TrackBTreatment.RETAIN_CURRENT_PAYMENT})

#: The three dispositions spec section 16 permits for a transformation that
#: relies materially on suppressed data.
_SUPPRESSION_DISPOSITIONS = frozenset(
    {"ALTERNATIVE_SOURCE", "AGGREGATE_TO_STABLE_LEVEL", "BLOCKED"}
)


#: Rule type implies final status. Stated here so the registry is validated
#: against the specification rather than trusted to be self-consistent.
RULE_TYPE_TO_FINAL_STATUS = {
    RuleType.EXCLUDE: MappingStatus.OUT_OF_SCOPE,
    RuleType.REPLACE: MappingStatus.TRANSFORMED,
    RuleType.COMBINE: MappingStatus.TRANSFORMED,
    RuleType.REASSIGN: MappingStatus.TRANSFORMED,
    RuleType.RETAIN: MappingStatus.DIRECT,
    RuleType.UNRESOLVED: MappingStatus.UNRESOLVED,
}

#: Rule types that remove expenditure from the CE-outlay basis without
#: assigning it to a DMI computation node.
_NODE_LESS_RULE_TYPES = frozenset({RuleType.EXCLUDE, RuleType.UNRESOLVED})

_REQUIRED_RULE_FIELDS = (
    "rule_id",
    "version",
    "track",
    "source_uccs",
    "final_status",
    "rule_type",
    "output_uccs",
    "output_node",
    "authoritative_basis",
    "source_document_titles",
    "evidence_notes",
    "transformation_formula",
    "assumptions",
    "materiality_all_cu",
    "materiality_by_quintile",
    "evidence_strength",
    "suppression_status",
    "review_status",
    "track_b",
)

_QUINTILES = ("Q1", "Q2", "Q3", "Q4", "Q5")


@dataclass(frozen=True)
class ScopeRule:
    """One CE->CPI scope treatment covering one or more exception UCCs."""

    rule_id: str
    version: str
    track: str
    source_uccs: tuple
    rule_type: RuleType
    final_status: MappingStatus
    output_uccs: tuple
    output_node: object
    authoritative_basis: tuple
    source_document_titles: tuple
    evidence_notes: str
    transformation_formula: Optional[str]
    assumptions: tuple
    materiality_all_cu: float
    materiality_by_quintile: Mapping
    evidence_strength: EvidenceStrength
    suppression_status: SuppressionStatus
    suppression_disposition: Optional[str]
    suppression_note: Optional[str]
    review_status: ReviewStatus
    track_b_treatment: TrackBTreatment
    track_b_treatment_by_ucc: Mapping
    track_b_rationale: str
    track_b_price_index_needed: tuple
    output_eli: Optional[str] = None
    members: tuple = ()
    validation_test: Optional[str] = None
    review_blocker: Optional[str] = None

    def track_b_for(self, ucc: str) -> TrackBTreatment:
        """Return the section 7 payments-concept treatment for ``ucc``."""
        if ucc not in self.source_uccs:
            raise UnknownUccError(f"{ucc} is not claimed by rule {self.rule_id}")
        return self.track_b_treatment_by_ucc.get(ucc, self.track_b_treatment)

    @property
    def is_applicable(self) -> bool:
        """Whether this rule may be applied without a further gate.

        ``PROPOSED`` rules are shelter-coupled and take effect only jointly
        with the Track-A rental-equivalence rule (spec section 6.5).
        ``OPEN`` rules are unresolved and are never applied.
        """
        return self.review_status is ReviewStatus.ACCEPTED

    def resolved_node_for(self, ucc: str) -> Optional[str]:
        """Return the DMI computation node for ``ucc``, or ``None``.

        ``None`` means this rule assigns no node: the expenditure is either
        out of scope or unresolved. Candidate nodes recorded against
        ``UNRESOLVED`` members are research leads and are deliberately not
        returned here (spec section 5.3).
        """
        if ucc not in self.source_uccs:
            raise UnknownUccError(f"{ucc} is not claimed by rule {self.rule_id}")
        if self.rule_type in _NODE_LESS_RULE_TYPES:
            return None
        if isinstance(self.output_node, dict):
            try:
                return self.output_node[ucc]
            except KeyError:
                raise ScopeRuleError(
                    f"rule {self.rule_id} has a per-UCC output_node map that "
                    f"omits {ucc}"
                ) from None
        return self.output_node


@dataclass(frozen=True)
class ScopeRuleRegistry:
    """The validated set of scope rules, indexed by UCC."""

    artifact_id: str
    version: str
    rules: tuple
    coverage: Mapping
    sources: Mapping
    structural_evidence: Mapping
    _by_ucc: Mapping

    def rule_for(self, ucc: str) -> ScopeRule:
        """Return the single rule claiming ``ucc``."""
        try:
            return self._by_ucc[ucc]
        except KeyError:
            raise UnknownUccError(
                f"no scope rule claims UCC {ucc}; the registry covers "
                f"{len(self._by_ucc)} UCCs"
            ) from None

    def rule_by_id(self, rule_id: str) -> ScopeRule:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        raise ScopeRuleError(f"no rule with id {rule_id}")

    @property
    def covered_uccs(self) -> frozenset:
        return frozenset(self._by_ucc)

    def rules_of_type(self, rule_type: RuleType) -> tuple:
        return tuple(r for r in self.rules if r.rule_type is rule_type)

    def materiality_by_final_status(self, population: str = "All Consumer Units") -> dict:
        """Sum published materiality by final status for one population."""
        totals: dict = {}
        for rule in self.rules:
            if population == "All Consumer Units":
                amount = rule.materiality_all_cu
            else:
                if population not in _QUINTILES:
                    raise ScopeRuleError(f"unknown population {population!r}")
                amount = rule.materiality_by_quintile[population]
            key = rule.final_status.value
            totals[key] = totals.get(key, 0.0) + amount
        return totals


def _require(mapping: Mapping, field: str, context: str):
    if field not in mapping:
        raise ScopeRuleError(f"{context}: missing required field {field!r}")
    return mapping[field]


def _validate_rule(raw: Mapping) -> ScopeRule:
    rule_id = raw.get("rule_id", "<no rule_id>")
    context = f"rule {rule_id}"

    for field in _REQUIRED_RULE_FIELDS:
        _require(raw, field, context)

    try:
        rule_type = RuleType(raw["rule_type"])
    except ValueError:
        raise ScopeRuleError(
            f"{context}: unknown rule_type {raw['rule_type']!r}"
        ) from None
    try:
        final_status = MappingStatus(raw["final_status"])
    except ValueError:
        raise ScopeRuleError(
            f"{context}: unknown final_status {raw['final_status']!r}"
        ) from None
    try:
        evidence_strength = EvidenceStrength(raw["evidence_strength"])
        suppression_status = SuppressionStatus(raw["suppression_status"])
        review_status = ReviewStatus(raw["review_status"])
    except ValueError as exc:
        raise ScopeRuleError(f"{context}: {exc}") from None

    # Section 16: a transformation that relies materially on suppressed data
    # must resolve that reliance explicitly rather than proceeding quietly.
    suppression_disposition = raw.get("suppression_disposition")
    if suppression_status is SuppressionStatus.MATERIAL:
        if suppression_disposition not in _SUPPRESSION_DISPOSITIONS:
            raise ScopeRuleError(
                f"{context}: suppression_status MATERIAL requires a "
                f"suppression_disposition in {sorted(_SUPPRESSION_DISPOSITIONS)}; "
                f"got {suppression_disposition!r}"
            )
    elif suppression_disposition is not None:
        raise ScopeRuleError(
            f"{context}: suppression_disposition is only meaningful when "
            f"suppression_status is MATERIAL"
        )
    if suppression_status is not SuppressionStatus.NONE and not raw.get(
        "suppression_note"
    ):
        raise ScopeRuleError(
            f"{context}: a rule exposed to suppressed data must record a "
            f"suppression_note stating the bound"
        )

    expected_status = RULE_TYPE_TO_FINAL_STATUS[rule_type]
    if final_status is not expected_status:
        raise ScopeRuleError(
            f"{context}: rule_type {rule_type.value} implies final_status "
            f"{expected_status.value}, but the registry declares "
            f"{final_status.value}"
        )

    source_uccs = tuple(raw["source_uccs"])
    if not source_uccs:
        raise ScopeRuleError(f"{context}: source_uccs is empty")
    for ucc in source_uccs:
        if not UCC_RE.match(ucc):
            raise ScopeRuleError(f"{context}: {ucc!r} is not a 6-digit UCC")
    if len(set(source_uccs)) != len(source_uccs):
        raise ScopeRuleError(f"{context}: source_uccs contains duplicates")

    authoritative_basis = tuple(raw["authoritative_basis"])

    # Spec section 5.2: absence of a concordance row is not evidence. An
    # EXCLUDE rule must cite at least one authoritative source.
    if rule_type is RuleType.EXCLUDE and not authoritative_basis:
        raise ScopeRuleError(
            f"{context}: an EXCLUDE rule must cite at least one authoritative "
            f"source (spec section 5.2)"
        )
    if rule_type is RuleType.UNRESOLVED and authoritative_basis:
        raise ScopeRuleError(
            f"{context}: an UNRESOLVED rule must not cite an authoritative "
            f"basis; if a basis exists the rule is not unresolved"
        )

    # Spec section 5.2: WEAK evidence may never support an exclusion.
    if rule_type is RuleType.EXCLUDE and evidence_strength is EvidenceStrength.WEAK:
        raise ScopeRuleError(
            f"{context}: WEAK evidence cannot support OUT_OF_SCOPE "
            f"(spec section 5.2)"
        )

    output_node = raw["output_node"]
    if rule_type in _NODE_LESS_RULE_TYPES:
        if output_node is not None:
            raise ScopeRuleError(
                f"{context}: rule_type {rule_type.value} must have a null "
                f"output_node"
            )
    else:
        if output_node is None:
            raise ScopeRuleError(
                f"{context}: rule_type {rule_type.value} requires an output_node"
            )
        if isinstance(output_node, dict):
            missing = set(source_uccs) - set(output_node)
            if missing:
                raise ScopeRuleError(
                    f"{context}: per-UCC output_node map omits "
                    f"{sorted(missing)}"
                )
            extra = set(output_node) - set(source_uccs)
            if extra:
                raise ScopeRuleError(
                    f"{context}: per-UCC output_node map has entries for UCCs "
                    f"the rule does not claim: {sorted(extra)}"
                )

    output_eli = raw.get("output_eli")
    if output_eli is not None and not ELI_RE.match(output_eli):
        raise ScopeRuleError(f"{context}: {output_eli!r} is not a valid ELI code")

    if rule_type is RuleType.COMBINE and not raw.get("transformation_formula"):
        raise ScopeRuleError(
            f"{context}: a COMBINE rule must state a transformation_formula "
            f"(spec section 5.1)"
        )

    if review_status is ReviewStatus.PROPOSED and not raw.get("review_blocker"):
        raise ScopeRuleError(
            f"{context}: a PROPOSED rule must state its review_blocker"
        )

    materiality = raw["materiality_by_quintile"]
    missing_q = set(_QUINTILES) - set(materiality)
    if missing_q:
        raise ScopeRuleError(
            f"{context}: materiality_by_quintile omits {sorted(missing_q)}"
        )

    members = tuple(raw.get("members", ()))
    if rule_type is RuleType.UNRESOLVED:
        member_uccs = {m["ucc"] for m in members}
        if member_uccs != set(source_uccs):
            raise ScopeRuleError(
                f"{context}: every UNRESOLVED source UCC must have a member "
                f"entry documenting why it is unresolved; mismatch on "
                f"{sorted(member_uccs ^ set(source_uccs))}"
            )

    track_b = _validate_track_b(raw["track_b"], source_uccs, context)

    return ScopeRule(
        rule_id=rule_id,
        version=raw["version"],
        track=raw["track"],
        source_uccs=source_uccs,
        rule_type=rule_type,
        final_status=final_status,
        output_uccs=tuple(raw["output_uccs"]),
        output_node=output_node,
        authoritative_basis=authoritative_basis,
        source_document_titles=tuple(raw["source_document_titles"]),
        evidence_notes=raw["evidence_notes"],
        transformation_formula=raw["transformation_formula"],
        assumptions=tuple(raw["assumptions"]),
        materiality_all_cu=float(raw["materiality_all_cu"]),
        materiality_by_quintile=dict(materiality),
        evidence_strength=evidence_strength,
        suppression_status=suppression_status,
        suppression_disposition=suppression_disposition,
        suppression_note=raw.get("suppression_note"),
        review_status=review_status,
        output_eli=output_eli,
        members=members,
        validation_test=raw.get("validation_test"),
        review_blocker=raw.get("review_blocker"),
        track_b_treatment=track_b[0],
        track_b_treatment_by_ucc=track_b[1],
        track_b_rationale=track_b[2],
        track_b_price_index_needed=track_b[3],
    )


def _validate_track_b(raw: Mapping, source_uccs: tuple, context: str):
    """Validate the spec section 7 Track-B block of one rule."""
    try:
        treatment = TrackBTreatment(_require(raw, "treatment", context))
    except ValueError:
        raise ScopeRuleError(
            f"{context}: unknown track_b treatment {raw.get('treatment')!r}"
        ) from None

    overrides = {}
    for ucc, value in raw.get("treatment_by_ucc", {}).items():
        if ucc not in source_uccs:
            raise ScopeRuleError(
                f"{context}: track_b.treatment_by_ucc names {ucc}, which the "
                f"rule does not claim"
            )
        try:
            overrides[ucc] = TrackBTreatment(value)
        except ValueError:
            raise ScopeRuleError(
                f"{context}: unknown track_b treatment {value!r} for {ucc}"
            ) from None

    rationale = _require(raw, "rationale", context)
    price_index = tuple(raw.get("price_index_needed", ()))

    # Section 7 requires Track B to identify the price indexes a payments
    # measure would need. A rule that retains expenditure but names no price
    # source has skipped that requirement.
    retaining = {treatment, *overrides.values()} & TRACK_B_RETAINING_TREATMENTS
    if retaining and not price_index:
        raise ScopeRuleError(
            f"{context}: track_b retains expenditure but names no "
            f"price_index_needed entry, which spec section 7 requires"
        )
    if not retaining and price_index:
        raise ScopeRuleError(
            f"{context}: track_b retains no expenditure yet names "
            f"price_index_needed entries"
        )
    return treatment, overrides, rationale, price_index


def load_scope_rules(path: Path = SCOPE_RULES_PATH) -> ScopeRuleRegistry:
    """Load and strictly validate the scope-rule registry.

    Raises :class:`ScopeRuleError` on any structural problem. There is no
    lenient mode.
    """
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)

    for field in ("artifact_id", "version", "rules", "coverage", "sources"):
        _require(payload, field, f"registry {path.name}")

    if payload.get("status") != "RESEARCH_ONLY":
        raise ScopeRuleError(
            f"registry {path.name}: status must be RESEARCH_ONLY, got "
            f"{payload.get('status')!r}"
        )

    rules = tuple(_validate_rule(raw) for raw in payload["rules"])

    by_ucc: dict = {}
    for rule in rules:
        for ucc in rule.source_uccs:
            if ucc in by_ucc:
                raise ScopeRuleError(
                    f"UCC {ucc} is claimed by both {by_ucc[ucc].rule_id} and "
                    f"{rule.rule_id}; each UCC must be claimed exactly once"
                )
            by_ucc[ucc] = rule

    rule_ids = [r.rule_id for r in rules]
    if len(set(rule_ids)) != len(rule_ids):
        raise ScopeRuleError("duplicate rule_id in registry")

    coverage = payload["coverage"]
    declared = coverage.get("uccs_claimed_by_rules")
    if declared != len(by_ucc):
        raise ScopeRuleError(
            f"coverage declares {declared} claimed UCCs but the rules claim "
            f"{len(by_ucc)}"
        )

    _validate_reconciliation(rules, coverage)

    return ScopeRuleRegistry(
        artifact_id=payload["artifact_id"],
        version=payload["version"],
        rules=rules,
        coverage=coverage,
        sources=payload["sources"],
        structural_evidence=payload.get("structural_evidence", {}),
        _by_ucc=by_ucc,
    )


def _validate_reconciliation(rules: Sequence, coverage: Mapping) -> None:
    """Check the registry's own declared reconciliation identity.

    Spec section 19.1: no expenditure may disappear.
    """
    rec = coverage.get("reconciliation_all_cu")
    if rec is None:
        raise ScopeRuleError("coverage omits reconciliation_all_cu")

    observed = {
        "transformed_reassign": 0.0,
        "transformed_combine": 0.0,
        "transformed_replace": 0.0,
        "out_of_scope": 0.0,
        "unresolved": 0.0,
    }
    bucket = {
        RuleType.REASSIGN: "transformed_reassign",
        RuleType.COMBINE: "transformed_combine",
        RuleType.REPLACE: "transformed_replace",
        RuleType.EXCLUDE: "out_of_scope",
        RuleType.UNRESOLVED: "unresolved",
    }
    for rule in rules:
        if rule.rule_type is RuleType.RETAIN:
            continue
        observed[bucket[rule.rule_type]] += rule.materiality_all_cu

    for key, value in observed.items():
        declared = rec.get(key)
        if declared is None:
            raise ScopeRuleError(f"reconciliation_all_cu omits {key}")
        if abs(float(declared) - value) > 0.5:
            raise ScopeRuleError(
                f"reconciliation_all_cu.{key} declares {declared} but the "
                f"rules sum to {value}"
            )

    total = sum(observed.values())
    exception_total = float(rec["exception_total"])
    if abs(total - exception_total) > 0.5:
        raise ScopeRuleError(
            f"scope rules sum to {total} but the Milestone-1 exception total "
            f"is {exception_total}; expenditure must not disappear "
            f"(spec section 19.1)"
        )
