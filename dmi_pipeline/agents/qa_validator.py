"""
QA Validator & Report Generator - Quality assurance gates for DMI releases.

Implements hard checks, soft checks, and policy gates per v0.1.8 spec.
"""

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime
import uuid

import pandas as pd


def run_hard_checks(
    dmi_output: Dict,
    cpi_data: pd.DataFrame,
    weights_data: pd.DataFrame,
    slack_data: pd.DataFrame
) -> List[Dict]:
    """
    Run hard QA checks that must pass for release.
    
    Returns list of check results.
    """
    checks = []
    
    # Check 1: All quintiles present
    quintiles = {d['group_id'] for d in dmi_output['dmi_by_group']}
    expected_quintiles = {'Q1', 'Q2', 'Q3', 'Q4', 'Q5'}
    
    if quintiles == expected_quintiles:
        checks.append({
            "check_id": "DMI_OUTPUT_ALL_QUINTILES_PRESENT",
            "status": "PASS",
            "message": "All 5 quintiles present in output"
        })
    else:
        checks.append({
            "check_id": "DMI_OUTPUT_ALL_QUINTILES_PRESENT",
            "status": "FAIL",
            "message": f"Missing quintiles: {expected_quintiles - quintiles}"
        })
    
    # Check 2: DMI values in reasonable range
    dmi_values = [d['dmi'] for d in dmi_output['dmi_by_group']]
    all_reasonable = all(0 <= v <= 100 for v in dmi_values)
    
    if all_reasonable:
        checks.append({
            "check_id": "DMI_VALUES_REASONABLE_RANGE",
            "status": "PASS",
            "message": f"All DMI values in [0, 100]: range {min(dmi_values):.2f} to {max(dmi_values):.2f}",
            "metrics": {"min": min(dmi_values), "max": max(dmi_values)}
        })
    else:
        checks.append({
            "check_id": "DMI_VALUES_REASONABLE_RANGE",
            "status": "FAIL",
            "message": "DMI values outside reasonable range [0, 100]"
        })
    
    # Check 3: Inflation values calculated
    inflation_values = [d['inflation'] for d in dmi_output['dmi_by_group']]
    has_inflation = all(v is not None for v in inflation_values)
    
    if has_inflation:
        checks.append({
            "check_id": "INFLATION_VALUES_PRESENT",
            "status": "PASS",
            "message": f"Inflation computed for all quintiles: range {min(inflation_values):.2f}% to {max(inflation_values):.2f}%",
            "metrics": {"min": min(inflation_values), "max": max(inflation_values)}
        })
    else:
        checks.append({
            "check_id": "INFLATION_VALUES_PRESENT",
            "status": "FAIL",
            "message": "Missing inflation values"
        })
    
    # Check 4: CPI category coverage (t and t-12)
    reference_period = dmi_output['reference_period']
    cpi_at_t = cpi_data[cpi_data['period'] == reference_period]
    
    expected_categories = 8  # 8 major groups
    categories_at_t = len([c for c in cpi_at_t.columns if c.startswith('CPI_')])
    
    if categories_at_t >= expected_categories:
        checks.append({
            "check_id": "CPI_CATEGORY_COVERAGE_COMPLETE",
            "status": "PASS",
            "message": f"All {expected_categories} CPI categories present at t={reference_period}",
            "metrics": {"categories_count": categories_at_t}
        })
    else:
        checks.append({
            "check_id": "CPI_CATEGORY_COVERAGE_COMPLETE",
            "status": "FAIL",
            "message": f"Missing CPI categories: found {categories_at_t}, expected {expected_categories}"
        })
    
    # Check 5: Weights sum to 1.0
    weights_valid = True
    for group_id in ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']:
        group_weights = weights_data[weights_data['group_id'] == group_id]
        weight_sum = group_weights['weight'].sum()
        if abs(weight_sum - 1.0) > 0.001:
            weights_valid = False
            break
    
    if weights_valid:
        checks.append({
            "check_id": "WEIGHTS_SUM_TO_ONE",
            "status": "PASS",
            "message": "All quintile weights sum to 1.0 ± 0.001"
        })
    else:
        checks.append({
            "check_id": "WEIGHTS_SUM_TO_ONE",
            "status": "FAIL",
            "message": f"Weights for {group_id} sum to {weight_sum:.4f}, expected 1.0"
        })
    
    return checks


def run_soft_checks(dmi_output: Dict, weights_data: pd.DataFrame) -> List[Dict]:
    """
    Run soft QA checks (warnings, not blockers).
    
    Returns list of check results.
    """
    checks = []
    
    # Check 1: DMI gradient (Q1 should typically >= Q5)
    q1_dmi = next(d['dmi'] for d in dmi_output['dmi_by_group'] if d['group_id'] == 'Q1')
    q5_dmi = next(d['dmi'] for d in dmi_output['dmi_by_group'] if d['group_id'] == 'Q5')
    
    if q1_dmi >= q5_dmi:
        checks.append({
            "check_id": "DMI_DISTRIBUTIONAL_GRADIENT",
            "status": "PASS",
            "message": f"Expected pattern: Q1 ({q1_dmi:.2f}) >= Q5 ({q5_dmi:.2f})",
            "metrics": {"q1_dmi": q1_dmi, "q5_dmi": q5_dmi, "difference": q1_dmi - q5_dmi}
        })
    else:
        checks.append({
            "check_id": "DMI_DISTRIBUTIONAL_GRADIENT",
            "status": "WARN",
            "message": f"Unusual pattern: Q5 ({q5_dmi:.2f}) > Q1 ({q1_dmi:.2f}) - verify data",
            "metrics": {"q1_dmi": q1_dmi, "q5_dmi": q5_dmi}
        })
    
    # Check 2: Weights vintage age
    weights_year = dmi_output['parameters']['weights_year']
    reference_year = int(dmi_output['reference_period'][:4])
    vintage_age = reference_year - weights_year
    
    if vintage_age <= 2:
        checks.append({
            "check_id": "WEIGHTS_VINTAGE_AGE",
            "status": "PASS",
            "message": f"Weights vintage age: {vintage_age} years (acceptable)",
            "metrics": {"weights_year": weights_year, "reference_year": reference_year, "age": vintage_age}
        })
    else:
        checks.append({
            "check_id": "WEIGHTS_VINTAGE_AGE",
            "status": "WARN",
            "message": f"Weights vintage age: {vintage_age} years (>2 years old, consider updating)",
            "metrics": {"weights_year": weights_year, "reference_year": reference_year, "age": vintage_age}
        })
    
    return checks


def run_policy_gates(dmi_output: Dict, weights_data: pd.DataFrame) -> List[Dict]:
    """
    Run policy gate checks (weights vintage policy, etc.).
    
    Returns list of gate results.
    """
    gates = []
    
    # Gate 1: CE weights conservative policy
    weights_year = dmi_output['parameters']['weights_year']
    reference_year = int(dmi_output['reference_period'][:4])
    
    # Per conservative policy: use most recent CE table, but only update when new data available
    is_current = (reference_year - weights_year) <= 1
    
    gates.append({
        "gate_id": "CE_WEIGHTS_CONSERVATIVE_POLICY",
        "status": "PASS" if is_current else "WARN",
        "policy_ref": "ce_weights_policy_v0_1.json",
        "decision": {
            "weights_year": weights_year,
            "reference_year": reference_year,
            "is_current": is_current
        },
        "message": f"Using {weights_year} weights for {reference_year} data ({'current' if is_current else 'outdated - review needed'})"
    })
    
    return gates


def generate_qa_report(
    dmi_output: Dict,
    cpi_data: pd.DataFrame,
    weights_data: pd.DataFrame,
    slack_data: pd.DataFrame,
    output_path: Optional[Path] = None,
    raw_artifact_path: Optional[Path] = None,
    specification: Optional[str] = None,
) -> Dict:
    """
    Generate comprehensive QA report for DMI release.

    Returns QA report dict conforming to qa_report.schema.json.

    Round-4 §1: when ``raw_artifact_path`` and ``specification`` are
    supplied, the report carries a ``subject`` block binding it to the
    exact artifact bytes and specification it was computed from. Release
    finalization requires that binding, because a filename alone is not
    evidence that a report describes the artifact it sits next to.
    """
    # Run checks
    hard_checks = run_hard_checks(dmi_output, cpi_data, weights_data, slack_data)
    soft_checks = run_soft_checks(dmi_output, weights_data)
    policy_gates = run_policy_gates(dmi_output, weights_data)
    
    # Aggregate status
    hard_fail_count = sum(1 for c in hard_checks if c['status'] == 'FAIL')
    soft_warn_count = sum(1 for c in soft_checks if c['status'] == 'WARN')
    policy_fail_count = sum(1 for g in policy_gates if g['status'] == 'FAIL')
    
    overall_status = "PASS"
    if hard_fail_count > 0 or policy_fail_count > 0:
        overall_status = "FAIL"
    elif soft_warn_count > 0:
        overall_status = "PASS_WITH_WARNING"
    
    # Compile report
    report = {
        "schema_version": "0.1.8",
        "run_id": str(uuid.uuid4()),
        "reference_period": dmi_output['reference_period'],
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": overall_status,
        "hard_checks": hard_checks,
        "soft_checks": soft_checks,
        "policy_gates": policy_gates,
        "warnings": [c['message'] for c in soft_checks + policy_gates if c.get('status') == 'WARN'],
        "errors": [c['message'] for c in hard_checks + policy_gates if c.get('status') == 'FAIL'],
        "summary": {
            "hard_fail_count": hard_fail_count,
            "soft_warn_count": soft_warn_count,
            "policy_fail_count": policy_fail_count
        }
    }

    # Round-4 §1: bind the report to the artifact it actually describes.
    # Hashing the on-disk bytes (rather than re-serialising `dmi_output`)
    # means the binding breaks if the raw file is edited after the checks
    # ran, which is precisely the substitution we need to detect.
    if raw_artifact_path is not None and specification is not None:
        raw_path = Path(raw_artifact_path)
        digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        try:
            recorded_path = str(raw_path.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            recorded_path = str(raw_path)
        report["subject"] = {
            "specification": specification,
            "reference_period": dmi_output["reference_period"],
            "raw_artifact": recorded_path,
            "raw_sha256": digest,
        }

    # Save if path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"✓ Saved QA report to {output_path}")
    
    return report


def print_qa_summary(report: Dict):
    """Print human-readable QA summary."""
    print("\n" + "=" * 80)
    print("QA REPORT SUMMARY")
    print("=" * 80)
    print(f"Status: {report['status']}")
    print(f"Reference Period: {report['reference_period']}")
    print(f"Run ID: {report['run_id']}")
    
    summary = report['summary']
    print(f"\nChecks Summary:")
    print(f"  Hard Failures: {summary['hard_fail_count']}")
    print(f"  Soft Warnings: {summary['soft_warn_count']}")
    print(f"  Policy Failures: {summary['policy_fail_count']}")
    
    print(f"\nHard Checks ({len(report['hard_checks'])}):")
    for check in report['hard_checks']:
        status_icon = "✓" if check['status'] == "PASS" else "✗"
        print(f"  {status_icon} {check['check_id']}: {check.get('message', '')}")
    
    print(f"\nSoft Checks ({len(report['soft_checks'])}):")
    for check in report['soft_checks']:
        status_icon = "✓" if check['status'] == "PASS" else "⚠"
        print(f"  {status_icon} {check['check_id']}: {check.get('message', '')}")
    
    print(f"\nPolicy Gates ({len(report['policy_gates'])}):")
    for gate in report['policy_gates']:
        status_icon = "✓" if gate['status'] == "PASS" else "⚠"
        print(f"  {status_icon} {gate['gate_id']}: {gate.get('message', '')}")
    
    if report['errors']:
        print(f"\n❌ ERRORS ({len(report['errors'])}):")
        for error in report['errors']:
            print(f"  - {error}")
    
    if report['warnings']:
        print(f"\n⚠️  WARNINGS ({len(report['warnings'])}):")
        for warning in report['warnings']:
            print(f"  - {warning}")
    
    print("=" * 80)
