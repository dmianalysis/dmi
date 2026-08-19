# Distributional Misery Index (DMI) v0.1 — Implementation Plan & PDD (Spec Package)

**Status:** Draft for implementation
**Version:** v0.1 (spec)
**Spec package revision:** v0.1.8
**Last updated:** 2025-12-17
**Author:** Thomas C. Williams (project owner)

> ## ⚠️ v0.1.12 STATUS BANNER — READ FIRST (§12)
>
> This specification documents the **v0.1 (spec-package v0.1.8) design
> intent**, including a three-specification architecture. It has NOT
> been rewritten for v0.1.12. The shipped v0.1.12 pipeline diverges
> from this spec in two material ways:
>
> 1. **Core is withdrawn.** The v0.1.12 pipeline emits Baseline and
>    Slack-Plus only; Core computation is not implemented. See
>    [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md).
> 2. **Retired endpoints and paths.** The public health manifest no
>    longer advertises `latest_core`, `latest_u6`, `timeseries`, or
>    `dmi_timeseries` (§8); the public timeseries at
>    `data/outputs/published/dmi_timeseries.json` is Baseline-only
>    (§7).
>
> For the current operational surface consult
> [`README.md`](../README.md),
> [`docs/API.md`](API.md),
> [`CHANGELOG.md`](../CHANGELOG.md),
> and [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](repair/V0.1.12_ALIGNMENT_AUDIT.md).

This document is the *implementation-facing* specification for a **reproducible, auditable** measurement tool that publishes a monthly **Distributed Misery Index** by income group.

Core principle:

> **Strict separation between deterministic calculation and data operations**  
> Deterministic math is pure, auditable, and reproducible; data work is automated but tightly governed.

---

## 0. Glossary (short)

- **DMI(g,r,t)**: Distributional Misery Index for income group *g*, geography *r*, month *t*
- **π(g,r,t)**: group-weighted inflation (YoY) for group *g* in geography *r*
- **S(r,t)**: labor-market slack (baseline: unemployment rate U‑3) for geography *r*
- **w(g,c)**: expenditure weight/share for group *g* in CPI category *c*
- **Manifest**: pinned configuration that fully determines what gets computed and published
- **Policy**: deterministic rule-set that selects series / fallbacks and emits explicit flags
- **Release metadata**: machine-readable audit record for one pipeline run/release
- **Computation categories**: categories used in the calculator inputs (weights + CPI levels)
- **Reporting categories**: categories shown in outputs (may be rollups of computation categories)

---

## 1. Product summary

### 1.1 What DMI v0.1 publishes

A **monthly** dataset and human-readable summaries that answer:

- How economic pressure varies by income quintile (Q1…Q5)
- Whether pressure is spreading out or concentrating (dispersion metrics)
- What moved the index this month (inflation contributions by category)

**Default geography:** US national (`geo_id = US`).  
The architecture is geo-extensible, but subnational publication is *not* required for the first public iteration.

### 1.2 v0.1 scope (minimum credible product)

**In scope**
- US national DMI by income quintile, monthly
- Inflation component uses CPI‑U **major groups** (category universe defined in a pinned category registry)
- Labor slack component uses national U‑3 unemployment rate
- CE weights come from **BLS published CE tables** (not PUMD), with an explicit pinned CE→CPI mapping artifact
- Pinned inputs + release metadata output (audit trail)
- **Conservative publish gates**:
  - **Weights vintage changes:** FAIL publish by default (but generate internal candidate backfill + diff report)
  - **Slack time alignment:** published releases must satisfy same_reference_month_required (otherwise FAIL publish)

**Out of scope (explicit non-goals)**
- Causal claims, forecasts, trading signals, or policy prescriptions
- “True welfare” measurement
- Quintile-specific unemployment (v0.2+)
- Full CE PUMD microdata processing (optional v0.2+ path)
- Modeled “state inflation” where CPI does not exist (v0.1 uses explicit national proxy + flags)

---

## 2. Architecture at a glance

### 2.1 Components

1) **Deterministic calculator** (`dmi_calculator/`)  
Pure functions:
- compute group-weighted inflation π(g,r,t)
- compute slack S(r,t)
- compute DMI and summary metrics

2) **Data scaffolding** (`data/` + `registry/` + `schemas/`)  
Defines:
- canonical observation schema
- curated artifact contracts
- deterministic policies (weights, slack, inflation-geo)
- registries (sources, series catalog, geo registry, **category registry**)
- reporting views (compute categories → reporting categories)
- mapping artifacts (CE table labels → CPI categories)

3) **Agentic back-end** (`dmi_pipeline/agents/`)  
Agents may automate:
- data collection (harvesting)
- integration (mapping + shaping)
- QA and gating
- publishing outputs + release metadata

…but **agents must never**:
- change the calculator formula
- choose methodology
- “fix” numbers to pass QA

---

## 3. Deterministic calculator (PDD section)

### 3.1 Core formula

﻿DMI(g,r,t) = scale_factor * [ α * π(g,r,t) + (1-α) * S(r,t) ]

Defaults:
- α = 0.5  
- scale_factor = 2.0 (so the baseline scale approximates “inflation + unemployment”)

### 3.2 Inflation: π(g,r,t)

v0.1 uses CPI category **index levels** (not seasonally adjusted by default for coverage) and a 12‑month horizon:

1. rel(c,r,t) = CPI(c,r,t) / CPI(c,r,t-12)  
2. log_rel(g,r,t) = Σ_c w(g,c) · ln(rel(c,r,t))  
3. π(g,r,t) = 100 · (exp(log_rel(g,r,t)) − 1)

The calculator also emits:
- category contribution table for explainability (each category’s contribution to π)

**Category-agnostic requirement (critical):**  
The calculator must not hard-code “Food/Housing/etc.” logic. It keys off `category_id` and the provided weights/CPI matrices.

### 3.3 Slack: S(r,t)

v0.1 uses **U‑3 unemployment rate** as the baseline slack proxy.

Key v0.1 simplification:
- Within a geography, slack is the same for all income groups (no group-specific unemployment yet).

Slack series selection + time alignment are governed by `registry/policies/slack_policy_v0_1.json`.

**Publish constraint:** the slack reference month must match the inflation reference month for published releases.

### 3.4 Outputs (contract)

Publishable release artifacts include (see output contract for exact filenames/formats):

- `dmi_by_group`: DMI(g,r,t) for each group
- `summary_metrics`: median (typically Q3), stress (e.g., max quintile), dispersion (Q5−Q1)
- `inflation_contributions`: π decomposition by (reporting) category
- `weights_by_group`: exact weight snapshot used for this release (w(g,c)), including weights_year + build metadata (published as JSON + CSV + Parquet)
- `qa_report`: machine-readable QA report (PASS/FAIL/PASS_WITH_WARNING) validating against `schemas/qa_report.schema.json`

**Authoritative output contract:** `registry/output_contract_v0_1.json` (validate with `schemas/output_contract.schema.json`).

---

## 4. Data scaffolding (PDD section)

### 4.1 Canonical observation schema (staging)

All ingested datapoints normalize into a single schema so QA and transformations are uniform.

See: `schemas/observation.schema.json`

Minimum staging fields:
- dataset_id, series_id
- geo_id
- category_id (CPI category or N/A)
- period (YYYY‑MM)
- value, unit, seasonal_adjustment
- source_url, retrieval_timestamp
- release_id (e.g., `BLS_CPI_2025-11`)

### 4.2 Storage layers

- **Raw** (`data/raw/`): as-downloaded source artifacts (JSON/CSV/XLSX/ZIP), checksummed  
- **Staging** (`data/staging/`): normalized observations (Parquet)  
- **Curated** (`data/curated/`): calculator-ready matrices (Parquet)  
- **Outputs** (`data/outputs/`): derived artifacts, split into:
  - `data/outputs/published/` — publishable releases (`releases/{YYYY-MM}/`) + `latest/` aliases
  - `data/outputs/internal/` — internal review artifacts (candidate backfills + diff packets; never deployed)

### 4.3 Curated artifacts (calculator-ready)

Curated artifacts are the *only* inputs the deterministic calculator receives.

- `cpi_category_levels.parquet`  
  CPI index levels by `category_id × period × geo_id`
- `weights_by_group.parquet`  
  w(g,c) by income group × CPI category_id  
  *v0.1 source:* CE published tables (`BLS_CE_TABLES`)
- `slack.parquet`  
  S(geo_id, period) (baseline: U‑3)

### 4.4 Registries, policies, and mapping artifacts

These files define “what data means” and must be versioned + reviewed:

**Registries**
- `registry/sources_registry_v0_1.yaml` — authoritative declarations of data sources
- `registry/series_catalog_v0_1.json` — CPI + slack series IDs and patterns
- `registry/geo_registry_v0_1.yaml` — canonical geo_ids and levels (geo_id is an identifier, not a label)
- `registry/category_registry_v0_1.json` — category_id dictionary + universes (supports future ELI expansion)
- `registry/category_reporting_views_v0_1.json` — reporting views (compute categories → reporting categories)

**Policies**
- `registry/policies/geo_inflation_policy_v0_1.json` — inflation geo selection rules
- `registry/policies/slack_policy_v0_1.json` — slack selection + time alignment rules
- `registry/policies/ce_weights_policy_v0_1.json` — CE weights extraction + gating rules

**Mapping artifacts**
- `registry/artifacts/ce_table_to_cpi_mapping_v0_1.json` — explicit CE table label → CPI category mapping (pinned + checksummed)

### 4.5 Release metadata (audit trail)

Each pipeline run produces one **release metadata** JSON file (schema):

- `schemas/release_metadata.schema.json`

The release metadata must record:
- manifest version + policy versions
- retrieval timestamps + raw checksums
- decision objects produced by deterministic policies (geo inflation selection, slack selection, weights vintage)
- QA status (PASS/FAIL/WARN)
- output file list + optional checksums
- references to registry artifacts used (geo registry, category registry, reporting view, mapping artifacts)

---

## 5. Agentic back-end (PDD section)

Agents are **automation modules** with narrow scope. They may use LLM assistance for:
- finding correct series IDs / endpoints,
- generating registry diffs,
- drafting release notes,
- preparing internal “candidate backfill + diff” reports,

…but never for changing numeric values or choosing methodology.

### 5.1 Agents (minimum set)

1) **SourceScout**  
Maintains registries (sources, series catalog, geo registry, category registry, reporting views) and policy references.  
- Proposes diffs; diffs require approval.

2) **Harvester**  
Pulls raw data (API/ftp/http) to `data/raw/` with checksums.

3) **Mapper**  
Maintains category mapping artifacts.  
- v0.1: CE published table label → CPI category mapping (`ce_table_to_cpi_mapping_v0_1.json`)  
- v0.2+: optional UCC→ELI→CPI crosswalk pipeline

4) **WeightsBuilder**

**v0.1.8 robustness requirement (CE XLSX parsing):**
- Before extracting any shares, WeightsBuilder must run **structural validation** of the CE table XLSX (see `registry/policies/ce_weights_policy_v0_1.json` → `structural_validation`).
- Structural validation is intended to prevent *silent mis-parsing* if BLS changes table layouts year-to-year.
- On hard-fail, the pipeline must stop and emit a clear error (ideally with a short sheet snippet or a pointer to an internal diagnostics artifact).  
Extracts weights from CE published tables using:
- `ce_weights_policy_v0_1.json` and
- `ce_table_to_cpi_mapping_v0_1.json`  
Produces `weights_by_group.parquet`, plus excluded-share diagnostics.

5) **Validator (“Janus”)**

**v0.1.8 clarification (weights vintage review packet algorithm):**
- When `weights_year` changes and the default policy is to FAIL publish, Validator must still be able to generate an internal **weights vintage review packet** (`weights_vintage_review_packet.json`) under `data/outputs/internal/review_packets/{run_id}/`.
- The packet must include (at minimum) a candidate recomputation for at least one period and a deterministic diff summary (see `ce_weights_policy_v0_1.json` → `vintage_change_policy.internal_assist`).  
Runs QA gates:
- hard checks (must pass)
- soft checks (warn / require review)

Special gating in v0.1:
- If `weights_year` changes versus prior published release, default action is **FAIL publish** unless explicitly approved.
- When failing due to weights vintage change, the pipeline may still generate:
  - an **internal backfill candidate** (recomputed outputs with the new weights_year), and
  - a **diff report** (old vs candidate)  
  …but it must not publish automatically.

6) **Synthesizer**  
Builds curated matrices and calls the deterministic calculator.

7) **Publisher**

**v0.1.8 robustness requirements (output contract + schema validation):**
- Publisher must treat `registry/output_contract_v0_1.json` as an executable checklist:
  - Pre-validate that *all required artifacts* can be produced before writing a published release directory.
  - Generate all required files, plus `latest/` aliases, exactly as specified.
- Publisher must validate **schema-bound JSON artifacts** using `jsonschema` (or equivalent) before they are placed under `data/outputs/published/`.
- Publisher must populate `release_metadata.json.outputs[]` with the full published file list and checksums (where feasible).  
Writes outputs (CSV/Parquet/JSON) and **release metadata JSON**, then drafts a short narrative from contribution tables.

### 5.2 Storage abstraction (required)

Pipeline code must treat storage as an abstraction with the four layers:
raw → staging → curated → outputs

Each stored artifact must include:
- checksum
- retrieval/build timestamp
- run_id
- (optional) git SHA

### 5.3 Data quality assurance (category-granularity invariant)

**Hard checks (fail)**
- no duplicate keys for canonical observations
- dates monotonic within a series
- required series present for the requested reference period
- inflation category coverage meets `geo_inflation_policy` rules
- weights non-negative
- weights sum to 1.0 ± tolerance (after exclusions/renormalization)
- excluded share is explicitly tracked (even if zero)
- inflation contributions sum to total π(g,r,t) within tolerance

**Operational definition for `category_coverage_completeness` (v0.1.8):**
- For the computation universe `CPI_MAJOR_GROUPS_V0_1` (from `registry/category_registry_v0_1.json`), CPI level data must exist for **all universe categories** for:
  - the reference period *t*, and
  - the required lag period *(t − horizon_months)* (v0.1 default horizon_months = 12)
- Missing even one required category-period observation is a **hard FAIL** for published releases.

**Schema validation (v0.1.8):**
- Treat schema validation of required JSON artifacts as a hard check (`schema_validation_required_artifacts`).
- Minimum set: `dmi_release.json`, `qa_report.json`, `release_metadata.json`, and (internal-only when triggered) `weights_vintage_review_packet.json`.

**Soft checks (warn)**
- outliers (z-score over trailing window)
- revision detection (hash diff of raw snapshots)
- discontinuities at policy/vintage changes (e.g., weights_year change)

### 5.4 Inflation geography policy (critical constraint)

Because CPI is not published for every state, DMI must follow an explicit deterministic rule for **what inflation series is used for each geo_id**.

v0.1 policy (encoded in `registry/policies/geo_inflation_policy_v0_1.json`):
1. Validate `geo_id` against `registry/geo_registry_v0_1.yaml`.
2. If CPI series exist for `geo_id` **for the full required computation category universe** → use them.
3. Else use **national CPI (US)** as the inflation proxy for that `geo_id`, and set required flags.
4. Optional: BEA RPP can be applied as a **price level** adjustment for cross-place comparisons, but must not be described as “state inflation”.

### 5.5 Slack policy (publish vs research)

Slack selection and alignment are encoded in `registry/policies/slack_policy_v0_1.json`.

Baseline (v0.1 published):
- metric: U‑3
- geo: US national (CPS series)
- time alignment: **same_reference_month_required** (FAIL publish if not satisfiable)

Research / exploration mode (unpublished):
- may use `latest_available_not_after`, but must be explicitly flagged and must not be promoted to the public release channel.

---

## 6. Data sources (PDD section)

Authoritative sources (see `registry/sources_registry_v0_1.yaml`):

- BLS CPI (CPI‑U category index levels)
- BLS Consumer Expenditure published tables (weights by income decile/quintile)
- BLS CPS (national unemployment U‑3; optional U‑6)
- BLS LAUS (state/metro unemployment patterns; future)
- BEA RPP (optional price level adjustment; future)

---

## 7. Web/data publication

v0.1 default: publish precomputed outputs as static assets for a web UI.
- pipeline writes publishable outputs to `data/outputs/published/` (per the output contract)
- pipeline may write internal review artifacts to `data/outputs/internal/` (never deployed)
- web app reads published JSON/CSV from a `/public/data/` folder (or object storage in later versions)

---

## 8. Non-goals and constraints

- **Nonpartisan posture:** descriptive; “visibility, not advocacy”
- **Determinism:** published numbers must be reproducible from pinned inputs
- **Transparency:** no black-box decisions; policies and manifests must explain any fallback/proxy choices
- **Bank OBA compatibility:** publish as public-interest research; avoid providing financial advice or client-specific recommendations

---

## 9. Definition of done (v0.1)

v0.1 is complete when:

- one command produces US DMI by quintile for the latest available month
- all outputs reproducible from raw snapshots + pinned manifest
- QA gate produces PASS/FAIL/WARN plus required policy flags
- release metadata JSON is produced and validates against `release_metadata.schema.json`
- methods note / PDD explain formula + limitations + data sources

---

## 10. Package contents

This spec package ships:
- Implementation plan (this file)
- PDD
- Implementation checklist (v0.1.8) for Antigravity/dev execution
- CE weights/CPI granularity decision rubric
- Pinned manifest (YAML + JSON)
- Source registry, series catalog, geo registry, category registry, category reporting views
- Policies: geo inflation, CE weights, slack
- Mapping artifact: CE table label → CPI category mapping
- Output contract (published + internal review artifacts)
- JSON Schemas:
  - schemas/observation.schema.json
  - schemas/weights.schema.json
  - schemas/crosswalk.schema.json
  - schemas/dmi_output.schema.json
  - schemas/geo_registry.schema.json
  - schemas/ce_table_to_cpi_mapping.schema.json
  - schemas/category_registry.schema.json
  - schemas/category_reporting_views.schema.json
  - schemas/release_metadata.schema.json
  - schemas/output_contract.schema.json
  - schemas/qa_report.schema.json
  - schemas/weights_vintage_review_packet.schema.json
