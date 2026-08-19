# Remote Withdrawal Log — 2026-08-19

**Remote-origin withdrawal completed successfully.** All 21 inventoried
Core artifacts were verified absent, and all 15 protected operational
artifacts were verified present. Automated public-HTTP verification from
the GitHub runner was inconclusive because the verification client
received uniform HTTP 403 responses across withdrawn and operational
endpoints. Subsequent normal-browser checks passed. No restoration or CDN
purge was performed.

Machine-readable evidence:
[`docs/repair/evidence/core-withdrawal-2026-08-19/`](evidence/core-withdrawal-2026-08-19/)

---

## Four distinct events

These are separate operations and are not interchangeable. Conflating
them is the specific confusion this log exists to prevent.

| # | Stage | Status |
|---|---|---|
| 1 | **Repository cleanup / quarantine** — Core absent from the tracked tree, manifests, health file and deployment package; U-6 and with-CI files quarantined | **Complete** (v0.1.12 repair, PR #25) |
| 2 | **Production deployment** of the corrected public surface | **Complete** (`deploy_production.yml`, merge commit `e581689`) |
| 3 | **Remote-origin withdrawal** of the 21 legacy Core artifacts | **Complete 2026-08-19** (this log) |
| 4 | **CDN / public-cache verification** | **Verified**; no purge was required or performed |

Stage 3 succeeding does not imply stage 4: a withdrawn URL can keep
returning 200 from cache after the origin file is gone. That did not
happen here — see *Public verification* below.

---

## Authorization and run

| | |
|---|---|
| Workflow | *Execute Core Withdrawal (DESTRUCTIVE — Phase 2)* |
| Run ID | `32214973867` |
| Run URL | https://github.com/dmianalysis/dmi/actions/runs/32214973867 |
| Dispatched commit | `baa2e9e57f83d9436fe9fc1b5e65cae9e4fd8bf4` (merge of PR #28) |
| Event | `workflow_dispatch` |
| Run started (UTC) | 2026-08-19T04:13:38Z |
| Origin post-check (UTC) | **2026-08-19T04:14:49Z** |
| Confirmation phrase | `WITHDRAW-CORE-21-3812991FA2ED52E4` |
| Run conclusion | **failure** — attributable solely to the inconclusive public-HTTP step; see *Why the run is red* |

---

## Controlling inventory

| | |
|---|---|
| Path | `docs/repair/inventories/core-withdrawal-2026-08-19.json` |
| File SHA-256 | `ce1e55939c2c10c04c18cb96b2457db802241f9bdfcdf484438f5250ba84e11c` |
| Internal integrity seal | `3812991fa2ed52e4e3cfcc543c28c3f1769c20a3033c307abdb8085fd1887fd6` |
| Files | 21 |
| Total bytes | 63,598 |
| Remote base | `/home/agiraces/dmianalysis` |

**Pre-execution verification: `verified: true`, `problems: []`.** The seal
recomputed to the recorded value, all 21 paths were unique and sorted, and
every filename matched one of the three Core classes.
Evidence: `pre-execution-verification.json`.

---

## Backup (taken and verified before any deletion)

| | |
|---|---|
| Artifact name | `core-withdrawal-backup` |
| Artifact ID | `9352027951` |
| Artifact URL | https://github.com/dmianalysis/dmi/actions/runs/32214973867/artifacts/9352027951 |
| Downloaded ZIP SHA-256 | `30f35c1e491990db114413f6f05c92894b6a937b8071610eefbb101bbe752d8c` |
| Contained tar.gz SHA-256 | `452a0c2f8d816f2b8fd427bceb9da18f72782a36e23b07e10e4e33a19b19c48a` |
| Backup manifest SHA-256 | `8777454ad92e244cb24939bde9386c5d1cd1f7159f4d42d530bc52572b67a022` |
| Retention | 30 days from 2026-08-19 |

Independently re-verified on 2026-08-19 while preparing this log: the
archive contains exactly the 21 inventoried paths, every archived file
matches the manifest's size and SHA-256, there are no extra entries, and
the manifest is byte-identical between the backup artifact and the
evidence artifact.

The backup archive itself is **not** committed to this repository — it
contains the withdrawn Core artifacts. It lives in the run artifact.

---

## Deletion result

All 21 remote files were re-hashed and matched the sealed inventory
before any deletion. Each of the 21 exact inventoried paths was then
removed, and all 21 were verified absent afterwards. There was **no
partial deletion**.

| Class | Count | Periods |
|---|---|---|
| `dmi_release_<period>_core.json` | 6 | 2024-11, 2026-03 … 2026-07 |
| `dmi-<period>-core.csv` | 5 | 2026-03 … 2026-07 |
| `dmi-<period>-core.parquet` | 5 | 2026-03 … 2026-07 |
| `qa_report_<period>_core.json` | 5 | 2026-03 … 2026-07 |

The 21 exact paths are recorded in the sealed inventory and in
`execution-log.txt`, which contains one `removed <path>` line per file.

### Protected origin surface

```json
{
  "all_operational_present": true,
  "all_withdrawn_absent": true,
  "operational_expected_present": 15,
  "operational_missing": [],
  "withdrawn_expected_absent": 21,
  "withdrawn_still_present": []
}
```

All 15 protected operational artifacts were present and none missing —
including the `_u6` and `_with_ci` legacy files, which are **not** Core,
were outside this authorization, and were untouched.
Evidence: `origin-post-check.json`.

---

## Public verification

### Automated check during the run — inconclusive

The GitHub-hosted Python verifier received **HTTP 403 for all 21
withdrawn URLs, all 11 operational control endpoints, and the public
contract fetch**.

This does not establish public degradation, and it does not establish
withdrawal. Uniform 403 across resources that certainly exist means the
verification client was refused; it says nothing about what the site
serves to anyone else. The verifier correctly refused to treat 403 as
evidence of withdrawal, and correctly failed the step — but it labelled
the operational surface "degraded", which was wrong. That misclassification
is corrected in `scripts/verify_public_surface.py`; see
*Verifier correction*.

Evidence: `public-http-status.json`, `operational-surface.json`.

### Operator browser checks — passed

The operator subsequently performed normal-browser checks and reports
that they passed: operational endpoints were available and correct, and
withdrawn Core endpoints were absent. This is recorded as an **operator
attestation**. No per-URL timestamps or response headers were captured
for it, and none are claimed.

### Independent re-verification, 2026-08-19

While preparing this log, the corrected verifier was run read-only
against the public site from a client the edge serves:

- all **21** withdrawn URLs returned **404** — withdrawal publicly
  demonstrated;
- all **11** operational endpoints returned **200** with valid expected
  content;
- the public contract validated: `current_release_id` is `2026-07`, and
  both `latest.json` and `specifications.json` advertise exactly
  `baseline` and `slack_plus`.

Evidence: `public-http-status-reverification-2026-08-19.json`,
`operational-surface-reverification-2026-08-19.json`.

### Cache status

No withdrawn URL returned 200 at any point, so **no CDN-cache condition
arose and no Cloudflare purge was required or performed.**

---

## Why the run is red

The workflow run is marked *failure*. The deletion succeeded; the public
verification step failed because its result was inconclusive under the
uniform 403. Failing closed on an inconclusive result is the intended
behaviour — a blocked client has proved nothing, and reporting that as
success would be worse than reporting nothing.

**The red run does not indicate a failed, partial, or unsafe withdrawal.**
Origin evidence collected in the same run establishes the opposite.

---

## Verifier correction

`scripts/verify_public_surface.py` now:

- routes every request through one canonical helper with a stable,
  truthful project User-Agent (`dmi-public-verifier/1.0`), GET,
  cache-busting, and captured diagnostic headers;
- classifies uniform refusal across known-good controls as
  `verification_client_blocked` — inconclusive, still non-zero exit,
  and explicitly **not** operational degradation;
- continues to reject 403, 401, 5xx, redirects and network errors as
  evidence of withdrawal;
- asserts operational endpoints return valid expected content rather than
  merely responding;
- enforces the contract rather than merely recording it.

The block was not worked around by impersonating a browser, disabling TLS
verification, accepting 403, or changing Cloudflare.

---

## What did not happen

- **No restoration.** No withdrawn Core file was restored, and the
  withdrawn artifacts are not committed to this repository.
- **No Cloudflare purge**, and none was required.
- **No Core implementation.** Core remains unscheduled, unimplemented,
  unvalidated and non-operational.
- **Baseline and Slack-Plus remained the only operational
  specifications** throughout, before and after.

## Retirement

The destructive Phase-2 workflow (`.github/workflows/execute_withdrawn_core.yml`)
was **retired after this successful execution** and removed from the
active Actions surface, so it can no longer be dispatched. Its
implementation is preserved in Git history and described here. Read-only
verification remains available as
`.github/workflows/verify_core_withdrawal_public.yml`.
