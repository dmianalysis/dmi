# Remote Withdrawal Procedure — v0.1.12 Core Artifacts

**Status**: **EXECUTED 2026-08-19 — this procedure is complete and the destructive workflow has been retired.**

Both phases have run. The outcome, evidence and hashes are recorded in
[`docs/repair/REMOTE_WITHDRAWAL_LOG_2026-08-19.md`](REMOTE_WITHDRAWAL_LOG_2026-08-19.md).
All 21 inventoried Core artifacts were verified absent and all 15
protected operational artifacts verified present; no restoration and no
CDN purge were performed.

This document is retained as the **procedure of record** — the steps that
were followed — not as a pending instruction. The destructive workflow
`execute_withdrawn_core.yml` was removed from `.github/workflows` after
the successful run, so the commands below are no longer dispatchable as
written; re-running any of them would require deliberately reinstating a
destructive entry point, which is a new decision requiring new
authorization.

Three things are easy to conflate; they are separate and only the first
is finished:

| | State |
|---|---|
| **Local repository cleanup** | **Complete.** Core artifacts are absent from every active tree, manifest, health file and deployment package. The U-6 / with-CI legacy files are quarantined under `data/quarantine/pre_v0.1.12/`. |
| **Production deployment** | **Has not occurred.** It happens automatically from the merge commit once the repair PR is merged, via `.github/workflows/deploy_production.yml`. |
| **Remote artifact withdrawal** | **Not authorized and not executed.** This document. It is a separate, deliberate act performed by an operator; nothing triggers it automatically, and merging the PR does not run it. |

Because local cleanup is complete, the withdrawn Core files are no longer
*advertised* by anything the site serves. They may still be *present* on
the server as unreferenced files until this procedure is run. That is the
gap this document closes.

Do not run any of the commands below without explicit, contemporaneous
authorization from the repository owner.

---

## Scope

Withdraw from the live site (`https://dmianalysis.org/`) the artifacts
that v0.1.12 no longer advertises, so that the on-disk state at
`agiraces@…:/home/agiraces/dmianalysis/` matches the v0.1.12 published
contract (Baseline + Slack-Plus only).

### Files to withdraw

This procedure withdraws **Core artifacts only**. The scope is exactly
four filename classes:

| Live URL                                                               | Remote path (iFastNet)                                                  |
|------------------------------------------------------------------------|-------------------------------------------------------------------------|
| `/data/outputs/dmi_release_YYYY-MM_core.json` (every historical month) | `/home/agiraces/dmianalysis/data/outputs/dmi_release_YYYY-MM_core.json` |
| `/data/outputs/dmi-YYYY-MM-core.csv`                                   | `/home/agiraces/dmianalysis/data/outputs/dmi-YYYY-MM-core.csv`          |
| `/data/outputs/dmi-YYYY-MM-core.parquet`                               | `/home/agiraces/dmianalysis/data/outputs/dmi-YYYY-MM-core.parquet`      |
| `/data/outputs/qa_report_YYYY-MM_core.json`                            | `/home/agiraces/dmianalysis/data/outputs/qa_report_YYYY-MM_core.json`   |

> **Scope correction (Round 4).** Earlier revisions of this runbook and of
> the tool listed `dmi_release_YYYY-MM_u6.json` and
> `dmi_release_YYYY-MM_with_ci.json` in this table, and omitted
> `qa_report_*_core.json`. Both were errors.
>
> **`_u6` and `_with_ci` files are NOT Core** and must **not** be deleted
> through this procedure. They are pre-v0.1.12 legacy artifacts —
> historical evidence of superseded methodology runs. Their remote
> disposition is explicitly **outside the authorization** this runbook
> operates under, and requires a separate decision. Local copies are
> quarantined (not deleted) under `data/quarantine/pre_v0.1.12/`; see that
> directory's README.
>
> The tool now enforces this: `NON_CORE_REGEXES` in
> `scripts/withdraw_remote_artifacts.py` actively **refuses** any
> inventory entry matching `_u6` or `_with_ci`, and `CORE_NAME_REGEXES`
> requires every entry to positively match one of the four classes above.
> If you supply an inventory containing one, both phases abort.

### Files to leave in place

- **`dmi_release_YYYY-MM_u6.json`** and
  **`dmi_release_YYYY-MM_with_ci.json`** — not Core; outside this
  authorization (see the scope correction above).

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
  "ls -la $DMI_REMOTE_BASE/data/outputs/ | grep -E '_core\\.json$|-core\\.(csv|parquet)$' || true"

# Separately, for INFORMATION ONLY — these are NOT withdrawal targets.
# Seeing them here does not authorize deleting them (see scope note above).
ssh $SSH_OPTS "$DMI_REMOTE_USER@$DMI_REMOTE_HOST" \
  "ls -la $DMI_REMOTE_BASE/data/outputs/ | grep -E '_u6\\.json$|_with_ci\\.json$' || true"
```

Expected: a list of the files enumerated in the "Files to withdraw"
table (or empty, if the site has already been cleaned).

---

## Step 1 — Backup

Snapshot the remote `data/outputs/` tree before any deletion.

```bash
BACKUP_DIR="./backup-preremoval-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"

# §3 (Round-4): host authentication is PINNED, not acquired.
#
# An earlier revision of this runbook fetched the host key with
# `ssh-keyscan` when it was not already known. That authenticates
# nothing: `ssh-keyscan` asks whoever answers the connection to
# introduce itself and believes the reply, so an intercepting party
# simply answers and their key becomes the trusted one. Strict checking
# then verifies the session against the attacker's key.
#
# Supply the expected key out of band. Get it from the hosting control
# panel or from a known-good prior session, NOT by scanning the host you
# are about to authenticate.
KNOWN_HOSTS="$HOME/.ssh/dmi_known_hosts"
export DMI_KNOWN_HOSTS="$KNOWN_HOSTS"
export DMI_KNOWN_HOSTS_DATA="$(cat /secure/path/to/ifastnet_known_hosts)"

python -m scripts.install_known_hosts \
  --host "$DMI_REMOTE_HOST" --port "$DMI_REMOTE_PORT" \
  --known-hosts "$KNOWN_HOSTS"
# Fails if the pinned material is absent, empty, malformed, or issued
# for a different host or port. There is no fallback.

rsync -avz \
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS" \
  "$DMI_REMOTE_USER@$DMI_REMOTE_HOST:$DMI_REMOTE_BASE/data/outputs/" \
  "$BACKUP_DIR/"

# Verify backup includes withdrawn artifacts:
find "$BACKUP_DIR" -type f \( \
    -name '*_core.json' -o \
    -name '*-core.csv' -o \
    -name '*-core.parquet' -o \
    -name 'qa_report_*_core.json' \
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
3. The inventory's `integrity_sha256` still matches a recomputation over
   its own contents — so an inventory edited after review cannot be
   consumed silently (see Step 2a-bis for the legitimate pruning path).
4. Every path passes the scope rules: not a protected
   Baseline/Slack-Plus/manifest/release-note name, not a non-Core legacy
   name (`_u6`, `_with_ci`), and a positive match against one of the four
   Core filename classes.
5. Each file's on-remote SHA-256 at execution time matches the hash
   recorded in the inventory (protects against races between the two
   phases).

`execute` **never re-runs `find`**. It deletes exactly the paths in the
reviewed inventory and nothing else, so a file that appeared on the
remote after review cannot enter the delete set. Afterwards it verifies
that every inventoried path is actually absent and fails if any
survived.

Files matching the protected patterns (Baseline `dmi_release_YYYY-MM.json`,
Slack-Plus `dmi_release_YYYY-MM_slack_plus.json`, the corresponding
`dmi-YYYY-MM-{baseline,slack_plus}.{csv,parquet}` plus legacy
`dmi-YYYY-MM.{csv,parquet}`, the manifests, and the release notes) are
refused up front — the tool exits non-zero rather than deleting a
mislabeled operational artifact.

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
#     ],
#     "integrity_sha256": "<hex>"
#   }
#
# `integrity_sha256` seals the reviewed decision: it covers remote_base,
# remote_outputs, and every (path, size, sha256) triple. It deliberately
# EXCLUDES generated_at_utc, so the hash identifies the decision rather
# than the run that produced it — re-running inventory against an
# unchanged remote yields the same hash.
```

Review the inventory before proceeding. Every listed path must be one of
the four Core filename classes: `dmi_release_YYYY-MM_core.json`,
`dmi-YYYY-MM-core.csv`, `dmi-YYYY-MM-core.parquet`, or
`qa_report_YYYY-MM_core.json`. If anything else appears — in particular
any `_u6` or `_with_ci` file — stop and open a bug; the tool should have
refused at inventory time.

### Step 2a-bis — Reseal, only if you pruned the inventory

If review leads you to remove entries you do not want deleted, the
integrity hash no longer matches and `execute` will refuse. Re-approve
the pruned list explicitly:

```bash
python -m scripts.withdraw_remote_artifacts reseal \
  --inventory "$INVENTORY"
# Prints the previous and new hash. Local only: no SSH, no deletion.
# Re-validates the scope rules, so resealing cannot smuggle an
# out-of-scope path past them.
```

Resealing is an auditable act, not a bypass: it records that a human
re-approved a changed list. Never edit `integrity_sha256` by hand.

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
# 1. Withdrawn CORE files should now 404:
for URL in \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_core.json \
  https://dmianalysis.org/data/outputs/dmi-2026-03-core.csv \
  https://dmianalysis.org/data/outputs/dmi-2026-03-core.parquet \
  https://dmianalysis.org/data/outputs/qa_report_2026-03_core.json
do
  code=$(curl -o /dev/null -sS -w '%{http_code}' "$URL")
  echo "$code  $URL"
done
# Expected: 404 for every URL that Step 0 listed as present.

# 2. Legacy _u6 / _with_ci files are NOT withdrawal targets. Whatever
#    status they returned before this procedure, they must return the
#    SAME status afterwards. A 404 here means something deleted a file
#    outside this authorization — investigate before proceeding.
for URL in \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_u6.json \
  https://dmianalysis.org/data/outputs/dmi_release_2024-11_with_ci.json
do
  code=$(curl -o /dev/null -sS -w '%{http_code}' "$URL")
  echo "$code  $URL   (must be unchanged from Step 0)"
done

# 3. Baseline + Slack-Plus for the current period still 200:
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

If any expectation fails, restore from the Step 1 backup.

Note the `UserKnownHostsFile` below: it is `$KNOWN_HOSTS`, the pinned
file validated in Step 1 — **not** the default `~/.ssh/known_hosts`.
Recovery is exactly when a host-identity check matters most, and it is
exactly when an operator is under time pressure and reaching for a
familiar command. Falling back to the default file here would
authenticate the restore against whatever that file happens to contain,
which is the trust-on-first-use problem the pinning exists to remove.

```bash
rsync -avz \
  -e "ssh -i $DMI_REMOTE_KEY -p $DMI_REMOTE_PORT -o StrictHostKeyChecking=yes -o UserKnownHostsFile=$KNOWN_HOSTS" \
  "$BACKUP_DIR/" \
  "$DMI_REMOTE_USER@$DMI_REMOTE_HOST:$DMI_REMOTE_BASE/data/outputs/"
```

If `$KNOWN_HOSTS` is not set in the recovery shell, re-run the Step 1
`scripts.install_known_hosts` command before restoring. Do not substitute
the default file.

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
