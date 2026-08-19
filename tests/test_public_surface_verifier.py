#!/usr/bin/env python3
"""The public verifier must never mistake a blocked client for evidence.

The 2026-08-19 withdrawal run made the failure mode concrete. Every
withdrawn URL returned 403 — and so did all eleven known-good operational
controls, and so did the contract fetch. The verifier of the day did two
things right and one thing wrong: it refused to read 403 as withdrawal,
and it failed the step; but it labelled the operational surface
"degraded", which pointed the operator at a production incident that was
not happening.

Uniform refusal across resources that certainly exist is a statement
about the client, not the site. These tests pin that distinction, along
with the fail-closed classification that surrounds it.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from scripts.verify_public_surface import (
    CLIENT_BLOCK_THRESHOLD,
    DIAGNOSTIC_HEADERS,
    EXPECTED_RELEASE_ID,
    EXPECTED_SPECS,
    OPERATIONAL_ENDPOINTS,
    USER_AGENT,
    WITHDRAWN_STATUSES,
    Response,
    check_content,
    classify_client_accessibility,
    classify_withdrawn,
)

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "scripts" / "verify_public_surface.py"


class TestWithdrawnClassification(unittest.TestCase):
    """Only two outcomes are acceptable, and 403 is not one of them."""

    def test_404_and_410_are_accepted_as_withdrawn(self):
        for status in (404, 410):
            with self.subTest(status=status):
                verdict, ok = classify_withdrawn(status, origin_absent=False)
                self.assertTrue(ok)
                self.assertEqual(verdict, "withdrawn")

    def test_200_is_a_cache_condition_only_with_confirmed_origin_absence(self):
        verdict, ok = classify_withdrawn(200, origin_absent=True)
        self.assertTrue(ok)
        self.assertEqual(verdict, "cached_after_origin_deletion")

    def test_200_without_origin_confirmation_fails(self):
        verdict, ok = classify_withdrawn(200, origin_absent=False)
        self.assertFalse(ok)
        self.assertIn("not_confirmed_absent", verdict)

    def test_403_never_proves_withdrawal(self):
        for origin_absent in (False, True):
            with self.subTest(origin_absent=origin_absent):
                verdict, ok = classify_withdrawn(403, origin_absent)
                self.assertFalse(
                    ok,
                    "a refused request says nothing about the resource",
                )
                self.assertIn("client_refused", verdict)

    def test_401_never_proves_withdrawal(self):
        verdict, ok = classify_withdrawn(401, origin_absent=True)
        self.assertFalse(ok)
        self.assertIn("client_refused", verdict)

    def test_network_error_fails_closed(self):
        verdict, ok = classify_withdrawn(0, origin_absent=True)
        self.assertFalse(ok)
        self.assertIn("network", verdict)

    def test_redirects_fail_closed(self):
        for status in (301, 302, 307, 308):
            with self.subTest(status=status):
                verdict, ok = classify_withdrawn(status, origin_absent=True)
                self.assertFalse(ok)
                self.assertIn("redirect", verdict)

    def test_5xx_fails_closed(self):
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                self.assertFalse(classify_withdrawn(status, True)[1])

    def test_only_404_and_410_are_in_the_withdrawn_set(self):
        self.assertEqual(set(WITHDRAWN_STATUSES), {404, 410})


class TestClientBlockedClassification(unittest.TestCase):
    """Uniform refusal is a client problem, not an outage."""

    def _rows(self, statuses):
        return [{"url": f"/u{i}", "status": s} for i, s in enumerate(statuses)]

    def test_uniform_403_is_classified_as_client_blocked(self):
        result = classify_client_accessibility(
            self._rows([403] * 11), self._rows([403] * 21)
        )
        self.assertTrue(result["blocked"])
        self.assertEqual(result["status"], 403)
        self.assertIn("blocked", result["reason"])

    def test_uniform_403_is_not_called_operational_degradation(self):
        """The message must deny degradation, not merely avoid the word.

        Asserting the substring "degraded" is absent would be wrong: the
        correct message says "NOT that the public surface is degraded",
        and a check that forbade the word would push the text toward
        being vaguer rather than clearer.
        """
        result = classify_client_accessibility(
            self._rows([403] * 11), self._rows([403] * 21)
        )
        self.assertIn("not that the public surface is degraded",
                      result["reason"])
        self.assertIn("blocked", result["reason"])
        self.assertIn("inconclusive", result["reason"])
        self.assertIn("not a pass", result["reason"])

    def test_the_2026_08_19_pattern_is_recognised(self):
        """The exact observed run: 11 operational + 21 withdrawn, all 403."""
        result = classify_client_accessibility(
            self._rows([403] * 11), self._rows([403] * 21)
        )
        self.assertTrue(result["blocked"])
        self.assertEqual(result["operational_total"], 11)
        self.assertEqual(result["withdrawn_with_same_status"], 21)

    def test_healthy_operational_controls_are_not_blocked(self):
        result = classify_client_accessibility(
            self._rows([200] * 11), self._rows([404] * 21)
        )
        self.assertFalse(result["blocked"])

    def test_genuine_degradation_is_not_masked_as_a_block(self):
        """A 500 across the site is an outage, not a refusal."""
        result = classify_client_accessibility(
            self._rows([500] * 11), self._rows([500] * 21)
        )
        self.assertFalse(
            result["blocked"],
            "5xx is degradation, not a client refusal; masking it as a "
            "block would hide a real outage",
        )

    def test_one_failing_endpoint_is_not_a_block(self):
        statuses = [200] * 10 + [403]
        result = classify_client_accessibility(
            self._rows(statuses), self._rows([404] * 21)
        )
        self.assertFalse(result["blocked"])

    def test_threshold_is_a_supermajority(self):
        self.assertGreaterEqual(CLIENT_BLOCK_THRESHOLD, 0.75)

    def test_no_controls_is_not_a_block(self):
        result = classify_client_accessibility([], [])
        self.assertFalse(result["blocked"])


class TestOperationalContentAssertions(unittest.TestCase):
    """A 200 carrying a block page is not a healthy endpoint."""

    def test_non_200_is_a_problem(self):
        self.assertIsNotNone(
            check_content("json", Response(403, {}, b"blocked"))
        )

    def test_empty_body_is_a_problem(self):
        self.assertIsNotNone(check_content("json", Response(200, {}, b"")))

    def test_invalid_json_is_a_problem(self):
        problem = check_content("json", Response(200, {}, b"<html>nope</html>"))
        self.assertIsNotNone(problem)
        self.assertIn("not valid JSON", problem)

    def test_valid_json_passes(self):
        self.assertIsNone(
            check_content("json", Response(200, {}, b'{"ok": true}'))
        )

    def test_non_html_body_for_html_endpoint_is_a_problem(self):
        self.assertIsNotNone(
            check_content("html", Response(200, {}, b'{"json": true}'))
        )

    def test_html_body_passes(self):
        self.assertIsNone(
            check_content("html", Response(200, {}, b"<!DOCTYPE html><html>"))
        )

    def test_every_operational_endpoint_declares_a_content_kind(self):
        for url, kind in OPERATIONAL_ENDPOINTS:
            with self.subTest(url=url):
                self.assertIn(kind, ("json", "html", "text", "binary"))


class TestCanonicalRequestHelper(unittest.TestCase):
    """All four retrieval paths must go through one helper."""

    @classmethod
    def setUpClass(cls):
        cls.src = MODULE.read_text()
        cls.tree = ast.parse(cls.src)

    def test_user_agent_is_stable_truthful_and_project_specific(self):
        self.assertIn("dmi-public-verifier", USER_AGENT)
        self.assertIn("github.com/dmianalysis/dmi", USER_AGENT)

    def test_user_agent_does_not_impersonate_a_browser(self):
        lowered = USER_AGENT.lower()
        for token in ("mozilla", "chrome", "safari", "firefox", "webkit",
                      "edge/", "gecko"):
            with self.subTest(token=token):
                self.assertNotIn(token, lowered)

    def test_only_one_urlopen_call_site(self):
        calls = [
            n for n in ast.walk(self.tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "urlopen"
        ]
        self.assertEqual(
            len(calls), 1,
            "every request must route through the canonical helper; "
            f"found {len(calls)} urlopen call sites",
        )

    def test_the_urlopen_call_is_inside_http_get(self):
        helper = next(n for n in ast.walk(self.tree)
                      if isinstance(n, ast.FunctionDef) and n.name == "http_get")
        inside = [
            n for n in ast.walk(helper)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "urlopen"
        ]
        self.assertEqual(len(inside), 1)

    def test_helper_uses_get_not_head(self):
        self.assertIn('method="GET"', self.src)
        self.assertNotIn('method="HEAD"', self.src)

    def test_helper_sends_the_expected_headers(self):
        for header in ("User-Agent", "Accept", "Cache-Control", "Pragma"):
            with self.subTest(header=header):
                self.assertIn(f'"{header}"', self.src)

    def test_cache_busting_is_retained(self):
        self.assertIn("cb=", self.src)

    def test_diagnostic_headers_are_captured(self):
        for header in ("Server", "CF-Ray", "CF-Cache-Status", "Age",
                       "Content-Type", "Location"):
            with self.subTest(header=header):
                self.assertIn(header, DIAGNOSTIC_HEADERS)

    def test_tls_verification_is_never_disabled(self):
        for token in ("ssl._create_unverified_context", "verify=False",
                      "CERT_NONE", "check_hostname = False"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.src)

    def test_no_403_bypass_or_embedded_credential(self):
        for token in ("Authorization", "cf_clearance", "__cf_bm",
                      "Cookie", "api_key", "token="):
            with self.subTest(token=token):
                self.assertNotIn(token, self.src)


class TestReportShape(unittest.TestCase):
    """Reports carry diagnostics, never response bodies."""

    def test_response_diagnostics_include_only_named_headers(self):
        response = Response(
            403, {"Server": "cloudflare", "CF-Ray": "abc", "Set-Cookie": "x"},
            b"<html>block page</html>",
        )
        diagnostics = response.diagnostics()
        self.assertIn("Server", diagnostics)
        self.assertIn("CF-Ray", diagnostics)
        self.assertNotIn("Set-Cookie", diagnostics)

    def test_diagnostics_never_include_the_body(self):
        response = Response(403, {"Server": "cloudflare"}, b"SECRET-BODY")
        self.assertNotIn("SECRET-BODY", json.dumps(response.diagnostics()))

    def test_no_report_field_stores_a_response_body(self):
        src = MODULE.read_text()
        self.assertNotIn('"body"', src)
        self.assertNotIn("row['body']", src)

    def test_report_separates_the_four_questions(self):
        src = MODULE.read_text()
        for field in ("origin_withdrawal", "withdrawn_urls",
                      "public_contract", "verifier_client"):
            with self.subTest(field=field):
                self.assertIn(field, src)


class TestContractEnforcement(unittest.TestCase):

    def test_contract_constants_are_pinned(self):
        self.assertEqual(EXPECTED_RELEASE_ID, "2026-07")
        self.assertEqual(set(EXPECTED_SPECS), {"baseline", "slack_plus"})

    def test_contract_problems_fail_the_run(self):
        src = MODULE.read_text()
        func = next(n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        body = ast.get_source_segment(src, func)
        self.assertIn("if contract_problems:", body)
        self.assertIn("failed = True", body)
        self.assertLess(body.index("if contract_problems:"),
                        body.index("if failed:"))

    def test_both_manifests_are_checked(self):
        src = MODULE.read_text()
        self.assertIn("latest.json", src)
        self.assertIn("specifications.json", src)

    def test_blocked_client_does_not_produce_a_false_contract_failure(self):
        """A refused fetch describes the client, not the contract."""
        src = MODULE.read_text()
        self.assertIn("not evaluated: the verification client was blocked",
                      src)


class TestDocstringsMatchBehaviour(unittest.TestCase):
    """Comments that contradict the code are worse than no comments."""

    def test_no_claim_that_only_one_outcome_passes(self):
        src = MODULE.read_text().lower()
        self.assertNotIn("only the first is a pass", src)

    def test_classifier_docstring_names_both_acceptable_outcomes(self):
        doc = classify_withdrawn.__doc__.lower()
        self.assertIn("two outcomes are acceptable", doc)
        self.assertIn("404/410", doc)
        self.assertIn("cache", doc)


if __name__ == "__main__":
    unittest.main()
