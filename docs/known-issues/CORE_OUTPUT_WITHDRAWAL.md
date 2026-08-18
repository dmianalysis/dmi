# Core-Specification Output Withdrawal Record

**Status:** Withdrawn (local repository); remote withdrawal pending explicit authorization
**Repair branch:** `repair/v0.1.12-concept-note-alignment`
**Phase:** 2 (Core removal from operational paths)
**Record date:** 2026-08-15
**Authority:** `docs/DMI_Concept_Note_v0.4.6_final_v3.1_August_2026.md` §1, §3, §4, §5
**Related:** `docs/repair/V0.1.12_ALIGNMENT_AUDIT.md` (Phase 1 evidence)

---

## 1. Summary

All artifacts labeled as "Core" DMI outputs in this repository — for every reference period
present as of 2026-08-15 — carry metadata that does not match the computation that produced
them. Specifically, the files are stamped with `parameters.inflation_measure = "CORE_CPI"`
and `parameters.excluded_categories = ["CPI_FOOD_BEVERAGES"]`, which asserts that the
calculation excluded food and beverages from the inflation input. The numerical values in
those files show that this exclusion was not performed. The Core-labeled quintile inflation
and DMI values are byte-identical to the Baseline (headline-CPI) outputs for the same
reference period.

Concept note v0.4.6 lists Core as an *intended future companion specification* that is not
implemented or validated for v0.1.12. No repository code path was found that constructs a
food-and-beverages-excluded inflation series or a Core-specific quintile weight matrix
during the run that produced the current outputs.

The withdrawal covers:

- 6 JSON release files (`dmi_release_<period>_core.json`)
- 5 CSV files (`dmi-<period>-core.csv`)
- 5 Parquet files (`dmi-<period>-core.parquet`)
- 5 QA reports (`qa_report_<period>_core.json`)
- All references to the Core specification in `data/outputs/releases.json`,
  `data/outputs/latest.json`, and `data/outputs/specifications.json`

No claim of intent is made or implied. The record documents observed metadata versus
observed values; the mechanism by which the current files were produced is documented in
the audit and are covered by regression tests in `tests/`.

---

## 2. Evidence

### 2.1 Byte-level identity of Core vs Baseline numerics (2026-07)

Direct inspection of `dmi_release_2026-07.json` (Baseline) and `dmi_release_2026-07_core.json`:

| Quintile | Baseline inflation | Core inflation | Baseline DMI | Core DMI |
|:--------:|:------------------:|:--------------:|:------------:|:--------:|
| Q1 | 3.272239 | 3.272239 | 7.372239 | 7.372239 |
| Q2 | 3.352656 | 3.352656 | 7.452656 | 7.452656 |
| Q3 | 3.416957 | 3.416957 | 7.516957 | 7.516957 |
| Q4 | 3.452377 | 3.452377 | 7.552377 | 7.552377 |
| Q5 | 3.442016 | 3.442016 | 7.542016 | 7.542016 |

All six decimals match. The `slack` field in both files is `4.1` (U-3). The distributional
summary metrics (`income_pressure_spread`, `income_pressure_tilt`, `most_pressured_group`,
`least_pressured_group`) are identical between the two files.

If the Core computation had actually excluded food and beverages from CPI, the per-quintile
inflation values could not be identical to Baseline, because food-and-beverages weights
vary across quintiles (a well-known feature of BLS CE data and the reason a Core
specification is worth publishing at all).

### 2.2 Metadata stamped on the same file

From `data/outputs/dmi_release_2026-07_core.json` `parameters` block:

```
spec_id:                core
inflation_measure:      CORE_CPI
slack_measure:          u3
excluded_categories:    ["CPI_FOOD_BEVERAGES"]
```

The `inflation_measure` and `excluded_categories` claims are inconsistent with the values
shown in §2.1.

### 2.3 Code path that stamps the metadata

`scripts/compute_dmi_release.py` (evidence recorded in the Phase 1 audit §5.1):

- Defines `build_core_weights(...)` (audit §5.1 references L215) but never calls it during
  the release build path.
- `load_slack_for_spec(...)` (audit §5.1 references L228) routes `core` → U-3, i.e., the
  same slack input as Baseline (Core would ordinarily still use U-3, so this is not
  independently a defect; it is only noted as evidence that no separate Core-specific data
  input is prepared).
- Sets Core metadata labels only, in a branch (audit §5.1 references L347):
  ```python
  if spec == "core":
      results["parameters"]["inflation_measure"] = "CORE_CPI"
      results["parameters"]["excluded_categories"] = ["CPI_FOOD_BEVERAGES"]
  else:
      results["parameters"]["inflation_measure"] = "HEADLINE_CPI"
  ```

This assigns the Core inflation label after the computation has already used the headline
inputs. The result is a file that carries a Core label without a Core computation.

### 2.4 Legacy Core file (2024-11)

`dmi_release_2024-11_core.json` predates the current parameters schema — `spec_id` and
`slack_measure` are both `null` in that file. It carries the same `inflation_measure:
CORE_CPI` and `excluded_categories: [CPI_FOOD_BEVERAGES]` metadata. Its numerical values
are not byte-compared here (baseline output was regenerated after that period; a
strictly-equal comparison requires care) but the file is included in this withdrawal for
consistency: no v0.1.12-era code path is known to produce a validated Core computation, so
no historical Core file can be considered validated under the v0.1.12 methodology.

---

## 3. Affected artifacts

### 3.1 Files to be quarantined (local repository)

**JSON release files (6):**

- `data/outputs/dmi_release_2024-11_core.json`
- `data/outputs/dmi_release_2026-03_core.json`
- `data/outputs/dmi_release_2026-04_core.json`
- `data/outputs/dmi_release_2026-05_core.json`
- `data/outputs/dmi_release_2026-06_core.json`
- `data/outputs/dmi_release_2026-07_core.json`

**Tabular exports — CSV (5) and Parquet (5):**

- `data/outputs/dmi-2026-03-core.csv`, `dmi-2026-03-core.parquet`
- `data/outputs/dmi-2026-04-core.csv`, `dmi-2026-04-core.parquet`
- `data/outputs/dmi-2026-05-core.csv`, `dmi-2026-05-core.parquet`
- `data/outputs/dmi-2026-06-core.csv`, `dmi-2026-06-core.parquet`
- `data/outputs/dmi-2026-07-core.csv`, `dmi-2026-07-core.parquet`

**QA reports (5):**

- `data/outputs/qa_report_2026-03_core.json`
- `data/outputs/qa_report_2026-04_core.json`
- `data/outputs/qa_report_2026-05_core.json`
- `data/outputs/qa_report_2026-06_core.json`
- `data/outputs/qa_report_2026-07_core.json`

**Total local artifacts to be withdrawn:** 21 files.

### 3.2 References to be removed from manifests

The following manifests advertised the Core spec and its file URLs at
the time of the audit. **They have since been regenerated without it**;
no manifest in the current tree carries a `spec_urls.core` block or a
`core` `spec_id`:

- `data/outputs/releases.json` (per-period `spec_urls.core` blocks)
- `data/outputs/latest.json` (pointer to Core release JSON, if present)
- `data/outputs/specifications.json` (`specifications[].spec_id == "core"` entry)

The 7 release-note HTML files under `data/outputs/releases/` are combined per-period notes
that currently mention Core. They are not per-spec files. Their treatment is:

- 2026-07 release note: regenerate from repaired 2026-07 baseline + slack_plus outputs.
- 2026-03..2026-06 release notes: regenerate in Phase 4 from repaired manifests.
- 2025-12, 2026-01, 2026-02 release notes: reviewed per Phase 4 conservative policy for
  historical periods (Baseline-only, no reconstruction).

### 3.3 Public/remote surfaces

The following remote surfaces are known or expected to serve Core artifacts and will
require withdrawal actions. **Remote actions are deferred pending explicit authorization**
per the repair spec's safety rules. This section enumerates the paths so that the
withdrawal procedure prepared in Phase 7 can act on them:

- iFastNet, path pattern `/home/agiraces/dmianalysis/data/outputs/dmi_release_*_core.json`
  (mirrors §3.1 JSON list).
- iFastNet, path pattern `/home/agiraces/dmianalysis/data/outputs/dmi-*-core.{csv,parquet}`
  (mirrors §3.1 tabular list).
- iFastNet, path pattern `/home/agiraces/dmianalysis/data/outputs/qa_report_*_core.json`
  (mirrors §3.1 QA list).
- iFastNet, `/home/agiraces/dmianalysis/data/outputs/releases.json` and `latest.json` must
  be replaced with the Phase-4 regenerated versions before or at the same time as the
  Core JSON withdrawal.
- iFastNet, `/home/agiraces/dmianalysis/data/outputs/specifications.json` must be replaced
  with the Phase-4 regenerated version.
- WordPress site: the `dmi-release-data` plugin currently reads Core data at plugin path
  `web/wp-plugins/dmi-release-data/dmi_release_data.php` (audit §7 P0 finding). Plugin
  redeployment must land before or with the JSON withdrawal so that visitors do not see
  broken lookups.

No remote action is performed by this record, and none has been
performed since. The withdrawal tooling now exists as
[`scripts/withdraw_remote_artifacts.py`](../../scripts/withdraw_remote_artifacts.py)
— a two-phase inventory/execute tool whose scope is Core artifacts only —
with the operator procedure in
[`docs/repair/REMOTE_WITHDRAWAL.md`](../repair/REMOTE_WITHDRAWAL.md).

**Neither phase has been authorized or executed.** Nothing runs it
automatically. Local repository cleanup is complete; remote withdrawal is
a separate decision that has not been taken.

---

## 4. Remediation plan (this repair)

Ordered to avoid a window in which manifests reference files that have been deleted, or in
which the plugin points at Core files that no longer exist.

1. **This record** (Phase 2, complete on commit): documents the scope and evidence.
2. **Local quarantine, not deletion** (Phase 2): the 21 files in §3.1 are removed from the
   working tree in a dedicated commit. Git history preserves them; no destructive
   history rewrite is performed. This is a repository state change only; no publication
   happens.
3. **Code-path removal** (Phase 2): remove Core from `scripts/compute_dmi_release.py`
   (CLI spec choice, `build_core_weights`, `load_slack_for_spec` Core branch, metadata
   assignment block).
4. **Workflow removal** (Phase 5): remove Core from `.github/workflows/monthly_dmi.yml`
   (spec matrix or per-spec invocation list, artifact-name references, deployment
   references).
5. **Manifest regeneration** (Phase 4): regenerate `releases.json`, `latest.json`,
   `specifications.json` under schema-version 3.0.0 (breaking; Core spec is disallowed).
6. **Public plugin repair** (Phase 6): update `web/wp-plugins/dmi-release-data/dmi_release_data.php`
   to remove Core code paths before any deployment.
7. **Remote withdrawal** (Phase 7, prepared but not executed): withdrawal script
   enumerated in §3.3 for later explicit authorization. No live-server change happens
   inside this repair without that authorization.

---

## 5. Guardrails

Per the repair spec's safety rules and the user's controlling instruction on this repair:

- No merge, tag, GitHub release, deploy, or live-server change is performed by any commit
  on `repair/v0.1.12-concept-note-alignment` without explicit authorization.
- No workflow is triggered by this repair. Where a workflow file is edited, the file is
  audited to confirm it has no auto-run trigger that fires on the branch.
- The concept-note DOI is not added to `CITATION.cff` in this repair (unpublished DOI
  policy per controlling decision 6).

---

## 6. Reversal / dispute path

If a validated Core computation is added in a future repair (v0.1.13 or later), the
withdrawn files remain retrievable through git history for reference. New Core outputs
would be produced by the corrected code path and published under a new specification entry
in `specifications.json` with schema-version 3.0.0 or later. This record is a permanent
part of the repository history and is not superseded by a future publication; it should be
linked from the release notes of the release in which Core is (re)introduced.
