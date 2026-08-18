# Detailed Inflation Substrate v0.1 — Track-A Shelter (2024)

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**Core DMI remains withdrawn and unimplemented.** This task computes no
inflation index, constructs no weights, normalizes nothing to one, acquires no
CPI price data and produces no DMI release. Nothing here is imported by
`dmi_calculator`, by the Baseline or Slack-Plus specifications, or by any
release workflow. The Operational Baseline is unchanged.

**Two of the four shelter rules are still not settled**, and they are held for
reasons that producing an estimate does not address. See §7.

---

## 1. What this task was for

[Milestone 2](DETAILED_INFLATION_MILESTONE_2.md) resolved 58 unmapped UCCs into
ten CE→CPI scope rules and then stopped at a wall. Four rules covering
$1,137,534M — 16.64% of the detailed basis — stayed `PROPOSED`. Every one of
them carried the same sentence:

> Takes effect only jointly with the Track-A rental-equivalence rule.

You cannot remove a homeowner's mortgage interest from a consumption basis
unless something else prices the shelter that interest was buying. Milestone 2
was right to refuse.

This task asks whether that condition can now be met, and answers it in four
ordered phases with gates between them.

| Phase | Question | Result |
| --- | --- | --- |
| A | Is the 2024 PUMD benchmark preserved? | Re-run, PASS reproduced, tagged `dmi-detailed-inflation-v0.1-pumd-benchmark-2024` |
| B | Does the estimator work on UCCs it was never tuned on? | **PASS** on 111 previously unused UCCs, 666 cells |
| C | Can the four rental-equivalence UCCs be estimated? | Three yes, one no |
| D | Do the four pending rules now resolve? | Two yes, two no |

---

## 2. The finding that made the rest possible

**Milestone 2's blocking condition was unsatisfiable as written, and not
because the evidence was missing.**

All four rules were made conditional on "the Track-A rental-equivalence rule".
The v0.1 registry contains ten rules and **none of them is that rule**. Nobody
ever wrote it. There was nothing for evidence to attach to.

So Phase D writes it — and writes it in two parts, because the pinned BLS
concordance already splits the concept and there was no reason to pretend
otherwise:

| New rule | UCCs | ELI | Status |
| --- | --- | --- | --- |
| `TA_OWNER_RENTAL_EQUIVALENCE_PRIMARY_v0_1` | 910104 | HC011, *Owners' Equivalent Rent Of Primary Residence* (sampled) | **ACCEPTED / EFFECTIVE** |
| `TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1` | 910105, 910106, 910107 | HC090 (unsampled residual) | **PROPOSED / PENDING** |

The split is not a convenience. HC011 is a sampled ELI that BLS prices
directly; HC090 is an unsampled residual. One of them is a much stronger place
to stand than the other, and the accounting reflects that.

---

## 3. Headline results (All Consumer Units, millions of 2024 dollars)

| Quantity | Amount |
| --- | ---: |
| `E_source` — CE observed outlay basis | 6,836,520 |
| Rental equivalence introduced (910104 only) | **+2,493,831** |
| Owner outlays removed (mortgage interest, property tax) | **−892,133** |
| `Delta_shelter` | **+1,601,698** |
| `E_CPI` | 8,124,512 |
| `Delta_scope` | **+1,287,992** |

**`Delta_shelter` is not zero and was not made to be zero.** Replacing owner
cash outlays with an imputed rental flow changes the size of the basis by 1.6
trillion dollars. That is what the substitution *means*. Nothing here rescales,
renormalises, allocates a residual or applies a balancing factor. The only sums
checked anywhere are that each total equals its own parts:

```
E_source = retained + accepted_transformed + accepted_out_of_scope
         + pending_proposed + unresolved_open
E_CPI    = retained + accepted_transformed + rental_equivalence_introduced
```

Neither identity compares the two bases to each other. A test constructs an
accounting row whose bases differ by a factor of 9.5 and asserts it is
accepted, so that the decomposition checks cannot be mistaken for a balance
requirement.

Per quintile:

| Population | `E_source` | Rent equiv. | Removed | `Delta_shelter` | `Delta_scope` |
| --- | ---: | ---: | ---: | ---: | ---: |
| All CU | 6,836,520 | 2,493,831 | 892,133 | +1,601,698 | +1,287,992 |
| Q1 | 688,872 | 238,213 | 49,260 | +188,953 | +165,489 |
| Q2 | 959,951 | 348,689 | 84,170 | +264,519 | +222,937 |
| Q3 | 1,223,874 | 409,607 | 132,582 | +277,025 | +214,916 |
| Q4 | 1,572,916 | 565,763 | 211,580 | +354,183 | +284,853 |
| Q5 | 2,390,913 | 931,559 | 414,540 | +517,019 | +399,795 |

$2.49T of imputed primary-residence rent is in the right neighbourhood of BEA's
roughly $2.0T imputed rent of owner-occupied housing. The two are not the same
construct and the agreement is a sanity check, not a validation.

---

## 4. Phase B: the estimator was confirmed before it was trusted

The PUMD estimator was built and checked against four shelter-adjacent series.
Using it on new UCCs on that basis would have been circular. Phase B therefore
froze a roster **before running any comparison** and ran the estimator against
every remaining eligible UCC:

- **111 UCCs, 666 cells**, none of them previously used to build or tune anything
- Result: **PASS**
- No tuning of any kind was permitted, and none was performed

The frozen roster, the run and the reasoning are written up in
[PUMD_2024_ESTIMATOR_CONFIRMATION.md](PUMD_2024_ESTIMATOR_CONFIRMATION.md),
with artifacts under
`data/research/detailed_inflation/pumd_confirmation_2024/`.

---

## 5. Phase C: three of the four UCCs are usable, and one is not

### 5.1 A hypothesis was falsified, in public

Milestone 2 carried an inference (**P1**) that the four `9101xx` addenda were
monthly figures whose published counterparts were annual, so that a factor of
twelve would relate them. Phase C measured it. The counterpart ratios come out
at approximately **1.00, not 12**. P1 is wrong, and it is recorded as wrong
rather than quietly dropped. The published ADDENDA statistics go through the
same annualisation machinery as everything else.

### 5.2 The estimates

| UCC | Concept | All-CU aggregate | RSE | Usability | Quality |
| --- | --- | ---: | ---: | --- | --- |
| 910104 | Rental equivalence of owned home | 2,493,831 | 1.30% | BENCHMARKED | **HIGH** |
| 910105 | Rent equiv., vacation home not available for rent | 93,019 | 8.34% | BENCHMARKED | MODERATE |
| 910106 | Rent equiv., vacation home available for rent | 665 | 60.64% | **NOT_ESTABLISHED** | **UNUSABLE** |
| 910107 | Rental equivalence for timeshares | 9,216 | 31.79% | BENCHMARKED | LOW |

**910107 is BENCHMARKED and LOW at the same time.** That combination is the
entire point of keeping usability and precision as separate fields. A valid
procedure can produce a noisy number. The frozen plan forbade the 25% RSE flag
from becoming a usability rule, and a test mutates the RSE across five orders
of magnitude and asserts that no usability verdict moves.

### 5.3 Why 910106 was refused

Not because it is imprecise. Because the estimator does not reach it.

- **Q1 has no records at all** — not a small number, none
- **Q2 has 3 records, and 22 of 44 replicate estimates are exactly zero**

When half the balanced half-samples contain none of the reporting consumer
units, the replicate-weight variance estimator is *degenerate*: it is computing
a standard error of something other than the quantity of interest. That is a
procedure failure, not noise, and it is the kind of failure that a
"reasonable-looking" RSE would have concealed.

The Q1 cell is `NO_RECORDS` and carries **null**, not `0.00`, through the
dataclass, the CSV and the JSON. A test asserts each.

### 5.4 The pairing was measured, not assumed

Milestone 2's UCC correspondence was a `DMI_INFERENCE` resting on matching
concept names in matching order. Phase C6 measured it at the record level,
*after* the estimates existed, and said so:

| Pair | Shared keys | Relation |
| --- | ---: | --- |
| 910050 → 910104 | 36,740 | `TWELVE_TIMES` on 87.9% |
| 910101 → 910105 | 1,425 | `TWELVE_TIMES` on 79.6% |
| 910102 → 910106 | 40 | **`NO_CLEAN_RELATION`** |
| 910103 → 910107 | 590 | `WEEKS_OWNED_SHARE` on 87.6% |

The 910103 → 910107 result matters for a specific prohibition. `52 × ratio` is
a whole number on 517 of 590 keys, distributed `{1: 304, 2: 140, 3: 20, 4: 24,
6: 13, 7: 10, 12: 6}`. **910103 is the whole timeshare property's annual rental
value; 910107 is the share of weeks this consumer unit owns.** They are
different estimands. Neither may be inferred from the other, and neither is.

---

## 6. Track A and Track B are two concepts, not two arithmetics

| | Track A (CPI-compatible) | Track B (household payments) |
| --- | --- | --- |
| Mortgage interest, home equity interest (8 UCCs) | REMOVED_OUT_OF_SCOPE | RETAINED |
| Residential property tax (2 UCCs) | REMOVED_OUT_OF_SCOPE | RETAINED |
| Owner structure investment (8 UCCs) | PENDING | RETAINED |
| Secondary residence costs (15 UCCs) | PENDING | RETAINED |
| 910104 rental equivalence | **INTRODUCED** | NOT_INTRODUCED |
| 910105, 910107 | held by a PENDING rule | NOT_INTRODUCED |
| 910106 | **WITHHELD** | NOT_INTRODUCED |

Track B retains all 33 owner outlays and introduces none of the four addenda.
It performs no substitution at all — that is what makes it a payments concept
rather than Track A with a sign flipped.

> **Track B is not the BLS Household Cost Index.** The HCI is a specific BLS
> construction with its own treatment of mortgage principal, insurance and
> durables, none of which is implemented here, and no attempt has been made to
> reproduce its published values. Calling this an HCI would be naming a thing
> that does not exist in this repository. A test asserts that no artifact makes
> that claim.

---

## 7. Phase D4: the four rules, adjudicated one at a time

Each rule was put to the six questions Phase D requires. **The existence of an
estimate does not accept a rule.** Two moved; two did not.

### ACCEPTED — `OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1` ($504,695M)

Two independent grounds, either sufficient. The CPI Handbook states that
"interest costs and finance charges are also out-of-scope" — that holds
regardless of how shelter is treated. And the replacement now exists for the
primary residence, which is $494,917M of the $504,695M.

### ACCEPTED — `OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1` ($387,438M)

"The CPI excludes income tax and other direct taxes." A market rent already
embeds the landlord's property tax, so pricing owner shelter by rental
equivalence *and* retaining the tax would count it twice.

### HELD — `OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1` ($232,781M)

This rule had **two** recorded blockers. The shelter one cleared. The other did
not, and nothing in this task speaks to it: **BLS does not enumerate these eight
UCCs.** The membership rests on the DMI owner/renter counterpart test and
Milestone 2 graded it MODERATE and flagged it for reviewer attention on its own
merits.

Accepting it now would be promoting a structural inference on the strength of
an unrelated benchmark. The rule stays `PROPOSED` and its evidence grade stays
MODERATE.

### HELD — `RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1` ($12,620M)

This is a `REPLACE` rule: it removes fifteen owned-vacation outlays *and adds*
the secondary-residence rental equivalence. That addend is not available,
because the rule supplying it is itself pending. Executing it would require
substituting zero for a missing estimate, or inferring 910106 from 910102 —
both explicitly forbidden.

### HELD — `TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1` (new)

Two independent blockers:

1. The concept has three components and **910106 is not admissible**.
2. Casey 2010 Appendix B note 2: "in order to price the rental equivalence of
   secondary homes and timeshares, CPI uses a factor to account for the
   consumption portion of a homeowner's total expenditure." **That factor is
   not published.** This blocker would stand even if 910106 were fine.

### No evidence grade moved

Not up, not down. Grades were not lowered to obtain closure and not promoted
because an amount became calculable. A dataclass invariant raises if any code
path tries, and a test asserts the invariant fires.

---

## 8. Phase D3: the double-counting audit

Nine categories, each with an explicit Track-A and Track-B disposition:

| Category | Track A | All-CU $M |
| --- | --- | ---: |
| Primary-residence owner shelter (910104) | INTRODUCED | 2,493,831 |
| Mortgage and home-equity interest | REMOVED_OUT_OF_SCOPE | 504,695 |
| Residential property tax | REMOVED_OUT_OF_SCOPE | 387,438 |
| Owner repairs / improvements / structure investment | PENDING | 232,781 |
| Homeowners insurance, primary residence | RETAINED | 100,026 |
| Secondary and vacation residence costs | PENDING | 12,620 |
| Renter rent and renter-related costs | RETAINED | 755,603 |
| Utilities (19 UCCs) | RETAINED | 412,019 |
| Rental-equivalence addenda 910104–910107 | mixed | — |

The audit has two halves and both matter.

**Nothing survives that should have been removed.** Every UCC claimed by an
EFFECTIVE removing rule is gone from Track A. A test iterates the rules and
asserts it.

**Nothing was removed merely for being housing-associated.** Utilities and
renter rent are priced separately by the CPI and are not embedded in owners'
equivalent rent. They must survive a change in owner shelter treatment, and
they do. This failure would have been silent, which is why it gets its own row
and its own test.

### Three open items, flagged rather than fixed

**Homeowners insurance is retained in full, and whether that is too much is not
established.** Casey 2010 Appendix B note 3 records that the CPI reduces
homeowners insurance "to reflect only the renter's part of the owner's
expenditure. The factor applied is 43%." Two claims follow, and collapsing them
is the error to avoid:

| Claim | State |
| --- | --- |
| Historical BLS authority for a renter's-part allocation exists | `ESTABLISHED` |
| That factor, or a successor, governs the 2024 weighting vintage | `NOT_ESTABLISHED` |

The first is settled by a primary, dated BLS document. The second was not
investigated in this task, so nothing is known about it either way. Track A
retains 100% of $100,026M — not because 100% has been shown correct, but
because no adjudicated 2024 factor exists to apply. **No factor has been
applied**, and the magnitude of any overstatement is unknown: quoting "57%"
would silently promote a 2010 factor to a 2024 factor, which is precisely the
failure this workstream exists to avoid.

**$25,547M of owned-vacation outlays leave Track A with no replacement in
effect.** The mortgage-interest and property-tax rules are accepted and their
owned-vacation members ($9,778M + $15,769M) go with them, while the
secondary-residence rental equivalence is still PENDING. That is an
understatement of Track-A secondary shelter. It is reported as
`secondary_residence_outlays_removed_without_replacement` and is **not** netted,
offset or corrected.

**Owner structure investment sits in the pending bucket**, so the potential
duplication does not occur — and the category is not closed either.

---

## 9. Phase D5: the predecessors survive

Nothing was rewritten in place. Successors were written at new paths:

| Predecessor (unchanged) | Successor |
| --- | --- |
| `registry/research/ce_cpi_scope_rules_v0_1.json` (0.1.0) | `ce_cpi_scope_rules_v0_2.json` (0.2.0) |
| `registry/research/ucc_provenance_classes_v0_1.json` (0.2.0) | `ucc_provenance_classes_v0_3.json` (0.3.0) |

v0.2 carries all ten v0.1 rules plus the two new ones, records the predecessor
path and version, and lists **all four** reviewed rules under
`rule_reviews_from_v0_1` — including the two that did not move, marked
`status_changed: false`. A review that concludes "no change" is a result, and
the reason it reached that result is the useful part.

Tests assert that no UCC membership and no evidence grade changed between
versions, and that the **eleven open UCCs are untouched** — no rule written here
claims any of them. Solving those was explicitly not this task's business.

---

## 10. What is deliberately not done

- **No index.** No category inflation rate, no Core, no price data.
- **No weight normalisation.** Detailed node weights are not normalised here.
- **No balancing.** `Delta_shelter` and `Delta_scope` are reported as they fall out.
- **The 11 open UCCs from Milestone 1 are not resolved.**
- **910106 is not replaced by zero**, not inferred from 910102, and not dropped.
- **The Casey 43% insurance factor is recorded, not applied, and not assumed to
  hold for 2024.**
- **The Operational Baseline, Baseline and Slack-Plus are untouched.**

---

## 11. Known limitations

1. **910106 blocks a whole concept.** Secondary-residence rental equivalence
   cannot be stated while one of its three components is unusable, which in turn
   blocks `RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1`.
2. **The BLS secondary-home consumption factor is unpublished.** Even a usable
   910106 would not clear this.
3. **Homeowners insurance may be overstated in Track A, by an unknown amount.**
   Historical BLS authority for a renter's-part reduction is `ESTABLISHED`
   (Casey 2010, 43%); current-vintage applicability is `NOT_ESTABLISHED`. The
   full $100,026M is retained pending that second question. The 57% figure an
   earlier draft quoted assumed the 2010 factor still governs 2024, which is
   not known.
4. **910107 is LOW quality** at a 31.79% All-CU RSE. Admissible, and thin.
5. **Whether BLS adjusts 910104 before use is not established.** No BLS statement
   was located either way. The introduced amount is the CE addendum as
   estimated; no claim is made that BLS uses it unmodified.
6. **`OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1` remains the largest
   MODERATE-evidence exclusion in the registry**, unresolved on its own merits.
7. **The UCC pairing remains a `DMI_INFERENCE`**, now with record-level
   measurements attached. Measurement is not a BLS statement of equivalence.

---

## 12. How to run it

```bash
# Phase C: estimate and adjudicate (requires the pinned 2024 PUMD archive)
python3 scripts/estimate_shelter_2024.py   --pumd-dir <extracted-interview-dir>
python3 scripts/adjudicate_shelter_2024.py --pumd-dir <extracted-interview-dir>

# Phase D: tracks, accounting, audit, versioned registries (no PUMD needed)
python3 scripts/build_shelter_tracks_2024.py

# Tests
python3 -m pytest tests/test_detailed_inflation_shelter_estimation.py
python3 -m pytest tests/test_detailed_inflation_shelter_tracks.py
```

The adjudication runner recomputes the estimates rather than reading the CSV
back, and refuses to proceed if they no longer reproduce to 1e-9. An
adjudication built on an artifact that no longer reproduces would be an
adjudication of nothing.

---

## 13. Code map

| Path | Role |
| --- | --- |
| `dmi_research/detailed_inflation/shelter_source.py` | C1 archive observation |
| `dmi_research/detailed_inflation/shelter_estimation.py` | C3–C5 estimation, frozen-plan enforcement |
| `dmi_research/detailed_inflation/shelter_adjudication.py` | C6 usability and quality |
| `dmi_research/detailed_inflation/shelter_tracks.py` | D1–D5 tracks, accounting, audit, registries |
| `scripts/build_shelter_tracks_2024.py` | Phase D runner |
| `data/research/detailed_inflation/shelter_2024/` | All Phase C and D artifacts |
| `registry/research/shelter_estimation_spec_v0_1.json` | The frozen C2 plan |

Artifacts written by Phase D:

- `shelter_cpi_track_2024.csv`, `shelter_payments_track_2024.csv`
- `shelter_concept_comparison_2024.csv`
- `shelter_double_counting_audit_2024.csv`
- `shelter_rule_adjudication.json`, `shelter_accounting_summary.json`
- `registry/research/ce_cpi_scope_rules_v0_2.json`
- `registry/research/ucc_provenance_classes_v0_3.json`

---

## 14. Attribution

UCC codes and titles, ELI codes and titles, the CE hierarchical grouping files,
the CE Public Use Microdata, the CPI Handbook of Methods and the CE→CPI
concordance are publications of the U.S. Bureau of Labor Statistics. The
grouping of UCCs into scope rules, the rule identifiers, the usability and
quality scales, the track construction and every inference recorded here are
DMI research metadata and are not a BLS product.

BLS has not reviewed, approved or endorsed any of it.
