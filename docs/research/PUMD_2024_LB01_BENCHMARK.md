# 2024 CE Interview PUMD → LB01 Benchmark

**`benchmark_status = PASS`**

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**A PASS here is a validation result, not an authorization.** It does not
license any DMI figure to be sourced from PUMD, it does not create a weight, a
price, or an index, and it does not change the Milestone-2 classification of
any UCC. In particular UCCs 910104–910107 remain
`pumd_membership = VERIFIED` / `pumd_quantitative_usability = NOT_ESTABLISHED`,
and no annual or quintile expenditure estimate was calculated, printed, saved
or reported for any of them by this work.

**Core DMI remains withdrawn and unimplemented.** Nothing here is imported by
`dmi_calculator`, by the Baseline or Slack-Plus specifications, or by any
release workflow. Every artifact is written under
`data/research/detailed_inflation/`.

---

## 1. The question

Milestone 2 resolved *what* the unmapped 2024 CE expenditure means. It did so
entirely from published aggregates. The obvious next question is whether the
underlying microdata is usable at all:

> Can the public 2024 CE Interview PUMD be transformed into annual
> All-Consumer-Unit and income-quintile means that reproduce the published
> 2024 LB01 / Table 1101 figures closely enough for PUMD to serve as a
> defensible source?

This is a **gate**, not a licence. The point of asking it before using PUMD for
anything is that a negative answer is cheap now and expensive later. A failure
would have been recorded as a failure.

## 2. Verdict

`PASS`. Every criterion in the frozen acceptance rule was met.

| Criterion | Threshold | Observed | |
|---|---:|---:|:--|
| All-CU population agreement | ≤ 0.500% | 0.00004% | PASS |
| Per-quintile population agreement | ≤ 2.500% | 1.267% (Q5) | PASS |
| Median absolute percentage error | ≤ 5.00% | 1.09% | PASS |
| p75 absolute percentage error | ≤ 8.00% | 2.31% | PASS |
| p90 absolute percentage error | ≤ 15.00% | 4.09% | PASS |
| Per-cell pass fraction | ≥ 0.800 | 0.967 | PASS |
| Mean signed percentage error | \|·\| ≤ 3.00% | −0.298% | PASS |
| Small-value absolute difference | ≤ $2.00 | $1.00 (max) | PASS |

`failed_criteria: []`. 90 comparisons — 15 UCCs × 6 populations — of which 87
pass at the cell level.

The dispersion is the interesting part: the median comparison is off by about
one percent, and the ninetieth percentile is off by four. That is far inside
what the documented sources of PUMD-to-publication divergence would permit, and
it holds across quintiles rather than only in aggregate.

## 3. Method, as established from primary sources

Every element below was read out of a BLS document or out of BLS's own PUMD
sample program before any comparison was run. None of it was tuned. Full
citations, retrieval timestamps and SHA-256 digests are in
[`registry/research/pumd_2024_interview_source_v0_1.json`](../../registry/research/pumd_2024_interview_source_v0_1.json).

| Element | Value | Established from |
|---|---|---|
| Calendar year | 2024 | — |
| FMLI files | `fmli241x`, `fmli242`, `fmli243`, `fmli244`, `fmli251` | Getting Started Guide §"five quarters"; sample program `SET` statement |
| MTBI files | `mtbi241x`, `mtbi242`, `mtbi243`, `mtbi244`, `mtbi251` | same |
| Join key | `NEWID` | sample program `MERGE ... BY NEWID` |
| Join kind | inner join for the numerator; the **full** FMLI file is the denominator | `IF INEXP AND INFAM` against an unfiltered `FMLY` |
| Final weight | `FINLWT21` | Getting Started Guide |
| Replicate weights | `WTREP01`–`WTREP44` | Getting Started Guide (BRR) |
| `QNUM` | 4 | Getting Started Guide |
| `MO_SCOPE` | first quarter `QINTRVMO − 1`; fifth quarter `4 − QINTRVMO`; otherwise 3 | sample program |
| Population weight | `FINLWT21 × MO_SCOPE / 12` | sample program `REPS_B(i)` |
| Expenditure weight | `FINLWT21`, **not** `MO_SCOPE`-adjusted | sample program `RCOST(i) = REPS_A(i) * COST` |
| Calendar-year filter | `REF_YR == 2024` | sample program; reference *month* is not used |
| Annualization | hierarchical grouping column 6, per UCC, 1 or 4 | PUMD documentation page |
| Income concept | `FINCBTXM` | the only income-before-taxes variable the BLS sample program uses to form income groups |
| Quintile rule | assignment by the lower limits **BLS publishes** in Table 1101 | Table 1101, row "Lower limit" |
| Standard error | `sqrt((1/44) · Σ_r (mean_r − mean)²)` | sample program |
| Estimand | mean annual expenditure per consumer unit | LABSTAT LB01 carries only process code `M` |

Two of these deserve emphasis because they are the kind of thing a plausible
but wrong implementation gets backwards.

**The weighting asymmetry is real and is BLS's.** The denominator population is
`MO_SCOPE`-adjusted; the expenditure numerator uses the raw `FINLWT21`. This
looks like an inconsistency and is not: it is exactly what
`CE-Interview-Mean-and-SE.sas` does. A January first-quarter interview
therefore contributes zero to the population and its expenditures still enter
the numerator.

This was checked rather than assumed. Applying `MO_SCOPE` to the numerator as
well — the symmetric alternative that looks more principled — moves the median
All-CU absolute error across the fifteen roster UCCs from **1.01% to 7.67%**
and turns every one of the fifteen errors negative, which is the unmistakable
signature of a systematic under-weighting. The asymmetric rule is not a
convenience; it is the one that reproduces the published table.

**The quintile boundaries are not reconstructed.** BLS publishes the lower
limits but not the algorithm that produced them, and the published quintile CU
counts are not exactly equal (27,139 / 27,186 / 26,959 / 27,205 / 27,272
thousand against an equal split of about 27,152), so whole CUs are being
assigned to one side of a boundary by a rule that is not public. Rather than
invent that rule, the benchmark assigns using the limits BLS itself publishes.
A weighted-rank reconstruction of the same limits is computed and reported as a
**diagnostic only**; `used_for_assignment = published` on every row of
`quintile_reconstruction.csv`.

The reconstruction is close, and is worth recording precisely because it is not
exact:

| Boundary | Published | Reconstructed | Difference |
|---|---:|---:|---:|
| Q2 lower limit | 29,932 | 30,000 | +0.227% |
| Q3 lower limit | 57,452 | 57,500 | +0.084% |
| Q4 lower limit | 94,511 | 95,000 | +0.517% |
| Q5 lower limit | 155,925 | 157,204 | +0.820% |

Three of the four reconstructed limits land on round dollar figures. That is
what a weighted-rank boundary does when reported incomes pile up at round
values: the boundary falls inside a mass point rather than between two distinct
incomes, which is another reason the exact BLS rule cannot be inferred from the
limits it produces. The consistent positive sign is what the CE FAQ predicts:
`FINCBTXM` excludes meals and rent as pay, which the published "Income before
taxes" line includes.

## 4. Gate 1 — population and quintile structure

The population stage is validated and reported **before** any expenditure
comparison, so that a bad quintile assignment cannot be mistaken for a bad
annualization.

| Population | Published (000s CU) | PUMD (000s CU) | Diff | Published mean income | PUMD mean income | Diff |
|---|---:|---:|---:|---:|---:|---:|
| All Consumer Units | 135,760 | 135,760.05 | +0.00004% | 104,207 | 104,894 | +0.660% |
| Q1 | 27,139 | 27,075.18 | −0.235% | 16,658 | 16,505 | −0.918% |
| Q2 | 27,186 | 27,197.06 | +0.041% | 42,925 | 42,859 | −0.154% |
| Q3 | 26,959 | 26,662.00 | −1.102% | 74,474 | 74,378 | −0.129% |
| Q4 | 27,205 | 27,208.29 | +0.012% | 121,548 | 121,586 | +0.031% |
| Q5 | 27,272 | 27,617.52 | +1.267% | 264,510 | 265,655 | +0.433% |

The All-CU total reproduces to fifty-three consumer units in 135.76 million.
That is a strong signal that the weighting and `MO_SCOPE` rules are right,
because there is no free parameter that could have been adjusted to hit it.

The quintile counts are looser, and in the expected direction: Q5 is over-filled
by 1.27% and Q3 under-filled by 1.10%. Assignment by published limits using a
disclosure-perturbed income variable will move boundary CUs, and the top
quintile is where topcoding bites. This is `PARTIALLY_ESTABLISHED` structure
being reported honestly, not a solved problem.

## 5. The roster

Fifteen UCCs, selected by a rule stated in advance — before any expenditure
error existed — and implemented in `pumd_benchmark.py::select_roster`:

1. Milestone-2 `provenance_class == DIRECT_CONCORDANCE_UCC`
2. Milestone-2 `ce_source == I`
3. not one of the 58 Milestone-1 exception UCCs
4. present in `CE-HG-Inter-2024.txt` with `section == EXPEND`
5. present in `CE-HG-Integ-2024.txt` with `section == EXPEND` **and** `survey == I`
6. LABSTAT publishes a mean for all six LB01 populations

then equal-count terciles of the eligible pool by published All-CU mean; then
only DMI nodes with at least one eligible UCC in **every** tercile; then the
median member by rank within each (node, stratum) cell.

| UCC | Title | Node | Stratum | All-CU published mean |
|---|---|---|---|---:|
| 230112 | Painting and papering | HOUSEHOLD_FURNISHINGS_OPERATIONS | LARGE | 126 |
| 250212 | Gas, bottled/tank (owned home) | HOUSEHOLD_ENERGY | MEDIUM | 45 |
| 260111 | Electricity (renter) | HOUSEHOLD_ENERGY | LARGE | 459 |
| 260114 | Electricity (rented vacation) | HOUSEHOLD_ENERGY | SMALL | 4 |
| 270411 | Trash/garbage collection (renter) | WATER_SEWER_TRASH | MEDIUM | 25 |
| 270412 | Trash/garbage collection (owned home) | WATER_SEWER_TRASH | LARGE | 225 |
| 270413 | Trash/garbage collection (owned vacation) | WATER_SEWER_TRASH | SMALL | 8 |
| 280220 | Slipcovers and decorative pillows | HOUSEHOLD_FURNISHINGS_OPERATIONS | SMALL | 6 |
| 320420 | Power tools | HOUSEHOLD_FURNISHINGS_OPERATIONS | MEDIUM | 35 |
| 450350 | Car/truck lease payments | TRANSPORT_SERVICES | LARGE | 228 |
| 450353 | Cash down payment car/truck lease | TRANSPORT_SERVICES | MEDIUM | 39 |
| 460110 | Used cars | TRANSPORT_COMMODITIES_EX_MOTOR_FUEL | LARGE | 710 |
| 470212 | Motor oil on out of town trips | TRANSPORT_COMMODITIES_EX_MOTOR_FUEL | SMALL | 2 |
| 480100 | Vehicle parts, accessories, fluid excluding tires | TRANSPORT_COMMODITIES_EX_MOTOR_FUEL | MEDIUM | 45 |
| 520542 | Tolls on out of town trips | TRANSPORT_SERVICES | SMALL | 6 |

`roster_version = v0.2`,
`roster_hash = 5d01d306772bedeb8025723f8f4684133b7200e689d77fadfd29a1c3d3d88a33`.
The hash is pinned inside the frozen spec, and `run_benchmark` refuses to run
against a roster that does not hash to it. The full roster was run; nothing was
dropped for reproducing poorly.

This is the **v0.2** roster, and it is not the one first frozen. The selection
rule is unchanged; the pool it selects from was corrected after the v0.1 run
failed, and the roster fell from 18 UCCs to 15 as a consequence. §10 sets out
what was wrong, why the correction is a repair rather than a cull, and what it
cost.

The roster is deliberately hard on itself. It spans two orders of magnitude —
$2 to $710 — because a benchmark restricted to large items would test only the
easy case, and it includes items with published RSEs above 20% because those
are where a wrong weight would hide.

## 6. The acceptance rule and what was precommitted

The thresholds live in
[`registry/research/pumd_lb01_benchmark_spec_v0_1.json`](../../registry/research/pumd_lb01_benchmark_spec_v0_1.json),
`spec_version = v0.2`, and are derived from what BLS documents about why PUMD
diverges from published tables — chiefly the non-disclosure adjustment and
income imputation — rather than from any observed error.

**Not every threshold was blind, and the spec says so.** The eight expenditure
thresholds were written before a single UCC-level percentage error existed. The
two population thresholds were not: the population and quintile stages had been
prototyped first, so those two are *informed*. They are reported as informed
rather than presented as predictions.

**No threshold moved.** `thresholds_unchanged_since = "v0.1"`,
`threshold_change_log = []`, and the acceptance rule in the passing v0.2 spec is
byte-identical to the one in the superseded v0.1 spec that produced a FAIL. A
committed test asserts this equality, which is the strongest available guarantee
that the FAIL→PASS transition was not obtained by loosening anything.

**Small values are judged differently, and that was in the frozen text.** LB01
publishes means as whole dollars, so a published mean of $2 carries a $0.50
rounding half-width — 25% of the value. Cells with a published mean below $10
are therefore judged on absolute difference (≤ $2.00) rather than percentage,
and are excluded from the percentage distribution. They still contribute their
PASS or FAIL to the pass fraction. This is an alternate diagnostic, not an
exemption; 29 of the 90 comparisons were judged this way, and the worst of them
was off by $1.00.

## 7. Results

Distribution of the 61 percentage-judged comparisons:

| Statistic | Value |
|---|---:|
| median \|% error\| | 1.09% |
| p75 \|% error\| | 2.31% |
| p90 \|% error\| | 4.09% |
| max \|% error\| | 13.36% |
| mean signed % error | −0.298% |

Mean signed error by population:

| | All CU | Q1 | Q2 | Q3 | Q4 | Q5 |
|---|---:|---:|---:|---:|---:|---:|
| mean signed % error | +0.230 | +0.731 | −1.022 | −0.581 | −0.982 | −0.174 |

The signed errors are **not monotone in income** and Q5 is not the worst. That
matters: a systematic bias increasing with income would have suggested topcoding
was dominating, and a systematic bias of constant sign would have suggested a
wrong annualization factor or a wrong weight. Neither pattern is present. The
overall mean of −0.30% against a ±3.00% tolerance says the errors are
dispersion, not bias.

## 8. The three failures

| UCC | Title | Population | Published | PUMD | Error | PUMD SE | Published RSE | n |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 230112 | Painting and papering | Q3 | 66 | 58.57 | −11.25% | 13.54 | 22.55% | 41 |
| 480100 | Vehicle parts, accessories, fluid ex. tires | Q4 | 65 | 56.51 | −13.06% | 10.47 | 20.51% | 231 |
| 480100 | Vehicle parts, accessories, fluid ex. tires | Q5 | 67 | 75.95 | +13.36% | 18.18 | 17.47% | 253 |

All three are quintile cells; no All-CU comparison failed. All three are
**within one BRR standard error** of the published value — the $7.43 shortfall
on 230112/Q3 sits against a standard error of $13.54. 230112/Q3 rests on 41
reporting consumer units and carries a published RSE of 22.55%; BLS's own
estimate of that cell is imprecise.

The two 480100 failures have opposite signs in adjacent quintiles (Q4 low, Q5
high) while the All-CU figure for that UCC passes. That is the signature of
boundary reassignment, not of a wrong estimate: consumer units near the Q4/Q5
limit are landing on a different side than they do in the confidential file,
which is exactly the consequence the spec anticipated from assigning by
published limits using an imputed, disclosure-perturbed income variable.

These are reported as failures, not explained away. Three of ninety exceed the
per-cell tolerance; the rule permits eighteen.

## 9. Three independent corroborations

The pass would be weaker if it rested only on the error distribution. It does
not.

**Publication rounding.** The largest absolute difference across all fifteen
All-CU comparisons is **$0.4956**. Every one of the fifteen is inside the $0.50
half-width of the published value's own rounding. At the All-CU level the
reproduction is as exact as the published figures permit anyone to verify.

**Independently published standard errors.** LB01 publishes an RSE for each
cell, computed by BLS from the confidential file. The benchmark computes its own
RSE from the 44 PUMD replicate weights. The median difference across all 90
cells is **−0.0014 percentage points**, with a range of −2.07 to +6.46 pp and 89
of 90 within 5 pp. The BRR machinery is reproducing not just the point estimates
but their sampling variability, against a quantity that was never a target.

**The failures are inside their own uncertainty.** All 3 of 3 are within one
standard error.

## 10. The v0.1 FAIL, and two corrections made after seeing it

The first run **failed**, on `p90_abs_pct_error_max` and
`mean_signed_pct_error_abs_max`. Its roster, results and FAIL verdict are
preserved unaltered under
`data/research/detailed_inflation/pumd_benchmark_2024/superseded/roster_v0_1/`.
Two defects were then fixed. Both fixes were made **after** the failing results
were seen, which is the circumstance under which a fix most needs justifying.

**Defect 1 — the eligibility test was vacuous.** The v0.1 rule tested the survey
source code in `CE-HG-Inter-2024.txt`. That is the *Interview* stub, so its
survey code is `I` for essentially every row; the test excluded nothing. LB01 is
Table 1101, an **integrated** table, and the file that states which survey
supplies a published integrated value is `CE-HG-Integ-2024.txt`. Twenty-seven
UCCs present in the Interview stub carry survey code `D` there: their published
means come from the Diary survey and cannot be reproduced from Interview
microdata at all. One of them, 690119 (Computer software), had entered the v0.1
roster.

Why this is a fix and not a cull: the corrected rule is stated without reference
to any error, it was applied uniformly to the whole candidate pool, and it
disqualifies 690119 for the same reason it disqualifies the other twenty-six —
none of which was in the roster. It is independently corroborated: every 2024
Interview MTBI record for 690119 carries `PUBFLAG = 1`, documented in the PUMD
dictionary as "Not published".

The correction was not free. `EDUCATION_COMMUNICATION` had exactly one eligible
MEDIUM-stratum candidate — 690119. Losing it cost that node its full-stratum
coverage, so the unchanged node filter dropped the whole node, taking 670320 and
690116 with it. The roster fell from 18 UCCs to 15. That collateral loss was not
chosen; it is what the unchanged rule does with the corrected pool.

**Defect 2 — the code contradicted the frozen spec.** `summarize()` was
including cells below the small-value floor in the percentage-error
distribution, even though the frozen spec text already said such cells are
judged on absolute difference *instead*, because a percentage against a
near-zero base measures publication precision rather than reproduction quality.
Thirty-five of the 108 v0.1 comparisons had a published mean under ten dollars,
and their rounding artefacts dominated p90 and the mean signed error. The code
was corrected to match the text it was supposed to implement. No threshold was
changed.

A reader who wants to discount this PASS should discount it on the ground that
the roster shrank from 18 to 15 while the rule was being repaired, and should
weigh that against the fact that no tolerance moved and the corrected rule is
stated independently of any result.

## 11. What this does not establish

- **It does not establish quintile construction.** `quintile_construction`
  remains `PARTIALLY_ESTABLISHED`. Which income variable BLS ranks, which weight
  it ranks by, and how it handles ties and the boundary CU are all still
  unknown. The benchmark sidesteps this by assigning on published limits; it
  does not solve it.
- **It does not extend beyond the roster.** Fifteen UCCs in five DMI nodes and
  two domains reproduced well. Nothing here says the other several hundred do.
- **It does not extend beyond 2024,** and does not test the Diary survey or any
  integrated (I+D) UCC.
- **It does not touch 910104–910107.** Their `pumd_quantitative_usability`
  remains `NOT_ESTABLISHED`. Two findings from this work corroborate the frozen
  Milestone-2 result without changing it: none of the four appears in either
  2024 hierarchical grouping file while 910050, 910101, 910102 and 910103 do;
  and the PUMD dictionary documents `PUBFLAG = 1` as "Not published", which
  supplies the meaning of a code Milestone 2 had recorded bare.
- **It is not authorization.** No DMI weight, price, index or release may be
  sourced from PUMD on the strength of this document.

## 12. Test evidence

`tests/test_detailed_inflation_pumd_benchmark.py`:

- **124 tests pass** with the PUMD archive present
  (`DMI_PUMD_2024_INTERVIEW_DIR` set); **121 pass and 3 skip cleanly** without
  it. The suite is fully runnable by someone who does not have the microdata.
- Coverage includes schema validation, duplicate and orphan join detection,
  calendar-year eligibility, `MO_SCOPE` and annualization, final-weight
  application, weighted quintile assignment, boundary and tie handling,
  zero/negative/missing income, roster immutability against the committed CSV,
  estimand and units consistency, the firewall, and the absence of any
  910104–910107 amount in any artifact.
- **The suite is proven non-vacuous.** A mutation probe, run outside the
  repository and not committed, breaks one methodological decision at a time in
  the real modules and reruns the whole suite in a fresh subprocess. **All 21
  injections were detected** — including `MO_SCOPE` ignored, unweighted
  aggregation, quintile ties to the wrong side, the BRR divisor changed to
  n−1, annualization forced to 1, the roster hash made constant, the shelter
  guard defused, and the v0.1 eligibility defect reintroduced.
- The whole repository suite is green: **497 passed, 8 skipped, 811 subtests**.

Two tests are worth naming because they guard the claims most easily faked. One
asserts that the superseded v0.1 acceptance rule equals the passing v0.2 rule,
so no tolerance can have been loosened. One forges a `RosterEntry` for 910104
past its own `__post_init__` and asserts `run_benchmark` still refuses, so the
shelter guard is shown to be live rather than decorative.

## 13. Provenance

| | |
|---|---|
| `benchmark_status` | **PASS** |
| Benchmark year | 2024 |
| Source registry | `registry/research/pumd_2024_interview_source_v0_1.json` |
| Spec artifact | `registry/research/pumd_lb01_benchmark_spec_v0_1.json` |
| `spec_version` | v0.2 |
| `roster_version` | v0.2 |
| `roster_hash` | `5d01d306772bedeb8025723f8f4684133b7200e689d77fadfd29a1c3d3d88a33` |
| Roster size | 15 |
| Acceptance rule | unchanged since v0.1; `threshold_change_log: []` |
| Frozen checkpoint | `dmi-detailed-inflation-v0.1-m2-corrected` @ `e6402097eacd45c536a30a0ae9c9476fc2bfc76d` (not modified) |

Microdata archives (retrieved 2026-08-17, held outside the repository at
`~/dev/dmi-data/pumd/2024/`, nothing committed):

| Archive | Bytes | SHA-256 |
|---|---:|---|
| `intrvw24.zip` | 53,613,162 | `421ec90c2b8469c10f91eac27988f65f5d09fcfa9944e5069bb00b5460677f26` |
| `intrvw23.zip` | 46,493,816 | `97e9a17edeee28e77a3fd5a7d874e5f4b9034222be204e25b0d902f4c82235ac` |

`intrvw23.zip` is recorded as a documented alternative and is **not used**. The
Getting Started Guide states that releases from 2020 onward omit the first
quarter of the release year, which would have forced the 2024 Q1 files to come
from the prior release; the 2024 archive in fact contains `fmli241x`/`mtbi241x`.
The archive listing was believed over the prose, and the discrepancy is recorded
in the source registry rather than silently absorbed.

Per-member SHA-256 digests for the ten CSVs actually used are in the source
registry under `archives.INTRVW24.members_relied_on`.

BLS documents relied on, each with its retrieval timestamp and SHA-256 in the
source registry:

| Document | Retrieved (UTC) |
|---|---|
| PUMD Getting Started Guide (page last modified April 8, 2026) | 2026-08-17T19:56:10Z |
| PUMD Documentation page | 2026-08-17T19:56:11Z |
| CE Interview Sample Program (`sas-table.zip`, program year constant 2018) | 2026-08-17T20:29:39Z |
| Hierarchical grouping files (`stubs.zip`) | 2026-08-17T20:29:53Z |
| PUMD Interview/Diary Dictionary | 2026-08-17T20:29:53Z |
| CE FAQ | 2026-08-17T20:29:53Z |
| Handbook of Methods, CEX Presentation | 2026-08-17T20:50:11Z |
| Table 1101, 2024 (source line: December 2025) | 2026-08-17T20:50:42Z |
| Tables Getting Started Guide | 2026-08-17T20:51:42Z |
| Source Selection File | 2026-08-17T20:52:16Z |
| PUMD Data Files page | 2026-08-17T20:53:57Z |

One documentation discrepancy is recorded and worked around rather than
absorbed: the documented hierarchical-grouping column layout (source at 83,
factor at 86, section at 89) matches `CE-HG-Inter-2018.txt` but **not**
`CE-HG-Inter-2024.txt`, which is shifted three characters left after the UCC
field. Column offsets are detected per file at load time by locating the
six-digit UCC field and the known token sets; nothing is hardcoded.

## 14. Artifacts

| Path | |
|---|---|
| `registry/research/pumd_2024_interview_source_v0_1.json` | documents, archives, established method |
| `registry/research/pumd_lb01_benchmark_spec_v0_1.json` | frozen acceptance rule, roster hash, revision history |
| `data/research/detailed_inflation/pumd_benchmark_2024/benchmark_roster.csv` | the 15 UCCs |
| `…/population_validation.csv` | gate 1 |
| `…/quintile_reconstruction.csv` | diagnostic only |
| `…/benchmark_results.csv` | 90 comparisons |
| `…/benchmark_summary.json` | verdict and diagnostics |
| `…/superseded/roster_v0_1/` | the preserved v0.1 FAIL |
| `dmi_research/detailed_inflation/pumd.py` | estimation pipeline |
| `dmi_research/detailed_inflation/pumd_benchmark.py` | roster, comparison, acceptance |
| `scripts/benchmark_pumd_2024.py` | runner |
| `tests/test_detailed_inflation_pumd_benchmark.py` | tests |

Reproduce with:

```
DMI_PUMD_2024_INTERVIEW_DIR=<extracted intrvw24> \
python3 scripts/benchmark_pumd_2024.py --stub-dir <extracted stubs>
```

The benchmark has no automatic download step by design; the archives are
acquired out of band and verified against the digests above.
