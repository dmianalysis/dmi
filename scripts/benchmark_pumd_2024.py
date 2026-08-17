#!/usr/bin/env python3
"""Run the 2024 CE Interview PUMD benchmark against published LB01.

RESEARCH ONLY. This script writes under ``data/research/`` and reads only
research registries and Milestone-1/Milestone-2 artifacts. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

The PUMD microdata are not committed and are not downloaded here. Point the
script at the extracted Interview CSVs::

    export DMI_PUMD_2024_INTERVIEW_DIR=~/dev/dmi-data/pumd/2024/interview
    python3 scripts/benchmark_pumd_2024.py --stub ~/dev/dmi-data/pumd/2024/docs/stubs/stubs/CE-HG-Inter-2024.txt

Order matters and is enforced: the roster is written before any comparison is
computed, and the acceptance rule is loaded from a frozen artifact rather than
chosen here.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd, pumd_benchmark as bench  # noqa: E402

MILESTONE_1 = REPO_ROOT / "data/research/detailed_inflation/audit_2024"
MILESTONE_2 = REPO_ROOT / "data/research/detailed_inflation/milestone_2"
OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/pumd_benchmark_2024"
SPEC_PATH = REPO_ROOT / "registry/research/pumd_lb01_benchmark_spec_v0_1.json"
STUB_DIR = Path.home() / "dev/dmi-data/pumd/2024/docs/stubs/stubs"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pumd-dir", default=None, help="extracted Interview CSVs")
    parser.add_argument(
        "--stub-dir",
        default=str(STUB_DIR),
        help="directory holding CE-HG-Inter-2024.txt and CE-HG-Integ-2024.txt",
    )
    parser.add_argument(
        "--roster-only",
        action="store_true",
        help="write the frozen roster and stop, without reading any microdata",
    )
    args = parser.parse_args()

    spec_payload = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    stub_dir = Path(args.stub_dir).expanduser()
    interview_stub = pumd.read_stub_file(stub_dir / "CE-HG-Inter-2024.txt")
    integrated_stub = pumd.read_stub_file(stub_dir / "CE-HG-Integ-2024.txt")
    provenance = read_csv(MILESTONE_2 / "ucc_provenance_classes_2024.csv")
    basis = read_csv(MILESTONE_1 / "active_ucc_basis.csv")
    exceptions = [row["ucc"] for row in read_csv(MILESTONE_1 / "exception_ledger.csv")]

    # -- Stage A: the roster, computed and written before any comparison ----
    roster = bench.select_roster(
        provenance, basis, exceptions, interview_stub, integrated_stub
    )
    bench.write_csv(
        OUTPUT_DIR / "benchmark_roster.csv",
        bench.ROSTER_COLUMNS,
        bench.roster_rows(roster),
    )
    digest = bench.roster_hash(roster)
    print(f"roster: {len(roster)} UCCs, hash {digest}")
    if args.roster_only:
        return 0

    spec = bench.BenchmarkSpec.from_json(SPEC_PATH)

    # -- Stage B: microdata ------------------------------------------------
    directory = pumd.locate_interview_csv_dir(args.pumd_dir)
    units = pumd.read_all_fmli(directory)
    keep = frozenset(entry.ucc for entry in roster)
    records = pumd.read_all_mtbi(directory, keep_uccs=keep)
    print(f"microdata: {len(units)} FMLI records, {len(records)} MTBI records in scope")

    # -- Stage C: population and quintile structure, reported first --------
    populations = pumd.population_estimates(units)
    targets = spec_payload["population_validation"]
    comparisons = bench.compare_populations(
        populations,
        units,
        targets["published_targets_2024_consumer_units_thousands"],
        targets["published_mean_income_before_taxes_2024"],
    )
    bench.write_csv(
        OUTPUT_DIR / "population_validation.csv",
        tuple(asdict(comparisons[0])),
        [asdict(row) for row in comparisons],
    )
    for row in comparisons:
        print(
            f"  {row.population:20s} CU {row.pumd_consumer_units_thousands:10.1f} "
            f"vs {row.published_consumer_units_thousands:8.0f} "
            f"({row.percentage_difference:+.2f}%)  income {row.income_percentage_difference:+.2f}%"
        )

    boundaries = bench.reconstruct_boundaries(units)
    bench.write_csv(
        OUTPUT_DIR / "quintile_reconstruction.csv",
        tuple(asdict(boundaries[0])),
        [asdict(row) for row in boundaries],
    )

    # -- Stage D: the expenditure benchmark --------------------------------
    results, _ = bench.run_benchmark(roster, units, records, basis, spec)
    bench.write_csv(
        OUTPUT_DIR / "benchmark_results.csv",
        tuple(asdict(results[0])),
        [_result_row(result) for result in results],
    )

    summary = bench.summarize(results, comparisons, roster, spec)
    payload = asdict(summary)
    payload["benchmark_year"] = pumd.BENCHMARK_YEAR
    payload["source_registry"] = "registry/research/pumd_2024_interview_source_v0_1.json"
    payload["spec_artifact"] = str(SPEC_PATH.relative_to(REPO_ROOT))
    payload["excluded_from_calibration"] = list(bench.EXCLUDED_FROM_CALIBRATION)
    (OUTPUT_DIR / "benchmark_summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(
        f"\nbenchmark_status = {summary.benchmark_status}\n"
        f"  median |%err| {summary.median_abs_pct_error:6.2f}  "
        f"p75 {summary.p75_abs_pct_error:6.2f}  "
        f"p90 {summary.p90_abs_pct_error:6.2f}  "
        f"max {summary.max_abs_pct_error:8.2f}\n"
        f"  mean signed %err {summary.mean_signed_pct_error:+.2f}  "
        f"pass fraction {summary.pass_fraction:.3f}"
    )
    if summary.failed_criteria:
        print(f"  failed criteria: {', '.join(summary.failed_criteria)}")
    return 0


def _result_row(result: bench.BenchmarkResult) -> dict[str, str]:
    row = asdict(result)
    for key, value in list(row.items()):
        if value is None:
            row[key] = ""
        elif isinstance(value, float):
            row[key] = f"{value:.4f}"
    return row


if __name__ == "__main__":
    raise SystemExit(main())
