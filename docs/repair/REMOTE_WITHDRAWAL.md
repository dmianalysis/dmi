# Remote Withdrawal Procedure — v0.1.12 Core Artifacts

**Status**: **NOT EXECUTED.** This document specifies the commands and
verification steps that would remove withdrawn Core artifacts from the
live iFastNet site. Do not run any of the commands below without
explicit, contemporaneous authorization from the repository owner. The
repair PR must be merged first.

---

## Scope

Withdraw from the live site (`https://dmianalysis.org/`) the artifacts
that v0.1.12 no longer advertises, so that the on-disk state at
`agiraces@…:/home/agiraces/dmianalysis/` matches the v0.1.12 published
contract (Baseline + Slack-Plus only).

### Files to withdraw

| Live URL                                                                | Remote path (iFastNet)                                                     |
|-------------------------------------------------------------------------|----------------------------------------------------------------------------|
| `/data/outputs/dmi_release_YYYY-MM_core.json` (every historical month)  | `/home/agiraces/dmianalysis/data/outputs/dmi_release_YYYY-MM_core.json`    |
| `/data/outputs/dmi-YYYY-MM-core.csv`                                    | `/home/agiraces/dmianalysis/data/outputs/dmi-YYYY-MM-core.csv`             |
| `/data/outputs/dmi-YYYY-MM-core.parquet`                                | `/home/agiraces/dmianalysis/data/outputs/dmi-YYYY-MM-core.parquet`         |
| `/data/outputs/dmi_release_YYYY-MM_u6.json` (legacy naming, if present) | `/home/agiraces/dmianalysis/data/outputs/dmi_release_YYYY-MM_u6.json`      |
| `/data/outputs/dmi_release_YYYY-MM_with_ci.json` (legacy, if present)   | `/home/agiraces/dmianalysis/data/outputs/dmi_release_YYYY-MM_with_ci.json` |

### Files to leave in place

- `dmi_release_YYYY-MM.json` (Baseline)
- `dmi_release_YYYY-MM_slack_plus.json` (Slack-Plus)
- `dmi-YYYY-MM-baseline.{csv,parquet}`
- `dmi-YYYY-MM-slack_plus.{csv,parquet}`
- `releases.json`, `latest.json`, `specifications.json`, `health.json`
- Everything under `data/outputs/published/historical/`
- Everything under `dashboard/`

### Files to update

- `releases.json`, `latest.json` (already contain no `spec_urls.core`
  after Phase 4 rebuild — verify).
- `specifications.json` (already contains no `core` `spec_id` after
  Phase 4 rebuild — verify).
- `health.json` (already regenerated — verify no `latest_core` /
  `latest_u6` / `timeseries` endpoints).

The next successful run of `monthly_dmi.yml` will rsync the current
manifests over the top; nothing here manually rewrites JSON on the
server.

---

## Authorization gate

Do not proceed unless **all** of the following are true:

1. The repair PR (branch `repair/v0.1.12-concept-note-alignment`) is
   merged into `main`.
2. The repository owner has issued explicit contemporaneous authorization
   for the remote withdrawal ("execute the remote withdrawal script for
   v0.1.12" or equivalent).
3. A recent, verified backup of `/home/agiraces/dmianalysis/data/outputs/`
   is available. The pre-withdrawal snapshot below produces that
   backup.

---

## Prerequisites

- SSH key at `~/.ssh/deploy_key` matching the iFastNet deploy user (same
  key used by `monthly_dmi.yml`).
- Host / user / port matching `IFASTNET_SSH_HOST`,
  `IFASTNET_SSH_USER`, and port `1394` from the workflow secrets.
- Local checkout on the merged `main` commit.

Set environment variables in the local shell (do **not** commit them):

```bash
export DMI_REMOTE_HOST="<IFASTNET_SSH_HOST>"
export DMI_REMOTE_USER="<IFASTNET_SSH_USER>"
export DMI_REMOTE_PORT=1394
export DMI_REMOTE_KEY="$HOME/.ssh/deploy_key"
export DMI_REMOTE_BASE="/home/agiraces/dmianalysis"
```

---

## Step 0 — Pre-withdrawal verification (read-only)

Confirm current published state before touching anything.

```bash
# Live manifests currently advertise no Core:
curl -sS https://dmianalysis.org/data/outputs/releases.json |
  jq '[.releases[] | select(.spec_urls|has("core"))] | length'
# Expected: 0

curl -sS https://dmianalysis.org/data/outputs/latest.json |
  jq '[.releases[] | select(.spec_urls|has("core"))] | length'
# Expected: 0

curl -sS https://dmianalysis.org/data/outputs/specifications.json |
  jq '[.specifications[] | select(.spec_id=="core")] | length'
# Expected: 0

curl -sS https://dmianalysis.org/health.json |
  jq 'has("latest_core"), has("latest_u6"), has("timeseries")'
# Expected: false false false
```

If any of the above is non-zero / non-false, **stop** and investigate:
the manifests on the server disagree with the merged v0.1.12 state.

Confirm the withdrawn files themselves still exist on the server
(so we know the withdrawal has something to do):

```bash
ssh -i "$DMI_REMOTE_KEY" -p "$DMI_REMOTE_PORT" \
  "$DMI_REMOTE_USER@$DMI_REMOTE_HOST" \
  "ls -la $DMI_REMOTE_BASE/data/outputs/ | grep -E '_core\\.json$|-core\\.(csv|parquet)$|_u6\\.json$|_with_ci\\.json$' || true"
```

Expected: a list of the files enumerated in the "Files to withdraw"
table (or empty, if the site has already been cleaned).

---

## Step 1 — Backup

Snapshot the remote `data/outputs/` tree before any deletion.

```bash
BACKUP_DIR="./backup-preremoval-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

rsync -avz \
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=no" \
  "$DMI_REMOTE_USER@$DMI_REMOTE_HOST:$DMI_REMOTE_BASE/data/outputs/" \
  "$BACKUP_DIR/"

# Verify backup includes withdrawn artifacts:
find "$BACKUP_DIR" -type f \( \
    -name '*_core.json' -o \
    -name '*-core.csv' -o \
    -name '*-core.parquet' -o \
    -name '*_u6.json' -o \
    -name '*_with_ci.json' \
  \)
```

If the backup is missing files that Step 0 saw on the server, **stop**.

---

## Step 2 — Withdrawal (destructive; requires authorization)

Run the withdrawal script (see `scripts/withdraw_core_artifacts.sh`
below). It only removes files matching the withdrawn patterns; it does
not touch Baseline, Slack-Plus, manifests, published/historical, or
the dashboard tree.

```bash
# Sanity: script should refuse to run without an explicit CONFIRM flag.
./scripts/withdraw_core_artifacts.sh   # will print a usage banner and exit 1

# Actual removal (only after explicit authorization):
./scripts/withdraw_core_artifacts.sh --confirm
```

---

## Step 3 — Post-withdrawal verification

```bash
# 1. Removed files should now 404:
for URL in \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_core.json \
  https://dmianalysis.org/data/outputs/dmi-2026-03-core.csv \
  https://dmianalysis.org/data/outputs/dmi-2026-03-core.parquet \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_u6.json \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_with_ci.json
do
  code=$(curl -o /dev/null -sS -w '%{http_code}' "$URL")
  echo "$code  $URL"
done
# Expected: 404 for every URL that Step 0 listed as present.

# 2. Baseline + Slack-Plus for the current period still 200:
PERIOD=$(curl -sS https://dmianalysis.org/data/outputs/latest.json |
  jq -r '.releases[0].release_id')

for URL in \
  https://dmianalysis.org/data/outputs/dmi_release_${PERIOD}.json \
  https://dmianalysis.org/data/outputs/dmi_release_${PERIOD}_slack_plus.json \
  https://dmianalysis.org/data/outputs/dmi-${PERIOD}-baseline.csv \
  https://dmianalysis.org/data/outputs/dmi-${PERIOD}-baseline.parquet \
  https://dmianalysis.org/data/outputs/dmi-${PERIOD}-slack_plus.csv \
  https://dmianalysis.org/data/outputs/dmi-${PERIOD}-slack_plus.parquet
do
  code=$(curl -o /dev/null -sS -w '%{http_code}' "$URL")
  echo "$code  $URL"
done
# Expected: 200 for every URL.

# 3. Manifests still coherent:
curl -sS https://dmianalysis.org/data/outputs/releases.json |
  jq '.schema_version, (.releases | length), .releases[0].release_id'
# Expected: "3.0.0", <int>, "<current period>"

curl -sS https://dmianalysis.org/data/outputs/specifications.json |
  jq '.schema_version, [.specifications[].spec_id]'
# Expected: "0.3.0", ["baseline","slack_plus"]

# 4. Dashboard still loads:
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://dmianalysis.org/dashboard.html
# Expected: 200

# 5. Health endpoint:
curl -sS https://dmianalysis.org/health.json |
  jq '.version, .latest_period, .endpoints'
# Expected: "0.1.12", "<current period>", object without
# latest_core / latest_u6 / timeseries keys.
```

If any expectation fails, restore from the Step 1 backup:

```bash
rsync -avz \
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=no" \
  "$BACKUP_DIR/" \
  "$DMI_REMOTE_USER@$DMI_REMOTE_HOST:$DMI_REMOTE_BASE/data/outputs/"
```

---

## Step 4 — Record

- File the executed script log (stdout + stderr) at
  `docs/repair/REMOTE_WITHDRAWAL_LOG_<date>.md`.
- Update `docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md` with a "Removed
  from live site on <date>" section including the list of paths deleted
  and the curl-404 evidence from Step 3.
- Retain `$BACKUP_DIR` for at least 30 days.

---

## Rollback

If the withdrawal produces unexpected 5xx on the live site or breaks
the dashboard, restore immediately from the Step 1 backup (see Step 3
final block). No JSON on the server was rewritten by this procedure —
only static-artifact files were unlinked — so restoring the files
should fully reverse the change.

---

## See also

- Withdrawal script:
  [`scripts/withdraw_core_artifacts.sh`](../../scripts/withdraw_core_artifacts.sh)
- **Read-only local inventory helper (§10, added in Round 2):**
  [`scripts/inventory_withdrawn_artifacts.py`](../../scripts/inventory_withdrawn_artifacts.py).
  This script only *lists* withdrawn artifacts under the local working
  tree and never touches the remote. Use it before running Step 0 to
  confirm the local repository state you are about to compare against.
- Withdrawal-tool safety-posture regression:
  [`tests/test_withdrawal_tooling.py`](../../tests/test_withdrawal_tooling.py).
  Locks the shell script's `--confirm`-gated posture and the Python
  inventory tool's read-only surface so this runbook cannot silently
  regress.
- Rationale: [`docs/repair/CORE_WITHDRAWAL.md`](CORE_WITHDRAWAL.md)
- Consumer impact:
  [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
- Deployment workflow reference:
  [`.github/workflows/monthly_dmi.yml`](../../.github/workflows/monthly_dmi.yml)
- Round-2 §1-§15 dispositions:
  [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](V0.1.12_ALIGNMENT_AUDIT.md) §14.
