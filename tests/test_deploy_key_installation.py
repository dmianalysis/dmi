#!/usr/bin/env python3
"""Deployment private-key installation (hotfix).

The outage
----------
A production deployment failed on the runner with::

    Load key "/home/runner/.ssh/deploy_key": error in libcrypto

The workflows had been changed from ``echo "$IFASTNET_SSH_KEY" > …`` to
``printf '%s' "$IFASTNET_SSH_KEY" > …``. ``echo`` appends a trailing
newline; ``printf '%s'`` does not. OpenSSH requires the key file to end
with a newline after the closing ``-----END …-----`` line and rejects it
outright otherwise.

The change looked like a tightening — no stray whitespace in a secret —
and was in fact breaking. Nothing caught it because no test ever
installed a key: the workflows were checked for *shape* (strict host
checking, pinned known_hosts, correct gating) and never for whether the
bytes they wrote could actually be loaded.

These tests therefore generate **real** OpenSSH keys with ``ssh-keygen``
and run the real installer, because the defect lives precisely in the
byte-level handling that a mocked or string-compared test cannot see.

Note on the error text: the exact wording depends on the crypto backend
(``error in libcrypto`` on OpenSSL builds, ``invalid format`` on
LibreSSL). These tests assert on the ``ssh-keygen`` exit status and on
whether installation succeeds, not on the message, so they behave the
same on a runner and on a developer machine.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "scripts" / "install_deploy_key.sh"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

DEPLOY_WORKFLOWS = (
    "deploy_production.yml",
    "deploy_wp_plugins.yml",
    "deploy_web_dashboard.yml",
)

HAVE_SSH_KEYGEN = shutil.which("ssh-keygen") is not None


def _generate_key(directory: Path, passphrase: str = "") -> str:
    """Generate a genuine OpenSSH private key and return its text."""
    path = directory / "generated_key"
    subprocess.run(
        ["ssh-keygen", "-t", "ed25519", "-N", passphrase, "-C",
         "dmi-test-key", "-f", str(path), "-q"],
        check=True, capture_output=True,
    )
    return path.read_text()


def _install(key_material: str, dest: Path, home: Path):
    """Run the real installer with the secret in the environment."""
    env = dict(os.environ)
    env["IFASTNET_SSH_KEY"] = key_material
    env["HOME"] = str(home)
    return subprocess.run(
        ["bash", str(INSTALLER), str(dest)],
        env=env, capture_output=True, text=True,
    )


def _ssh_keygen_accepts(path: Path) -> bool:
    """Whether OpenSSH can actually parse the installed key."""
    return subprocess.run(
        ["ssh-keygen", "-y", "-P", "", "-f", str(path)],
        capture_output=True,
    ).returncode == 0


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not available")
class TestKeyInstallationAcceptsValidInput(unittest.TestCase):
    """Keys that should work, must work."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.dest = self.home / ".ssh" / "deploy_key"
        self.key = _generate_key(self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_key_with_terminal_newline_installs(self):
        self.assertTrue(self.key.endswith("\n"), "fixture assumption")
        result = _install(self.key, self.dest, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(_ssh_keygen_accepts(self.dest))

    def test_key_without_terminal_newline_is_repaired(self):
        """The exact outage input.

        This is the case that broke production: the secret's material
        written with no final newline. The installer must repair it
        rather than propagate a file OpenSSH will refuse.
        """
        stripped = self.key.rstrip("\n")
        self.assertFalse(stripped.endswith("\n"), "fixture assumption")

        # Prove the unrepaired form really is rejected, so the repair is
        # doing work rather than the key being tolerant.
        raw = self.dir / "unrepaired"
        raw.write_text(stripped)
        raw.chmod(0o600)
        self.assertFalse(
            _ssh_keygen_accepts(raw),
            "a key without its terminal newline must be rejected by "
            "ssh-keygen; if it is accepted here the outage cannot be "
            "reproduced and this test proves nothing.",
        )

        result = _install(stripped, self.dest, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            _ssh_keygen_accepts(self.dest),
            "the installer must add the terminal newline OpenSSH needs.",
        )

    def test_installed_key_ends_with_exactly_one_newline_run(self):
        result = _install(self.key.rstrip("\n"), self.dest, self.home)
        self.assertEqual(result.returncode, 0)
        data = self.dest.read_bytes()
        self.assertTrue(data.endswith(b"\n"))

    def test_crlf_input_is_normalised_and_installs(self):
        crlf = self.key.replace("\n", "\r\n")
        self.assertIn("\r", crlf, "fixture assumption")
        result = _install(crlf, self.dest, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(b"\r", self.dest.read_bytes())
        self.assertTrue(_ssh_keygen_accepts(self.dest))

    def test_crlf_without_terminal_newline_installs(self):
        """Both spellings of the same mistake, together."""
        crlf = self.key.replace("\n", "\r\n").rstrip("\r\n")
        result = _install(crlf, self.dest, self.home)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(_ssh_keygen_accepts(self.dest))

    def test_permissions_are_correct(self):
        _install(self.key, self.dest, self.home)
        self.assertEqual(self.dest.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.dest.parent.stat().st_mode & 0o777, 0o700)

    def test_validation_happens_before_any_network_use(self):
        """ssh-keygen validation must be in the installer itself."""
        src = INSTALLER.read_text()
        self.assertIn("ssh-keygen -y -P \"\"", src)
        self.assertNotIn("ssh-keyscan", src)
        self.assertNotIn("rsync", src)


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not available")
class TestKeyInstallationFailsClosed(unittest.TestCase):
    """Bad input must fail loudly, before any connection is attempted."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.dest = self.home / ".ssh" / "deploy_key"

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_secret_fails(self):
        env = dict(os.environ)
        env.pop("IFASTNET_SSH_KEY", None)
        env["HOME"] = str(self.home)
        result = subprocess.run(
            ["bash", str(INSTALLER), str(self.dest)],
            env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("IFASTNET_SSH_KEY", result.stderr)
        self.assertFalse(self.dest.exists())

    def test_empty_secret_fails(self):
        result = _install("", self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_whitespace_only_secret_fails(self):
        result = _install("   \n\t\n  ", self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_malformed_key_fails(self):
        result = _install(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nnot-real\n"
            "-----END OPENSSH PRIVATE KEY-----\n",
            self.dest, self.home,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(
            self.dest.exists(),
            "a key that fails validation must not be left on disk.",
        )

    def test_literal_backslash_n_key_fails(self):
        r"""A secret pasted with literal ``\n`` instead of real newlines.

        A common way to mangle a key when copying it into a secret box.
        It must fail here rather than at connection time.
        """
        key = _generate_key(self.dir).replace("\n", "\\n")
        self.assertIn("\\n", key)
        result = _install(key, self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_encrypted_key_fails_without_hanging(self):
        """A passphrase-protected key must fail, not block on a prompt."""
        encrypted = _generate_key(self.dir, passphrase="correct horse")
        result = subprocess.run(
            ["bash", str(INSTALLER), str(self.dest)],
            env={**os.environ, "IFASTNET_SSH_KEY": encrypted,
                 "HOME": str(self.home)},
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())

    def test_truncated_key_fails(self):
        key = _generate_key(self.dir)
        result = _install(key[: len(key) // 2], self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.dest.exists())


@unittest.skipUnless(HAVE_SSH_KEYGEN, "ssh-keygen not available")
class TestNoKeyMaterialIsEverPrinted(unittest.TestCase):
    """Diagnostics must describe the key, never reveal it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.dest = self.home / ".ssh" / "deploy_key"

    def tearDown(self):
        self._tmp.cleanup()

    def _secret_body_lines(self, key: str) -> list[str]:
        """The base64 body lines — the part that must never surface."""
        return [
            ln.strip() for ln in key.splitlines()
            if ln.strip() and not ln.startswith("-----") and len(ln.strip()) > 20
        ]

    def test_success_path_prints_no_key_material(self):
        key = _generate_key(self.dir)
        result = _install(key, self.dest, self.home)
        output = result.stdout + result.stderr
        for line in self._secret_body_lines(key):
            self.assertNotIn(line, output)

    def test_failure_path_prints_no_key_material(self):
        key = _generate_key(self.dir)
        mangled = key.replace("\n", "\\n")
        result = _install(mangled, self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        for line in self._secret_body_lines(key):
            self.assertNotIn(line, output)

    def test_encrypted_failure_prints_no_key_material(self):
        key = _generate_key(self.dir, passphrase="hunter2")
        result = _install(key, self.dest, self.home)
        self.assertNotEqual(result.returncode, 0)
        output = result.stdout + result.stderr
        for line in self._secret_body_lines(key):
            self.assertNotIn(line, output)

    def test_installer_never_cats_or_echoes_the_key_variable(self):
        """Scoped to executable lines.

        The installer's header comment quotes the old defective form in
        order to explain the outage, so a whole-file scan would flag the
        documentation of the bug as the bug — and the file would get
        "safer" by deleting the explanation of why it exists.
        """
        code = "\n".join(
            line for line in INSTALLER.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        for bad in ('echo "$IFASTNET_SSH_KEY"',
                    'cat "$DEST"', "echo $IFASTNET_SSH_KEY"):
            with self.subTest(pattern=bad):
                self.assertNotIn(bad, code)

    def test_comment_stripping_is_not_vacuous(self):
        """The scan must still see the installer's real code."""
        code = "\n".join(
            line for line in INSTALLER.read_text().splitlines()
            if not line.lstrip().startswith("#")
        )
        self.assertIn("install -d -m 700", code)
        self.assertIn("ssh-keygen -y -P", code)
        self.assertIn("chmod 600", code)


class TestWorkflowsUseTheCanonicalInstaller(unittest.TestCase):
    """Every deployment workflow must route through one implementation."""

    def _script(self, name: str) -> str:
        import yaml
        doc = yaml.safe_load((WORKFLOWS / name).read_text())
        return "\n".join(
            step.get("run", "")
            for job in (doc.get("jobs") or {}).values()
            for step in (job.get("steps") or [])
        )

    def test_installer_exists_and_is_executable(self):
        self.assertTrue(INSTALLER.is_file())
        self.assertTrue(os.access(INSTALLER, os.X_OK))

    def test_every_deploy_workflow_calls_the_installer(self):
        for name in DEPLOY_WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertIn(
                    "scripts/install_deploy_key.sh", self._script(name),
                    f"{name} must install the key through the canonical "
                    f"helper.",
                )

    def test_no_workflow_writes_the_key_inline(self):
        """The defective pattern must not reappear anywhere."""
        offenders = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if "IFASTNET_SSH_KEY" in stripped and (
                    ">" in stripped or "tee" in stripped
                ):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
        self.assertEqual(
            offenders, [],
            f"key material must only be written by the canonical helper: "
            f"{offenders}",
        )

    def test_no_workflow_uses_printf_percent_s_for_the_key(self):
        """Pin the exact regression."""
        offenders = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                if "printf '%s'" in line and "IFASTNET_SSH_KEY" in line:
                    offenders.append(f"{path.name}:{lineno}")
        self.assertEqual(
            offenders, [],
            f"`printf '%s'` drops the terminal newline OpenSSH requires: "
            f"{offenders}",
        )

    def test_every_ssh_command_uses_identities_only(self):
        import yaml
        for name in DEPLOY_WORKFLOWS:
            script = self._script(name)
            with self.subTest(workflow=name):
                for line in script.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if "ssh -i ~/.ssh/deploy_key" not in stripped:
                        continue
                    self.assertIn(
                        "IdentitiesOnly=yes", stripped,
                        f"{name}: every SSH command must offer only the "
                        f"configured deployment identity: {stripped}",
                    )

    def test_identities_only_check_is_not_vacuous(self):
        found = sum(
            1 for name in DEPLOY_WORKFLOWS
            for line in self._script(name).splitlines()
            if "ssh -i ~/.ssh/deploy_key" in line
        )
        self.assertGreaterEqual(
            found, 3,
            "expected an SSH command in each deployment workflow; if none "
            "are found the IdentitiesOnly check passes vacuously.",
        )

    def test_ssh_commands_still_require_strict_checking_and_pinned_hosts(self):
        """The hotfix must not weaken what the previous repair established."""
        for name in DEPLOY_WORKFLOWS:
            script = self._script(name)
            with self.subTest(workflow=name):
                self.assertIn("StrictHostKeyChecking=yes", script)
                self.assertIn(
                    "UserKnownHostsFile=$HOME/.ssh/dmi_known_hosts", script
                )


class TestDeploymentControlChangesTriggerADeployment(unittest.TestCase):
    """A fix to deployment must be able to deploy itself."""

    REQUIRED = (
        ".github/workflows/deploy_production.yml",
        ".github/workflows/deploy_web_dashboard.yml",
        ".github/workflows/deploy_wp_plugins.yml",
        "scripts/install_deploy_key.sh",
        "scripts/install_known_hosts.py",
        "scripts/prepare_deployment.py",
    )

    def _paths(self):
        import yaml
        doc = yaml.safe_load(
            (WORKFLOWS / "deploy_production.yml").read_text()
        )
        on = doc.get("on") or doc.get(True)
        return on["push"]["paths"]

    def test_every_deployment_control_file_is_in_the_trigger_set(self):
        paths = self._paths()
        missing = [f for f in self.REQUIRED if f not in paths]
        self.assertEqual(
            missing, [],
            f"a change to these files repairs deployment itself; if they "
            f"are not in the push path filter, merging the fix produces "
            f"no deployment run and the only way to exercise it is to "
            f"rerun the defective revision. Missing: {missing}",
        )

    def test_published_content_paths_are_still_covered(self):
        paths = self._paths()
        for required in ("data/outputs/**", "web/**", "deploy/**"):
            with self.subTest(path=required):
                self.assertIn(required, paths)

    def test_the_key_helper_specifically_triggers_deployment(self):
        """The file this hotfix adds must itself be a trigger."""
        self.assertIn("scripts/install_deploy_key.sh", self._paths())


if __name__ == "__main__":
    unittest.main()
