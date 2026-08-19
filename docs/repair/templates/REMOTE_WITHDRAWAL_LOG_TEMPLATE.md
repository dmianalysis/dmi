# Remote Withdrawal Log — <YYYY-MM-DD>

> **TEMPLATE — NOT A RECORD OF AN EXECUTED RUN.**
> Copy to `docs/repair/REMOTE_WITHDRAWAL_LOG_<date>.md` and fill in from
> the `core-withdrawal-evidence` artifact **after** a real Phase-2 run.
> Every `<…>` placeholder must be replaced with an observed value. Do not
> pre-fill an outcome.

## Four distinct states

These are separate operations and must never be conflated in this log:

| Stage | What it means | Status |
|---|---|---|
| 1. Repository cleanup | Core absent from the tracked tree, manifests, health, deployment package | Complete (v0.1.12 repair, merged) |
| 2. Production deployment | Corrected artifacts uploaded to the origin server | Complete (`deploy_production.yml`, run `<run-id>`) |
| 3. Remote-origin withdrawal | The 21 withdrawn Core files deleted from origin disk | `<not executed / executed on <date>>` |
| 4. CDN-cache removal | Cloudflare no longer serving cached copies | `<not required / required / purged on <date>>` |

Stage 3 succeeding does **not** imply stage 4. A withdrawn URL can keep
returning 200 from cache after the origin file is gone.

## Authorization

- Authorized by: `<name>`
- Date/time (UTC): `<timestamp>`
- Workflow run: `<url>`
- Confirmation phrase supplied: `WITHDRAW-CORE-21-3812991FA2ED52E4`
- Environment approval (`core-withdrawal`) granted by: `<name>`

## Inventory consumed

- Path: `docs/repair/inventories/core-withdrawal-2026-08-19.json`
- File SHA-256: `ce1e55939c2c10c04c18cb96b2457db802241f9bdfcdf484438f5250ba84e11c`
- Internal seal (`integrity_sha256`): `3812991fa2ed52e4e3cfcc543c28c3f1769c20a3033c307abdb8085fd1887fd6`
- Files: 21 · Total bytes: 63,598
- Remote base: `/home/agiraces/dmianalysis`
- Seal recomputed at run time: `<yes/no>`

## Backup (taken before deletion)

- Artifact name: `core-withdrawal-backup`
- Artifact ID: `<id>` · URL: `<url>` · Digest: `<digest>`
- Archive SHA-256: `<sha256>` · Retention: 30 days
- Every file verified against the inventory by size and SHA-256: `<yes/no>`

## Deleted paths (exactly 21)

| # | Remote path | Size | SHA-256 |
|---|---|---|---|
| 1 | `<path>` | `<bytes>` | `<sha256>` |
| … | | | |

*(Transcribe from the inventory in the evidence artifact — do not retype
from memory.)*

## Execution result

- Tool: `python -m scripts.withdraw_remote_artifacts execute --inventory <path> --confirm`
- Seal revalidated: `<yes/no>`
- Scope revalidated: `<yes/no>`
- All 21 re-hashed and matching before deletion: `<yes/no>`
- Deletions reported: `<n>`
- Post-deletion absence verified for all 21: `<yes/no>`
- Result: `<success / failed / partial>`

If **partial**: stop. Record the exact state below and take no recovery
action without separate authorization.

- Deleted: `<paths>`
- Still present: `<paths>`

## Origin post-check

- All 21 withdrawn paths absent: `<yes/no>`
- Baseline / Slack-Plus raw, CSV, Parquet present: `<yes/no>`
- Manifests, release notes, health, timeseries present: `<yes/no>`
- `_u6` / `_with_ci` unchanged from pre-run status: `<yes/no>`

## Public HTTPS verification (cache-busted)

- Operational endpoints returning 200: `<n>/<n>`
- Withdrawn Core URLs returning 404/410: `<n>/21`
- Withdrawn Core URLs still returning 200: `<n>`
- `CF-Cache-Status` observed: `<values>`

If any withdrawn URL still returns 200 **while the origin file is
absent**, this is a CDN-cache condition, not a failed deletion. Record it
here and do not restore files.

- Cloudflare purge required: `<yes/no>`
- Purge authorized by: `<name / not authorized>`
- Purge performed: `<date / not performed>`

## Public contract after withdrawal

- `releases.json` / `latest.json` advertise only `baseline` + `slack_plus`: `<yes/no>`
- `specifications.json` spec_ids: `<list>`
- Current release remains `2026-07`: `<yes/no>`
- Dashboard renders: `<yes/no>`

## Evidence artifact

`core-withdrawal-evidence` — ID `<id>`, retention 90 days, containing the
reviewed inventory, backup manifest, pre-execution verification report,
execution log, origin post-check, public HTTP status report and
operational-surface report. It contains no credentials, SSH
configuration, key material or known-hosts contents.
