# DMI v0.1.12 repository repair and concept-note alignment

You are working in the GitHub repository `dmianalysis/dmi`. Repair the repository and prepare a reviewable pull request that makes the operational software, release artifacts, schemas, workflows, tests, documentation, and metadata consistent with the unpublished Distributional Misery Index concept note v0.4.6, subject to the explicit implementation-status correction below.

This repository was developed over several interrupted AI-assisted sessions. Assume that partially completed work, stale generated files, contradictory version strings, dead links, obsolete scripts, and code/documentation drift may exist. Do not treat the current implementation, comments, changelog, generated outputs, or draft PR #23 as authoritative merely because they are present.

## Non-negotiable authority order

Resolve conflicts in this order:

1. The decisions and operational boundary stated in this prompt.
2. The final corrected, unpublished DMI concept note v0.4.6, if it is supplied in the working environment.
3. Official source definitions and current schemas expressly adopted by that note.
4. Current tests and implementation, but only where they do not conflict with items 1–3.
5. Older repository documentation, generated artifacts, historical planning files, and prior AI-session outputs.

The v0.4.6 note is the **initial DMI concept note**. Its draft version number reflects prepublication revision; there is no prior published DMI concept note. Do not write “since the prior concept note” or imply that an earlier concept note exists.

The concept note itself is still unpublished and is being corrected separately. Do not edit or version-bump it in this repository unless an explicit local copy is supplied and the user specifically asks you to do so.

## Canonical operational boundary

The designed specification architecture contains Baseline, Slack-Plus, and an intended future Core specification. The **operational v0.1.12 release family contains only Baseline and Slack-Plus**.

| Specification | Status | Definition |
|---|---|---|
| `baseline` | Operational and publishable | Quintile-weighted headline CPI inflation plus shared national U-3 unemployment |
| `slack_plus` | Operational and publishable | The same quintile-weighted headline CPI inflation as Baseline, substituting shared national U-6 labor underutilization |
| `core` | Intended; not implemented, validated, or publishable | A future robustness specification excluding both food and energy, requiring a finer CPI–Consumer Expenditure category mapping |

The current eight-category basket permits direct removal of food but does not isolate energy. Energy is embedded principally within housing and transportation. An ex-food calculation is therefore **not** the specified Core measure. Do not silently relabel ex-food output as Core, do not implement “simplified Core,” and do not publish any current or historical output under the Core label.

The recurring public DMI is national only. State DMI is planned and partially specified, but no state result has been implemented, validated, or published.

The national operational method uses one shared labor-slack value across all five income quintiles. Therefore, within an operational specification, cross-quintile variation—and the current Income Pressure Spread and Income Pressure Tilt—comes from the distributional inflation component. Do not imply that released slack is quintile-specific.

The canonical summary metrics are:

- `dmi_median`: median of the five quintile DMI values.
- `dmi_stress`: maximum of the five quintile DMI values.
- `income_pressure_spread`: `max(DMI) - min(DMI)`, always nonnegative.
- `income_pressure_tilt`: `DMI(Q1) - DMI(Q5)`, signed; positive means Q1 is more pressured than Q5.
- `most_pressured_group` and `least_pressured_group`: actual extrema across all five quintiles, not assumed endpoints.

The retired `income_pressure_gap` field must not appear in the current public schema or newly generated current artifacts. Do not rewrite genuinely frozen historical source artifacts merely to erase history; distinguish frozen legacy data from current public contracts.

## Safety and change-control rules

- Start from the latest `main` after fetching all remotes. Create a new repair branch such as `repair/v0.1.12-concept-note-alignment`.
- Read any `AGENTS.md`, `CONTRIBUTING.md`, workflow instructions, and repository-local development rules before changing files.
- Inspect the dirty state before editing. Preserve unrelated user changes.
- Do not merge, tag, create a GitHub release, deploy to `dmianalysis.org`, upload through SSH/rsync, or allow a workflow to auto-merge during this task.
- Do not expose or print secrets. Do not require live BLS or hosting credentials for tests.
- Do not delete or rewrite evidence merely because it is inconsistent. Git history preserves deleted files, but any withdrawal or quarantine of public artifacts must also be documented.
- Do not merge draft PR #23 as written. It assumes three operational specifications and publishes Core. Salvage its useful deferred-release-note and deployment-hardening ideas only after adapting them to the two-spec operational boundary.
- If an ambiguity would alter published values, historical provenance, schema compatibility, or live deployment behavior, stop and document it rather than inventing an answer.

## Phase 1 — Inventory before editing

Run a repository-wide audit and save the findings in `docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`. At minimum, inventory:

1. Every executable path that can compute, label, register, package, deploy, display, or link a Core result. Search code, tests, workflows, dashboards, WordPress plugins, schemas, manifests, documentation, deployment directories, and old deployment-package directories.
2. Every Core-labeled generated file and the periods it purports to cover. Determine whether it is identical to Baseline, ex-food, or something else; do not infer validity from its filename or metadata.
3. Every active Baseline and Slack-Plus artifact, including JSON, CSV, Parquet, QA, manifest, release-note, dashboard, and deployment references.
4. Every advertised URL in `releases.json`, `latest.json`, `specifications.json`, web code, and documentation; determine whether its target exists in the repository and intended deployment package.
5. Schema/instance mismatches, especially whether `release_note` is incorrectly required for every specification while only the Baseline release has one shared human-readable note.
6. Version and date drift among `METHODOLOGY_VERSION`, schemas, `README.md`, `CHANGELOG.md`, `CITATION.cff`, health files, deployment metadata, dashboards, and documentation.
7. Remaining `tcwilliams79/dmi` references. Distinguish active references that must become `dmianalysis/dmi` from immutable historical records or frozen old packages that should instead be clearly labeled archival.
8. Syntax, import, or compile errors, including the known broken/empty `if __name__ == "__main__":` block in `scripts/backfill_releases.py`.
9. The behavior of `.github/workflows/monthly_dmi.yml`, including manual-dispatch defaults, scheduled-period derivation, live deployment, PR creation, and auto-merge.
10. Draft PR #23 and issue #21. Record which changes remain useful under a two-spec model and which must be rejected or rewritten.

For each inconsistency, record: affected files, present behavior, required behavior, proposed repair, compatibility/provenance implications, and verification method. Complete this audit before broad mechanical edits.

## Phase 2 — Remove Core from all operational paths

Make Core impossible to produce or advertise accidentally:

- Remove `core` from operational CLI choices, workflow matrices/steps, specification orders, active registries, manifest builders, release URL builders, dashboards, release notes, deployment packaging, and current API examples.
- Remove or disable `build_core_weights()` and any equivalent active ex-food computation path. If retaining a legacy entry point for compatibility, it must fail loudly with a clear message that Core is withheld and must not create files.
- Remove obsolete executable scripts such as a legacy Core calculator from active documentation and workflows. It is acceptable to remove dead code because Git preserves history; do not leave an apparently supported command that emits a mislabeled result.
- Ensure the monthly workflow cannot generate `*_core.*`, `dmi_release_*_core.json`, Core QA output, or a Core manifest entry.
- Ensure `specifications.json` means the **active operational specifications** and contains only Baseline and Slack-Plus.
- Add regression tests that fail if newly generated manifests, deployment packages, release notes, or workflow commands contain an operational Core entry or Core artifact URL.
- Open or prepare the text for a separate future issue describing the work required for defensible Core: finer CPI and Consumer Expenditure taxonomy, explicit food and energy component mappings, source-series validation, weights, concordance, QA, backfill policy, and methodology review. Do not implement that extension in this repair.

### Existing Core-labeled artifacts

Treat existing Core-labeled files as withdrawn/invalid, not as valid historical releases.

- Remove them from active manifests, `latest.json`, dashboards, APIs, release notes, deployment inputs, and documentation.
- Do not rename them to `ex_food`, because their actual provenance and computation must first be established.
- Quarantine them outside active public/deployment paths only if doing so improves clarity; otherwise remove them from the working tree and rely on Git history. In either case, create a concise withdrawal record such as `docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md` listing affected periods/paths, the reason for withdrawal, and the fact that no valid operational Core series currently exists.
- Do not publish reconstructed Core values.
- Ensure old generated deployment directories cannot reintroduce withdrawn Core artifacts into a new package. Clearly identify any frozen v0.1.10 package as archival and exclude it from v0.1.12 build inputs.

## Phase 3 — Make Baseline and Slack-Plus internally coherent

Verify and repair the two operational computations:

### Baseline

- Uses quintile-specific Consumer Expenditure weights with the adopted headline CPI category series.
- Uses shared national U-3 for all five quintiles.
- Uses `alpha = 0.5` and `scale_factor = 2.0`, which is numerically inflation plus slack.
- Produces all canonical summary metrics correctly.

### Slack-Plus

- Uses exactly the same inflation inputs and quintile weights as Baseline for the same period and vintage.
- Substitutes shared national U-6 for shared national U-3.
- Records the slack measure and value transparently in output metadata.
- Does not change Income Pressure Spread, Income Pressure Tilt, most-pressured group, or least-pressured group relative to Baseline except for a genuine tie/rounding rule that is explicitly tested and documented. It should shift each quintile’s DMI by the common `U-6 - U-3` amount.

Add deterministic regression tests for these identities and for the extrema/endpoint distinction: a fixture with an interior maximum must prove that `dmi_stress` and `most_pressured_group` inspect all five quintiles, while `income_pressure_tilt` remains Q1 minus Q5.

Ensure QA receives the exact effective inputs used by each computation. Do not validate one weight/slack object while calculating with another.

## Phase 4 — Repair manifests, schemas, historical indexes, and release notes

Establish one coherent contract for new v0.1.12 releases:

1. Compute Baseline.
2. Compute Slack-Plus.
3. Run specification-level QA and cross-specification invariants.
4. Build the two-spec `specifications.json` manifest.
5. Generate one Baseline-owned, specification-aware human-readable release note after both operational outputs and the manifest exist.
6. Update `releases.json`, `latest.json`, health, timeseries, and deployment staging only after required checks pass.

Adapt the useful deferred-generation work from PR #23 to this sequence. The release note may include a two-row comparison table labeled “Comparison across operational specifications” or equivalent. If the cross-specification invariants fail, generation/deployment should fail rather than normalize the inconsistency as an ordinary robustness result.

Schema and URL requirements:

- Separate Baseline-owned shared URLs, such as the human release note, from per-specification data URLs. Do not require or advertise duplicate Slack-Plus release-note pages when none exist.
- Every URL emitted by an active manifest must resolve to a file included in the intended deployment tree.
- `latest.json` must contain exactly one current release and agree with the matching entry in `releases.json` and the raw Baseline release metrics.
- Validate every generated JSON instance against its declared schema.
- Preserve the distinction among methodology version, individual schema versions, document version, reference period, data vintage, computation timestamp, and publication date.

### Historical public releases

Be conservative with incomplete historical companions:

- Do not advertise Slack-Plus CSV/Parquet/JSON URLs for periods where those files do not actually exist.
- For a historical release without a validated Slack-Plus companion, keep the valid Baseline entry and omit the unavailable companion comparison. A note may state that the companion was not published for that release.
- Do not create an in-memory reconstruction solely to populate a table while leaving linked artifacts absent.
- Do not backdate a newly reconstructed artifact or imply it was part of the original release. If the user later authorizes reconstruction, it will need explicit reconstruction metadata, current computation time, source/method versions, and a separate validation decision.
- Make backfill and manifest-rebuild scripts idempotent and incapable of reintroducing Core or nonexistent URLs.

## Phase 5 — Repair the scheduled workflow without triggering production

Update `.github/workflows/monthly_dmi.yml` and related deployment workflows so the scheduled path follows the two-spec sequence above.

Requirements:

- Remove the Core computation step.
- Build the two-spec manifest and deferred note only after Baseline and Slack-Plus succeed.
- Fail if required artifacts are absent, schemas fail, manifests disagree, or any Core artifact is staged for deployment.
- Derive the scheduled reference period deterministically. Remove stale hard-coded manual defaults; an explicit manual period must be honored, while an omitted input should use a clearly documented rule.
- Preserve the intended August monthly schedule behavior, but do not run the live workflow as a test.
- Keep deployment and auto-merge disabled during local/repair validation. Add or document a safe offline/dry-run path that exercises computation, QA, manifest, note, and package assembly without SSH, rsync, GitHub PR creation, merge, or external writes.
- Ensure release-note files are required rather than copied with failure suppressed.
- Ensure a stale `specifications.json` for another reference period causes a hard failure.
- Parse/validate all modified YAML.

## Phase 6 — Documentation, metadata, and version cleanup

Bring active documentation into agreement with the repaired v0.1.12 state:

- `README.md`: current version and scope; national-only implementation; Baseline and Slack-Plus operational; Core intended and withheld; current commands and file patterns; new repository URL.
- `docs/DMI_Methodology_Note.md`: either update it accurately to the v0.1.12 operational method or clearly replace its authority with a concise technical implementation note aligned to the concept note. Do not present an obsolete v0.1.9 document as current.
- `docs/API.md`: current schemas, filenames, metrics, examples, and only real operational endpoints.
- `docs/Alternative_Specifications.md`: two operational specifications plus a clearly labeled future Core section. Remove claims that Core or an ex-food proxy is implemented.
- Deployment, release-calendar, dashboard, plugin, and contribution documentation: current paths, owner, sequence, and status.
- `CHANGELOG.md`: add an accurate release date only when known; state that invalid Core outputs were withdrawn and that v0.1.12 is a pre-1.0 exceptional breaking public-schema release. Do not fabricate retroactive tags for v0.1.9–v0.1.11.
- `CITATION.cff`: software version `0.1.12`, `dmianalysis/dmi`, accurate description, and actual release date only when the release occurs. Remove claims of operational Core and unsupported current coverage. Add the concept note DOI `10.5281/zenodo.21881671` as a preferred citation only if the corrected concept note has actually been published and the DOI resolves; otherwise leave a documented final-release TODO rather than citing an unpublished draft as published.
- `deploy/metadata.json`, health metadata, and any active generated metadata: current repository owner, correct version, accurate coverage, and no stale v0.1.10 claims.

Do not claim that bootstrap confidence intervals, historical coverage, a state method, or any other feature is operational merely because old files or prose mention it. Verify every current feature claim against executable code, tests, and deployable artifacts.

## Phase 7 — Verification gates

Run verification from a clean checkout or clean worktree using supported project dependencies. At minimum:

```bash
python -m compileall dmi_calculator dmi_pipeline scripts tests
pytest -q
git diff --check
```

Also add and run checks that prove:

1. Baseline and Slack-Plus calculate successfully from fixture/staged test inputs without network access.
2. Slack-Plus differs from Baseline only by the common slack substitution for a given period and inflation profile.
3. New outputs contain all canonical summary metrics and no current `income_pressure_gap`.
4. No operational code path accepts or emits `core`.
5. New release manifests and deployment packages contain no Core entry or Core URL.
6. Every active manifest URL points to a packaged file.
7. Historical entries do not advertise missing companion artifacts.
8. `releases.json`, `latest.json`, raw release output, and `specifications.json` agree on period, methodology, specification identities, and metrics.
9. All JSON instances validate against their declared schemas.
10. `CITATION.cff` validates.
11. Modified workflows parse as YAML and the offline release path completes without live deployment or GitHub mutation.
12. Repository-wide searches find no active claim that Core is implemented/published and no active `tcwilliams79/dmi` URL. Any retained archival occurrences must be enumerated and justified in the audit.

If the full test suite has pre-existing failures unrelated to this repair, do not suppress them. Report the exact failures, identify whether they are pre-existing, and add a bounded fix only when it is safe and relevant.

## Required deliverables

Produce a reviewable branch and draft pull request, but do not merge it. The PR should contain:

1. The implementation, schema, workflow, artifact, and documentation repairs.
2. `docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`, updated from proposed to actual disposition.
3. `docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md` or an equivalent withdrawal record.
4. A concise `docs/releases/v0.1.12_RELEASE.md` describing the cumulative release since v0.1.8, the breaking schema change, the Core withdrawal, compatibility implications, and remaining release gates.
5. Tests and a machine-checkable validation command or script suitable for reuse before each monthly release.

In the final handoff, report:

- branch name and commit SHA;
- PR URL if created;
- files changed, removed, or quarantined;
- exact historical periods affected by withdrawn Core or missing Slack-Plus artifacts;
- schema/version changes and compatibility consequences;
- test and validation commands with exact results;
- anything not completed and why;
- safe manual steps remaining before the August scheduled run and before tagging `v0.1.12`.

Do not declare the repository release-ready merely because tests pass. It is release-ready only when the implementation, published status claims, generated artifacts, active URLs, schemas, documentation, and deployment workflow all agree with the canonical operational boundary above.
