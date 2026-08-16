# Detailed Inflation Substrate v0.1 — Milestone 1

**Status: RESEARCH ONLY. Not a DMI specification. Not wired into any release.**

**Core DMI remains withdrawn and unimplemented.** Nothing in this document or
in the code it describes implements, restores, or approximates the withdrawn
Core specification. This milestone computes no inflation index, constructs no
weights, acquires no CPI data, and produces no DMI release.

---

## 1. Purpose

The Detailed Inflation Substrate is an exploration of whether a household
inflation measure could be built from a *detailed* expenditure basis — the
individual Consumer Expenditure (CE) items BLS actually collects — rather than
from a handful of top-level aggregates, and whether that basis can be
differentiated by income quintile.

Milestone 1 answers one narrow, empirical, prerequisite question:

> For 2024, across the Food, Alcoholic beverages, Housing and Transportation
> CE domains, how much household expenditure can actually be mapped onto CPI
> price indexes, and how much cannot?

The answer is a *feasibility audit*, not a measure. It quantifies the mapping
gap and the sampling-noise burden that any later design would have to confront.
It deliberately stops before the point where methodological choices would begin.

## 2. Why this is research-only

Three reasons, in order of importance.

**The mapping is not complete.** 19.4% of All-Consumer-Unit expenditure in
these four domains has no row in the BLS UCC→ELI concordance. That is not a
defect in this code; it is a real difference between what CE measures
(household outlays, including mortgage interest and property taxes) and what
CPI prices (consumption, using owner-equivalent rent). Resolving it requires
economic judgement about scope, not more parsing.

**The quintile estimates are noisy.** 11.5% of first-quintile expenditure sits
in items whose relative standard error is at or above 25%. Any quintile-level
index built on this basis inherits that noise. Milestone 1 measures the burden
so that a later design can decide what to do about it; it does not decide.

**Nothing here has been reviewed as a specification.** The 14-node computation
taxonomy in `registry/research/detailed_inflation_taxonomy_v0_1.json` is a
*candidate* structure used to test whether concordance destinations collapse
coherently. It is not an approved DMI category set.

A firewall enforces the boundary in code: `assert_research_output_dir()`
refuses to write anywhere under `data/outputs/` or `deploy/data/outputs/`, and
`tests/test_research_firewall.py` fingerprints both trees before and after a
real audit run to prove they are untouched.

## 3. Required external BLS inputs

These files are published by BLS, are large (up to ~739 MB), and are **never
committed to this repository**. Supply them by path.

| Argument | File | Source |
|---|---|---|
| `--series` | `cx.series` | BLS LABSTAT, CE Surveys |
| `--data` | `cx.data.1.AllData` | BLS LABSTAT, CE Surveys |
| `--items` | `cx.item` | BLS LABSTAT, CE Surveys |
| `--aspects` | `cx.aspect` | BLS LABSTAT, CE Surveys |
| `--concordance` | pinned normalized TSV (committed) | derived from the BLS UCC→ELI concordance workbook |

LABSTAT flat files are available from the BLS public data download facility
under `pub/time.series/cx/`. `cx.series` and `cx.aspect` may be pre-filtered to
the 2024 target universe; the loaders stream and filter internally, so an
unfiltered file also works.

### The concordance is pinned, and the version matters

The audit does not re-parse the BLS workbook on every run. It joins against
`registry/research/ucc_eli_concordance_2024_v0_1.tsv`, produced once by
`scripts/import_ucc_eli_concordance.py` and committed alongside a provenance
sidecar recording the source SHA-256, row counts and the BLS trailer notes
verbatim.

The pinned artifact derives from the **August 2026** concordance publication,
which states:

> This mapping reflects the CPI item structure that was introduced for 2024
> annual expenditure weights used in the calculation of indexes starting in
> January 2026.

That is the version aligned to the 2024 weights this milestone audits. **Do not
substitute the January 2025 or January 2024 archived concordances**; BLS
publishes those separately and they encode a different CPI item structure.

To regenerate:

```bash
python scripts/import_ucc_eli_concordance.py \
    --source /path/to/ce-cpi-concordance-August-2026.xlsx \
    --out    registry/research/ucc_eli_concordance_2024_v0_1.tsv
```

## 4. How to run the audit

```bash
python scripts/audit_detailed_inflation_2024.py \
    --series   /path/to/cx.series_2024_dmi_target.tsv \
    --data     /path/to/cx.data.1.AllData \
    --items    /path/to/cx.item \
    --aspects  /path/to/cx.aspect_2024_dmi_target.tsv \
    --concordance registry/research/ucc_eli_concordance_2024_v0_1.tsv \
    --output-dir  data/research/detailed_inflation/audit_2024
```

`--dry-run` prints the report without writing artifacts. The command exits
non-zero if the parent accounting reconciliation fails.

`--year`, `--rounding-unit` and `--rse-threshold` are exposed so the audit can
be re-run for another year or re-examined under a different assumption. None of
them is tuned to make the numbers come out right.

## 5. Output artifacts

All artifacts are written to a research directory, by default
`data/research/detailed_inflation/audit_2024/`.

| Artifact | Contents |
|---|---|
| `audit_summary.json` | Every headline figure, the parameters used, concordance provenance, and the delta against each expected baseline |
| `active_ucc_basis.csv` | The accounting basis: one row per active UCC per population, with aggregate expenditure, mean expenditure, RSE and the high-RSE flag |
| `parent_reconciliation.csv` | Summed leaves vs published domain parent, with the absolute difference, the percentage difference, the rounding bound and the pass flag |
| `ucc_mapping_audit.csv` | One row per UCC: destination ELIs, destination nodes, mapping status, exception reason |
| `mapping_status_summary.csv` | Counts and expenditure shares by status and population |
| `rse_audit.csv` | Per-population, per-domain and combined RSE statistics, including missing counts |
| `exception_ledger.csv` | Every UCC Milestone 1 could not resolve, with its All-CU expenditure and why |

## 6. Mapping-status semantics

Five statuses exist in the model. **Milestone 1 assigns only three of them**,
and it assigns them by derivation, never from a hand-maintained list.

| Status | Meaning | Assigned by Milestone 1 |
|---|---|---|
| `DIRECT` | Exactly one destination ELI, resolving to one computation node | Yes |
| `MULTI_SAME_NODE` | Several destination ELIs, all resolving to the *same* node | Yes |
| `UNRESOLVED` | No concordance row, or destinations spanning more than one node | Yes (preliminary) |
| `TRANSFORMED` | Requires a CE→CPI scope transformation (e.g. owner-equivalent rent) | **No** |
| `OUT_OF_SCOPE` | Genuinely outside CPI consumption scope | **No** |

Two distinctions carry real weight:

**A UCC with no concordance row is not out-of-scope.** It is unresolved. Some
of these items (mortgage interest, property taxes) will almost certainly end up
`TRANSFORMED` or `OUT_OF_SCOPE` once scope rules exist — but deciding that
requires the rules, and asserting it now would silently discard 19.4% of
expenditure behind a label that sounds authoritative. They go in the exception
ledger instead.

**`MULTI_SAME_NODE` is not a problem to be solved.** When a UCC maps to five
gasoline ELIs that all land in `MOTOR_FUEL`, the multiplicity is immaterial:
one node receives the whole amount. Expenditure is never split, never
renormalized, and never allocated across nodes.

Cross-node multi-mapping *would* be a problem, because allocating one UCC's
expenditure across two nodes requires the BLS special adjustment factors, which
are not part of the published concordance. Detection is generic — the classifier
compares resolved node sets, it does not test for known cases — and for 2024 in
these four domains it finds none.

An ELI that cannot be resolved to a node raises `UnknownEliError` and aborts
the run. This is deliberate: silently dropping an unmapped ELI would understate
mapped expenditure and hide a concordance change behind a plausible-looking
number.

## 7. Findings

Derived from the authoritative 2024 files. Every figure below is computed, not
asserted; the expected baselines are reported alongside as deltas and are never
substituted into the computation.

**Accounting basis.** 337 active numeric UCCs, identical across all six
populations. Descriptive parent aggregates (`FOODTOTL`, `FOODHOME`, `BAKERY`, …)
are excluded structurally by the six-digit-numeric rule, so parents and
children are never summed together.

**Parent reconciliation.** All 24 domain × population checks pass. The largest
residual is 5 units against a parent of 200,392 — indisputable publication
rounding.

**Mapping, by expenditure share, All Consumer Units:**

| Status | UCCs | Share |
|---|---|---|
| `DIRECT` | 274 | 71.39% |
| `MULTI_SAME_NODE` | 5 | 9.20% |
| Cross-node multi-map | 0 | 0.00% |
| No concordance | 58 | 19.41% |

**The five `MULTI_SAME_NODE` cases**, derived rather than enumerated:

| UCC | Title | Node | Destination ELIs |
|---|---|---|---|
| 270102 | Cellular phone service | `EDUCATION_COMMUNICATION` | ED031, EE041 |
| 470111 | Gasoline | `MOTOR_FUEL` | TB011, TB012, TB013, TB021, TB022 |
| 470113 | Gasoline on out-of-town trips | `MOTOR_FUEL` | TB011, TB012, TB013, TB021, TB022 |
| 480100 | Vehicle parts/accessories/fluids excl. tires | `TRANSPORT_COMMODITIES_EX_MOTOR_FUEL` | TC021, TC022 |
| 490100 | Vehicle maintenance/repair excl. tire purchase | `TRANSPORT_SERVICES` | TD011, TD021, TD031 |

**High-RSE expenditure share** (RSE ≥ 25%, all four domains combined):

| Population | Share |
|---|---|
| All Consumer Units | 0.98% |
| Q1 | 11.47% |
| Q2 | 9.81% |
| Q3 | 7.93% |
| Q4 | 6.52% |
| Q5 | 2.79% |

The gradient is the substantive result. Pooling all consumer units conceals an
order-of-magnitude difference in estimate reliability between the bottom and
top quintiles. Any quintile-differentiated measure built on this basis must
confront it explicitly.

**Exception ledger:** 58 UCCs, 1,326,642 units of All-CU aggregate
expenditure. It is dominated by mortgage interest (471,125) and property taxes
(371,669) — precisely the CE/CPI scope difference the owner-equivalent-rent
treatment exists to address — followed by home maintenance and repair
services, out-of-town food, and vehicle finance charges and registration fees.

## 8. Known limitations and unresolved questions

1. **19.4% of expenditure is unmapped.** Until CE/CPI scope rules are written,
   this share cannot be classified. It is not evenly distributed: it is
   concentrated in Housing, which means Housing is the domain where a naive
   detailed index would go wrong first.

2. **Owner-equivalent rent is untouched.** CE reports mortgage interest and
   property taxes as outlays; CPI prices shelter through owner-equivalent
   rent. Reconciling these is a methodological decision, not a mapping
   exercise, and it is not attempted here.

3. **Suppressed estimates are missing, not zero.** BLS suppresses 19 All-CU and
   up to 38 Q1 aggregate values that do not meet publication standards, and
   suppresses the matching RSE in every case. These are reported as missing and
   excluded from both numerator and denominator. Whether a later design should
   impute them, and how, is open.

4. **The 14-node taxonomy is a candidate.** It was chosen to test whether ELI
   destinations collapse coherently — they do — not because it is the right
   reporting structure for DMI.

5. **ELI→node resolution rests on a documented identifier substring.** The
   leading two characters of a BLS ELI denote the CPI item grouping, so prefix
   lookup is an exact join, not a heuristic. Every prefix in the pinned
   concordance was verified node-homogeneous except `TA`, where vehicle leasing
   (`TA031`) and auto/truck rental (`TA041`) are transportation *services*
   despite sharing the vehicle-commodities prefix. Both are handled by explicit
   overrides carrying stated reasons. A future concordance could introduce
   another heterogeneous prefix; the resolver has no default node and will
   abort rather than guess.

6. **One year, four domains, one demographic set.** 2024, Income Quintiles
   (`LB01`), Food / Alcoholic beverages / Housing / Transportation. Nothing
   here establishes that the mapping is stable over time.

7. **No price data.** No CPI series has been acquired or validated. The
   `candidate_cpi_series_id` values in the taxonomy are structurally
   well-formed and unique, and have not been fetched.

## 9. Relationship to the future Core specification

**Core DMI is withdrawn and unimplemented.** This substrate is not Core, is not
a replacement for Core, and does not restore it.

If a future specification were to use a detailed expenditure basis, this
milestone establishes what it would inherit: a reconciled 337-UCC accounting
basis, an 80.6%-mapped expenditure universe, an explicit ledger of the
remainder, and a quantified statement of the sampling-noise burden by quintile.
It also establishes what such a specification would still owe: scope rules for
the unmapped 19.4%, a shelter treatment, a decision on suppressed estimates,
and an approved category structure.

The next milestone is not authorized by this work. Weight construction, CPI
acquisition, owner-equivalent-rent transformation, Core calculation, historical
backfill and operational integration are all explicitly out of scope.

## 10. Attribution

Source data and classification systems used here are publications of the
**U.S. Bureau of Labor Statistics**:

- **Consumer Expenditure Surveys** — the CE LABSTAT series, item, aspect and
  data files, including the UCC item structure, aggregate expenditure
  estimates, and relative standard errors.
- **Consumer Price Index** — the CPI item structure, Entry Level Item (ELI)
  codes and titles, and the CPI series identifiers referenced as candidates.
- **UCC→ELI concordance** — the published mapping between CE Universal
  Classification Codes and CPI Entry Level Items.

DMI did not originate any of these classification systems, statistical
methodologies, sampling designs, or estimates. This repository contributes only
the audit code, the derived research artifacts, and the candidate ELI→node
assignment, which is DMI research metadata and is **not** a BLS product.

## 11. Code map

| Path | Role |
|---|---|
| `dmi_research/detailed_inflation/sources.py` | BLS LABSTAT loaders; metadata-driven target selection |
| `dmi_research/detailed_inflation/basis.py` | Active numeric-UCC basis; parent reconciliation |
| `dmi_research/detailed_inflation/taxonomy.py` | Mapping-status model; taxonomy validation; ELI→node resolver |
| `dmi_research/detailed_inflation/concordance.py` | Pinned concordance loader |
| `dmi_research/detailed_inflation/mapping.py` | Classification, status summaries, exception ledger |
| `dmi_research/detailed_inflation/rse.py` | High-RSE flagging and expenditure-weighted summaries |
| `dmi_research/detailed_inflation/audit.py` | Orchestration, research firewall, artifact emission |
| `scripts/audit_detailed_inflation_2024.py` | CLI |
| `scripts/import_ucc_eli_concordance.py` | One-time concordance import and pinning |
| `registry/research/` | Candidate taxonomy, ELI→node map, pinned concordance + provenance |
| `tests/test_detailed_inflation_*.py`, `tests/test_research_firewall.py` | Test suite |

Tests that depend on the external BLS files skip automatically when those files
are absent, so the suite runs in CI. Everything else — including the five
`MULTI_SAME_NODE` regression cases and the 470311 ledger case — runs against
the committed pinned artifacts.
