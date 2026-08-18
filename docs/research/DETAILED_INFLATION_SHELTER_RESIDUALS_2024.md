# Detailed Inflation Substrate v0.1 — Residual Track-A Shelter Questions (2024)

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**Core DMI remains withdrawn and unimplemented.** This task computes no
inflation index, constructs no weights, normalizes nothing to one, acquires no
CPI price data and produces no DMI release. Nothing here is imported by
`dmi_calculator`, by the Baseline or Slack-Plus specifications, or by any
release workflow. The Operational Baseline is unchanged.

**Verdict: `PARTIAL`.** One of the three questions is resolved on current BLS
evidence. The other two are blocked on parameters BLS describes and does not
publish. See [§10](#10-verdict).

---

## 1. What this task was for

The [shelter milestone](DETAILED_INFLATION_SHELTER_2024.md) left three
questions open. Each is an amount sitting in a bucket that is neither in the
CPI basis nor demonstrably out of it.

| Question | Amount, All CU | What the milestone said |
| --- | ---: | --- |
| Owner maintenance and structure investment | $232,781M | One rule, `PROPOSED`, membership resting on a DMI reading |
| Homeowners insurance | $100,026M | Retained at 100%; a historical 43% factor known, its 2024 applicability not |
| Secondary residence | $12,620M | `REPLACE` or `EXCLUDE` could not be told apart on the published record |

The task's instruction was not "resolve these". It was "resolve these **if
defensibly possible**, and say precisely why not otherwise". That distinction
does most of the work below.

---

## 2. The rule that governs everything else

> Historical sources may establish that a procedure once existed. Historical
> sources do not by themselves authorize applying a numerical factor to 2024.

Every piece of evidence in this task carries a machine-readable vintage class,
and the class decides what the evidence is allowed to do.

| Class | Count | What it may do |
| --- | ---: | --- |
| `CURRENT_2024_COMPATIBLE` | 9 | Support an `ACCEPTED` rule |
| `CURRENT_BUT_NONNUMERIC` | 1 | Establish a concept, never a number |
| `HISTORICAL_ONLY` | 3 | Establish that a procedure once existed |
| `DMI_INFERENCE` | 2 | Nothing, on its own. Labelled as ours |
| `NOT_FOUND` | 3 | Record that a search returned nothing |

A `NOT_FOUND` record is evidence. It is the difference between "we did not
look" and "we looked here, here and here, and it is not there". Each one names
the documents searched.

`registry/research/shelter_residual_evidence_v0_1.json` holds all 18 records,
each with the passage quoted, what it establishes, and — the field that
mattered most in practice — **what it does not establish**.

---

## 3. Issue 1: owner maintenance and structure investment

### 3.1 The predecessor rule offered a test, and the test fails

`OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1` covered eight UCCs and said how it
could be cleared:

> an independent check that no renter counterpart exists for the five
> maintenance members

That check was run against the 2024 CE integrated stub and the pinned
concordance. It does not work.

| Owner UCC | Renter counterpart | Owner mapped? |
| --- | --- | --- |
| 230112 Painting and papering | 230150, generic, → HP043 | **Yes**, → HP043 |
| 230113 Plumbing | 230150, generic, → HP043 | No |
| 230114 Heat, a/c, electrical | 230150, generic, → HP043 | No |
| 230115 Roofing and gutters | 230150, generic, → HP043 | No |
| 240213 Roofing materials | 240211, names *"roofing, and gutters"*, → HM090 | No |
| 240212 Plaster and siding | 240211, → HM090 | **Yes**, → HM090 |

`230112` has exactly the counterpart structure the four excluded services
have, and it is mapped. `240213` has a renter counterpart that names its own
concept explicitly, and it is not mapped. **Counterpart existence predicts
neither inclusion nor exclusion.** The criterion could not have cleared the
rule in either direction.

The falsified criterion is recorded in `ce_cpi_scope_rules_v0_3.json` under
`falsified_predecessor_criterion` rather than deleted, because a criterion
that failed is part of why the successors are shaped the way they are.

### 3.2 What replaced it

Two current BLS factsheets, independently, put most owner maintenance out of
scope:

> The rental equivalence approach used to measure price change in the cost of
> owner-occupied shelter renders household insurance for residential
> structures, along with **most spending on home maintenance and repairs**, out
> of scope.
> — *Tenant's and Household Insurance* factsheet, last modified May 20, 2026

> Interest costs (such as mortgage interest), property taxes, real estate
> fees, **most maintenance**, and all improvement costs are part of the cost of
> the capital good and are also not treated as consumption items.
> — *Rent and rental equivalence* factsheet

That establishes the concept. It does not establish membership, because
"most" is not a list. The pinned 2024 concordance supplies the list: an
unmapped UCC carries no CPI expenditure weight. This is the same evidentiary
shape that already underpins the `ACCEPTED` mortgage-interest and
property-tax rules.

### 3.3 The rule is split four ways

The predecessor combined four materially different concepts under one
criterion. The task permits splitting and forbids preserving a broad rule for
convenience, so it is split.

| Successor rule | UCCs | All CU | Status |
| --- | --- | ---: | --- |
| `OS_CPI_OWNER_MAINTENANCE_SERVICES_v0_2` | 230113, 230114, 230115, 230151 | $199,079M | **ACCEPTED / EFFECTIVE** |
| `OS_CPI_OWNER_ROOF_MATERIALS_ANOMALY_v0_2` | 240213 | $3,440M | `PROPOSED` |
| `OS_CPI_OWNER_SITE_PAYMENTS_v0_2` | 210901, 220901 | $12,574M | `PROPOSED` |
| `OS_CPI_OWNER_PROPERTY_MANAGEMENT_v0_2` | 230901 | $17,688M | `PROPOSED` |

$199,079 + $3,440 + $12,574 + $17,688 = $232,781M. The split partitions the
predecessor's membership exactly: no UCC is claimed twice and none is lost.
That is asserted, not asserted-in-prose.

The three held rules are held for **three different reasons**, which is the
point of splitting them:

- **`240213`, `BLOCKED_BY_CONTRADICTORY_MEMBERSHIP`.** It is the sole unmapped
  maintenance commodity in a branch where all eight siblings are mapped, and
  its renter counterpart names roofing and gutters explicitly. A clerical
  omission in the concordance and a deliberate scope decision are equally
  consistent with the record. Treating an anomaly as a finding would be
  reading the gap as permission.
- **`210901`, `220901`, `BLOCKED_BY_UNESTABLISHED_CONCEPT`.** No BLS source
  states the CPI treatment of ground rent or parking at an owned dwelling.
  The CE rent question for *renters* includes garage and parking charges,
  which hints at subsumption into shelter, but that is a DMI reading of a
  survey instrument, not a statement of CPI scope.
- **`230901`, `BLOCKED_BY_UNESTABLISHED_CONCEPT`.** Property management is not
  maintenance and not an improvement. Its `OWNMNAGE` sibling `340911` is
  mapped to HP090, so the stub container does not settle it either.

### 3.4 What this opened

Casey (2010) states that owner expenditures on home maintenance and repair are
weighted from *"the corresponding mean expenditures of renters"*. If that
procedure still operates, the eleven owner maintenance UCCs that **are** mapped
carry a CPI weight that is not their CE amount — and Track A retains them at
full CE value, about $59,921M. No current-vintage source restating the
procedure was located, and none denying it was located either.

So the direction is known and the size is not. Nothing is applied. The item is
recorded as `MAPPED_OWNER_MAINTENANCE_RETAINED_AT_CE_VALUE` with
`action_taken: NONE`. **It did not exist before this task**: the milestone
asked whether the unmapped maintenance codes should leave, and answering that
surfaced a question about the ones that stay.

---

## 4. Issue 2: homeowners insurance

### 4.1 The historical source, located and characterised

Casey (2010), Appendix B note 3:

> It is required that CPI reduce the homeowners insurance **weight** to reflect
> only the renter's part of the owner's expenditure. The factor applied is 43%.

That answers the question the task asked about which quantity the factor acts
on: **the expenditure weight**, not the price movement.

### 4.2 The current source says something stronger than "unconfirmed"

The *Tenant's and Household Insurance* factsheet, last modified May 20, 2026:

> Spending by renters on tenants' insurance is included. **Only a portion of
> spending by homeowners on homeowner's insurance is included** to reflect the
> scope of owner's equivalent rent.

> **Since January 2025**, information and data from the National Association of
> Insurance Commissioners are used to calculate a factor applied to the total
> spending by homeowners on homeowner's insurance to derive the portion of
> insurance premium that accounts for contents coverage. […] The **median value
> of those ratios** is the adjustment factor applied to spending by homeowners
> on homeowner's insurance.

Three things follow, and they are not the same thing:

1. **The concept is current.** A renter's-part allocation is exactly what BLS
   still does, and the in-scope portion is specifically *contents coverage*.
   This also resolves an ambiguity the milestone had flagged as a stop
   condition: HD011 pools tenants' and homeowners' insurance, and the scope
   question is now answered.
2. **43% is superseded, not merely unconfirmed.** The derivation was replaced
   in January 2025. Outcome A is excluded **affirmatively**.
3. **The replacement value is not published.** The factsheet describes the
   method in full and states no number.

### 4.3 What was deliberately not derived

The factsheet contains the sentence:

> the typical coverage limit for personal property is **approximately 50
> percent** of the value of the dwelling

That is a coverage limit at an intermediate step of the derivation. It is not
the adjustment factor. Using it as one would be exactly the move the task
forbids, and it is recorded under `does_not_establish` so that a later reader
does not have to rediscover why.

### 4.4 Outcome C, and what it does to Track A

`TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1` is a new `TRANSFORM` rule,
`PROPOSED`, `BLOCKED_BY_UNPUBLISHED_PARAMETER`, evidence strength
`STRONG_CONCEPT_NO_PARAMETER`, `factor_applied: null`.

No factor is stored on the rule deliberately. Storing 0.43 with
`is_applicable: false` would leave a superseded number one edit away from use.
The historical value appears in this repository only as a quotation inside an
evidence record classed `HISTORICAL_ONLY`; it exists nowhere as a numeric
literal the code could reach, and a test asserts that.

$100,026M stays retained in Track A and is now labelled an **upper bound**.
This is not an exception to the rule that a `PROPOSED` rule has no effect; it
is that rule applied correctly to a transform. Not applying a partial-retention
transform leaves the amount as recorded. Moving it to the pending bucket
instead would remove it from the CPI basis entirely, which would assert that
*none* of it is in scope — a claim current BLS text directly contradicts.

The milestone's position was "$100,026M of unknown correctness". The position
now is "$100,026M is an upper bound whose excess is real and unquantifiable".
That is a narrower claim, and it is the one the evidence supports.

---

## 5. Issue 3: secondary residence

### 5.1 The `REPLACE`-versus-`EXCLUDE` ambiguity is resolved

The milestone could not tell whether owned-vacation outlays are excluded
outright or displaced by an imputed rental flow. Footnote 1 of the OER
factsheet settles it:

> Rental equivalence for vacation homes and timeshares exist as items in the
> Consumer Expenditure Survey (UCC 910105, 910106, and 910107) and have a small
> amount of weight in the CPI as **Unsampled owners' equivalent rent of
> secondary residences (ELI HC090)**, but as this item is unsampled, no price
> quotes are actually collected for it.

The displacing item demonstrably exists, is named, is mapped, and carries
relative importance 0.973. `REPLACE` is the correct rule type.

It also answers a question the task asked directly — whether residence types
are treated differently. They are not: all three UCCs pool into one unsampled
ELI. There is no type-specific treatment to go looking for.

### 5.2 And the rules still do not clear

`RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1` stays `PROPOSED` under the task's own
standard: a `REPLACE` rule may be accepted only when all required
transformations are reproducible, and the replacement is not.

Casey (2010), Appendix B note 2:

> In order to price the rental equivalence of secondary homes and timeshares,
> CPI uses a factor to account for the consumption portion of a homeowner's
> total expenditure.

No current-vintage counterpart was located, across the rent and rental
equivalence factsheet and its footnotes, the rent/OER questions and answers,
the methodology-change notices for 2024 and 2025, and the Handbook of Methods.
That search is recorded as `NOT_FOUND`, not as silence.

### 5.3 Two blockers, kept apart

The milestone's `review_blocker` ran two limitations together in one
paragraph. They are not the same kind of problem and will not be fixed by the
same thing, so `residual_review.blockers` now carries them separately on both
affected rules:

| Blocker | Kind | Affects | Cleared by |
| --- | --- | --- | --- |
| `SECONDARY_CONSUMPTION_PORTION_FACTOR_UNPUBLISHED` | `PARAMETER` | 910105, 910106, 910107 | BLS publishing the factor, or stating the CE amounts enter unmodified |
| `UCC_910106_DEGENERATE_VARIANCE` | `SAMPLING` | 910106 | A PUMD vintage where 910106 has Q1 records and a non-degenerate Q2 replicate variance |

Each declares itself `independent_of` the other. Clearing either one alone
leaves both rules blocked on the other.

The predecessor's original `review_blocker` text is retained above the
annotation, unedited.

---

## 6. What was not done, and why that is the finding

The task named five ways to manufacture a missing number: approximate it, copy
the nearest historical factor, interpolate it, infer it from residual
accounting, or choose the value that makes `Delta_shelter` smaller. None was
used. Three parameters remain unavailable and are reported as unavailable.

`BLOCKED_BY_UNPUBLISHED_PARAMETER` is not a failure mode here. It is the
correct description of a state where BLS says a transformation happens and
does not say what it is.

---

## 7. Nothing was balanced

`Delta_scope` = **+$1,287,992M** and `Delta_shelter` = **+$1,601,698M**, before
and after, in every population, to the last decimal place.

That is not the result of tuning, and the reason is structural rather than
disciplinary. The buckets are related by three identities:

```
e_source     = retained + accepted_transformed + accepted_out_of_scope
                        + pending_proposed + unresolved_open
e_cpi        = retained + accepted_transformed + rental_equivalence_introduced
delta_scope  = rental_equivalence_introduced − accepted_out_of_scope
                        − pending_proposed − unresolved_open
```

`accepted_out_of_scope` and `pending_proposed` both sit outside the CPI-basis
total. Promoting $199,079M from one to the other **cannot** move `e_cpi`,
`delta_scope` or `delta_shelter`. All three identities are re-verified after
the move.

The one adjudication in this task that *would* have changed a delta is the
secondary-residence replacement rule. Accepting it would have moved $12,620M
out of the basis with nothing entering in its place, enlarging the reported
understatement from $25,547M to $38,167M. It was declined on evidence, not on
effect — a module quietly optimising the gap downward would have taken it.

The forbidden-vocabulary guard scans identifiers in the parse tree, not words
in the text, so the module's own prose saying it does not rescale cannot
satisfy the test. The guard is asserted to **fire** on each of `rescale`,
`normalize_to_total`, `balancing_factor`, `residual_allocation`,
`scaling_factor`, `calibration_ratio`, `historical_factor_as_current` and
others before it is asserted not to fire on the real modules. A guard that
never fires proves nothing.

---

## 8. Before and after

Millions of 2024 dollars, published CE aggregate basis.

| Population | `accepted_out_of_scope` | `pending_proposed` | `unresolved_open` |
| --- | ---: | ---: | ---: |
| ALL_CU | 949,487 → 1,148,566 | 245,401 → 46,322 | 10,951 → 10,951 |
| Q1 | 52,096 → 65,580 | 19,806 → 6,322 | 822 → 822 |
| Q2 | 90,773 → 116,478 | 33,787 → 8,082 | 1,192 → 1,192 |
| Q3 | 142,855 → 184,964 | 50,017 → 7,908 | 1,819 → 1,819 |
| Q4 | 228,848 → 265,907 | 49,295 → 12,236 | 2,767 → 2,767 |
| Q5 | 434,914 → 515,637 | 92,499 → 11,776 | 4,351 → 4,351 |

Unchanged in every population: `e_source`, `e_cpi`, `retained`,
`accepted_transformed`, `rental_equivalence_introduced`, `delta_scope`,
`delta_shelter`, `unresolved_open`.

**Conceptually resolved but parameter unavailable** and **concept itself
unresolved** are different states and are reported separately. The $46,322M
still pending splits by blocker kind, not by size:

| Blocker kind | Amount | Meaning |
| --- | ---: | --- |
| `BLOCKED_BY_UNESTABLISHED_CONCEPT` | $30,262M | The concept itself is unresolved |
| `BLOCKED_BY_UNPUBLISHED_PARAMETER` | $12,620M | Concept resolved, parameter unavailable |
| `BLOCKED_BY_CONTRADICTORY_MEMBERSHIP` | $3,440M | Concept resolved, membership contradicts itself |

---

## 9. Versioning

Predecessors are read and never written. Successors are written at new paths.
`scripts/build_shelter_tracks_2024.py` still reproduces the frozen milestone
state byte-for-byte.

| Predecessor | Successor | What changed |
| --- | --- | --- |
| `ce_cpi_scope_rules_v0_2.json` | `ce_cpi_scope_rules_v0_3.json` | One rule replaced by four; one rule added; two rules annotated |
| `ucc_provenance_classes_v0_3.json` | `ucc_provenance_classes_v0_4.json` | One `cpi_adjustment_status` becomes `VERIFIED` |

Every carried-forward rule body is byte-equal to its v0.2 self apart from an
**additive** `residual_review` block on the two annotated rules. A test
compares them field by field, because editing a predecessor in place while
writing it to a new path would satisfy every path-based check and would still
be the thing preservation exists to prevent.

`ucc_provenance_classes_v0_3.json` recorded that
`cpi_adjustment_status: VERIFIED` was *"Not asserted for any UCC in this
file."* The tenants' insurance factsheet is the first BLS documentation
located in this workstream that states an adjustment for a specific UCC, so
`220121` becomes the first — noting that the status asserts the adjustment
exists, not that its value is known.

---

## 10. Verdict

**`residual_shelter_status: PARTIAL`.**

Not `PASS`: two of three questions remain blocked. Not `BLOCKED`: the largest
single block cleared, and both remaining blockers are now named, dated and
separated.

| Issue | Amount | Outcome |
| --- | ---: | --- |
| Owner maintenance services | $199,079M | **ACCEPTED / EFFECTIVE / out of scope** |
| Owner roof materials | $3,440M | `BLOCKED_BY_CONTRADICTORY_MEMBERSHIP` |
| Owner site payments | $12,574M | `BLOCKED_BY_UNESTABLISHED_CONCEPT` |
| Owner property management | $17,688M | `BLOCKED_BY_UNESTABLISHED_CONCEPT` |
| Homeowners insurance | $100,026M | `BLOCKED_BY_UNPUBLISHED_PARAMETER`, **B5 Outcome C** |
| Secondary residence outlays | $12,620M | `BLOCKED_BY_UNPUBLISHED_PARAMETER` |
| Secondary rental equivalence | $102,235M | Parameter **and** sampling blockers, separated |

---

## 11. Artifacts

| Path | Contents |
| --- | --- |
| `registry/research/shelter_residual_evidence_v0_1.json` | 18 evidence records with vintage classes |
| `registry/research/ce_cpi_scope_rules_v0_3.json` | Successor scope rules |
| `registry/research/ucc_provenance_classes_v0_4.json` | Successor provenance classes |
| `data/research/detailed_inflation/shelter_residuals_2024/owner_structure_ucc_matrix_2024.csv` | UCC-level classification audit, 8 rows × 21 columns |
| `data/research/detailed_inflation/shelter_residuals_2024/residual_accounting_before_after_2024.csv` | Before/after by population and quantity |
| `data/research/detailed_inflation/shelter_residuals_2024/residual_rule_transitions.csv` | Every status transition with predecessor and vintage |
| `data/research/detailed_inflation/shelter_residuals_2024/residual_shelter_verdict.json` | Verdict, issue outcomes, open items |

Reproduce with:

```
python3 scripts/build_shelter_residuals_2024.py
python3 -m pytest tests/test_detailed_inflation_shelter_residuals.py
```

---

## 12. What a later reader should not conclude

- **Not** that owner maintenance is settled. Four codes left the basis; eleven
  mapped codes stayed at full CE value under an open question about renter-mean
  weighting.
- **Not** that homeowners insurance is retained correctly. It is retained
  because the correction is unavailable, and $100,026M is an upper bound.
- **Not** that secondary residence is excluded. It is displaced by an item that
  exists and carries weight; the replacement amount is what is missing.
- **Not** that `Delta_shelter` is now a measured quantity. It is what the
  accounting produces when the rules are applied as written, and three
  parameters that would move it are unavailable.
