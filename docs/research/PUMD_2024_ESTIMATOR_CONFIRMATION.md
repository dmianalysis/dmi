# Out-of-Sample Confirmation of the 2024 PUMD Estimator

**`confirmation_status = PASS`**

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**A PASS here is a validation result, not an authorization.** It is evidence that
the estimator generalises beyond the fifteen UCCs it was built against. It does
not upgrade `pumd_quantitative_usability` for 910104–910107, which remains
`NOT_ESTABLISHED`.

---

## 1. Why this run exists

The Phase-B benchmark passed. That result is preserved, unmodified, at the
annotated tag `dmi-detailed-inflation-v0.1-pumd-benchmark-2024`
(`95111fd675f2d0287e5cc89398411e3322ad65a3`).

It has a weakness, and the weakness is stated in its own write-up. The roster
that passed was not the roster the exercise started with. Two defects in the
selection rule were found — the v0.1 rule tested the survey-source code in the
*Interview* hierarchical grouping file, where it is trivially `I` for every row,
rather than the *Integrated* file that actually determines which survey supplies
a published LB01 value — and repairing them shrank the roster from eighteen UCCs
to fifteen. No tolerance moved during the repair, and the failed v0.1 result was
kept on disk rather than deleted. But a roster that was present in the room while
a rule was being fixed cannot, on its own, establish that the estimator
generalises. It can only establish that the estimator and the roster ended up
consistent with each other.

The question this run asks is therefore narrow and different:

> Does the estimator frozen at `95111fd` still reproduce published 2024 LB01
> values when applied to eligible UCCs it has never been run against?

Answering it before pointing the estimator at four unpublished shelter UCCs is
the point. If the estimator only worked on the fifteen UCCs that survived its own
development, any shelter number it produced would be worthless.

---

## 2. What was run, and what was not allowed to change

The estimator was not re-implemented. `dmi_research/detailed_inflation/pumd_confirmation.py`
contributes a roster and a set of diagnostics. Every estimate comes from the
frozen `pumd_benchmark.run_benchmark`, and every verdict comes from the frozen
`pumd_benchmark.summarize`. The confirmation module contains no annualization
logic, no `MO_SCOPE` treatment, no weight variable, no quintile boundaries, no
BRR replication and no small-value branch, so it cannot change any of them.

The acceptance rule was not restated. `confirmation_spec` is one line:

```python
return dataclasses.replace(frozen, roster_hash=roster_hash(roster))
```

`summarize` refuses any roster whose content hash differs from the one its spec
pins — that guard is what stops a development roster drifting past a frozen rule,
and a confirmation with a different roster has to get past it. Changing the pinned
hash and nothing else is the way to do that without touching a threshold. No
threshold is retyped, so no threshold can be mistyped. A test asserts equality
field by field against the frozen v0.2 spec, and a second test fails if a
threshold is ever added to `BenchmarkSpec` without being added to the
enumeration, so the check cannot fall silently out of date.

The ten thresholds are the same objects that judged the development run:

| Criterion | Threshold | Unchanged since |
| --- | ---: | --- |
| `population_tolerance_pct` | 0.5 | v0.1 |
| `quintile_population_tolerance_pct` | 2.5 | v0.1 |
| `median_abs_pct_error_max` | 5.0 | v0.1 |
| `p75_abs_pct_error_max` | 8.0 | v0.1 |
| `p90_abs_pct_error_max` | 15.0 | v0.1 |
| `per_ucc_abs_pct_error_max` | 10.0 | v0.1 |
| `per_ucc_pass_fraction_min` | 0.80 | v0.1 |
| `mean_signed_pct_error_abs_max` | 3.0 | v0.1 |
| `small_value_absolute_floor` | 10.0 | v0.1 |
| `small_value_abs_diff_max` | 2.0 | v0.1 |

---

## 3. The confirmation set, and why it involved no judgement

The set is **every remaining eligible UCC**: 111 UCCs, 666 UCC × population cells.

That is the choice that leaves least room for the set to have been shaped by
anything. There is no sampling rule, no holdout draw and no stratification,
because taking the entire remainder means there is no step at which a UCC could
have been dropped for reproducing badly. The frozen development rule kept one
median UCC per (node, stratum) cell and discarded nodes that did not span all
three magnitude strata; neither device is applied here, since both exist to build
a small balanced roster and this roster is not small. A test confirms that a UCC
in a node spanning only one stratum — excluded from the development roster by
construction — is nevertheless included in the confirmation.

Eligibility is the frozen v0.2 rule, reused without modification. The complete
1,015-UCC candidate universe is written to
`data/research/detailed_inflation/pumd_confirmation_2024/candidate_universe.csv`
with a reason for every UCC that did not make it. Reasons are tested in a fixed
order and each UCC is recorded under the first that applies, so the tally
partitions the universe rather than double-counting it:

| Reason | Count |
| --- | ---: |
| `NOT_DIRECT_CONCORDANCE_UCC` | 521 |
| `CE_SOURCE_NOT_INTERVIEW` | 181 |
| `INCOMPLETE_LB01_PUBLICATION` | 130 |
| `BLANK_PUBLISHED_MEAN` | 39 |
| `IN_DEVELOPMENT_ROSTER` | 15 |
| `INTERVIEW_STUB_SECTION_NOT_EXPEND` | 6 |
| `MILESTONE_2_SHELTER_UCC` | 4 |
| `ABSENT_FROM_INTERVIEW_STUB` | 4 |
| `ABSENT_FROM_INTEGRATED_STUB` | 2 |
| `INTEGRATED_STUB_SURVEY_NOT_INTERVIEW` | 2 |
| `MILESTONE_1_EXCEPTION` | 0 |
| `INTEGRATED_STUB_SECTION_NOT_EXPEND` | 0 |
| `UNRESOLVED_ANNUALIZATION_TRANSFORMATION` | 0 |
| **Excluded** | **904** |
| **Included** | **111** |
| **Total** | **1,015** |

Two counts read oddly and both are artefacts of the ordering rather than of the
rule, so they are worth stating plainly. `MILESTONE_1_EXCEPTION` counts zero not
because the test was skipped but because all 58 Milestone-1 exception UCCs are
already excluded by the earlier Milestone-2 classification test; a test asserts
that all 58 are present in the ledger and all 58 are excluded.
`INTEGRATED_STUB_SURVEY_NOT_INTERVIEW` counts only 2 for the same reason — the
Milestone-2 `ce_source` test catches most Diary-sourced UCCs first — and is not a
restatement of the 27 UCCs the v0.2 correction removed.

One exclusion is a confirmation-only addition rather than part of the frozen
rule. A UCC whose hierarchical-grouping annualization factor is not 1 needs a
multiplication the Phase-B benchmark never exercised, because every development
UCC carried a factor of 1. Rather than assume the untested path is sound, such a
UCC is held out and the holding-out is recorded. In 2024 this excludes nothing,
and the ledger says so; a synthetic test with a factor-4 UCC proves the branch is
live.

The frozen set spans 10 DMI nodes and two domains, published All-CU means from
$2 to $5,450, and 37 UCCs in each magnitude stratum. Its content hash is
`3bc3200eb781054f6902ff69966ffba0cd8052331d7b32e87b0056c531125577`.

### The freeze is provable, not asserted

`scripts/confirm_pumd_2024.py` has two subcommands and they are separate on
purpose. `freeze` reads no microdata at all — it builds the universe and the
roster from published artifacts and writes
`registry/research/pumd_lb01_confirmation_spec_v0_1.json`. `run` refuses to start
unless that specification is **already in git history**, and then refuses to
continue unless four things hold: the roster it rebuilds hashes to the pinned
value, the universe ledger hashes to the pinned value, the frozen benchmark spec
file is unedited, and `pumd.py` and `pumd_benchmark.py` still match the SHA-256
digests recorded at freeze time.

The specification was committed as `d334eb8`, before any comparison was computed.
Adjusting the set after seeing an error would appear both as a hash mismatch at
runtime and as a specification edited after the fact in `git log`.

---

## 4. Result

`confirmation_status = PASS`. `failed_criteria = []`.

| Metric | Development (15 UCCs) | Confirmation (111 UCCs) | Threshold | Margin |
| --- | ---: | ---: | ---: | ---: |
| UCCs | 15 | 111 | — | — |
| Comparisons | 90 | 666 | — | — |
| Cell pass fraction | 0.9667 | **0.9489** | ≥ 0.80 | +0.149 |
| Median abs % error | 1.091 | **1.317** | ≤ 5.0 | +3.68 |
| p75 abs % error | 2.311 | **3.491** | ≤ 8.0 | +4.51 |
| p90 abs % error | 4.087 | **7.955** | ≤ 15.0 | +7.05 |
| Mean signed % error | −0.298 | **−0.533** | ≤ 3.0 | +2.47 |
| Max abs % error | 13.36 | 40.10 | not a criterion | — |
| All-CU population error | +0.00004 | **+0.00004** | ≤ 0.5 | +0.50 |
| Worst quintile population error | +1.267 | **+1.267** (Q5) | ≤ 2.5 | +1.23 |

The last two rows are identical between the two runs and are not independent
evidence. The population comparison is computed from the FMLI universe alone, so
it does not depend on which UCCs are in the roster; the confirmation reproduces
it byte-for-byte because it is the same calculation on the same file. It is
included because the frozen acceptance rule reads it, not because it says
anything new.

Errors are larger on the confirmation set than on the development set, on every
percentile. That is the expected direction and it is worth saying so rather than
presenting the PASS as if nothing degraded: the development roster was fifteen
median-of-cell UCCs, and the confirmation is the whole remaining tail including
every small and awkward item. The p90 nearly doubled. It is still half its
threshold.

Cells judged on absolute difference are reported separately, because the frozen
rule excludes them from the percentage distribution and a summary quoting only
percentiles would be silent about a third of the run:

| Small-value cells (published mean < $10) | |
| --- | ---: |
| Count | 192 of 666 |
| Passing | 190 |
| Failing | 2 |
| Median absolute difference | $0.25 |
| Max absolute difference | $4.92 |

---

## 5. The three things that make this more than a threshold comparison

### Every All-CU cell passed

All 111 All-CU comparisons pass. Median absolute error 0.54%, p90 2.83%, worst
8.05%, and the largest absolute miss anywhere in the All-CU column is **$12.78**
in a survey whose largest single UCC is $5,450 a year.

Every one of the 34 failing cells is a quintile cell. That matters for what the
failures mean: a quintile cell is roughly a fifth of the sample, so it carries
roughly the sampling variance one would expect from a fifth of the sample, and
the All-CU column is where a methodological defect in annualization, weighting or
scope would show up undiluted.

### No UCC is systematically broken

The 34 failures are spread over 23 distinct UCCs. Twelve UCCs fail one cell each,
eleven fail two, and **no UCC fails three or more**. Nothing in the set behaves
like an item the estimator cannot handle; the failures look like the tail of a
noise distribution, not like a category of concept that is being mis-estimated.

Fail rates by node are consistent with that reading. The largest node,
`HOUSEHOLD_FURNISHINGS_OPERATIONS`, fails 21 of 336 cells (6.2%) against an
overall 5.1% — slightly worse, not categorically different. `MEDICAL_CARE` shows
2 of 6, which looks alarming until one notices that is a single UCC.

### Every failure is inside the sampling noise

All 34 failing cells fall within **two** BRR standard errors of the published
value, and 28 of the 34 within one. The twelve worst percentage errors in the
whole run — including the worst, 240111 Q2 at −40.1% on a published mean of $11 —
are all within 1.5 standard errors.

This is the check that distinguishes "the estimator is wrong" from "the cell is
small". A systematic methodological error would produce failures that are large
*relative to their own standard error*, and none of these are.

Independently of the means, the BRR machinery reproduces the RSE that BLS
publishes and computes separately:

| BRR RSE vs published LB01 RSE | |
| --- | ---: |
| Cells compared | 666 |
| Median gap | **+0.003 pp** |
| Within 5 pp | 97.6% |
| Range | −10.3 pp to +17.3 pp |

A median gap of three thousandths of a percentage point across 666 cells is
evidence that the replicate weights and the replication formula are the BLS ones,
not merely that the point estimates happen to land in the right place.

---

## 6. What this says about shelter, and what it does not

Five UCCs in the confirmation set sit in the `SHELTER` DMI node. They were not
chosen for that; they are simply what the eligibility rule returned. Their All-CU
reproduction:

| UCC | Title | Published | PUMD | Error | Failing cells |
| --- | --- | ---: | ---: | ---: | ---: |
| 210110 | Rent | $5,450 | $5,462.8 | **+0.23%** | 0 of 6 |
| 210210 | Lodging on out-of-town trips | $906 | $906.3 | **+0.03%** | 0 of 6 |
| 220121 | Homeowners insurance | $737 | $736.8 | **−0.03%** | 0 of 6 |
| 350110 | Tenant's insurance | $40 | $39.8 | −0.59% | 0 of 6 |
| 210310 | Housing while attending school | $160 | $164.3 | +2.68% | 1 of 6 |

Rent is the largest single UCC in the entire Interview survey and it reproduces
to a quarter of a percent. This is the strongest corroboration available short of
estimating 910104–910107 themselves: the estimator handles published shelter
concepts, drawn from the same survey and the same files, at high precision.

**It is not the same thing as establishing that 910104–910107 can be estimated.**
Those four UCCs are `CONCORDANCE_ONLY_UCC`; they have no published LB01 value, so
there is nothing to compare a PUMD estimate against, and no confirmation run can
supply one. What this section establishes is narrower and should be read
narrowly: the estimator is not defective *on shelter concepts*, so a failure to
estimate 910104–910107 would not be attributable to the estimator. Whether those
estimates are usable is a separate question about record counts, cell thickness
and disclosure treatment, adjudicated per UCC elsewhere.

---

## 7. What this run does not establish

- **It does not authorise anything.** `pumd_quantitative_usability` for
  910104–910107 is untouched and remains `NOT_ESTABLISHED`. The four UCCs cannot
  enter a benchmark roster by construction — `RosterEntry.__post_init__` raises —
  and a test confirms no amount was produced for them here.
- **It does not validate the Diary survey.** 181 UCCs were excluded as not
  Interview-sourced. Nothing here says anything about them.
- **It is not independent of the development run in every respect.** It uses the
  same archive, the same five quarters, the same published quintile lower limits
  and the same LABSTAT extraction. It is out-of-sample in the UCCs, not in the
  data source. A defect in the archive handling or the quintile boundaries would
  be invisible to both runs equally.
- **The quintile boundary reconstruction remains diagnostic only.** Consumer
  units are assigned by BLS's published lower limits, not by a reconstructed
  weighted rank. That was true in Phase B and is unchanged.
- **It cannot rule out a shared error in the eligibility rule.** Both runs define
  eligibility the same way. If the v0.2 rule is still wrong in some way neither
  run can see, both are wrong together.

---

## 8. Reproducing

```bash
export DMI_PUMD_2024_INTERVIEW_DIR=~/dev/dmi-data/pumd/2024/interview/extracted
python3 scripts/confirm_pumd_2024.py run \
  --stub-dir ~/dev/dmi-data/pumd/2024/docs/stubs/stubs
```

The run is deterministic. Re-running it rewrites all four artifacts
byte-for-byte identically, verified by SHA-256 before and after.

`freeze` will refuse to overwrite an existing specification, and `run` will
refuse to proceed against a specification that is absent, uncommitted, or that
pins a hash the rebuilt roster does not match.

---

## 9. Test evidence

`tests/test_detailed_inflation_confirmation.py`: 52 tests, 506 subtests. Full
repository suite: 549 passed, 8 skipped, 1,317 subtests.

The tests that would fail if a discipline were broken, rather than merely
recording that it was not:

| Discipline | How it is tested |
| --- | --- |
| No threshold changed | Field-by-field equality with the frozen v0.2 spec; a mutation loosening one threshold must show up as exactly one differing field |
| The enumeration cannot fall behind | Adding a field to `BenchmarkSpec` without adding it to `THRESHOLD_FIELDS` fails a test |
| Confirmation ∩ development = ∅ | Asserted on the synthetic fixture, the frozen spec and the written results |
| The set is the whole remainder | Anything eligible but in neither roster must carry a named confirmation-only reason; an unexplained drop fails |
| The ledger has not drifted from the frozen rule | The ledger's eligible set must equal `eligible_candidates`; two mutation tests drop an eligible UCC and admit an ineligible one, and both must raise |
| No failing UCC was removed | The pass fraction must be recomputable from the full result file, and the test asserts the run contains failures so it cannot pass vacuously |
| Metrics are not re-derived favourably | Median, p90 and max are recomputed from the CSV and must match the summary |
| Phase B is preserved | The Phase-B summary still reports PASS with 90 cells, the superseded v0.1 FAIL still reports FAIL with 108, the freeze tag still resolves to `95111fd`, and the Phase-B roster still hashes to what its spec pins |
| Firewall | Nothing written under `data/outputs` or `deploy/data/outputs`; no operational import in either new file |

---

## 10. Provenance

| Item | Value |
| --- | --- |
| Frozen estimator | `95111fd675f2d0287e5cc89398411e3322ad65a3` |
| Freeze tag | `dmi-detailed-inflation-v0.1-pumd-benchmark-2024` |
| Confirmation spec frozen at | `d334eb8` |
| Confirmation spec version | v0.1 |
| Confirmation roster version | v0.1 |
| Eligibility rule version | v0.2 (`pumd_benchmark.ROSTER_VERSION`) |
| Acceptance rule version | v0.2, inherited unchanged |
| Confirmation roster hash | `3bc3200eb781054f6902ff69966ffba0cd8052331d7b32e87b0056c531125577` |
| Development roster hash | `5d01d306772bedeb8025723f8f4684133b7200e689d77fadfd29a1c3d3d88a33` |
| PUMD archive | `INTRVW24`, SHA-256 `421ec90c2b8469c10f91eac27988f65f5d09fcfa9944e5069bb00b5460677f26` |
| Files used | `fmli241x`, `fmli242`, `fmli243`, `fmli244`, `fmli251`; `mtbi241x`, `mtbi242`, `mtbi243`, `mtbi244`, `mtbi251` |
| Join key | `NEWID` |
| Weight variable | `FINLWT21`; replicates `WTREP01`–`WTREP44` |
| Estimand | `MEAN_ANNUAL_EXPENDITURE_PER_CONSUMER_UNIT`, US dollars per consumer unit per year |
| Income concept | `FINCBTXM` |
| Quintile rule | BLS published 2024 lower limits: 29,932 / 57,452 / 94,511 / 155,925 |
| FMLI records read | 23,176 |
| MTBI records in scope | 436,048 |

## 11. Artifacts

| Path | Contents |
| --- | --- |
| `registry/research/pumd_lb01_confirmation_spec_v0_1.json` | The frozen specification: eligibility rule, universe counts, exclusion tally, full 111-UCC roster, roster hash, estimator and archive digests |
| `data/research/detailed_inflation/pumd_confirmation_2024/candidate_universe.csv` | All 1,015 UCCs with status and first-applicable exclusion reason |
| `data/research/detailed_inflation/pumd_confirmation_2024/confirmation_results.csv` | All 666 cells, including every failure |
| `data/research/detailed_inflation/pumd_confirmation_2024/confirmation_summary.json` | The verdict and every reported metric |
| `data/research/detailed_inflation/pumd_confirmation_2024/population_validation.csv` | Weighted CU counts and mean incomes against published targets |
