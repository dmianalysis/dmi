#!/usr/bin/env python3
"""Out-of-sample confirmation of the frozen 2024 PUMD estimator.

RESEARCH ONLY. This script writes under ``data/research/`` and
``registry/research/`` and reads only research registries, Milestone-1 and
Milestone-2 artifacts, and the pinned PUMD archive. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

The script has two modes and they are deliberately separate commands, because
the ordering is the whole point of the exercise::

    python3 scripts/confirm_pumd_2024.py freeze
    git commit registry/research/pumd_lb01_confirmation_spec_v0_1.json ...
    python3 scripts/confirm_pumd_2024.py run

``freeze`` reads no microdata at all. It builds the confirmation universe and
roster from the published artifacts and the hierarchical grouping files, and
writes the specification. ``run`` refuses to start unless that specification
already exists on disk, and refuses to continue unless the roster it rebuilds
hashes to the value the specification pinned. A confirmation set therefore
cannot be adjusted after an error has been seen without the adjustment showing
up as a hash mismatch and, in git, as a specification edited after the fact.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import (  # noqa: E402
    pumd,
    pumd_benchmark as bench,
    pumd_confirmation as confirm,
    research_csv,
)

MILESTONE_1 = REPO_ROOT / "data/research/detailed_inflation/audit_2024"
MILESTONE_2 = REPO_ROOT / "data/research/detailed_inflation/milestone_2"
OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/pumd_confirmation_2024"
SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_confirmation_spec_v0_1.json"
FROZEN_SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_benchmark_spec_v0_1.json"
SOURCE_REGISTRY = REPO_ROOT / "registry/research/pumd_2024_interview_source_v0_1.json"
UNIVERSE_PATH = OUTPUT_DIR / "candidate_universe.csv"
STUB_DIR = Path.home() / "dev/dmi-data/pumd/2024/docs/stubs/stubs"

ESTIMATOR_MODULES = (
    "dmi_research/detailed_inflation/pumd.py",
    "dmi_research/detailed_inflation/pumd_benchmark.py",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_inputs(stub_dir: Path):
    interview_stub = pumd.read_stub_file(stub_dir / "CE-HG-Inter-2024.txt")
    integrated_stub = pumd.read_stub_file(stub_dir / "CE-HG-Integ-2024.txt")
    provenance = read_csv(MILESTONE_2 / "ucc_provenance_classes_2024.csv")
    basis = read_csv(MILESTONE_1 / "active_ucc_basis.csv")
    exceptions = [row["ucc"] for row in read_csv(MILESTONE_1 / "exception_ledger.csv")]
    return provenance, basis, exceptions, interview_stub, integrated_stub


def build(stub_dir: Path):
    inputs = load_inputs(stub_dir)
    universe = confirm.classify_universe(*inputs)
    roster = confirm.confirmation_roster(*inputs)
    return universe, roster


# ---------------------------------------------------------------------------
# freeze
# ---------------------------------------------------------------------------


def freeze(stub_dir: Path) -> int:
    if SPEC_PATH.exists():
        print(
            f"refusing to overwrite {SPEC_PATH.relative_to(REPO_ROOT)}.\n"
            "A frozen confirmation specification is frozen. If the "
            "construction rule genuinely needs to change, increment the "
            "version and write a new file, leaving this one in place.",
            file=sys.stderr,
        )
        return 1

    universe, roster = build(stub_dir)
    frozen = bench.BenchmarkSpec.from_json(FROZEN_SPEC_PATH)
    spec = confirm.confirmation_spec(frozen, roster)

    research_csv.write_csv(UNIVERSE_PATH, confirm.UNIVERSE_COLUMNS, confirm.universe_rows(universe))
    source = json.loads(SOURCE_REGISTRY.read_text(encoding="utf-8"))
    archive = source["archives"]["INTRVW24"]

    payload = {
        "artifact": "pumd_lb01_confirmation_spec",
        "confirmation_spec_version": confirm.CONFIRMATION_SPEC_VERSION,
        "confirmation_roster_version": confirm.CONFIRMATION_ROSTER_VERSION,
        "status": "RESEARCH_ONLY",
        "purpose": (
            "Out-of-sample confirmation that the 2024 CE Interview PUMD "
            "estimator frozen at commit "
            f"{confirm.FROZEN_ESTIMATOR_COMMIT} continues to reproduce "
            "published LB01 means on eligible UCCs that played no part in "
            "its development. A PASS is evidence that the estimator "
            "generalises. It is not an authorisation for any UCC whose "
            "quantitative usability is not established."
        ),
        "frozen_estimator": {
            "commit": confirm.FROZEN_ESTIMATOR_COMMIT,
            "tag": confirm.FROZEN_ESTIMATOR_TAG,
            "roster_selection_rule_version": bench.ROSTER_VERSION,
            "module_sha256": {
                module: confirm.file_digest(REPO_ROOT / module)
                for module in ESTIMATOR_MODULES
            },
        },
        "frozen_benchmark_spec": {
            "path": str(FROZEN_SPEC_PATH.relative_to(REPO_ROOT)),
            "spec_version": frozen.spec_version,
            "roster_version": frozen.roster_version,
            "development_roster_hash": frozen.roster_hash,
            "file_sha256": confirm.file_digest(FROZEN_SPEC_PATH),
        },
        "acceptance_rule": {
            "inherited_from": str(FROZEN_SPEC_PATH.relative_to(REPO_ROOT)),
            "inheritance_mechanism": (
                "dataclasses.replace on the loaded BenchmarkSpec, changing "
                "roster_hash and nothing else. No threshold is restated in "
                "the confirmation code path, so no threshold can be changed "
                "there."
            ),
            "thresholds_changed_for_confirmation": [],
            "population_tolerance_pct": frozen.population_tolerance_pct,
            "quintile_population_tolerance_pct": frozen.quintile_population_tolerance_pct,
            "median_abs_pct_error_max": frozen.median_abs_pct_error_max,
            "p75_abs_pct_error_max": frozen.p75_abs_pct_error_max,
            "p90_abs_pct_error_max": frozen.p90_abs_pct_error_max,
            "per_ucc_abs_pct_error_max": frozen.per_ucc_abs_pct_error_max,
            "per_ucc_pass_fraction_min": frozen.per_ucc_pass_fraction_min,
            "mean_signed_pct_error_abs_max": frozen.mean_signed_pct_error_abs_max,
            "small_value_absolute_floor": frozen.small_value_absolute_floor,
            "small_value_abs_diff_max": frozen.small_value_abs_diff_max,
        },
        "eligibility_rule": {
            "version": bench.ROSTER_VERSION,
            "source": "dmi_research.detailed_inflation.pumd_benchmark.eligible_candidates",
            "reused_without_modification": True,
            "tests_in_order": [
                "not one of the four Milestone-2 shelter UCCs 910104-910107",
                "Milestone-2 provenance_class is DIRECT_CONCORDANCE_UCC",
                "Milestone-2 ce_source is I (Interview)",
                "not one of the 58 Milestone-1 exception UCCs",
                "present in CE-HG-Inter-2024.txt in section EXPEND",
                "present in CE-HG-Integ-2024.txt in section EXPEND with survey I",
                "LABSTAT publishes a non-blank mean for all six LB01 populations",
            ],
            "confirmation_additional_tests_in_order": [
                "hierarchical-grouping annualization factor is 1, the only "
                "value the Phase-B benchmark exercised",
                "not in the frozen fifteen-UCC development roster",
            ],
            "development_rule_devices_not_applied": [
                "the (node, stratum) median selection, which exists to build "
                "a small balanced roster",
                "the requirement that a DMI node span all three magnitude "
                "strata, which exists for the same reason",
            ],
            "selection": (
                "None. The confirmation roster is the entire remaining "
                "eligible pool. No UCC is sampled in and none can be dropped."
            ),
            "notes_on_the_exclusion_tally": [
                "Reasons are tested in the order listed and a UCC is recorded "
                "under the first that applies, so the tally partitions the "
                "universe rather than double-counting it. A reason with a "
                "count of zero means no UCC reached that test still eligible, "
                "not that the test was skipped.",
                "All 58 Milestone-1 exception UCCs are present in the ledger "
                "and all 58 are already excluded as NOT_DIRECT_CONCORDANCE_UCC "
                "by the earlier Milestone-2 test, which is why "
                "MILESTONE_1_EXCEPTION counts zero. The test is retained "
                "because its redundancy is a property of the 2024 data, not "
                "of the rule.",
                "INTEGRATED_STUB_SURVEY_NOT_INTERVIEW counts only 2 for the "
                "same ordering reason: the Milestone-2 ce_source test catches "
                "most Diary-sourced UCCs first. It is not a restatement of "
                "the 27 UCCs the v0.2 selection-rule correction removed.",
            ],
        },
        "candidate_universe": {
            "source": str(
                (MILESTONE_2 / "ucc_provenance_classes_2024.csv").relative_to(REPO_ROOT)
            ),
            "ledger": str(UNIVERSE_PATH.relative_to(REPO_ROOT)),
            "ledger_sha256": confirm.file_digest(UNIVERSE_PATH),
            "ledger_content_hash": confirm.universe_hash(universe),
            "total_uccs": len(universe),
            "included_count": sum(1 for row in universe if row.status == confirm.INCLUDED),
            "excluded_count": sum(1 for row in universe if row.status == confirm.EXCLUDED),
            "exclusions_by_reason": confirm.exclusion_tally(universe),
        },
        "confirmation_roster": {
            "size": len(roster),
            "roster_hash": spec.roster_hash,
            "comparison_count": len(roster) * len(bench.REQUIRED_CHARACTERISTICS),
            "populations": list(bench.LABSTAT_POPULATION_BY_CODE.values()),
            "entries": bench.roster_rows(roster),
        },
        "pumd_source": {
            "registry": str(SOURCE_REGISTRY.relative_to(REPO_ROOT)),
            "archive": "INTRVW24",
            "archive_sha256": archive["sha256"],
            "archive_bytes": archive.get("bytes"),
        },
        "estimand": {
            "code": bench.ESTIMAND,
            "units": bench.ESTIMAND_UNITS,
        },
        "excluded_from_calibration": list(bench.EXCLUDED_FROM_CALIBRATION),
        "frozen_before_any_comparison": (
            "This file is written by `scripts/confirm_pumd_2024.py freeze`, "
            "which reads no microdata. The comparison is run by a separate "
            "command that refuses to start unless this file already exists "
            "and refuses to continue unless the roster it rebuilds hashes to "
            "the value pinned above."
        ),
    }
    SPEC_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"universe: {len(universe)} UCCs -> {UNIVERSE_PATH.relative_to(REPO_ROOT)}")
    for reason, count in confirm.exclusion_tally(universe).items():
        print(f"  {reason:42s} {count:5d}")
    print(f"confirmation roster: {len(roster)} UCCs, hash {spec.roster_hash}")
    print(f"comparisons to run: {len(roster) * len(bench.REQUIRED_CHARACTERISTICS)}")
    print(f"spec written: {SPEC_PATH.relative_to(REPO_ROOT)}")
    print("\nCommit this specification before running the confirmation.")
    return 0


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


def _spec_is_committed() -> bool:
    """Whether the frozen specification is already in git history."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", str(SPEC_PATH.relative_to(REPO_ROOT))],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return bool(result.stdout.strip())


def run(stub_dir: Path, pumd_dir: str | None, allow_uncommitted: bool) -> int:
    if not SPEC_PATH.exists():
        print(
            f"{SPEC_PATH.relative_to(REPO_ROOT)} does not exist. Run "
            "`confirm_pumd_2024.py freeze` and commit the result before "
            "computing any comparison.",
            file=sys.stderr,
        )
        return 1
    if not _spec_is_committed() and not allow_uncommitted:
        print(
            f"{SPEC_PATH.relative_to(REPO_ROOT)} exists but is not in git "
            "history. The freeze is only meaningful if it is provably prior "
            "to the comparison. Commit it first, or pass "
            "--allow-uncommitted-spec and explain why in the write-up.",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    universe, roster = build(stub_dir)

    pinned = payload["confirmation_roster"]["roster_hash"]
    rebuilt = bench.roster_hash(roster)
    if rebuilt != pinned:
        print(
            "the confirmation roster has changed since it was frozen: spec "
            f"pins {pinned}, roster hashes to {rebuilt}. The confirmation "
            "cannot proceed against a roster the specification does not "
            "describe.",
            file=sys.stderr,
        )
        return 1
    ledger_hash = confirm.universe_hash(universe)
    if ledger_hash != payload["candidate_universe"]["ledger_content_hash"]:
        print(
            "the candidate universe has changed since it was frozen: spec "
            f"pins {payload['candidate_universe']['ledger_content_hash']}, "
            f"ledger hashes to {ledger_hash}.",
            file=sys.stderr,
        )
        return 1

    frozen = bench.BenchmarkSpec.from_json(FROZEN_SPEC_PATH)
    spec = confirm.confirmation_spec(frozen, roster)
    if confirm.file_digest(FROZEN_SPEC_PATH) != payload["frozen_benchmark_spec"]["file_sha256"]:
        print(
            "the frozen Phase-B benchmark specification has been edited since "
            "the confirmation was frozen. Stop and investigate.",
            file=sys.stderr,
        )
        return 1
    for module, digest in payload["frozen_estimator"]["module_sha256"].items():
        if confirm.file_digest(REPO_ROOT / module) != digest:
            print(
                f"{module} has been edited since the confirmation was frozen. "
                "The confirmation is only meaningful against the frozen "
                "estimator. Stop and investigate.",
                file=sys.stderr,
            )
            return 1

    print(f"confirmation roster: {len(roster)} UCCs, hash {rebuilt}")

    directory = pumd.locate_interview_csv_dir(pumd_dir)
    units = pumd.read_all_fmli(directory)
    keep = frozenset(entry.ucc for entry in roster)
    records = pumd.read_all_mtbi(directory, keep_uccs=keep)
    print(f"microdata: {len(units)} FMLI records, {len(records)} MTBI records in scope")

    populations = pumd.population_estimates(units)
    frozen_payload = json.loads(FROZEN_SPEC_PATH.read_text(encoding="utf-8"))
    targets = frozen_payload["population_validation"]
    comparisons = bench.compare_populations(
        populations,
        units,
        targets["published_targets_2024_consumer_units_thousands"],
        targets["published_mean_income_before_taxes_2024"],
    )
    research_csv.write_csv(
        OUTPUT_DIR / "population_validation.csv",
        tuple(asdict(comparisons[0])),
        [asdict(row) for row in comparisons],
    )

    basis = read_csv(MILESTONE_1 / "active_ucc_basis.csv")
    results, _ = bench.run_benchmark(roster, units, records, basis, spec)
    research_csv.write_csv(
        OUTPUT_DIR / "confirmation_results.csv",
        tuple(asdict(results[0])),
        [_result_row(result) for result in results],
    )

    summary = bench.summarize(results, comparisons, roster, spec)
    all_cu = next(r for r in comparisons if r.population == "All Consumer Units")
    worst_quintile = max(
        (r for r in comparisons if r.population != "All Consumer Units"),
        key=lambda r: abs(r.percentage_difference),
    )

    out = asdict(summary)
    out["confirmation_status"] = summary.benchmark_status
    out["confirmation_spec_version"] = confirm.CONFIRMATION_SPEC_VERSION
    out["confirmation_roster_version"] = confirm.CONFIRMATION_ROSTER_VERSION
    out["frozen_estimator_commit"] = confirm.FROZEN_ESTIMATOR_COMMIT
    out["frozen_estimator_tag"] = confirm.FROZEN_ESTIMATOR_TAG
    out["development_roster_hash"] = frozen.roster_hash
    out["thresholds_changed_for_confirmation"] = []
    out["spec_artifact"] = str(SPEC_PATH.relative_to(REPO_ROOT))
    out["source_registry"] = str(SOURCE_REGISTRY.relative_to(REPO_ROOT))
    out["excluded_from_calibration"] = list(bench.EXCLUDED_FROM_CALIBRATION)
    out["benchmark_year"] = pumd.BENCHMARK_YEAR
    out["all_cu_population_pct_error"] = all_cu.percentage_difference
    out["worst_quintile_population"] = worst_quintile.population
    out["worst_quintile_population_pct_error"] = worst_quintile.percentage_difference
    out["failures_by_node"] = confirm.failures_by_node(results)
    out["cells_by_node"] = confirm.cells_by_node(results)
    out["small_value_outcome"] = confirm.small_value_outcome(results)
    out["stratum_breakdown"] = confirm.stratum_breakdown(results)
    out["rse_corroboration"] = confirm.rse_corroboration(results)
    (OUTPUT_DIR / "confirmation_summary.json").write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"\nconfirmation_status = {out['confirmation_status']}")
    print(f"  UCCs                     {summary.roster_size}")
    print(f"  comparisons              {summary.comparison_count}")
    print(f"  cell pass fraction       {summary.pass_fraction:.4f}")
    print(f"  median abs pct error     {summary.median_abs_pct_error:.3f}")
    print(f"  p75 abs pct error        {summary.p75_abs_pct_error:.3f}")
    print(f"  p90 abs pct error        {summary.p90_abs_pct_error:.3f}")
    print(f"  max abs pct error        {summary.max_abs_pct_error:.3f}")
    print(f"  mean signed pct error    {summary.mean_signed_pct_error:+.3f}")
    print(f"  All-CU population error  {all_cu.percentage_difference:+.3f}")
    print(
        f"  worst quintile pop error {worst_quintile.percentage_difference:+.3f} "
        f"({worst_quintile.population})"
    )
    print(f"  failed criteria          {list(summary.failed_criteria)}")
    return 0


def _result_row(result) -> dict[str, object]:
    row = asdict(result)
    for key, value in list(row.items()):
        if value is None:
            row[key] = ""
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    freeze_parser = sub.add_parser("freeze", help="write the confirmation spec")
    freeze_parser.add_argument("--stub-dir", default=str(STUB_DIR))

    run_parser = sub.add_parser("run", help="run the frozen confirmation")
    run_parser.add_argument("--stub-dir", default=str(STUB_DIR))
    run_parser.add_argument("--pumd-dir", default=None)
    run_parser.add_argument("--allow-uncommitted-spec", action="store_true")

    args = parser.parse_args()
    stub_dir = Path(args.stub_dir).expanduser()
    if args.command == "freeze":
        return freeze(stub_dir)
    return run(stub_dir, args.pumd_dir, args.allow_uncommitted_spec)


if __name__ == "__main__":
    raise SystemExit(main())
