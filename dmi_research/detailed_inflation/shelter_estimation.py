"""Estimate the four shelter rental-equivalence UCCs, under a frozen plan.

Detailed Inflation Substrate v0.1, shelter task, Phases C2-C5.

RESEARCH ONLY. Nothing here is imported by ``dmi_calculator``, by the
operational Baseline or Slack-Plus paths, or by any release workflow. Producing
a number for 910104-910107 authorizes no DMI weight; that decision is Phase D's
and is recorded separately.

This module contains no estimator. That is deliberate and it is the whole
design. The arithmetic is :func:`pumd.weighted_ucc_means`, unchanged, at the
commit that passed the Phase-B benchmark and the out-of-sample confirmation.
What this module adds is a frozen plan, a set of diagnostics the plan requires,
and the refusal to compute anything the plan did not authorise in advance.

Three disciplines are load-bearing.

*The plan precedes the amount.* :func:`build_spec` reads no microdata. The
runner refuses to start unless the spec is already committed to git history,
so a plan cannot be adjusted after an inconvenient estimate has been seen
without the adjustment being visible as a commit made after the fact.

*Nothing shelter-specific enters the estimator.* There is no scaling factor,
no calibration, no annualization override, no quintile change, no boundary
change and no denominator adjustment. :func:`assert_estimator_untouched`
checks the module digests of the estimator against the values the spec pinned,
so an edit to ``pumd.py`` between freeze and run stops the run rather than
silently changing the result.

*A missing estimate stays missing.* A UCC/population cell with no records is
reported as having no records. It is never reported as zero, because zero is
an estimate and "we have nothing" is not.

The published counterparts 910050 and 910101-910103 are estimated too, and for
one reason only: the confirmed estimator has never been run against an ADDENDA
line, because every UCC in both the development roster and the confirmation
set came from the EXPEND section. Those four are ADDENDA lines that LB01 does
publish, which makes them the only available test of whether the ordinary
estimator behaves sensibly on this section and this concept family. No Track-A
amount is taken from them and no shelter estimate is inferred from them.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

from . import pumd
from . import pumd_confirmation as confirm
from . import shelter_source as source

REPO_ROOT = Path(__file__).resolve().parents[2]

SPEC_PATH = REPO_ROOT / "registry/research/shelter_estimation_spec_v0_1.json"
SOURCE_REGISTRY_PATH = source.SOURCE_REGISTRY_PATH

SHELTER_SPEC_VERSION = "v0.1"

#: The estimator that passed Phase B and the out-of-sample confirmation.
FROZEN_ESTIMATOR_COMMIT = confirm.FROZEN_ESTIMATOR_COMMIT
FROZEN_ESTIMATOR_TAG = confirm.FROZEN_ESTIMATOR_TAG

#: The commit that recorded ``confirmation_status = PASS``.
CONFIRMATION_COMMIT = "edd14d458cf6ac160f2237c73b43e750f28821e5"

#: The commit that recorded ``source_reproduction_status = REPRODUCED``.
SOURCE_REPRODUCTION_COMMIT = "5076a6df1a2dcf99f675f4bbf60165227fafe63a"

#: Modules whose contents must not change between freeze and run. The
#: estimator is the first two; the third is the source reader, whose record
#: counts the diagnostics quote.
PINNED_MODULES: tuple[str, ...] = (
    "dmi_research/detailed_inflation/pumd.py",
    "dmi_research/detailed_inflation/pumd_benchmark.py",
    "dmi_research/detailed_inflation/shelter_source.py",
)

SHELTER_UCCS = source.SHELTER_UCCS
PUBLISHED_COUNTERPART_UCCS = source.PUBLISHED_COUNTERPART_UCCS
ESTIMATED_UCCS: tuple[str, ...] = SHELTER_UCCS + PUBLISHED_COUNTERPART_UCCS

#: Cell outcomes. ``NO_RECORDS`` is not zero and must never be rendered as
#: zero downstream.
ESTIMATED = "ESTIMATED"
NO_RECORDS = "NO_RECORDS"

#: The project's existing informational RSE threshold, carried forward as a
#: warning. Milestone 1 used it as a diagnostic flag and this task does not
#: promote it to a usability rule; no BLS publication rule authorises that.
HIGH_RSE_INFORMATIONAL_THRESHOLD_PCT = 25.0

#: Normal-approximation multiplier for a two-sided 95% interval. Declared in
#: the spec rather than chosen after seeing a cell, and flagged as an
#: approximation that thin cells may not satisfy.
INTERVAL_Z = 1.959963984540054
INTERVAL_COVERAGE = 0.95


class ShelterEstimationError(RuntimeError):
    """The frozen plan does not authorise what is being attempted."""


def module_digests(modules: Sequence[str] = PINNED_MODULES) -> dict[str, str]:
    return {
        name: hashlib.sha256((REPO_ROOT / name).read_bytes()).hexdigest()
        for name in modules
    }


# --------------------------------------------------------------------------
# C2: the frozen plan
# --------------------------------------------------------------------------


def build_spec() -> dict:
    """Build the shelter estimation specification. Reads no microdata.

    Every quantity that could be tuned after seeing a result is fixed here:
    the estimator commit, the module digests, the archive hash, the estimands,
    the units, the diagnostics required, the treatment of thin and empty
    cells, and the interpretation each UCC is given. The predictions in
    ``counterpart_validation`` are stated before the estimates exist, so that
    a wrong prediction is a finding rather than an embarrassment to be
    quietly revised.
    """
    registry = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    archive = registry["archives"]["INTRVW24"]

    return {
        "artifact": "shelter_estimation_spec",
        "spec_version": SHELTER_SPEC_VERSION,
        "status": "RESEARCH_ONLY",
        "milestone": "Detailed Inflation Substrate v0.1, shelter task, Phase C2",
        "purpose": (
            "Fix, before any amount is computed, exactly how the four "
            "rental-equivalence UCCs 910104-910107 will be estimated from the "
            "2024 CE Interview PUMD, what will be reported, in what units, "
            "and what will be done about cells that are thin or empty. This "
            "specification authorizes a calculation. It does not authorize a "
            "DMI weight, and producing a number under it does not upgrade any "
            "scope rule."
        ),
        "frozen_before_any_amount_was_computed": {
            "discipline": (
                "The runner refuses to start unless this file is already in "
                "git history, and refuses to continue if any pinned module "
                "digest has changed. A plan revised after an inconvenient "
                "estimate therefore shows up as a commit made after the run "
                "rather than as an unrecorded adjustment."
            ),
            "what_had_already_been_seen_when_this_was_written": (
                "Honesty about the starting point matters more than a claim of "
                "blindness. Before this specification was written, the session "
                "had read from the pinned archive: the record counts and "
                "PUBFLAG values re-derived under C1; the NEWID overlap between "
                "each shelter UCC and its published counterpart; the fact that "
                "COST is identical on none of the shared (NEWID, REF_YR, "
                "REF_MO) keys for any of the four pairs; and, for the timeshare "
                "pair alone, that the unweighted COST distributions differ by "
                "roughly a factor of forty. It had also read the published LB01 "
                "2024 means for the four counterparts, which are the comparison "
                "target and are pinned below. No weighted estimate for any of "
                "910104-910107 had been computed, and none of the thresholds, "
                "estimands or diagnostics below was chosen with such an "
                "estimate in view."
            ),
        },
        "source_archive": {
            "url": archive["url"],
            "sha256": archive["sha256"],
            "bytes": archive["bytes"],
            "members_relied_on": archive["members_relied_on"],
            "registry": "registry/research/pumd_2024_interview_source_v0_1.json",
            "reproduction": {
                "phase": "C1",
                "commit": SOURCE_REPRODUCTION_COMMIT,
                "status": "REPRODUCED",
                "artifact": (
                    "data/research/detailed_inflation/shelter_2024/"
                    "shelter_source_observation.json"
                ),
            },
        },
        "estimator": {
            "identity": (
                "Exactly the estimator that passed the Phase-B benchmark and "
                "the out-of-sample confirmation. This task adds no estimator "
                "code. The arithmetic is pumd.weighted_ucc_means and "
                "pumd.population_estimates, called unmodified."
            ),
            "frozen_commit": FROZEN_ESTIMATOR_COMMIT,
            "frozen_tag": FROZEN_ESTIMATOR_TAG,
            "confirmation": {
                "commit": CONFIRMATION_COMMIT,
                "status": "PASS",
                "spec": "registry/research/pumd_lb01_confirmation_spec_v0_1.json",
                "uccs": 111,
                "cells": 666,
                "note": (
                    "The confirmation is what makes this estimator usable "
                    "outside the fifteen UCCs it was built on. It is not a "
                    "warrant for the shelter UCCs specifically; see "
                    "known_limitations."
                ),
            },
            "pinned_module_digests": module_digests(),
            "prohibited_here": [
                "any shelter-specific scaling factor",
                "any calibration of a shelter estimate to any published value",
                "any annualization method other than the one below",
                "any change to quintile assignment or quintile boundaries",
                "any change to the population denominator",
                "any post-hoc adjustment of an estimate after it is seen",
                "substituting a published counterpart's value for a shelter estimate",
            ],
        },
        "method": {
            "calendar_year": pumd.BENCHMARK_YEAR,
            "files": {
                "fmli": [name for name, _m, _r in pumd.QUARTER_FILES],
                "mtbi": [name for _f, name, _r in pumd.QUARTER_FILES],
                "join": "inner join of MTBI onto FMLI on NEWID for the numerator",
                "denominator": "the full FMLI file, not the joined subset",
            },
            "calendar_year_eligibility": (
                "MTBI rows with REF_YR == 2024, matching the BLS sample "
                "program's filter on reference year alone. Reference month "
                "does not restrict."
            ),
            "final_weight": pumd.FINAL_WEIGHT_VARIABLE,
            "replicate_weights": (
                f"WTREP01-WTREP{pumd.REPLICATE_WEIGHT_COUNT:02d}"
            ),
            "population_denominator": (
                "sum(FINLWT21 * MO_SCOPE / 12) over all consumer units in the "
                "population. MO_SCOPE is QINTRVMO - 1 in the first quarter "
                "file, 4 - QINTRVMO in the fifth, and 3 otherwise."
            ),
            "expenditure_numerator": (
                "sum(FINLWT21 * COST * factor) over the calendar-year-eligible "
                "records, using the UNADJUSTED final weight. The asymmetry "
                "between numerator and denominator is the BLS sample "
                "program's and is preserved, not corrected."
            ),
            "quintile_assignment": {
                "income_variable": pumd.INCOME_VARIABLE,
                "lower_limits": list(pumd.PUBLISHED_QUINTILE_LOWER_LIMITS_2024),
                "units": "dollars of income before taxes",
                "source": "Table 1101, row 'Lower limit', as published by BLS",
                "note": (
                    "Consumer units are assigned to quintiles using the limits "
                    "BLS publishes, not a reconstruction of the BLS algorithm. "
                    "Unchanged from the benchmark."
                ),
            },
            "brr": {
                "replicates": pumd.REPLICATE_WEIGHT_COUNT,
                "formula": "SE = sqrt((1/44) * sum over r of (mean_r - mean)^2)",
                "source": "PUMD Getting Started Guide 6.3.2 and the BLS sample program",
            },
            "annualization": {
                "rule": (
                    "The per-UCC factor is column 6 of the hierarchical "
                    "grouping file, value 1 or 4, defaulting to 1 for a UCC "
                    "the file does not carry. This is the benchmark's rule, "
                    "applied unchanged."
                ),
                "factor_applied_to_910104_910107": 1,
                "why_the_default_applies": (
                    "910104-910107 appear in neither CE-HG-Inter-2024.txt nor "
                    "CE-HG-Integ-2024.txt, so no factor is published for them "
                    "and the default of 1 is used. This is a real gap and is "
                    "recorded as such under known_limitations rather than "
                    "presented as a published value."
                ),
                "factor_published_for_the_four_counterparts": 1,
                "counterpart_stub_evidence": (
                    "910050, 910101, 910102 and 910103 are all present in both "
                    "2024 stub files at level 3, survey I, section ADDENDA, "
                    "factor 1. The four codes conceptually paired with the "
                    "shelter UCCs therefore carry the same factor the default "
                    "supplies, which is corroboration for the default and not "
                    "a substitute for a published value."
                ),
                "no_periodicity_correction_is_applied": (
                    "The estimator sums every calendar-year-eligible monthly "
                    "record and divides by the annual population, which yields "
                    "an annual figure for a monthly-reported item. No further "
                    "multiplication or division by 12 is performed anywhere, "
                    "for any UCC, under any circumstance."
                ),
            },
        },
        "uccs": {
            "estimated": list(ESTIMATED_UCCS),
            "track_a_inputs": list(SHELTER_UCCS),
            "validation_counterparts": list(PUBLISHED_COUNTERPART_UCCS),
            "interpretation": {
                "910104": {
                    "concordance_title": "Rental Equivalence Of Owned Home",
                    "eli": "HC011",
                    "eli_title": "Owners' Equivalent Rent Of Primary Residence",
                    "shelter_concept": "OWNER_OCCUPIED_PRIMARY_RESIDENCE",
                    "sampled_eli": True,
                    "role": "Track-A rental-equivalence input for owner-occupied primary residence.",
                },
                "910105": {
                    "concordance_title": "Rent Equiv Vac Home Not Avail Rnt",
                    "eli": "HC090",
                    "eli_title": "Unsampled residual, owned vacation homes",
                    "shelter_concept": "SECONDARY_RESIDENCE_NOT_AVAILABLE_FOR_RENT",
                    "sampled_eli": False,
                    "role": "Track-A rental-equivalence input for a secondary residence held out of the rental market.",
                },
                "910106": {
                    "concordance_title": "Rent Equiv Vac Home Avail For Rnt",
                    "eli": "HC090",
                    "eli_title": "Unsampled residual, owned vacation homes",
                    "shelter_concept": "SECONDARY_RESIDENCE_AVAILABLE_FOR_RENT",
                    "sampled_eli": False,
                    "role": "Track-A rental-equivalence input for a secondary residence offered for rent. The thinnest cell in the set; see thin_cells.",
                },
                "910107": {
                    "concordance_title": "Rental Equivalence For Timeshares",
                    "eli": "HC090",
                    "eli_title": "Unsampled residual, owned vacation homes",
                    "shelter_concept": "TIMESHARE",
                    "sampled_eli": False,
                    "role": "Track-A rental-equivalence input for timeshare interests.",
                },
            },
            "correspondence": {
                "claim_type": "DMI_INFERENCE",
                "evidence_strength": "MODERATE",
                "pairs": {
                    "910050": "910104",
                    "910101": "910105",
                    "910102": "910106",
                    "910103": "910107",
                },
                "this_is_not_a_bls_crosswalk": (
                    "BLS publishes no crosswalk between the published ADDENDA "
                    "codes and the concordance-only codes, and none is asserted "
                    "here. Each pair is a DMI inference from matching concept "
                    "names and matching order, carried forward from "
                    "ucc_provenance_classes_v0_1.json at the same claim_type "
                    "and the same evidence strength. This specification does "
                    "not upgrade it."
                ),
                "what_the_pairing_may_be_used_for": (
                    "Testing whether the ordinary estimator behaves sensibly on "
                    "an ADDENDA rental-equivalence line, by estimating the "
                    "published counterpart and comparing that estimate against "
                    "the published LB01 value."
                ),
                "what_the_pairing_may_not_be_used_for": [
                    "substituting a published counterpart value for a shelter estimate",
                    "inferring 910107 from 910103 or 910103 from 910107",
                    "inferring any shelter estimate from any published value",
                    "deriving a scaling factor from a counterpart comparison",
                ],
                "observed_structure_before_the_freeze": {
                    "note": (
                        "Measured from the pinned archive before this file was "
                        "written, and recorded because it bears directly on how "
                        "strong the pairing inference is. These are unweighted "
                        "source-structure facts about raw records. None is an "
                        "estimate and none may be read as one."
                    ),
                    "newid_overlap": (
                        "Near-total for three pairs. 910102 and 910106 are the "
                        "exception: 291 records over 85 consumer units against "
                        "45 records over 15."
                    ),
                    "cost_identity": (
                        "COST is identical on none of the shared (NEWID, REF_YR, "
                        "REF_MO) keys for any of the four pairs. The paired "
                        "codes are therefore not duplicates of one another, "
                        "which is consistent with one being a reported value "
                        "and the other an imputed equivalence but does not "
                        "establish that."
                    ),
                    "timeshare_scale_gap": (
                        "The unweighted COST distributions of 910103 and 910107 "
                        "differ by roughly a factor of forty. This is the "
                        "quantitative face of the published-title periodicity "
                        "anomaly and is a reason to treat the timeshare pairing "
                        "with more caution than the other three, not a reason "
                        "to convert one into the other."
                    ),
                },
            },
        },
        "estimands": {
            "unweighted_record_count": {
                "definition": "MTBI rows with REF_YR == 2024 for this UCC contributing to this population.",
                "units": "records",
            },
            "reporting_consumer_units": {
                "definition": "Distinct NEWIDs contributing at least one such record.",
                "units": "consumer units (unweighted)",
            },
            "weighted_population": {
                "definition": "sum(FINLWT21 * MO_SCOPE / 12) over the population. The estimate's denominator.",
                "units": "consumer units",
            },
            "annual_mean_per_consumer_unit": {
                "definition": "numerator / weighted_population.",
                "units": "dollars per consumer unit per year",
                "note": (
                    "A mean over ALL consumer units in the population, not over "
                    "those reporting the item. A consumer unit with no record "
                    "contributes to the denominator and not the numerator."
                ),
            },
            "annual_aggregate": {
                "definition": (
                    "sum(FINLWT21 * COST * factor) over the "
                    "calendar-year-eligible records, which is identically "
                    "annual_mean_per_consumer_unit * weighted_population."
                ),
                "units": "dollars per year",
                "also_reported_in": "millions of dollars per year, for comparability with published LB01 aggregate series",
            },
            "standard_error": {"definition": "BRR over 44 replicates.", "units": "dollars per consumer unit per year"},
            "relative_standard_error": {"definition": "100 * SE / |mean|.", "units": "percent"},
            "uncertainty_interval": {
                "definition": f"mean +/- {INTERVAL_Z:.6f} * SE",
                "coverage": INTERVAL_COVERAGE,
                "units": "dollars per consumer unit per year",
                "declared_limitation": (
                    "A normal approximation. For a cell resting on fifteen "
                    "consumer units it is not credible as a coverage "
                    "statement and is reported as a width, not as a promise. "
                    "No better interval is manufactured, because manufacturing "
                    "one would require a distributional assumption this task "
                    "has no basis for."
                ),
            },
        },
        "required_quality_diagnostics": [
            "unweighted record count, by UCC and population",
            "distinct reporting consumer units, by UCC and population",
            "weighted population denominator",
            "BRR standard error and relative standard error",
            "the number of replicates whose estimate for the cell is zero",
            "minimum and maximum replicate mean",
            "the spread of replicate means relative to the point estimate",
            "whether the relative standard error exceeds the informational threshold",
        ],
        "thin_cells": {
            "no_minimum_record_cutoff_is_invented": (
                "No BLS publication rule authorising a minimum-record cutoff "
                "for PUMD estimates was located, so none is imposed. A cell is "
                "not dropped, suppressed or zeroed for being small."
            ),
            "high_rse_is_informational": {
                "threshold_pct": HIGH_RSE_INFORMATIONAL_THRESHOLD_PCT,
                "carried_forward_from": "the project's existing Milestone-1 RSE diagnostic",
                "status": "WARNING_ONLY",
                "explicitly_not": (
                    "a usability rule, an exclusion criterion, or a licence to "
                    "substitute zero. Promoting it to any of those would need "
                    "methodological authority this task does not have."
                ),
            },
            "validity_and_precision_are_separate": (
                "estimator_validity is a property of the method and is settled "
                "by the benchmark and the confirmation. estimate_precision is a "
                "property of one cell and is settled by its standard error. A "
                "valid estimator can yield a noisy estimate, and a noisy "
                "estimate is not evidence against the estimator."
            ),
            "known_thin_cell": {
                "ucc": "910106",
                "records_all_reference_years": 45,
                "records_in_benchmark_year": 40,
                "reporting_consumer_units_in_benchmark_year": 15,
                "disclosure": (
                    "Reported at every population, including quintiles where "
                    "the count will be lower still and may reach zero. It is "
                    "not hidden, not aggregated away and not rounded out."
                ),
            },
        },
        "empty_and_missing_cells": {
            "rule": (
                "A UCC/population cell with no calendar-year-eligible record is "
                "reported with cell_status = NO_RECORDS and a null mean. It is "
                "never reported as zero."
            ),
            "why": (
                "Zero is an estimate: it asserts that consumer units in that "
                "population spend nothing on the concept. Absence of a record "
                "in a sample asserts nothing of the kind. Collapsing the two "
                "would put a fabricated zero into any aggregate built on top."
            ),
            "downstream_obligation": (
                "A null must propagate as unresolved. Any Phase-D accounting "
                "that meets one must carry it as unresolved rather than "
                "treating it as zero to make a total balance."
            ),
        },
        "counterpart_validation": {
            "why_it_is_needed": (
                "Every UCC in the development roster and in the 111-UCC "
                "confirmation set came from the EXPEND section of the "
                "hierarchical grouping file. The estimator has therefore never "
                "been run against an ADDENDA line. 910104-910107 are not "
                "ADDENDA lines either - they are in no stub file at all - but "
                "their four conceptual counterparts are, and LB01 publishes "
                "means for all four across all six populations. That makes the "
                "counterparts the only available test of the estimator on this "
                "section and this concept family."
            ),
            "what_it_is_not": (
                "It is not a second confirmation gate and its outcome does not "
                "change confirmation_status. It is not a route by which a "
                "counterpart value may become a shelter value. It produces no "
                "correction factor under any outcome."
            ),
            "published_targets_2024": {
                "source": "LABSTAT cx.data.1.AllData, LB01, period A01, year 2024, process code M",
                "units": "dollars per consumer unit, at the periodicity BLS publishes for each line",
                "values": {
                    "910050": {"01": 1556, "02": 755, "03": 1082, "04": 1323, "05": 1757, "06": 2856},
                    "910101": {"01": 63, "02": 23, "03": 36, "04": 33, "05": 70, "06": 154},
                    "910102": {"01": 18, "02": 4, "03": 10, "04": 12, "05": 36, "06": 30},
                    "910103": {"01": 1220, "02": 274, "03": 309, "04": 648, "05": 1555, "06": 3301},
                },
            },
            "predictions_stated_before_the_estimates_exist": {
                "note": (
                    "These are predictions, not thresholds. A wrong prediction "
                    "is recorded as a wrong prediction and is not revised after "
                    "the fact. Nothing in the estimator depends on any of them."
                ),
                "P1_monthly_lines": (
                    "The published titles of 910050, 910101 and 910102 say "
                    "'Estimated monthly rental value'. The estimator sums twelve "
                    "monthly records and divides by the annual population, so "
                    "its output is annual. The ratio "
                    "estimate / published is therefore predicted to be "
                    "approximately 12 for these three, at All Consumer Units "
                    "and at every quintile."
                ),
                "P2_annual_line": (
                    "910103's published title says 'Estimated annual rental "
                    "value'. If BLS publishes an annual figure while the "
                    "microdata carries the annual amount on each monthly "
                    "record, the ratio would be approximately 12 as well; if "
                    "the microdata carries a monthly amount, the ratio would be "
                    "approximately 1. Which of these holds is not known at the "
                    "time of writing and is the specific question the timeshare "
                    "case turns on."
                ),
                "P3_interpretation_if_P1_holds": (
                    "A ratio near 12 on the monthly lines means the estimator "
                    "is behaving correctly and the published ADDENDA series is "
                    "simply on a different periodicity. It is a units "
                    "difference in the published target, not an error in the "
                    "estimate, and it is corrected in neither direction."
                ),
                "P4_interpretation_if_P1_fails": (
                    "A ratio that is neither near 12 nor near 1, or that varies "
                    "materially across populations, would be evidence that the "
                    "ordinary estimator does not transfer to ADDENDA "
                    "rental-equivalence lines. Under that outcome the affected "
                    "shelter UCCs are flagged and withdrawn from rule "
                    "adjudication, per Phase C3. They are not repaired."
                ),
            },
            "ratio_consistency_tolerance_pct": 10.0,
            "ratio_consistency_rule": (
                "The ratio is called consistent across populations for a UCC "
                "when every population's ratio is within 10 percent of that "
                "UCC's All-Consumer-Units ratio. This threshold is declared "
                "here, before the ratios exist, and is used only to describe "
                "the counterpart evidence. It gates nothing and adjusts nothing."
            ),
        },
        "known_limitations": {
            "no_published_value_exists_for_the_shelter_uccs": (
                "LB01 publishes no series for 910104-910107, so their estimates "
                "cannot be validated directly against anything. This is the "
                "irreducible limit of the exercise: the confirmation "
                "establishes that the estimator reproduces published values on "
                "111 UCCs it never saw, and the counterpart comparison "
                "establishes how it behaves on the neighbouring published "
                "ADDENDA lines, but neither is a check on these four amounts "
                "themselves."
            ),
            "no_stub_row_means_no_published_annualization_factor": (
                "The factor of 1 applied to 910104-910107 is the estimator's "
                "default for an absent UCC, corroborated by the four "
                "counterparts carrying factor 1, not a factor BLS publishes "
                "for these codes. If BLS applies a different factor internally, "
                "these estimates would be wrong by that factor and nothing here "
                "would detect it."
            ),
            "imputed_concept": (
                "All four are equivalence concepts, not recorded outlays. The "
                "CE collects them as respondent estimates of rental value. What "
                "the CPI does with them between the concordance and the "
                "published weight is not established, and cpi_adjustment_status "
                "stays INFERRED."
            ),
            "the_estimator_was_confirmed_on_expend_lines_only": (
                "Stated here rather than left to be discovered. The 111-UCC "
                "confirmation set is entirely EXPEND-section. The counterpart "
                "validation exists precisely because of this gap and only "
                "partly closes it."
            ),
        },
        "outputs": {
            "directory": "data/research/detailed_inflation/shelter_2024",
            "files": [
                "shelter_estimates_2024.csv",
                "counterpart_validation_2024.csv",
                "shelter_estimation_summary.json",
            ],
        },
    }


# --------------------------------------------------------------------------
# C3-C5: run the frozen plan
# --------------------------------------------------------------------------


def load_spec(path: Path = SPEC_PATH) -> dict:
    if not path.exists():
        raise ShelterEstimationError(
            f"the shelter estimation specification has not been frozen: {path}. "
            "C2 requires it to exist, and to be committed, before any amount "
            "is computed."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def assert_estimator_untouched(spec: Mapping[str, object]) -> None:
    """Stop if any pinned module has changed since the freeze.

    The prohibition on shelter-specific tuning is only as good as the check
    that nothing was tuned. A digest comparison catches an edit to the
    estimator between freezing the plan and running it, which is the one
    window in which such an edit would otherwise be invisible.
    """
    pinned = dict(spec["estimator"]["pinned_module_digests"])  # type: ignore[index]
    measured = module_digests(tuple(pinned))
    drifted = sorted(name for name in pinned if pinned[name] != measured.get(name))
    if drifted:
        raise ShelterEstimationError(
            "these modules changed after the estimation plan was frozen, so "
            "the estimator that would run is not the one the plan pinned: "
            + ", ".join(drifted)
        )


@dataclass(frozen=True)
class ShelterCell:
    """One UCC by one population, with everything C4 requires."""

    ucc: str
    population: str
    cell_status: str

    unweighted_record_count: int
    reporting_consumer_units: int
    weighted_population: float

    annual_mean_per_consumer_unit: float | None
    annual_aggregate_dollars: float | None
    standard_error: float | None
    relative_standard_error_pct: float | None
    interval_low: float | None
    interval_high: float | None

    replicate_min: float | None
    replicate_max: float | None
    replicates_at_zero: int | None

    @property
    def annual_aggregate_millions(self) -> float | None:
        if self.annual_aggregate_dollars is None:
            return None
        return self.annual_aggregate_dollars / 1_000_000.0

    @property
    def high_rse(self) -> bool:
        rse = self.relative_standard_error_pct
        return rse is not None and rse >= HIGH_RSE_INFORMATIONAL_THRESHOLD_PCT


def estimate_cells(
    units: Sequence[pumd.ConsumerUnit],
    records: Sequence[pumd.ExpenditureRecord],
    uccs: Sequence[str] = ESTIMATED_UCCS,
) -> list[ShelterCell]:
    """Run the frozen estimator over the shelter UCCs and their counterparts.

    The point estimate, the standard error and the population denominator all
    come from :mod:`pumd`. What this function adds is the per-cell bookkeeping
    C4 asks for and the replicate-stability diagnostics C5 asks for, neither
    of which changes a single estimate.
    """
    populations = pumd.population_estimates(units)
    # The annualization factor for every UCC here is the estimator's default
    # for a UCC absent from the stub, which is 1. Passing an empty mapping
    # invokes exactly that default rather than restating it as a value.
    estimates = pumd.weighted_ucc_means(units, records, populations, {})

    by_newid = {u.newid: u for u in units}
    reporters: dict[tuple[str, str], set[str]] = {}
    replicate_means: dict[tuple[str, str], list[float]] = {}

    slots = pumd.REPLICATE_WEIGHT_COUNT + 1
    buckets: dict[tuple[str, str], list[float]] = {}
    for record in records:
        unit = by_newid[record.newid]
        quintile = pumd.assign_quintile(unit.income_before_taxes)
        weights = (unit.final_weight,) + unit.replicate_weights
        for population in (pumd.ALL_CONSUMER_UNITS, quintile):
            key = (record.ucc, population)
            reporters.setdefault(key, set()).add(record.newid)
            bucket = buckets.setdefault(key, [0.0] * slots)
            for index, weight in enumerate(weights):
                if weight > 0:
                    bucket[index] += weight * record.cost

    for key, bucket in buckets.items():
        estimate = populations[key[1]]
        denominators = (
            estimate.consumer_units,
        ) + estimate.replicate_consumer_units
        replicate_means[key] = [
            (bucket[i] / denominators[i]) if denominators[i] > 0 else 0.0
            for i in range(1, slots)
        ]

    cells: list[ShelterCell] = []
    for ucc in uccs:
        for population in pumd.POPULATIONS:
            key = (ucc, population)
            weighted_population = populations[population].consumer_units
            estimate = estimates.get(key)
            if estimate is None:
                cells.append(
                    ShelterCell(
                        ucc=ucc,
                        population=population,
                        cell_status=NO_RECORDS,
                        unweighted_record_count=0,
                        reporting_consumer_units=0,
                        weighted_population=weighted_population,
                        annual_mean_per_consumer_unit=None,
                        annual_aggregate_dollars=None,
                        standard_error=None,
                        relative_standard_error_pct=None,
                        interval_low=None,
                        interval_high=None,
                        replicate_min=None,
                        replicate_max=None,
                        replicates_at_zero=None,
                    )
                )
                continue
            replicates = replicate_means[key]
            mean = estimate.mean
            error = estimate.standard_error
            cells.append(
                ShelterCell(
                    ucc=ucc,
                    population=population,
                    cell_status=ESTIMATED,
                    unweighted_record_count=estimate.reporting_records,
                    reporting_consumer_units=len(reporters[key]),
                    weighted_population=weighted_population,
                    annual_mean_per_consumer_unit=mean,
                    annual_aggregate_dollars=mean * weighted_population,
                    standard_error=error,
                    relative_standard_error_pct=estimate.relative_standard_error_pct,
                    interval_low=mean - INTERVAL_Z * error,
                    interval_high=mean + INTERVAL_Z * error,
                    replicate_min=min(replicates),
                    replicate_max=max(replicates),
                    replicates_at_zero=sum(1 for r in replicates if r == 0.0),
                )
            )
    return cells


# --------------------------------------------------------------------------
# The counterpart comparison
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterpartComparison:
    """One published ADDENDA line, estimated and compared against LB01."""

    ucc: str
    population: str
    published_mean: float
    estimated_mean: float
    ratio: float
    published_periodicity: str


#: Periodicity as stated in each counterpart's own published title. Read from
#: cx.item, not inferred from the numbers.
PUBLISHED_PERIODICITY: Mapping[str, str] = {
    "910050": "MONTHLY",
    "910101": "MONTHLY",
    "910102": "MONTHLY",
    "910103": "ANNUAL",
}


def compare_counterparts(
    cells: Sequence[ShelterCell], spec: Mapping[str, object]
) -> list[CounterpartComparison]:
    """Ratio of the estimate to the published LB01 value, per cell.

    The ratio is reported. It is never applied. No branch of this function
    multiplies an estimate by anything.
    """
    published = spec["counterpart_validation"]["published_targets_2024"]["values"]  # type: ignore[index]
    code_by_population = {
        label: code
        for code, label in {
            "01": pumd.ALL_CONSUMER_UNITS,
            "02": "Q1",
            "03": "Q2",
            "04": "Q3",
            "05": "Q4",
            "06": "Q5",
        }.items()
    }
    comparisons: list[CounterpartComparison] = []
    for cell in cells:
        if cell.ucc not in published:
            continue
        if cell.cell_status != ESTIMATED or cell.annual_mean_per_consumer_unit is None:
            continue
        code = code_by_population[cell.population]
        target = float(published[cell.ucc][code])
        if target == 0:
            continue
        comparisons.append(
            CounterpartComparison(
                ucc=cell.ucc,
                population=cell.population,
                published_mean=target,
                estimated_mean=cell.annual_mean_per_consumer_unit,
                ratio=cell.annual_mean_per_consumer_unit / target,
                published_periodicity=PUBLISHED_PERIODICITY[cell.ucc],
            )
        )
    return comparisons


def ratio_consistency(
    comparisons: Sequence[CounterpartComparison], tolerance_pct: float
) -> dict[str, dict[str, object]]:
    """Is a UCC's ratio stable across populations, at the declared tolerance?"""
    by_ucc: dict[str, list[CounterpartComparison]] = {}
    for comparison in comparisons:
        by_ucc.setdefault(comparison.ucc, []).append(comparison)

    result: dict[str, dict[str, object]] = {}
    for ucc, group in by_ucc.items():
        anchor = next(
            (c.ratio for c in group if c.population == pumd.ALL_CONSUMER_UNITS), None
        )
        ratios = [c.ratio for c in group]
        if anchor is None or anchor == 0:
            result[ucc] = {
                "all_cu_ratio": anchor,
                "min_ratio": min(ratios),
                "max_ratio": max(ratios),
                "consistent": False,
                "note": "no All Consumer Units ratio to anchor on",
            }
            continue
        deviations = [abs(r - anchor) / abs(anchor) * 100.0 for r in ratios]
        result[ucc] = {
            "all_cu_ratio": anchor,
            "min_ratio": min(ratios),
            "max_ratio": max(ratios),
            "max_deviation_pct": max(deviations),
            "consistent": max(deviations) <= tolerance_pct,
            "published_periodicity": PUBLISHED_PERIODICITY[ucc],
        }
    return result
