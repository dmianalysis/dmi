#!/usr/bin/env python3
"""Pinned SSH host authentication (Round-4 §3).

Why `ssh-keyscan` had to go
---------------------------
The previous implementation required `ssh-keyscan` to exit zero and
return a non-empty key before writing it to `known_hosts`. That closed a
real hole — `ssh-keyscan` exits 0 when it cannot reach the host, so an
empty `known_hosts` had been possible — but it did not authenticate
anything.

`ssh-keyscan` asks whoever answers the connection to introduce itself,
and then believes the answer. An attacker positioned to intercept simply
answers; their key lands in `known_hosts` as trusted; and
`StrictHostKeyChecking=yes` then verifies the session against the
attacker's key, faithfully. This is trust-on-first-use on every run,
which is the weakest form of it — there is not even a second run to
notice the key changed.

The expected key is now supplied out of band through a secret, and
validated against the host and port the deployment will actually
contact. No test here touches the network.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from scripts.install_known_hosts import (
    HostPinError,
    expected_host_tokens,
    fingerprint_of,
    install,
    parse_known_hosts,
    validate_hosts_match,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

HOST = "ssh.example.org"
PORT = "1394"
KEY_B64 = (
    "AAAAC3NzaC1lZDI1NTE5AAAAIJmVOZmVOZmVOZmVOZmVOZmVOZmVOZmVOZmVOZmVOZmV"
)
GOOD_LINE = f"[{HOST}]:{PORT} ssh-ed25519 {KEY_B64}"


class _Target:
    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        return Path(self._tmp.name) / "known_hosts"

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


class TestPinnedMaterialIsRequired(unittest.TestCase):
    """§3: absent material is a hard failure, never a scan."""

    def test_no_material_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError) as ctx:
                install(HOST, PORT, kh)
            self.assertIn("no pinned host material", str(ctx.exception))
            self.assertFalse(kh.exists())

    def test_empty_material_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError):
                install(HOST, PORT, kh, known_hosts_data="   \n\n")
            self.assertFalse(kh.exists())

    def test_comment_only_material_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError) as ctx:
                install(HOST, PORT, kh,
                        known_hosts_data="# just a comment\n")
            self.assertIn("no usable known_hosts entry", str(ctx.exception))

    def test_missing_host_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError) as ctx:
                install("", PORT, kh, known_hosts_data=GOOD_LINE)
            self.assertIn("no deployment host", str(ctx.exception))


class TestMalformedMaterialIsRejected(unittest.TestCase):
    """§3: malformed pinned material must fail, not be written through."""

    def test_too_few_fields_fails(self):
        with self.assertRaises(HostPinError) as ctx:
            parse_known_hosts("justonefield")
        self.assertIn("malformed", str(ctx.exception))

    def test_implausible_key_type_fails(self):
        with self.assertRaises(HostPinError) as ctx:
            parse_known_hosts(f"[{HOST}]:{PORT} banana {KEY_B64}")
        self.assertIn("implausible key type", str(ctx.exception))

    def test_non_base64_key_fails(self):
        with self.assertRaises(HostPinError) as ctx:
            parse_known_hosts(f"[{HOST}]:{PORT} ssh-ed25519 !!!nope!!!")
        self.assertIn("base64", str(ctx.exception))

    def test_malformed_material_is_not_written(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError):
                install(HOST, PORT, kh, known_hosts_data="garbage")
            self.assertFalse(
                kh.exists(),
                "§3: a malformed pin must not leave a known_hosts behind",
            )


class TestHostAndPortConsistency(unittest.TestCase):
    """§3: material must match the host AND port actually contacted."""

    def test_wrong_host_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError) as ctx:
                install(HOST, PORT, kh,
                        known_hosts_data=f"[evil.example]:{PORT} ssh-ed25519 {KEY_B64}")
            self.assertIn("does not match the configured target",
                          str(ctx.exception))

    def test_wrong_port_fails(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError):
                install(HOST, PORT, kh,
                        known_hosts_data=f"[{HOST}]:22 ssh-ed25519 {KEY_B64}")

    def test_bare_hostname_is_rejected_for_a_nonstandard_port(self):
        """OpenSSH writes bare names only for port 22."""
        with self.assertRaises(HostPinError):
            validate_hosts_match(
                parse_known_hosts(f"{HOST} ssh-ed25519 {KEY_B64}"),
                HOST, PORT,
            )

    def test_bare_hostname_is_accepted_for_port_22(self):
        validate_hosts_match(
            parse_known_hosts(f"{HOST} ssh-ed25519 {KEY_B64}"), HOST, "22"
        )

    def test_expected_tokens(self):
        self.assertEqual(expected_host_tokens(HOST, "1394"),
                         {f"[{HOST}]:1394"})
        self.assertEqual(expected_host_tokens(HOST, "22"),
                         {f"[{HOST}]:22", HOST})

    def test_comma_separated_host_list_is_accepted(self):
        line = f"[{HOST}]:{PORT},[203.0.113.9]:{PORT} ssh-ed25519 {KEY_B64}"
        validate_hosts_match(parse_known_hosts(line), HOST, PORT)


class TestSuccessfulPinning(unittest.TestCase):
    """The positive path, so the negatives are not vacuous."""

    def test_valid_material_is_installed(self):
        with _Target() as kh:
            install(HOST, PORT, kh, known_hosts_data=GOOD_LINE)
            self.assertTrue(kh.is_file())
            self.assertIn(KEY_B64, kh.read_text())

    def test_installed_file_is_owner_only(self):
        with _Target() as kh:
            install(HOST, PORT, kh, known_hosts_data=GOOD_LINE)
            self.assertEqual(kh.stat().st_mode & 0o777, 0o600)

    def test_installation_needs_no_network(self):
        """Proven by construction: no subprocess on this path.

        `install` only shells out when a fingerprint scan is explicitly
        requested, which these tests never do.
        """
        with _Target() as kh:
            install(HOST, PORT, kh, known_hosts_data=GOOD_LINE)
            self.assertTrue(kh.is_file())

    def test_fingerprint_helper_matches_openssh_format(self):
        fp = fingerprint_of("ssh-ed25519", KEY_B64)
        self.assertTrue(fp.startswith("SHA256:"))
        self.assertNotIn("=", fp, "OpenSSH strips base64 padding")


class TestFingerprintScanRequiresOptIn(unittest.TestCase):
    """§3: fetching a key and checking a fingerprint is opt-in only."""

    def test_fingerprint_without_opt_in_fails_without_network(self):
        with _Target() as kh:
            with self.assertRaises(HostPinError) as ctx:
                install(HOST, PORT, kh, fingerprint="SHA256:abc")
            self.assertIn("--allow-fingerprint-scan", str(ctx.exception))

    def test_literal_material_takes_precedence_over_fingerprint(self):
        """With both supplied, the stronger one is used and no scan runs."""
        with _Target() as kh:
            install(HOST, PORT, kh,
                    known_hosts_data=GOOD_LINE,
                    fingerprint="SHA256:whatever",
                    allow_fingerprint_scan=False)
            self.assertIn(KEY_B64, kh.read_text())


class TestNoDynamicTrustAnywhere(unittest.TestCase):
    """§3: no deployment or destructive path may scan for trust."""

    def _executable_lines(self, path: Path):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            yield stripped

    def test_withdrawal_tool_requires_pinned_material(self):
        src = (REPO_ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        self.assertIn(
            "from scripts.install_known_hosts import", src,
            "§3: the destructive withdrawal tool must obtain pinned host "
            "material, not acquire trust itself.",
        )

    def test_withdrawal_tool_does_not_scan_for_trust(self):
        import ast
        src = (REPO_ROOT / "scripts" / "withdraw_remote_artifacts.py").read_text()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                 ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)
        offenders = [
            n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value not in docstrings and "ssh-keyscan" in n.value
        ]
        self.assertEqual(
            offenders, [],
            f"§3: the withdrawal tool must not invoke ssh-keyscan: "
            f"{offenders}",
        )

    def test_only_the_pinned_installer_may_invoke_keyscan(self):
        import ast
        offenders = []
        for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
            if path.name == "install_known_hosts.py":
                continue
            tree = ast.parse(path.read_text())
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef,
                                     ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc = ast.get_docstring(node, clean=False)
                    if doc:
                        docstrings.add(doc)
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and \
                        isinstance(node.value, str) and \
                        node.value not in docstrings and \
                        "ssh-keyscan" in node.value:
                    offenders.append(f"{path.name}: {node.value!r}")
        self.assertEqual(offenders, [], f"§3: offenders: {offenders}")

    def test_runbook_does_not_instruct_operators_to_scan(self):
        runbook = REPO_ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md"
        offenders = [
            line for line in self._executable_lines(runbook)
            if "ssh-keyscan" in line and not line.startswith((">", "*", "-"))
        ]
        self.assertEqual(
            offenders, [],
            f"§3: the runbook must not tell an operator to scan for "
            f"trust: {offenders}",
        )

    def test_runbook_documents_pinned_material(self):
        runbook = (REPO_ROOT / "docs" / "repair"
                   / "REMOTE_WITHDRAWAL.md").read_text()
        self.assertIn("scripts.install_known_hosts", runbook)
        self.assertIn("DMI_KNOWN_HOSTS_DATA", runbook)

    def test_strict_host_key_checking_is_never_disabled(self):
        import ast
        offenders = []
        for path in sorted((REPO_ROOT / "scripts").glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Constant) and \
                        isinstance(node.value, str) and \
                        "StrictHostKeyChecking=no" in node.value:
                    offenders.append(path.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()


class TestRunbookExamplesAllUseThePinnedFile(unittest.TestCase):
    """Every executable SSH/rsync example in the runbook must be pinned.

    The runbook installs validated host material into `$KNOWN_HOSTS`, and
    the main commands referenced it correctly — but the recovery command
    at the end reverted to `$HOME/.ssh/known_hosts`.

    That was the worst possible placement for the inconsistency. Recovery
    runs when something has already gone wrong, under time pressure, and
    it is exactly when an operator reaches for a familiar command without
    re-reading it. Authenticating a restore against whatever the default
    file happens to hold reintroduces, at the critical moment, the
    trust-on-first-use problem the pinning exists to remove.
    """

    RUNBOOK = REPO_ROOT / "docs" / "repair" / "REMOTE_WITHDRAWAL.md"
    PINNED = "UserKnownHostsFile=$KNOWN_HOSTS"

    @classmethod
    def setUpClass(cls):
        cls.text = cls.RUNBOOK.read_text()
        cls.lines = cls.text.splitlines()

    def _fenced_code_lines(self):
        """Lines inside ``` fences — the parts an operator would run."""
        inside = False
        for line in self.lines:
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                yield line

    def test_runbook_has_executable_ssh_examples(self):
        """Non-vacuity: the assertions below need something to inspect."""
        found = [
            ln for ln in self._fenced_code_lines()
            if "UserKnownHostsFile" in ln
        ]
        self.assertGreaterEqual(
            len(found), 2,
            "expected multiple pinned SSH examples in the runbook; if none "
            "are found the checks below pass for the wrong reason.",
        )

    def test_every_executable_example_uses_the_pinned_file(self):
        offenders = [
            ln.strip() for ln in self._fenced_code_lines()
            if "UserKnownHostsFile" in ln and self.PINNED not in ln
        ]
        self.assertEqual(
            offenders, [],
            f"§2 (cleanup): every SSH/rsync example must use "
            f"{self.PINNED}. Offenders: {offenders}",
        )

    def test_no_example_falls_back_to_the_default_known_hosts(self):
        offenders = [
            ln.strip() for ln in self._fenced_code_lines()
            if "known_hosts" in ln
            and "$HOME/.ssh/known_hosts" in ln
        ]
        self.assertEqual(
            offenders, [],
            f"§2 (cleanup): no runbook command may fall back to the "
            f"default known_hosts. Offenders: {offenders}",
        )

    def test_recovery_path_specifically_is_pinned(self):
        """The regression that motivated this class."""
        idx = self.text.find("restore from the Step 1 backup")
        self.assertGreater(idx, 0, "recovery section not found")
        recovery = self.text[idx:idx + 1400]
        self.assertIn(
            self.PINNED, recovery,
            "§2 (cleanup): the recovery rsync must use the pinned file.",
        )
        self.assertNotIn("$HOME/.ssh/known_hosts", recovery)

    def test_recovery_section_explains_why_the_pinned_file_matters(self):
        idx = self.text.find("restore from the Step 1 backup")
        recovery = self.text[idx:idx + 1400].lower()
        self.assertIn(
            "not** the default", recovery,
            "the recovery section should say plainly that the default "
            "file is not to be substituted.",
        )

    def test_every_ssh_example_also_requires_strict_checking(self):
        offenders = [
            ln.strip() for ln in self._fenced_code_lines()
            if "UserKnownHostsFile" in ln
            and "StrictHostKeyChecking=yes" not in ln
        ]
        self.assertEqual(offenders, [], f"offenders: {offenders}")
