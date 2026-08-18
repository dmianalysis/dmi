#!/usr/bin/env python3
"""Build the canonical state manifest and the UCC x population ledger.

Detailed Inflation Substrate v0.1, tasks C1 and C2.

RESEARCH ONLY. Reads committed research registries and committed research
artifacts. Writes under ``registry/research/`` and
``data/research/detailed_inflation/canonical_substrate_2024/``. It does not
touch ``dmi_calculator``, the Baseline, Slack-Plus, any release workflow, any
production manifest, or the deployment output tree.

It computes no weight, no share, no denominator, no price and no inflation
rate, and it reconciles nothing. C2 records where each source amount currently
sits; comparing those amounts against anything is a later task, and doing it
here would let a convenient total decide a disposition.

Usage::

    python3 scripts/build_canonical_substrate_2024.py
    python3 scripts/build_canonical_substrate_2024.py --check

``--check`` rebuilds every artifact in memory and compares it byte for byte
against what is on disk, without writing. It exits non-zero on any difference.
That is the determinism gate: these artifacts carry no timestamp, so a diff
means an input moved, and it should be read as a signal rather than as noise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dmi_research.detailed_inflation import canonical_ledger as ledger  # noqa: E402
from dmi_research.detailed_inflation import canonical_state as cstate  # noqa: E402


def _rendered() -> dict[Path, str]:
    """Every artifact, rendered to the exact bytes that would be written.

    Rendering and writing go through the same code so that ``--check`` cannot
    pass while a real build would differ.
    """
    rows = ledger.build_ledger()
    return {
        cstate.MANIFEST_PATH: cstate.render_manifest(),
        ledger.SCHEMA_PATH: ledger.render_schema(),
        ledger.LEDGER_PATH: ledger.render_ledger(rows),
        ledger.LEDGER_SUMMARY_PATH: ledger.render_summary(rows),
    }


def _report(rows) -> None:
    rules = ledger.load_inputs().rules
    print("governing registry versions (C1)")
    for family in sorted(cstate.REGISTRY_FAMILIES):
        version = cstate.governing_version(family)
        print(f"  {family:24}{version.artifact_id:32}{version.relative_path}")

    print("\nrule lineage (C1), rules with successors")
    by_id = {node.rule_id: node for node in rules.lineage}
    for node in rules.lineage:
        if not node.successor_rule_ids:
            continue
        print(f"  {node.rule_id:48}{node.state.value}")
        for successor in node.successor_rule_ids:
            print(f"    -> {successor:46}{by_id[successor].state.value}")

    print("\nrule states (C1)")
    states: dict[str, int] = {}
    for node in rules.lineage:
        states[node.state.value] = states.get(node.state.value, 0) + 1
    for key, count in sorted(states.items()):
        print(f"  {key:20}{count:4}")

    print("\nledger (C2)")
    summary = ledger.summarise(rows)
    print(f"  rows{summary['row_count']:34}")
    print(f"  distinct UCCs{summary['distinct_uccs']:25}")
    for title, key in (
        ("source class", "rows_by_source_class"),
        ("source amount status", "rows_by_source_amount_status"),
        ("Track-A disposition", "rows_by_disposition"),
        ("normalization state", "rows_by_normalization_state"),
    ):
        print(f"\n  rows by {title}")
        for name, count in summary[key].items():
            print(f"    {name:34}{count:6}")

    print("\n  null is not zero: UCC 910106")
    for row in rows:
        if row.ucc == "910106":
            amount = (
                "" if row.source_amount_millions is None
                else f"{row.source_amount_millions:,.3f}"
            )
            print(
                f"    {row.population:8}{amount:>14}  "
                f"{row.source_amount_status.value:14}"
                f"{row.track_a_disposition.value}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory and fail on any difference from disk",
    )
    args = parser.parse_args()

    rendered = _rendered()

    if args.check:
        differing = []
        for path, content in sorted(rendered.items()):
            if not path.exists():
                differing.append((path, "missing"))
            elif path.read_text(encoding="utf-8") != content:
                differing.append((path, "differs"))
        for path, why in differing:
            print(f"CHANGED {path.relative_to(REPO_ROOT)}: {why}", file=sys.stderr)
        if differing:
            print(
                "\nThese artifacts are deterministic and carry no timestamp, "
                "so a difference means an input moved.",
                file=sys.stderr,
            )
            return 1
        print(f"unchanged: {len(rendered)} artifacts")
        return 0

    _report(ledger.build_ledger())

    for path, content in sorted(rendered.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    print("\nwrote")
    for path in sorted(rendered):
        print(f"  {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
