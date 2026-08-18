#!/usr/bin/env python3
"""Re-derive the shelter-UCC source observations from the pinned 2024 PUMD.

Detailed Inflation Substrate v0.1, shelter task, Phase C1.

RESEARCH ONLY. This script writes under ``data/research/`` and reads only the
research registries and the pinned PUMD archive. It does not touch
``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

Usage::

    python3 scripts/verify_shelter_source_2024.py \
        --pumd-dir /path/to/intrvw24/extracted \
        --dictionary /path/to/ce-pumd-interview-diary-dictionary.xlsx

It computes no expenditure. Its exit status is the C1 gate: non-zero if any
preserved claim failed to reproduce, so the milestone cannot proceed past a
source that has moved without that being noticed.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import pumd  # noqa: E402
from dmi_research.detailed_inflation import shelter_source as source  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "data/research/detailed_inflation/shelter_2024"
OBSERVATION_PATH = OUTPUT_DIR / "shelter_source_observation.json"
DEFAULT_DICTIONARY = (
    Path.home() / "dev/dmi-data/pumd/2024/docs/ce-pumd-interview-diary-dictionary.xlsx"
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pumd-dir", default=None)
    parser.add_argument("--dictionary", default=str(DEFAULT_DICTIONARY))
    args = parser.parse_args()

    directory = pumd.locate_interview_csv_dir(args.pumd_dir)
    print(f"pinned archive members: {directory}")
    digests = source.verify_archive_members(directory)
    for name, digest in sorted(digests.items()):
        print(f"  {name}  {digest}  pinned-match")

    observations = source.read_shelter_source(directory)
    checks = source.compare_with_prior_observation(observations)
    verdict = source.source_verdict(checks)

    print("\nrecord counts")
    print(
        f"  {'UCC':<9}{'all ref yrs':>12}{'prior claim':>13}{'REF_YR=2024':>13}"
        f"{'NEWIDs 2024':>13}  PUBFLAG"
    )
    for ucc in source.OBSERVED_UCCS:
        o = observations[ucc]
        claimed = source.PRIOR_MANUAL_RECORD_COUNTS.get(ucc)
        claimed_text = "-" if claimed is None else str(claimed)
        print(
            f"  {ucc:<9}{o.records_all_reference_years:>12}{claimed_text:>13}"
            f"{o.records_in_benchmark_year:>13}"
            f"{o.distinct_newids_in_benchmark_year:>13}  {o.pubflag_tally}"
        )

    print("\npreserved claims")
    for check in checks:
        mark = "ok  " if check.reproduced else "FAIL"
        print(
            f"  {mark} {check.claim:<13}{check.ucc}  claimed={check.claimed!r} "
            f"measured={check.measured!r}"
        )

    corroborated = source.partition_is_corroborated(observations)
    print(f"\nPUBFLAG splits on the cx.item partition: {corroborated}")

    dictionary_payload: dict[str, object] | None = None
    dictionary_path = Path(args.dictionary)
    try:
        reading = source.read_pubflag_dictionary(dictionary_path)
    except pumd.PumdDataUnavailable as error:
        print(f"\nPUBFLAG dictionary NOT read: {error}")
    else:
        dictionary_payload = {
            "path": str(dictionary_path),
            "workbook_sha256": reading.workbook_sha256,
            "workbook_sha256_matches_registry": (
                reading.workbook_sha256_matches_registry
            ),
            "sheet": reading.sheet,
            "rows_read": list(reading.rows_read),
            "variable_description": reading.variable_description,
            "code_meanings": dict(reading.code_meanings),
            "agrees_with_expectation": reading.agrees_with_expectation,
        }
        print("\nMTBI PUBFLAG, from the BLS PUMD data dictionary")
        print(f"  workbook sha256 matches registry: "
              f"{reading.workbook_sha256_matches_registry}")
        print(f"  description: {reading.variable_description!r}")
        for code, meaning in sorted(reading.code_meanings.items()):
            print(f"  {code} = {meaning!r}")

    print(f"\nsource_reproduction_status = {verdict}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "phase": "C1",
        "status": "RESEARCH_ONLY",
        "source_reproduction_status": verdict,
        "benchmark_year": pumd.BENCHMARK_YEAR,
        "archive_members_verified": digests,
        "source_registry": "registry/research/pumd_2024_interview_source_v0_1.json",
        "prior_observation_citation": (
            "registry/research/ucc_provenance_classes_v0_1.json :: "
            "pumd_observations.CE_2024_INTERVIEW_MTBI_SHELTER_RENTAL_EQUIVALENCE"
        ),
        "prior_manual_counting_basis": source.PRIOR_MANUAL_COUNTING_BASIS,
        "observations": {
            ucc: {
                **asdict(observation),
                "records_by_reference_year": {
                    str(year): count
                    for year, count in observation.records_by_reference_year.items()
                },
            }
            for ucc, observation in observations.items()
        },
        "preserved_claim_checks": [asdict(check) for check in checks],
        "pubflag_partition_corroborated": corroborated,
        "pubflag_dictionary": dictionary_payload,
    }
    OBSERVATION_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OBSERVATION_PATH.relative_to(REPO_ROOT)}")

    return 0 if verdict == source.REPRODUCED else 1


if __name__ == "__main__":
    raise SystemExit(main())
