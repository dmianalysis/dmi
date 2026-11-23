# Dependency locks

DMI declares its direct dependencies in [`../requirements.txt`](../requirements.txt).
That file is for people to read and edit. Nothing in CI or production
installs it directly.

Workflows install a hash-pinned lock compiled from it, one per supported
interpreter:

| File | Interpreter | Used by |
|---|---|---|
| [`python3.12.txt`](python3.12.txt) | Python 3.12 | Production and every operational workflow; PR CI |
| [`python3.13.txt`](python3.13.txt) | Python 3.13 | PR CI compatibility leg only |

## Python support policy

| | Version | Where it is enforced |
|---|---|---|
| Minimum supported | 3.12 | PR CI parses every module with `ast.parse(..., feature_version=(3, 12))` |
| Production runtime | 3.12 | `PYTHON_VERSION` in each operational workflow |
| CI-tested | 3.12 and 3.13 | the `verify` matrix in `.github/workflows/pr_ci.yml` |

`tests/test_python_runtime_policy.py` holds these values and fails if a
workflow drifts from them.

Each workflow job checks the interpreter it received in a step named
"Verify Python runtime". If `actions/setup-python` cannot provide the
declared version, the job stops there. Nothing substitutes another
interpreter.

## Operating systems

The **application**, meaning the calculator, the pipeline and the release
finalization, has no operating-system dependency. PR CI runs the
calculator and published-value reproduction tests on macOS and Windows as
a portability smoke test.

The **deployment tooling** is Linux-only by design. It uses SSH with
pinned host keys and rsync. The deployment workflows run on
`ubuntu-latest`. They do not depend on a particular Ubuntu release, so
no workflow pins one.

The production web host serves static files and runs no Python.

## Why the production lock holds these versions

The Python 3.12 lock reproduces the environment of the last successful
Python 3.9 production run, on October 15, 2026, package for package. The
only differences are two 3.9-only backports, `exceptiongroup` and `tomli`,
which 3.12 does not need. The numerical stack is unchanged:

| Package | Version |
|---|---|
| numpy | 2.0.2 |
| pandas | 2.3.3 |
| pyarrow | 21.0.0 |
| openpyxl | 3.1.5 |

The Python 3.13 lock is identical except for numpy 2.1.3. numpy 2.0.2
publishes no Python 3.13 wheels, and 2.1.3 is the earliest release that
does.

Both interpreters reproduce, bit for bit, every published release whose
inputs are committed to the repository. `tests/test_published_values_reproduce.py` checks this
on every PR.

`requirements.txt` caps pandas below 3. pandas 3 changes copy and
string-dtype semantics, and an unbounded `pandas>=2.0.0` would install
it on Python 3.12. Moving to pandas 3 is a methodology-review decision.

## Refreshing a lock deliberately

Locks change only on purpose, in their own PR. Compile them on Linux
x86-64, the production platform, because pip-compile resolves
platform-specific dependencies for the machine it runs on.

1. Edit `requirements.txt` if a direct dependency changes.
2. From the repository root, recompile each lock in a container:

   ```bash
   for v in 3.12 3.13; do
     docker run --rm --platform linux/amd64 -v "$PWD":/src -w /src python:$v-slim \
       sh -c "pip install -q pip==26.3 pip-tools==7.7.0 && \
              CUSTOM_COMPILE_COMMAND='see requirements-lock/README.md' \
              pip-compile --quiet --strip-extras --generate-hashes --no-emit-index-url \
                --output-file requirements-lock/python$v.txt requirements.txt"
   done
   ```

   pip-compile keeps every existing pin it can satisfy. To move one
   package, add `--upgrade-package NAME==VERSION`. To move everything,
   add `--upgrade`; this is rarely what you want.
3. Run the full suite on both interpreters. A change that moves any
   published value fails `tests/test_published_values_reproduce.py`.
   Do not regenerate the published files to make it pass. Revert the
   refresh and report the difference.
4. If numpy, pandas, pyarrow or openpyxl changed in the 3.12 lock, update
   `test_production_lock_holds_the_last_verified_stack` in
   `tests/test_python_runtime_policy.py` in the same PR and say why in
   the PR description.

## Adding or retiring a Python version

1. Compile `requirements-lock/pythonX.Y.txt` as above with
   `python:X.Y-slim`.
2. Update the `verify` matrix in `.github/workflows/pr_ci.yml`.
3. Update `CI_PYTHONS` and, if the minimum changes, `MINIMUM_PYTHON` in
   `tests/test_python_runtime_policy.py`, together with the
   `feature_version` level of the syntax gate in PR CI and its assertion
   in `tests/test_monthly_workflow_safety.py`.
4. Change the production runtime only after the new version has passed
   PR CI. Update `PYTHON_VERSION` in every operational workflow and
   `PRODUCTION_PYTHON` in the same PR.
5. Update this file and the Python version stated in `README.md`.

## Checking the installed versions

Every workflow log records the Python patch version, the pip version
and the output of `python -m pip freeze --all` right after installation.
