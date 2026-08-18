#!/usr/bin/env python3
"""Residual Track-A shelter allocation questions: owner maintenance, homeowners
insurance, and secondary residence.

Detailed Inflation Substrate v0.1, shelter residuals task, Phase B.

RESEARCH ONLY. Reads the frozen shelter-milestone artifacts, the pinned scope-rule
registry ``ce_cpi_scope_rules_v0_2.json``, the pinned CE-to-CPI concordance and the
published CE aggregate basis. Writes only under ``data/research/`` and
``registry/research/``, at new paths. Nothing here touches ``dmi_calculator``, the
Baseline, Slack-Plus, any release workflow or the deployment output tree. No index
is computed, no weight is normalised and no category inflation rate exists.

Four things are worth reading before the code.

*The predecessor registries are inputs, not targets.* ``ce_cpi_scope_rules_v0_2``
and ``ucc_provenance_classes_v0_3`` are the frozen shelter-milestone state. This
module reads them and writes ``_v0_3`` and ``_v0_4`` successors at new paths. It
never edits a predecessor, and re-running the milestone build must still reproduce
the predecessors byte for byte.

*Evidence carries a vintage, and vintage is load-bearing.* A BLS document that
once stated a numerical factor does not thereby authorise applying that factor to
the 2024 weighting vintage. Every evidence record in this module declares one of
``CURRENT_2024_COMPATIBLE``, ``CURRENT_BUT_NONNUMERIC``, ``HISTORICAL_ONLY``,
``DMI_INFERENCE`` or ``NOT_FOUND``, and the rule outcomes are derived from those
classes rather than from the existence of a source.

*Absence of a published parameter is not permission to invent one.* Where BLS
states that an adjustment is made but does not publish its value, the outcome
here is ``BLOCKED_BY_UNPUBLISHED_PARAMETER``. No factor is approximated,
interpolated, copied forward from a superseded vintage, or backed out of a
residual. Two of the three questions this module examines end that way, and that
is the finding rather than a failure to reach one.

*Nothing in this module moves Delta_scope or Delta_shelter.* Promoting a rule from
PROPOSED to ACCEPTED-out-of-scope moves an amount between two buckets that both
sit outside the CPI-basis total, so the CPI basis and both deltas are arithmetically
untouched. That is asserted and tested, not hoped for. There is no rescaling,
renormalisation, balancing factor or residual-allocating step anywhere in this file.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from . import pumd
from .concordance import load_concordance

REPO_ROOT = Path(__file__).resolve().parents[2]

SCOPE_RULES_V0_2_PATH = REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_2.json"
SCOPE_RULES_V0_3_PATH = REPO_ROOT / "registry/research/ce_cpi_scope_rules_v0_3.json"
PROVENANCE_V0_3_PATH = REPO_ROOT / "registry/research/ucc_provenance_classes_v0_3.json"
PROVENANCE_V0_4_PATH = REPO_ROOT / "registry/research/ucc_provenance_classes_v0_4.json"
EVIDENCE_PATH = REPO_ROOT / "registry/research/shelter_residual_evidence_v0_1.json"

BASIS_PATH = REPO_ROOT / "data/research/detailed_inflation/audit_2024/active_ucc_basis.csv"
SHELTER_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
ACCOUNTING_SUMMARY_PATH = SHELTER_DIR / "shelter_accounting_summary.json"

RESIDUALS_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_residuals_2024"
UCC_MATRIX_PATH = RESIDUALS_DIR / "owner_structure_ucc_matrix_2024.csv"
RULE_TRANSITIONS_PATH = RESIDUALS_DIR / "residual_rule_transitions.csv"
BEFORE_AFTER_PATH = RESIDUALS_DIR / "residual_accounting_before_after_2024.csv"
VERDICT_PATH = RESIDUALS_DIR / "residual_shelter_verdict.json"

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

VINTAGE_CLASSES = (
    "CURRENT_2024_COMPATIBLE",
    "CURRENT_BUT_NONNUMERIC",
    "HISTORICAL_ONLY",
    "DMI_INFERENCE",
    "NOT_FOUND",
)

VINTAGE_SEMANTICS = {
    "CURRENT_2024_COMPATIBLE": (
        "A current BLS source states the thing claimed, and the statement is "
        "applicable to the 2024 CE-to-CPI weighting vintage. This class may "
        "support an ACCEPTED rule."
    ),
    "CURRENT_BUT_NONNUMERIC": (
        "A current BLS source states that a treatment exists and describes it "
        "in words, but publishes no number that could be applied. This class "
        "establishes a concept and blocks a computation at the same time."
    ),
    "HISTORICAL_ONLY": (
        "A primary BLS source states the thing claimed, but for a superseded "
        "vintage. It establishes that a procedure once existed. It never "
        "authorises applying a numerical factor to 2024."
    ),
    "DMI_INFERENCE": (
        "The claim is a DMI reading of BLS material rather than a BLS "
        "statement. Recorded so a reader can see exactly which link in a "
        "chain is ours."
    ),
    "NOT_FOUND": (
        "Searched for and not located in any primary BLS source. This is a "
        "recorded negative result, not an invitation to substitute a value."
    ),
}

EVIDENTIARY_ROLES = ("PRIMARY", "CORROBORATING")

EVIDENTIARY_ROLE_SEMANTICS = {
    "PRIMARY": (
        "A BLS source states the treatment itself. A record in this role can "
        "carry a scope conclusion on its own."
    ),
    "CORROBORATING": (
        "The record is consistent with a treatment stated elsewhere and "
        "sharpens it, typically at the code level, but does not state the "
        "treatment. A record in this role may not carry a scope conclusion "
        "on its own. Concordance absence is the paradigm case: no row is a "
        "fact about the crosswalk, and a concept can still receive CPI "
        "expenditure weight through a production transformation that the "
        "crosswalk does not display."
    ),
}

BLOCKER_KINDS = {
    "BLOCKED_BY_UNPUBLISHED_PARAMETER": (
        "BLS states that a transformation is applied but does not publish the "
        "number. The concept is established; the arithmetic is not available. "
        "Parameter uncertainty."
    ),
    "BLOCKED_BY_DEGENERATE_VARIANCE": (
        "A microdata estimate this rule depends on failed its usability tests "
        "because the replicate-based variance estimator is degenerate rather "
        "than merely imprecise. Sampling uncertainty."
    ),
    "BLOCKED_BY_UNESTABLISHED_CONCEPT": (
        "No BLS source states how the CPI treats this concept at all. Not a "
        "missing number: a missing treatment."
    ),
    "BLOCKED_BY_CONTRADICTORY_MEMBERSHIP": (
        "The BLS concept is stated, but the code-level signals point both "
        "ways, so which side of the boundary this UCC falls on is not "
        "determinable from the published record."
    ),
}


@dataclass(frozen=True)
class Evidence:
    """One evidentiary claim, with the vintage that governs how it may be used."""

    evidence_id: str
    issue: str
    claim: str
    vintage_class: str
    source_title: str
    source_locator: str
    source_date: str
    quoted_passage: str
    establishes: str
    does_not_establish: str
    evidentiary_role: str = "PRIMARY"

    def __post_init__(self) -> None:
        if self.vintage_class not in VINTAGE_CLASSES:
            raise ValueError(f"unknown vintage class {self.vintage_class!r}")
        if self.evidentiary_role not in EVIDENTIARY_ROLES:
            raise ValueError(
                f"unknown evidentiary role {self.evidentiary_role!r}"
            )


# --------------------------------------------------------------------------
# Evidence located in this task
# --------------------------------------------------------------------------

OER_FACTSHEET = "https://www.bls.gov/cpi/factsheets/owners-equivalent-rent-and-rent.htm"
TENANTS_FACTSHEET = "https://www.bls.gov/cpi/factsheets/tenants-household-insurance.htm"
CONCORDANCE_LOCATOR = (
    "registry/research/ucc_eli_concordance_2024_v0_1.tsv, normalised from the "
    "pinned BLS workbook ce-cpi-concordance-August-2026.xlsx sheet UTEM_2024 "
    "(CPI Handbook of Methods Appendix 5)"
)

EVIDENCE: tuple[Evidence, ...] = (
    # -- Issue 1: owner maintenance and structure investment ---------------
    Evidence(
        evidence_id="OER_FS_MAINTENANCE_OUT_OF_SCOPE",
        issue="owner_maintenance",
        claim=(
            "The CPI treats most owner maintenance and all owner improvement "
            "costs as non-consumption and out of scope."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="Measuring Price Change in the CPI: Rent and rental equivalence",
        source_locator=OER_FACTSHEET,
        source_date="retrieved 2026-08-17; relative-importance table dated December 2025",
        quoted_passage=(
            "Interest costs (such as mortgage interest), property taxes, real "
            "estate fees, most maintenance, and all improvement costs are part "
            "of the cost of the capital good and are also not treated as "
            "consumption items. These non-consumption costs of owned housing "
            "are out of scope for the CPI under the cost-of-living framework "
            "that guides the index."
        ),
        establishes=(
            "The exclusion concept, stated by BLS in a current document, for "
            "owner maintenance as a class."
        ),
        does_not_establish=(
            "Which maintenance. The word is 'most', not 'all', so this "
            "sentence cannot by itself place any particular UCC on either "
            "side of the boundary."
        ),
    ),
    Evidence(
        evidence_id="TENANTS_FS_MAINTENANCE_OUT_OF_SCOPE",
        issue="owner_maintenance",
        claim=(
            "A second current BLS factsheet independently states that most "
            "home maintenance and repair spending is out of scope, and "
            "attributes the exclusion to the rental-equivalence approach."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="Measuring Price Change in the CPI: Tenant's and Household Insurance",
        source_locator=TENANTS_FACTSHEET,
        source_date="Last Modified Date: May 20, 2026",
        quoted_passage=(
            "The rental equivalence approach used to measure price change in "
            "the cost of owner-occupied shelter renders household insurance "
            "for residential structures, along with most spending on home "
            "maintenance and repairs, out of scope."
        ),
        establishes=(
            "That the exclusion concept is not an artefact of a single "
            "document, and that its stated cause is rental equivalence."
        ),
        does_not_establish="Which maintenance, for the same reason.",
    ),
    Evidence(
        evidence_id="CONCORDANCE_2024_UNMAPPED_MAINTENANCE_SERVICES",
        issue="owner_maintenance",
        claim=(
            "In the pinned 2024-vintage concordance, owner maintenance "
            "services 230113, 230114, 230115 and 230151 have no direct CPI "
            "entry level item mapping, while nearby owner and renter "
            "maintenance concepts do. This corroborates the current BLS scope "
            "statement at the code level. It is not by itself proof that a "
            "concept receives no CPI expenditure weight through any "
            "production transformation."
        ),
        evidentiary_role="CORROBORATING",
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="CPI Handbook of Methods Appendix 5, CE UCC to CPI ELI concordance",
        source_locator=CONCORDANCE_LOCATOR,
        source_date=(
            "workbook vintage note: the CPI item structure introduced for 2024 "
            "annual expenditure weights, used in indexes starting January 2026"
        ),
        quoted_passage=(
            "No row exists for UCC 230113, 230114, 230115 or 230151 in sheet "
            "UTEM_2024. Recomputed on every run by this module rather than "
            "quoted from a snapshot."
        ),
        establishes=(
            "Corroboration, at the code level, for the membership the "
            "factsheet sentence leaves open. BLS's own crosswalk publishes "
            "no direct mapping for these four, which is what the factsheet "
            "statement predicts."
        ),
        does_not_establish=(
            "Exclusion, by itself. Absence of a row is a fact about the "
            "crosswalk, not a stated rationale and not a demonstration that "
            "no CPI expenditure weight reaches the concept by some other "
            "production route. The scope conclusion rests on the factsheets; "
            "this record only agrees with them."
        ),
    ),
    Evidence(
        evidence_id="COUNTERPART_TEST_FALSIFIED",
        issue="owner_maintenance",
        claim=(
            "The clearing criterion recorded in "
            "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1 -- that no renter "
            "counterpart exists for the maintenance members -- does not "
            "distinguish the excluded UCCs from the included ones and is "
            "therefore falsified."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title=(
            "CE 2024 integrated stub CE-HG-Integ-2024.txt with the pinned "
            "concordance"
        ),
        source_locator=CONCORDANCE_LOCATOR,
        source_date="2024 CE stub and 2024-vintage concordance",
        quoted_passage=(
            "Under CE stub container OWNREPSV, 230112 'Painting and papering' "
            "is mapped to HP043 while 230113, 230114, 230115 and 230151 are "
            "unmapped. The renter branch RNTREPSV carries a single generic "
            "code 230150 'Repair or maintenance services', also mapped to "
            "HP043, so all five owner service codes share an identical "
            "counterpart structure. Separately, owner commodity 240213 "
            "'Materials and equipment for roofs and gutters' is unmapped "
            "although its renter counterpart 240211 'Materials for "
            "plastering, panels, roofing, and gutters, etc.' is mapped to "
            "HM090, and the owner sibling 240212 is mapped to HM090 as well."
        ),
        establishes=(
            "That counterpart existence predicts neither exclusion nor "
            "inclusion, so the rule's stated evidentiary basis must be "
            "replaced rather than merely strengthened."
        ),
        does_not_establish=(
            "A substitute criterion. None is invented here; the concordance "
            "is read directly instead."
        ),
    ),
    Evidence(
        evidence_id="CASEY_NOTE_5_MAINTENANCE_ALLOCATION_FACTOR",
        issue="owner_maintenance",
        claim=(
            "A historical BLS paper states that an allocation factor removes "
            "the investment element from owner home maintenance, and that "
            "owner maintenance weights are built from renter mean "
            "expenditures."
        ),
        vintage_class="HISTORICAL_ONLY",
        source_title=(
            "Casey, W., An Overview of the CPI's Requirements of the Consumer "
            "Expenditure Survey, U.S. Bureau of Labor Statistics"
        ),
        source_locator=(
            "registry/research/ce_cpi_scope_rules_v0_2.json, sources.CASEY_2010, "
            "quoted_passages entries 5 and 10"
        ),
        source_date="2010",
        quoted_passage=(
            "Appendix B note 5: 'Maintenance to one's home can be considered "
            "an investment. For this reason, an allocation factor is applied "
            "to remove investment expense from the total consumption "
            "expenditure.' And: 'Owner expenditures on major appliances and "
            "home maintenance and repair are based on the corresponding mean "
            "expenditures of renters and likelihood of renters to purchase "
            "those types of appliances.'"
        ),
        establishes=(
            "That the owner maintenance UCCs which ARE mapped may carry a CPI "
            "weight different from their CE amount. Track A retains those at "
            "full CE value, so this opens a new item rather than closing one."
        ),
        does_not_establish=(
            "Anything about 2024. The CE vintage this paper describes is "
            "superseded, and no current source restates the procedure."
        ),
    ),
    Evidence(
        evidence_id="RENTER_MEAN_WEIGHTING_CURRENT_VINTAGE",
        issue="owner_maintenance",
        claim=(
            "Whether the CPI still builds owner maintenance weights from "
            "renter mean expenditures in the 2024 weighting vintage."
        ),
        vintage_class="NOT_FOUND",
        source_title="(searched; not located)",
        source_locator=(
            "CPI Handbook of Methods concepts, design, calculation and data "
            "sources sections; CPI factsheet index; CPI additional resources "
            "index; rent and OER questions and answers; methodology change "
            "notices 2017-2025"
        ),
        source_date="searched 2026-08-17",
        quoted_passage="",
        establishes="Nothing. Recorded so the gap is visible and citable.",
        does_not_establish=(
            "That the procedure lapsed. Not finding a restatement is not "
            "evidence of withdrawal, and neither reading may be acted on."
        ),
    ),
    # -- Issue 2: homeowners insurance --------------------------------------
    Evidence(
        evidence_id="CASEY_NOTE_3_INSURANCE_43_PCT",
        issue="homeowners_insurance",
        claim=(
            "The historical BLS source for the 43% treatment. It applies to "
            "the CPI expenditure weight for homeowners insurance, not to a "
            "price movement, and it retains the renter's part of the owner's "
            "expenditure."
        ),
        vintage_class="HISTORICAL_ONLY",
        source_title=(
            "Casey, W., An Overview of the CPI's Requirements of the Consumer "
            "Expenditure Survey, U.S. Bureau of Labor Statistics"
        ),
        source_locator=(
            "registry/research/ce_cpi_scope_rules_v0_2.json, sources.CASEY_2010, "
            "quoted_passages entry 8; Appendix B note 3"
        ),
        source_date="2010",
        quoted_passage=(
            "Appendix B note 3: 'It is required that CPI reduce the "
            "homeowners insurance weight to reflect only the renter's part of "
            "the owner's expenditure. The factor applied is 43%.'"
        ),
        establishes=(
            "That a renter's-part allocation on the homeowners-insurance "
            "expenditure weight is a real BLS procedure with a stated value, "
            "and that the quantity adjusted is the weight."
        ),
        does_not_establish=(
            "That 43% governs 2024. The Casey Appendix B UCC lists describe a "
            "superseded CE vintage, and the derivation was replaced in "
            "January 2025 -- see INSURANCE_NAIC_METHOD_SINCE_2025."
        ),
    ),
    Evidence(
        evidence_id="INSURANCE_PARTIAL_INCLUSION_CURRENT",
        issue="homeowners_insurance",
        claim=(
            "The renter's-part allocation concept is current: BLS states that "
            "only a portion of homeowner insurance spending enters the CPI "
            "weight, and gives rental equivalence as the reason."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="Measuring Price Change in the CPI: Tenant's and Household Insurance",
        source_locator=TENANTS_FACTSHEET,
        source_date="Last Modified Date: May 20, 2026",
        quoted_passage=(
            "Spending by renters on tenants' insurance is included. Only a "
            "portion of spending by homeowners on homeowner's insurance is "
            "included to reflect the scope of owner's equivalent rent."
        ),
        establishes=(
            "That the conceptual treatment survives to the current vintage, "
            "and that the in-scope portion is strictly between nothing and "
            "everything."
        ),
        does_not_establish="The size of the portion.",
    ),
    Evidence(
        evidence_id="INSURANCE_NAIC_METHOD_SINCE_2025",
        issue="homeowners_insurance",
        claim=(
            "The derivation of the factor changed in January 2025 and is now "
            "based on National Association of Insurance Commissioners data. "
            "The method is described in words; the resulting factor is not "
            "published."
        ),
        vintage_class="CURRENT_BUT_NONNUMERIC",
        source_title="Measuring Price Change in the CPI: Tenant's and Household Insurance",
        source_locator=TENANTS_FACTSHEET,
        source_date="Last Modified Date: May 20, 2026",
        quoted_passage=(
            "Since January 2025, information and data from the National "
            "Association of Insurance Commissioners are used to calculate a "
            "factor applied to the total spending by homeowners on "
            "homeowner's insurance to derive the portion of insurance premium "
            "that accounts for contents coverage. For each range of coverage "
            "for homeowner's policies, the typical coverage limit for "
            "personal property is approximately 50 percent of the value of "
            "the dwelling. After adjusting average homeowner's premiums to "
            "reflect the in-scope portion, ratios of average renter's "
            "premiums to average adjusted homeowner's premiums by each range "
            "of coverage are determined. The median value of those ratios is "
            "the adjustment factor applied to spending by homeowners on "
            "homeowner's insurance."
        ),
        establishes=(
            "That the 2010 factor is superseded, so Outcome A is excluded "
            "affirmatively rather than merely unproven; and that the current "
            "method is a median of premium ratios, which cannot be evaluated "
            "from public data."
        ),
        does_not_establish=(
            "Any number. The 50 percent in this passage is a typical personal-"
            "property coverage limit used at an intermediate step, not the "
            "adjustment factor applied to spending. Reading it as the factor "
            "would be exactly the substitution this task forbids."
        ),
    ),
    Evidence(
        evidence_id="INSURANCE_CONTENTS_ONLY_SCOPE",
        issue="homeowners_insurance",
        claim=(
            "Only contents coverage is in CPI scope. Structure physical "
            "damage and liability coverage carried inside homeowners policies "
            "are excluded."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="Measuring Price Change in the CPI: Tenant's and Household Insurance",
        source_locator=TENANTS_FACTSHEET,
        source_date="Last Modified Date: May 20, 2026",
        quoted_passage=(
            "Therefore, insurance on physical damage to structures and "
            "liability coverage included in homeowners' policies as well as "
            "insurance on commercial properties are excluded from the index."
        ),
        establishes=(
            "The meaning of the in-scope portion, and it resolves an "
            "ambiguity: the Handbook Appendix 2 description of ELI HD011 does "
            "not say whether the whole homeowners policy or only the "
            "tenant-equivalent part is in scope. This factsheet says."
        ),
        does_not_establish="The size of the contents share of a premium.",
    ),
    Evidence(
        evidence_id="INSURANCE_FACTOR_VALUE_2024_VINTAGE",
        issue="homeowners_insurance",
        claim="The numerical value of the factor governing the 2024 weighting vintage.",
        vintage_class="NOT_FOUND",
        source_title="(searched; not located)",
        source_locator=(
            "CPI tenants' and household insurance factsheet; CPI relative "
            "importance documentation; CPI Handbook of Methods; CPI "
            "additional resources index; CPI methodology change notices for "
            "2024 and 2025; pinned CE-to-CPI concordance workbook footnotes"
        ),
        source_date="searched 2026-08-17",
        quoted_passage="",
        establishes=(
            "That the transformation is blocked on a parameter BLS describes "
            "but does not publish."
        ),
        does_not_establish=(
            "Permission to reuse 43%, to read the factor off the published "
            "relative importance of 0.292, or to pick any other value."
        ),
    ),
    Evidence(
        evidence_id="INSURANCE_METHOD_APPLIES_TO_2024_WEIGHTS",
        issue="homeowners_insurance",
        claim=(
            "The NAIC-based method, rather than any earlier method, is the "
            "one that governs the CE 2024 expenditure weighting vintage."
        ),
        vintage_class="DMI_INFERENCE",
        source_title=(
            "DMI inference chaining three current BLS statements. The three "
            "statements are BLS. The chain is not."
        ),
        source_locator=(
            "CPI rent and OER questions and answers (upper-level weights are "
            "updated annually with the publication of January indexes); "
            "pinned concordance workbook vintage note (2024 annual "
            "expenditure weights are used in indexes starting January 2026); "
            "tenants' insurance factsheet (NAIC method in use since January "
            "2025, document current as of May 2026)"
        ),
        source_date="2026-08-17",
        quoted_passage="",
        establishes=(
            "That the 2024 weighting vintage postdates the method change, so "
            "the superseding is not merely chronological trivia: it bears "
            "directly on the vintage this workstream weights."
        ),
        does_not_establish=(
            "Anything BLS said. No BLS document states 'the 2024 weights use "
            "the NAIC factor'. This link is ours and is labelled as ours."
        ),
    ),
    # -- Issue 3: secondary residence ---------------------------------------
    Evidence(
        evidence_id="SECONDARY_OER_IN_CURRENT_CPI",
        issue="secondary_residence",
        claim=(
            "Secondary-residence rental equivalence remains part of the "
            "current CPI architecture, under ELI HC090, and BLS names all "
            "three source UCCs."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="Measuring Price Change in the CPI: Rent and rental equivalence",
        source_locator=OER_FACTSHEET + " (footnote 1 to the relative importance table)",
        source_date="relative importance as of December 2025; retrieved 2026-08-17",
        quoted_passage=(
            "Rental equivalence for vacation homes and timeshares exist as "
            "items in the Consumer Expenditure Survey (UCC 910105, 910106, "
            "and 910107) and have a small amount of weight in the CPI as "
            "Unsampled owners' equivalent rent of secondary residences (ELI "
            "HC090), but as this item is unsampled, no price quotes are "
            "actually collected for it."
        ),
        establishes=(
            "Three things at once. The concept is current. The three UCCs are "
            "named by BLS rather than inferred. And the competing reading "
            "recorded in RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1 -- that "
            "owned-vacation outlays might simply be excluded as real-estate "
            "investment rather than displaced by an equivalence concept -- is "
            "resolved in favour of displacement, because the displacing item "
            "demonstrably exists and carries weight."
        ),
        does_not_establish=(
            "The consumption-portion factor, which this footnote neither "
            "states nor denies."
        ),
    ),
    Evidence(
        evidence_id="SECONDARY_TYPES_POOLED_AND_UNSAMPLED",
        issue="secondary_residence",
        claim=(
            "The three secondary-residence types are not treated differently "
            "from one another in the CPI item structure: all three map to the "
            "single ELI HC090, which is unsampled. The primary residence is a "
            "separate, sampled ELI HC011."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title=(
            "CPI Handbook of Methods Appendix 5 concordance, with the OER "
            "factsheet footnote"
        ),
        source_locator=CONCORDANCE_LOCATOR,
        source_date="2024-vintage concordance",
        quoted_passage=(
            "910105, 910106 and 910107 all map to HC090 'Unsampled Owners' "
            "Equivalent Rent Of Secondary Residence'; 910104 maps to HC011 "
            "'Owners' Equivalent Rent Of Primary Residence'. Recomputed on "
            "every run by this module."
        ),
        establishes=(
            "That no residence-type-specific CPI treatment exists to look "
            "for, which answers one of the questions this task asked."
        ),
        does_not_establish=(
            "That the consumption-portion factor is likewise uniform across "
            "the three types. Pooling at the ELI does not entail pooling at "
            "the adjustment."
        ),
        evidentiary_role="CORROBORATING",
    ),
    Evidence(
        evidence_id="OWNED_VACATION_BRANCH_FULLY_UNMAPPED",
        issue="secondary_residence",
        claim=(
            "Every UCC in the CE owned-vacation-home branch is unmapped in "
            "the pinned 2024 concordance, with no exceptions."
        ),
        vintage_class="CURRENT_2024_COMPATIBLE",
        source_title="CE 2024 integrated stub with the pinned concordance",
        source_locator=CONCORDANCE_LOCATOR,
        source_date="2024 CE stub and 2024-vintage concordance",
        quoted_passage=(
            "Containers OWVHOME, OWNVMORT, OWVEXPEN, OWVREPSV, OWVREPSP, "
            "OWVMISC and OWVMNAGE. The count and the member list are "
            "recomputed on every run by this module rather than asserted."
        ),
        establishes=(
            "Corroboration for a displacement by rental equivalence: the "
            "outlay branch is absent from the crosswalk exactly where "
            "displacement predicts it would be, and the displacing item "
            "HC090 is present. The conclusion is carried by the footnote "
            "that names HC090, not by this absence."
        ),
        does_not_establish=(
            "That the outlay concept receives no CPI expenditure weight by "
            "any route. A branch can be absent from the crosswalk and still "
            "be reached by a production transformation the crosswalk does "
            "not display. Nor the replacement amount: a complete absence on "
            "the outlay side says nothing about the size of the equivalence "
            "side."
        ),
        evidentiary_role="CORROBORATING",
    ),
    Evidence(
        evidence_id="CASEY_NOTE_2_CONSUMPTION_PORTION",
        issue="secondary_residence",
        claim=(
            "The historical source for the secondary-residence consumption-"
            "portion factor."
        ),
        vintage_class="HISTORICAL_ONLY",
        source_title=(
            "Casey, W., An Overview of the CPI's Requirements of the Consumer "
            "Expenditure Survey, U.S. Bureau of Labor Statistics"
        ),
        source_locator=(
            "registry/research/ce_cpi_scope_rules_v0_2.json, sources.CASEY_2010, "
            "quoted_passages entry 7; Appendix B note 2"
        ),
        source_date="2010",
        quoted_passage=(
            "Appendix B note 2: 'In order to price the rental equivalence of "
            "secondary homes and timeshares, CPI uses a factor to account for "
            "the consumption portion of a homeowner's total expenditure.'"
        ),
        establishes=(
            "That a factor exists as a concept, and that it is specific to "
            "secondary homes and timeshares rather than applying to the "
            "primary residence."
        ),
        does_not_establish=(
            "Its value, its sign convention, whether it is applied before or "
            "after survey weighting, whether it varies by residence type, or "
            "that it still operates."
        ),
    ),
    Evidence(
        evidence_id="SECONDARY_CONSUMPTION_FACTOR_CURRENT_VINTAGE",
        issue="secondary_residence",
        claim=(
            "The current value of the secondary-residence consumption-portion "
            "factor, the stage at which it is applied, and whether it differs "
            "by residence type."
        ),
        vintage_class="NOT_FOUND",
        source_title="(searched; not located)",
        source_locator=(
            "CPI rent and rental equivalence factsheet including its footnotes; "
            "CPI rent and OER questions and answers; CPI Handbook of Methods "
            "concepts, design, calculation and data sources; CPI additional "
            "resources index; pinned concordance workbook, whose only trailer "
            "note concerns multi-ELI allocation and is not attached to any "
            "910xxx row"
        ),
        source_date="searched 2026-08-17",
        quoted_passage="",
        establishes=(
            "That the replacement amount cannot be reproduced from the "
            "published record, independently of the microdata problem."
        ),
        does_not_establish=(
            "Permission to derive the factor from the published relative "
            "importance of 0.973, from the 910101-910103 published addenda, "
            "from the 910105-910107 microdata, or from any historical ratio."
        ),
    ),
    Evidence(
        evidence_id="UCC_910106_DEGENERATE_VARIANCE",
        issue="secondary_residence",
        claim=(
            "910106 is inadmissible for a reason that has nothing to do with "
            "the missing factor: its replicate-based variance estimator is "
            "degenerate."
        ),
        vintage_class="DMI_INFERENCE",
        source_title="DMI shelter task Phase C6 usability tests",
        source_locator=(
            "registry/research/ucc_provenance_classes_v0_3.json and "
            "ce_cpi_scope_rules_v0_2.json rule review blockers"
        ),
        source_date="2026, this workstream",
        quoted_passage=(
            "The Q1 cell has no records. The Q2 cell has 22 of 44 replicate "
            "estimates at exactly zero. Phase C6 additionally measured the "
            "910106-to-910102 record-level relation as NO_CLEAN_RELATION, "
            "against TWELVE_TIMES for 910105 and WEEKS_OWNED_SHARE for "
            "910107."
        ),
        establishes=(
            "Sampling uncertainty, which is a different limitation from "
            "parameter uncertainty and is kept in its own blocker so that "
            "resolving one is not mistaken for resolving the other."
        ),
        does_not_establish=(
            "Anything about the consumption-portion factor. Even a perfect "
            "910106 estimate would leave that factor missing."
        ),
    ),
)


# --------------------------------------------------------------------------
# Successor rules
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SuccessorRule:
    """One narrower rule carved out of a predecessor, with its own outcome."""

    rule_id: str
    predecessor_rule_id: str
    predecessor_status: str
    successor_status: str
    effect_state: str
    rule_type: str
    category: str
    source_uccs: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_strength: str
    final_status: str
    numerical_treatment_computable: bool
    blocker_kind: str | None
    rationale: str


PREDECESSOR_STRUCTURE_RULE = "OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1"

SUCCESSOR_RULES: tuple[SuccessorRule, ...] = (
    SuccessorRule(
        rule_id="OS_CPI_OWNER_MAINTENANCE_SERVICES_v0_2",
        predecessor_rule_id=PREDECESSOR_STRUCTURE_RULE,
        predecessor_status="PROPOSED",
        successor_status="ACCEPTED",
        effect_state="EFFECTIVE",
        rule_type="EXCLUDE",
        category="maintenance_and_repair_services",
        source_uccs=("230113", "230114", "230115", "230151"),
        evidence_ids=(
            "OER_FS_MAINTENANCE_OUT_OF_SCOPE",
            "TENANTS_FS_MAINTENANCE_OUT_OF_SCOPE",
            "CONCORDANCE_2024_UNMAPPED_MAINTENANCE_SERVICES",
            "COUNTERPART_TEST_FALSIFIED",
        ),
        evidence_strength="MODERATE",
        final_status="OUT_OF_SCOPE",
        numerical_treatment_computable=True,
        blocker_kind=None,
        rationale=(
            "Current BLS methodology places most owner maintenance outside "
            "CPI consumption scope: two independent current factsheets state "
            "it and attribute the exclusion to rental equivalence. The "
            "pinned 2024-vintage CE-to-CPI concordance provides corroborating "
            "UCC-level evidence for the membership the word 'most' leaves "
            "open: these four have no direct ELI mapping while nearby owner "
            "and renter maintenance concepts do. DMI accepts these four as "
            "out of scope on the combined evidence. Absence of a concordance "
            "row is corroborating evidence and is not, by itself, proof that "
            "a concept receives no CPI expenditure weight through any "
            "production transformation; the scope conclusion here rests on "
            "the factsheets, which the crosswalk agrees with. That is the "
            "same evidentiary shape as the already-accepted mortgage-interest "
            "and property-tax rules, a current BLS scope statement joined to "
            "unmapped status, and the required transformation is removal, "
            "which needs no parameter. The predecessor's own criterion, the "
            "renter-counterpart test, is discarded rather than relied on: it "
            "is falsified by 230112, which shares the identical counterpart "
            "structure and is mapped. Graded MODERATE, not STRONG, because "
            "BLS nowhere states that these four UCCs are the maintenance it "
            "means; the join between the sentence and the codes is ours."
        ),
    ),
    SuccessorRule(
        rule_id="OS_CPI_OWNER_ROOF_MATERIALS_ANOMALY_v0_2",
        predecessor_rule_id=PREDECESSOR_STRUCTURE_RULE,
        predecessor_status="PROPOSED",
        successor_status="PROPOSED",
        effect_state="PENDING",
        rule_type="EXCLUDE",
        category="maintenance_and_repair_commodities",
        source_uccs=("240213",),
        evidence_ids=(
            "OER_FS_MAINTENANCE_OUT_OF_SCOPE",
            "COUNTERPART_TEST_FALSIFIED",
        ),
        evidence_strength="WEAK",
        final_status="OUT_OF_SCOPE",
        numerical_treatment_computable=True,
        blocker_kind="BLOCKED_BY_CONTRADICTORY_MEMBERSHIP",
        rationale=(
            "Separated from the services because its code-level signals point "
            "the other way. 240213 is the only unmapped maintenance commodity "
            "in the owner branch: 240112, 240122, 240212, 240222, 240312, "
            "240322, 320612 and 320632 are all mapped. Its renter counterpart "
            "240211 names 'roofing, and gutters' explicitly and is mapped to "
            "HM090, and its nearest owner sibling 240212 is mapped to HM090 "
            "too. A clerical omission by BLS is at least as plausible as a "
            "scope decision, and this workstream has already recorded one "
            "such anomaly rather than resolving it. Excluding it would treat "
            "an absent row as permission. Held at 3,440 million dollars, "
            "visible, unapplied."
        ),
    ),
    SuccessorRule(
        rule_id="OS_CPI_OWNER_SITE_PAYMENTS_v0_2",
        predecessor_rule_id=PREDECESSOR_STRUCTURE_RULE,
        predecessor_status="PROPOSED",
        successor_status="PROPOSED",
        effect_state="PENDING",
        rule_type="EXCLUDE",
        category="ground_rent_and_parking",
        source_uccs=("210901", "220901"),
        evidence_ids=("RENTER_MEAN_WEIGHTING_CURRENT_VINTAGE",),
        evidence_strength="WEAK",
        final_status="OUT_OF_SCOPE",
        numerical_treatment_computable=True,
        blocker_kind="BLOCKED_BY_UNESTABLISHED_CONCEPT",
        rationale=(
            "Ground rent and parking at an owned dwelling are neither "
            "maintenance nor improvement nor interest nor tax, so the current "
            "factsheet sentence that carries the maintenance members does not "
            "reach them. Both are unmapped, but unmapped status on its own "
            "was graded MODERATE throughout this workstream and here there is "
            "no BLS principle to join it to. Two readings remain live and no "
            "published source chooses between them: out-of-scope payment for "
            "land, or a shelter cost already subsumed inside owners' "
            "equivalent rent. The second has a real hook -- the CPI's OER "
            "question asks what the home would rent for, and the CE rent "
            "question for renters explicitly includes garage and parking "
            "charges -- but that hook is a DMI reading, not a BLS statement, "
            "and it is recorded as a lead rather than applied."
        ),
    ),
    SuccessorRule(
        rule_id="OS_CPI_OWNER_PROPERTY_MANAGEMENT_v0_2",
        predecessor_rule_id=PREDECESSOR_STRUCTURE_RULE,
        predecessor_status="PROPOSED",
        successor_status="PROPOSED",
        effect_state="PENDING",
        rule_type="EXCLUDE",
        category="property_management",
        source_uccs=("230901",),
        evidence_ids=("RENTER_MEAN_WEIGHTING_CURRENT_VINTAGE",),
        evidence_strength="WEAK",
        final_status="OUT_OF_SCOPE",
        numerical_treatment_computable=True,
        blocker_kind="BLOCKED_BY_UNESTABLISHED_CONCEPT",
        rationale=(
            "Property management is a purchased service, not maintenance of "
            "the structure, so the maintenance sentence does not reach it "
            "either. It is held separately from ground rent and parking "
            "because its evidentiary situation is different and worse: its "
            "own CE stub sibling under OWNMNAGE, 340911 'Management and "
            "upkeep services for security (owner)', IS mapped, to HP090. Two "
            "owner-only management services under one container, one mapped "
            "and one not, is precisely the pattern that falsified the "
            "counterpart test. Nothing here is strong enough to act on in "
            "either direction. Held at 17,688 million dollars."
        ),
    ),
)

# Rules whose evidence changed in this task without their status changing.
SECONDARY_RESIDENCE_BLOCKERS: tuple[dict[str, object], ...] = (
    {
        "blocker_kind": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
        "blocker_id": "SECONDARY_CONSUMPTION_PORTION_FACTOR_UNPUBLISHED",
        "uncertainty_kind": "PARAMETER",
        "affects_uccs": ["910105", "910106", "910107"],
        "what_would_clear_it": (
            "A current BLS source stating the consumption-portion factor, or "
            "stating that the CE addenda amounts enter the CPI weight "
            "unmodified for this concept."
        ),
        "independent_of": "UCC_910106_DEGENERATE_VARIANCE",
    },
    {
        "blocker_kind": "BLOCKED_BY_DEGENERATE_VARIANCE",
        "blocker_id": "UCC_910106_DEGENERATE_VARIANCE",
        "uncertainty_kind": "SAMPLING",
        "affects_uccs": ["910106"],
        "what_would_clear_it": (
            "A PUMD vintage in which 910106 has records in Q1 and a "
            "non-degenerate replicate variance in Q2, or a published BLS "
            "aggregate for the concept that does not depend on the DMI "
            "estimator."
        ),
        "independent_of": "SECONDARY_CONSUMPTION_PORTION_FACTOR_UNPUBLISHED",
    },
)
"""B6 requires these two kept apart. They are different kinds of uncertainty,
they have different clearing conditions, and clearing either one alone leaves
the rules that depend on them still blocked on the other."""


HELD_RULE_UPDATES: tuple[dict[str, object], ...] = (
    {
        "rule_id": "TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1",
        "predecessor_rule_id": None,
        "predecessor_status": "NONE",
        "successor_status": "PROPOSED",
        "effect_state": "PENDING",
        "rule_type": "TRANSFORM",
        "category": "homeowners_insurance",
        "source_uccs": ("220121",),
        "evidence_ids": (
            "CASEY_NOTE_3_INSURANCE_43_PCT",
            "INSURANCE_PARTIAL_INCLUSION_CURRENT",
            "INSURANCE_NAIC_METHOD_SINCE_2025",
            "INSURANCE_CONTENTS_ONLY_SCOPE",
            "INSURANCE_FACTOR_VALUE_2024_VINTAGE",
            "INSURANCE_METHOD_APPLIES_TO_2024_WEIGHTS",
        ),
        "evidence_strength": "STRONG_CONCEPT_NO_PARAMETER",
        "final_status": "TRANSFORMED",
        "numerical_treatment_computable": False,
        "blocker_kind": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
        "blockers": (
            {
                "blocker_kind": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
                "blocker_id": "INSURANCE_CONTENTS_FACTOR_UNPUBLISHED",
                "uncertainty_kind": "PARAMETER",
                "what_would_clear_it": (
                    "BLS publishing the median ratio it derives from the "
                    "National Association of Insurance Commissioners data, or "
                    "publishing the derived in-scope share of homeowner "
                    "insurance spending, for the 2024 weighting vintage."
                ),
            },
        ),
        "b5_outcome": "C",
        "rationale": (
            "New rule, written because the shelter milestone had no rule for "
            "this at all: 220121 was simply retained at 100 percent. Outcome "
            "C of the five the task allows. The conceptual treatment is "
            "established by a current BLS factsheet -- only a portion of "
            "homeowner insurance spending enters the weight, and the in-scope "
            "part is contents coverage -- while the numerical transformation "
            "is blocked, because the factor's value is not published. Outcome "
            "A is excluded affirmatively rather than left unproven: the "
            "derivation was replaced in January 2025 with a National "
            "Association of Insurance Commissioners method, so 43 percent is "
            "superseded, not merely unconfirmed."
        ),
        "track_a_effect": (
            "None. 220121 stays RETAINED at its full 100,026 million dollars "
            "and is flagged an upper bound. This is not an exception to the "
            "rule that a PROPOSED rule has no effect; it is that rule applied "
            "correctly to a transform. Not applying a partial-retention "
            "transform leaves the amount as recorded. Moving it to the "
            "pending bucket instead would remove it from the CPI basis "
            "entirely, which would assert that none of it is in scope -- a "
            "claim current BLS text directly contradicts. The pending bucket "
            "is the right home for an amount whose direction is unknown; a "
            "retained upper bound is the right home for an amount BLS "
            "confirms is partly in scope by an unpublished fraction."
        ),
    },
    {
        "rule_id": "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        "predecessor_rule_id": "RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1",
        "predecessor_status": "PROPOSED",
        "successor_status": "PROPOSED",
        "effect_state": "PENDING",
        "rule_type": "REPLACE",
        "category": "secondary_and_vacation_residence_costs",
        "source_uccs": (),
        "evidence_ids": (
            "SECONDARY_OER_IN_CURRENT_CPI",
            "SECONDARY_TYPES_POOLED_AND_UNSAMPLED",
            "OWNED_VACATION_BRANCH_FULLY_UNMAPPED",
            "CASEY_NOTE_2_CONSUMPTION_PORTION",
            "SECONDARY_CONSUMPTION_FACTOR_CURRENT_VINTAGE",
            "UCC_910106_DEGENERATE_VARIANCE",
        ),
        "evidence_strength": "MODERATE",
        "final_status": "TRANSFORMED",
        "numerical_treatment_computable": False,
        "blocker_kind": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
        "blockers": SECONDARY_RESIDENCE_BLOCKERS,
        "b5_outcome": None,
        "rationale": (
            "Status unchanged, evidence improved. The milestone recorded that "
            "the REPLACE reading could not be separated from a plain EXCLUDE "
            "reading on the published record; the current OER factsheet "
            "separates them, because the displacing item demonstrably exists, "
            "is named, and carries weight. The structural check that the "
            "whole owned-vacation branch is unmapped is re-verified against "
            "the pinned concordance rather than restated. The rule "
            "nonetheless stays PROPOSED, and the reason is the task's own "
            "standard: a REPLACE rule may be accepted only when all its "
            "required transformations are reproducible, and the replacement "
            "is not."
        ),
        "track_a_effect": (
            "None. The fifteen members stay in the pending bucket. Accepting "
            "this rule would have moved 12,620 million dollars out of the "
            "basis with nothing entering in its place, enlarging the "
            "already-reported understatement to 38,167. That is the direction "
            "the evidence would have pushed, and it was not taken, because "
            "the evidence does not reach the replacement."
        ),
    },
    {
        "rule_id": "TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1",
        "predecessor_rule_id": "TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1",
        "predecessor_status": "PROPOSED",
        "successor_status": "PROPOSED",
        "effect_state": "PENDING",
        "rule_type": "INTRODUCE",
        "category": "rental_equivalence_addenda_910104_910107",
        "source_uccs": (),
        "evidence_ids": (
            "SECONDARY_OER_IN_CURRENT_CPI",
            "SECONDARY_TYPES_POOLED_AND_UNSAMPLED",
            "CASEY_NOTE_2_CONSUMPTION_PORTION",
            "SECONDARY_CONSUMPTION_FACTOR_CURRENT_VINTAGE",
            "UCC_910106_DEGENERATE_VARIANCE",
        ),
        "evidence_strength": "MODERATE",
        "final_status": "INTRODUCED",
        "numerical_treatment_computable": False,
        "blocker_kind": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
        "blockers": SECONDARY_RESIDENCE_BLOCKERS,
        "b5_outcome": None,
        "rationale": (
            "Status unchanged. What changes is that its single blocker is "
            "split into two, because the milestone's wording ran them "
            "together and they are not the same kind of problem and will not "
            "be fixed by the same thing. Parameter uncertainty: the "
            "consumption-portion factor is historical only, with no current "
            "counterpart located. Sampling uncertainty: 910106 has no records "
            "in Q1 and a degenerate replicate variance in Q2. Clearing either "
            "one alone leaves the rule blocked on the other."
        ),
        "track_a_effect": (
            "None. The secondary rental-equivalence amount of 102,235 million "
            "dollars still does not enter Track A."
        ),
    },
)


# --------------------------------------------------------------------------
# Newly opened items
# --------------------------------------------------------------------------

OPEN_ITEMS: tuple[dict[str, object], ...] = (
    {
        "open_item_id": "MAPPED_OWNER_MAINTENANCE_RETAINED_AT_CE_VALUE",
        "issue": "owner_maintenance",
        "finding": (
            "OPENED BY THIS TASK, NOT CLOSED. The owner maintenance UCCs that "
            "ARE mapped are retained in Track A at their full published CE "
            "value. Casey 2010 states that owner expenditures on home "
            "maintenance and repair are weighted from 'the corresponding mean "
            "expenditures of renters', and that an allocation factor removes "
            "the investment element. If that procedure still operates, the "
            "CPI weight for these codes is not their CE amount and Track A "
            "overstates them. No current-vintage source restating the "
            "procedure was located, and none denying it was located either, "
            "so the direction is known and the size is not. Nothing is "
            "applied. This item did not exist before this task: the milestone "
            "asked whether the unmapped maintenance codes should leave, and "
            "answering that surfaced a question about the ones that stay."
        ),
        "evidence_ids": (
            "CASEY_NOTE_5_MAINTENANCE_ALLOCATION_FACTOR",
            "RENTER_MEAN_WEIGHTING_CURRENT_VINTAGE",
        ),
        "uccs": (
            "230112",
            "230142",
            "320625",
            "240112",
            "240122",
            "240212",
            "240222",
            "240312",
            "240322",
            "320612",
            "320632",
        ),
        "boundary_is_dmi": (
            "Which codes count as 'home maintenance and repair' for Casey's "
            "sentence is a DMI reading of CE stub containers OWNREPSV, "
            "OWNREPSP and OWNMISC. Casey also names major appliances for "
            "owned housing, which sit outside shelter under CE stub parent "
            "MAJAPPL and are not counted here."
        ),
        "action_taken": "NONE",
    },
    {
        "open_item_id": "HOMEOWNERS_INSURANCE_UPPER_BOUND",
        "issue": "homeowners_insurance",
        "finding": (
            "NARROWED BY THIS TASK, NOT CLOSED. The milestone recorded that "
            "historical authority for a renter's-part allocation was "
            "established while 2024 applicability was not. Both halves now "
            "move. The conceptual allocation IS current: BLS states that only "
            "a portion of homeowner insurance spending is included, and that "
            "the in-scope part is contents coverage. The 43 percent factor is "
            "NOT current: the derivation was replaced in January 2025. And "
            "the replacement factor's value is not published. Track A's "
            "100,026 million dollars is therefore an upper bound whose "
            "excess is real and unquantifiable, rather than an amount of "
            "unknown correctness."
        ),
        "evidence_ids": (
            "INSURANCE_PARTIAL_INCLUSION_CURRENT",
            "INSURANCE_NAIC_METHOD_SINCE_2025",
            "INSURANCE_FACTOR_VALUE_2024_VINTAGE",
            "INSURANCE_METHOD_APPLIES_TO_2024_WEIGHTS",
        ),
        "uccs": ("220121",),
        "boundary_is_dmi": (
            "That the January 2025 method governs the 2024 weighting vintage "
            "is a DMI inference from three current BLS statements, recorded "
            "as INSURANCE_METHOD_APPLIES_TO_2024_WEIGHTS."
        ),
        "action_taken": "NONE",
    },
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def load_basis(path: Path = BASIS_PATH) -> dict[tuple[str, str], float | None]:
    """Published CE aggregate expenditure by UCC and population, in millions."""
    from .shelter_tracks import load_basis as _load_basis

    return _load_basis(path)


def load_predecessor_rules(path: Path = SCOPE_RULES_V0_2_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_predecessor_provenance(path: Path = PROVENANCE_V0_3_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_accounting_summary(path: Path = ACCOUNTING_SUMMARY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# B4 matrix
# --------------------------------------------------------------------------

UCC_LABELS = {
    "210901": "Ground rent (owner)",
    "220901": "Parking (owner)",
    "230113": "Plumbing and water heating",
    "230114": "Heat, a/c, and electrical work",
    "230115": "Roofing and gutters",
    "230151": "Other repair and maintenance services",
    "230901": "Property management (owner)",
    "240213": "Materials and equipment for roofs and gutters",
}

UCC_STUB_PARENT = {
    "210901": "OWNEXPEN",
    "220901": "OWNEXPEN",
    "230113": "OWNREPSV",
    "230114": "OWNREPSV",
    "230115": "OWNREPSV",
    "230151": "OWNREPSV",
    "230901": "OWNMNAGE",
    "240213": "OWNREPSP",
}

UCC_BLS_CONCEPT = {
    "230113": "Owner maintenance and repair service, building system",
    "230114": "Owner maintenance and repair service, building system",
    "230115": "Owner maintenance and repair service, structural envelope",
    "230151": "Owner maintenance and repair service, residual",
    "240213": "Owner maintenance and repair commodity, structural envelope",
    "210901": "Payment for use of land under an owned dwelling",
    "220901": "Parking at an owned dwelling",
    "230901": "Purchased property management service for an owned dwelling",
}

UCC_UNRESOLVED_REASON = {
    "230113": "NONE. Resolved.",
    "230114": "NONE. Resolved.",
    "230115": "NONE. Resolved.",
    "230151": "NONE. Resolved.",
    "240213": (
        "Sole unmapped maintenance commodity in the owner branch; renter "
        "counterpart 240211 names roofing and gutters and is mapped to HM090; "
        "owner sibling 240212 is mapped to HM090. Omission and scope decision "
        "are equally consistent with the record."
    ),
    "210901": (
        "No BLS source states the CPI treatment of owner ground rent. "
        "Out-of-scope land payment and subsumption into owners' equivalent "
        "rent are both live readings."
    ),
    "220901": (
        "No BLS source states the CPI treatment of parking at an owned "
        "dwelling. The CE rent question for renters includes garage and "
        "parking charges, which suggests subsumption into the shelter "
        "concept, but that is a DMI reading."
    ),
    "230901": (
        "No BLS source states the CPI treatment of owner property "
        "management. Its OWNMNAGE sibling 340911 is mapped to HP090, so the "
        "container does not settle it."
    ),
}


@dataclass(frozen=True)
class MatrixRow:
    ucc: str
    label: str
    category: str
    ce_stub_parent: str
    concordance_eli: str
    all_cu_expenditure: float | None
    q1_expenditure: float | None
    q2_expenditure: float | None
    q3_expenditure: float | None
    q4_expenditure: float | None
    q5_expenditure: float | None
    current_proposed_treatment: str
    bls_concept: str
    cpi_scope_treatment: str
    concordance_evidentiary_role: str
    evidence_source: str
    evidence_vintage: str
    allocation_factor: str
    factor_provenance: str
    final_research_disposition: str
    unresolved_reason: str
    successor_rule_id: str


def build_ucc_matrix(
    basis: Mapping[tuple[str, str], float | None],
    concordance=None,
) -> tuple[MatrixRow, ...]:
    """One row per UCC governed by the predecessor owner-structure rule."""
    if concordance is None:
        concordance = load_concordance()
    by_ucc = {ucc: rule for rule in SUCCESSOR_RULES for ucc in rule.source_uccs}
    evidence_by_id = {ev.evidence_id: ev for ev in EVIDENCE}

    rows: list[MatrixRow] = []
    for ucc in sorted(by_ucc):
        rule = by_ucc[ucc]
        entry = concordance.get(ucc)
        eli = ",".join(entry.elis) if entry else "UNMAPPED"
        vintages = sorted(
            {evidence_by_id[e].vintage_class for e in rule.evidence_ids}
        )
        disposition = (
            "ACCEPTED_OUT_OF_SCOPE"
            if rule.successor_status == "ACCEPTED"
            else f"PENDING__{rule.blocker_kind}"
        )
        rows.append(
            MatrixRow(
                ucc=ucc,
                label=UCC_LABELS[ucc],
                category=rule.category,
                ce_stub_parent=UCC_STUB_PARENT[ucc],
                concordance_eli=eli,
                all_cu_expenditure=basis.get((ucc, "ALL_CU")),
                q1_expenditure=basis.get((ucc, "Q1")),
                q2_expenditure=basis.get((ucc, "Q2")),
                q3_expenditure=basis.get((ucc, "Q3")),
                q4_expenditure=basis.get((ucc, "Q4")),
                q5_expenditure=basis.get((ucc, "Q5")),
                current_proposed_treatment=(
                    f"{PREDECESSOR_STRUCTURE_RULE} EXCLUDE, PROPOSED, PENDING"
                ),
                bls_concept=UCC_BLS_CONCEPT[ucc],
                cpi_scope_treatment=(
                    "No direct ELI mapping in the pinned 2024-vintage "
                    "concordance."
                    if eli == "UNMAPPED"
                    else f"Mapped to {eli}"
                ),
                concordance_evidentiary_role=(
                    "CORROBORATING. Absence of a row records what the "
                    "crosswalk does not display. It does not by itself "
                    "establish exclusion, and the scope disposition in this "
                    "row is not derived from it alone."
                    if eli == "UNMAPPED"
                    else "PRIMARY. A mapping is a positive fact about the "
                    "crosswalk."
                ),
                evidence_source="; ".join(rule.evidence_ids),
                evidence_vintage="; ".join(vintages),
                allocation_factor="NONE",
                factor_provenance=(
                    "No allocation factor is applied to any UCC in this "
                    "matrix. Removal needs no parameter, and no rule here "
                    "retains a fraction."
                ),
                final_research_disposition=disposition,
                unresolved_reason=UCC_UNRESOLVED_REASON[ucc],
                successor_rule_id=rule.rule_id,
            )
        )
    return tuple(rows)


# --------------------------------------------------------------------------
# B11 before/after accounting
# --------------------------------------------------------------------------

# Buckets that sit outside the CPI-basis total. Moving an amount between any
# two of these cannot change e_cpi, delta_scope or delta_shelter. That is the
# whole reason the reclassification in this task is numerically inert, and it
# is checked rather than assumed.
BUCKETS_OUTSIDE_CPI_BASIS = ("accepted_out_of_scope", "pending_proposed", "unresolved_open")


@dataclass(frozen=True)
class BeforeAfter:
    population: str
    quantity: str
    before: float | None
    after: float | None

    @property
    def change(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


def _promoted_amount(
    basis: Mapping[tuple[str, str], float | None], population: str
) -> float:
    """Expenditure moving from pending to accepted-out-of-scope, by population."""
    total = 0.0
    for rule in SUCCESSOR_RULES:
        if rule.successor_status != "ACCEPTED":
            continue
        for ucc in rule.source_uccs:
            value = basis.get((ucc, population))
            if value is not None:
                total += value
    return total


def build_before_after(
    summary: Mapping[str, object],
    basis: Mapping[tuple[str, str], float | None],
) -> tuple[BeforeAfter, ...]:
    """Reclassify the promoted amount and re-check every identity afterwards."""
    by_population = summary["by_population"]  # type: ignore[index]
    rows: list[BeforeAfter] = []
    for population in pumd.POPULATIONS:
        before = by_population[population]  # type: ignore[index]
        promoted = _promoted_amount(basis, population)

        after = dict(before)
        after["accepted_out_of_scope"] = before["accepted_out_of_scope"] + promoted
        after["pending_proposed"] = before["pending_proposed"] - promoted

        if after["pending_proposed"] < 0:
            raise ValueError(
                f"{population}: promoted {promoted} exceeds the pending bucket"
            )
        _check_identities(population, after)

        for quantity in (
            "e_source",
            "e_cpi",
            "delta_scope",
            "delta_shelter",
            "retained",
            "accepted_transformed",
            "accepted_out_of_scope",
            "pending_proposed",
            "unresolved_open",
            "rental_equivalence_introduced",
            "owner_outlays_removed",
            "secondary_residence_outlays_removed_without_replacement",
        ):
            rows.append(
                BeforeAfter(
                    population=population,
                    quantity=quantity,
                    before=before.get(quantity),
                    after=after.get(quantity),
                )
            )
    return tuple(rows)


def _check_identities(population: str, entry: Mapping[str, float]) -> None:
    """The three identities the milestone declared, re-checked after the move."""
    tolerance = 1e-6
    source = (
        entry["retained"]
        + entry["accepted_transformed"]
        + entry["accepted_out_of_scope"]
        + entry["pending_proposed"]
        + entry["unresolved_open"]
    )
    if abs(source - entry["e_source"]) > tolerance:
        raise ValueError(f"{population}: source identity broken")

    cpi = (
        entry["retained"]
        + entry["accepted_transformed"]
        + entry["rental_equivalence_introduced"]
    )
    if abs(cpi - entry["e_cpi"]) > tolerance:
        raise ValueError(f"{population}: CPI identity broken")

    delta = (
        entry["rental_equivalence_introduced"]
        - entry["accepted_out_of_scope"]
        - entry["pending_proposed"]
        - entry["unresolved_open"]
    )
    if abs(delta - entry["delta_scope"]) > tolerance:
        raise ValueError(f"{population}: delta identity broken")


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------


def build_verdict(
    basis: Mapping[tuple[str, str], float | None],
    before_after: Sequence[BeforeAfter],
) -> dict:
    promoted = _promoted_amount(basis, "ALL_CU")
    held = sum(
        basis[(ucc, "ALL_CU")] or 0.0
        for rule in SUCCESSOR_RULES
        if rule.successor_status != "ACCEPTED"
        for ucc in rule.source_uccs
    )
    unchanged = {
        row.quantity: row.change
        for row in before_after
        if row.population == "ALL_CU"
        and row.quantity in ("e_source", "e_cpi", "delta_scope", "delta_shelter")
    }
    return {
        "artifact_id": "SHELTER_RESIDUAL_VERDICT_2024",
        "residual_shelter_status": "PARTIAL",
        "status": "RESEARCH_ONLY",
        "units": "millions of 2024 dollars, published CE aggregate basis",
        "verdict_reasoning": (
            "PARTIAL, not PASS and not BLOCKED. One of the three questions is "
            "resolved on current BLS evidence: owner maintenance services, "
            f"{promoted:,.0f} million dollars, moves from PROPOSED to "
            "ACCEPTED and out of scope. The other two are not resolved, and "
            "in both cases the reason is a parameter that BLS describes and "
            "does not publish rather than an absence of concept. Calling this "
            "PASS would overstate it; calling it BLOCKED would hide that the "
            "largest single block did clear and that both remaining blockers "
            "are now named, dated and separated."
        ),
        "b4_category_coverage": {
            "note": (
                "The task named seven owner-housing categories to be "
                "distinguished. Four of them are members of the predecessor "
                "rule and appear in the UCC matrix. The other three are "
                "recorded here so that their absence from the matrix reads as "
                "a fact about where they live, not as an omission."
            ),
            "in_this_matrix": {
                "maintenance_and_repair_services": (
                    "OS_CPI_OWNER_MAINTENANCE_SERVICES_v0_2"
                ),
                "maintenance_and_repair_commodities": (
                    "OS_CPI_OWNER_ROOF_MATERIALS_ANOMALY_v0_2"
                ),
                "ground_rent_and_parking": "OS_CPI_OWNER_SITE_PAYMENTS_v0_2",
                "property_management": (
                    "OS_CPI_OWNER_PROPERTY_MANAGEMENT_v0_2"
                ),
            },
            "elsewhere": {
                "improvements_and_capital_additions": (
                    "Adjudicated at the shelter milestone by "
                    "OS_CPI_CAPITAL_IMPROVEMENT_v0_1, ACCEPTED. Not reopened."
                ),
                "service_contracts_and_warranties": (
                    "No UCC in the CE shelter stub tree carries this concept "
                    "for owned housing. Appliance repair 230142 is the "
                    "nearest, and it is mapped to HP041 and retained, so it "
                    "was never a member of the predecessor rule."
                ),
                "other_owner_housing_services": (
                    "Security-system management 340911 is mapped to HP090 and "
                    "retained. It is listed under the open item on mapped "
                    "owner maintenance rather than here."
                ),
            },
        },
        "issue_outcomes": {
            "owner_maintenance_and_structure_investment": {
                "predecessor_rule": PREDECESSOR_STRUCTURE_RULE,
                "predecessor_amount_all_cu": promoted + held,
                "resolved_amount_all_cu": promoted,
                "still_pending_amount_all_cu": held,
                "outcome": "PARTIALLY_RESOLVED_BY_SPLIT",
                "summary": (
                    "The single rule is replaced by four narrower successors "
                    "because it combined four materially different concepts "
                    "under one criterion, and that criterion is falsified. "
                    "Maintenance services clear on current BLS evidence. Roof "
                    "materials, site payments and property management do not, "
                    "for three different reasons, each recorded separately."
                ),
            },
            "homeowners_insurance": {
                "amount_all_cu": 100026.0,
                "outcome": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
                "b5_outcome": "C",
                "summary": (
                    "Conceptual treatment established by current BLS "
                    "authority; numerical transformation blocked. The "
                    "historical 43 percent factor is superseded as of January "
                    "2025, so it is affirmatively wrong for 2024 rather than "
                    "merely unconfirmed, and the replacement factor is not "
                    "published. Track A continues to retain 100 percent, now "
                    "labelled an upper bound."
                ),
            },
            "secondary_residence": {
                "outlay_amount_all_cu": 12620.0,
                "rental_equivalence_amount_all_cu": 102234.815688,
                "outcome": "BLOCKED_BY_UNPUBLISHED_PARAMETER",
                "summary": (
                    "Secondary-residence rental equivalence is confirmed "
                    "present in the current CPI, under one unsampled ELI "
                    "covering all three residence types, with all three "
                    "source UCCs named by BLS. That resolves the milestone's "
                    "REPLACE-versus-EXCLUDE ambiguity. The consumption-"
                    "portion factor remains historical only, and the 910106 "
                    "variance defect is separated from it as a distinct "
                    "blocker."
                ),
            },
        },
        "quantities_unchanged_by_this_task": unchanged,
        "no_balancing": (
            "Delta_scope and Delta_shelter are byte-identical before and "
            "after. That is not a result of tuning: an amount promoted from "
            "the pending bucket to the accepted-out-of-scope bucket moves "
            "between two buckets that both sit outside the CPI-basis total, "
            "so the CPI basis and both deltas cannot move. The one adjudication "
            "in this task that would have changed a delta -- accepting the "
            "secondary-residence replacement rule -- would have made the "
            "reported understatement larger, and it was declined on evidence, "
            "not on its effect. No rescaling, renormalisation, balancing "
            "factor or residual-allocating step exists in this module."
        ),
        "open_items": [dict(item) for item in OPEN_ITEMS],
    }


# --------------------------------------------------------------------------
# Successor registries
# --------------------------------------------------------------------------


def build_scope_rules_v0_3(
    predecessor: Mapping[str, object],
    basis: Mapping[tuple[str, str], float | None],
) -> dict:
    """Successor registry. The predecessor is copied, never edited in place."""
    payload = json.loads(json.dumps(predecessor))
    payload["version"] = "0.3"
    payload["artifact_id"] = "CE_CPI_SCOPE_RULES_V0_3"
    payload["predecessor"] = {
        "artifact_id": predecessor.get("artifact_id"),
        "version": predecessor.get("version"),
        "path": "registry/research/ce_cpi_scope_rules_v0_2.json",
        "note": (
            "The predecessor is preserved byte-for-byte at its own path and "
            "remains the frozen shelter-milestone state. It is regenerated "
            "unchanged by scripts/build_shelter_tracks_2024.py, which this "
            "task did not modify. Every difference is listed in "
            "residual_transitions below."
        ),
    }

    annotations = {
        str(spec["rule_id"]): spec
        for spec in HELD_RULE_UPDATES
        if spec["predecessor_rule_id"] == spec["rule_id"]
    }
    kept = []
    for rule in payload["rules"]:
        if rule["rule_id"] == PREDECESSOR_STRUCTURE_RULE:
            continue
        spec = annotations.get(rule["rule_id"])
        if spec is not None:
            rule["residual_review"] = _held_review_payload(spec)
        kept.append(rule)
    for rule in SUCCESSOR_RULES:
        kept.append(_successor_rule_payload(rule, basis))
    kept.append(_insurance_rule_payload(basis))
    payload["rules"] = sorted(kept, key=lambda r: r["rule_id"])

    payload["residual_transitions"] = _transition_payload(basis)
    payload["residual_evidence_reference"] = (
        "registry/research/shelter_residual_evidence_v0_1.json holds the full "
        "evidence records, each with a vintage class. Rule outcomes here are "
        "derived from those classes: a rule may be ACCEPTED only on "
        "CURRENT_2024_COMPATIBLE evidence, never on HISTORICAL_ONLY evidence "
        "however primary its source."
    )
    payload["falsified_predecessor_criterion"] = {
        "criterion": (
            "The predecessor rule's review_blocker offered a clearing path: "
            "'an independent check that no renter counterpart exists for the "
            "five maintenance members'."
        ),
        "verdict": "FALSIFIED",
        "evidence_id": "COUNTERPART_TEST_FALSIFIED",
        "consequence": (
            "The check was run and it does not separate the excluded UCCs "
            "from the included ones, so it could not have cleared the rule in "
            "either direction. The successor rules do not use it. It is "
            "recorded rather than deleted, because a criterion that failed is "
            "part of why the successors are shaped the way they are."
        ),
    }
    return payload


def _held_review_payload(spec: Mapping[str, object]) -> dict:
    """Non-destructive annotation on a rule whose status did not change.

    The predecessor's own fields are left exactly as the milestone wrote them.
    What is added is what this task learned: the evidence it rests on now, and
    its blockers separated into the distinct kinds of uncertainty they are.
    """
    return {
        "reviewed_by": "SHELTER_RESIDUALS_2024",
        "review_status": spec["successor_status"],
        "status_changed": False,
        "evidence_ids": list(spec["evidence_ids"]),  # type: ignore[arg-type]
        "evidence_strength": spec["evidence_strength"],
        "numerical_treatment_computable": spec["numerical_treatment_computable"],
        "blockers": [
            dict(b, blocker_semantics=BLOCKER_KINDS[str(b["blocker_kind"])])
            for b in spec["blockers"]  # type: ignore[union-attr]
        ],
        "predecessor_review_blocker_note": (
            "The predecessor's review_blocker field is retained above, "
            "unedited. It ran two distinct limitations together in one "
            "paragraph. The blockers list here separates them without "
            "deleting the original wording."
        ),
        "rationale": spec["rationale"],
        "track_a_effect": spec["track_a_effect"],
    }


def _successor_rule_payload(
    rule: SuccessorRule, basis: Mapping[tuple[str, str], float | None]
) -> dict:
    materiality = sum(
        basis[(ucc, "ALL_CU")] or 0.0 for ucc in rule.source_uccs
    )
    return {
        "rule_id": rule.rule_id,
        "rule_type": rule.rule_type,
        "track": "SHELTER_COUPLED",
        "category": rule.category,
        "review_status": rule.successor_status,
        "effect_state": rule.effect_state,
        "evidence_strength": rule.evidence_strength,
        "final_status": rule.final_status,
        "is_applicable": rule.successor_status == "ACCEPTED",
        "materiality_all_cu": materiality,
        "source_uccs": list(rule.source_uccs),
        "evidence_ids": list(rule.evidence_ids),
        "numerical_treatment_computable": rule.numerical_treatment_computable,
        "blocker_kind": rule.blocker_kind,
        "blocker_semantics": (
            BLOCKER_KINDS[rule.blocker_kind] if rule.blocker_kind else None
        ),
        "predecessor_rule_id": rule.predecessor_rule_id,
        "rationale": rule.rationale,
    }


def _insurance_rule_payload(
    basis: Mapping[tuple[str, str], float | None]
) -> dict:
    spec = next(
        item
        for item in HELD_RULE_UPDATES
        if item["rule_id"] == "TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1"
    )
    uccs = tuple(spec["source_uccs"])  # type: ignore[arg-type]
    return {
        "rule_id": spec["rule_id"],
        "rule_type": spec["rule_type"],
        "track": "SHELTER_COUPLED",
        "category": spec["category"],
        "review_status": spec["successor_status"],
        "effect_state": spec["effect_state"],
        "evidence_strength": spec["evidence_strength"],
        "final_status": spec["final_status"],
        "is_applicable": False,
        "materiality_all_cu": sum(basis[(u, "ALL_CU")] or 0.0 for u in uccs),
        "source_uccs": list(uccs),
        "evidence_ids": list(spec["evidence_ids"]),  # type: ignore[arg-type]
        "numerical_treatment_computable": spec["numerical_treatment_computable"],
        "blocker_kind": spec["blocker_kind"],
        "blocker_semantics": BLOCKER_KINDS[str(spec["blocker_kind"])],
        "blockers": [
            dict(b, blocker_semantics=BLOCKER_KINDS[str(b["blocker_kind"])])
            for b in spec["blockers"]  # type: ignore[union-attr]
        ],
        "predecessor_rule_id": spec["predecessor_rule_id"],
        "b5_outcome": spec["b5_outcome"],
        "rationale": spec["rationale"],
        "track_a_effect": spec["track_a_effect"],
        "factor_applied": None,
        "factor_not_applied_note": (
            "No factor is stored on this rule, deliberately. Storing 0.43 "
            "with is_applicable false would leave a superseded number one "
            "edit away from being used."
        ),
    }


def _transition_payload(
    basis: Mapping[tuple[str, str], float | None]
) -> list[dict]:
    rows: list[dict] = []
    for rule in SUCCESSOR_RULES:
        rows.append(
            {
                "rule_id": rule.rule_id,
                "predecessor_rule_id": rule.predecessor_rule_id,
                "predecessor_status": rule.predecessor_status,
                "successor_status": rule.successor_status,
                "triggering_evidence": list(rule.evidence_ids),
                "source_vintage": sorted(
                    {
                        ev.vintage_class
                        for ev in EVIDENCE
                        if ev.evidence_id in rule.evidence_ids
                    }
                ),
                "numerical_treatment_became_computable": (
                    rule.numerical_treatment_computable
                    and rule.successor_status == "ACCEPTED"
                ),
                "materiality_all_cu": sum(
                    basis[(u, "ALL_CU")] or 0.0 for u in rule.source_uccs
                ),
                "blocker_kinds": (
                    [rule.blocker_kind] if rule.blocker_kind else []
                ),
            }
        )
    for spec in HELD_RULE_UPDATES:
        rows.append(
            {
                "rule_id": spec["rule_id"],
                "predecessor_rule_id": spec["predecessor_rule_id"],
                "predecessor_status": spec["predecessor_status"],
                "successor_status": spec["successor_status"],
                "triggering_evidence": list(spec["evidence_ids"]),  # type: ignore[arg-type]
                "source_vintage": sorted(
                    {
                        ev.vintage_class
                        for ev in EVIDENCE
                        if ev.evidence_id in spec["evidence_ids"]  # type: ignore[operator]
                    }
                ),
                "numerical_treatment_became_computable": False,
                "materiality_all_cu": (
                    sum(
                        basis[(u, "ALL_CU")] or 0.0
                        for u in spec["source_uccs"]  # type: ignore[union-attr]
                    )
                    if spec["source_uccs"]
                    else None
                ),
                "blocker_kinds": sorted(
                    {
                        str(b["blocker_kind"])
                        for b in spec["blockers"]  # type: ignore[union-attr]
                    }
                ),
            }
        )
    return rows


def build_provenance_v0_4(predecessor: Mapping[str, object]) -> dict:
    """Successor provenance registry: one adjustment status becomes VERIFIED."""
    payload = json.loads(json.dumps(predecessor))
    payload["version"] = "0.4"
    payload["artifact_id"] = "UCC_PROVENANCE_CLASSES_V0_4"
    payload["predecessor"] = {
        "artifact_id": predecessor.get("artifact_id"),
        "version": predecessor.get("version"),
        "path": "registry/research/ucc_provenance_classes_v0_3.json",
        "note": (
            "Read and not written. The predecessor is still regenerated "
            "unchanged by the milestone build."
        ),
    }
    payload["evidence_scales"]["cpi_adjustment_status"]["VERIFIED"] = (
        "BLS documentation states that the CPI applies a specific adjustment "
        "to this UCC. Asserted for 220121 as of this task; see "
        "cpi_adjustment_status_assertions."
    )
    payload["cpi_adjustment_status_assertions"] = {
        "220121": {
            "status": "VERIFIED",
            "predecessor_status": "UNKNOWN",
            "evidence_ids": [
                "INSURANCE_PARTIAL_INCLUSION_CURRENT",
                "INSURANCE_NAIC_METHOD_SINCE_2025",
                "INSURANCE_CONTENTS_ONLY_SCOPE",
            ],
            "what_is_verified": (
                "That an adjustment is applied, what quantity it adjusts (the "
                "expenditure weight), what it retains (the contents-coverage "
                "portion) and how it is currently derived (a median of "
                "renter-to-adjusted-homeowner premium ratios from National "
                "Association of Insurance Commissioners data, in use since "
                "January 2025)."
            ),
            "what_is_not_verified": (
                "The value. VERIFIED here means BLS says an adjustment "
                "happens, not that the adjustment can be reproduced. The two "
                "are recorded separately on purpose."
            ),
        },
        "_note": (
            "The predecessor stated that VERIFIED was 'not asserted for any "
            "UCC in this file'. It is now asserted for exactly one, which is "
            "why this successor exists."
        ),
    }
    payload["secondary_residence_current_confirmation"] = {
        "evidence_id": "SECONDARY_OER_IN_CURRENT_CPI",
        "claim_type": "CURRENT_2024_COMPATIBLE",
        "finding": (
            "The predecessor recorded the 910104-910107 to 910050/910101-910103 "
            "pairing as a DMI_INFERENCE and warned that BLS publishes no "
            "crosswalk. That warning stands unchanged. What is new is "
            "narrower and does not touch it: a current BLS factsheet names "
            "910105, 910106 and 910107 by number and states their CPI "
            "destination is ELI HC090, which the pinned concordance already "
            "showed. BLS naming the concordance-side codes is not BLS pairing "
            "them with the published-side codes, and no pairing is promoted "
            "here."
        ),
        "cpi_adjustment_status_unchanged": (
            "910105, 910106 and 910107 remain INFERRED. Casey 2010 states a "
            "consumption-portion factor exists but is HISTORICAL_ONLY, and no "
            "current source restates it, so the standard for VERIFIED is not "
            "met."
        ),
    }
    return payload


def build_evidence_registry() -> dict:
    return {
        "artifact_id": "SHELTER_RESIDUAL_EVIDENCE_V0_1",
        "version": "0.1",
        "status": "RESEARCH_ONLY",
        "milestone": "Detailed Inflation Substrate v0.1, shelter residuals, Phase B",
        "vintage_classes": dict(VINTAGE_SEMANTICS),
        "blocker_kinds": dict(BLOCKER_KINDS),
        "source_standard": (
            "Primary BLS sources only for methodological authority. A "
            "historical primary source establishes that a procedure once "
            "existed and never authorises applying its number to 2024. Where "
            "a chain of current statements is joined by a step of our own, "
            "that step is recorded as its own DMI_INFERENCE record rather "
            "than folded into the current ones."
        ),
        "absence_is_not_permission": (
            "Four records in this file are NOT_FOUND. None of them licenses a "
            "substitute. No factor in this workstream is approximated, "
            "interpolated, carried forward from a superseded vintage, read "
            "off a published relative importance, or backed out of a residual."
        ),
        "evidence": [asdict(ev) for ev in EVIDENCE],
        "counts_by_vintage": {
            cls: sum(1 for ev in EVIDENCE if ev.vintage_class == cls)
            for cls in VINTAGE_CLASSES
        },
    }


# --------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_ucc_matrix(path: Path, rows: Sequence[MatrixRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(asdict(rows[0]).keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            record = asdict(row)
            for key, value in record.items():
                if value is None:
                    record[key] = ""
            writer.writerow(record)


def write_before_after(path: Path, rows: Sequence[BeforeAfter]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["population", "quantity", "before", "after", "change"])
        for row in rows:
            writer.writerow(
                [
                    row.population,
                    row.quantity,
                    "" if row.before is None else f"{row.before:.6f}",
                    "" if row.after is None else f"{row.after:.6f}",
                    "" if row.change is None else f"{row.change:.6f}",
                ]
            )


def write_rule_transitions(
    path: Path, basis: Mapping[tuple[str, str], float | None]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "rule_id",
                "predecessor_rule_id",
                "predecessor_status",
                "successor_status",
                "source_vintage",
                "numerical_treatment_became_computable",
                "materiality_all_cu",
                "triggering_evidence",
            ]
        )
        for row in _transition_payload(basis):
            writer.writerow(
                [
                    row["rule_id"],
                    row["predecessor_rule_id"] or "",
                    row["predecessor_status"],
                    row["successor_status"],
                    "|".join(row["source_vintage"]),  # type: ignore[arg-type]
                    row["numerical_treatment_became_computable"],
                    ""
                    if row["materiality_all_cu"] is None
                    else f"{row['materiality_all_cu']:.6f}",
                    "|".join(row["triggering_evidence"]),  # type: ignore[arg-type]
                ]
            )
