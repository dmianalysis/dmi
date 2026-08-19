#!/usr/bin/env bash
#
# Install the deployment private key from $IFASTNET_SSH_KEY (hotfix).
#
# Why this file exists
# --------------------
# A production deployment failed with:
#
#     Load key "/home/runner/.ssh/deploy_key": error in libcrypto
#
# The workflows had been changed from
#
#     echo "$IFASTNET_SSH_KEY" > ~/.ssh/deploy_key
#
# to
#
#     printf '%s' "$IFASTNET_SSH_KEY" > ~/.ssh/deploy_key
#
# `echo` appends a trailing newline; `printf '%s'` does not. OpenSSH
# requires the PEM/OpenSSH key file to end with a newline after the
# closing "-----END ... KEY-----" line, and rejects the file outright
# without it. The switch looked like a tightening (no stray whitespace)
# and was in fact a breaking change. Nothing in CI caught it, because CI
# never installs a key.
#
# The failure surfaced only at deploy time, and only on the runner. It is
# also easy to misread: "error in libcrypto" suggests a corrupt or
# wrong-format secret rather than a missing final byte, which points an
# operator at rotating the secret — exactly the wrong response, and one
# that would have left the real cause in place.
#
# So key installation lives here, once, and is tested against genuinely
# generated keys rather than described in three separate YAML files.
#
# Contract
# --------
#   in : $IFASTNET_SSH_KEY   the private key material
#        $1 (optional)       destination path (default ~/.ssh/deploy_key)
#   out: a mode-600 key file that `ssh-keygen -y` accepts
#
# It never prints key material: every diagnostic describes a property of
# the key (empty, malformed, passphrase-protected), never its content.

set -euo pipefail

DEST="${1:-$HOME/.ssh/deploy_key}"
SSH_DIR="$(dirname "$DEST")"

die() {
    # Diagnostics only. Never echo $IFASTNET_SSH_KEY or file contents.
    echo "ERROR: $*" >&2
    exit 1
}

# --- 1. require the secret to be present and non-empty -----------------
if [ -z "${IFASTNET_SSH_KEY:-}" ]; then
    die "IFASTNET_SSH_KEY is unset or empty. The deployment private key \
must be provided through that secret; refusing to continue."
fi

# Reject whitespace-only input, which is empty for our purposes but not
# caught by -z.
if [ -z "$(printf '%s' "$IFASTNET_SSH_KEY" | tr -d '[:space:]')" ]; then
    die "IFASTNET_SSH_KEY contains only whitespace."
fi

# --- 2. create ~/.ssh with the mode OpenSSH insists on -----------------
install -d -m 700 "$SSH_DIR"

# --- 3. write the key -------------------------------------------------
#
# `printf '%s\n'` guarantees exactly one terminal newline — the byte
# whose absence caused the outage. `tr -d '\r'` strips CR so a secret
# stored with Windows line endings does not produce "\r\n" lines, which
# OpenSSH also rejects. Together they normalise both spellings of the
# same mistake.
#
# If the secret already ends with a newline, `printf '%s\n'` yields a
# trailing blank line. OpenSSH tolerates that, and it is strictly safer
# than trying to detect and conditionally add one.
umask 077
printf '%s\n' "$IFASTNET_SSH_KEY" | tr -d '\r' > "$DEST"
chmod 600 "$DEST"

# --- 4. validate BEFORE any network connection ------------------------
#
# -y derives the public key, which requires successfully parsing the
# private key: the cheapest complete parse check available.
# -P "" supplies an empty passphrase non-interactively, so a
# passphrase-protected key fails here instead of hanging a runner
# waiting on a prompt that will never be answered.
if ! ssh-keygen -y -P "" -f "$DEST" >/dev/null 2>"$DEST.err"; then
    detail="$(tr -d '\r' < "$DEST.err" | head -3 | tr '\n' ' ')"
    rm -f "$DEST" "$DEST.err"
    die "the deployment key in IFASTNET_SSH_KEY could not be parsed by \
ssh-keygen. It is malformed, truncated, or passphrase-protected \
(deployment requires an unencrypted key). ssh-keygen said: ${detail:-<none>}. \
No key material is shown. The key file has been removed."
fi
rm -f "$DEST.err"

echo "Deployment key installed and validated at $DEST (mode 600)."
