#!/usr/bin/env python3
"""Regression coverage for the health-endpoint contract (§8).

`web/health.json` is the public, machine-readable "what does this site
serve" manifest. Retired endpoint keys (``latest_core``, ``latest_u6``,
``timeseries``, ``dmi_timeseries``) MUST NOT be present. The mechanism
that historically let them resurface was:

- Writer reads the on-disk health.json into a dict,
- updates a handful of specific keys,
- writes the dict back.

Any retired key present in the on-disk file that was NOT explicitly
popped by the writer survived the round-trip. `scripts/health_endpoints`
now provides a single allow-list + sanitizer used by every writer.
These tests pin the contract.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from scripts.health_endpoints import (
    ALLOWED_ENDPOINT_KEYS,
    RETIRED_ENDPOINT_KEYS,
    sanitize_health_endpoints,
)

ROOT = Path(__file__).resolve().parent.parent
SHIPPED_HEALTH = ROOT / "web" / "health.json"


class TestAllowRetireSetsAreDisjoint(unittest.TestCase):

    def test_no_key_is_both_allowed_and_retired(self):
        overlap = ALLOWED_ENDPOINT_KEYS & RETIRED_ENDPOINT_KEYS
        self.assertEqual(
            overlap, frozenset(),
            f"§8: keys cannot be both allowed and retired: {sorted(overlap)}",
        )

    def test_retired_set_pins_known_offenders(self):
        # These four MUST stay retired forever; the sanitizer relies on
        # the allow-list logic, but we spell them out explicitly so a
        # future edit that quietly re-permits any of them fails loudly.
        for key in ("latest_core", "latest_u6", "timeseries", "dmi_timeseries"):
            self.assertIn(
                key, RETIRED_ENDPOINT_KEYS,
                f"§8: {key!r} must be pinned as retired.",
            )
            self.assertNotIn(
                key, ALLOWED_ENDPOINT_KEYS,
                f"§8: {key!r} must not be in the allow-list.",
            )


class TestSanitizeHealthEndpoints(unittest.TestCase):

    def test_strips_every_retired_key(self):
        health = {
            "endpoints": {
                "dashboard": "/dashboard.html",
                "latest": "/data/outputs/dmi_release_2026-07.json",
                "latest_core": "/data/outputs/dmi_release_2026-07_core.json",
                "latest_u6": "/data/outputs/dmi_release_2026-07_slack_plus.json",
                "timeseries": "/data/outputs/published/dmi_timeseries.json",
                "dmi_timeseries": "/data/outputs/published/dmi_timeseries.json",
            }
        }
        sanitize_health_endpoints(health)
        for key in RETIRED_ENDPOINT_KEYS:
            self.assertNotIn(
                key, health["endpoints"],
                f"§8: retired key {key!r} survived sanitization.",
            )

    def test_preserves_every_allowed_key(self):
        health = {
            "endpoints": {key: f"/fake/{key}" for key in ALLOWED_ENDPOINT_KEYS}
        }
        sanitize_health_endpoints(health)
        self.assertEqual(
            set(health["endpoints"].keys()), set(ALLOWED_ENDPOINT_KEYS),
            "§8: sanitizer must not drop legitimately-allowed keys.",
        )

    def test_strips_unknown_typo_keys(self):
        health = {
            "endpoints": {
                "dashboard": "/dashboard.html",
                "latset": "/typo",           # typo of "latest"
                "release":  "/typo",         # missing trailing s
                "not_a_real_endpoint": "/x",
            }
        }
        sanitize_health_endpoints(health)
        self.assertEqual(
            list(health["endpoints"].keys()), ["dashboard"],
            "§8: only allow-listed keys must remain after sanitization.",
        )

    def test_missing_endpoints_block_is_a_noop(self):
        # No `endpoints` key at all.
        health = {"status": "healthy"}
        sanitize_health_endpoints(health)
        self.assertNotIn("endpoints", health)

    def test_non_dict_endpoints_is_a_noop(self):
        health = {"endpoints": "not-a-dict"}
        sanitize_health_endpoints(health)
        # Sanitizer must not crash and must not invent a dict.
        self.assertEqual(health["endpoints"], "not-a-dict")

    def test_returns_the_same_object(self):
        # Convenience: sanitize_health_endpoints returns the mutated dict
        # so callers can inline it in a fluent chain if they wish.
        health = {"endpoints": {"latest_core": "/x"}}
        result = sanitize_health_endpoints(health)
        self.assertIs(result, health)


class TestShippedHealthJson(unittest.TestCase):

    def setUp(self):
        self.health = json.loads(SHIPPED_HEALTH.read_text())

    def test_shipped_endpoints_are_all_allow_listed(self):
        endpoints = self.health.get("endpoints", {})
        offenders = sorted(set(endpoints) - ALLOWED_ENDPOINT_KEYS)
        self.assertEqual(
            offenders, [],
            f"§8: shipped health.json advertises non-allow-listed "
            f"endpoint(s): {offenders}",
        )

    def test_shipped_endpoints_contain_no_retired_keys(self):
        endpoints = self.health.get("endpoints", {})
        offenders = sorted(set(endpoints) & RETIRED_ENDPOINT_KEYS)
        self.assertEqual(
            offenders, [],
            f"§8: shipped health.json still advertises retired "
            f"endpoint(s): {offenders}",
        )


class TestBothWritersInvokeSanitizer(unittest.TestCase):
    """Contract-level check: both writers import the sanitizer.

    We do not exercise the writers end-to-end here (that would require
    building a whole release fixture); this test freezes the specific
    integration point so a future refactor that quietly drops the
    sanitize call fails immediately.
    """

    def test_compute_dmi_update_health_json_calls_sanitizer(self):
        src = (ROOT / "scripts" / "compute_dmi.py").read_text()
        self.assertIn("sanitize_health_endpoints", src)

    def test_backfill_releases_update_health_json_calls_sanitizer(self):
        src = (ROOT / "scripts" / "backfill_releases.py").read_text()
        self.assertIn("sanitize_health_endpoints", src)


if __name__ == "__main__":
    unittest.main()
