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
  out the repository nor installs packages, so it cannot run DMI code;
- one named monitoring-only workflow, the missing-release watchdog, is
  the exception. It checks out the repository and runs one
  standard-library module on the image's ``python3``, and must not use
  ``actions/setup-python`` or the lock: it exists to report failures of
  that setup, so it cannot depend on it. It may run nothing else.

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

#: Monitoring-only workflows exempt from the runtime and lock rules, each
#: with the one standard-library module it may run on the image's python3.
#: Nothing else may be added here without the same justification.
MONITORING_ONLY = {
    "monthly_release_watchdog.yml": "scripts.monthly_release_watchdog",
}
#: Repository modules a monitoring-only module may import. Both must stay
#: standard-library only (TestMonitoringOnlyExemption checks it).
MONITORING_IMPORTS = {"scripts.unavailable_periods"}
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


def _python_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if re.match(r"(\S+=\S+\s+)*python[\d.]*\b", line)]


def monitoring_violations(where: str, steps: list, module: str) -> list[str]:
    """The rules for a monitoring-only job: image python3, stdlib, one module."""
    found = []
    for step in steps:
        uses = str(step.get("uses", ""))
        if uses and not uses.startswith("actions/checkout@"):
            found.append(f"{where}: a monitoring-only job may use only actions/checkout, "
                         f"not {uses}")
    lines = [line for s in steps for line in _logical_lines(str(s.get("run", "")))]
    for line in lines:
        if re.search(r"\bpip3?\b|requirements|PYTHON_VERSION", line):
            found.append(f"{where}: a monitoring-only job must not install packages or "
                         f"use the DMI lock: {line}")
    allowed = ("python3 --version", f"python3 -m {module}")
    runs_module = False
    for line in _python_lines(lines):
        if line == allowed[0]:
            continue
        if line == allowed[1] or line.startswith(allowed[1] + " "):
            runs_module = True
            continue
        found.append(f"{where}: a monitoring-only job may run only `{allowed[1]}` on the "
                     f"image's python3: {line}")
    if not runs_module:
        found.append(f"{where}: does not run `{allowed[1]}`")
    return found


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

        if name in MONITORING_ONLY:
            found += monitoring_violations(where, steps, MONITORING_ONLY[name])
            continue

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
        versions. The migration verified that, on the same machine, 3.12
        with them gives results identical to 3.9. Changing them is a deliberate
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



def _imports(path: Path) -> set[str]:
    import ast
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
    return found


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestMonitoringOnlyExemption(unittest.TestCase):
    """The watchdog's exemption is narrow, and the watchdog stays dependency-free."""

    GOOD = {"jobs": {"watch": {"runs-on": "ubuntu-latest", "steps": [
        {"uses": "actions/checkout@v6", "with": {"persist-credentials": False}},
        {"run": "python3 --version\n"},
        {"run": 'ARGS=(--dry-run)\npython3 -m scripts.monthly_release_watchdog "${ARGS[@]}"\n'},
    ]}}}
    NAME = "monthly_release_watchdog.yml"

    def _mutate(self, fn, name=NAME):
        import copy
        doc = copy.deepcopy(self.GOOD)
        fn(doc["jobs"]["watch"]["steps"])
        return runtime_violations(name, doc)

    def test_exemption_names_only_the_watchdog(self):
        self.assertEqual(MONITORING_ONLY, {self.NAME: "scripts.monthly_release_watchdog"})
        self.assertFalse(set(MONITORING_ONLY) & set(OPERATIONAL))
        self.assertNotIn(PR_CI, MONITORING_ONLY)
        self.assertTrue((WORKFLOWS / self.NAME).is_file())

    def test_watchdog_shape_is_clean(self):
        self.assertEqual(runtime_violations(self.NAME, self.GOOD), [])

    def test_the_same_shape_is_rejected_for_any_other_workflow(self):
        found = runtime_violations("monthly_dmi.yml", self.GOOD)
        self.assertTrue(any("runner image's interpreter" in f for f in found), found)

    def test_flags_setup_python(self):
        found = self._mutate(lambda s: s.insert(1, {"uses": "actions/setup-python@v6"}))
        self.assertTrue(any("only actions/checkout" in f for f in found), found)

    def test_flags_package_installation(self):
        for line in ("python3 -m pip install requests",
                     'pip install --require-hashes -r "requirements-lock/python3.12.txt"'):
            with self.subTest(line=line):
                found = self._mutate(lambda s: s.insert(1, {"run": line}))
                self.assertTrue(any("must not install packages" in f for f in found), found)

    def test_flags_running_any_other_python(self):
        for line in ("python3 -m scripts.compute_dmi", "python -m scripts.monthly_release_watchdog",
                     "python3 - <<'PY'", "python3.12 -m scripts.monthly_release_watchdog"):
            with self.subTest(line=line):
                found = self._mutate(lambda s: s.insert(2, {"run": line}))
                self.assertTrue(any("may run only" in f for f in found), found)

    def test_flags_a_workflow_that_no_longer_runs_the_module(self):
        found = self._mutate(lambda s: s.pop())
        self.assertTrue(any("does not run" in f for f in found), found)

    def test_watchdog_workflow_uses_no_setup_python_or_lock(self):
        text = (WORKFLOWS / self.NAME).read_text()
        doc = _load(WORKFLOWS / self.NAME)
        steps = [s for job in doc["jobs"].values() for s in job["steps"]]
        self.assertFalse(any(SETUP_PYTHON in str(s.get("uses", "")) for s in steps))
        self.assertNotIn("PYTHON_VERSION", doc.get("env") or {})
        code = "\n".join(line for s in steps for line in _logical_lines(str(s.get("run", ""))))
        self.assertNotIn("requirements", code)
        self.assertNotIn("pip", code)
        self.assertIn("python3 -m scripts.monthly_release_watchdog", text)

    def test_monitoring_modules_import_only_the_standard_library(self):
        import sys
        for module in set(MONITORING_ONLY.values()) | MONITORING_IMPORTS:
            path = ROOT / (module.replace(".", "/") + ".py")
            with self.subTest(module=module):
                for name in _imports(path):
                    top = name.split(".")[0]
                    if name in MONITORING_IMPORTS:
                        continue
                    self.assertIn(top, sys.stdlib_module_names,
                                  f"{module} imports {name}, which is not in the standard "
                                  "library; the watchdog must stay dependency-free")

    def test_watchdog_runs_without_site_packages(self):
        """Import and classify with site-packages disabled (-S)."""
        import subprocess
        import sys
        code = (
            "import sys\n"
            "assert not any('site-packages' in p for p in sys.path), sys.path\n"
            "from datetime import datetime, timezone\n"
            "from scripts import monthly_release_watchdog as wd\n"
            "ev = wd.Evidence(period='2026-11', as_of=datetime(2026, 12, 17, 16, 37, "
            "tzinfo=timezone.utc))\n"
            "v = wd.classify(ev)\n"
            "assert v.classification == wd.SCHEDULED_RUN_MISSING, v\n"
            "wd.render(ev, v)\n"
            "print('ok', sorted(m for m in sys.modules if m.split('.')[0] in "
            "('numpy', 'pandas', 'yaml', 'requests', 'jsonschema')))\n"
        )
        out = subprocess.run([sys.executable, "-S", "-E", "-c", code], cwd=ROOT,
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "ok []")


if __name__ == "__main__":
    unittest.main()
