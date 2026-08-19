# C3 — Internal reconciliation and full-universe coverage, 2024

Detailed Inflation Substrate v0.1, task C3. Research only. Pre-normalization.

**Input checkpoint:** `dmi-detailed-inflation-v0.1-canonical-ledger-2024` →
`47ff8513205635851fc5979f7a771003c9295bc9`

Two verdicts, deliberately reported separately:

| | |
|---|---|
| `internal_reconciliation_status` | **PASS** |
| `full_universe_coverage_status` | **MATERIAL_EXPANSION_REQUIRED** |

The distinction is the point of this task. The canonical ledger accounts for
every dollar it contains, exactly, with no residual and no balancing category.
It also covers about two-thirds of the published expenditure universe, and one
of the fourteen DMI nodes has no representation in it at all. Both statements
are true, and only the first is reassuring.

---

## C3-A — Internal accounting reconciliation

### Two accounting systems, not merged

**Source side** answers *what happened to the CE source amounts?* Restricted to
`PUBLISHED_CE_BASIS` rows, because that is the only source class carrying
published CE dollars. A rental-equivalence amount estimated from microdata
never was a published CE dollar; inserting it here would make the source side
count money BLS never published.

```
E_source = retained + excluded_effective + removed_for_replacement
         + transformed + pending + open + withheld
```

**Track-A side** answers *what is currently in force?*

```
E_track_a_effective = retained_effective + replacement_effective + transformed_effective
```

with `excluded_effective`, `pending`, `open` and `withheld` reported beside it
and never folded in. An amount that is blocked is not an amount that is zero.

### Results, in millions of dollars

| Population | E_source | Source residual | E_track_a_effective | Δ_scope |
|---|---:|---:|---:|---:|
| ALL_CU | 6,836,520 | **0.000000** | 8,124,511.81 | 1,287,991.81 |
| Q1 | 688,872 | **0.000000** | 854,361.44 | 165,489.44 |
| Q2 | 959,951 | **0.000000** | 1,182,887.88 | 222,936.88 |
| Q3 | 1,223,874 | **0.000000** | 1,438,790.01 | 214,916.01 |
| Q4 | 1,572,916 | **0.000000** | 1,857,768.95 | 284,852.95 |
| Q5 | 2,390,913 | **0.000000** | 2,790,707.53 | 399,794.53 |

Source buckets, All Consumer Units: retained 5,509,878; excluded 1,148,566;
transformed 120,803; pending 46,322; open 10,951; removed-for-replacement 0;
withheld 0.

Amounts not in force, All Consumer Units, decomposed because the two halves are
different kinds of number:

```
pending_source_amount         =  46,322.000000   published CE, rule proposed
pending_replacement_amount    = 102,234.815688   microdata estimate, rule not in force
pending_total_admitted_amount = 148,556.815688   exactly the sum
withheld_replacement_amount   =     665.471372   produced, failed a quality gate
```

Withheld is **not** part of pending. The secondary-residence replacement side
therefore totals 102,900.287060, of which the pending part is admitted as an
estimate and the withheld part is not. Open is 10,951.

### Why the residual is exactly zero, and why that is not luck

Every ledger row populates exactly one amount column, and that column is the
one its disposition maps to, and its value **is** the row's source amount. C2
moves amounts between buckets and never rescales them. So the source identity
closes by construction, and the meaningful test is not whether the sum
balances but whether the construction is intact — asserted cell by cell across
all 2,076 rows.

This has a consequence worth stating: a mutation that changes a source amount
*and* its bucket together produces no residual, because both are the same
cell. What a lost dollar actually looks like is the bucket and the source
amount disagreeing, or a published amount reaching no bucket at all. Those are
what the guards detect, and what the mutation tests inject.

No tolerance is used anywhere in C3-A. Amounts are read as `decimal.Decimal`
over the ledger's fixed-point strings, so sums are exact.

### Replacement accounting stays non-balancing

| Group | Removal side | Replacement side | Δ_replacement |
|---|---|---|---|
| `RG_PRIMARY_RESIDENCE_RENTAL_EQUIVALENCE` | none declared | 2,493,830.81 effective | **not defined** |
| `RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE` | 12,620 pending | 102,900.29 pending | **not defined** |

The primary group declares no removal side. The registry states the rule
removes nothing and that the outlays it displaces leave under their own
out-of-scope rules, with no arithmetic depending on their amounts. Subtracting
those outlays here would invent the very linkage the registry declines to
make, so no delta is defined and the row says why.

The secondary group is PENDING on both sides. Neither is in force, so no delta
is defined. It remains pending; C3 does not adjudicate it.

### Δ_scope and Δ_shelter, re-derived — and one finding

Both are recomputed from ledger rows. Nothing is read from the shelter
concept-comparison artifact, so agreement is a reproduction rather than a
restatement.

| Quantity, ALL_CU | Reproduced | Frozen checkpoint |
|---|---:|---:|
| e_source | 6,836,520.000000 | 6,836,520.000000 |
| e_cpi | 8,124,511.812994 | 8,124,511.812994 |
| Δ_scope | 1,287,991.812994 | 1,287,991.812994 |
| `delta_shelter_frozen_membership` | 1,601,697.812994 | 1,601,697.812994 |
| `delta_shelter_current_state` | **1,402,618.812994** | — |

Both readings are published only under those qualified names — no artifact
emits a bare `delta_shelter` field — and every row carries its own
interpretation: the frozen reading is labelled
`HISTORICAL_CHECKPOINT_COMPARABILITY` and reproduces the frozen published
value; the other is `CURRENT_GOVERNING_RULE_STATE` and is derived from the
rules accepted as of this commit.

**Classification: `DIFFERENCE_IN_ACCOUNTING_DEFINITION`.**

Δ_scope reproduces exactly. Δ_shelter reproduces exactly *only* under the
removal membership frozen at the shelter checkpoint — mortgage interest and
charges plus residential property tax, 892,133.

Owner maintenance services, 199,079, was `OWNER_OUTLAY` and PROPOSED at that
checkpoint and is ACCEPTED and out of scope now. Under a current-state reading
of "owner outlays removed", Δ_shelter is smaller by exactly that amount.

The residual task recorded Δ_shelter as unchanged and justified it by noting
that pending and accepted-out-of-scope both sit outside the CPI basis, so the
basis and both deltas cannot move. **That argument is sufficient for Δ_scope,
whose second term is the CPI basis. It is not sufficient for Δ_shelter, whose
second term is a removal set.** The invariance is real, but it rests on the
membership being pinned at the shelter checkpoint, not on the bucket-movement
argument given.

Both readings are reported. Neither number is adjusted, and no rule state is
revisited. Which definition should govern is a question for review, not for
C3.

---

## C3-B — Full-universe coverage

### The denominator was established, not assumed

The universe is derived from `cx.series` metadata: `category_code == EXPEND`,
`demographics_code == LB01`, one of the six Income-Quintile populations,
`begin_year <= 2024 <= end_year`, and a six-digit numeric item code. No UCC
list appears anywhere in the coverage module — a test asserts the source
contains no six-digit literals.

**581 numeric UCCs, not 998.** `cx.item` holds 998 numeric item codes; 417 are
either inactive in 2024 or belong to the `ADDENDA`, `INCOME` and `CUCHARS`
categories, which are not expenditure. Summing all 998 would have been wrong
twice over.

**Additivity was tested for every domain, not inherited from Milestone 1.**
The Milestone-1 parent reconciliation was re-run across all 14 CE domains × 6
populations, using the same bound derived from BLS's publication rounding —
`0.5 × (leaves + 1)` — rather than a tuned tolerance.

- 84 of 84 domain × population cells additive.
- The 14 domain roots sum to published `TOTALEXP` in all six populations
  (ALL_CU: 10,655,034 vs 10,655,034, difference 0, bound 7.5).

`full_universe_additivity_established = true`. Had it failed, no expenditure
ratio would have been produced at all.

### Coverage

| Population | Universe | Consumption universe | Canonical | Share of universe | Share of consumption |
|---|---:|---:|---:|---:|---:|
| ALL_CU | 10,655,036 | 9,013,835 | 6,836,520 | **64.16%** | **75.84%** |
| Q1 | 950,125 | 909,708 | 688,872 | 72.50% | 75.72% |
| Q2 | 1,359,501 | 1,247,179 | 959,951 | 70.61% | 76.97% |
| Q3 | 1,805,133 | 1,584,810 | 1,223,874 | 67.80% | 77.23% |
| Q4 | 2,444,889 | 2,057,892 | 1,572,916 | 64.33% | 76.43% |
| Q5 | 4,095,373 | 3,214,233 | 2,390,913 | **58.38%** | 74.39% |

The consumption variant excludes `CASHCONT` (transfers) and `INSPENSN`
(insurance and pensions). Both denominators are reported; choosing between
them is a scope judgement C3 does not make.

**Structural UCC coverage is 337/581 = 58.00%**, a count diagnostic only. It is
not the expenditure share and is never substituted for it.

Coverage falls as income rises. Q5 is the least covered population on the full
denominator, which matters because the unaudited domains are not distributed
evenly across the distribution.

### Node coverage — all 14, including the empty one

| Node | State | Canonical UCCs | Omitted UCCs | Omitted ALL_CU |
|---|---|---:|---:|---:|
| FOOD | AUDITED_AND_REPRESENTED | 78 | 0 | 0 |
| ALCOHOLIC_BEVERAGES | AUDITED_AND_REPRESENTED | 4 | 0 | 0 |
| SHELTER | AUDITED_AND_REPRESENTED | 6 | 0 | 0 |
| HOUSEHOLD_ENERGY | AUDITED_AND_REPRESENTED | 20 | 0 | 0 |
| WATER_SEWER_TRASH | AUDITED_AND_REPRESENTED | 8 | 0 | 0 |
| HOUSEHOLD_FURNISHINGS_OPERATIONS | AUDITED_AND_REPRESENTED | 95 | 0 | 0 |
| **APPAREL** | **ABSENT_FROM_CANONICAL_BASIS** | **0** | 49 | 270,861 |
| TRANSPORT_COMMODITIES_EX_MOTOR_FUEL | AUDITED_AND_REPRESENTED | 15 | 0 | 0 |
| MOTOR_FUEL | AUDITED_AND_REPRESENTED | 3 | 0 | 0 |
| TRANSPORT_SERVICES | AUDITED_AND_REPRESENTED | 26 | 0 | 0 |
| **MEDICAL_CARE** | PARTIALLY_REPRESENTED | 2 | 41 | 841,186 |
| **RECREATION** | PARTIALLY_REPRESENTED | 1 | 91 | 489,524 |
| EDUCATION_COMMUNICATION | PARTIALLY_REPRESENTED | 16 | 15 | 230,038 |
| OTHER_GOODS_SERVICES | PARTIALLY_REPRESENTED | 5 | 32 | 345,706 |

A node is never called covered because a UCC maps to it. Recreation carries
one canonical UCC against 91 omitted published UCCs worth 489,524; Medical
care carries two against 41 worth 841,186. Apparel has nothing.

### Omitted-UCC ledger

244 UCCs, 3,818,516 million for All Consumer Units.

| CE domain | UCCs | ALL_CU |
|---|---:|---:|
| INSPENSN | 7 | 1,330,097 |
| HEALTH | 41 | 841,186 |
| ENTRTAIN | 91 | 489,524 |
| CASHCONT | 9 | 311,104 |
| APPAREL | 49 | 270,861 |
| EDUCATN | 8 | 213,036 |
| MISC | 20 | 165,353 |
| PERSCARE | 8 | 132,521 |
| TOBACCO | 4 | 47,832 |
| READING | 7 | 17,002 |

Classifications: `OUTSIDE_M1_AUDIT_SCOPE` 228,
`NONCONSUMPTION_OR_SCOPE_REVIEW_REQUIRED` 16. Every omitted UCC carries one
classification, an observable reason, and `requires_scope_adjudication = true`.

**Concordance absence is recorded and never used as a reason.** Milestone 2
established that a UCC missing from the CE-to-CPI concordance is not thereby
out of CPI scope. Each omitted row carries `concordance_status` as a fact;
importing that inference as an omission reason would silently adjudicate 244
UCCs.

Candidate DMI nodes on omitted rows are derived from the CE domain and are
**diagnostic only** — declared in the coverage spec, flagged on every row, and
never a mapping decision.

---

## Verdicts

### `internal_reconciliation_status = PASS`

Source accounting closes exactly in all six populations. Track-A effective
accounting is reported independently. Node totals reconstruct population
totals exactly. Replacement accounting remains non-balancing. No residual
category, rescaling or plug exists anywhere.

### `full_universe_coverage_status = MATERIAL_EXPANSION_REQUIRED`

No percentage decided this. Ten of the fourteen CE expenditure domains have
never had the mapping, provenance and scope discipline the four audited
domains received. They carry roughly a third of published total expenditure
and about a quarter of consumption expenditure. Every node that is not fully
represented is a node whose expenditure sits in those domains, and Apparel —
a top-level CPI major group — has no canonical representation at all.

The specified default applies, and the evidence supports it rather than
arguing against it.

**Recommendation: perform domain expansion before C4 review.** The current
ledger is an excellent denominator for the four domains it audits and is not
yet a defensible all-items normalization denominator. C3 does not perform that
expansion.

---

## Methodology metadata

Recorded in `data/research/detailed_inflation/c3_2024/c3_summary.json`:
checkpoint tag and SHA, canonical manifest and ledger digests, sha256 of
`cx.series`/`cx.item`/`cx.aspect`, source vintages, universe construction rule
and inclusion/exclusion list, additivity validation result, population
ordering, node taxonomy version, and the arithmetic and tolerance policies.

Artifacts are deterministic: no timestamps, hostnames, usernames or absolute
paths, LF serialization throughout, and `build_c3_2024.py --check` rebuilds
them in memory and compares byte for byte.

## Non-goals observed

No normalized weight, CPI price acquisition, inflation calculation, Core,
Baseline or Slack-Plus change. No omitted UCC received a Track-A rule,
disposition or node adjudication. No scope rule was extended. The frozen
C1+C2 artifacts were read and never written; C3 adds files and modifies none.
