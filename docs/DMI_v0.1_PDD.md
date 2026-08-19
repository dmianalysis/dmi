# DMI v0.1 — Product Design Document (PDD)

**Product:** Distributional Misery Index (DMI)
**Version:** v0.1
**Spec package revision:** v0.1.8
**Date:** 2025-12-17

> ## ⚠️ v0.1.12 STATUS BANNER — READ FIRST (§12)
>
> This PDD describes the **v0.1 (spec-package v0.1.8) design intent**,
> including three operational specifications (Baseline, Slack-Plus,
> Core). It has NOT been rewritten for v0.1.12.
>
> The shipped v0.1.12 reality differs from this document in two
> load-bearing ways:
>
> 1. **Core is withdrawn.** No `dmi_release_*_core.*` artifact is
>    produced by the v0.1.12 pipeline, and no `latest_core` endpoint
>    is advertised. The Core-labeled files that existed in prior
>    versions were byte-identical to the Baseline computation — the
>    Core-specific calculation described in this PDD was never
>    implemented. See
>    [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md).
> 2. **Two operational specifications only:** Baseline (U-3, headline
>    CPI) and Slack-Plus (U-6, headline CPI). Consult
>    [`README.md`](../README.md), [`docs/API.md`](API.md), and
>    [`CHANGELOG.md`](../CHANGELOG.md) for the current published
>    contract; consult
>    [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](repair/V0.1.12_ALIGNMENT_AUDIT.md)
>    for the evidence trail.
>
> Sections below that describe Core (§3.2, §4.0 design patterns,
> Alternative Specifications) remain for historical design context
> only; they do NOT describe operational v0.1.12 behaviour.

This PDD complements the implementation spec by describing what DMI v0.1 is, what it produces, and how success is evaluated.

---

## 1. Problem statement

Headline economic statistics (inflation, unemployment) obscure distributional realities.

DMI exists to make visible **how economic pressure differs across income groups** by combining:

- group-weighted inflation π(g,r,t)
- labor-market slack S(r,t)

---

## 2. Target users and use cases

Primary users:
- policymakers and staff
- journalists and researchers
- informed public (data-literate)

Typical use cases:
- “Which income group is experiencing the highest price pressure?”
- “Is pressure converging or diverging across groups?”
- “What categories drove this month’s shift for Q1 vs Q5?”

---

## 3. v0.1 scope

### 3.1 Outputs (what users see)

For each reference month *t*:
- DMI by income quintile (Q1–Q5), US national (geo_id = US)
- summary metrics: median, stress, dispersion
- inflation contributions by category (major-group reporting view)
- **weights snapshot used for the release** (w(g,c)) published as `weights_by_group.json` + CSV/Parquet exports
- a machine-readable **QA report** (`qa_report.json`) validating against `schemas/qa_report.schema.json`
- downloadable CSV/Parquet/JSON outputs (for DMI tables + weights)
- a machine-readable release metadata JSON (audit trail)
- outputs follow the publishable/internal separation defined by `registry/output_contract_v0_1.json`

### 3.2 Inputs (what the calculator consumes)

The deterministic calculator receives only curated matrices:
- CPI category index levels (by category × period × geo)
- group expenditure weights w(g,c)
- slack series S(geo, period)

### 3.3 Policies, registries, and artifacts (transparent governance)

v0.1 uses explicit registry + policy files to keep methodology transparent:

**Policies**
- Inflation geography policy: `registry/policies/geo_inflation_policy_v0_1.json`
- Slack policy: `registry/policies/slack_policy_v0_1.json`
- CE weights policy: `registry/policies/ce_weights_policy_v0_1.json`

**Registries**
- Geo registry: `registry/geo_registry_v0_1.yaml` (geo_id is an identifier, not a label)
- Category registry: `registry/category_registry_v0_1.json` (category_id meaning + universes)
- Category reporting views: `registry/category_reporting_views_v0_1.json` (compute → report separation)

**Pinned mapping artifact (v0.1 requirement)**
Because v0.1 uses CE *published tables* (not microdata), an explicit mapping artifact is required:
- `registry/artifacts/ce_table_to_cpi_mapping_v0_1.json`  
  CE table labels → CPI category_ids used in the v0.1 computation universe

Artifacts are versioned and checksummed in the manifest/release metadata so future versions can “swap in” improved mappings/weights without rewriting calculator logic.

---

## 4. Method (v0.1)

### 4.1 Formula

DMI(g,r,t) = 2 · [ 0.5 · π(g,r,t) + 0.5 · S(r,t) ]

### 4.2 Inflation π(g,r,t)

- CPI‑U major groups (US national by default)
- YoY log-change aggregation with group weights
- Contribution table produced for explainability

**Design requirement:** the calculator is category-agnostic (no hard-coded category logic).

### 4.3 Slack S(r,t)

- baseline: U‑3 unemployment rate
- v0.1 simplification: slack is not income-group-specific (same for all quintiles within a geo)

**Time alignment (publish constraint):**
- Published releases must satisfy `same_reference_month_required` (slack month matches inflation reference month).
- `latest_available_not_after` is permitted only for unpublished research/exploration outputs and must be explicitly flagged.

---

## 5. Acceptance criteria

v0.1 is accepted when:

1) **Reproducibility**
- A run with pinned inputs reproduces identical outputs.
- All policy decisions (fallbacks/proxies) are captured in release metadata.

2) **Transparency**
- Methods note and policy files explain:
  - how weights are built (CE tables, mapping artifact, exclusions, renormalization, excluded_share)
  - how inflation is computed
  - what slack measure is used
  - when/why national CPI is used as a proxy for subnational geos

3) **Auditability**

3b) **Schema validation + output contract compliance (v0.1.8)**
- All schema-bound JSON artifacts validate (via `jsonschema`): `dmi_release.json`, `qa_report.json`, `release_metadata.json` (and `weights_vintage_review_packet.json` when triggered).
- Publisher prevalidates output contract compliance to avoid partially-written releases.
- `release_metadata.json` validates against `schemas/release_metadata.schema.json`.
- `qa_report.json` validates against `schemas/qa_report.schema.json`.
- The published release includes a weight snapshot (`weights_by_group.json` + exports) matching the weights used in computation.
- Raw source artifacts have checksums and retrieval timestamps recorded.

4) **Minimum viable UX**
- Outputs are viewable as a simple dashboard and downloadable as files.

5) **Conservative publication gates**
- If `weights_year` changes versus the prior published release, default is **FAIL publish** unless explicitly approved.
  - The pipeline may still generate an internal candidate backfill + diff report to reduce review burden.
- Slack time alignment must be satisfied for published releases (else FAIL publish).

---

## 6. Non-goals (v0.1)

- Causal attribution (“X policy caused Y”)
- Forecasting
- Quintile-specific unemployment
- Full CE microdata processing
- Modeled state inflation where CPI is not published

---

## 7. Risks and mitigations

- **Weights complexity:** CE PUMD processing is complex.  
  v0.1 mitigation: use CE published tables + explicit CE→CPI mapping artifact.

- **Weights vintage discontinuities:** Annual table updates can shift results.  
  v0.1 mitigation: conservative gating on weights_year changes (default: fail publish unless approved), plus optional internal backfill candidate + diff report.

- **Subnational CPI coverage gaps:** Many states have no CPI.  
  v0.1 mitigation: explicit national CPI proxy rule + required flags; optional BEA RPP for price-level comparisons only.

- **Future CPI granularity upgrades:** moving from major groups → ELI can create category universe changes.  
  v0.1 mitigation: category registry + reporting views + pinned crosswalk artifacts, so upgrades are primarily data swaps (not calculator rewrites).

- **CE table format drift (XLSX):** BLS can change table layouts year-to-year.  
  v0.1.8 mitigation: structural validation before extraction (expected labels present, Mean→Share row pairing, group column counts) and clear parse diagnostics on failure.

- **Output contract drift / incomplete releases:** Missing one required file breaks downstream consumers (web, audits).  
  v0.1.8 mitigation: publisher prevalidation against `registry/output_contract_v0_1.json` and schema validation of required JSON artifacts before publish.

---
