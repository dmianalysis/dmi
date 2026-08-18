#!/usr/bin/env python3
"""Track-A / Track-B shelter construction and the scope-rule adjudication.

Detailed Inflation Substrate v0.1, shelter task, Phase D.

RESEARCH ONLY. Reads the Milestone-2 artifacts, the pinned scope-rule registry
and this task's own shelter estimates. Writes only under ``data/research/`` and
``registry/research/``. Nothing here touches ``dmi_calculator``, the Baseline,
Slack-Plus, any release workflow or the deployment output tree. No index is
computed, no weight is normalised and no category inflation rate exists.

Three things in this module are worth reading before the code.

*The two tracks are two concepts, not two arithmetics.* Track A prices
owner-occupied shelter the way the CPI does, by rental equivalence, and
therefore removes the owner's financing and tax outlays. Track B keeps the
household's actual cash payments and introduces no rental equivalence at all.
Neither is a correction of the other. Track B is a payments sensitivity view;
it is not the BLS Household Cost Index, which this module does not implement
and does not claim to reproduce.

*The accounting does not balance and is not made to.* Replacing an outlay
concept with an imputed-flow concept changes the size of the basis. The
source-basis and CPI-basis totals are reported separately, their difference is
reported as a named quantity, and no rescaling, renormalisation, residual
allocation or balancing factor appears anywhere in this file. The one identity
that *is* enforced is a decomposition check: the parts of each total must sum
to that total. That is a different claim from the two totals agreeing.

*A pending rule is neither applied nor reversed.* Milestone 2's
``track_a_disposition`` established that a PROPOSED rule has no effect. This
module preserves that. An expenditure under a rule that stays PROPOSED is not
retained in Track A and is not removed from it: it sits in its own bucket and
is visible in every total.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from . import pumd
from . import shelter_adjudication as adj
from . import shelter_estimation as est

REPO_ROOT = Path(__file__).resolve().parents[2]

SCOPE_RULES_V0_1_PATH = REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_1.json"
SCOPE_RULES_V0_2_PATH = REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_2.json"
PROVENANCE_V0_1_PATH = REPO_ROOT / "registry/research/ucc_provenance_classes_v0_1.json"
PROVENANCE_V0_3_PATH = REPO_ROOT / "registry/research/ucc_provenance_classes_v0_3.json"

MILESTONE_2_DIR = REPO_ROOT / "data/research/detailed_inflation/milestone_2"
RECONCILIATION_PATH = MILESTONE_2_DIR / "transformation_reconciliation.csv"
SCOPE_RESOLUTION_PATH = MILESTONE_2_DIR / "scope_resolution_2024.csv"
BASIS_PATH = REPO_ROOT / "data/research/detailed_inflation/audit_2024/active_ucc_basis.csv"

SHELTER_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
ESTIMATES_PATH = SHELTER_DIR / "shelter_estimates_2024.csv"
CPI_TRACK_PATH = SHELTER_DIR / "shelter_cpi_track_2024.csv"
PAYMENTS_TRACK_PATH = SHELTER_DIR / "shelter_payments_track_2024.csv"
COMPARISON_PATH = SHELTER_DIR / "shelter_concept_comparison_2024.csv"
DOUBLE_COUNTING_PATH = SHELTER_DIR / "shelter_double_counting_audit_2024.csv"
RULE_ADJUDICATION_PATH = SHELTER_DIR / "shelter_rule_adjudication.json"
ACCOUNTING_PATH = SHELTER_DIR / "shelter_accounting_summary.json"

#: The reconciliation CSV names All Consumer Units in full; everything else in
#: this workstream uses the PUMD label. Translating in one place keeps the
#: mismatch from being rediscovered in five.
RECONCILIATION_POPULATION = {
    "All Consumer Units": "ALL_CU",
    "Q1": "Q1",
    "Q2": "Q2",
    "Q3": "Q3",
    "Q4": "Q4",
    "Q5": "Q5",
}

#: Milestone 2's own bucket names, reused rather than renamed.
SOURCE_BUCKETS = (
    "retained",
    "accepted_transformed",
    "accepted_out_of_scope",
    "pending_proposed",
    "unresolved_open",
)

ACCEPTED = "ACCEPTED"
PROPOSED = "PROPOSED"
EFFECTIVE = "EFFECTIVE"
PENDING = "PENDING"

PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
SECONDARY_RESIDENCE = "SECONDARY_RESIDENCE"

#: The four rules Phase D was asked to adjudicate, in the order the task gave
#: them.
PENDING_RULE_IDS = (
    "OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1",
    "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1",
    "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1",
    "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
)

#: Milestone 2 wrote, in all four of those rules, that each "takes effect only
#: jointly with the Track-A rental-equivalence rule". No such rule exists in
#: v0.1. The registry has ten entries and not one of them introduces
#: 910104-910107. The dependency was named but never written down, so nothing
#: could ever satisfy it. Phase D writes it.
TRACK_A_PRIMARY_RULE_ID = "TA_OWNER_RENTAL_EQUIVALENCE_PRIMARY_v0_1"
TRACK_A_SECONDARY_RULE_ID = "TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1"

#: Which rental-equivalence concept each shelter UCC belongs to. The split is
#: not this task's invention: the pinned BLS concordance already sends 910104
#: to HC011, a sampled ELI naming the primary residence, and sends the other
#: three to HC090, an unsampled residual. Two destinations, two rules.
RENTAL_EQUIVALENCE_TENURE = {
    "910104": PRIMARY_RESIDENCE,
    "910105": SECONDARY_RESIDENCE,
    "910106": SECONDARY_RESIDENCE,
    "910107": SECONDARY_RESIDENCE,
}

TRACK_A = "TRACK_A_CPI_COMPATIBLE"
TRACK_B = "TRACK_B_HOUSEHOLD_PAYMENTS"

TRACK_B_IS_NOT_THE_HCI = (
    "Track B retains the consumer unit's recorded cash and payment outlays for "
    "owner shelter and introduces no rental equivalence. That is a payments "
    "concept, and it is the only claim made for it. It is not the BLS "
    "Household Cost Index. The HCI is a specific BLS construction with its own "
    "treatment of mortgage principal, insurance and durables, none of which is "
    "implemented here, and no attempt has been made to reproduce its published "
    "values. Calling this an HCI would be naming a thing that does not exist "
    "in this repository."
)

# Dispositions used in the Track-A and Track-B tables and in the audit matrix.
RETAINED = "RETAINED"
REMOVED_OUT_OF_SCOPE = "REMOVED_OUT_OF_SCOPE"
REMOVED_FOR_REPLACEMENT = "REMOVED_FOR_REPLACEMENT"
INTRODUCED = "INTRODUCED"
WITHHELD = "WITHHELD"
PENDING_NEITHER_APPLIED_NOR_REVERSED = "PENDING_NEITHER_APPLIED_NOR_REVERSED"
UNRESOLVED = "UNRESOLVED"

DISPOSITION_SEMANTICS = {
    RETAINED: "The outlay stays in this track at its published CE value.",
    REMOVED_OUT_OF_SCOPE: (
        "The outlay leaves this track because the CPI does not price it. "
        "Nothing is added in its place."
    ),
    REMOVED_FOR_REPLACEMENT: (
        "The outlay leaves this track because a different concept prices the "
        "same thing. The replacement is introduced separately and is not "
        "assumed to equal what it replaced."
    ),
    INTRODUCED: (
        "An imputed amount enters this track that has no counterpart in the "
        "CE outlay basis."
    ),
    WITHHELD: (
        "An amount that would belong to this track is not admitted, because "
        "the estimate for it failed adjudication. It is not replaced by zero: "
        "the track is incomplete by exactly this item and says so."
    ),
    PENDING_NEITHER_APPLIED_NOR_REVERSED: (
        "The governing rule is PROPOSED. Milestone 2 established that a "
        "PROPOSED rule has no effect, so this amount is neither retained in "
        "the track nor removed from it. It is reported in its own bucket."
    ),
    UNRESOLVED: "No disposition has been proposed for this amount at all.",
}


class ShelterTrackError(RuntimeError):
    """Raised when the construction would have to assume something to proceed."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_scope_rules(path: Path = SCOPE_RULES_V0_1_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rules_by_id(registry: Mapping[str, object]) -> dict[str, dict]:
    return {rule["rule_id"]: rule for rule in registry["rules"]}  # type: ignore[index]


def rule_materiality(rule: Mapping[str, object]) -> dict[str, float]:
    """Published expenditure claimed by a rule, in millions, by population."""
    by_quintile = dict(rule["materiality_by_quintile"])  # type: ignore[index]
    out = {"ALL_CU": float(rule["materiality_all_cu"])}  # type: ignore[arg-type]
    for population in pumd.POPULATIONS[1:]:
        out[population] = float(by_quintile[population])
    return out


def load_reconciliation(path: Path = RECONCILIATION_PATH) -> dict[str, dict[str, float]]:
    """Milestone 2's accounting identity, keyed by PUMD population label."""
    out: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            population = RECONCILIATION_POPULATION[row["population"]]
            out[population] = {
                "ce_observed_basis": float(row["ce_observed_basis"]),
                **{bucket: float(row[bucket]) for bucket in SOURCE_BUCKETS},
            }
    missing = [p for p in pumd.POPULATIONS if p not in out]
    if missing:
        raise ShelterTrackError(
            "the Milestone-2 reconciliation is missing populations: "
            + ", ".join(missing)
        )
    return out


def load_shelter_aggregates(
    path: Path = ESTIMATES_PATH,
) -> dict[tuple[str, str], float | None]:
    """Estimated annual aggregates in millions, keyed by (UCC, population).

    ``None`` where the cell has no estimate. It is deliberately not zero, and
    every consumer of this mapping has to decide what to do about that rather
    than being handed a number that would quietly add up.
    """
    out: dict[tuple[str, str], float | None] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            text = row["annual_aggregate_millions"]
            out[(row["ucc"], row["population"])] = float(text) if text else None
    return out


def load_ucc_rows(path: Path = SCOPE_RESOLUTION_PATH) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_basis(path: Path = BASIS_PATH) -> dict[tuple[str, str], float | None]:
    """Published CE aggregates in millions, keyed by (UCC, population)."""
    out: dict[tuple[str, str], float | None] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            population = RECONCILIATION_POPULATION.get(row["population"])
            if population is None:
                continue
            text = row["aggregate_expenditure"]
            out[(row["ucc"], population)] = float(text) if text else None
    return out


def basis_item_text(path: Path = BASIS_PATH) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            out.setdefault(row["ucc"], row["item_text"])
    return out


# ---------------------------------------------------------------------------
# Tenure
# ---------------------------------------------------------------------------

SECONDARY_LABEL_MARKERS = ("owned vacation", "rented vacation")


def ucc_tenure(label: str) -> str:
    """Primary or secondary residence, read off the registry's own label.

    Milestone 2 wrote the tenure into every source label it recorded, because
    the CE stub distinguishes ``OWNMORTG`` from ``OWNVMORT`` and so on. Reading
    it back is not an inference.
    """
    lowered = label.lower()
    if any(marker in lowered for marker in SECONDARY_LABEL_MARKERS):
        return SECONDARY_RESIDENCE
    return PRIMARY_RESIDENCE


def rule_tenure_split(
    rule: Mapping[str, object], basis: Mapping[tuple[str, str], float | None]
) -> dict[str, dict[str, float]]:
    """Split a rule's published expenditure by residence, per population.

    Suppressed cells contribute nothing to either side and are counted
    separately, so a reader can see how much of the split is unobserved rather
    than being shown a total that silently omits it.
    """
    uccs = list(rule["source_uccs"])  # type: ignore[index]
    labels = list(rule["source_labels"])  # type: ignore[index]
    tenure_of = {ucc: ucc_tenure(label) for ucc, label in zip(uccs, labels)}
    out: dict[str, dict[str, float]] = {}
    for population in pumd.POPULATIONS:
        totals = {PRIMARY_RESIDENCE: 0.0, SECONDARY_RESIDENCE: 0.0}
        suppressed = 0
        for ucc in uccs:
            amount = basis.get((ucc, population))
            if amount is None:
                suppressed += 1
                continue
            totals[tenure_of[ucc]] += amount
        out[population] = {
            "primary_residence": totals[PRIMARY_RESIDENCE],
            "secondary_residence": totals[SECONDARY_RESIDENCE],
            "suppressed_ucc_count": float(suppressed),
        }
    return out


# ---------------------------------------------------------------------------
# The Track-A rental-equivalence rules (D4, and the dependency Milestone 2
# named but never wrote)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleQuestion:
    """One of the six questions Phase D requires each rule to answer."""

    question: str
    answer: str
    finding: str


@dataclass(frozen=True)
class RuleVerdict:
    rule_id: str
    review_status: str
    resolution_state: str
    is_applicable: bool
    evidence_strength: str
    evidence_strength_changed: bool
    questions: tuple[RuleQuestion, ...]
    blocker: str | None
    materiality_all_cu: float
    transition: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        accepted = self.review_status == ACCEPTED
        if accepted != (self.resolution_state == EFFECTIVE):
            raise ShelterTrackError(
                f"{self.rule_id}: review_status and resolution_state disagree"
            )
        if accepted != self.is_applicable:
            raise ShelterTrackError(
                f"{self.rule_id}: is_applicable does not follow review_status"
            )
        if accepted and self.blocker is not None:
            raise ShelterTrackError(
                f"{self.rule_id}: accepted while still carrying a blocker"
            )
        if not accepted and not self.blocker:
            raise ShelterTrackError(
                f"{self.rule_id}: held without stating what blocks it"
            )
        if self.evidence_strength_changed:
            raise ShelterTrackError(
                f"{self.rule_id}: an evidence grade moved in this task, which "
                "it may not do on the strength of an amount becoming "
                "computable"
            )


def secondary_replacement_status(
    verdicts: Mapping[str, RuleVerdict],
) -> tuple[bool, str]:
    """Is a secondary-residence rental-equivalence amount admissible yet?"""
    verdict = verdicts[TRACK_A_SECONDARY_RULE_ID]
    return verdict.review_status == ACCEPTED, verdict.blocker or ""


def adjudicate_rules(
    registry: Mapping[str, object],
    adjudication: Mapping[str, object],
    aggregates: Mapping[tuple[str, str], float | None],
    basis: Mapping[tuple[str, str], float | None],
) -> dict[str, RuleVerdict]:
    """Adjudicate the two new Track-A rules and the four pending ones.

    Every verdict is built from the C6 shelter adjudication and the registry's
    own recorded evidence. Nothing here reads a relative standard error, and
    nothing promotes or demotes an evidence grade.
    """
    by_id = rules_by_id(registry)
    admitted = set(adjudication["track_a_admitted"])  # type: ignore[index]
    withheld = set(adjudication["track_a_withheld"])  # type: ignore[index]
    quality = {
        ucc: entry["pumd_estimate_quality"]
        for ucc, entry in adjudication["adjudication"].items()  # type: ignore[index]
    }
    verdicts: dict[str, RuleVerdict] = {}

    # -- the primary-residence rental-equivalence rule -----------------------
    primary_amount = aggregates[("910104", "ALL_CU")]
    if primary_amount is None:
        raise ShelterTrackError("910104 has no All-CU aggregate to introduce")
    primary_admitted = "910104" in admitted
    verdicts[TRACK_A_PRIMARY_RULE_ID] = RuleVerdict(
        rule_id=TRACK_A_PRIMARY_RULE_ID,
        review_status=ACCEPTED if primary_admitted else PROPOSED,
        resolution_state=EFFECTIVE if primary_admitted else PENDING,
        is_applicable=primary_admitted,
        evidence_strength="STRONG",
        evidence_strength_changed=False,
        materiality_all_cu=primary_amount,
        transition=(
            "NEW. Milestone 2 made four rules conditional on a Track-A "
            "rental-equivalence rule that the v0.1 registry does not contain. "
            "This is that rule for the primary residence."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "YES",
                "The pinned 2024 BLS concordance maps 910104 to ELI HC011, "
                "'Owners' Equivalent Rent Of Primary Residence', which is a "
                "sampled ELI. Casey 2010 states that owned housing is "
                "'adjusted from net out-of-pocket expense to eliminate "
                "investment elements'. Both are BLS documents naming this "
                "concept for this UCC.",
            ),
            RuleQuestion(
                "Is the required estimate now available?",
                "YES",
                f"910104 is adjudicated {quality.get('910104')} quality and "
                "admitted to Track A. Its published counterpart 910050 "
                "reproduces at a ratio of 0.9990 for All Consumer Units with "
                "a maximum deviation of 1.41 percent across the six "
                "populations.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "YES",
                "The All-CU relative standard error is 1.30 percent and every "
                "quintile is estimated with a non-degenerate replicate "
                "distribution. The standard error travels with the amount in "
                "every artifact.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "YES",
                "This rule introduces an amount that has no counterpart in the "
                "CE outlay basis. 910104 is an ADDENDA line and is not a "
                "member of the EXPEND basis, so introducing it cannot "
                "duplicate anything already counted. Whether the outlays it "
                "displaces are removed is the business of the three rules "
                "below, and is audited separately.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the others?",
                "YES",
                "It supplies the replacement concept that "
                "OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1, "
                "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1 and "
                "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1 were all made "
                "conditional on. It claims no UCC claimed by any other rule.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES, RECORDED",
                "BLS has not been located stating whether a further adjustment "
                "is applied to 910104 before it becomes the CPI's HC011 "
                "weight. The provenance registry records cpi_adjustment_status "
                "as INFERRED for exactly this reason and this task produced no "
                "evidence that changes it. The amount introduced here is the "
                "CE addendum, not a reconstruction of a CPI weight, and the "
                "artifacts say so.",
            ),
        ),
        blocker=None
        if primary_admitted
        else "910104 was not admitted to Track A by the C6 adjudication.",
        warnings=(
            "The introduced amount is the CE rental-equivalence addendum. It "
            "is not a CPI expenditure weight and no claim is made that BLS "
            "uses it unmodified.",
        ),
    )

    # -- the secondary-residence rental-equivalence rule ---------------------
    secondary_uccs = ("910105", "910106", "910107")
    secondary_withheld = sorted(u for u in secondary_uccs if u in withheld)
    secondary_available = sorted(u for u in secondary_uccs if u in admitted)
    secondary_ok = not secondary_withheld
    blockers: list[str] = []
    if secondary_withheld:
        blockers.append(
            "The secondary-residence rental-equivalence concept has three "
            "components and "
            + ", ".join(secondary_withheld)
            + " is not admissible: it failed both usability tests in Phase C6. "
            "Its Q1 cell has no records and its Q2 cell has 22 of 44 replicate "
            "estimates at exactly zero, so the variance estimator is "
            "degenerate rather than merely imprecise. Substituting zero for it "
            "is forbidden, and inferring it from its published counterpart "
            "910102 is forbidden, so the replacement amount cannot be stated."
        )
    blockers.append(
        "Casey 2010 Appendix B note 2 states that 'in order to price the "
        "rental equivalence of secondary homes and timeshares, CPI uses a "
        "factor to account for the consumption portion of a homeowner's total "
        "expenditure'. The factor is not published. BLS therefore does not use "
        "the CE addenda amounts unmodified for this concept, and this task has "
        "no basis for reconstructing what it does use. This blocker is "
        "independent of the 910106 problem and would remain even if 910106 "
        "were admissible."
    )
    verdicts[TRACK_A_SECONDARY_RULE_ID] = RuleVerdict(
        rule_id=TRACK_A_SECONDARY_RULE_ID,
        review_status=PROPOSED,
        resolution_state=PENDING,
        is_applicable=False,
        evidence_strength="MODERATE",
        evidence_strength_changed=False,
        materiality_all_cu=sum(
            aggregates[(ucc, "ALL_CU")] or 0.0 for ucc in secondary_available
        ),
        transition=(
            "NEW. The secondary-residence half of the Track-A "
            "rental-equivalence dependency Milestone 2 named. It is written "
            "down so that the rules depending on it have something real to "
            "depend on, and it is written down PENDING because it is."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "YES",
                "The pinned concordance maps 910105, 910106 and 910107 to ELI "
                "HC090, and Casey 2010 Appendix B note 2 confirms that the CPI "
                "prices secondary homes and timeshares by rental equivalence. "
                "HC090 is an unsampled residual, which is a weaker destination "
                "than the primary residence's HC011.",
            ),
            RuleQuestion(
                "Is the required estimate now available?",
                "NO",
                "Two of the three components are admissible ("
                + ", ".join(secondary_available)
                + ") and "
                + ", ".join(secondary_withheld or ["none"])
                + " is not. A concept made of three parts cannot be stated "
                "from two of them without assuming the third, and the two "
                "available parts are not offered as if they were the whole.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "PARTLY",
                "910105 is MODERATE quality and 910107 is LOW at a 31.79 "
                "percent All-CU relative standard error, both carried "
                "explicitly. 910107's published counterpart 910103 misses by "
                "11.05 percent in Q3, which is recorded rather than dropped. "
                "For 910106 there is no defensible uncertainty statement at "
                "all, which is the point.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "NOT REACHED",
                "The question does not arise while the rule is PENDING. The "
                "double-counting matrix nevertheless records the secondary "
                "residence row, because the outlays removed by the two "
                "accepted exclusion rules include secondary-residence members "
                "whose replacement is this pending concept.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the others?",
                "NOT YET",
                "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1 is a REPLACE rule "
                "whose added term is precisely this amount, so it cannot take "
                "effect while this is PENDING. Separately, the "
                "secondary-residence members of the mortgage-interest and "
                "property-tax rules leave the basis without this concept "
                "entering. That residual is quantified in the accounting "
                "summary and is not netted against anything.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES",
                "The unpublished BLS consumption factor, and the question of "
                "whether a vacation home held available for rent is "
                "owner-occupied shelter at all. Neither was resolved here and "
                "neither was guessed at.",
            ),
        ),
        blocker=" ".join(blockers),
    )

    secondary_ready, secondary_blocker = secondary_replacement_status(verdicts)

    # -- OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1 ---------------------------
    rule = by_id["OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1"]
    split = rule_tenure_split(rule, basis)["ALL_CU"]
    verdicts[rule["rule_id"]] = RuleVerdict(
        rule_id=rule["rule_id"],
        review_status=ACCEPTED,
        resolution_state=EFFECTIVE,
        is_applicable=True,
        evidence_strength=rule["evidence_strength"],
        evidence_strength_changed=False,
        materiality_all_cu=float(rule["materiality_all_cu"]),
        transition=(
            "PROPOSED/PENDING -> ACCEPTED/EFFECTIVE. The recorded blocker was "
            "that the PUMD annual-weighting and income-quintile procedure had "
            "not been benchmarked against published 2024 LB01 estimates. It "
            "has been: the frozen estimator passed the Phase-B confirmation on "
            "111 previously unused UCCs and 666 cells, and reproduces the "
            "published shelter counterpart 910050 to within 1.41 percent."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "YES",
                "Unchanged and independent of shelter. The CPI Handbook of "
                "Methods states that 'interest costs and finance charges are "
                "also out-of-scope', and all eight UCCs are interest or "
                "charges on a credit instrument by name and by CE stub "
                "placement. Milestone 2 graded this STRONG on two independent "
                "grounds and neither has moved.",
            ),
            RuleQuestion(
                "Is the required replacement estimate now available?",
                "YES FOR THE PRIMARY RESIDENCE, NO FOR THE SECONDARY",
                f"{split['primary_residence']:,.0f} million dollars of the "
                f"{float(rule['materiality_all_cu']):,.0f} million claimed by "
                "this rule is primary-residence financing, whose replacement "
                f"{TRACK_A_PRIMARY_RULE_ID} is now EFFECTIVE. "
                f"{split['secondary_residence']:,.0f} million is "
                "secondary-residence financing, whose replacement rule is "
                "PENDING. This rule is an EXCLUDE rule and adds no term, so "
                "its arithmetic does not require the replacement; the residual "
                "is nonetheless quantified in the accounting summary rather "
                "than absorbed.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "YES",
                "The removed amounts are published CE aggregates, not "
                "estimates, so they carry no sampling error of this task's "
                "making. One member, 830112, is suppressed; its published "
                "sibling 830111 is 21 million dollars, which bounds the "
                "unobserved amount far below materiality.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "YES, AND IT IS WHAT PREVENTS IT",
                "Retaining mortgage interest alongside the introduced rental "
                "equivalence would count owner shelter twice, since rental "
                "equivalence prices the whole flow of housing services "
                "including the financing embedded in a market rent. The audit "
                "matrix records that no member of this rule survives in Track "
                "A.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the other three?",
                "YES",
                "Each UCC is claimed by exactly one rule, which Milestone 2 "
                "verified and which is re-checked here. The owned-vacation "
                "members sit in this rule rather than in "
                "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1 because the interest "
                "ground is STRONG and does not depend on the "
                "secondary-residence argument, which is Milestone 2's stated "
                "reason and is unchanged.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES, RECORDED, NOT BLOCKING",
                "The secondary-residence members leave the basis while their "
                "rental-equivalence replacement is PENDING. That understates "
                "Track-A shelter by an amount that is reported, not corrected. "
                "It is not a reason to retain interest, because the CPI "
                "excludes interest for both tenures regardless of how the "
                "shelter flow is priced.",
            ),
        ),
        blocker=None,
        warnings=(
            f"{split['secondary_residence']:,.0f} million dollars of "
            "owned-vacation financing leaves the basis under this rule while "
            f"{TRACK_A_SECONDARY_RULE_ID} is PENDING. "
            + secondary_blocker,
        )
        if not secondary_ready
        else (),
    )

    # -- OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1 --------------------------------
    rule = by_id["OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1"]
    split = rule_tenure_split(rule, basis)["ALL_CU"]
    verdicts[rule["rule_id"]] = RuleVerdict(
        rule_id=rule["rule_id"],
        review_status=ACCEPTED,
        resolution_state=EFFECTIVE,
        is_applicable=True,
        evidence_strength=rule["evidence_strength"],
        evidence_strength_changed=False,
        materiality_all_cu=float(rule["materiality_all_cu"]),
        transition=(
            "PROPOSED/PENDING -> ACCEPTED/EFFECTIVE, on the same cleared "
            "benchmark blocker as the mortgage-interest rule."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "YES",
                "Unchanged. The Handbook states that 'the CPI excludes income "
                "tax and other direct taxes', and residential property tax is "
                "a direct tax on the owner. Graded STRONG at Milestone 2 and "
                "not revisited here.",
            ),
            RuleQuestion(
                "Is the required replacement estimate now available?",
                "YES FOR THE PRIMARY RESIDENCE, NO FOR THE SECONDARY",
                f"{split['primary_residence']:,.0f} million dollars is "
                "primary-residence property tax and "
                f"{split['secondary_residence']:,.0f} million is "
                "owned-vacation property tax. The same asymmetry as the "
                "mortgage rule, reported the same way.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "YES",
                "Both members are published, unsuppressed CE aggregates.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "YES",
                "A market rent embeds the landlord's property tax. Pricing "
                "owner shelter by rental equivalence and also charging the "
                "owner's tax bill would count it twice.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the other three?",
                "YES",
                "Milestone 2 deliberately did not extend this treatment to the "
                "vehicle personal property tax, which BLS itself bundles into "
                "the registration-fee concept. That boundary is untouched.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES, RECORDED, NOT BLOCKING",
                "The owned-vacation member, as with the mortgage rule.",
            ),
        ),
        blocker=None,
        warnings=(
            f"{split['secondary_residence']:,.0f} million dollars of "
            "owned-vacation property tax leaves the basis while "
            f"{TRACK_A_SECONDARY_RULE_ID} is PENDING.",
        )
        if not secondary_ready
        else (),
    )

    # -- OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1 ------------------------------
    rule = by_id["OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"]
    verdicts[rule["rule_id"]] = RuleVerdict(
        rule_id=rule["rule_id"],
        review_status=PROPOSED,
        resolution_state=PENDING,
        is_applicable=False,
        evidence_strength=rule["evidence_strength"],
        evidence_strength_changed=False,
        materiality_all_cu=float(rule["materiality_all_cu"]),
        transition=(
            "PROPOSED/PENDING preserved. One of its two recorded blockers is "
            "cleared and the other is untouched, so its status does not move."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "PARTLY",
                "The principle is BLS's: the CPI 'excludes investment items, "
                "such as stocks, bonds, real estate', and Casey 2010 states "
                "that owner maintenance is weighted from 'the corresponding "
                "mean expenditures of renters'. What is not BLS's is the "
                "membership. BLS does not name these eight UCCs. Milestone 2 "
                "assigned them with the owner/renter counterpart test, which "
                "is a DMI structural inference, and graded the rule MODERATE "
                "for that reason.",
            ),
            RuleQuestion(
                "Is the required replacement estimate now available?",
                "NOT APPLICABLE TO THE BLOCKER",
                "This is the part that has changed. All eight members are "
                "primary-residence codes, so the rental-equivalence dependency "
                f"is satisfied by {TRACK_A_PRIMARY_RULE_ID}. For the five "
                "maintenance members the operative replacement is not rental "
                "equivalence at all but the renter counterpart expenditure, "
                "which Track A already retains; the counterpart test's whole "
                "claim is that these five have no such counterpart. That claim "
                "is what remains unverified against BLS.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "YES FOR THE AMOUNT, NO FOR THE MEMBERSHIP",
                "The 232,781 million dollars is published and exact. The "
                "uncertainty is not sampling uncertainty; it is whether these "
                "are the right eight codes, and an exact amount attached to an "
                "uncertain membership is precisely the shape of error this "
                "rule is exposed to.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "YES, IF THE MEMBERSHIP IS RIGHT",
                "Conditional on the membership, retaining owner maintenance "
                "alongside rental equivalence would double count. The "
                "condition is the problem.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the other three?",
                "YES",
                "No UCC overlap, and its 232,781 million dollars stays in the "
                "pending bucket, so it is neither retained in Track A nor "
                "removed from it and cannot double count in either direction.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES, BLOCKING",
                "Milestone 2 recorded that this is 'the largest "
                "MODERATE-evidence exclusion in the registry at 3.4 percent of "
                "basis and should receive explicit reviewer attention on its "
                "own merits'. That was a second, separate bar, and this task "
                "produced no evidence bearing on it. Clearing the shelter "
                "blocker does not clear it. Accepting the rule now would be "
                "promoting a MODERATE structural inference on the strength of "
                "an unrelated benchmark, which is the failure mode the "
                "instruction against obtaining closure names.",
            ),
        ),
        blocker=(
            "The shelter dependency is cleared but the evidence blocker is "
            "not. BLS does not enumerate these eight UCCs; the membership "
            "rests on the DMI owner/renter counterpart test. Milestone 2 "
            "flagged the rule for reviewer attention on its own merits and "
            "nothing produced in this task speaks to it. Clearing requires "
            "either a BLS source naming the codes, or an independent check "
            "that no renter counterpart exists for the five maintenance "
            "members."
        ),
    )

    # -- RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1 ------------------------------
    rule = by_id["RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1"]
    verdicts[rule["rule_id"]] = RuleVerdict(
        rule_id=rule["rule_id"],
        review_status=PROPOSED,
        resolution_state=PENDING,
        is_applicable=False,
        evidence_strength=rule["evidence_strength"],
        evidence_strength_changed=False,
        materiality_all_cu=float(rule["materiality_all_cu"]),
        transition=(
            "PROPOSED/PENDING preserved. The benchmark blocker is cleared; the "
            "replacement this rule has to add is still not statable."
        ),
        questions=(
            RuleQuestion(
                "Is its BLS scope rationale still supported?",
                "YES",
                "Casey 2010 Appendix B note 2 documents that the CPI prices "
                "secondary homes and timeshares by rental equivalence, and "
                "Milestone 2's structural check that the entire owned-vacation "
                "CE stub branch is unmapped in the concordance is unchanged.",
            ),
            RuleQuestion(
                "Is the required replacement estimate now available?",
                "NO",
                "This is a REPLACE rule. Its transformation formula removes "
                "the fifteen owned-vacation outlays and adds the "
                "secondary-residence rental-equivalence amount. That addend is "
                f"supplied by {TRACK_A_SECONDARY_RULE_ID}, which is PENDING "
                "because 910106 failed adjudication and because the BLS "
                "consumption factor is unpublished. Executing the formula "
                "would require substituting zero for the missing component or "
                "inferring it from 910102, both of which are forbidden.",
            ),
            RuleQuestion(
                "Is uncertainty adequately represented?",
                "PARTLY",
                "The removed side is published and exact, though 320633 is "
                "suppressed and eight of fifteen members are suppressed in Q1. "
                "The added side has no defensible value, which is not a wide "
                "interval but an absence.",
            ),
            RuleQuestion(
                "Does acceptance avoid double counting?",
                "NOT REACHED",
                "The question does not arise while the rule is PENDING.",
            ),
            RuleQuestion(
                "Does the rule interact correctly with the other three?",
                "YES",
                "It claims only the owned-vacation codes that the STRONG "
                "interest and direct-tax rules do not claim, and it cedes "
                "990940 to the capital-improvement rule so that concept is "
                "treated identically across tenures. That partition is "
                "unchanged.",
            ),
            RuleQuestion(
                "Does any unresolved conceptual issue remain?",
                "YES, BLOCKING",
                "Milestone 2 recorded a competing reading under which these "
                "outlays are simply excluded as real-estate investment rather "
                "than replaced. Under that reading the rule needs no addend "
                "and could be accepted today. The published record does not "
                "settle which reading is right, and choosing the convenient "
                "one to obtain closure is not an argument.",
            ),
        ),
        blocker=(
            "The replacement amount this rule must add is not available. "
            + secondary_blocker
            + " Separately, whether these outlays are replaced or simply "
            "excluded is not settled by the published record, and the two "
            "readings differ in what the rule has to supply."
        ),
    )
    return verdicts


# ---------------------------------------------------------------------------
# Track construction (D1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrackRow:
    track: str
    component: str
    ucc: str
    label: str
    tenure: str
    disposition: str
    rule_id: str | None
    amounts: dict[str, float | None] = field(default_factory=dict)
    note: str = ""


def _shelter_rule_ids() -> tuple[str, ...]:
    return PENDING_RULE_IDS


def build_tracks(
    registry: Mapping[str, object],
    verdicts: Mapping[str, RuleVerdict],
    aggregates: Mapping[tuple[str, str], float | None],
    basis: Mapping[tuple[str, str], float | None],
    adjudication: Mapping[str, object],
) -> tuple[list[TrackRow], list[TrackRow]]:
    """Track A and Track B, built from the same source rows by two rules.

    Track B is not Track A with a sign flipped. It is the statement that a
    payments concept performs no substitution: every owner outlay stays, and no
    imputed rent appears.
    """
    by_id = rules_by_id(registry)
    item_text = basis_item_text()
    withheld = set(adjudication["track_a_withheld"])  # type: ignore[index]
    track_a: list[TrackRow] = []
    track_b: list[TrackRow] = []

    for rule_id in _shelter_rule_ids():
        rule = by_id[rule_id]
        verdict = verdicts[rule_id]
        applied = verdict.is_applicable
        for ucc, label in zip(rule["source_uccs"], rule["source_labels"]):  # type: ignore[index]
            tenure = ucc_tenure(label)
            amounts = {p: basis.get((ucc, p)) for p in pumd.POPULATIONS}
            if not applied:
                disposition = PENDING_NEITHER_APPLIED_NOR_REVERSED
            elif rule["rule_type"] == "REPLACE":
                disposition = REMOVED_FOR_REPLACEMENT
            else:
                disposition = REMOVED_OUT_OF_SCOPE
            track_a.append(
                TrackRow(
                    track=TRACK_A,
                    component="OWNER_OUTLAY",
                    ucc=ucc,
                    label=label,
                    tenure=tenure,
                    disposition=disposition,
                    rule_id=rule_id,
                    amounts=amounts,
                    note=""
                    if applied
                    else "governing rule is PROPOSED, so nothing is applied",
                )
            )
            track_b.append(
                TrackRow(
                    track=TRACK_B,
                    component="OWNER_OUTLAY",
                    ucc=ucc,
                    label=label,
                    tenure=tenure,
                    disposition=RETAINED,
                    rule_id=rule_id,
                    amounts=amounts,
                    note=str(rule["track_b"]["treatment"]),  # type: ignore[index]
                )
            )

    for ucc in est.SHELTER_UCCS:
        tenure = RENTAL_EQUIVALENCE_TENURE[ucc]
        introducing = (
            TRACK_A_PRIMARY_RULE_ID
            if tenure == PRIMARY_RESIDENCE
            else TRACK_A_SECONDARY_RULE_ID
        )
        verdict = verdicts[introducing]
        amounts = {p: aggregates.get((ucc, p)) for p in pumd.POPULATIONS}
        if ucc in withheld:
            disposition = WITHHELD
            note = (
                "failed the Phase-C6 usability adjudication; not admitted and "
                "not replaced by zero"
            )
        elif verdict.is_applicable:
            disposition = INTRODUCED
            note = ""
        else:
            disposition = PENDING_NEITHER_APPLIED_NOR_REVERSED
            note = "introducing rule is PROPOSED"
        track_a.append(
            TrackRow(
                track=TRACK_A,
                component="RENTAL_EQUIVALENCE",
                ucc=ucc,
                label=adj.PUBLISHED_ITEM_TEXT.get(adj.PUBLISHED_OF[ucc], ucc),
                tenure=tenure,
                disposition=disposition,
                rule_id=introducing,
                amounts=amounts,
                note=note,
            )
        )
        track_b.append(
            TrackRow(
                track=TRACK_B,
                component="RENTAL_EQUIVALENCE",
                ucc=ucc,
                label=adj.PUBLISHED_ITEM_TEXT.get(adj.PUBLISHED_OF[ucc], ucc),
                tenure=tenure,
                disposition="NOT_INTRODUCED",
                rule_id=None,
                amounts={p: None for p in pumd.POPULATIONS},
                note=(
                    "a payments concept imputes no rent; the amount is absent "
                    "by construction, not missing"
                ),
            )
        )
    return track_a, track_b


# ---------------------------------------------------------------------------
# Accounting (D2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PopulationAccounting:
    population: str
    e_source: float
    retained: float
    accepted_transformed: float
    accepted_out_of_scope: float
    pending_proposed: float
    unresolved_open: float
    rental_equivalence_introduced: float
    rental_equivalence_withheld: float | None
    owner_outlays_removed: float
    e_cpi: float
    delta_scope: float
    delta_shelter: float
    secondary_residence_outlays_removed_without_replacement: float

    def __post_init__(self) -> None:
        """Check the decompositions, which is not the same as forcing a balance.

        Two sums are checked: that the source buckets reconstruct the source
        basis, and that the CPI basis equals what was put into it. Neither
        check compares the two bases to each other, and nothing here adjusts a
        number to make a check pass.
        """
        source_parts = (
            self.retained
            + self.accepted_transformed
            + self.accepted_out_of_scope
            + self.pending_proposed
            + self.unresolved_open
        )
        if abs(source_parts - self.e_source) > 0.5:
            raise ShelterTrackError(
                f"{self.population}: source buckets sum to {source_parts}, "
                f"basis is {self.e_source}"
            )
        cpi_parts = (
            self.retained + self.accepted_transformed + self.rental_equivalence_introduced
        )
        if abs(cpi_parts - self.e_cpi) > 0.5:
            raise ShelterTrackError(
                f"{self.population}: CPI parts sum to {cpi_parts}, "
                f"basis is {self.e_cpi}"
            )
        if abs((self.e_cpi - self.e_source) - self.delta_scope) > 0.5:
            raise ShelterTrackError(f"{self.population}: delta_scope is not the gap")


def build_accounting(
    reconciliation: Mapping[str, Mapping[str, float]],
    verdicts: Mapping[str, RuleVerdict],
    registry: Mapping[str, object],
    aggregates: Mapping[tuple[str, str], float | None],
    basis: Mapping[tuple[str, str], float | None],
    adjudication: Mapping[str, object],
) -> dict[str, PopulationAccounting]:
    by_id = rules_by_id(registry)
    withheld = set(adjudication["track_a_withheld"])  # type: ignore[index]
    newly_accepted = [
        rule_id
        for rule_id in PENDING_RULE_IDS
        if verdicts[rule_id].review_status == ACCEPTED
    ]
    out: dict[str, PopulationAccounting] = {}
    for population in pumd.POPULATIONS:
        row = reconciliation[population]

        moved = sum(
            rule_materiality(by_id[rule_id])[population] for rule_id in newly_accepted
        )
        accepted_out_of_scope = row["accepted_out_of_scope"] + moved
        pending_proposed = row["pending_proposed"] - moved

        introduced = 0.0
        withheld_total: float | None = None
        for ucc in est.SHELTER_UCCS:
            tenure = RENTAL_EQUIVALENCE_TENURE[ucc]
            introducing = (
                TRACK_A_PRIMARY_RULE_ID
                if tenure == PRIMARY_RESIDENCE
                else TRACK_A_SECONDARY_RULE_ID
            )
            if ucc in withheld:
                continue
            if not verdicts[introducing].is_applicable:
                continue
            amount = aggregates.get((ucc, population))
            if amount is None:
                raise ShelterTrackError(
                    f"{ucc}/{population} is admitted but has no amount, which "
                    "cannot be treated as zero"
                )
            introduced += amount
        for ucc in sorted(withheld):
            amount = aggregates.get((ucc, population))
            withheld_total = amount if withheld_total is None else (
                None if amount is None else withheld_total + amount
            )

        secondary_stranded = 0.0
        for rule_id in newly_accepted:
            split = rule_tenure_split(by_id[rule_id], basis)[population]
            secondary_stranded += split["secondary_residence"]
        if verdicts[TRACK_A_SECONDARY_RULE_ID].is_applicable:
            secondary_stranded = 0.0

        e_source = row["ce_observed_basis"]
        e_cpi = row["retained"] + row["accepted_transformed"] + introduced
        out[population] = PopulationAccounting(
            population=population,
            e_source=e_source,
            retained=row["retained"],
            accepted_transformed=row["accepted_transformed"],
            accepted_out_of_scope=accepted_out_of_scope,
            pending_proposed=pending_proposed,
            unresolved_open=row["unresolved_open"],
            rental_equivalence_introduced=introduced,
            rental_equivalence_withheld=withheld_total,
            owner_outlays_removed=moved,
            e_cpi=e_cpi,
            delta_scope=e_cpi - e_source,
            delta_shelter=introduced - moved,
            secondary_residence_outlays_removed_without_replacement=secondary_stranded,
        )
    return out


# ---------------------------------------------------------------------------
# Double-counting audit (D3)
# ---------------------------------------------------------------------------

#: The nine categories Phase D requires be inspected explicitly, plus the UCC
#: sets that stand for them. Categories that are not governed by a scope rule
#: are given their UCCs directly, because "we looked and it was fine" is not an
#: auditable statement unless the reader can see what was looked at.
RENTER_SHELTER_UCCS = ("210110", "800710", "350110")
UTILITY_UCCS = (
    "260111",
    "260112",
    "260113",
    "260114",
    "260211",
    "260212",
    "260213",
    "260214",
    "250111",
    "250112",
    "250211",
    "250212",
    "250213",
    "250912",
    "270211",
    "270212",
    "270213",
    "270214",
    "270411",
)
HOMEOWNERS_INSURANCE_PRIMARY = ("220121",)
HOMEOWNERS_INSURANCE_SECONDARY = ("220122",)


@dataclass(frozen=True)
class AuditRow:
    category: str
    basis_for_membership: str
    uccs: tuple[str, ...]
    all_cu_expenditure: float | None
    track_a_disposition: str
    track_b_disposition: str
    governing_rule: str | None
    double_counting_finding: str
    is_open_item: bool = False
    """Does this row leave something unsettled that a reader must carry forward?

    Stated by the row that knows, not inferred from the wording of the
    finding. An earlier draft read the flag off the prose, which meant a
    reworded sentence could drop a category out of the open-items list without
    anyone noticing. The failures this audit exists to catch are the silent
    ones.
    """


def _sum_basis(
    uccs: Sequence[str], basis: Mapping[tuple[str, str], float | None], population: str
) -> float | None:
    total = 0.0
    seen = False
    for ucc in uccs:
        amount = basis.get((ucc, population))
        if amount is None:
            continue
        seen = True
        total += amount
    return total if seen else None


def build_double_counting_audit(
    registry: Mapping[str, object],
    verdicts: Mapping[str, RuleVerdict],
    aggregates: Mapping[tuple[str, str], float | None],
    basis: Mapping[tuple[str, str], float | None],
    adjudication: Mapping[str, object],
) -> list[AuditRow]:
    by_id = rules_by_id(registry)
    withheld = set(adjudication["track_a_withheld"])  # type: ignore[index]
    rows: list[AuditRow] = []

    def rule_row(
        category: str,
        rule_id: str,
        finding: str,
        membership: str,
        open_item: bool = False,
    ) -> AuditRow:
        rule = by_id[rule_id]
        verdict = verdicts[rule_id]
        if not verdict.is_applicable:
            disposition = PENDING_NEITHER_APPLIED_NOR_REVERSED
        elif rule["rule_type"] == "REPLACE":
            disposition = REMOVED_FOR_REPLACEMENT
        else:
            disposition = REMOVED_OUT_OF_SCOPE
        return AuditRow(
            category=category,
            basis_for_membership=membership,
            uccs=tuple(rule["source_uccs"]),  # type: ignore[arg-type]
            all_cu_expenditure=float(rule["materiality_all_cu"]),  # type: ignore[arg-type]
            track_a_disposition=disposition,
            track_b_disposition=RETAINED,
            governing_rule=rule_id,
            double_counting_finding=finding,
            is_open_item=open_item,
        )

    primary_amount = aggregates[("910104", "ALL_CU")]
    rows.append(
        AuditRow(
            category="primary_residence_owner_shelter",
            basis_for_membership=(
                "The pinned BLS concordance maps 910104 to HC011, a sampled "
                "ELI naming the primary residence."
            ),
            uccs=("910104",),
            all_cu_expenditure=primary_amount,
            track_a_disposition=INTRODUCED
            if verdicts[TRACK_A_PRIMARY_RULE_ID].is_applicable
            else PENDING_NEITHER_APPLIED_NOR_REVERSED,
            track_b_disposition="NOT_INTRODUCED",
            governing_rule=TRACK_A_PRIMARY_RULE_ID,
            double_counting_finding=(
                "No duplication. 910104 is a CE ADDENDA line and is not a "
                "member of the EXPEND basis, so it cannot be counted twice by "
                "being introduced. The outlays it displaces are handled by the "
                "three rows below and none of them survives in Track A."
            ),
        )
    )
    rows.append(
        rule_row(
            "mortgage_interest_and_home_equity_interest",
            "OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1",
            "No duplication. Every member is removed from Track A, so none "
            "survives alongside the rental equivalence that prices the same "
            "shelter flow. Track B retains all of them, which is the point of "
            "Track B.",
            "Rule membership, Milestone 2, STRONG evidence.",
        )
    )
    rows.append(
        rule_row(
            "residential_property_tax",
            "OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1",
            "No duplication. Both members are removed from Track A.",
            "Rule membership, Milestone 2, STRONG evidence.",
        )
    )
    rows.append(
        rule_row(
            "owner_repairs_improvements_structure_investment",
            "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1",
            "POTENTIAL DUPLICATION, UNRESOLVED AND VISIBLE. The rule is "
            "PROPOSED, so these outlays are neither retained in Track A nor "
            "removed from it; they sit in the pending bucket. That is why the "
            "duplication does not occur, and it is also why the category is "
            "not closed. If the rule were accepted the duplication would be "
            "removed; if it were rejected the outlays would return to Track A "
            "alongside rental equivalence and the duplication would be real.",
            "Rule membership, Milestone 2, MODERATE evidence resting on the "
            "DMI owner/renter counterpart test.",
            open_item=True,
        )
    )

    insurance_primary = _sum_basis(HOMEOWNERS_INSURANCE_PRIMARY, basis, "ALL_CU")
    rows.append(
        AuditRow(
            category="homeowners_insurance_primary_residence",
            basis_for_membership=(
                "220121, mapped at Milestone 1 and not claimed by any scope "
                "rule."
            ),
            uccs=HOMEOWNERS_INSURANCE_PRIMARY,
            all_cu_expenditure=insurance_primary,
            track_a_disposition=RETAINED,
            track_b_disposition=RETAINED,
            governing_rule=None,
            double_counting_finding=(
                "RETAINED IN FULL, AND WHETHER THAT IS TOO MUCH IS NOT "
                "ESTABLISHED. Casey 2010 Appendix B note 3 states that CPI "
                "reduces the homeowners insurance weight 'to reflect only the "
                "renter's part of the owner's expenditure. The factor applied "
                "is 43%'. Two separate things follow and they must not be "
                "merged. Historical BLS authority for a renter's-part "
                "allocation is ESTABLISHED: the document is primary, dated, "
                "and states a factor. Whether that factor or any successor "
                "governs the 2024 CE-to-CPI weighting vintage is "
                "NOT_ESTABLISHED, because no current-vintage source has been "
                "located in this task. Track A therefore retains 100 percent "
                "-- not because 100 percent has been shown correct, but "
                "because no adjudicated 2024 factor exists to apply. The size "
                "of any overstatement is unknown. Quoting 57 percent would "
                "silently promote a 2010 factor to a 2024 factor, which is the "
                "failure this workstream exists to avoid."
            ),
            is_open_item=True,
        )
    )
    rows.append(
        rule_row(
            "secondary_and_vacation_residence_costs",
            "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
            "NO DUPLICATION, BUT AN INCOMPLETE REPLACEMENT ELSEWHERE. This "
            "rule is PROPOSED so its fifteen members stay in the pending "
            "bucket. Separately, the owned-vacation members of the accepted "
            "mortgage-interest and property-tax rules do leave the basis while "
            "the secondary-residence rental equivalence has not entered. That "
            "is an understatement of Track-A secondary shelter, quantified in "
            "the accounting summary as "
            "secondary_residence_outlays_removed_without_replacement. It is "
            "not netted, offset or corrected.",
            "Rule membership, Milestone 2, MODERATE evidence.",
            open_item=True,
        )
    )
    renter_amount = _sum_basis(RENTER_SHELTER_UCCS, basis, "ALL_CU")
    rows.append(
        AuditRow(
            category="renter_rent_and_renter_related_costs",
            basis_for_membership=(
                "Rent (210110), rent as pay (800710) and tenant's insurance "
                "(350110). None is claimed by any scope rule."
            ),
            uccs=RENTER_SHELTER_UCCS,
            all_cu_expenditure=renter_amount,
            track_a_disposition=RETAINED,
            track_b_disposition=RETAINED,
            governing_rule=None,
            double_counting_finding=(
                "No duplication and no loss. Renter rent is priced directly by "
                "the CPI and is untouched by the owner-shelter treatment. The "
                "check that matters here is the second half of the audit "
                "instruction: nothing was removed merely for being "
                "housing-associated."
            ),
        )
    )
    utility_amount = _sum_basis(UTILITY_UCCS, basis, "ALL_CU")
    rows.append(
        AuditRow(
            category="utilities",
            basis_for_membership=(
                "Electricity, natural gas, bottled gas, fuel oil, other fuels, "
                "water and sewer, and trash collection, across all four "
                "tenures. None is claimed by any scope rule."
            ),
            uccs=UTILITY_UCCS,
            all_cu_expenditure=utility_amount,
            track_a_disposition=RETAINED,
            track_b_disposition=RETAINED,
            governing_rule=None,
            double_counting_finding=(
                "No duplication and no loss. Utilities are priced separately "
                "by the CPI and are not embedded in owners' equivalent rent, "
                "so changing the shelter treatment must not and does not "
                "remove them. This row exists because the failure it guards "
                "against would be silent."
            ),
        )
    )
    secondary_admitted = sorted(
        ucc
        for ucc in ("910105", "910106", "910107")
        if ucc not in withheld
    )
    rows.append(
        AuditRow(
            category="rental_equivalence_addenda_910104_910107",
            basis_for_membership=(
                "The four CE ADDENDA rental-equivalence lines estimated in "
                "Phase C."
            ),
            uccs=tuple(est.SHELTER_UCCS),
            all_cu_expenditure=None,
            track_a_disposition=(
                "910104 INTRODUCED; "
                + ", ".join(secondary_admitted)
                + " admissible but held by a PENDING rule; "
                + ", ".join(sorted(withheld))
                + " WITHHELD"
            ),
            track_b_disposition="NOT_INTRODUCED",
            governing_rule=(
                f"{TRACK_A_PRIMARY_RULE_ID}; {TRACK_A_SECONDARY_RULE_ID}"
            ),
            double_counting_finding=(
                "No duplication. None of the four is in the EXPEND basis, and "
                "none of them may be inferred from its published counterpart. "
                "In particular 910107 is not inferred from 910103: the "
                "record-level measurement in Phase C6 shows 910103 is the "
                "whole timeshare property's annual rental value while 910107 "
                "is the share of weeks this consumer unit owns, so they are "
                "different estimands and neither substitutes for the other."
            ),
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Writers (D5, D6)
# ---------------------------------------------------------------------------

TRACK_CSV_COLUMNS = (
    "track",
    "component",
    "ucc",
    "label",
    "tenure",
    "disposition",
    "rule_id",
    *(f"{p.lower()}_millions" for p in pumd.POPULATIONS),
    "note",
)

COMPARISON_CSV_COLUMNS = (
    "population",
    "quantity",
    "millions",
    "definition",
)

AUDIT_CSV_COLUMNS = (
    "category",
    "ucc_count",
    "uccs",
    "all_cu_millions",
    "track_a_disposition",
    "track_b_disposition",
    "governing_rule",
    "basis_for_membership",
    "is_open_item",
    "double_counting_finding",
)


def _cell(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def write_track_csv(path: Path, rows: Sequence[TrackRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRACK_CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.track,
                    row.component,
                    row.ucc,
                    row.label,
                    row.tenure,
                    row.disposition,
                    row.rule_id or "",
                    *(_cell(row.amounts.get(p)) for p in pumd.POPULATIONS),
                    row.note,
                ]
            )


COMPARISON_DEFINITIONS = {
    "e_source": "CE observed outlay basis, Milestone 2 section 19.1.",
    "e_cpi": (
        "Retained plus accepted-transformed plus rental equivalence "
        "introduced. Excludes everything under a PROPOSED or OPEN rule."
    ),
    "delta_scope": "e_cpi minus e_source. Not required to be zero.",
    "rental_equivalence_introduced": (
        "Admitted Track-A rental equivalence under an EFFECTIVE introducing "
        "rule."
    ),
    "rental_equivalence_withheld": (
        "Estimated amount for shelter UCCs that failed adjudication. Shown so "
        "the gap has a size; blank where the cell has no estimate at all, "
        "which is not zero."
    ),
    "owner_outlays_removed": (
        "Published CE expenditure removed by the shelter-coupled rules "
        "accepted in this task."
    ),
    "delta_shelter": (
        "rental_equivalence_introduced minus owner_outlays_removed. Not "
        "required to be zero and not adjusted."
    ),
    "secondary_residence_outlays_removed_without_replacement": (
        "Owned-vacation outlays leaving the basis under accepted rules while "
        "the secondary-residence rental-equivalence rule is still PENDING."
    ),
    "pending_proposed": "Under a PROPOSED rule: neither applied nor reversed.",
    "unresolved_open": "No disposition proposed at all.",
}

COMPARISON_QUANTITIES = tuple(COMPARISON_DEFINITIONS)


def write_comparison_csv(
    path: Path, accounting: Mapping[str, PopulationAccounting]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(COMPARISON_CSV_COLUMNS)
        for population in pumd.POPULATIONS:
            entry = accounting[population]
            for quantity in COMPARISON_QUANTITIES:
                writer.writerow(
                    [
                        population,
                        quantity,
                        _cell(getattr(entry, quantity)),
                        COMPARISON_DEFINITIONS[quantity],
                    ]
                )


def write_audit_csv(path: Path, rows: Sequence[AuditRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(AUDIT_CSV_COLUMNS)
        for row in rows:
            writer.writerow(
                [
                    row.category,
                    len(row.uccs),
                    " ".join(row.uccs),
                    _cell(row.all_cu_expenditure),
                    row.track_a_disposition,
                    row.track_b_disposition,
                    row.governing_rule or "",
                    row.basis_for_membership,
                    "yes" if row.is_open_item else "no",
                    row.double_counting_finding,
                ]
            )


def _json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_rule_adjudication(
    path: Path, verdicts: Mapping[str, RuleVerdict], registry: Mapping[str, object]
) -> None:
    _json(
        path,
        {
            "artifact_id": "SHELTER_RULE_ADJUDICATION_2024",
            "status": "RESEARCH_ONLY",
            "phase": "D4",
            "predecessor_registry": registry["artifact_id"],
            "predecessor_version": registry["version"],
            "the_dependency_milestone_2_named_but_never_wrote": (
                "All four rules reviewed here carried the same blocker: each "
                "'takes effect only jointly with the Track-A rental-equivalence "
                "rule'. The v0.1 registry contains ten rules and none of them "
                "is that rule. The condition was unsatisfiable as written, not "
                "because the evidence was missing but because the thing to be "
                "joint with did not exist. Phase D writes it, and writes it in "
                "two parts because the pinned BLS concordance already splits "
                "the concept in two: 910104 to the sampled ELI HC011 for the "
                "primary residence, and 910105 to 910107 to the unsampled "
                "residual HC090 for secondary residences."
            ),
            "what_acceptance_does_and_does_not_mean": (
                "An ACCEPTED rule moves expenditure between the accounting "
                "buckets of a research substrate. It does not compute an "
                "index, normalise a weight or touch the Operational Baseline, "
                "and it is reversible by a later versioned registry. That is "
                "not a reason to accept lightly, and the two rules held below "
                "are held for reasons that an amount becoming computable does "
                "not address."
            ),
            "verdicts": {
                rule_id: {
                    "rule_id": verdict.rule_id,
                    "review_status": verdict.review_status,
                    "resolution_state": verdict.resolution_state,
                    "is_applicable": verdict.is_applicable,
                    "evidence_strength": verdict.evidence_strength,
                    "evidence_strength_changed_in_this_task": (
                        verdict.evidence_strength_changed
                    ),
                    "materiality_all_cu_millions": verdict.materiality_all_cu,
                    "transition": verdict.transition,
                    "questions": [
                        {
                            "question": q.question,
                            "answer": q.answer,
                            "finding": q.finding,
                        }
                        for q in verdict.questions
                    ],
                    "blocker": verdict.blocker,
                    "warnings": list(verdict.warnings),
                }
                for rule_id, verdict in verdicts.items()
            },
            "accepted": sorted(
                r for r, v in verdicts.items() if v.review_status == ACCEPTED
            ),
            "held": sorted(
                r for r, v in verdicts.items() if v.review_status != ACCEPTED
            ),
        },
    )


def write_accounting_summary(
    path: Path,
    accounting: Mapping[str, PopulationAccounting],
    verdicts: Mapping[str, RuleVerdict],
    audit: Sequence[AuditRow],
) -> None:
    _json(
        path,
        {
            "artifact_id": "SHELTER_ACCOUNTING_SUMMARY_2024",
            "status": "RESEARCH_ONLY",
            "phase": "D2",
            "units": "millions of 2024 dollars, published CE aggregate basis",
            "no_balancing": (
                "Replacing an owner outlay concept with an imputed rental "
                "flow changes the size of the basis. delta_scope and "
                "delta_shelter are reported as they fall out. No rescaling, "
                "renormalisation, residual allocation or balancing factor was "
                "applied anywhere, and there is no requirement that either be "
                "zero. The only sums checked are that each total equals its "
                "own parts."
            ),
            "identity_source": (
                "e_source = retained + accepted_transformed + "
                "accepted_out_of_scope + pending_proposed + unresolved_open"
            ),
            "identity_cpi": (
                "e_cpi = retained + accepted_transformed + "
                "rental_equivalence_introduced"
            ),
            "identity_delta": (
                "delta_scope = e_cpi - e_source = "
                "rental_equivalence_introduced - accepted_out_of_scope - "
                "pending_proposed - unresolved_open. The last two terms are "
                "undecided, not out of scope, and are shown separately for "
                "that reason."
            ),
            "track_b_is_not_the_household_cost_index": TRACK_B_IS_NOT_THE_HCI,
            "disposition_semantics": DISPOSITION_SEMANTICS,
            "by_population": {
                population: {
                    field_name: getattr(entry, field_name)
                    for field_name in (
                        "e_source",
                        "retained",
                        "accepted_transformed",
                        "accepted_out_of_scope",
                        "pending_proposed",
                        "unresolved_open",
                        "rental_equivalence_introduced",
                        "rental_equivalence_withheld",
                        "owner_outlays_removed",
                        "e_cpi",
                        "delta_scope",
                        "delta_shelter",
                        "secondary_residence_outlays_removed_without_replacement",
                    )
                }
                for population, entry in accounting.items()
            },
            "rules_effective_in_this_accounting": sorted(
                r for r, v in verdicts.items() if v.review_status == ACCEPTED
            ),
            "rules_promoted_from_milestone_2_pending": sorted(
                r
                for r, v in verdicts.items()
                if v.review_status == ACCEPTED and r in PENDING_RULE_IDS
            ),
            "rules_written_new_in_this_task": sorted(
                r for r in verdicts if r not in PENDING_RULE_IDS
            ),
            "rules_held": sorted(
                r for r, v in verdicts.items() if v.review_status != ACCEPTED
            ),
            "double_counting_audit_categories": [row.category for row in audit],
            "open_items": [
                {
                    "category": row.category,
                    "all_cu_millions": row.all_cu_expenditure,
                    "finding": row.double_counting_finding,
                }
                for row in audit
                if row.is_open_item
            ],
        },
    )


# ---------------------------------------------------------------------------
# Versioned registries (D5)
# ---------------------------------------------------------------------------

LINEAGE_NOTE = (
    "This is a successor artifact, not an edit. The predecessor is preserved "
    "byte-for-byte at its own path and remains the Milestone-2 evidence of "
    "what was believed then. Every status that differs is listed below with "
    "the evidence that moved it."
)


def _new_track_a_rule(
    rule_id: str,
    uccs: Sequence[str],
    verdict: RuleVerdict,
    aggregates: Mapping[tuple[str, str], float | None],
    adjudication: Mapping[str, object],
    tenure: str,
    eli: str,
    eli_title: str,
) -> dict:
    withheld = set(adjudication["track_a_withheld"])  # type: ignore[index]
    quality = {
        ucc: entry["pumd_estimate_quality"]
        for ucc, entry in adjudication["adjudication"].items()  # type: ignore[index]
    }
    by_quintile = {
        population: sum(
            aggregates.get((ucc, population)) or 0.0
            for ucc in uccs
            if ucc not in withheld
        )
        for population in pumd.POPULATIONS[1:]
    }
    return {
        "rule_id": rule_id,
        "version": "0.1.0",
        "track": "SHELTER_COUPLED",
        "source_uccs": list(uccs),
        "source_labels": [
            adj.PUBLISHED_ITEM_TEXT.get(adj.PUBLISHED_OF[ucc], ucc) for ucc in uccs
        ],
        "final_status": "INTRODUCED",
        "rule_type": "INTRODUCE",
        "output_uccs": list(uccs),
        "output_node": "SHELTER",
        "destination_eli": eli,
        "destination_eli_title": eli_title,
        "tenure": tenure,
        "authoritative_basis": ["CE_CPI_CONCORDANCE_2024", "CASEY_2010"],
        "evidence_strength": verdict.evidence_strength,
        "suppression_status": "NONE",
        "review_status": verdict.review_status,
        "resolution_state": verdict.resolution_state,
        "is_applicable": verdict.is_applicable,
        "review_blocker": verdict.blocker,
        "materiality_all_cu": verdict.materiality_all_cu,
        "materiality_by_quintile": by_quintile,
        "materiality_source": (
            "Estimated from the 2024 CE Interview PUMD by the frozen "
            f"estimator, spec {est.SHELTER_SPEC_VERSION}. These are DMI "
            "estimates, not published BLS aggregates, and the distinction is "
            "why they are recorded in their own field rather than alongside "
            "the published materialities of the exclusion rules."
        ),
        "estimate_quality": {ucc: quality.get(ucc) for ucc in uccs},
        "withheld_uccs": sorted(u for u in uccs if u in withheld),
        "transformation_formula": (
            "Added: the estimated annual rental-equivalence aggregate for the "
            "admitted UCCs above. Removed: nothing. This rule introduces a "
            "concept; the outlays it displaces are removed by their own rules "
            "and no arithmetic here depends on those amounts."
        ),
        "assumptions": [
            "The amount introduced is the CE ADDENDA rental-equivalence "
            "aggregate. Whether BLS applies a further adjustment before this "
            "becomes a CPI expenditure weight is not established; the "
            "provenance registry records cpi_adjustment_status as INFERRED.",
            "A withheld UCC is not replaced by zero. Where one is listed in "
            "withheld_uccs the introduced amount is incomplete by that item "
            "and the rule says so rather than presenting a total.",
        ],
        "track_b": {
            "treatment": "NOT_INTRODUCED",
            "rationale": (
                "A household-payments concept imputes no rent. The absence is "
                "by construction, not a gap in the data."
            ),
        },
        "transition": verdict.transition,
    }


def build_scope_rules_v0_2(
    registry: Mapping[str, object],
    verdicts: Mapping[str, RuleVerdict],
    aggregates: Mapping[tuple[str, str], float | None],
    adjudication: Mapping[str, object],
) -> dict:
    payload = json.loads(json.dumps(registry))
    payload["artifact_id"] = "CE_CPI_SCOPE_RULES_V0_2"
    payload["version"] = "0.2.0"
    payload["milestone"] = (
        "Detailed Inflation Substrate v0.1, shelter task, Phase D"
    )
    payload["predecessor"] = {
        "artifact_id": registry["artifact_id"],
        "version": registry["version"],
        "path": "registry/research/ce_cpi_scope_rules_v0_1.json",
        "note": LINEAGE_NOTE,
    }
    payload["rule_type_semantics"]["INTRODUCE"] = (
        "The rule adds a concept to Track A that has no counterpart in the CE "
        "outlay basis. It removes nothing. Introduction and removal are "
        "separate rules on purpose, so that neither can be made to justify the "
        "other's size."
    )

    transitions: list[dict] = []
    rules = list(payload["rules"])
    for index, rule in enumerate(rules):
        rule_id = rule["rule_id"]
        if rule_id not in verdicts:
            continue
        verdict = verdicts[rule_id]
        before = {
            "review_status": rule.get("review_status"),
            "resolution_state": "PENDING"
            if rule.get("review_status") == PROPOSED
            else "EFFECTIVE",
            "evidence_strength": rule.get("evidence_strength"),
        }
        rule["review_status"] = verdict.review_status
        rule["resolution_state"] = verdict.resolution_state
        rule["is_applicable"] = verdict.is_applicable
        rule["review_blocker"] = verdict.blocker
        rule["phase_d_adjudication"] = {
            "transition": verdict.transition,
            "questions": [
                {"question": q.question, "answer": q.answer, "finding": q.finding}
                for q in verdict.questions
            ],
            "warnings": list(verdict.warnings),
        }
        rules[index] = rule
        after = {
            "review_status": verdict.review_status,
            "resolution_state": verdict.resolution_state,
            "evidence_strength": verdict.evidence_strength,
        }
        transitions.append(
            {
                "rule_id": rule_id,
                "from": before,
                "to": after,
                "status_changed": after != before,
                "evidence": verdict.transition,
                "remaining_blocker": verdict.blocker,
            }
        )

    primary = _new_track_a_rule(
        TRACK_A_PRIMARY_RULE_ID,
        ("910104",),
        verdicts[TRACK_A_PRIMARY_RULE_ID],
        aggregates,
        adjudication,
        PRIMARY_RESIDENCE,
        "HC011",
        "Owners' Equivalent Rent Of Primary Residence",
    )
    secondary = _new_track_a_rule(
        TRACK_A_SECONDARY_RULE_ID,
        ("910105", "910106", "910107"),
        verdicts[TRACK_A_SECONDARY_RULE_ID],
        aggregates,
        adjudication,
        SECONDARY_RESIDENCE,
        "HC090",
        "Unsampled residual shelter ELI",
    )
    payload["rules"] = [primary, secondary, *rules]
    payload["rule_reviews_from_v0_1"] = transitions
    payload["rule_reviews_note"] = (
        "All four shelter-coupled rules were reviewed. Two changed status and "
        "two did not. The two that did not are listed here anyway, with "
        "status_changed false, because a review that reaches 'no change' is a "
        "result and the reason it reached that result is the useful part. "
        "Calling all four entries transitions would have implied movement "
        "where there was none."
    )
    payload["rules_added_in_v0_2"] = [
        TRACK_A_PRIMARY_RULE_ID,
        TRACK_A_SECONDARY_RULE_ID,
    ]
    payload["why_two_rules_were_added"] = (
        "Every one of the four shelter-coupled rules in v0.1 was made "
        "conditional on 'the Track-A rental-equivalence rule'. No such rule was "
        "ever written. The condition could not be met by producing evidence, "
        "because there was nothing for the evidence to attach to. These two "
        "rules are that missing dependency, split along the split the pinned "
        "BLS concordance already makes between HC011 and HC090."
    )
    payload["coverage"]["rules_in_v0_2"] = len(payload["rules"])
    payload["coverage"]["introduce_rules_claim_no_expend_ucc"] = (
        "910104 to 910107 are CE ADDENDA lines and are not members of the "
        "EXPEND basis, so the introduce rules do not claim any UCC claimed by "
        "an exclusion or replacement rule and the Milestone-1 exception "
        "partition is unchanged."
    )
    return payload


def build_provenance_v0_3(
    provenance: Mapping[str, object],
    adjudication: Mapping[str, object],
    verdicts: Mapping[str, RuleVerdict],
) -> dict:
    payload = json.loads(json.dumps(provenance))
    payload["artifact_id"] = "UCC_PROVENANCE_CLASSES_V0_3"
    payload["version"] = "0.3.0"
    payload["milestone"] = (
        "Detailed Inflation Substrate v0.1, shelter task, Phases C and D"
    )
    payload["predecessor"] = {
        "artifact_id": provenance["artifact_id"],
        "version": provenance["version"],
        "path": "registry/research/ucc_provenance_classes_v0_1.json",
        "note": LINEAGE_NOTE,
    }
    payload["evidence_scales"]["pumd_estimate_quality"] = dict(
        adjudication["quality_scale_definition"]  # type: ignore[index]
    )
    payload["evidence_scales"]["quality_is_not_usability"] = adjudication[
        "quality_is_not_usability"
    ]

    verdict_of = dict(adjudication["adjudication"])  # type: ignore[arg-type]
    changed: list[dict] = []
    for entry in payload["concordance_only_uccs"]["roster"]:
        ucc = entry["ucc"]
        if ucc not in verdict_of:
            continue
        record = verdict_of[ucc]
        before = entry["pumd_quantitative_usability"]
        entry["pumd_membership_evidence"] = {
            "citation": (
                "data/research/detailed_inflation/shelter_2024/"
                "shelter_source_observation.json"
            ),
            "observation": (
                "This repository read the pinned 2024 CE Interview PUMD "
                "archive and reproduced the record count and the PUBFLAG "
                "value for this UCC in Phase C1."
            ),
            "reproduced_by_test": True,
            "evidence_kind": "REPRODUCED_ARCHIVE_OBSERVATION",
            "supersedes": (
                "The v0.1 entry recorded a PRIOR_MANUAL_SOURCE_OBSERVATION "
                "that this repository had never re-derived. It has now been "
                "re-derived from the archive, so the caveat that accompanied "
                "it no longer applies and has been removed rather than left "
                "standing as a false warning."
            ),
        }
        entry["pumd_quantitative_usability"] = record["pumd_quantitative_usability"]
        entry["pumd_quantitative_usability_note"] = record[
            "usability_finding"
        ] if "usability_finding" in record else (
            "Adjudicated in Phase C6 on structural grounds: whether a "
            "validated aggregation procedure reaches this UCC's records, and "
            "whether the replicate-weight variance estimator is "
            "non-degenerate. No relative standard error is read by either "
            "test."
        )
        entry["pumd_estimate_quality"] = record["pumd_estimate_quality"]
        entry["pumd_estimate_quality_by_population"] = record[
            "per_population_quality"
        ]
        entry["track_a_admissible"] = record["track_a_admissible"]
        entry["phase_c6_tests"] = [
            {"name": t["name"], "passed": t["passed"], "finding": t["finding"]}
            for t in record["tests"]
        ]
        if before != entry["pumd_quantitative_usability"]:
            changed.append(
                {
                    "ucc": ucc,
                    "from": before,
                    "to": entry["pumd_quantitative_usability"],
                }
            )
    payload["usability_transitions_from_v0_1"] = changed
    payload["usability_transitions_note"] = (
        "The transitions are not uniform, which is the finding. Three of the "
        "four shelter UCCs became BENCHMARKED and one did not. A blanket "
        "promotion would have been easier to write and would have concealed "
        "that 910106's first-quintile cell has no records at all and its "
        "second-quintile cell has 22 of 44 replicate estimates at exactly "
        "zero."
    )

    correspondence = payload["shelter_rental_equivalence_correspondence"]
    correspondence["measured_in_phase_c6"] = {
        "note": (
            "The pairing entered this workstream as a DMI_INFERENCE resting on "
            "matching concept names and matching order. Phase C6 measured it "
            "at the record level, after the estimates already existed. The "
            "claim_type is unchanged, because a measurement of a relation is "
            "not a BLS statement that the relation is the intended one."
        ),
        "relations": dict(adjudication["pair_structure"]),  # type: ignore[arg-type]
    }
    correspondence["published_addenda_anomaly_resolution"] = (
        "The preserved anomaly was that 910103 is titled an annual rental "
        "value while its siblings are titled monthly. Phase C6 measured 52 "
        "times the record-level ratio of 910107 to 910103 and found a whole "
        "number on 87.6 percent of 590 shared consumer-unit months, "
        "distributed as 1, 2, 3, 4, 6, 7 and 12. Those are weeks of a "
        "timeshare owned. 910103 is the whole property's annual rental value; "
        "910107 is the share this consumer unit owns. They are different "
        "estimands, which is why neither was used to manufacture the other and "
        "why the prohibition on doing so was substantively right rather than "
        "merely cautious."
    )
    payload["consumer_of_this_artifact"] = (
        "registry/research/ce_cpi_scope_rules_v0_2.json, whose two "
        "rental-equivalence introduce rules read pumd_quantitative_usability "
        "and pumd_estimate_quality from here."
    )
    return payload
