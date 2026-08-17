# Detailed Inflation Substrate v0.1 — Milestone 2

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**Core DMI remains withdrawn and unimplemented.** This milestone computes no
inflation index, constructs no weights, normalizes nothing to one, acquires no
CPI price data, and produces no DMI release. Nothing here is imported by
`dmi_calculator`, by the Baseline or Slack-Plus specifications, or by any
release workflow.

**The owner-occupied shelter rule is not settled.** Four rules covering
$1,137,534M of expenditure — 16.6391% of the detailed basis — remain `PROPOSED`.
Their dispositions are recorded but **not in force**, and the expenditure is
held in a separate `pending_proposed` bucket rather than counted as excluded or
transformed. See §2 and §8 below.

---

## 1. What this milestone was for

[Milestone 1](DETAILED_INFLATION_SUBSTRATE.md) established that 19.4052% of
2024 All-Consumer-Unit expenditure in the Food, Alcoholic beverages, Housing
and Transportation domains — 58 UCCs, $1,326,642M — has no row in the pinned
BLS UCC→ELI concordance. Milestone 1
deliberately stopped there and marked all 58 `UNRESOLVED`, because deciding
what they mean requires scope judgement rather than more parsing.

Milestone 2 answers the follow-on question:

> Why is each of those 58 items unmapped, what does BLS's own published record
> say should happen to it, and can the expenditure be accounted for without
> either deleting it or inventing a mapping for it?

The result is a **scope resolution**, not a measure. It says where each item
belongs conceptually; it does not weight anything.

## 2. Headline results

**A proposed methodological disposition is not an effective Track-A
classification. Proposed shelter rules are carried in a separate pending bucket
until their prerequisites are satisfied.** The two questions — *does the
published record explain this item?* and *is that explanation in force?* — have
different answers here, and reporting only the first would overstate the
milestone.

**What the record explains.** Every exception now has a documented proposed
disposition except 11:

| | UCCs | All-CU $M | % of basis |
|---|---:|---:|---:|
| Milestone-1 exceptions | 58 | 1,326,642 | 19.4052% |
| → proposed `TRANSFORMED` | 21 | 133,423 | 1.9516% |
| → proposed `OUT_OF_SCOPE` | 26 | 1,182,268 | 17.2934% |
| → nothing proposed, still `UNRESOLVED` | 11 | 10,951 | **0.1602%** |

**What is actually in force.** Only the five `ACCEPTED` rules are applicable.
The four `PROPOSED` shelter rules argue for a disposition they cannot yet
apply, so their expenditure is neither transformed, excluded nor retained — it
sits in its own pending bucket:

| §19.1 bucket | UCCs | All-CU $M | % of basis |
|---|---:|---:|---:|
| `accepted_transformed` | 6 | 120,803 | 1.7670% |
| `accepted_out_of_scope` | 8 | 57,354 | 0.8389% |
| **`pending_proposed`** | **33** | **1,137,534** | **16.6391%** |
| `unresolved_open` | 11 | 10,951 | 0.1602% |
| *effective now* (first two rows) | 14 | 178,157 | 2.6060% |

So: **Milestone 2 reduces the expenditure share lacking any proposed
methodological disposition from 19.4052% to 0.1602%. However, 16.6391% of the
basis remains subject to proposed shelter rules that are not yet effective
pending PUMD validation, and only 2.6060% is classified by rules in force.**

The substantive finding stands — almost the entire Milestone-1 mapping gap is a
*concept* difference between CE outlays and CPI consumption rather than a data
defect, and the published BLS record is explicit enough to say which is which in
47 of 58 cases. What the corrected accounting adds is that most of that gap is
explained but not yet *settled*.

Each row therefore carries both claims. `proposed_track_a_status` is what the
governing rule argues for; `effective_track_a_status` is what the accounting
does. For the 33 shelter UCCs they differ, and `resolution_state` says why:

| `resolution_state` | Meaning | UCCs |
|---|---|---:|
| `EFFECTIVE` | An `ACCEPTED`, applicable rule is in force | 14 |
| `PENDING` | A disposition is argued but its prerequisite is unmet | 33 |
| `OPEN` | No disposition is proposed at all | 11 |

`PENDING` and `OPEN` are kept apart deliberately. Both read `UNRESOLVED` in
effect, but "blocked on a stated prerequisite" and "undecided" are different
facts, and collapsing them would either overstate the open gap or understate the
blocked one. `unresolved_ledger_v0_2.csv` lists the `OPEN` items only, since a
pending shelter UCC is not a research lead.

The accounting identity in spec §19.1 holds **exactly** — residual `0.000000` —
in all six populations, across all five buckets. See
`transformation_reconciliation.csv`.

### The ten scope rules

| Rule | Type | UCCs | All-CU $M | % basis | Evidence | Review | Track B |
|---|---|---:|---:|---:|---|---|---|
| `TR_TRIP_FOOD_ALCOHOL_v0_1` | REASSIGN | 3 | 90,717 | 1.3269% | STRONG | ACCEPTED | NOT_APPLICABLE |
| `OS_CPI_VEHICLE_FINANCE_CHARGES_v0_1` | EXCLUDE | 4 | 56,713 | 0.8296% | STRONG | ACCEPTED | NOT_APPLICABLE |
| `OS_CPI_MORTGAGE_INTEREST_AND_CHARGES_v0_1` | EXCLUDE | 8 | 504,695 | 7.3823% | STRONG | **PROPOSED** | RETAIN_CURRENT_PAYMENT |
| `OS_CPI_RESIDENTIAL_PROPERTY_TAX_v0_1` | EXCLUDE | 2 | 387,438 | 5.6672% | STRONG | **PROPOSED** | RETAIN_CURRENT_PAYMENT |
| `TR_VEHICLE_REGISTRATION_FEES_v0_1` | COMBINE | 2 | 28,734 | 0.4203% | STRONG | ACCEPTED | NOT_APPLICABLE |
| `TR_EV_CHARGING_v0_1` | REASSIGN | 1 | 1,352 | 0.0198% | MODERATE | ACCEPTED | NOT_APPLICABLE |
| `OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1` | EXCLUDE | 8 | 232,781 | 3.4050% | MODERATE | **PROPOSED** | RETAIN_CURRENT_PAYMENT |
| `RP_SECONDARY_RESIDENCE_OWNER_COST_v0_1` | REPLACE | 15 | 12,620 | 0.1846% | MODERATE | **PROPOSED** | RETAIN_CURRENT_PAYMENT |
| `OS_CPI_CAPITAL_IMPROVEMENT_v0_1` | EXCLUDE | 4 | 641 | 0.0094% | MODERATE | ACCEPTED | EXCLUDE_CAPITAL_ACQUISITION |
| `UNRESOLVED_v0_2` | UNRESOLVED | 11 | 10,951 | 0.1602% | WEAK | OPEN | UNRESOLVED |

The five `ACCEPTED` rules cover 178,157 ($M), 2.6060% of basis. The four
`PROPOSED` rules cover 1,137,534 ($M), 16.6391%, and are all shelter-coupled.

## 3. The structural finding: owner maintenance is weighted from renters

The largest analytical result is not in any single rule. Testing the 2024 CE
hierarchical grouping file against the pinned concordance shows:

- **100% of the rented-dwellings maintenance branch (`RNTDWELL`) is mapped**,
  except `230144`, `990920` and `790690`.
- On the owner side, a UCC is mapped **if and only if a renter counterpart
  exists**. The twelve mapped pairs are 240112/240111, 240122/240121,
  240212/240211, 240222/240221, 240312/240311, 240322/240321, 320612/320611,
  320625/320624, 320632/320631, 230142/230141, 230112/230150 and 220121/350110.
- The eight owner UCCs in `OS_CPI_OWNER_STRUCTURE_INVESTMENT_v0_1` are exactly
  those with **no** renter counterpart.

This operationalizes Casey (2010) Appendix B notes 3–5 from BLS's own data
rather than taking the notes on trust, and it shows the criterion is *not* the
owner/renter tenure split as such. It is recorded as
`structural_evidence.OWNER_RENTER_COUNTERPART_TEST` in the registry, together
with the one counter-instance the test produces (`340911`→`HP090`, an
"unsampled" residual ELI), which is surfaced rather than suppressed.

The mapping half of that block is re-derived from the pinned concordance by
`TestStructuralEvidence`, so the prose cannot drift away from the data, and the
test proves something stronger than the claim: each of the twelve counterpart
pairs maps not merely to *some* destination but to the *same* ELI. The *branch
membership* half — which UCCs sit under `RNTDWELL` and `OWNDWELL` — comes from
the CE hierarchical grouping file, which is not committed here, so that part is
recorded evidence rather than test-enforced.

Two corollaries:

**Capital improvement is the only concept unmapped on all three tenures** —
`990920` (renter), `990930` (owner), `990940` (vacation). Tenure therefore
cannot explain that exclusion; the concept does.

**The owned-vacation-home branch is excluded as a whole.** Every UCC under
`Shelter > Other lodging > Owned vacation homes` is unmapped while its
primary-residence analogue is largely mapped. That is consistent with Casey
note 2 (secondary homes priced by rental equivalence with a consumption
factor), so the rule is `REPLACE`, not `EXCLUDE`. The competing reading — that
these are excluded as real-estate investment — is recorded explicitly in the
registry, because the published record cannot distinguish the two.

## 4. Suppression is bounded, not assumed away (§16)

BLS suppresses some detailed quintile cells. 23 of the 58 exceptions carry at
least one suppressed cell; eight are suppressed in all six populations. None of
these are ever coerced to zero — they are written as empty cells in
`scope_resolution_2024.csv`, and the test
`test_suppressed_cells_are_blank_not_zero` enforces that.

The magnitude is bounded from BLS's own published parents rather than guessed:

```
upper_bound = max(0, published_parent − Σ published_children) + rounding_bound
```

Results:

| | per UCC | per rule |
|---|---:|---:|
| `NONE` | 35 | 6 |
| `IMMATERIAL` | 23 | 3 |
| `MATERIAL` | 0 | 1 |

The worst per-population bound is **0.0157% of basis**. One rule,
`OS_CPI_CAPITAL_IMPROVEMENT_v0_1`, is `MATERIAL`: up to 52.2% of its own
possible total is unobserved. Under §16 it is dispositioned
`AGGREGATE_TO_STABLE_LEVEL` — it is not blocked, because the exclusion decision
rests on the tenure evidence above rather than on the magnitudes, but any
future consumer must take it at the rule total, never at the individual UCC.

Two of the ten declared statuses in my first draft of the registry were wrong;
the computation caught both. `OS_CPI_CAPITAL_IMPROVEMENT_v0_1` was declared
`IMMATERIAL` and is in fact `MATERIAL`. `UNRESOLVED_v0_2` was declared
`MATERIAL`, conflating "we do not know the scope treatment" with "the data are
suppressed"; it is `IMMATERIAL` for suppression, and its real defect is
recorded by `review_status: OPEN`. The registry now declares and the code
verifies: `test_declared_suppression_status_is_reproduced` fails the build if
they ever diverge.

## 5. ELI→node semantic validation (§15)

Every concordance-reachable ELI was checked against BLS's *own* major
expenditure grouping, taken from Handbook of Methods Appendix 2 (pinned as
`registry/research/cpi_eli_descriptions_v0_1.tsv`, normalized from the BLS
workbook `cpi-eli-descriptions-hom-appendix2.xlsx`, source sha256
`40d13c0b…`).

| Result | Count |
|---|---:|
| CONSISTENT | 251 |
| CONSISTENT_BY_DESIGN | 15 |
| **DIVERGENT** | **0** |
| NO_BLS_DESCRIPTION | 28 |

Zero divergences. The 15 `CONSISTENT_BY_DESIGN` cases are where the 14-node
DMI taxonomy deliberately splits one of BLS's 8 major groups — for example
`MOTOR_FUEL` out of Transportation, so that a future Core-style
food-and-energy exclusion is expressible. The 28 undescribed ELIs are all
structurally explained by BLS's own title text: 26 are `*090` "Unsampled"
residuals and 2 are "Retained Earnings" constructs, none of which Appendix 2
documents by design. Unexplained gaps: **0**.

Pinning Appendix 2 surfaced one BLS publication inconsistency: the workbook
prints the 4-character stratum code `HA01` for "Rent of primary residence"
where the concordance and CPI item structure use the 5-character ELI `HA011`.
The row is retained under the corrected code so the shelter ELI is not silently
lost, with the published code preserved in `source_code_as_published` and the
correction documented in the provenance as a DMI correction, not a BLS-authored
change.

## 6. UCC provenance: `cx.item` is not the CPI's universe

Milestone 1 keyed its accounting basis on the published CE item file `cx.item`
and treated a UCC with no row there as a fatal error — `build_basis` raises. That
is right for a *published* basis and wrong as a general assumption, and the
distinction had never been written down. Testing the pinned concordance against
`cx.item` shows the two BLS universes only partly overlap:

| Class | Membership | UCCs |
|---|---|---:|
| `DIRECT_CONCORDANCE_UCC` | in `cx.item` **and** in the concordance | 490 |
| `PUBLISHED_CE_UCC` | in `cx.item` only | 508 |
| `CONCORDANCE_ONLY_UCC` | in the concordance only | **17** |
| union | | 1,015 |

The three classes partition the union exactly: every UCC has one class, none has
two, and the class is *derived* from set membership rather than assigned by hand.
The arithmetic closes on both sides — 490 + 508 = 998, the numeric item codes in
`cx.item`; 490 + 17 = 507, the concordance UCCs.

**Concordance-only UCC is a structural classification based solely on BLS
source-file membership. PUMD availability and CPI-adjustment semantics are
separate evidence claims.** The class was originally called
`CPI_ADJUSTED_PUMD_UCC`, which was an overclaim: membership is established by
set difference alone, and a set difference cannot show that a UCC is reachable
in the Public Use Microdata or that the CPI adjusts it. Those two properties are
now graded per UCC on their own scales, alongside the reason for
non-publication:

| Property | Scale | Asserted for |
|---|---|---|
| `publication_reason` | `PUBFLAG_1` / `UNDOCUMENTED` / `NOT_APPLICABLE` | `PUBFLAG_1` for `510115`; `UNDOCUMENTED` for the other 16 |
| `pumd_membership` | `VERIFIED` / `NOT_VERIFIED` | `VERIFIED` for `510115` only; `NOT_VERIFIED` for 16 |
| `cpi_adjustment_status` | `VERIFIED` / `INFERRED` / `UNKNOWN` | `INFERRED` for `910104`–`910107`; `UNKNOWN` for 13; `VERIFIED` for none |

`NOT_VERIFIED` and `UNKNOWN` are the defaults and mean *no evidence was
recorded*, not *the property is false*. Nothing is graded `VERIFIED` for CPI
adjustment because no BLS statement of a specific adjustment was located. The
four shelter codes are graded `INFERRED` and labelled `claim_type:
DMI_INFERENCE`: their BLS titles and their `HC011` destination describe an
imputed equivalence concept rather than a recorded outlay, which implies *some*
adjustment relative to reported expenditure, but that is a DMI reading of BLS
titles and not a BLS statement.

One tempting shortcut is explicitly rejected. All four shelter codes carry `CE
SOURCE = I`, but that column names the **collection instrument**, not the PUMD
data dictionary, so it is not evidence of microdata reachability. The only
committed PUMD observation is for `510115` (see §9), and even that is graded
`reproduced_by_test: false` with a stated caveat, because the citation is an
asserted research finding rather than a check this repository re-runs.

**The 17 are the finding.** A pipeline keyed on `cx.item` cannot see them and
will not error, so it under-counts the CPI-relevant universe silently. They are
not obscure: every one resolves to a live DMI computation node — `RECREATION` 8,
`SHELTER` 4, `TRANSPORT_COMMODITIES_EX_MOTOR_FUEL` 3, `TRANSPORT_SERVICES` 1,
`HOUSEHOLD_FURNISHINGS_OPERATIONS` 1 — so none is safely ignorable. Eight fall
outside the four Milestone-1 target domains; the other nine are *inside* them
and still never appeared as exceptions, precisely because they never enter a
`cx.item`-derived basis at all.

BLS publishes no annual LABSTAT aggregate for any of the 17, so an amount for
one of them could not come from `cx.data` in any case; PUMD microdata under a
validated weighting procedure is the only candidate source, which is a statement
about where one would have to look rather than a finding that the data are
there. `510115` is the clearest case: it is the `COMBINE` destination of
`TR_VEHICLE_REGISTRATION_FEES_v0_1`, and its absence from `cx.item` is exactly
why that rule reconstructs it from the two published components rather than
reading it. Only `510115` carries a documented reason for non-publication (CE
microdata `PUBFLAG=1`); the other 16 are marked `UNDOCUMENTED` rather than given
an invented explanation. The classification is structural and does not depend on
knowing why.

Three of the 17 are trade-in allowances (`450116`, `450216`, `600153`). A
trade-in offsets a gross purchase price rather than adding to outlay, and its
sign convention in CPI weighting is not established here, so the registry warns
that they must not be summed as ordinary positive expenditure.

**The shelter correspondence is derived, and it corroborates the amendment.**
The four rental-equivalence codes the concordance uses — `910104`–`910107` — are
all `CONCORDANCE_ONLY_UCC`. Their published counterparts `910050` and
`910101`–`910103` are all `PUBLISHED_CE_UCC`: published but unmapped. That
asymmetry is measured from the two files, not assumed, and it is why the
normative Track-A input is the concordance code and the published addenda are
validation counterparts only. The ordered concept-for-concept pairing between
the two sets is recorded as `claim_type: DMI_INFERENCE` with an explicit warning
that **BLS publishes no such crosswalk**, and a test asserts the label rather
than trusting the prose.

The `910103` anomaly is preserved rather than tidied: three published addenda
read "Estimated **monthly** rental value" while `910103` alone reads "Estimated
**annual** rental value of timeshare", all four at `display_level` 1 under
subcategory `TITLEOFI`. Summing them as published would add an annual figure to
three monthly ones. It is recorded `status: UNRESOLVED, blocking: false` —
unresolved because the published record does not explain it, non-blocking
because it is confined to the counterpart series and `910107` is the normative
input.

This classification **authorizes nothing**. It changes no Milestone-1 or
Milestone-2 result, adds no expenditure, and does not entitle any
`CONCORDANCE_ONLY_UCC` to enter a DMI weight; the four shelter codes stay gated
behind the PUMD benchmark validation described in §8, whose first step is
establishing whether they are in the microdata at all. `build_basis` still raises
on a `cx.series` UCC missing from `cx.item`, unchanged. What is new is that the
assumption is now named, pinned with counts, and re-derived on every run:
`verify_against_registry` fails if the counts drift or if the 17-code roster
changes, so a new concordance vintage surfaces as an error instead of quietly
reclassifying UCCs.

## 7. Track B: the payments concept (§7)

Track B asks which Housing UCCs would remain relevant under a
household-outlay concept of the kind BLS's Homeowner Cost Index research
explores. It is a **comparison only**. Spec §3.3 is explicit that its existence
does not authorize changing Baseline, and no index is computed from it.

| Treatment | UCCs |
|---|---:|
| RETAIN_CURRENT_PAYMENT | 33 |
| NOT_APPLICABLE | 11 |
| UNRESOLVED | 10 |
| EXCLUDE_CAPITAL_ACQUISITION | 4 |

**$1,137,534M — 16.6391% of the detailed basis — is expenditure that Track A
proposes to remove and Track B keeps.** That is the size of the concept gap
between a CPI-compatible substrate and a payments-based one, measured rather
than asserted. It is dominated by mortgage interest (7.38%) and residential
property tax (5.67%). The Track-A side of that gap is proposed rather than
effective — it is exactly the `pending_proposed` bucket of §2 — so the figure
measures a concept difference that has been identified, not one that has been
applied.

Capital acquisition is the one concept both tracks exclude, which is the §7
"current expense versus capital acquisition" distinction doing real work.

§7 also requires naming the price indexes a payments measure would eventually
need. The registry records these per rule, and the loader refuses to accept a
retaining rule that names none. The honest summary is that the two largest
components have **no published CPI series at all**: a mortgage interest cost
index and an effective residential property tax index would both have to be
constructed. Property management fees and ground rent have no identified price
source either.

## 8. What is deliberately not done

**The Track-A owner-occupied shelter rule is not finalized.** The four
shelter-coupled rules stay `PROPOSED` and `is_applicable` returns `False` for
all of them. The three shelter CSVs named in spec §17
(`shelter_cpi_track_2024.csv`, `shelter_payments_track_2024.csv`,
`shelter_concept_comparison_2024.csv`) are **not written**, because emitting a
placeholder would misrepresent an unfinished decision as a finished one.

The blocker is a prerequisite, not an oversight: the PUMD annual-weighting and
quintile procedure must first be built and validated against multiple published
2024 LB01 LABSTAT benchmarks before UCCs 910104–910107 can be aggregated. Those
validation results must be reported before the shelter rule is finalized. As §6
notes, PUMD membership for those four codes is itself `NOT_VERIFIED`, so the
first step is establishing whether the microdata carries them.

Consequently §19.2 replacement accounting reports the **removed** owner outlay
($12,620M All-CU) and marks the replacement `PENDING`. §19.2 does not expect
the two to be equal, so neither may be inferred from the other. That report is
now explicit that the removal has not actually happened: the rule is `PENDING`,
so the $12,620M is still counted in the §19.1 basis, in the `pending_proposed`
bucket. The field `removed_outlay_is_still_in_the_basis` states this, and
`build_resolution` raises if a `REPLACE` rule ever becomes effective while its
replacement amount is still uncomputed, which would otherwise report a removal
with no replacement.

**No weights are normalized** (§19.3) and no index is calculated (§3.2, §7).
`test_no_index_or_weights_are_produced` asserts this against the summary.

## 9. Known limitations

**11 UCCs remain unresolved** ($10,951M, 0.1602%). The largest is `340915`
Home security system service fees ($6,028M, 0.088%), where sibling `340911` and
five other codes map to `HP090` but BLS has never mapped `340915` in any of the
five concordance vintages examined. A monitored-alarm subscription is a
plausibly distinct concept, so the obvious candidate is recorded and **not
applied** (§5.3). These are recommended BLS queries, not defects to paper over.

**A Diary-versus-Interview explanation was tested and rejected.** The
hypothesis that `300900`/`340913` are unmapped because they are Diary codes
fails: Diary codes are widely mapped (190 Diary versus 434 Interview rows in
the concordance).

**`270906` is probably a BLS clerical omission.** Its owner twin `270907` maps,
and both water-softening twins map. It is left unresolved rather than
"corrected", because inventing a mapping is exactly what §5 forbids.

**One structural claim is not reproduced by a committed test.** The
`510115 = 520110 + 950024` identity underpinning the vehicle-registration
`COMBINE` rule was verified against 2024 CE Interview PUMD MTBI records
(4,785 of 4,785, 100%), but that microdata is not distributed with this
repository, so no test re-derives it. Only the concordance-side claim
(`510115`→`TF011`) is test-enforced. The registry marks that evidence block
`reproduced_by_test: false` with a stated reason, and
`test_unreproduced_claims_say_so` fails the build if any evidence block ever
claims reproduction it does not have. Reproducing the record-level identity is
outstanding work.

**Every evidence citation is resolved, not trusted.** An earlier draft of this
registry cited its validation in a test module that had never been written. All
ten rules and all three structural-evidence blocks pointed at it, so every claim
read as verified while none was checked — a worse failure than an honest blank,
because it is invisible. The citations now name real tests, the loader refuses a
rule whose `validation_test` module is absent, and
`test_every_rule_names_a_test_that_exists` parses the target module to confirm
the named class and method exist rather than merely that the file does. A
companion test fabricates each way a citation can be wrong to prove that guard
can still fail.

**Internet Archive lookups failed throughout** (HTTP 503), so the dates at
which BLS wording changed between concordance vintages could not be
established. This is a genuine unresolved gap in the provenance chain.

**Evidence grading is mine, not BLS's.** `STRONG`/`MODERATE`/`WEAK` are a DMI
scale defined in the registry preamble. The underlying documents are BLS's; the
grading of them is not.

## 10. How to run it

```bash
python scripts/resolve_detailed_inflation_2024.py \
    --series   /path/to/cx.series_2024_dmi_target.tsv \
    --data     /path/to/cx.data.1.AllData \
    --items    /path/to/cx.item \
    --aspects  /path/to/cx.aspect_2024_dmi_target.tsv
```

Exit code 1 if any rule's declared suppression status is not reproduced by the
data, or if any ELI is semantically divergent. `--dry-run` reports without
writing. The research firewall refuses any output path under `data/outputs/` or
`deploy/data/outputs/`.

Artifacts land in `data/research/detailed_inflation/milestone_2/`:

| File | Contents |
|---|---|
| `scope_resolution_2024.csv` | The §18 resolution, one row per exception; 20 columns, carrying proposed and effective status separately |
| `transformation_reconciliation.csv` | §19.1 identity per population, over the five buckets |
| `unresolved_ledger_v0_2.csv` | The 11 `OPEN` items, with candidates marked not-applied. Pending shelter UCCs are deliberately absent |
| `eli_node_semantic_validation.csv` | §15, one row per concordance-reachable ELI |
| `ucc_provenance_classes_2024.csv` | §6, one row per UCC in either BLS universe (1,015), with the three evidence claims beside the class |
| `scope_resolution_summary.json` | Machine-readable summary of everything above |

The Milestone-1 artifacts under `audit_2024/` are **unchanged** and remain the
historical record (§18).

## 11. Code map

| Path | Role |
|---|---|
| `registry/research/ce_cpi_scope_rules_v0_1.json` | The 10 scope rules, sources, structural evidence, Track B |
| `registry/research/cpi_eli_descriptions_v0_1.tsv` | Pinned BLS Appendix 2 ELI titles and major groups |
| `registry/research/ucc_provenance_classes_v0_1.json` | §6 class definitions, pinned counts, the 17-code roster, the shelter correspondence |
| `dmi_research/detailed_inflation/scope_rules.py` | Registry loader; enforces §5 and §13 invariants |
| `dmi_research/detailed_inflation/semantics.py` | §15 ELI→node semantic validation |
| `dmi_research/detailed_inflation/provenance.py` | §6 UCC provenance classification and registry agreement check |
| `dmi_research/detailed_inflation/resolution.py` | §16 suppression, §18 output, §19 reconciliation |
| `scripts/resolve_detailed_inflation_2024.py` | CLI |
| `tests/test_detailed_inflation_milestone_2.py` | 112 tests, including negative tests that mutate the registry |

## 12. Corrections to this milestone's own claims

Two defects were found in the first cut of Milestone 2. Both were cases where
the prose was appropriately cautious but the data model was not, so a machine
consumer reading the artifacts would have drawn a stronger conclusion than the
evidence supports. Both are recorded here rather than quietly fixed.

**A proposed disposition was recorded as an effective one.** `build_resolution`
wrote each rule's `final_status` into a single `m2_track_a_status` column
regardless of its `review_status`. The four `PROPOSED` shelter rules therefore
appeared as accepted exclusions and transformations, and the §19.1 reconciliation
counted $1,137,534M — 16.6391% of the basis — as excluded or transformed when no
rule in force said so. The prose in §8 correctly said the shelter rule was
unfinished; the CSV and the summary JSON did not. The column is now split into
`proposed_track_a_status`, `effective_track_a_status`, `review_status` and
`resolution_state`, the reconciliation gained a `pending_proposed` bucket, and
the headline reports the effective share (2.6060%) alongside the explained one.
The old column name is gone rather than aliased, since leaving it in place would
let existing consumers keep making the same misreading.

**A structural class asserted two unverified properties in its name.** The third
provenance class was called `CPI_ADJUSTED_PUMD_UCC`. Membership was derived by
set difference — in the concordance, absent from `cx.item` — which shows neither
PUMD availability nor CPI adjustment. It is renamed `CONCORDANCE_ONLY_UCC`,
which is what the derivation shows, and the two asserted properties are split
into separately graded evidence fields as described in §6. The 490/508/17
partition is unchanged, because the classification logic was never wrong; only
its name was.

Neither correction changes a single expenditure figure, a mapping, a rule or a
count. What changed is which claims the artifacts make. The regression tests
added with the fixes are written to fail on the original behaviour: a mutation
test flips one `ACCEPTED` exclusion to `PROPOSED` and requires its expenditure to
move out of the accepted bucket, and an AST check parses `resolution.py` to prove
no code path turns `final_status` into an effective status without consulting the
review state.

## 13. Attribution

Source data and documents are published by the U.S. Bureau of Labor Statistics:
Consumer Expenditure Surveys (LABSTAT `cx.*`, hierarchical grouping files),
Consumer Price Index (Handbook of Methods including Appendix 2, the motor fuel
factsheet, the CPI item structure), and the CE→CPI UCC→ELI concordance. Casey
(2010) is a BLS-published working paper.

The 14-node computation taxonomy, the mapping of BLS major groups to DMI nodes,
the evidence-strength scale, the scope rules, the Track-B classification and
the suppression thresholds are **DMI research constructs, not BLS products**.
Any error in them is mine.
