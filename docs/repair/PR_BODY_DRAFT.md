# PR body draft — `repair/v0.1.12-concept-note-alignment`

**Draft only. This PR has not been opened.** Paste the body below when
opening it.

This document describes the **final state of the branch**. Earlier
revisions accumulated one section per repair round, which meant a reader
had to reconstruct the current state from a chronology and mentally
discard superseded claims. The per-round history lives in
`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`,
which is the right place for it.

---

<!-- ==================== PASTE FROM HERE ==================== -->

## Title

```
repair(v0.1.12): withdraw Core, gate release publication, centralise deployment authority
```

## Summary

This branch aligns the repository with the v0.1.12 concept note and
closes the defects found by three independent reviews.

The v0.1.12 published contract is **two operational specifications**:
**Baseline** (U-3, headline CPI) and **Slack-Plus** (U-6, headline CPI).
**Core is withdrawn** — it was documented but never implemented as a
bona fide core-inflation calculation, and the files that shipped under
its name were Baseline outputs relabelled. See
`docs/repair/CORE_WITHDRAWAL.md`.

### Release publication is now transactional

Publication used to happen *during* computation: computing Baseline
wrote `releases.json`, `latest.json`, `web/health.json` and the public
timeseries as a side effect, before Slack-Plus had been computed and
before anyone had looked at QA. The workflow's QA step validated that
reports were well-formed JSON — never that they had passed.

`scripts/finalize_release.py` now enforces the order: validate both raw
outputs, validate both QA reports, enforce QA **outcome** policy, enforce
the Baseline/Slack-Plus identity gate, and only then publish the tabular
exports, the three manifests, the release note, the timeseries,
`health.json` and the deployment staging tree — as one transaction. On
any failure the whole public surface is restored byte-for-byte.

### Exactly one workflow can deploy

Three workflows previously carried their own `push: branches: [main]`
trigger, so one merge started three runs that could each independently
upload to the live site.
`.github/workflows/deploy_production.yml`
is now the sole orchestrator and the only workflow with an automatic push
trigger. It decides authorization once and passes it explicitly to its
components.

### Host authentication is pinned

Deployment previously trusted whatever `ssh-keyscan` returned at deploy
time. That is trust-on-first-use on every run: `ssh-keyscan` asks whoever
answers the connection to introduce itself and believes the reply.
`scripts/install_known_hosts.py` now installs host material supplied out
of band through the `IFASTNET_KNOWN_HOSTS` secret and validates it
against the host and port actually being contacted.

---

## What happens when this PR is merged

These are four distinct events. Only the first two are automatic.

| Stage | Trigger | Status |
|---|---|---|
| **PR preparation** | This branch, pushed | **Done.** Nothing was deployed. |
| **Merge to `main`** | A reviewer merging this PR | Not done — awaiting review. |
| **Production deployment** | Automatic, on the merge commit, via `deploy_production.yml` | **Will occur on merge.** |
| **Remote artifact withdrawal** | A separately authorized manual run | **Not authorized, not executed.** |

Merging this PR **will deploy to the live site**, from the merged commit,
through the single authoritative deployment workflow. That is the
intended design — production deploys only reviewed, merged artifacts —
but it means the merge is the deployment decision. Review the staged
surface before merging.

**Remote withdrawal is not part of the merge.** Deleting the withdrawn
Core artifacts that already sit on the live server is a separate,
explicitly authorized, two-phase operation documented in
`docs/repair/REMOTE_WITHDRAWAL.md`. Neither phase
has been run. Merging this PR does not run it.

---

## Scope of change

**Release path**
- `scripts/finalize_release.py` — transactional finalization (new)
- `scripts/release_policy.py` — QA outcome + cross-specification gates (new)
- `scripts/release_evidence.py` — single evidence-based manifest writer (new)
- `scripts/compute_dmi_release.py` — computes only; publishes nothing
- `schemas/qa_report.schema.json` — optional `subject` binding a report to
  the artifact bytes and specification it describes

**Deployment**
- `.github/workflows/deploy_production.yml` — sole production authority
- `.github/workflows/deploy_wp_plugins.yml` — reusable component
- `.github/workflows/deploy_web_dashboard.yml` — manual maintenance only
- `scripts/prepare_deployment.py` — adds the `wp-plugins` component, so
  plugin staging is no longer a separate hand-built tree
- `scripts/install_known_hosts.py` — pinned host authentication (new)

**Withdrawal**
- `scripts/withdraw_remote_artifacts.py` — two-phase, sealed inventory,
  Core-only scope, pinned host material
- `data/quarantine/pre_v0.1.12/` — U-6 and confidence-interval artifacts,
  which are **not** Core and are outside the withdrawal authorization

**CI**
- `.github/workflows/pr_ci.yml` — read-only PR checks (new)

**Documentation**
- `docs/repair/CORE_WITHDRAWAL.md`, `docs/DMI_Methodology_Note.md`,
  `docs/repair/REMOTE_WITHDRAWAL.md`,
  `docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`

---

## Manifest schema versions

Two of the three manifests are at `3.0.0` and one is at `0.3.0`, by
design:

| Manifest | `schema_version` |
|---|---|
| `data/outputs/releases.json` | `3.0.0` |
| `data/outputs/latest.json` | `3.0.0` |
| `data/outputs/specifications.json` | `0.3.0` |

`specifications.json` is a separately versioned contract. It is not
lagging and is not scheduled to be renumbered to match the other two.

## Citation metadata

`CITATION.cff` deliberately carries **no** `doi` and **no**
`date-released`. The concept note is unpublished and has no DOI to cite,
and there is no v0.1.12 tag yet — a `date-released` would be asserting a
release date for something not released. Both are added when a real tag
is cut, not before.

---

## Disclosure: staged U-6 data was extended during development

While regenerating the QA reports so they carry a `subject` binding, the
generator found the staged U-6 file covered only through 2026-03 although
releases existed through 2026-07, and fetched the gap.

- Source series: BLS U-6, `LNS13327709`
- Retrieved: August 18, 2026
- Observations added to `data/staging/slack_u6_2025_2026.json`:

  | Period | U-6 |
  |---|---|
  | 2026-04 | 8.2 |
  | 2026-05 | 8.1 |
  | 2026-06 | 7.9 |
  | 2026-07 | 7.9 |

- Each value **exactly matches** the Slack-Plus value already present in
  the corresponding published raw release, so no published figure
  changed and the corresponding published raw releases were left
  unchanged.
- No previously staged period was modified; the change is purely
  additive.
- It closes the prior offline-staging gap: fixture validation no longer
  needs to fetch these observations.
- The network fetch was an unintended development-time side effect. It
  contacted the BLS public API only. **No production host was
  contacted.**

## Pre-merge requirement: `IFASTNET_KNOWN_HOSTS`

**This must be configured before merging.**

- `IFASTNET_KNOWN_HOSTS` must exist as a GitHub Actions secret,
  containing **independently verified** host material for the configured
  deployment host on **port 1394** — obtained from the hosting control
  panel or a known-good prior session, never by scanning the host being
  authenticated.
- **Merging this PR automatically triggers production deployment** from
  the merged commit.
- If the secret is absent, empty, malformed, or issued for a different
  host or port, deployment **fails closed**: `scripts/install_known_hosts.py`
  refuses to proceed and there is no fallback that acquires trust
  dynamically. Nothing is uploaded.

## Reviewer checklist

- [ ] Baseline vs Slack-Plus values are reasonable for the period.
- [ ] QA warnings (weights vintage, Q5>Q1 pattern) have been triaged.
- [ ] The staged surface in the workflow log lists every expected
      endpoint.
- [ ] No Core, `_u6` or `_with_ci` artifact appears in `deploy/`.
- [ ] CI is green. The expected pass/skip counts are recorded in the
      Round-4 verification snapshot in
      `docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`; check
      against that rather than against any number quoted in an older
      document.
- [ ] `IFASTNET_KNOWN_HOSTS` is configured with independently verified
      host material for the deployment host on port 1394.
- [ ] You accept that merging deploys to production.

---

## What this PR does not do

No deployment has occurred. No remote withdrawal has been authorized or
executed. No tag, no release, no history rewrite. The frozen
`dmi-v0.1.10-deployment/` archive is untouched. Core is **not**
implemented — it remains unscheduled, unimplemented, unvalidated and
non-operational.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
