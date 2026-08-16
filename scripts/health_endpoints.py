"""Central source of truth for `web/health.json` endpoints (§8).

The health endpoint is the machine-readable "what does this site serve"
manifest at ``https://dmianalysis.org/health.json``. It is a small,
public contract, and every retired endpoint is a public regression
risk: consumers polling the retired URL will start receiving 404s, or
worse, will see fabricated data if a stale file is still on disk.

Historically the two writers (``scripts/compute_dmi.py::update_health_json``
and ``scripts/backfill_releases.py::update_health_json``) each read the
existing ``web/health.json`` from disk, updated a handful of specific
keys, and wrote the result back. Any key present in the on-disk file
that was NOT explicitly touched by the writer survived the round-trip.
That is exactly how the withdrawn ``latest_core`` endpoint kept
resurfacing after each release: an out-of-date checkout carried it,
the writer never popped it, and the next commit shipped it again.

This module centralises the endpoint contract:

- ``ALLOWED_ENDPOINT_KEYS`` is the frozenset of endpoint keys that are
  legitimately present under ``health["endpoints"]``.
- ``RETIRED_ENDPOINT_KEYS`` is the frozenset of keys that were
  legitimately present in prior versions and MUST NOT return. Kept as
  a named list so tests can assert they never resurface.
- ``sanitize_health_endpoints()`` strips every key that is not in the
  allow-list — retired keys, typos, unknown extensions — from the
  ``endpoints`` block of a health dict. Applied by every writer just
  before persisting.

Any new endpoint MUST be added to ``ALLOWED_ENDPOINT_KEYS`` here
first; retirements should move the key from ``ALLOWED`` to ``RETIRED``.
"""

from __future__ import annotations


# Every endpoint key currently blessed for the public health manifest.
# The values themselves are per-release paths, computed by the writers;
# this set only governs which KEYS are legal.
ALLOWED_ENDPOINT_KEYS: frozenset[str] = frozenset({
    "dashboard",
    "latest",
    "latest_slack_plus",
    "releases",
    "specifications",
    # Optional: only written when a `dmi_release_YYYY-MM_with_ci.json`
    # exists for the current period; the writer pops it otherwise.
    "latest_with_ci",
})


# Endpoint keys that were shipped by prior versions of the writer and
# have been retired. They must NEVER reappear under `health["endpoints"]`.
# Documented explicitly so regression tests can pin the retirement.
RETIRED_ENDPOINT_KEYS: frozenset[str] = frozenset({
    # Core spec was withdrawn (see docs/repair/CORE_WITHDRAWAL.md); the
    # `latest_core` URL served fabricated data and must never return.
    "latest_core",
    # `latest_u6` was a legacy alias for `latest_slack_plus`. The two-
    # spec (Baseline + Slack-Plus) v0.1.12 contract exposes only the
    # canonical `latest_slack_plus` name; the alias is retired.
    "latest_u6",
    # Historical v0.1.10 health.json advertised a bare timeseries URL
    # under this key; the current contract expects consumers to fetch
    # `/data/outputs/published/dmi_timeseries.json` directly. Removing
    # the alias avoids a two-URL contract for the same file.
    "timeseries",
    "dmi_timeseries",
})


def sanitize_health_endpoints(health: dict) -> dict:
    """Strip every endpoint key not in ``ALLOWED_ENDPOINT_KEYS``.

    Mutates and returns ``health`` for convenience. If
    ``health["endpoints"]`` is missing or not a dict, no action is
    taken (the writer will typically initialise it via ``setdefault``
    elsewhere; this function does not invent an empty dict).
    """
    endpoints = health.get("endpoints")
    if not isinstance(endpoints, dict):
        return health

    for key in list(endpoints.keys()):
        if key not in ALLOWED_ENDPOINT_KEYS:
            del endpoints[key]

    return health
