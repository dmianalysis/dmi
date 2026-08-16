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

# §3 (Round-3): strict host verification is mandatory. Pin the host
# key up front; a failure to reach the host is fatal.
KNOWN_HOSTS="$HOME/.ssh/known_hosts"
mkdir -p "$(dirname "$KNOWN_HOSTS")" && touch "$KNOWN_HOSTS" && chmod 600 "$KNOWN_HOSTS"
if ! ssh-keygen -F "[$DMI_REMOTE_HOST]:$DMI_REMOTE_PORT" -f "$KNOWN_HOSTS" >/dev/null 2>&1 \
   && ! ssh-keygen -F "$DMI_REMOTE_HOST" -f "$KNOWN_HOSTS" >/dev/null 2>&1; then
  ssh-keyscan -p "$DMI_REMOTE_PORT" "$DMI_REMOTE_HOST" >> "$KNOWN_HOSTS"
fi

rsync -avz \
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS" \
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

## Step 2 — Withdrawal (two-phase; destructive phase requires authorization)

The withdrawal is performed by
[`scripts/withdraw_remote_artifacts.py`](../../scripts/withdraw_remote_artifacts.py)
(Round-3 §10). The tool has two subcommands and refuses to delete
anything unless three independent conditions hold:

1. The `execute` subcommand was invoked with `--confirm`.
2. The inventory JSON's `remote_base` matches the current environment
   variable `DMI_REMOTE_BASE`.
3. Each file's on-remote SHA-256 at execution time matches the hash
   recorded in the inventory (protects against races between the two
   phases).

Files matching the protected patterns (Baseline `dmi_release_YYYY-MM.json`,
Slack-Plus `dmi_release_YYYY-MM_slack_plus.json`, and the corresponding
`dmi-YYYY-MM-{baseline,slack_plus}.{csv,parquet}` plus legacy
`dmi-YYYY-MM.{csv,parquet}`) are refused up front — the tool exits
non-zero rather than deleting a mislabeled operational artifact.

### Step 2a — Inventory (read-only)

```bash
INVENTORY=/tmp/dmi-remote-withdraw-inventory-$(date -u +%Y%m%dT%H%M%SZ).json

python -m scripts.withdraw_remote_artifacts inventory \
  --output "$INVENTORY"

# The inventory command runs ssh over the pinned known_hosts, walks
# $DMI_REMOTE_BASE/data/outputs/ for the withdrawn-artifact patterns,
# computes SHA-256 for each match, and writes a JSON file with:
#   {
#     "schema_version": "1.0.0",
#     "remote_base": "/home/agiraces/dmianalysis",
#     "generated_at": "<UTC ISO8601>",
#     "files": [
#       {"path": "<remote_base>/data/outputs/dmi_release_2024-11_core.json",
#        "size": <bytes>, "sha256": "<hex>"},
#       ...
#     ]
#   }
```

Review the inventory before proceeding. Every listed path should end in
one of the withdrawn suffixes (`_core.json`, `_u6.json`, `_with_ci.json`,
`-core.csv`, `-core.parquet`). If anything else appears, stop and open a
bug; the tool should have refused at inventory time.

### Step 2b — Execute (destructive; requires --confirm)

```bash
# Sanity: without --confirm, execute exits fail-fast before any SSH I/O.
python -m scripts.withdraw_remote_artifacts execute \
  --inventory "$INVENTORY"
# Expected: "ERROR: execute requires --confirm" and exit 1.

# Actual removal (only after explicit authorization):
python -m scripts.withdraw_remote_artifacts execute \
  --inventory "$INVENTORY" \
  --confirm
```

For each file in the inventory the execute phase:

1. Re-hashes the remote file over SSH.
2. Refuses to delete if the current hash differs from the inventory
   hash (raced file); exits non-zero and reports the mismatched paths.
3. Otherwise runs `ssh … "rm -f <path>"` and records the deletion.

The tool writes a completion summary to stdout. Capture it into
`docs/repair/REMOTE_WITHDRAWAL_LOG_<date>.md` per Step 4.

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
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$HOME/.ssh/known_hosts" \
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

- Withdrawal tool (two-phase, §10):
  [`scripts/withdraw_remote_artifacts.py`](../../scripts/withdraw_remote_artifacts.py)
  — the ``inventory`` → review → ``execute --confirm`` workflow
  documented in Step 2. Replaces the retired
  ``scripts/withdraw_core_artifacts.sh``.
- **Read-only local inventory helper:**
  [`scripts/inventory_withdrawn_artifacts.py`](../../scripts/inventory_withdrawn_artifacts.py).
  This script only *lists* withdrawn artifacts under the local working
  tree and never touches the remote. Use it before running Step 0 to
  confirm the local repository state you are about to compare against.
- Withdrawal-tool safety-posture regression:
  [`tests/test_withdrawal_tooling.py`](../../tests/test_withdrawal_tooling.py).
  Locks the two-phase Python tool's structural guarantees (SHA-256
  re-verification gate, ``--confirm`` fail-fast before SSH I/O,
  protected-pattern refusal) and the local inventory tool's read-only
  surface so this runbook cannot silently regress.
- Rationale: [`docs/repair/CORE_WITHDRAWAL.md`](CORE_WITHDRAWAL.md)
- Consumer impact:
  [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
- Deployment workflow reference:
  [`.github/workflows/monthly_dmi.yml`](../../.github/workflows/monthly_dmi.yml)
- Round-2 §1-§15 dispositions:
  [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](V0.1.12_ALIGNMENT_AUDIT.md) §14.
