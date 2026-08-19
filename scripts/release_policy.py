#!/usr/bin/env python3
"""Publication gates: QA outcome policy and cross-specification identity (§1).

These are the checks that must pass BEFORE any mutable public artifact is
written. They are deliberately a separate, importable module rather than
inline workflow YAML, because a gate that exists only as a shell step in
one workflow cannot be unit-tested and cannot be reused by the other
entry points that publish.

What was wrong before
---------------------
The monthly workflow validated that QA reports were *well-formed JSON
matching a schema* and then proceeded. Schema validity is not an
outcome: a report with ``status: "FAIL"`` and five hard failures is a
perfectly valid document. Nothing anywhere read ``status`` or the
failure counts before publishing, and nothing compared Baseline against
Slack-Plus at runtime.

Two gate families
-----------------
``evaluate_qa_report``  — outcome policy for one report (§1 QA policy).
``check_cross_spec``    — Baseline/Slack-Plus identity (§1 identity gate).

Both return a list of problem strings; empty means pass. Returning
problems rather than raising lets a caller collect every failure in one
run instead of surfacing them one restart at a time.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = REPO_ROOT / "schemas"

#: Statuses that may proceed to publication. `PASS_WITH_WARNING` is
#: permitted only when both failure counts are zero — see below; the
#: status string alone is not trusted.
ACCEPTABLE_STATUSES = frozenset({"PASS", "PASS_WITH_WARNING"})

#: Tolerance for float comparison of price-side values. The two specs
#: consume the identical CPI series through the identical weights, so
#: any real difference is astronomically larger than this.
PRICE_TOLERANCE = 1e-9


class GateFailure(RuntimeError):
    """A publication gate rejected the release."""


# ---------------------------------------------------------------------------
# QA outcome policy
# ---------------------------------------------------------------------------

def evaluate_qa_report(
    report_path: Path,
    expected_period: str,
    expected_spec: str,
    raw_artifact_path: Optional[Path] = None,
    require_subject: bool = True,
) -> tuple[list[str], list[str]]:
    """Enforce QA outcome policy for one report.

    Returns ``(problems, warnings)``. Publication may proceed only when
    ``problems`` is empty; ``warnings`` must be surfaced prominently but
    do not block.

    Policy (§1):

    - a missing or malformed report is a failure, not an absence;
    - ``FAIL`` is rejected;
    - a nonzero ``hard_fail_count`` is rejected;
    - a nonzero ``policy_fail_count`` is rejected;
    - ``PASS`` is permitted;
    - ``PASS_WITH_WARNING`` is permitted only when both failure counts
      are zero;
    - the report's ``reference_period`` must equal the requested period;
    - the report must be bound to the intended raw artifact and
      specification by content, not by filename.

    The counts are checked independently of ``status`` on purpose. If a
    generator ever computed the status wrongly, trusting the string would
    publish a failing release; requiring both means the two have to agree.
    """
    problems: list[str] = []
    warnings: list[str] = []

    if not report_path.is_file():
        return ([
            f"{expected_spec}: QA report is missing: {report_path}. A "
            f"missing report is a failure, not an absence of findings."
        ], warnings)

    try:
        report = json.loads(report_path.read_text())
    except json.JSONDecodeError as exc:
        return ([
            f"{expected_spec}: QA report is malformed JSON "
            f"({report_path.name}): {exc}"
        ], warnings)

    if not isinstance(report, dict):
        return ([
            f"{expected_spec}: QA report is not an object "
            f"({report_path.name})"
        ], warnings)

    # Schema shape, so downstream field access is meaningful.
    try:
        from jsonschema import Draft202012Validator

        schema = json.loads(
            (SCHEMAS_DIR / "qa_report.schema.json").read_text()
        )
        Draft202012Validator.check_schema(schema)
        for err in sorted(
            Draft202012Validator(schema).iter_errors(report),
            key=lambda e: list(e.absolute_path),
        ):
            problems.append(
                f"{expected_spec}: {report_path.name} violates "
                f"qa_report.schema.json at {list(err.absolute_path)}: "
                f"{err.message}"
            )
        if problems:
            return (problems, warnings)
    except ImportError:  # pragma: no cover - jsonschema is a dependency
        problems.append("jsonschema is required to evaluate QA reports")
        return (problems, warnings)

    # --- period ---------------------------------------------------------
    actual_period = report.get("reference_period")
    if actual_period != expected_period:
        problems.append(
            f"{expected_spec}: QA report declares reference_period "
            f"{actual_period!r}, expected {expected_period!r}"
        )

    # --- outcome --------------------------------------------------------
    status = report.get("status")
    summary = report.get("summary") or {}
    hard = summary.get("hard_fail_count", 0)
    policy = summary.get("policy_fail_count", 0)
    soft = summary.get("soft_warn_count", 0)

    if status not in ACCEPTABLE_STATUSES:
        problems.append(
            f"{expected_spec}: QA status is {status!r}; publication "
            f"requires one of {sorted(ACCEPTABLE_STATUSES)}"
        )

    if hard:
        problems.append(
            f"{expected_spec}: QA reports {hard} hard failure(s); "
            f"publication requires zero"
        )
    if policy:
        problems.append(
            f"{expected_spec}: QA reports {policy} policy failure(s); "
            f"publication requires zero"
        )

    # `PASS_WITH_WARNING` is conditional, not a free pass.
    if status == "PASS_WITH_WARNING" and (hard or policy):
        problems.append(
            f"{expected_spec}: QA status PASS_WITH_WARNING is permitted "
            f"only when hard and policy failure counts are both zero "
            f"(hard={hard}, policy={policy})"
        )

    # Independent evidence: explicit FAIL entries in the check lists.
    for field in ("hard_checks", "policy_gates"):
        for entry in report.get(field) or []:
            if entry.get("status") == "FAIL":
                problems.append(
                    f"{expected_spec}: {field} entry "
                    f"{entry.get('check_id') or entry.get('gate_id')!r} "
                    f"reports FAIL"
                )

    for message in report.get("errors") or []:
        problems.append(f"{expected_spec}: QA error: {message}")

    # --- warnings (surfaced, never blocking) ----------------------------
    for message in report.get("warnings") or []:
        warnings.append(f"{expected_spec}: {message}")
    if soft and not warnings:
        warnings.append(
            f"{expected_spec}: {soft} soft warning(s) recorded with no "
            f"warning text"
        )

    # --- binding to the intended artifact -------------------------------
    subject = report.get("subject")
    if subject is None:
        if require_subject:
            problems.append(
                f"{expected_spec}: QA report carries no `subject` binding. "
                f"The filename alone is not evidence that this report "
                f"describes the intended raw artifact; regenerate it with "
                f"a raw_artifact_path and specification."
            )
    else:
        if subject.get("specification") != expected_spec:
            problems.append(
                f"{expected_spec}: QA report subject declares "
                f"specification {subject.get('specification')!r}"
            )
        if subject.get("reference_period") != expected_period:
            problems.append(
                f"{expected_spec}: QA report subject declares period "
                f"{subject.get('reference_period')!r}, expected "
                f"{expected_period!r}"
            )
        if raw_artifact_path is not None:
            if not Path(raw_artifact_path).is_file():
                problems.append(
                    f"{expected_spec}: raw artifact named by the QA "
                    f"subject does not exist: {raw_artifact_path}"
                )
            else:
                actual = hashlib.sha256(
                    Path(raw_artifact_path).read_bytes()
                ).hexdigest()
                if actual != subject.get("raw_sha256"):
                    problems.append(
                        f"{expected_spec}: QA report was computed against "
                        f"different bytes than the artifact being "
                        f"published (subject sha256 "
                        f"{subject.get('raw_sha256')!r}, actual {actual!r}). "
                        f"The raw artifact changed after QA ran."
                    )

    return (problems, warnings)


# ---------------------------------------------------------------------------
# Cross-specification identity
# ---------------------------------------------------------------------------

#: Parameters that MUST be identical across the two specifications.
#: `slack_measure` and `spec_id` are excluded because differing there is
#: the entire point of the companion specification.
SHARED_PARAMETERS = ("alpha", "scale_factor", "weights_year",
                     "inflation_measure")

#: The declared labor-slack construction: which `slack_measure` each
#: specification is required to use.
DECLARED_SLACK_MEASURE = {"baseline": "u3", "slack_plus": "u6"}


def check_cross_spec(baseline: dict, slack_plus: dict) -> list[str]:
    """Verify Baseline and Slack-Plus differ ONLY in labor slack (§1).

    The two specifications consume the same CPI series through the same
    quintile weights; they diverge only in the unemployment measure. So
    every price-side value must be bit-for-bit comparable, and the DMI
    difference must be exactly what the declared slack difference
    implies. Checking "the numbers look different" would pass a run in
    which the wrong CPI vintage reached one specification.
    """
    problems: list[str] = []

    # --- period ---------------------------------------------------------
    bp = baseline.get("reference_period")
    sp = slack_plus.get("reference_period")
    if bp != sp:
        problems.append(
            f"cross-spec: reference periods differ (baseline {bp!r}, "
            f"slack_plus {sp!r})"
        )

    # --- identity -------------------------------------------------------
    if baseline.get("specification") != "baseline":
        problems.append(
            f"cross-spec: baseline artifact declares specification "
            f"{baseline.get('specification')!r}"
        )
    if slack_plus.get("specification") != "slack_plus":
        problems.append(
            f"cross-spec: slack_plus artifact declares specification "
            f"{slack_plus.get('specification')!r}"
        )

    bpar = baseline.get("parameters") or {}
    spar = slack_plus.get("parameters") or {}

    # --- shared parameters (weights vintage, price construction) --------
    for key in SHARED_PARAMETERS:
        if bpar.get(key) != spar.get(key):
            problems.append(
                f"cross-spec: parameter {key!r} differs (baseline "
                f"{bpar.get(key)!r}, slack_plus {spar.get(key)!r}); the "
                f"two specifications must share the weights vintage and "
                f"price construction"
            )

    # --- declared slack construction ------------------------------------
    for label, params in (("baseline", bpar), ("slack_plus", spar)):
        expected = DECLARED_SLACK_MEASURE[label]
        if params.get("slack_measure") != expected:
            problems.append(
                f"cross-spec: {label} declares slack_measure "
                f"{params.get('slack_measure')!r}, expected {expected!r}"
            )

    # --- price-side values, per quintile --------------------------------
    bg = {g["group_id"]: g for g in baseline.get("dmi_by_group") or []}
    sg = {g["group_id"]: g for g in slack_plus.get("dmi_by_group") or []}
    if set(bg) != set(sg):
        problems.append(
            f"cross-spec: quintile sets differ (baseline {sorted(bg)}, "
            f"slack_plus {sorted(sg)})"
        )
    for gid in sorted(set(bg) & set(sg)):
        bi = bg[gid].get("inflation")
        si = sg[gid].get("inflation")
        if bi is None or si is None or abs(float(bi) - float(si)) > PRICE_TOLERANCE:
            problems.append(
                f"cross-spec: {gid} inflation differs (baseline {bi}, "
                f"slack_plus {si}); the price side must be identical"
            )

    # --- price-side inputs ----------------------------------------------
    if baseline.get("inflation_contributions") != \
            slack_plus.get("inflation_contributions"):
        problems.append(
            "cross-spec: inflation_contributions differ; the two "
            "specifications must consume identical price-side inputs"
        )

    if problems:
        # Later checks assume the shared parameters agree.
        return problems

    # --- the difference must be ONLY the slack difference ---------------
    alpha = float(bpar.get("alpha"))
    scale = float(bpar.get("scale_factor"))
    for gid in sorted(set(bg) & set(sg)):
        d_slack = float(sg[gid]["slack"]) - float(bg[gid]["slack"])
        d_dmi = float(sg[gid]["dmi"]) - float(bg[gid]["dmi"])
        implied = scale * (1.0 - alpha) * d_slack
        if abs(d_dmi - implied) > 1e-6:
            problems.append(
                f"cross-spec: {gid} DMI difference {d_dmi:.9f} is not "
                f"explained by the slack difference alone (implied "
                f"{implied:.9f}); something other than labor slack "
                f"changed between the two specifications"
            )

    return problems
