"""The missing-release watchdog (scripts/monthly_release_watchdog.py).

Every test runs against ``FakeGitHub``, an in-memory stand-in for the
GitHub REST API. Nothing here touches the network or creates a real
Issue. Job and step records are built from the real step names in
``monthly_dmi.yml``, so a renamed step breaks these tests rather than
silently changing the classification.
"""

from __future__ import annotations

import ast
import base64
import io
import json
import os
import re
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is a repo dependency
    yaml = None

from scripts import monthly_release_watchdog as wd

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WATCHDOG_WORKFLOW = WORKFLOWS / "monthly_release_watchdog.yml"
MODULE = ROOT / "scripts" / "monthly_release_watchdog.py"
REPO = "dmianalysis/dmi"
REAL_REGISTRY = json.loads((ROOT / "registry" / "unavailable_periods.json").read_text())


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def monthly_step_names() -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / "monthly_dmi.yml").read_text())
    return [s["name"] for s in doc["jobs"]["prepare-dmi"]["steps"]]


LIVE_ONLY = {"Fetch CPI data (live only)", "Compute DMI Baseline (live only)",
             "Compute DMI Slack+ (live only)",
             "Finalize release (gates, then publish) — live only"}
FIXTURE_ONLY = {"Verify release gates against committed artifacts — fixture only"}
PREPARE_ONLY = {"Ensure workflow files are not included in release PR",
                "Create Release PR (no deployment)"}


def job_record(failed_step=None, data_source="live"):
    """A jobs-API record for monthly_dmi.yml, failing at ``failed_step``."""
    steps, state = [{"name": "Set up job", "conclusion": "success"}], "success"
    for name in monthly_step_names():
        if state != "success":
            conclusion = "skipped"
        elif data_source == "fixture" and (name in LIVE_ONLY or name in PREPARE_ONLY):
            conclusion = "skipped"
        elif data_source == "live" and name in FIXTURE_ONLY:
            conclusion = "skipped"
        elif name == failed_step:
            conclusion = state = "failure"
        else:
            conclusion = "success"
        steps.append({"name": name, "conclusion": conclusion})
    if failed_step is not None:
        assert state == "failure", f"unknown step {failed_step!r}"
    return {"name": "prepare-dmi", "conclusion": state, "steps": steps}


class FakeGitHub:
    """Serves the endpoints the watchdog reads, and records every request."""

    def __init__(self):
        self.runs, self.jobs, self.pulls = [], {}, []
        self.issues, self.comments = [], {}
        self.manifest_ids = ["2026-09", "2026-08"]
        self.registry = REAL_REGISTRY
        self.requests = []
        self.fail = {}  # path prefix -> (status, message)

    # -- builders --------------------------------------------------------
    def run(self, run_id, created, event="schedule", conclusion="success",
            failed_step=None, data_source="live", status="completed", branch="main"):
        self.runs.append({"id": run_id, "event": event, "status": status,
                          "conclusion": conclusion if status == "completed" else None,
                          "created_at": created, "head_branch": branch,
                          "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"})
        self.jobs[run_id] = [job_record(failed_step, data_source)]

    def pr(self, number, period, created, merged_at=None, state="open", closed_at=None,
           title=None, labels=("automated", "release", "not-deployed"), branch=None):
        self.pulls.append({
            "number": number, "state": state, "created_at": created,
            "merged_at": merged_at, "closed_at": closed_at or merged_at,
            "title": title or f"DMI Release: {period} (not deployed)",
            "head": {"ref": branch or f"release/{period}-20261215103000"},
            "base": {"ref": "main"}, "labels": [{"name": n} for n in labels],
            "html_url": f"https://github.com/{REPO}/pull/{number}"})

    def issue(self, number, period, state="open", fingerprint=None):
        body = wd.issue_marker(period) + "\nreported earlier"
        if fingerprint:
            body += "\n" + wd.state_marker(fingerprint)
        self.issues.append({"number": number, "state": state, "body": body,
                            "title": wd.issue_title(period)})
        self.comments[number] = []

    # -- transport -------------------------------------------------------
    def __call__(self, method, path, body):
        self.requests.append((method, path, body))
        url = urlsplit(path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        route = url.path.removeprefix(f"/repos/{REPO}")
        for prefix, failure in self.fail.items():
            if route.startswith(prefix):
                return failure[0], {"message": failure[1]}
        if method == "POST":
            return self._post(route, body)
        if method != "GET":
            return 405, {"message": "fake supports GET and POST only"}
        if query.get("page", "1") != "1":
            return 200, {"workflow_runs": []} if route.endswith("/runs") else []
        if route == "/actions/workflows/monthly_dmi.yml":
            return 200, {"id": 7, "path": ".github/workflows/monthly_dmi.yml",
                         "html_url": f"https://github.com/{REPO}/actions/workflows/monthly_dmi.yml"}
        if route == "/actions/workflows/7/runs":
            since = query["created"].removeprefix(">=")
            return 200, {"workflow_runs": [r for r in self.runs if r["created_at"] >= since]}
        m = re.fullmatch(r"/actions/runs/(\d+)/jobs", route)
        if m:
            return 200, {"jobs": self.jobs[int(m.group(1))]}
        if route == "/pulls":
            return 200, sorted(self.pulls, key=lambda p: p["created_at"], reverse=True)
        if route == "/contents/data/outputs/releases.json":
            return 200, self._file({"releases": [{"release_id": r} for r in self.manifest_ids]})
        if route == "/contents/registry/unavailable_periods.json":
            if self.registry is None:
                return 404, {"message": "Not Found"}
            return 200, self._file(self.registry)
        if route == "/issues":
            wanted = query.get("state", "open")
            return 200, [i for i in reversed(self.issues) if wanted in ("all", i["state"])]
        m = re.fullmatch(r"/issues/(\d+)/comments", route)
        if m:
            return 200, self.comments[int(m.group(1))]
        return 404, {"message": f"fake has no route {route}"}

    @staticmethod
    def _file(doc):
        return {"encoding": "base64", "content": base64.b64encode(json.dumps(doc).encode()).decode()}

    def _post(self, route, body):
        if route == "/issues":
            number = 900 + len(self.issues)
            self.issues.append({"number": number, "state": "open", **body})
            self.comments[number] = []
            return 201, {"number": number}
        m = re.fullmatch(r"/issues/(\d+)/comments", route)
        if m:
            self.comments[int(m.group(1))].append(body)
            return 201, {"id": 1}
        return 404, {"message": f"fake has no POST route {route}"}

    @property
    def writes(self):
        return [(m, p) for m, p, _ in self.requests if m != "GET"]


DEC = "2026-12-17T16:37:00Z"  # first December check; expects 2026-11
NOV = "2026-11-17T16:37:00Z"  # first November check; expects 2026-10


def check(fake, as_of=DEC):
    gh = wd.GitHubClient(REPO, fake)
    ev = wd.gather(gh, utc(as_of))
    return ev, wd.classify(ev)


def run_main(fake, *argv, as_of=DEC):
    out, err = io.StringIO(), io.StringIO()
    with tempfile.TemporaryDirectory() as tmp:
        summary = Path(tmp) / "summary.md"
        old = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary)
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = wd.main(["--repo", REPO, *argv], transport=fake,
                               now=lambda: utc(as_of))
        finally:
            if old is None:
                os.environ.pop("GITHUB_STEP_SUMMARY")
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = old
        text = summary.read_text() if summary.exists() else ""
    return code, out.getvalue(), err.getvalue(), text


def healthy_december(fake):
    """The ordinary December cycle: scheduled run succeeded, PR opened."""
    fake.run(501, "2026-12-15T10:20:00Z")
    fake.pr(61, "2026-11", "2026-12-15T10:40:00Z")


# ---------------------------------------------------------------------------


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestClassification(unittest.TestCase):

    def test_01_november_scheduled_run_absent_after_grace(self):
        ev, v = check(FakeGitHub(), NOV)
        self.assertEqual(ev.period, "2026-10")
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_MISSING)
        self.assertTrue(v.alert)
        # October's approved data gap does not excuse a missing trigger.
        self.assertTrue(ev.approved_unavailable)
        self.assertIn("not a missing schedule trigger", v.reason)

    def test_not_yet_due_inside_the_grace_period(self):
        ev, v = check(FakeGitHub(), "2026-12-17T10:00:00Z")
        self.assertEqual(v.classification, wd.NOT_YET_DUE)
        self.assertFalse(v.alert)

    def test_02_python_setup_failure_before_release_preparation(self):
        fake = FakeGitHub()
        fake.run(502, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertEqual((v.run.id, v.run.failed_job, v.run.failed_step),
                         (502, "prepare-dmi", "Set up Python"))
        self.assertIn("no approved exception", v.reason)
        body = wd.render(ev, v)
        for needed in ("2026-11", "SCHEDULED_RUN_FAILED", "Set up Python",
                       "https://github.com/dmianalysis/dmi/actions/runs/502",
                       "Suggested action", "2026-12-17 16:37 UTC"):
            self.assertIn(needed, body)

    def test_03_successful_run_that_produced_no_pr(self):
        fake = FakeGitHub()
        fake.run(503, "2026-12-15T10:20:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RUN_SUCCEEDED_NO_RELEASE_PR)
        self.assertTrue(v.alert)

    def test_03b_closed_unmerged_pr_is_not_a_release(self):
        fake = FakeGitHub()
        fake.run(503, "2026-12-15T10:20:00Z")
        fake.pr(62, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                closed_at="2026-12-16T09:00:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RUN_SUCCEEDED_NO_RELEASE_PR)
        self.assertIn("#62", " ".join(v.notes))

    def test_03c_pr_must_match_title_branch_and_labels(self):
        for kwargs in ({"labels": ("release",)}, {"branch": "fix/2026-11"},
                       {"title": "DMI Release: 2026-11"}):
            with self.subTest(**kwargs):
                fake = FakeGitHub()
                fake.run(503, "2026-12-15T10:20:00Z")
                fake.pr(63, "2026-11", "2026-12-15T10:40:00Z", **kwargs)
                self.assertEqual(check(fake)[1].classification,
                                 wd.RUN_SUCCEEDED_NO_RELEASE_PR)

    def test_04_open_release_pr_awaiting_review(self):
        fake = FakeGitHub()
        healthy_december(fake)
        _, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_PR_PENDING_REVIEW)
        self.assertFalse(v.alert)
        self.assertEqual(v.pr.url, "https://github.com/dmianalysis/dmi/pull/61")
        code, out, _, _ = run_main(fake, "--notify")
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes, [], "an open release PR must not open an Issue")

    def test_05_pr_merged_but_manifest_not_updated(self):
        fake = FakeGitHub()
        fake.run(505, "2026-12-15T10:20:00Z")
        fake.pr(65, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-16T12:00:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.MERGED_BUT_NOT_IN_MANIFEST)
        self.assertTrue(v.alert)

    def test_06_valid_merged_release_recorded_in_main(self):
        fake = FakeGitHub()
        fake.run(506, "2026-12-15T10:20:00Z")
        fake.pr(66, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-16T12:00:00Z")
        fake.manifest_ids.insert(0, "2026-11")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_MERGED)
        self.assertFalse(v.alert)
        self.assertIn("does not deploy", v.reason)
        self.assertNotIn("deployed to", wd.render(ev, v))

    def test_06b_replayed_date_sees_the_pr_as_it_was(self):
        fake = FakeGitHub()
        fake.run(506, "2026-12-15T10:20:00Z")
        fake.pr(66, "2026-11", "2026-12-15T10:40:00Z", state="closed",
                merged_at="2026-12-20T12:00:00Z")
        self.assertEqual(check(fake, DEC)[1].classification, wd.RELEASE_PR_PENDING_REVIEW)

    def test_07_manual_recovery_after_a_scheduled_failure(self):
        fake = FakeGitHub()
        fake.run(507, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        fake.run(508, "2026-12-16T09:00:00Z", event="workflow_dispatch")
        fake.pr(67, "2026-11", "2026-12-16T09:30:00Z")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.RELEASE_PR_PENDING_REVIEW)
        self.assertIn("recovered by PR #67", " ".join(v.notes))
        self.assertEqual(ev.manual_runs[0].data_source, "live")
        self.assertTrue(ev.manual_runs[0].opened_pr)

    def test_07b_manual_recovery_without_any_scheduled_trigger_still_warns(self):
        fake = FakeGitHub()
        fake.run(508, "2026-12-16T09:00:00Z", event="workflow_dispatch")
        fake.pr(67, "2026-11", "2026-12-16T09:30:00Z")
        _, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_TRIGGER_MISSING)
        self.assertTrue(v.alert)
        self.assertIn(wd.RELEASE_PR_PENDING_REVIEW, v.reason)

    def test_08_manual_fixture_validation_is_not_release_preparation(self):
        fake = FakeGitHub()
        fake.run(509, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        fake.run(510, "2026-12-16T09:00:00Z", event="workflow_dispatch", data_source="fixture")
        ev, v = check(fake)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertEqual(ev.manual_runs[0].data_source, "fixture")
        self.assertIn("validate/fixture (not release preparation)", ev.manual_runs[0].describe())

    def test_08b_fixture_runs_do_not_stand_in_for_a_scheduled_run(self):
        fake = FakeGitHub()
        fake.run(510, "2026-12-15T11:00:00Z", event="workflow_dispatch", data_source="fixture")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_MISSING)

    def test_09_october_2026_registered_as_unavailable(self):
        fake = FakeGitHub()
        fake.run(511, "2026-11-15T10:20:00Z", conclusion="failure",
                 failed_step=wd.FETCH_STEP)
        ev, v = check(fake, NOV)
        self.assertEqual(ev.period, "2026-10")
        self.assertTrue(ev.approved_unavailable)
        self.assertEqual(v.classification, wd.APPROVED_SOURCE_UNAVAILABLE)
        self.assertFalse(v.alert)
        self.assertIn("dmianalysis/dmi#40", v.reason)
        self.assertIn("CPI comparison data are unavailable", v.reason)

    def test_10_approved_gap_does_not_conceal_an_infrastructure_failure(self):
        # This is what actually happened on November 15, 2026.
        for step in ("Set up Python", "Install dependencies", "Resolve reference period"):
            with self.subTest(step=step):
                fake = FakeGitHub()
                fake.run(512, "2026-11-15T17:14:00Z", conclusion="failure", failed_step=step)
                ev, v = check(fake, NOV)
                self.assertTrue(ev.approved_unavailable)
                self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
                self.assertIn("does not explain this failure", v.reason)

    def test_10b_failure_after_the_fetch_is_not_explained_either(self):
        fake = FakeGitHub()
        fake.run(513, "2026-11-15T10:20:00Z", conclusion="failure",
                 failed_step="Compute DMI Baseline (live only)")
        self.assertEqual(check(fake, NOV)[1].classification, wd.SCHEDULED_RUN_FAILED)

    def test_10c_cancelled_run_is_not_explained(self):
        fake = FakeGitHub()
        fake.run(514, "2026-11-15T10:20:00Z", conclusion="cancelled")
        self.assertEqual(check(fake, NOV)[1].classification, wd.SCHEDULED_RUN_FAILED)

    def test_11_failed_cpi_acquisition_with_an_approved_exception(self):
        fake = FakeGitHub()
        fake.run(515, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        ev, v = check(fake, NOV)
        self.assertTrue(v.run.steps_before_failure_succeeded)
        self.assertEqual(v.classification, wd.APPROVED_SOURCE_UNAVAILABLE)
        code, _, _, _ = run_main(fake, "--notify", as_of=NOV)
        self.assertEqual((code, fake.writes), (0, []))

    def test_11b_an_invalid_registry_approves_nothing(self):
        fake = FakeGitHub()
        fake.registry = json.loads(json.dumps(REAL_REGISTRY))
        fake.registry["periods"][0]["reason"] = "TODO"
        fake.run(515, "2026-11-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        ev, v = check(fake, NOV)
        self.assertFalse(ev.approved_unavailable)
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("registry is not valid", v.reason)

    def test_12_future_missing_month_with_no_approved_exception(self):
        fake = FakeGitHub()
        fake.run(516, "2027-04-15T10:20:00Z", conclusion="failure", failed_step=wd.FETCH_STEP)
        ev, v = check(fake, "2027-04-17T16:37:00Z")
        self.assertEqual(ev.period, "2027-03")
        self.assertEqual(v.classification, wd.SCHEDULED_RUN_FAILED)
        self.assertIn("no approved exception", v.reason)

    def test_stalled_and_in_progress_runs(self):
        fake = FakeGitHub()
        fake.run(517, "2026-12-17T10:20:00Z", status="in_progress")
        self.assertEqual(check(fake)[1].classification, wd.RUN_IN_PROGRESS)
        fake = FakeGitHub()
        fake.run(518, "2026-12-15T10:20:00Z", status="queued")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_STALLED)

    def test_scheduled_runs_from_another_cycle_are_ignored(self):
        fake = FakeGitHub()
        fake.run(519, "2026-11-15T10:20:00Z")
        self.assertEqual(check(fake)[1].classification, wd.SCHEDULED_RUN_MISSING)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestIssues(unittest.TestCase):

    def failing(self):
        fake = FakeGitHub()
        fake.run(520, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        return fake

    def test_alert_creates_one_assigned_issue(self):
        fake = self.failing()
        code, out, _, _ = run_main(fake, "--notify")
        self.assertEqual(code, 0)
        self.assertEqual(fake.writes, [("POST", f"/repos/{REPO}/issues")])
        body = fake.requests[-1][2]
        self.assertEqual(body["title"],
                         "[DMI Watchdog] 2026-11 — release preparation requires attention")
        self.assertTrue(body["body"].startswith("<!-- dmi-watchdog:2026-11 -->"))
        self.assertEqual(body["assignees"], ["tcwilliams79"])

    def test_13_repeated_daily_checks_produce_no_duplicate(self):
        fake = self.failing()
        for day in ("2026-12-17T16:37:00Z", "2026-12-18T16:37:00Z", "2026-12-19T16:37:00Z"):
            self.assertEqual(run_main(fake, "--notify", as_of=day)[0], 0)
        self.assertEqual(len(fake.issues), 1)
        self.assertEqual(len(fake.writes), 1)

    def test_a_meaningful_change_adds_exactly_one_update(self):
        fake = self.failing()
        run_main(fake, "--notify")
        fake.run(521, "2026-12-18T09:00:00Z", event="workflow_dispatch")
        fake.pr(68, "2026-11", "2026-12-18T09:30:00Z")
        for day in ("2026-12-18T16:37:00Z", "2026-12-19T16:37:00Z"):
            run_main(fake, "--notify", as_of=day)
        number = fake.issues[0]["number"]
        self.assertEqual(len(fake.comments[number]), 1)
        self.assertIn("no action needed now", fake.comments[number][0]["body"])
        self.assertEqual(fake.issues[0]["state"], "open", "never closed automatically")

    def test_14_closed_issue_is_not_duplicated(self):
        fake = self.failing()
        fake.issue(77, "2026-11", state="closed",
                   fingerprint="2026-11:SCHEDULED_RUN_MISSING")
        run_main(fake, "--notify")
        self.assertEqual(len(fake.issues), 1, "no second Issue for the same period")
        self.assertEqual(fake.writes, [("POST", f"/repos/{REPO}/issues/77/comments")])
        self.assertEqual(fake.issues[0]["state"], "closed", "never reopened automatically")
        run_main(fake, "--notify", as_of="2026-12-18T16:37:00Z")
        self.assertEqual(len(fake.writes), 1)

    def test_14b_closed_issue_gets_nothing_when_all_is_well(self):
        fake = FakeGitHub()
        healthy_december(fake)
        fake.issue(78, "2026-11", state="closed", fingerprint="2026-11:SCHEDULED_RUN_MISSING")
        run_main(fake, "--notify")
        self.assertEqual(fake.writes, [])

    def test_issues_for_other_periods_are_not_reused(self):
        fake = self.failing()
        fake.issue(79, "2026-10", state="open")
        run_main(fake, "--notify")
        self.assertEqual([i["number"] for i in fake.issues], [79, 901])


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestFailuresAreExplicit(unittest.TestCase):

    def test_15_authorization_failure_is_not_zero_runs(self):
        for prefix in ("/actions/workflows/7/runs", "/actions/runs/", "/pulls",
                       "/contents/data", "/issues"):
            with self.subTest(prefix=prefix):
                fake = FakeGitHub()
                fake.run(530, "2026-12-15T17:14:00Z", conclusion="failure",
                         failed_step="Set up Python")
                fake.fail[prefix] = (401, "Bad credentials")
                code, out, err, summary = run_main(fake, "--notify")
                self.assertEqual(code, 2)
                self.assertNotIn(wd.SCHEDULED_RUN_MISSING, out + err)
                self.assertIn("HTTP 401", err)
                self.assertIn("ERROR", summary)
                self.assertIn("not the same as finding nothing", summary)
                self.assertEqual(fake.writes, [])

    def test_missing_manifest_is_an_error_not_an_absent_release(self):
        fake = FakeGitHub()
        fake.fail["/contents/data/outputs/releases.json"] = (404, "Not Found")
        self.assertEqual(run_main(fake)[0], 2)

    def test_malformed_listing_is_an_error(self):
        fake = FakeGitHub()
        original = fake.__call__

        def broken(method, path, body):
            if "/runs?" in path:
                return 200, {"total_count": 0}
            return original(method, path, body)
        self.assertEqual(run_main(broken)[0], 2)

    def test_wrong_workflow_path_is_an_error(self):
        fake = FakeGitHub()
        original = fake.__call__

        def other(method, path, body):
            status, payload = original(method, path, body)
            if path.endswith("/actions/workflows/monthly_dmi.yml"):
                payload = {**payload, "path": ".github/workflows/other.yml"}
            return status, payload
        self.assertEqual(run_main(other)[0], 2)

    def test_missing_token_or_repo_fails(self):
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            env = {k: os.environ.pop(k) for k in ("GH_TOKEN", "GITHUB_TOKEN") if k in os.environ}
            try:
                self.assertEqual(wd.main(["--repo", REPO]), 2)
            finally:
                os.environ.update(env)
            self.assertEqual(wd.main(["--repo", "not a repo"], transport=FakeGitHub()), 2)


class TestDates(unittest.TestCase):

    def test_16_reference_period_from_the_check_date(self):
        cases = {
            "2026-11-17T16:37:00Z": "2026-10",
            "2026-12-17T16:37:00Z": "2026-11",
            "2027-01-17T16:37:00Z": "2026-12",
            "2027-01-01T00:00:00Z": "2026-12",
            "2026-12-31T23:59:59Z": "2026-11",
            # 19:30 on Dec 31 in New York is already January in UTC.
            "2026-12-31T19:30:00-05:00": "2026-12",
            "2027-02-28T16:37:00Z": "2027-01",
        }
        for when, period in cases.items():
            with self.subTest(when=when):
                self.assertEqual(wd.expected_period(utc(when)), period)

    def test_as_of_parsing(self):
        now = lambda: utc("2026-12-20T08:00:00Z")
        self.assertEqual(wd.parse_as_of(None, now), now())
        self.assertEqual(wd.parse_as_of("2026-12-17", now), utc("2026-12-17T23:59:59Z"))
        self.assertEqual(wd.parse_as_of("2026-12-17T16:37Z", now), utc("2026-12-17T16:37:00Z"))
        for bad in ("17/12/2026", "2026-12-17T16:37"):
            with self.subTest(bad=bad), self.assertRaises(SystemExit):
                wd.parse_as_of(bad, now)

    @unittest.skipIf(yaml is None, "PyYAML not available")
    def test_january_cycle_crosses_the_year(self):
        fake = FakeGitHub()
        fake.manifest_ids.insert(0, "2026-11")
        fake.run(540, "2027-01-15T10:20:00Z")
        fake.pr(70, "2026-12", "2027-01-15T10:40:00Z")
        ev, v = check(fake, "2027-01-17T16:37:00Z")
        self.assertEqual((ev.period, v.classification), ("2026-12", wd.RELEASE_PR_PENDING_REVIEW))


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestDryRun(unittest.TestCase):

    def test_17_dry_run_makes_no_github_writes(self):
        fake = FakeGitHub()
        fake.run(550, "2026-12-15T17:14:00Z", conclusion="failure", failed_step="Set up Python")
        for argv in ((), ("--dry-run",), ("--dry-run", "--as-of", "2026-12-17")):
            with self.subTest(argv=argv):
                code, out, _, summary = run_main(fake, *argv)
                self.assertEqual(code, 0)
                self.assertEqual(fake.writes, [])
                for needed in ("dry run (no GitHub writes)", "Expected reference period:** 2026-11",
                               "Scheduled runs this cycle", "Release PRs for 2026-11",
                               "data/outputs/releases.json on main", "registry/unavailable_periods.json",
                               "Classification:** `SCHEDULED_RUN_FAILED`",
                               "Issue action:** create"):
                    self.assertIn(needed, out)
                self.assertEqual(out.strip(), summary.strip())

    def test_dry_run_client_refuses_writes_outright(self):
        gh = wd.GitHubClient(REPO, FakeGitHub(), allow_writes=False)
        with self.assertRaises(wd.WatchdogError):
            gh.post("/issues", {"title": "x"})

    def test_replayed_dates_cannot_notify(self):
        fake = FakeGitHub()
        code, _, err, _ = run_main(fake, "--notify", "--as-of", "2026-12-17")
        self.assertEqual((code, fake.writes), (2, []))
        self.assertIn("dry-run", err)


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestNoPublicationAuthority(unittest.TestCase):
    """18: no reruns, merges, deployment or repository writes."""

    def test_client_permits_only_issue_creation_and_comments(self):
        sent = []

        def accepts_anything(method, path, body):
            sent.append((method, path))
            return 201, {}
        gh = wd.GitHubClient(REPO, accepts_anything, allow_writes=True)
        gh.post("/issues", {})
        gh.post("/issues/5/comments", {})
        self.assertEqual(len(sent), 2)
        for suffix in ("/actions/runs/1/rerun", "/actions/runs/1/rerun-failed-jobs",
                       "/actions/workflows/7/dispatches", "/pulls/1/merge",
                       "/pulls/1/reviews", "/merges", "/deployments", "/dispatches",
                       "/git/refs", "/issues/1/labels", "/contents/data/outputs/releases.json"):
            with self.subTest(suffix=suffix), self.assertRaises(wd.WatchdogError):
                gh.post(suffix, {})
        self.assertEqual(len(sent), 2, "a refused write must never be sent")
        self.assertFalse(hasattr(gh, "put") or hasattr(gh, "patch") or hasattr(gh, "delete"))

    def test_module_sends_only_get_and_post(self):
        methods = set(re.findall(r'_send\("([A-Z]+)"', MODULE.read_text()))
        self.assertEqual(methods, {"GET", "POST"})
        self.assertEqual(re.findall(r"\b(PUT|PATCH|DELETE)\b", MODULE.read_text()), [])

    def test_module_writes_no_local_files_except_the_run_summary(self):
        tree = ast.parse(MODULE.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        names = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                 for n in calls}
        self.assertFalse(names & {"write_text", "write_bytes", "dump", "mkdir", "unlink",
                                  "rmtree", "run", "Popen", "system"})
        opens = [n for n in calls if getattr(n.func, "id", "") == "open"]
        self.assertEqual(len(opens), 1)
        self.assertIn("GITHUB_STEP_SUMMARY", ast.get_source_segment(MODULE.read_text(),
                                                                   _enclosing(tree, opens[0])))

    def test_module_is_independent_of_the_pipeline(self):
        imported = set()
        for node in ast.walk(ast.parse(MODULE.read_text())):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
        repo_modules = {m for m in imported if m and m.split(".")[0] in ("scripts", "dmi_pipeline",
                                                                       "dmi_calculator")}
        self.assertEqual(repo_modules, {"scripts.unavailable_periods"})

    def test_workflow_permissions_and_triggers(self):
        doc = yaml.safe_load(WATCHDOG_WORKFLOW.read_text())
        self.assertEqual(doc["permissions"], {"contents": "read", "actions": "read",
                                              "pull-requests": "read", "issues": "write"})
        on = doc.get("on", doc.get(True))
        self.assertEqual(set(on), {"schedule", "workflow_dispatch"})
        self.assertEqual(on["schedule"], [{"cron": "37 16 17-28 * *"}])
        self.assertIs(on["workflow_dispatch"]["inputs"]["notify"]["default"], False)
        for job in doc["jobs"].values():
            self.assertEqual(job["runs-on"], "ubuntu-latest")
            self.assertNotIn("permissions", job)

    def test_workflow_holds_no_secrets_and_cannot_deploy(self):
        text = WATCHDOG_WORKFLOW.read_text()
        self.assertNotIn("secrets.", text)
        doc = yaml.safe_load(text)
        steps = [s for job in doc["jobs"].values() for s in job["steps"]]
        code = "\n".join(line for s in steps for line in str(s.get("run", "")).splitlines()
                         if not line.strip().startswith("#"))
        for forbidden in ("ssh", "rsync", "scp", "sftp", "deploy", "gh workflow", "gh run",
                          "gh pr", "gh api", "git push", "git commit", "curl", "rerun",
                          "finalize_release", "compute_dmi", "test_bls_api", "prepare_deployment"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)
        uses = {str(s.get("uses", "")).split("@")[0] for s in steps if s.get("uses")}
        self.assertEqual(uses, {"actions/checkout", "actions/setup-python"})
        checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
        self.assertIs(checkout["with"]["persist-credentials"], False)

    def test_watchdog_is_not_a_deployment_workflow(self):
        from tests import test_monthly_workflow_safety as safety
        self.assertIn(WATCHDOG_WORKFLOW, safety.ALL_WORKFLOWS)
        self.assertNotIn(WATCHDOG_WORKFLOW, safety.DEPLOY_WORKFLOWS)
        deploy = (WORKFLOWS / "deploy_production.yml").read_text()
        self.assertNotIn("monthly_release_watchdog", deploy)
        self.assertNotIn("workflow_run", WATCHDOG_WORKFLOW.read_text())

    def test_reminder_workflow_keeps_its_own_job(self):
        reminder = (WORKFLOWS / "release_gate_reminder.yml").read_text()
        self.assertNotIn("watchdog", reminder)
        self.assertNotIn("gh pr comment", WATCHDOG_WORKFLOW.read_text())


@unittest.skipIf(yaml is None, "PyYAML not available")
class TestWorkflowWiring(unittest.TestCase):
    """The workflow's shell picks the mode; run it against a stub python."""

    def run_step(self, event, as_of="", notify=""):
        doc = yaml.safe_load(WATCHDOG_WORKFLOW.read_text())
        step = next(s for s in doc["jobs"]["watch"]["steps"]
                    if s["name"] == "Check this month's release preparation")
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "python"
            stub.write_text('#!/bin/sh\necho "$@"\n')
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
            env = {"PATH": f"{tmp}:{os.environ['PATH']}", "EVENT_NAME": event,
                   "INPUT_AS_OF": as_of, "INPUT_NOTIFY": notify}
            out = subprocess.run(["bash", "-e", "-c", step["run"]], env=env,
                                 capture_output=True, text=True, check=True)
        return out.stdout.split()

    def test_scheduled_runs_notify(self):
        self.assertEqual(self.run_step("schedule"),
                         ["-m", "scripts.monthly_release_watchdog", "--notify"])

    def test_manual_runs_default_to_dry_run(self):
        self.assertEqual(self.run_step("workflow_dispatch", notify="false")[-1], "--dry-run")
        self.assertEqual(self.run_step("workflow_dispatch")[-1], "--dry-run")

    def test_manual_notify_must_be_ticked(self):
        self.assertEqual(self.run_step("workflow_dispatch", notify="true")[-1], "--notify")

    def test_replayed_date_is_always_a_dry_run(self):
        args = self.run_step("workflow_dispatch", as_of="2026-12-17", notify="true")
        self.assertEqual(args[-3:], ["--as-of", "2026-12-17", "--dry-run"])
        self.assertNotIn("--notify", args)

    def test_classification_relies_on_real_step_names(self):
        names = monthly_step_names()
        for step in (wd.FETCH_STEP, wd.CREATE_PR_STEP, "Set up Python"):
            self.assertIn(step, names)
        monthly = yaml.safe_load((WORKFLOWS / "monthly_dmi.yml").read_text())
        on = monthly.get("on", monthly.get(True))
        self.assertEqual(on["schedule"], [{"cron": "17 10 15 * *"}],
                         "the watchdog's grace period assumes the 15th at 10:17 UTC")
        create = next(s for s in monthly["jobs"]["prepare-dmi"]["steps"]
                      if s["name"] == wd.CREATE_PR_STEP)["with"]
        self.assertEqual(create["title"],
                         "DMI Release: ${{ steps.period.outputs.period }} (not deployed)")
        self.assertEqual(create["branch"], "release/${{ steps.period.outputs.period }}")
        self.assertEqual(set(create["labels"].split()) & wd.RELEASE_LABELS, wd.RELEASE_LABELS)


def _enclosing(tree, target):
    """The innermost function definition containing ``target``."""
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and any(n is target for n in ast.walk(node)):
            if best is None or node.lineno > best.lineno:
                best = node
    return best


if __name__ == "__main__":
    unittest.main()
