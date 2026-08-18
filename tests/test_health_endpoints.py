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
import os
import tempfile
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


class TestHealthWritersProduceExactEndpointSet(unittest.TestCase):
    """§7/§14: EXECUTE each health writer and assert the exact key set.

    The previous version of this class asserted only that the string
    "sanitize_health_endpoints" appeared in each writer's source, and
    said so openly ("We do not exercise the writers end-to-end here").
    That is not a control: it passes whether the call is reached, whether
    it runs before the write, and whether the allow-list is correct.

    These tests seed a health.json containing EVERY retired key plus
    every allowed key, run the real writer against it in a temporary
    working directory, and assert the exact resulting key set. Both
    writers hardcode the relative path `web/health.json`, so a chdir is
    sufficient to isolate them from the repository's own file.
    """

    #: What a stale checkout might carry in: every allowed key plus
    #: every retired key we have ever shipped.
    SEEDED_ENDPOINTS = {
        "dashboard": "/dashboard.html",
        "latest": "/data/outputs/dmi_release_2020-01.json",
        "latest_slack_plus": "/data/outputs/dmi_release_2020-01_slack_plus.json",
        "releases": "/data/outputs/releases.json",
        "specifications": "/data/outputs/specifications.json",
        # Retired — must be stripped.
        "latest_core": "/data/outputs/dmi_release_2020-01_core.json",
        "latest_u6": "/data/outputs/dmi_release_2020-01_u6.json",
        "latest_with_ci": "/data/outputs/dmi_release_2020-01_with_ci.json",
        "timeseries": "/data/outputs/published/dmi_timeseries.json",
        "dmi_timeseries": "/data/outputs/published/dmi_timeseries.json",
        # Unknown/typo — must also be stripped.
        "lastest": "/data/outputs/typo.json",
    }

    PERIOD = "2026-07"

    def _seed(self, tmp: Path) -> Path:
        """Write a health.json carrying every retired key."""
        health_path = tmp / "web" / "health.json"
        health_path.parent.mkdir(parents=True, exist_ok=True)
        health_path.write_text(json.dumps({
            "status": "healthy",
            "version": "0.1.10",
            "latest_period": "2020-01",
            "endpoints": dict(self.SEEDED_ENDPOINTS),
        }, indent=2))
        return health_path

    def _run_writer(self, writer) -> dict:
        """Run ``writer(PERIOD)`` inside an isolated temp cwd."""
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            health_path = self._seed(tmp_path)
            try:
                os.chdir(tmp_path)
                writer(self.PERIOD)
            finally:
                os.chdir(cwd)
            return json.loads(health_path.read_text())

    def _assert_exact_contract(self, health: dict, writer_name: str):
        keys = set(health.get("endpoints", {}))
        self.assertEqual(
            keys, set(ALLOWED_ENDPOINT_KEYS),
            f"§7: {writer_name} must produce EXACTLY the allow-listed "
            f"endpoint keys. Got {sorted(keys)}; expected "
            f"{sorted(ALLOWED_ENDPOINT_KEYS)}.",
        )
        # And no retired key survived under any spelling.
        self.assertEqual(
            keys & set(RETIRED_ENDPOINT_KEYS), set(),
            f"§7: {writer_name} resurrected retired key(s): "
            f"{sorted(keys & set(RETIRED_ENDPOINT_KEYS))}",
        )

    # -- compute_dmi -------------------------------------------------------

    def test_compute_dmi_writer_produces_exact_key_set(self):
        from scripts.compute_dmi import update_health_json
        health = self._run_writer(update_health_json)
        self._assert_exact_contract(health, "compute_dmi.update_health_json")

    def test_compute_dmi_writer_never_emits_latest_with_ci(self):
        """§7: the specific key the audit found being conditionally restored."""
        from scripts.compute_dmi import update_health_json
        health = self._run_writer(update_health_json)
        self.assertNotIn(
            "latest_with_ci", health.get("endpoints", {}),
            "§7: latest_with_ci must not be resurrected.",
        )

    def test_compute_dmi_writer_emits_latest_with_ci_even_when_file_exists(self):
        """The defect was presence-driven: an on-disk file flipped the surface.

        Seed the `_with_ci` artifact the old writer keyed on, and assert
        the endpoint STILL does not appear. This is the regression that
        a source-string test could never express.
        """
        from scripts.compute_dmi import update_health_json
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            health_path = self._seed(tmp_path)
            outputs = tmp_path / "data" / "outputs"
            outputs.mkdir(parents=True, exist_ok=True)
            (outputs / f"dmi_release_{self.PERIOD}_with_ci.json").write_text("{}")
            try:
                os.chdir(tmp_path)
                update_health_json(self.PERIOD)
            finally:
                os.chdir(cwd)
            health = json.loads(health_path.read_text())
        self.assertNotIn(
            "latest_with_ci", health.get("endpoints", {}),
            "§7: an on-disk _with_ci artifact must NOT re-create the "
            "retired health endpoint.",
        )
        self._assert_exact_contract(health, "compute_dmi (with _with_ci on disk)")

    def test_compute_dmi_writer_updates_the_period_endpoints(self):
        """The writer must still do its job, not merely strip keys."""
        from scripts.compute_dmi import update_health_json
        health = self._run_writer(update_health_json)
        self.assertEqual(
            health["endpoints"]["latest"],
            f"/data/outputs/dmi_release_{self.PERIOD}.json",
        )
        self.assertEqual(
            health["endpoints"]["latest_slack_plus"],
            f"/data/outputs/dmi_release_{self.PERIOD}_slack_plus.json",
        )
        self.assertEqual(health["latest_period"], self.PERIOD)

    # -- backfill_releases -------------------------------------------------

    def test_backfill_writer_produces_exact_key_set(self):
        from scripts.backfill_releases import update_health_json
        health = self._run_writer(update_health_json)
        self._assert_exact_contract(
            health, "backfill_releases.update_health_json"
        )

    def test_backfill_writer_never_emits_latest_with_ci(self):
        from scripts.backfill_releases import update_health_json
        health = self._run_writer(update_health_json)
        self.assertNotIn("latest_with_ci", health.get("endpoints", {}))

    def test_backfill_writer_updates_the_period_endpoints(self):
        from scripts.backfill_releases import update_health_json
        health = self._run_writer(update_health_json)
        self.assertEqual(
            health["endpoints"]["latest"],
            f"/data/outputs/dmi_release_{self.PERIOD}.json",
        )
        self.assertEqual(health["latest_period"], self.PERIOD)

    # -- both --------------------------------------------------------------

    def test_both_writers_agree_on_the_endpoint_surface(self):
        """Two writers must not drift into two different contracts."""
        from scripts.compute_dmi import update_health_json as w1
        from scripts.backfill_releases import update_health_json as w2
        self.assertEqual(
            set(self._run_writer(w1)["endpoints"]),
            set(self._run_writer(w2)["endpoints"]),
        )

    def test_seed_is_not_vacuous(self):
        """The fixture must really contain every retired key.

        Without this, adding a key to RETIRED_ENDPOINT_KEYS while
        forgetting the fixture would leave the writer tests passing
        without ever exercising the new key.
        """
        missing = set(RETIRED_ENDPOINT_KEYS) - set(self.SEEDED_ENDPOINTS)
        self.assertEqual(
            missing, set(),
            f"§7: seed fixture is missing retired key(s) {sorted(missing)}; "
            f"the writer tests would not exercise them.",
        )

    def test_seed_covers_every_allowed_key(self):
        missing = set(ALLOWED_ENDPOINT_KEYS) - set(self.SEEDED_ENDPOINTS)
        self.assertEqual(
            missing, set(),
            f"§7: seed fixture is missing allowed key(s) {sorted(missing)}.",
        )


if __name__ == "__main__":
    unittest.main()
