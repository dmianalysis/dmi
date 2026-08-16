# PR Body Draft — v0.1.12 Repository Repair

**Do not open the PR from this file automatically.** This is a draft the
repository owner can copy verbatim (or edit and copy) into the GitHub PR
creation form when explicitly authorizing the PR to be opened.

**Suggested PR title**:
`repair(v0.1.12): withdraw Core, bump schemas to 3.0.0 / 0.3.0, align presentation surfaces`

**Suggested branch**: `repair/v0.1.12-concept-note-alignment` → `main`

**Do NOT enable**: auto-merge, tag push, GitHub Release publication,
DOI assignment, or live deploy. Those are separate, later, explicit
decisions.

---

## Summary

Repair release bringing the repository into agreement with the v0.1.12
methodology and removing advertised functionality that the code did not
actually implement.

- **Withdraw the Core specification.** No release published under
  v0.1.12 advertises `spec_urls.core`. `specifications.json` no longer
  lists a `core` entry. The pipeline does not emit
  `dmi_release_*_core.json`, `dmi-*-core.csv`, or
  `dmi-*-core.parquet` artifacts. Rationale:
  [`docs/repair/CORE_WITHDRAWAL.md`](../repair/CORE_WITHDRAWAL.md);
  consumer impact:
  [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md).
- **Bump breaking schema versions.** `releases.schema.json`
  **2.0.0 → 3.0.0**; `specifications.schema.json` **0.2.0 → 0.3.0**.
  Both schemas now reject `core` as a `spec_urls` key or `spec_id`.
- **Enforce the Baseline / Slack-Plus identity**:
  `DMI_slackplus(g) − DMI_baseline(g) = U6 − U3` for every group `g`.
- **Enforce manifest coherence and schema conformance** via new
  regression tests.
- **Guard the workflows** so a deploy fails closed if any manifest ever
  regains a `core` URL.
- **Align every presentation surface** (README, CHANGELOG, CITATION,
  LICENSE, docs, WordPress plugin, dashboard, deploy metadata) with the
  actual v0.1.12 state.
- **Purge stale Core / U-6 / with_ci artifacts** from `deploy/`.
- **Prepare — but do not execute** — the remote withdrawal procedure
  for taking the withdrawn artifacts off the live iFastNet site.

## Breaking changes

1. Core specification removed from all public manifests, code, and
   tests. Consumers must migrate to Baseline (or Slack-Plus for broader
   labor slack).
2. `releases.schema.json` → **3.0.0**. `spec_urls` accepts only
   `baseline` (required) and `slack_plus` (optional).
3. `specifications.schema.json` → **0.3.0**. `spec_id` restricted to
   `baseline` and `slack_plus`.
4. Legacy `dmi_release_*_u6.json` and `dmi_release_*_with_ci.json`
   companions are not part of the v0.1.12 published contract.

## Verification (this branch)

- `python -m compileall scripts/ tests/ dmi_calculator/ dmi_pipeline/`
  → clean.
- `pytest tests/` → **46 passed / 5 skipped** (skipped are BLS-network
  CE weight tests). Identity, schema-validation, coherence,
  release-note, calculator, and summary-generator tests all green.
  (**Round 2** extends this to 128 passed / 5 skipped — see the
  Round-2 addendum at the bottom of this document.)
- JSON parse OK: `data/outputs/releases.json`, `latest.json`,
  `specifications.json`, `web/health.json`, `deploy/health.json`,
  `deploy/metadata.json`.
- YAML parse OK: `monthly_dmi.yml`, `deploy_web_dashboard.yml`,
  `deploy_wp_plugins.yml`, `CITATION.cff`.
- Repo-wide `core` / `tcwilliams79` sweeps: only legitimate residual
  matches (withdrawal docs, audit reports, enforcement tests, workflow
  guards, intentional descriptive backticks in CHANGELOG, and frozen
  historical archives).

## Not included in this PR

- No live-server deploy.
- No `v0.1.12` git tag.
- No GitHub Release publication.
- No DOI added to `CITATION.cff` (`date-released` marked placeholder).
- No execution of the remote withdrawal script; the script + procedure
  are checked in but require a separate authorization to run.
- `qa_validator.py` `schema_version` hardcode refactor (deferred to
  a follow-up PR; see §13 P1 dispositions).
- `dmi-latest-info` plugin defensive-check hardening (deferred).
- Housekeeping removal of `dmi-v0.1.10-deployment/` and
  `dmi-v0.1.11-external-deployment/` (deferred).

## Test plan

- [ ] CI: `pytest tests/` on merge target passes (expect 46 passed / 5
      skipped).
- [ ] JSON schema regression tests remain green.
- [ ] Identity + coherence regression tests remain green.
- [ ] Local re-run of `python -m scripts.rebuild_release_manifests` (if
      changed) produces a `releases.json` that still validates against
      `releases.schema.json` 3.0.0 with no `spec_urls.core`.
- [ ] Live-site sanity checks per Step 0 of
      [`docs/repair/REMOTE_WITHDRAWAL.md`](../repair/REMOTE_WITHDRAWAL.md)
      confirm the merged manifests behave as expected.

## Follow-up (post-merge, separate authorization each)

1. Execute the remote withdrawal per
   [`docs/repair/REMOTE_WITHDRAWAL.md`](../repair/REMOTE_WITHDRAWAL.md).
   Backup → withdraw → verify → record.
2. Publish a versioned v0.1.12 GitHub Release (and tag), using
   [`docs/releases/v0.1.12_RELEASE.md`](../releases/v0.1.12_RELEASE.md)
   as the body.
3. Assign / register a DOI, then update `CITATION.cff` (`doi` +
   `date-released`).
4. Follow-up PR: refactor `qa_validator.py` to read `schema_version`
   from a central version constant.

## Commits in this PR

- `3ef6599` docs(repair): Phase 1 alignment audit + inputs (concept note v0.4.6, repair spec)
- `e6989c9` docs(repair): Core-specification output withdrawal record (Phase 2)
- `0ea00eb` chore(repair): quarantine Core-specification artifacts from working tree (Phase 2a)
- `9c35ae9` fix(repair): remove Core code paths from compute_dmi_release.py (Phase 2b)
- `003372d` chore(repair): remove standalone Core script scripts/compute_dmi_core.py (Phase 2e)
- `bc69d54` fix(repair): remove Core from manifest-writing scripts (Phase 2e)
- `90fe1cd` test(repair): update release-note test + warning text for two-spec output (Phase 2e)
- `80b5262` test(repair): investigate specifications.json mixed state + add coherence tests (Phase 2d)
- `2cf6cc0` test(repair): add Baseline+Slack-Plus DMI identity regression tests (Phase 3)
- `353df46` fix(repair): repair release-artifact schemas (Phase 4)
- `4d775ea` fix(repair): bump manifest writers to schema 3.0.0 / 0.3.0 (Phase 4)
- `906391a` build(repair): regenerate manifests + 2026-07 release note under schema 3.0.0 (Phase 4)
- `4f6e8a4` test(repair): add schema-validation regression tests for public manifests (Phase 4)
- `05a2aa2` fix(repair): repair GitHub Actions workflows for two-spec pipeline (Phase 5)
- `22ecf93` docs+data(repair): align presentation surfaces + purge stale artifacts (Phase 6+7)
- `277bb52` docs+scripts(repair): v0.1.12 release note + remote withdrawal procedure (Phase 7)

## Links

- Audit + dispositions:
  [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](../repair/V0.1.12_ALIGNMENT_AUDIT.md)
  (§13 for Round 1, §14 for Round 2 §1-§15 dispositions).
- Release note: [`docs/releases/v0.1.12_RELEASE.md`](../releases/v0.1.12_RELEASE.md).
- Core withdrawal (rationale):
  [`docs/repair/CORE_WITHDRAWAL.md`](../repair/CORE_WITHDRAWAL.md).
- Core withdrawal (consumer impact):
  [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md).
- Remote withdrawal procedure:
  [`docs/repair/REMOTE_WITHDRAWAL.md`](../repair/REMOTE_WITHDRAWAL.md).
- CHANGELOG: [`CHANGELOG.md`](../../CHANGELOG.md#0112---repair-release-unreleased).

---

## Round 2 addendum — §1-§15 repair-prompt dispositions

The following commits extend the branch beyond the Round-1 set above to
close the fifteen defects itemized in
[`docs/DMI_v0.1.12_Repository_Repair_Prompt-2026-08-15.md`](../DMI_v0.1.12_Repository_Repair_Prompt-2026-08-15.md).
Full dispositions are recorded in
[`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](../repair/V0.1.12_ALIGNMENT_AUDIT.md)
§14. Round-2 authorization boundary is unchanged: **local only, no
push, no merge, no tag, no release, no deploy, no remote withdrawal**.

### Round 2 commits

- `d4b0094` fix(repair): remove unpublished concept note file (§1)
- `9bbf99c` fix(repair): lock manifest schema const 3.0.0 + top-level release_note (§2)
- `88f7ca7` fix(repair): repair historical manifest URLs + URL-existence test (§3)
- `e3bc0ff` fix(repair): repair release-note generator (§4)
- `86d586d` fix(repair): deterministic deployment staging rebuild (§5)
- `8a3744e` fix(repair): remove auto-merge; safe dry-run default (§6)
- `7241d9b` fix(repair): repair public timeseries contract + schema (§7)
- `d9e5dfc` fix(repair): lock health endpoints against retired-key resurrection (§8)
- `0ae9d5f` fix(repair): accept zero income_pressure_spread as legitimate (§9)
- `a148b47` feat(repair): add inventory-only withdrawal tool + lock safety posture (§10)
- `772c9f6` fix(repair): remove placeholder date-released from CITATION.cff (§11)
- `07983c9` docs(repair): align operational documentation with v0.1.12 reality (§12)
- `76ec37f` test(repair): add cross-cutting regression coverage (§13)

Round-2 verification gates (§14) all pass:

- `pytest tests/` → **128 passed / 5 skipped** (skipped are BLS-network
  CE weight tests; net delta over Round-1 baseline is +48 tests).
- `python -m scripts.prepare_deployment --verify` idempotent
  (deterministic-rebuild check per §5).
- `python -m scripts.inventory_withdrawn_artifacts` reports the two
  known residual v0.1.10 files in `data/outputs/` (documented in
  audit §14.2) and no new offenders.
- Shipped-manifest schema validation: `latest.json`, `releases.json`,
  `specifications.json`, `web/health.json` all validate.
- All `.github/workflows/*.yml` parse; no workflow calls
  `gh pr merge`; no workflow step is named `auto-merge`.

### Deferrals (non-blocking, tracked in audit §14.2)

- Two v0.1.10 residual files in `data/outputs/` (`dmi_release_2024-05_core.json`
  and its `_u6` sibling) remain on disk but are not referenced by any
  shipped manifest and cannot leak into a deployment because §5's
  staging rebuild + §8's health sanitizer both reject retired names.
- `dmi_pipeline/__version__ = "0.1.0"` is a package-init constant unused
  by any published manifest; consolidation into a single version source
  is deferred to a follow-up.
- `qa_validator.py` `schema_version` hardcode refactor still deferred
  as noted in the Round-1 "Not included in this PR" list.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
