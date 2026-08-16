#!/usr/bin/env bash
# withdraw_core_artifacts.sh
#
# Remove withdrawn v0.1.12 legacy artifacts from the live iFastNet site.
# The script is intentionally conservative: it targets only file
# name patterns that v0.1.12 no longer advertises (Core outputs, U-6
# legacy naming, with_ci confidence-interval companions). It never
# touches Baseline, Slack-Plus, published/historical, manifests, the
# dashboard tree, or anything under a directory whose name it does not
# recognize.
#
# See docs/repair/REMOTE_WITHDRAWAL.md for the full authorization gate,
# backup procedure, and verification steps. This script must not be
# invoked outside that procedure.
#
# Environment (must be set):
#   DMI_REMOTE_HOST   iFastNet SSH host
#   DMI_REMOTE_USER   iFastNet SSH user
#   DMI_REMOTE_PORT   SSH port (defaults to 1394)
#   DMI_REMOTE_KEY    Path to private SSH key
#   DMI_REMOTE_BASE   Remote base path (defaults to /home/agiraces/dmianalysis)
#
# Usage:
#   ./scripts/withdraw_core_artifacts.sh            # prints usage, exits 1
#   ./scripts/withdraw_core_artifacts.sh --dry-run  # lists what would be removed
#   ./scripts/withdraw_core_artifacts.sh --confirm  # actually removes files

set -euo pipefail

CONFIRM="no"
DRY_RUN="no"

for arg in "$@"; do
  case "$arg" in
    --confirm) CONFIRM="yes" ;;
    --dry-run) DRY_RUN="yes" ;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [ "$CONFIRM" != "yes" ] && [ "$DRY_RUN" != "yes" ]; then
  cat <<'BANNER' >&2
withdraw_core_artifacts.sh — refuses to run without an explicit flag.

  --dry-run   List the files that would be removed. No changes made.
  --confirm   Actually remove files. Requires prior authorization
              per docs/repair/REMOTE_WITHDRAWAL.md.

Neither flag was supplied. Exiting.
BANNER
  exit 1
fi

: "${DMI_REMOTE_HOST:?DMI_REMOTE_HOST must be set}"
: "${DMI_REMOTE_USER:?DMI_REMOTE_USER must be set}"
: "${DMI_REMOTE_PORT:=1394}"
: "${DMI_REMOTE_KEY:?DMI_REMOTE_KEY must be set}"
: "${DMI_REMOTE_BASE:=/home/agiraces/dmianalysis}"

REMOTE_OUTPUTS="$DMI_REMOTE_BASE/data/outputs"

if [ ! -f "$DMI_REMOTE_KEY" ]; then
  echo "SSH key not found at $DMI_REMOTE_KEY" >&2
  exit 3
fi

# §3 (Round-3 repair): strict host verification is mandatory. If the
# operator has not yet pinned the host key, populate a local
# known_hosts via ssh-keyscan; a keyscan failure is fatal (no `|| true`).
KNOWN_HOSTS="${DMI_KNOWN_HOSTS:-$HOME/.ssh/known_hosts}"
mkdir -p "$(dirname "$KNOWN_HOSTS")"
touch "$KNOWN_HOSTS"
chmod 600 "$KNOWN_HOSTS"
if ! ssh-keygen -F "[$DMI_REMOTE_HOST]:$DMI_REMOTE_PORT" -f "$KNOWN_HOSTS" >/dev/null 2>&1 \
   && ! ssh-keygen -F "$DMI_REMOTE_HOST" -f "$KNOWN_HOSTS" >/dev/null 2>&1; then
  echo "Host $DMI_REMOTE_HOST:$DMI_REMOTE_PORT not in $KNOWN_HOSTS; pinning via ssh-keyscan ..." >&2
  ssh-keyscan -p "$DMI_REMOTE_PORT" "$DMI_REMOTE_HOST" >> "$KNOWN_HOSTS"
fi

SSH_CMD=(ssh -i "$DMI_REMOTE_KEY" -p "$DMI_REMOTE_PORT" \
         -o StrictHostKeyChecking=yes \
         -o UserKnownHostsFile="$KNOWN_HOSTS" \
         "$DMI_REMOTE_USER@$DMI_REMOTE_HOST")

# The find expression matches ONLY the withdrawn patterns. Baseline
# (dmi_release_YYYY-MM.json, dmi-YYYY-MM-baseline.*) and Slack-Plus
# (dmi_release_YYYY-MM_slack_plus.json, dmi-YYYY-MM-slack_plus.*) do
# not match any of these patterns.
FIND_EXPR='(
  -name "dmi_release_*_core.json" -o
  -name "dmi_release_*_u6.json" -o
  -name "dmi_release_*_with_ci.json" -o
  -name "dmi-*-core.csv" -o
  -name "dmi-*-core.parquet"
)'

echo "Enumerating withdrawn artifacts under $REMOTE_OUTPUTS ..."
# List first, so the operator can eyeball what is about to go.
"${SSH_CMD[@]}" \
  "find $REMOTE_OUTPUTS -maxdepth 1 -type f \\( \
     -name 'dmi_release_*_core.json' -o \
     -name 'dmi_release_*_u6.json' -o \
     -name 'dmi_release_*_with_ci.json' -o \
     -name 'dmi-*-core.csv' -o \
     -name 'dmi-*-core.parquet' \
   \\) -print" \
  | tee /tmp/dmi_withdrawal_list.txt

COUNT=$(wc -l < /tmp/dmi_withdrawal_list.txt | tr -d ' ')
echo
echo "Matched $COUNT file(s)."

if [ "$COUNT" = "0" ]; then
  echo "Nothing to withdraw. Exiting cleanly."
  exit 0
fi

if [ "$DRY_RUN" = "yes" ]; then
  echo "Dry-run mode: no files removed."
  exit 0
fi

# Belt-and-suspenders safety: refuse to proceed if the match list
# contains anything that looks like a Baseline or Slack-Plus artifact.
# The find expression above already excludes those, but if the pattern
# is ever loosened by mistake, this guard fails closed.
if grep -E '/(dmi_release_[0-9]{4}-[0-9]{2}\.json|dmi_release_[0-9]{4}-[0-9]{2}_slack_plus\.json|dmi-[0-9]{4}-[0-9]{2}-baseline\.(csv|parquet)|dmi-[0-9]{4}-[0-9]{2}-slack_plus\.(csv|parquet))$' \
     /tmp/dmi_withdrawal_list.txt >/dev/null; then
  echo "ABORT: match list unexpectedly contains a Baseline or Slack-Plus artifact." >&2
  echo "Not deleting anything." >&2
  exit 4
fi

echo
echo "Proceeding with removal (--confirm supplied)."
"${SSH_CMD[@]}" \
  "find $REMOTE_OUTPUTS -maxdepth 1 -type f \\( \
     -name 'dmi_release_*_core.json' -o \
     -name 'dmi_release_*_u6.json' -o \
     -name 'dmi_release_*_with_ci.json' -o \
     -name 'dmi-*-core.csv' -o \
     -name 'dmi-*-core.parquet' \
   \\) -print -delete"

echo
echo "Withdrawal complete. Run the Step 3 verification block in"
echo "docs/repair/REMOTE_WITHDRAWAL.md."
