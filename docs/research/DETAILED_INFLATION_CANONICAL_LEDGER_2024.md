# Detailed Inflation Substrate v0.1 — Canonical State and Accounting Ledger (2024)

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**Core DMI remains withdrawn and unimplemented.** This task computes no
inflation index, constructs no weights, normalizes nothing to one, acquires no
CPI price data and produces no DMI release. Nothing here is imported by
`dmi_calculator`, by the Baseline or Slack-Plus specifications, or by any
release workflow. The Operational Baseline is unchanged.

This is milestone **C1 + C2** of the substrate program. C1 answers *which
version of what governs?* C2 answers *where does each source expenditure
amount currently sit?* Neither answers *how much is it worth?*, and both are
built so that they cannot begin to.

---

## 1. The four statements this document is required to make

These are stated first, plainly, because every design decision below follows
from one of them.

> **The canonical ledger is a pre-normalization accounting surface. It records
> the current disposition of each source expenditure amount but does not create
> expenditure shares or index weights.**

> **PENDING, OPEN and WITHHELD amounts remain part of the epistemic accounting
> record. They are not treated as zero and are not silently removed from a
> future normalization denominator.**

> **Absence from the public CE→CPI concordance is evidence about the crosswalk,
> not independently sufficient evidence that a concept receives no CPI weight
> through another production transformation.**

> **Replacement accounting is conceptual rather than balancing: a replacement
> amount is not required to equal the source outlay it replaces.**

---

## 2. What C1 + C2 produce

| Artifact | What it is |
| --- | --- |
| `registry/research/canonical_substrate_manifest_2024_v0_1.json` | C1. Which vintages, registry versions and rules govern the current state |
| `registry/research/canonical_ledger_schema_v0_1.json` | C2. The ledger's columns, vocabularies, invariants and null semantics |
| `data/research/detailed_inflation/canonical_substrate_2024/ucc_population_accounting_ledger.csv` | C2. 2,076 rows: 346 UCCs × 6 populations |
| `data/research/detailed_inflation/canonical_substrate_2024/canonical_ledger_summary.json` | A row-count diagnostic. Not a reconciliation |

Built by `scripts/build_canonical_substrate_2024.py`, which also has a
`--check` mode that rebuilds in memory and compares bytes.

Implementation lives in `dmi_research/detailed_inflation/canonical_state.py`
(C1) and `canonical_ledger.py` (C2). Tests are in
`tests/test_detailed_inflation_canonical_ledger.py`.

---

## 3. C1: why the head of a registry family has to be derived

The repository deliberately holds several versions of the same registry side by
side. Three scope-rule registries, three provenance registries. Deleting the
old ones would destroy the evidence of what was believed at each checkpoint,
so they stay.

That creates a question no filename can answer: **which one governs now?**

The obvious heuristic — take the highest version number in the directory — is
wrong in this repository, and provably so:

> `registry/research/ucc_provenance_classes_v0_1.json` declares
> `"version": "0.2.0"`. There is no `ucc_provenance_classes_v0_2.json`.

A filename is a label someone typed. So the head of each family is **derived**
by walking the `predecessor` block that each successor carries, and the walk
refuses to guess: it fails if the chain forks, if it has two roots, if it has a
cycle, or if a declared predecessor is missing. The head is the unique node no
other node claims as its predecessor.

### 3.1 The governing versions this derivation selects

| Family | Head | Version | Why |
| --- | --- | --- | --- |
| `ce_cpi_scope_rules` | `ce_cpi_scope_rules_v0_3.json` | 0.3 | `v0_3` names `V0_2` as predecessor; `v0_2` names `v0_1`; nothing names `v0_3` |
| `ucc_provenance_classes` | `ucc_provenance_classes_v0_5.json` | 0.5 | `v0_5` names `V0_4`; `v0_4` names `V0_3`; `v0_3` names `v0_1` (**not** a nonexistent `v0_2`) |

Seven further registries exist in exactly one version and are recorded as
`CURRENT_GOVERNING_INPUT` without a lineage walk: the taxonomy, the ELI→node
map, the PUMD 2024 Interview source pin, the LB01 benchmark and confirmation
specs, the shelter estimation spec, and the shelter residual evidence registry.

### 3.2 Checkpoints: historical authority is not current authority

All four frozen tags are recorded with their dereferenced commits, and each
carries an explicit role.

| Tag | Commit | Role |
| --- | --- | --- |
| `dmi-detailed-inflation-v0.1-m2-corrected` | `e640209` | `HISTORICAL_CHECKPOINT` |
| `dmi-detailed-inflation-v0.1-pumd-benchmark-2024` | `95111fd` | `HISTORICAL_CHECKPOINT` |
| `dmi-detailed-inflation-v0.1-shelter-partial-2024` | `5d1e513` | `HISTORICAL_CHECKPOINT` |
| `dmi-detailed-inflation-v0.1-shelter-residuals-2024` | `3ee9141` | `CURRENT_GOVERNING_INPUT` |

The distinction is the point. A frozen registry from the M2 checkpoint is
authoritative evidence of what M2 concluded. It is not an input to current
work. Exactly one checkpoint holds the `CURRENT_GOVERNING_INPUT` role, and the
manifest says which.

### 3.3 Rule lineage

Seventeen rules appear in the lineage graph: sixteen present in the governing
registry, one absent from it.

| State | Count |
| --- | ---: |
| `CURRENT_EFFECTIVE` | 9 |
| `CURRENT_PENDING` | 6 |
| `CURRENT_OPEN` | 1 |
| `SUPERSEDED` | 1 |
| `HISTORICAL_ONLY` | 0 |
| `NOT_APPLICABLE` | 0 |

`HISTORICAL_ONLY: 0` is stated rather than left to be inferred from an absence
of entries. "No rule was dropped without a successor" is a finding; an empty
section is not.

The one supersession:

```
OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1   (SUPERSEDED)
  ├── OS_CPI_OWNER_MAINTENANCE_SERVICES_v0_2   CURRENT_EFFECTIVE
  ├── OS_CPI_OWNER_PROPERTY_MANAGEMENT_v0_2    CURRENT_PENDING
  ├── OS_CPI_OWNER_ROOF_MATERIALS_ANOMALY_v0_2 CURRENT_PENDING
  └── OS_CPI_OWNER_SITE_PAYMENTS_v0_2          CURRENT_PENDING
```

The successor list is read out of the governing registry's `predecessor`
declarations. It is not transcribed from anywhere, including from the task that
created the split.

The graph is checked to be exhaustive and disjoint: the predecessor's eight
UCCs are partitioned across the four successors with nothing lost and nothing
claimed twice, and no UCC is claimed by both the predecessor and a successor.

### 3.4 The resolver

`UCC -> exactly one current governing rule`. Six states, with the semantics
recorded in the manifest rather than left to the reader:

| State | Meaning |
| --- | --- |
| `CURRENT_EFFECTIVE` | In the governing registry, `ACCEPTED` and applicable. May populate an effective amount |
| `CURRENT_PENDING` | In the governing registry, proposes a disposition not in force. **May never** populate an effective exclusion, transformation or replacement |
| `CURRENT_OPEN` | In the governing registry, proposes nothing. Undecided, which is not blocked |
| `SUPERSEDED` | Absent, with successors naming it. Its UCCs belong to them. Never resolvable |
| `HISTORICAL_ONLY` | Absent, with no successor naming it. It existed and was dropped |
| `NOT_APPLICABLE` | No rule applies |

Sixty-three UCCs are claimed as a rule source and one (`510115`) as an
output-only transformation destination. **Every one of them is claimed by
exactly one current rule.** A second claim is a build failure, not a warning:
the amount would have two treatments and no principled way to choose. There is
no fall-back to file order anywhere, because a rule that appears earlier in a
file is not thereby more authoritative.

### 3.5 Three inconsistencies recorded, then repaired in a successor

`UCC_PROVENANCE_CLASSES_V0_4` contained prose passages that went stale when its
own structured fields were updated. Each asserted, in the present tense, that
`pumd_quantitative_usability` was `NOT_ESTABLISHED` for every UCC it covered,
while the roster in the same file graded `910104`, `910105` and `910107`
`BENCHMARKED` and `usability_transitions_from_v0_1` recorded the three
transitions that put them there.

C1 recorded both readings and declined to fix them, on the ground that
**changing a governing registry's text is an adjudication** and C1 was
authorised to describe the current state, not revise it. That authorisation was
subsequently given, and `UCC_PROVENANCE_CLASSES_V0_5` supersedes v0.4 with the
prose corrected. Two points about how:

- **v0.4 is preserved byte-for-byte.** It is still on disk, still the version
  the frozen Residual Shelter Allocation milestone pins and regenerates, and
  still the artifact the recorded contradictions are attributed to. The
  correction is a successor, not an edit, so the stale text stays recoverable
  and nothing pinned to v0.4 moved.
- **The head moved on its own.** Nothing in the manifest names v0.5. The
  lineage walk found it because v0.5 declares v0.4 as its predecessor and
  nothing declares v0.5, which is the same derivation §3 describes and not a
  special case added for this.

There were three passages, not two. The reading that commissioned the repair
found two; the third was found by the scanner the repair installed, in
`pumd_observations`. That is the argument for having a test rather than a
careful reader, and it is why the entries are closed with a `repaired_in` field
rather than deleted: a consumer holding an older ledger still needs to be able
to find out why the prose they read no longer matches the file.

**No number moved.** The ledger reads `usability_transitions_from_v0_1` and
`shelter_rental_equivalence_correspondence.pairs[].published_ce_ucc` from this
registry and has never read a sentence from it. All 42 columns × 2,076 rows are
byte-identical across the correction, as is `canonical_ledger_summary.json` and
the ledger schema. The manifest changes in exactly two places: v0.4 is demoted
to `HISTORICAL_CHECKPOINT` with v0.5 appended as `CURRENT_GOVERNING_INPUT`, and
the contradiction records gain the third entry and their outcomes.

That the correction was invisible to the ledger is the finding, not a
disappointment. Prose that no consumer reads is exactly the prose that goes
stale without anything failing.

---

## 4. C2: the ledger

One row for every UCC × population, for `ALL_CU`, `Q1`, `Q2`, `Q3`, `Q4`, `Q5`.
346 UCCs, 2,076 rows, no exceptions.

### 4.1 The universe is not `cx.item`

Defining the ledger from the published CE item file alone would silently drop
every UCC the substrate needs but BLS does not publish an aggregate for. Four
source classes are carried instead:

| Source class | UCCs | Rows | What it is |
| --- | ---: | ---: | --- |
| `PUBLISHED_CE_BASIS` | 337 | 2,022 | The 2024 active numeric-UCC accounting basis, with a published LABSTAT aggregate |
| `CONCORDANCE_ONLY_ESTIMATED` | 4 | 24 | Named by the concordance, absent from `cx.item`. Any amount is estimated from microdata |
| `PUBLISHED_ADDENDUM_OUTSIDE_BASIS` | 4 | 24 | Published CE addenda the basis excludes to avoid double-counting what they duplicate |
| `TRANSFORMATION_DESTINATION` | 1 | 6 | A destination a rule combines other UCCs into. No source amount of its own |

The four addendum UCCs (`910050`, `910101`–`910103`) and the transformation
destination (`510115`) carry `source_amount_status = NOT_APPLICABLE` and no
amount at all — 30 rows. That is not missing data; no source amount is defined
for them.

### 4.2 Where amounts come from

| `amount_source` | Rows | |
| --- | ---: | --- |
| `LABSTAT_PUBLISHED` | 2,022 | Published by BLS in the CE aggregate series |
| `NOT_ADMISSIBLE_VALIDATION_ONLY` | 24 | An amount exists and the governing registry forbids taking a Track-A figure from it |
| `PUMD_BENCHMARKED` | 18 | Estimated from PUMD by an estimator whose quantitative usability is `BENCHMARKED` **for this UCC** |
| `PUMD_NOT_BENCHMARKED` | 6 | The same estimator, on a UCC still `NOT_ESTABLISHED` |
| `DERIVED_TRANSFORMATION` | 6 | Produced by applying a rule's transformation to other UCCs |

The split between the last two matters and is why `PUMD_BENCHMARKED` is not one
category. **Method validity is a property of the cell as well as of the
procedure.** A UCC is not PUMD-benchmarked because it exists in PUMD; it is
PUMD-benchmarked because the provenance registry records that transition for
that UCC. Three of the four rental-equivalence UCCs made it (`910104`,
`910105`, `910107`); `910106` did not.

### 4.3 Source amount status

| Status | Rows | Amount shown? |
| --- | ---: | --- |
| `OBSERVED` | 1,864 | Yes. Zero under this status is a genuine observed zero |
| `SUPPRESSED` | 176 | No. BLS publishes the series and did not publish this cell |
| `NOT_APPLICABLE` | 30 | No. No source amount is defined |
| `WITHHELD` | 5 | **Yes.** Produced and not admitted, because it failed a declared quality gate |
| `NOT_AVAILABLE` | 1 | No. No amount was produced at all |

`WITHHELD` shows its amount. That is deliberate. Withheld means *not admitted*,
not *unknown* — the number exists, it is known, and a reader who cannot see it
cannot judge how much is being held back.

---

## 5. Explicit Track-A accounting amounts

The core of C2. Eight separate amount columns, never one signed
`adjustment_amount`:

```
retained_amount            excluded_amount
removed_for_replacement_amount   replacement_amount
transformed_amount         pending_amount
open_amount                withheld_amount
```

Compressing these into a single net adjustment would make a row's accounting
role invisible: −$X could be an exclusion, a removal awaiting replacement, or
an amount held pending adjudication, and those are three different claims about
what is known.

**At most one amount column is non-blank on any row, and it is the column the
row's disposition maps to.** The mapping is a table, not a convention:

| Disposition | Column | Rows |
| --- | --- | ---: |
| `RETAINED` | `retained_amount` | 1,674 |
| `EXCLUDED` | `excluded_amount` | 132 |
| `PENDING` | `pending_amount` | 126 |
| `OPEN` | `open_amount` | 66 |
| `TRANSFORMED` | `transformed_amount` | 36 |
| `NOT_APPLICABLE` | *(none)* | 30 |
| `REPLACEMENT` | `replacement_amount` | 6 |
| `WITHHELD` | `withheld_amount` | 6 |
| `REMOVED_FOR_REPLACEMENT` | `removed_for_replacement_amount` | 0 |

`REMOVED_FOR_REPLACEMENT` is currently empty. The only rule that would produce
it — `RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1` — is `PENDING`, so its fifteen
UCCs sit in `pending_amount` instead. An empty column here is the correct
output, and it is worth noticing that it would be very easy to produce a
plausible-looking ledger in which those fifteen amounts had already been
removed.

### 5.1 The amount is never rescaled

> An accounting amount always equals the row's source amount.

C2 moves amounts between buckets. It does not scale, apportion or net them. A
partial-retention transform — "43% of homeowners insurance is contents" — is
arithmetic, and arithmetic is a later milestone's problem. The validator
rejects any row whose accounting amount differs from its source amount.

---

## 6. Proposed is not effective

This is the single claim the whole substrate rests on.

Four dispositions may only be reached from a rule in force: `EXCLUDED`,
`REMOVED_FOR_REPLACEMENT`, `REPLACEMENT`, `TRANSFORMED`. A rule in state
`CURRENT_PENDING` may reach none of them. The check is at one choke point,
which reads the rule's *canonical state* and never its declared `final_status`,
and it is duplicated in the row validator so a hand-built row cannot slip past.

The gate restates the hardened Milestone-2 gate
(`resolution.track_a_disposition`) because the older function's
`MappingStatus` type has five members and does not include `INTRODUCED`, while
the governing registry has two `INTRODUCE` rules. The duplication is *checked*
rather than trusted: a test runs both gates over every rule the older type can
express and requires them to agree.

### 6.1 "No effect" means baseline reversion, not a holding bucket

A `PENDING` rule does not automatically send its amount to the pending bucket.
What happens absent the rule depends on whether a rule-free baseline exists.

| `pending_rule_effect_on_amount` | Rows | |
| --- | ---: | --- |
| `AMOUNT_HELD_IN_PENDING_BUCKET` | 126 | No baseline: the UCC has no CPI mapping, or the rule would introduce a concept that does not otherwise exist |
| `AMOUNT_REVERTS_TO_MAPPED_BASELINE` | 6 | The UCC is mapped to an entry-level item, so absent the rule it is simply retained |
| `NOT_APPLICABLE` | 1,944 | The rule is in force, or there is none |

The six reverting rows are UCC `220121`, homeowners insurance, governed by
`TR_CPI_HOMEOWNERS_INSURANCE_CONTENTS_PORTION_v0_1` (`PENDING`). The registry
states this directly: the UCC is concordance-mapped, so not applying the
partial-retention transform leaves the amount where it already is. Moving
$100,026M to a pending bucket would remove it from the basis entirely — a
*larger* claim than the rule itself makes. The retained figure is recorded as
an upper bound of what the rule would leave.

---

## 7. Replacement is not removal

Two replacement groups are modelled, each with an explicit
`replacement_group_id` and per-row `replacement_role`.

### `RG_PRIMARY_RESIDENCE_RENTAL_EQUIVALENCE`

`replacement_rule_id = TA_OWNER_RENTAL_EQUIVALENCE_PRIMARY_v0_1`
(`CURRENT_EFFECTIVE`), `removal_rule_id = null`,
`linkage_basis = NO_REMOVAL_SIDE_DECLARED`.

One member: `910104`, rental equivalence of the owned home, `REPLACEMENT`,
$2,493,831M All CU from a `BENCHMARKED` PUMD estimate.

The removal side is deliberately **not asserted**. The registry states that
this rule removes nothing, and that the primary-owner outlays it displaces are
removed by their own rules, on out-of-scope grounds, with no arithmetic
depending on their amounts. Reading those outlays as this concept's removal
side would create a linkage the registry explicitly declines to create — and
would look, downstream, like a balancing relationship that nobody asserted.

### `RG_SECONDARY_RESIDENCE_RENTAL_EQUIVALENCE`

`removal_rule_id = RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1`,
`replacement_rule_id = TA_OWNER_RENTAL_EQUIVALENCE_SECONDARY_v0_1`,
`linkage_basis = REGISTRY_DECLARED_IN_PROSE`. Both sides are `PENDING`.

Fifteen removal-side UCCs and three replacement-side UCCs (`910105`, `910106`,
`910107`), all held. The linkage is recorded anyway. It is a fact about the
rules that survives their being blocked, and losing it would make the two
blockers look independent when they are not.

### The invariant

> Within one replacement group and one population, no removal-side UCC may be
> retained while any UCC introduces the replacement.

That is the double-counting guard, and it is the *only* constraint between the
two sides. Nothing requires `replacement_amount == removed_for_replacement_amount`,
and nothing in C2 computes one from the other. The two are separate
measurements of two different concepts, and forcing them equal would be an
assumption disguised as an identity.

---

## 8. Null is not zero

> **numeric 0** = BLS or the estimator observed zero.
> **blank** = unavailable, suppressed, withheld from production, or undefined.

Under `SUPPRESSED`, `NOT_AVAILABLE` and `NOT_APPLICABLE` the amount column must
be blank. Under `OBSERVED` and `WITHHELD` it must not be. The validator
enforces both directions.

The basis contains **seven genuine observed zeros** — `230141` in All CU and
Q1, `250911` in Q4 and Q5, `270902` in Q3, `340908` in Q1, `690310` in Q5 — and
they survive as `0.0`, not as blanks. A zero-fill of the 176 suppressed cells
would be indistinguishable from these seven in any downstream sum.

### 8.1 The regression case: UCC 910106

`910106`, rental equivalence of a vacant home available for rent, carries both
encodings **in the same column**:

| Population | Amount | Status | RSE |
| --- | ---: | --- | ---: |
| `ALL_CU` | 665.47 | `WITHHELD` | 60.6% |
| `Q1` | *(blank)* | `NOT_AVAILABLE` | — |
| `Q2` | 9.81 | `WITHHELD` | 100.4% |
| `Q3` | 99.08 | `WITHHELD` | 181.2% |
| `Q4` | 120.81 | `WITHHELD` | 63.7% |
| `Q5` | 435.78 | `WITHHELD` | 75.1% |

Q1 is blank because no consumer unit in the bottom quintile reported the item —
there is nothing to estimate. The other five have numbers that exist and are
not admitted, because the estimator failed adjudication for this UCC.

Coerce the Q1 blank to zero and the ledger stops saying that a measurement is
missing. Coerce the other five to zero and it stops saying that a measurement
was made and rejected. Those are three different states and the row exists in
all six populations to keep them apart.

Note also that `910106` is `PUMD_NOT_BENCHMARKED` while its three siblings are
`PUMD_BENCHMARKED`, under the *same* estimator. **One thin cell does not
downgrade the estimator, and a benchmarked estimator does not rescue a thin
cell.**

---

## 9. Concordance absence is corroborating, not dispositive

Fifty-eight basis UCCs have no direct ELI mapping in the pinned 2024-vintage
concordance. Their dispositions:

| Disposition | UCCs |
| --- | ---: |
| `EXCLUDED` | 22 |
| `PENDING` | 19 |
| `OPEN` | 11 |
| `TRANSFORMED` | 6 |

Unmapped is plainly not a synonym for excluded. Where an unmapped UCC *is*
excluded, the exclusion comes from a rule of type `EXCLUDE` that is in force
and says so on its own grounds — residential property tax, mortgage interest
and charges, owner maintenance services, capital improvement, vehicle finance
charges — not from the absence of a crosswalk row.

Every one of the 132 excluded rows names a `CURRENT_EFFECTIVE` governing rule
with `effective_track_a_status = OUT_OF_SCOPE`. There is no path in the code
from "unmapped" to "excluded", and a test injects one to prove the validator
rejects it.

This preserves the correction made at the residual-shelter checkpoint: the
concordance is a crosswalk BLS publishes for a purpose of its own, and its
silence about a UCC is evidence about the crosswalk. A concept can receive CPI
weight through another production transformation without appearing there.

---

## 10. `normalization_state` is a classification and nothing else

The field exists so that C4 has somewhere to start. It computes nothing.

| State | Rows | |
| --- | ---: | --- |
| `ELIGIBLE` | 1,619 | In the basis under a rule in force |
| `EXCLUDED_FROM_BASIS` | 132 | Deliberately outside the basis |
| `BLOCKED_PENDING_ADJUDICATION` | 126 | A disposition is proposed and not in force |
| `BLOCKED_AMOUNT_UNAVAILABLE` | 98 | A disposition exists but the amount does not |
| `BLOCKED_UNRESOLVED_METHODOLOGY` | 66 | No disposition is proposed |
| `NOT_APPLICABLE` | 30 | No normalisation question arises |
| `BLOCKED_AMOUNT_NOT_ADMITTED` | 5 | The amount exists and is not admitted |

The last two blocked states are kept apart on purpose. `BLOCKED_AMOUNT_UNAVAILABLE`
is unblocked by a measurement; `BLOCKED_AMOUNT_NOT_ADMITTED` is unblocked by an
estimate good enough to admit. Collapsing them would lose the fact that the
number already exists.

`normalization_state` is derived from the disposition and the amount status.
It is not an input to anything. There is no `normalized_weight`,
`weight_share` or `denominator_share` field, and a test parses the module
sources with `ast` — not a text scan, so the prose above cannot satisfy it —
and requires no such identifier to be bound anywhere.

---

## 11. Determinism

Rebuilding from the same commit produces byte-identical artifacts. This is
checked three ways: two in-process builds are compared, the committed files are
compared against a fresh render, and the build script's `--check` mode is run
as a subprocess.

- Every list is sorted explicitly. Rows are ordered by UCC ascending as a
  string, then population in the fixed order `ALL_CU, Q1, Q2, Q3, Q4, Q5`.
  Nothing depends on dictionary insertion order or on filesystem iteration
  order.
- JSON is `indent=2, sort_keys=True`, one trailing newline.
- The CSV sets `lineterminator="\n"` explicitly. The `csv` module defaults to
  CRLF, which `.gitattributes` would normalise on the way in, so the bytes
  written and the bytes committed would differ.
- **No artifact carries a timestamp, host, user or absolute path.** A manifest
  that changes on every rebuild cannot detect a real change. Because it has
  none, a diff means an input moved.

---

## 12. What is tested, and how it is known not to be vacuous

85 tests, 12,832 subtests, in `tests/test_detailed_inflation_canonical_ledger.py`.

Structural guards are asserted to **fire on a deliberately broken input**
before they are asserted not to fire on the real one. A guard that has never
been seen to fire proves nothing. The mutation tests build a temporary copy of
the registry directory, rewrite it, and require the build to fail — which in
turn required fixing a real defect found while writing them: several loaders
accepted a `registry_dir` argument and then resolved files against the
repository root, so every mutation would have silently read the real registry
and passed.

The seven named injections:

| # | Injection | Result |
| --- | --- | --- |
| 1 | Re-enable the superseded rule in the governing registry | Build fails: a UCC is claimed twice |
| 2 | Assign two current rules to one UCC | Build fails: incompatible current ownership |
| 3 | Turn a `PENDING` rule's proposal into an effective exclusion | Validator rejects: *requires a rule in force* |
| 4 | Turn the null `910106` Q1 cell into zero | Validator rejects: *must be blank* |
| 4b | Coerce a suppressed cell to zero | Validator rejects, same guard |
| 5 | Retain a source amount while introducing its replacement | Validator rejects: *counted twice* |
| 6 | Exclude an unmapped UCC whose rule is `OPEN` | Validator rejects: *requires a rule in force* |
| 7 | Add a `normalized_weight` field | AST firewall scan flags it |

Injection 6 needed re-aiming during development. The first attempt targeted an
unmapped UCC governed by *no* rule; there are none, because every basis UCC is
claimed. The honest injection is to exclude on a rule that proposes nothing, so
that unmappedness is the only remaining ground.

Also asserted: all four checkpoint tags dereference to their pinned SHAs, the
lineage walk rejects a fork and a second root, no UCC resolves through the
superseded rule, every UCC has exactly six population rows, no row has two
non-blank amount columns, no accounting amount differs from its source amount,
no module imports `dmi_calculator`, and every path literal in the three modules
lives under `data/research/`, `registry/research/` or `docs/research/`.

---

## 13. Attribution

**To BLS.** The Consumer Expenditure Survey and its published aggregates; the
CE Public Use Microdata; the integrated CE stub structure; the CE→CPI UCC/ELI
concordance; the CPI entry-level item definitions; all suppression and
publication decisions in the source data; and the CPI methodology described in
the *Handbook of Methods*. Every amount in the `LABSTAT_PUBLISHED` rows is a
BLS figure, reproduced without adjustment.

**To DMI research.** The taxonomy and node identifiers; the scope-rule
vocabulary and the rule registry; the evidence grading scheme and the
`PRIMARY`/`CORROBORATING` role distinction; the registry lineage structure and
the derivation of a governing head from predecessor declarations; the six
canonical rule states; the accounting dispositions and the eight explicit
amount columns; the `normalization_state` classification; and every judgement
recorded in this document.

The PUMD-derived amounts (`910104`–`910107`) are DMI estimates produced by the
frozen LB01 estimator from BLS microdata. They are not BLS publications and are
labelled `PUMD_BENCHMARKED` or `PUMD_NOT_BENCHMARKED` accordingly.

---

## 14. What C1 + C2 deliberately do not do

No population-level reconciliation of amounts (C3). No normalization-readiness
adjudication or readiness thresholds (C4). No freezing of the complete
substrate (C5). No normalized weights, expenditure shares or denominators. No
redistribution of pending or open mass. No sensitivity bounds. No CPI price
acquisition. No inflation calculation. No Core DMI. No change to the Baseline,
to Slack-Plus, to production manifests, to workflows or to deployment outputs.
No reopening of shelter residual research.

The ledger sums to nothing, because nothing sums it. The summary artifact
counts rows and says so in a field of its own:

> Every number below counts rows. No amount is summed anywhere in C1 or C2.
> Population-level reconciliation of amounts is a later task, and a total
> published here would be read as its answer.
