"""Python runtime policy for every GitHub Actions workflow.

The November 15, 2026 scheduled release run failed before any DMI code
ran: ``ubuntu-latest`` moved to Ubuntu 26.04, which has no Python 3.9
build, and ``actions/setup-python`` stopped the job. The October 2026
release was never prepared.

The repair moved the operational runtime to a supported Python instead of
pinning an older Ubuntu image. These tests hold that repair in place:

- every operational workflow declares the production runtime (3.12);
- PR CI tests the supported matrix (3.12 and 3.13) and parses every module
  at the minimum supported syntax level;
- each job checks the interpreter it got and fails if it is not the
  declared one, so nothing silently substitutes another version;
- dependencies come from a hash-pinned lock per interpreter in
  ``requirements-lock/``, never from the unpinned direct list;
- no job pins a specific Ubuntu release;
- a job may use the runner image's own Python only when it neither checks
  out the repository nor installs packages, so it cannot run DMI code.

Every rule is a function over the parsed workflow, and each has a
non-vacuity test that feeds it a deliberately bad workflow.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
LOCKS = ROOT / "requirements-lock"

#: The support policy. requirements-lock/README.md states the same values.
MINIMUM_PYTHON = "3.12"
PRODUCTION_PYTHON = "3.12"
CI_PYTHONS = ("3.12", "3.13")

#: Workflows that run DMI code and therefore must use the production runtime.
OPERATIONAL = (
    "monthly_dmi.yml",
    "deploy_production.yml",
    "deploy_web_dashboard.yml",
    "deploy_wp_plugins.yml",
    "inventory_withdrawn_core.yml",
    "verify_core_withdrawal_public.yml",
)
PR_CI = "pr_ci.yml"

SETUP_PYTHON = "actions/setup-python@"
VERSION_EXPR = "${{ env.PYTHON_VERSION }}"
MATRIX_EXPR = "${{ matrix.python-version }}"
LOCK_REF = "requirements-lock/python${PYTHON_VERSION}.txt"
ALLOWED_RUNNERS = {"ubuntu-latest", "macos-latest", "windows-latest"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))


def _logical_lines(script: str) -> list[str]:
    """Shell lines with backslash continuations joined and comments dropped."""
    out, buf = [], ""
    for raw in script.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        line = (buf + line).strip()
        buf = ""
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _resolve_versions(doc: dict, job: dict) -> list[str]:
    """The concrete PYTHON_VERSION values a job runs with."""
    value = (job.get("env") or {}).get("PYTHON_VERSION",
                                       (doc.get("env") or {}).get("PYTHON_VERSION"))
    if value is None:
        return []
    if str(value).strip() == MATRIX_EXPR:
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        return [str(v) for v in matrix.get("python-version") or []]
    return [str(value)]


def _runner_values(job: dict) -> list[str]:
    runs_on = job.get("runs-on")
    if isinstance(runs_on, str) and runs_on.strip() == "${{ matrix.os }}":
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        return [str(v) for v in matrix.get("os") or []]
    if isinstance(runs_on, list):
        return [str(v) for v in runs_on]
    return [str(runs_on)]


def runtime_violations(name: str, doc: dict, lock_dir: Path = LOCKS) -> list[str]:
    """Every runtime-policy violation in one parsed workflow."""
    found = []
    for job_name, job in (doc.get("jobs") or {}).items():
        where = f"{name}:{job_name}"
        if "uses" in job:
            # A reusable-workflow call has no runner or steps of its own;
            # the called workflow is checked as its own file.
            continue
        steps = job.get("steps") or []

        for runner in _runner_values(job):
            if runner not in ALLOWED_RUNNERS:
                found.append(f"{where}: runs-on {runner!r} pins a specific image; "
                             f"use one of {sorted(ALLOWED_RUNNERS)}")

        setup_idx = [i for i, s in enumerate(steps)
                     if str(s.get("uses", "")).startswith(SETUP_PYTHON)]
        runs = [str(s.get("run", "")) for s in steps]
        lines = [line for r in runs for line in _logical_lines(r)]
        uses_python = any(re.match(r"(\S+=\S+\s+)*python3?\b", line) for line in lines)
        installs = [line for line in lines if re.search(r"\bpip3? install\b", line)]

        if not setup_idx:
            checks_out = any(str(s.get("uses", "")).startswith("actions/checkout@")
                             for s in steps)
            if uses_python and (checks_out or installs):
                found.append(f"{where}: runs Python on the runner image's interpreter "
                             "while checking out the repository or installing "
                             "packages; use actions/setup-python with PYTHON_VERSION")
            continue

        versions = _resolve_versions(doc, job)
        if not versions:
            found.append(f"{where}: sets up Python without a PYTHON_VERSION")
        for v in versions:
            if v not in CI_PYTHONS:
                found.append(f"{where}: Python {v} is not a supported version {CI_PYTHONS}")
            if not (lock_dir / f"python{v}.txt").is_file():
                found.append(f"{where}: no lock file requirements-lock/python{v}.txt")

        for i in setup_idx:
            with_ = steps[i].get("with") or {}
            if str(with_.get("python-version", "")).strip() != VERSION_EXPR:
                found.append(f"{where}: setup-python must take python-version "
                             f"from {VERSION_EXPR}")
            nxt = steps[i + 1] if i + 1 < len(steps) else {}
            body = str(nxt.get("run", ""))
            if (nxt.get("name") != "Verify Python runtime"
                    or 'os.environ["PYTHON_VERSION"]' not in body
                    or "sys.exit(" not in body
                    or "python -m pip --version" not in body):
                found.append(f"{where}: the step after setup-python must be "
                             "'Verify Python runtime', print pip's version and exit "
                             "non-zero on an interpreter mismatch")

        if not installs:
            found.append(f"{where}: sets up Python but installs nothing from the lock")
        for line in installs:
            if "--upgrade pip" in line and " -r " not in f" {line} ":
                continue
            hashed = "--require-hashes" in line and f'-r "{LOCK_REF}"' in line
            constrained = f'-c "{LOCK_REF}"' in line
            if not (hashed or constrained):
                found.append(f"{where}: dependency install is not pinned to "
                             f"{LOCK_REF}: {line}")
            elif name != PR_CI and not hashed:
                found.append(f"{where}: an operational workflow must install the "
                             f"lock with --require-hashes: {line}")
            if "--only-binary=:all:" not in line:
                found.append(f"{where}: install must be wheels-only "
                             f"(--only-binary=:all:): {line}")
    return found


def lock_violations(path: Path, version: str) -> list[str]:
    """Problems with one lock file."""
    text = path.read_text()
    found = []
    header = "\n".join(text.splitlines()[:4])
    if f"with Python {version}" not in header:
        found.append(f"{path.name}: header does not say it was compiled with Python {version}")
    pins = re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", text, flags=re.M)
    if not pins:
        found.append(f"{path.name}: no pinned requirements")
    entries = re.split(r"\n(?=[A-Za-z0-9_.-]+[=<>!~ ])", text)
    for entry in entries:
        head = entry.strip().splitlines()[0] if entry.strip() else ""
        if not head or head.startswith("#"):
            continue
        if "==" not in head:
            found.append(f"{path.name}: requirement is not pinned with ==: {head}")
        if "--hash=sha256:" not in entry:
            found.append(f"{path.name}: requirement has no hash: {head}")
    return found


def _pins(path: Path) -> dict[str, str]:
    return {k.lower(): v for k, v in
            re.findall(r"^([A-Za-z0-9_.-]+)==([^\s\\]+)", path.read_text(), flags=re.M)}


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestSupportPolicy(unittest.TestCase):

    def test_policy_is_internally_consistent(self):
        self.assertEqual(MINIMUM_PYTHON, min(CI_PYTHONS, key=lambda v: tuple(map(int, v.split(".")))))
        self.assertIn(PRODUCTION_PYTHON, CI_PYTHONS)

    def test_operational_workflows_declare_the_production_runtime(self):
        for name in OPERATIONAL:
            with self.subTest(workflow=name):
                doc = _load(WORKFLOWS / name)
                self.assertEqual(str((doc.get("env") or {}).get("PYTHON_VERSION")),
                                 PRODUCTION_PYTHON)

    def test_pr_ci_tests_the_supported_matrix(self):
        job = _load(WORKFLOWS / PR_CI)["jobs"]["verify"]
        self.assertEqual(job["strategy"]["matrix"]["python-version"], list(CI_PYTHONS))
        self.assertIs(job["strategy"]["fail-fast"], False)
        self.assertEqual(job["env"]["PYTHON_VERSION"], MATRIX_EXPR)

    def test_syntax_gate_parses_at_the_minimum_supported_level(self):
        """The gate that stops newer syntax reaching production.

        It used to parse at (3, 9). With a 3.13 leg in the matrix, a
        3.13-only construct would pass the test suite there, so the gate
        must parse at the minimum supported level, not the newest one.
        """
        script = "\n".join(str(s.get("run", "")) for s in
                           _load(WORKFLOWS / PR_CI)["jobs"]["verify"]["steps"])
        levels = set(re.findall(r"feature_version=\((\d+), (\d+)\)", script))
        self.assertEqual(levels, {tuple(MINIMUM_PYTHON.split("."))})

    def test_every_workflow_satisfies_the_runtime_policy(self):
        files = _workflow_files()
        self.assertGreaterEqual(len(files), 8)
        found = []
        for path in files:
            found += runtime_violations(path.name, _load(path))
        self.assertEqual(found, [], "\n".join(found))

    def test_every_operational_workflow_and_pr_ci_sets_up_python(self):
        for name in OPERATIONAL + (PR_CI,):
            with self.subTest(workflow=name):
                steps = [s for job in _load(WORKFLOWS / name)["jobs"].values()
                         for s in job.get("steps") or []]
                self.assertTrue(any(str(s.get("uses", "")).startswith(SETUP_PYTHON)
                                    for s in steps))


class TestLocks(unittest.TestCase):

    def test_each_supported_version_has_a_valid_lock(self):
        for version in CI_PYTHONS:
            with self.subTest(version=version):
                path = LOCKS / f"python{version}.txt"
                self.assertTrue(path.is_file(), f"missing {path}")
                self.assertEqual(lock_violations(path, version), [])

    def test_locks_carry_the_numerical_stack(self):
        for version in CI_PYTHONS:
            pins = _pins(LOCKS / f"python{version}.txt")
            for package in ("numpy", "pandas", "pyarrow", "openpyxl", "jsonschema"):
                with self.subTest(version=version, package=package):
                    self.assertIn(package, pins)
            with self.subTest(version=version, package="pandas major"):
                self.assertEqual(pins["pandas"].split(".")[0], "2")

    def test_production_lock_holds_the_last_verified_stack(self):
        """3.12 runs the same numerical libraries as the last 3.9 release.

        The October 15, 2026 run (Python 3.9.25) installed exactly these
        versions, and the migration verified that 3.12 reproduces published
        artifacts bit for bit with them. Changing them is a deliberate
        refresh: update this test in the same PR and show that
        test_published_values_reproduce still passes.
        """
        pins = _pins(LOCKS / f"python{PRODUCTION_PYTHON}.txt")
        self.assertEqual(
            {k: pins[k] for k in ("numpy", "pandas", "pyarrow", "openpyxl")},
            {"numpy": "2.0.2", "pandas": "2.3.3", "pyarrow": "21.0.0", "openpyxl": "3.1.5"},
        )

    def test_direct_requirements_cap_pandas_below_3(self):
        text = (ROOT / "requirements.txt").read_text()
        spec = re.search(r"^pandas([^\n#]*)", text, flags=re.M)
        self.assertIsNotNone(spec)
        self.assertIn("<3", spec.group(1).replace(" ", ""))


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestDetectorsAreNotVacuous(unittest.TestCase):
    """Each rule must fire on a workflow that breaks it."""

    GOOD = {
        "env": {"PYTHON_VERSION": "3.12"},
        "jobs": {"j": {
            "runs-on": "ubuntu-latest",
            "steps": [
                {"uses": "actions/checkout@v6"},
                {"uses": "actions/setup-python@v6",
                 "with": {"python-version": VERSION_EXPR}},
                {"name": "Verify Python runtime",
                 "run": 'python -m pip --version\npython - <<\'PY\'\nimport os, sys\n'
                        'want = os.environ["PYTHON_VERSION"]\nsys.exit(1)\nPY\n'},
                {"run": "python -m pip install --upgrade pip\n"
                        "python -m pip install --require-hashes --only-binary=:all: \\\n"
                        f'  -r "{LOCK_REF}"\n'},
            ],
        }},
    }

    def _mutate(self, fn):
        import copy
        doc = copy.deepcopy(self.GOOD)
        fn(doc)
        return runtime_violations("x.yml", doc)

    def test_good_workflow_is_clean(self):
        self.assertEqual(runtime_violations("x.yml", self.GOOD), [])

    def test_flags_python_3_9(self):
        found = self._mutate(lambda d: d["env"].update(PYTHON_VERSION="3.9"))
        self.assertTrue(any("3.9 is not a supported version" in f for f in found), found)
        self.assertTrue(any("no lock file" in f for f in found), found)

    def test_flags_a_pinned_ubuntu_image(self):
        found = self._mutate(lambda d: d["jobs"]["j"].update({"runs-on": "ubuntu-24.04"}))
        self.assertTrue(any("ubuntu-24.04" in f for f in found), found)

    def test_flags_a_literal_python_version(self):
        found = self._mutate(
            lambda d: d["jobs"]["j"]["steps"][1]["with"].update({"python-version": "3.12"}))
        self.assertTrue(any("python-version" in f for f in found), found)

    def test_flags_a_missing_runtime_check(self):
        found = self._mutate(lambda d: d["jobs"]["j"]["steps"].pop(2))
        self.assertTrue(any("Verify Python runtime" in f for f in found), found)

    def test_flags_an_unpinned_install(self):
        found = self._mutate(lambda d: d["jobs"]["j"]["steps"][3].update(
            {"run": "pip install -r requirements.txt"}))
        self.assertTrue(any("not pinned" in f for f in found), found)

    def test_flags_constraints_only_install_outside_pr_ci(self):
        found = self._mutate(lambda d: d["jobs"]["j"]["steps"][3].update(
            {"run": "python -m pip install --only-binary=:all: -r requirements.txt "
                    f'-c "{LOCK_REF}"'}))
        self.assertTrue(any("--require-hashes" in f for f in found), found)

    def test_flags_source_builds(self):
        found = self._mutate(lambda d: d["jobs"]["j"]["steps"][3].update(
            {"run": f'python -m pip install --require-hashes -r "{LOCK_REF}"'}))
        self.assertTrue(any("wheels-only" in f for f in found), found)

    def test_flags_image_python_running_repository_code(self):
        def strip_setup(d):
            steps = d["jobs"]["j"]["steps"]
            d["jobs"]["j"]["steps"] = [steps[0], {"run": "python -m scripts.finalize_release x"}]
        found = self._mutate(strip_setup)
        self.assertTrue(any("runner image's interpreter" in f for f in found), found)

    def test_image_python_without_checkout_or_install_is_allowed(self):
        doc = {"jobs": {"j": {"runs-on": "ubuntu-latest",
                              "steps": [{"run": "python <<'PY'\nprint(1)\nPY\n"}]}}}
        self.assertEqual(runtime_violations("x.yml", doc), [])

    def test_lock_check_flags_an_unhashed_pin(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "python3.12.txt"
            path.write_text("#\n# This file is autogenerated by pip-compile with Python 3.12\n"
                            "numpy==2.0.2 \\\n    --hash=sha256:abc\npandas==2.3.3\n")
            found = lock_violations(path, "3.12")
            self.assertEqual(len(found), 1, found)
            self.assertIn("pandas", found[0])
            self.assertTrue(lock_violations(path, "3.13"))


if __name__ == "__main__":
    unittest.main()
