"""Missing-release watchdog: did this month's release preparation happen?

The scheduled ``monthly_dmi.yml`` run on the 15th prepares the release
for the previous calendar month and opens a review PR. On November 15,
2026 that run failed while setting up Python, no PR was opened, and
nothing noticed: ``release_gate_reminder.yml`` only watches PRs that
exist. This watchdog closes that gap.

From the 17th to the 28th of each month it works out which reference
period should have been prepared (the previous calendar month, from the
date alone), reads the GitHub evidence for it, classifies the outcome
and, when a human needs to act, opens or updates one GitHub Issue for
that period.

Evidence, all read through the GitHub REST API:

- runs of ``.github/workflows/monthly_dmi.yml`` in the cycle, with the
  failed job and step of any failed run;
- release PRs for the period: title ``DMI Release: YYYY-MM (not
  deployed)``, branch ``release/YYYY-MM[-suffix]``, labels ``release``
  and ``not-deployed``;
- ``data/outputs/releases.json`` on ``main``;
- ``registry/unavailable_periods.json`` on ``main``, checked with
  ``scripts.unavailable_periods``;
- for a run that failed at the CPI fetch in an approved period, the
  failed job's log, which must show the documented data limitation and
  nothing else before that failure is treated as expected.

The watchdog only reads, except for creating an Issue or commenting on
one. ``GitHubClient`` refuses every other write, so it cannot rerun a
workflow, merge or close a PR, change repository content or deploy. An
API error stops the run with a diagnostic; it is never read as "nothing
found".

It needs only the standard library and runs on the runner's own
``python3``: it must not depend on ``actions/setup-python`` or the DMI
dependency lock, whose failure it exists to report.

Run ``python3 -m scripts.monthly_release_watchdog --help``. Without
``--notify`` it is a dry run and makes no write at all.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Optional

if sys.version_info < (3, 9):  # pragma: no cover - the runner image's python3
    sys.exit("monthly_release_watchdog needs Python 3.9 or newer")

from scripts.unavailable_periods import (  # noqa: E402
    REGISTRY_RELATIVE_PATH,
    check_registry,
    month_index,
    release_id_for,
)

WORKFLOW_PATH = ".github/workflows/monthly_dmi.yml"
MANIFEST_PATH = "data/outputs/releases.json"
DEFAULT_BRANCH = "main"
ASSIGNEE = "tcwilliams79"

#: monthly_dmi.yml runs at 10:17 UTC on the 15th. The first check is
#: allowed after two more days.
SCHEDULE_DAY = 15
SCHEDULE_TIME = time(10, 17, tzinfo=timezone.utc)
GRACE = timedelta(days=2)
#: A run still queued or in progress this long after it was created is
#: reported as stalled. GitHub cancels a job after 6 hours.
STALL_AFTER = timedelta(hours=24)

#: Step names in monthly_dmi.yml that the classification relies on.
FETCH_STEP = "Fetch CPI data (live only)"
CREATE_PR_STEP = "Create Release PR (no deployment)"
#: The command that step runs, as it appears in the job log.
FETCH_COMMAND = "python -m scripts.test_bls_api"
#: Job logs larger than this are not read.
MAX_LOG_BYTES = 20_000_000

RELEASE_LABELS = {"release", "not-deployed"}

# Classifications. ALERTS need a human; the rest do not.
SCHEDULED_RUN_MISSING = "SCHEDULED_RUN_MISSING"
SCHEDULED_RUN_FAILED = "SCHEDULED_RUN_FAILED"
SCHEDULED_RUN_STALLED = "SCHEDULED_RUN_STALLED"
RUN_SUCCEEDED_NO_RELEASE_PR = "RUN_SUCCEEDED_NO_RELEASE_PR"
MERGED_BUT_NOT_IN_MANIFEST = "MERGED_BUT_NOT_IN_MANIFEST"
SCHEDULED_TRIGGER_MISSING = "SCHEDULED_TRIGGER_MISSING"
RELEASE_PR_PENDING_REVIEW = "RELEASE_PR_PENDING_REVIEW"
RELEASE_MERGED = "RELEASE_MERGED"
APPROVED_SOURCE_UNAVAILABLE = "APPROVED_SOURCE_UNAVAILABLE"
RUN_IN_PROGRESS = "RUN_IN_PROGRESS"
NOT_YET_DUE = "NOT_YET_DUE"

ALERTS = {
    SCHEDULED_RUN_MISSING,
    SCHEDULED_RUN_FAILED,
    SCHEDULED_RUN_STALLED,
    RUN_SUCCEEDED_NO_RELEASE_PR,
    MERGED_BUT_NOT_IN_MANIFEST,
    SCHEDULED_TRIGGER_MISSING,
}

ACTIONS = {
    SCHEDULED_RUN_MISSING: (
        "Check that the schedule in monthly_dmi.yml is intact and that Actions "
        "is enabled for the repository (GitHub disables schedules in a public "
        "repository after 60 days without activity). Then prepare the release "
        "manually: run "
        "Monthly DMI Preparation with mode=prepare_release, data_source=live and "
        "reference_period={period}."),
    SCHEDULED_RUN_FAILED: (
        "Open the run, read the failed step's log and fix the cause in a reviewed "
        "PR. Then prepare the release manually: run Monthly DMI Preparation with "
        "mode=prepare_release, data_source=live and reference_period={period}. "
        "If the official data for {period} do not exist, record that in "
        "registry/unavailable_periods.json in a reviewed PR; a failed run alone "
        "is not a reason to add an entry."),
    SCHEDULED_RUN_STALLED: (
        "The run has not finished. Cancel it in the Actions tab, then prepare the "
        "release manually with mode=prepare_release, data_source=live and "
        "reference_period={period}."),
    RUN_SUCCEEDED_NO_RELEASE_PR: (
        "The run reported success but no release PR for {period} exists. Check "
        "the 'Create Release PR (no deployment)' step and whether a PR was "
        "opened with a different title, branch or labels, or closed without "
        "merging."),
    MERGED_BUT_NOT_IN_MANIFEST: (
        "A release PR for {period} was merged, but data/outputs/releases.json on "
        "main has no {period} entry. Compare the merged PR with main before any "
        "deployment."),
    SCHEDULED_TRIGGER_MISSING: (
        "A release PR for {period} exists, so the release itself is not blocked, "
        "but no scheduled run of monthly_dmi.yml started this cycle. Check that "
        "the schedule is intact and Actions is enabled before next month."),
}

_PERIOD = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


class WatchdogError(RuntimeError):
    """Evidence could not be obtained. Never treated as an empty result."""


# --------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------

def expected_period(as_of: datetime) -> str:
    """The reference period prepared in the month of ``as_of`` (UTC)."""
    as_of = as_of.astimezone(timezone.utc)
    year, month = (as_of.year, as_of.month - 1) if as_of.month > 1 else (as_of.year - 1, 12)
    return f"{year:04d}-{month:02d}"


def cycle_start(as_of: datetime) -> datetime:
    """Midnight UTC on the 1st of the month of ``as_of``."""
    as_of = as_of.astimezone(timezone.utc)
    return datetime(as_of.year, as_of.month, 1, tzinfo=timezone.utc)


def scheduled_at(as_of: datetime) -> datetime:
    start = cycle_start(as_of)
    return datetime.combine(start.date().replace(day=SCHEDULE_DAY), SCHEDULE_TIME)


def parse_as_of(text: Optional[str], now: Callable[[], datetime]) -> datetime:
    """``YYYY-MM-DD`` means the end of that UTC day; a full ISO time is kept."""
    if not text:
        return now().astimezone(timezone.utc)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            day = date.fromisoformat(text)
            return datetime.combine(day, time(23, 59, 59, tzinfo=timezone.utc))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"--as-of must be YYYY-MM-DD or an ISO date-time: {exc}")
    if parsed.tzinfo is None:
        raise SystemExit("--as-of date-times must carry a UTC offset, e.g. 2026-12-17T16:37Z")
    return parsed.astimezone(timezone.utc)


def _ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --------------------------------------------------------------------------
# GitHub access
# --------------------------------------------------------------------------

Transport = Callable[[str, str, Optional[dict]], tuple[int, object]]

#: The only writes the watchdog may make: create an Issue, comment on one.
_ALLOWED_WRITES = re.compile(r"/repos/[^/]+/[^/]+/issues(/\d+/comments)?")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return redirects to the caller instead of following them.

    The job-log endpoint redirects to a signed storage URL. Following it
    here would send the token to that host as well.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(token: str, api_url: str) -> Transport:
    opener = urllib.request.build_opener(_NoRedirect)

    def send(method: str, path: str, body: Optional[dict]) -> tuple[int, object]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            api_url.rstrip("/") + path, data=data, method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "dmi-monthly-release-watchdog",
            })
        try:
            with opener.open(req, timeout=30) as resp:
                raw = resp.read()
                if "json" not in resp.headers.get("Content-Type", ""):
                    return resp.status, raw.decode("utf-8", errors="replace")
                return resp.status, json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                return exc.code, {"location": exc.headers.get("Location")}
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("message", detail)
            except (ValueError, AttributeError):
                pass
            return exc.code, {"message": str(detail)[:300]}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WatchdogError(f"{method} {path}: GitHub API unreachable: {exc}") from exc
    return send


def urllib_download(url: str) -> str:
    """Fetch a signed log URL. No token is sent; it is not GitHub's API host."""
    if not url.startswith("https://"):
        raise WatchdogError("job log redirect is not an https URL")
    req = urllib.request.Request(url, headers={"User-Agent": "dmi-monthly-release-watchdog"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read(MAX_LOG_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise WatchdogError(f"job log download failed: {exc}") from exc
    if len(raw) > MAX_LOG_BYTES:
        raise WatchdogError(f"job log is larger than {MAX_LOG_BYTES} bytes")
    return raw.decode("utf-8", errors="replace")


class GitHubClient:
    """Read access to one repository, plus Issue creation and comments.

    With ``allow_writes=False`` (a dry run) every write is refused before
    it is sent. With writes allowed, only the two Issue endpoints are
    permitted; anything else raises.
    """

    def __init__(self, repo: str, transport: Transport, allow_writes: bool = False,
                 download: Optional[Callable[[str], str]] = None):
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
            raise WatchdogError(f"repository must be owner/name, got {repo!r}")
        self.repo = repo
        self._send = transport
        self._download = download
        self.allow_writes = allow_writes

    def _path(self, suffix: str, params: Optional[dict] = None) -> str:
        path = f"/repos/{self.repo}{suffix}"
        if params:
            path += "?" + urllib.parse.urlencode(params)
        return path

    def get(self, suffix: str, params: Optional[dict] = None):
        path = self._path(suffix, params)
        status, payload = self._send("GET", path, None)
        if status != 200:
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise WatchdogError(f"GET {path} returned HTTP {status}: {message}")
        return payload

    def pages(self, suffix: str, params: dict, key: Optional[str] = None,
              stop: Optional[Callable[[dict], bool]] = None, max_pages: int = 20):
        """Every item across pages; ``stop(item)`` ends paging early."""
        items = []
        for page in range(1, max_pages + 1):
            payload = self.get(suffix, {**params, "per_page": 100, "page": page})
            batch = payload.get(key) if key else payload
            if not isinstance(batch, list):
                raise WatchdogError(f"GET {suffix}: expected a list"
                                    f"{' under ' + key if key else ''}, got {type(batch).__name__}")
            for item in batch:
                if stop and stop(item):
                    return items
                items.append(item)
            if len(batch) < 100:
                return items
        raise WatchdogError(f"GET {suffix}: more than {max_pages} pages; refusing to "
                            "guess from a partial listing")

    def post(self, suffix: str, body: dict):
        path = self._path(suffix)
        if not self.allow_writes:
            raise WatchdogError(f"dry run: refused POST {path}")
        if not _ALLOWED_WRITES.fullmatch(path):
            raise WatchdogError(f"the watchdog may only create Issues and Issue "
                                f"comments; refused POST {path}")
        status, payload = self._send("POST", path, body)
        if status not in (200, 201):
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise WatchdogError(f"POST {path} returned HTTP {status}: {message}")
        return payload

    def job_log(self, job_id: int) -> str:
        """The plain-text log of one Actions job (needs actions: read)."""
        path = self._path(f"/actions/jobs/{job_id}/logs")
        status, payload = self._send("GET", path, None)
        if status == 200 and isinstance(payload, str):
            return payload
        location = payload.get("location") if isinstance(payload, dict) else None
        if status in (301, 302, 303, 307, 308) and location:
            if self._download is None:
                raise WatchdogError(f"GET {path}: no way to download the redirected log")
            return self._download(location)
        message = payload.get("message") if isinstance(payload, dict) else payload
        raise WatchdogError(f"GET {path} returned HTTP {status}: {message}")

    def file_on_main(self, path: str):
        """Parsed JSON of a file on the default branch, or None if absent."""
        api_path = self._path(f"/contents/{path}", {"ref": DEFAULT_BRANCH})
        status, payload = self._send("GET", api_path, None)
        if status == 404:
            return None
        if status != 200 or not isinstance(payload, dict) or payload.get("encoding") != "base64":
            message = payload.get("message") if isinstance(payload, dict) else payload
            raise WatchdogError(f"GET {api_path} returned HTTP {status}: {message}")
        try:
            return json.loads(base64.b64decode(payload["content"]))
        except ValueError as exc:
            raise WatchdogError(f"{path} on {DEFAULT_BRANCH} is not valid JSON: {exc}") from exc


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------

@dataclass
class RunEvidence:
    id: int
    url: str
    event: str
    status: str
    conclusion: Optional[str]
    created_at: datetime
    branch: str
    failed_job: Optional[str] = None
    failed_job_id: Optional[int] = None
    failed_step: Optional[str] = None
    steps_before_failure_succeeded: bool = False
    #: "live" if the CPI fetch step ran, "fixture" if it was skipped,
    #: None when the run stopped before the mode was known.
    data_source: Optional[str] = None
    opened_pr: bool = False
    #: Set only for a fetch failure in an approved period, from the job log.
    source_explained: bool = False
    source_evidence: Optional[str] = None

    def describe(self) -> str:
        state = self.conclusion or self.status
        text = (f"run {self.id} ({self.event}, {self.created_at:%Y-%m-%d %H:%M} UTC, "
                f"branch {self.branch}): {state}")
        if self.failed_step or self.failed_job:
            text += f"; failed at job '{self.failed_job}', step '{self.failed_step or 'unknown'}'"
        if self.event == "workflow_dispatch":
            kind = {"live": "live release preparation", "fixture": "validate/fixture "
                    "(not release preparation)"}.get(self.data_source, "mode unknown")
            text += f"; {kind}"
        text += f" — {self.url}"
        if self.source_evidence:
            text += f"\n    - job log: {self.source_evidence}"
        return text


@dataclass
class PREvidence:
    number: int
    url: str
    title: str
    state: str
    merged_at: Optional[datetime]
    created_at: datetime
    branch: str

    @property
    def merged(self) -> bool:
        return self.merged_at is not None

    def describe(self) -> str:
        state = "merged" if self.merged else self.state
        return f"PR #{self.number} '{self.title}' ({state}, branch {self.branch}) — {self.url}"


@dataclass
class Evidence:
    period: str
    as_of: datetime
    workflow_url: str = ""
    scheduled_runs: list = field(default_factory=list)
    manual_runs: list = field(default_factory=list)
    release_prs: list = field(default_factory=list)
    closed_unmerged_prs: list = field(default_factory=list)
    manifest_ids: set = field(default_factory=set)
    manifest_found: bool = False
    registry_entry: Optional[dict] = None
    registry_problems: list = field(default_factory=list)

    @property
    def approved_unavailable(self) -> bool:
        return self.registry_entry is not None and not self.registry_problems


def _release_pr_matches(pr: dict, period: str) -> bool:
    title_ok = pr.get("title") == f"DMI Release: {period} (not deployed)"
    branch_ok = bool(re.fullmatch(rf"release/{period}(-[\w.-]+)?",
                                  (pr.get("head") or {}).get("ref", "")))
    labels = {label.get("name") for label in pr.get("labels") or []}
    base_ok = (pr.get("base") or {}).get("ref") == DEFAULT_BRANCH
    return title_ok and branch_ok and base_ok and RELEASE_LABELS <= labels


def _run_details(gh: GitHubClient, run: RunEvidence) -> None:
    jobs = gh.get(f"/actions/runs/{run.id}/jobs", {"per_page": 100}).get("jobs")
    if not isinstance(jobs, list):
        raise WatchdogError(f"run {run.id}: jobs listing is malformed")
    for job in jobs:
        steps = job.get("steps") or []
        by_name = {s.get("name"): s.get("conclusion") for s in steps}
        if FETCH_STEP in by_name:
            run.data_source = {"skipped": "fixture", None: None}.get(by_name[FETCH_STEP], "live")
        if by_name.get(CREATE_PR_STEP) == "success":
            run.opened_pr = True
        if job.get("conclusion") == "failure" and run.failed_job is None:
            run.failed_job = job.get("name")
            run.failed_job_id = job.get("id")
            for i, step in enumerate(steps):
                if step.get("conclusion") == "failure":
                    run.failed_step = step.get("name")
                    run.steps_before_failure_succeeded = all(
                        s.get("conclusion") == "success" for s in steps[:i])
                    break


def gather(gh: GitHubClient, as_of: datetime) -> Evidence:
    period = expected_period(as_of)
    ev = Evidence(period=period, as_of=as_of)
    start = cycle_start(as_of)

    workflow = gh.get(f"/actions/workflows/{WORKFLOW_PATH.rsplit('/', 1)[-1]}")
    if workflow.get("path") != WORKFLOW_PATH:
        raise WatchdogError(f"workflow lookup returned {workflow.get('path')!r}, "
                            f"not {WORKFLOW_PATH}")
    ev.workflow_url = workflow.get("html_url", "")

    runs = gh.pages(f"/actions/workflows/{workflow['id']}/runs",
                    {"created": f">={start:%Y-%m-%d}"}, key="workflow_runs")
    for raw in sorted(runs, key=lambda r: r["created_at"]):
        created = _ts(raw["created_at"])
        if created < start or created > as_of:
            continue
        run = RunEvidence(
            id=raw["id"], url=raw.get("html_url", ""), event=raw.get("event", ""),
            status=raw.get("status", ""), conclusion=raw.get("conclusion"),
            created_at=created, branch=raw.get("head_branch") or "")
        if run.event == "schedule" and created >= scheduled_at(as_of) - timedelta(hours=12):
            ev.scheduled_runs.append(run)
        elif run.event == "workflow_dispatch":
            ev.manual_runs.append(run)
        else:
            continue
        if run.status == "completed":
            _run_details(gh, run)

    # Newest first; a release PR for the period cannot predate the cycle.
    pulls = gh.pages("/pulls", {"state": "all", "sort": "created", "direction": "desc",
                                "base": DEFAULT_BRANCH},
                     stop=lambda pr: _ts(pr["created_at"]) < start)
    for raw in pulls:
        if not _release_pr_matches(raw, period) or _ts(raw["created_at"]) > as_of:
            continue
        merged_at = _ts(raw.get("merged_at"))
        closed_at = _ts(raw.get("closed_at"))
        # Replay the PR's state at as_of.
        if merged_at and merged_at > as_of:
            merged_at, state = None, "open"
        elif closed_at and closed_at > as_of:
            state = "open"
        else:
            state = raw.get("state", "")
        pr = PREvidence(number=raw["number"], url=raw.get("html_url", ""),
                        title=raw["title"], state=state, merged_at=merged_at,
                        created_at=_ts(raw["created_at"]), branch=raw["head"]["ref"])
        if pr.merged or pr.state == "open":
            ev.release_prs.append(pr)
        else:
            ev.closed_unmerged_prs.append(pr)

    manifest = gh.file_on_main(MANIFEST_PATH)
    if manifest is None:
        raise WatchdogError(f"{MANIFEST_PATH} not found on {DEFAULT_BRANCH}")
    try:
        ev.manifest_ids = {r["release_id"] for r in manifest["releases"]}
    except (KeyError, TypeError) as exc:
        raise WatchdogError(f"{MANIFEST_PATH} on {DEFAULT_BRANCH} has no releases list") from exc
    ev.manifest_found = True

    registry = gh.file_on_main(REGISTRY_RELATIVE_PATH.as_posix())
    entries, problems = check_registry(registry) if registry is not None else ({}, [])
    ev.registry_entry = entries.get(period)
    ev.registry_problems = problems
    if ev.registry_entry is not None and period in ev.manifest_ids:
        ev.registry_problems = problems + [
            f"{period} is listed as unavailable but is published"]

    if ev.approved_unavailable:
        for run in ev.scheduled_runs:
            if _failed_at_fetch(run):
                _read_fetch_log(gh, run, ev)
    return ev


def _failed_at_fetch(run: RunEvidence) -> bool:
    return (run.conclusion == "failure" and run.failed_step == FETCH_STEP
            and run.steps_before_failure_succeeded)


def _read_fetch_log(gh: GitHubClient, run: RunEvidence, ev: Evidence) -> None:
    """Look for the documented limitation in the failed job's log.

    A log that cannot be read leaves the failure unexplained, so it is
    reported for investigation; it is never taken as confirmation.
    """
    if run.failed_job_id is None:
        run.source_evidence = "the failed job has no id, so its log could not be read"
        return
    try:
        log = gh.job_log(run.failed_job_id)
    except WatchdogError as exc:
        run.source_evidence = f"the job log could not be read ({exc})"
        return
    run.source_explained, run.source_evidence = source_failure_evidence(
        log, ev.period, ev.registry_entry)


# --------------------------------------------------------------------------
# Job-log evidence
# --------------------------------------------------------------------------

_STAMP = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def base_month(period: str) -> str:
    """The 12-month CPI base month of a reference period."""
    return release_id_for(month_index(period) - 12)


def _fetch_output(log_text: str, period: str) -> Optional[list]:
    """Output lines of the fetch step for ``period``, or None if not found once.

    Each step in a job log opens with ``##[group]Run <first script line>``,
    lists its script until ``##[endgroup]``, then prints its output.
    """
    lines = [_ANSI.sub("", _STAMP.sub("", line)) for line in log_text.splitlines()]
    sections, current = [], None
    for line in lines:
        if line.startswith("##[group]Run "):
            current = [line]
            sections.append(current)
        elif current is not None:
            current.append(line)
    found = []
    for section in sections:
        try:
            end = section.index("##[endgroup]")
        except ValueError:
            continue
        script = "\n".join(section[:end])
        if FETCH_COMMAND in script and f'"{period}"' in script:
            found.append(section[end + 1:])
    return found[0] if len(found) == 1 else None


def source_failure_evidence(log_text: str, period: str, entry: dict) -> tuple:
    """``(explained, evidence)`` for a fetch failure in an approved period.

    Explained only if the log shows all of: the fetch ran for ``period``,
    both BLS requests completed and validation ran; no traceback; the
    single acquisition error for ``period``, whose only problem is that
    CPI has no observations for the 12-month base month; exit code 1. The
    approved registry entry must name that base month too. Anything else,
    such as a BLS authentication error, a network failure, a timeout or
    any other exception, is not explained.

    Python buffers stdout but not stderr in Actions, so the order of the
    two streams in the log is not relied on. The error and its problem
    list come from one write and stay together.
    """
    base = base_month(period)
    output = _fetch_output(log_text, period)
    if output is None:
        return False, f"the log has no single '{FETCH_STEP}' section for {period}"
    text = "\n".join(output)
    if "Traceback (most recent call last)" in text:
        return False, "the step raised an exception (traceback in the log)"
    required = (
        (f"BLS acquisition for reference period {period}", "the fetch did not start for the period"),
        (f"12-month CPI base month: {base}", f"the fetch did not report {base} as the base month"),
        ("[3/3] Validating required observations...", "the BLS requests did not complete"),
        ("##[error]Process completed with exit code 1.", "the step did not exit with code 1"),
    )
    for needle, problem in required:
        if needle not in text:
            return False, f"{problem} (log lacks '{needle}')"
    header = f"ERROR: BLS data cannot support DMI reference period {period}; nothing was staged."
    starts = [i for i, line in enumerate(output) if line == header]
    if len(starts) != 1:
        return False, "the log does not contain exactly one acquisition error for the period"
    problems = []
    for line in output[starts[0] + 1:]:
        if not line.startswith("  - "):
            break
        problems.append(line[4:])
    expected = [f"CPI has no observations for {base} (12-month CPI base month)."]
    if problems != expected:
        return False, f"the acquisition error lists {problems}, not only {expected}"
    named = (base, f"{_MONTHS[int(base[5:]) - 1]} {base[:4]}")
    entry_text = f"{entry.get('reason', '')} {entry.get('detail', '')}"
    if not any(n in entry_text for n in named):
        return False, f"the registry entry for {period} does not name {base} as the missing data"
    return True, (f"the job log shows the fetch completed and stopped only because CPI has no "
                  f"observations for {base}, the 12-month base month, which the registry "
                  f"entry ({entry.get('approved_in')}) documents as unavailable")


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------

@dataclass
class Verdict:
    classification: str
    reason: str
    run: Optional[RunEvidence] = None
    pr: Optional[PREvidence] = None
    notes: list = field(default_factory=list)

    @property
    def alert(self) -> bool:
        return self.classification in ALERTS

    def fingerprint(self, period: str) -> str:
        parts = [period, self.classification]
        if self.run:
            parts.append(f"run={self.run.id}:{self.run.conclusion or self.run.status}")
        if self.pr:
            parts.append(f"pr={self.pr.number}")
        return ":".join(parts)


def _expected_source_failure(run: RunEvidence, ev: Evidence) -> bool:
    """A failure the approved exception is shown to explain.

    The period must have a valid registry entry; the run must have got
    through every earlier step and failed at the live CPI fetch; and the
    job log must show the documented limitation as the only cause (see
    ``source_failure_evidence``). Failing at the right step is not enough.
    """
    return ev.approved_unavailable and _failed_at_fetch(run) and run.source_explained


def classify(ev: Evidence) -> Verdict:
    p = ev.period
    if ev.as_of < scheduled_at(ev.as_of) + GRACE:
        return Verdict(NOT_YET_DUE, f"the check for {p} starts at "
                       f"{scheduled_at(ev.as_of) + GRACE:%Y-%m-%d %H:%M} UTC")

    run = ev.scheduled_runs[-1] if ev.scheduled_runs else None
    merged = next((pr for pr in ev.release_prs if pr.merged), None)
    open_pr = next((pr for pr in ev.release_prs if pr.state == "open"), None)
    notes = []
    if ev.registry_problems:
        notes.append("registry problems: " + "; ".join(ev.registry_problems))
    if ev.closed_unmerged_prs:
        notes.append("closed without merging (not a release): "
                     + ", ".join(f"#{pr.number}" for pr in ev.closed_unmerged_prs))

    if p in ev.manifest_ids:
        if merged is None:
            notes.append(f"no merged release PR for {p} was found; the manifest entry "
                         "is the evidence")
        verdict = Verdict(RELEASE_MERGED, f"{p} is in {MANIFEST_PATH} on {DEFAULT_BRANCH}. "
                          "Merging does not deploy; check deploy_production.yml for the "
                          "production deployment.", run, merged, notes)
    elif merged is not None:
        return Verdict(MERGED_BUT_NOT_IN_MANIFEST, f"PR #{merged.number} was merged but "
                       f"{MANIFEST_PATH} on {DEFAULT_BRANCH} has no {p} entry", run, merged, notes)
    elif open_pr is not None:
        verdict = Verdict(RELEASE_PR_PENDING_REVIEW, f"PR #{open_pr.number} is awaiting "
                          "review; release_gate_reminder.yml follows it up", run, open_pr, notes)
    else:
        verdict = None

    if verdict is not None:
        # A release PR exists: preparation is done, by schedule or by hand.
        if run is None:
            return Verdict(SCHEDULED_TRIGGER_MISSING, f"{verdict.classification}: "
                           f"{verdict.reason}. But no scheduled run of {WORKFLOW_PATH} "
                           "started this cycle, so the scheduler is not shown to work.",
                           None, verdict.pr, notes)
        if run.conclusion != "success" and verdict.pr is not None:
            notes.append(f"scheduled run {run.id} ended {run.conclusion or run.status}; "
                         f"recovered by PR #{verdict.pr.number}")
        return verdict

    if run is None:
        reason = f"no scheduled run of {WORKFLOW_PATH} started this cycle"
        if ev.approved_unavailable:
            reason += (f". {p} is an approved unavailable period, but that explains a "
                       "missing release, not a missing schedule trigger")
        return Verdict(SCHEDULED_RUN_MISSING, reason, None, None, notes)

    if run.status != "completed":
        if ev.as_of - run.created_at > STALL_AFTER:
            return Verdict(SCHEDULED_RUN_STALLED, f"run {run.id} is still {run.status} "
                           f"after {ev.as_of - run.created_at}", run, None, notes)
        return Verdict(RUN_IN_PROGRESS, f"run {run.id} is {run.status}", run, None, notes)

    if run.conclusion == "success":
        return Verdict(RUN_SUCCEEDED_NO_RELEASE_PR, f"run {run.id} succeeded but no open or "
                       f"merged release PR for {p} exists", run, None, notes)

    if _expected_source_failure(run, ev):
        return Verdict(APPROVED_SOURCE_UNAVAILABLE, f"{p} is an approved unavailable period "
                       f"({ev.registry_entry['approved_in']}): "
                       f"{ev.registry_entry['reason']}. Run {run.id} failed at "
                       f"'{FETCH_STEP}', and {run.source_evidence}.", run, None, notes)

    reason = f"run {run.id} ended {run.conclusion}"
    if run.failed_step or run.failed_job:
        reason += f" at job '{run.failed_job}', step '{run.failed_step or 'unknown'}'"
    if ev.approved_unavailable and run.source_evidence:
        reason += (f". {p} is an approved unavailable period, but the evidence does not "
                   f"link this failure to it: {run.source_evidence}. It needs investigation")
    elif ev.approved_unavailable:
        reason += (f". {p} is an approved unavailable period, but the record does not show "
                   f"the run reaching '{FETCH_STEP}' and failing there, so the approved "
                   "exception does not explain this failure")
    elif ev.registry_entry is not None:
        reason += (f". {p} has an entry in {REGISTRY_RELATIVE_PATH.as_posix()}, but the "
                   "registry is not valid, so it is not treated as an approved exception")
    else:
        reason += f". {p} has no approved exception in {REGISTRY_RELATIVE_PATH.as_posix()}"
    return Verdict(SCHEDULED_RUN_FAILED, reason, run, None, notes)


# --------------------------------------------------------------------------
# Issues
# --------------------------------------------------------------------------

def issue_marker(period: str) -> str:
    return f"<!-- dmi-watchdog:{period} -->"


def state_marker(fingerprint: str) -> str:
    return f"<!-- dmi-watchdog-state:{fingerprint} -->"


def issue_title(period: str) -> str:
    return f"[DMI Watchdog] {period} — release preparation requires attention"


def render(ev: Evidence, verdict: Verdict) -> str:
    lines = [
        f"**Expected reference period:** {ev.period}",
        f"**Classification:** `{verdict.classification}`",
        f"**Problem:** {verdict.reason}",
        f"**Checked at:** {ev.as_of:%Y-%m-%d %H:%M} UTC",
        "",
        "**Evidence**",
    ]
    for label, items in ((f"Scheduled runs this cycle ({WORKFLOW_PATH})", ev.scheduled_runs),
                         ("Manual runs this cycle", ev.manual_runs),
                         (f"Release PRs for {ev.period}", ev.release_prs)):
        lines.append(f"- {label}:" + ("" if items else " none"))
        lines += [f"  - {item.describe()}" for item in items]
    lines.append(f"- {MANIFEST_PATH} on {DEFAULT_BRANCH}: {ev.period} "
                 + ("present" if ev.period in ev.manifest_ids else "absent"))
    if ev.registry_entry is not None:
        status = "valid" if ev.approved_unavailable else "present but not valid"
        lines.append(f"- {REGISTRY_RELATIVE_PATH.as_posix()}: {ev.period} listed ({status}), "
                     f"approved in {ev.registry_entry.get('approved_in')}")
    else:
        lines.append(f"- {REGISTRY_RELATIVE_PATH.as_posix()}: {ev.period} not listed")
    lines += [f"- Note: {n}" for n in verdict.notes]
    action = ACTIONS.get(verdict.classification)
    if action:
        lines += ["", "**Suggested action**", action.format(period=ev.period)]
    lines += ["", "This watchdog never reruns workflows, merges PRs or deploys."]
    return "\n".join(lines)


def find_issue(gh: GitHubClient, period: str) -> Optional[dict]:
    marker = issue_marker(period)
    for issue in gh.pages("/issues", {"state": "all", "sort": "created", "direction": "desc"}):
        if "pull_request" in issue:
            continue
        if marker in (issue.get("body") or ""):
            return issue
    return None


def last_state(gh: GitHubClient, issue: dict) -> Optional[str]:
    found = re.findall(r"<!-- dmi-watchdog-state:(\S+) -->", issue.get("body") or "")
    for comment in gh.pages(f"/issues/{issue['number']}/comments", {}):
        found += re.findall(r"<!-- dmi-watchdog-state:(\S+) -->", comment.get("body") or "")
    return found[-1] if found else None


@dataclass
class IssuePlan:
    action: str  # "none", "create", "comment"
    detail: str
    number: Optional[int] = None


def plan_issue(gh: GitHubClient, ev: Evidence, verdict: Verdict) -> IssuePlan:
    if verdict.classification == NOT_YET_DUE:
        return IssuePlan("none", "not yet due; Issues were not checked")
    issue = find_issue(gh, ev.period)
    fp = verdict.fingerprint(ev.period)
    if issue is None:
        if verdict.alert:
            return IssuePlan("create", f"create '{issue_title(ev.period)}'")
        return IssuePlan("none", "no alert and no existing Issue")
    where = f"#{issue['number']} ({issue.get('state')})"
    if last_state(gh, issue) == fp:
        return IssuePlan("none", f"Issue {where} already records this state", issue["number"])
    if not verdict.alert and issue.get("state") == "closed":
        return IssuePlan("none", f"Issue {where} is closed and nothing needs attention",
                         issue["number"])
    return IssuePlan("comment", f"add one update to Issue {where}; it is never closed or "
                     "reopened automatically", issue["number"])


def apply_issue(gh: GitHubClient, ev: Evidence, verdict: Verdict, plan: IssuePlan) -> None:
    body = render(ev, verdict) + "\n\n" + state_marker(verdict.fingerprint(ev.period))
    if plan.action == "create":
        gh.post("/issues", {"title": issue_title(ev.period),
                            "body": issue_marker(ev.period) + "\n" + body,
                            "assignees": [ASSIGNEE]})
    elif plan.action == "comment":
        prefix = ("**Update: no action needed now.**\n\n" if not verdict.alert
                  else "**Update: the condition changed.**\n\n")
        gh.post(f"/issues/{plan.number}/comments", {"body": prefix + body})


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

def report(ev: Evidence, verdict: Verdict, plan: IssuePlan, notify: bool) -> str:
    mode = "live (notifications enabled)" if notify else "dry run (no GitHub writes)"
    return "\n".join([
        f"## DMI missing-release watchdog — {ev.period}",
        "",
        f"**Mode:** {mode}",
        render(ev, verdict),
        "",
        f"**Issue action:** {plan.action} — {plan.detail}",
    ])


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main(argv: Optional[list] = None, transport: Optional[Transport] = None,
         now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
         download: Optional[Callable[[str], str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m scripts.monthly_release_watchdog",
        description="Check that this month's DMI release preparation happened.")
    parser.add_argument("--as-of", help="evaluation date, YYYY-MM-DD (end of that UTC "
                        "day) or an ISO date-time; default now")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"),
                        help="owner/name; default $GITHUB_REPOSITORY")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print the result and the Issue action; write nothing (default)")
    mode.add_argument("--notify", action="store_true",
                      help="create or update the Issue. Only for the current date.")
    args = parser.parse_args(argv)

    try:
        if not args.repo:
            raise WatchdogError("no repository: pass --repo or set GITHUB_REPOSITORY")
        if args.notify and args.as_of:
            raise WatchdogError("--notify cannot be combined with --as-of; a replayed "
                                "date may only be dry-run")
        as_of = parse_as_of(args.as_of, now)
        if transport is None:
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise WatchdogError("no GitHub token: set GH_TOKEN or GITHUB_TOKEN")
            transport = urllib_transport(token, os.environ.get("GITHUB_API_URL",
                                                               "https://api.github.com"))
            download = download or urllib_download
        gh = GitHubClient(args.repo, transport, allow_writes=args.notify, download=download)
        ev = gather(gh, as_of)
        verdict = classify(ev)
        plan = plan_issue(gh, ev, verdict)
        text = report(ev, verdict, plan, args.notify)
        print(text)
        _summary(text)
        if args.notify:
            apply_issue(gh, ev, verdict, plan)
    except WatchdogError as exc:
        text = (f"## DMI missing-release watchdog — ERROR\n\n{exc}\n\n"
                "The watchdog could not establish the facts, so it reached no "
                "conclusion. This is not the same as finding nothing.")
        print(text, file=sys.stderr)
        _summary(text)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
