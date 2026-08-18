#!/usr/bin/env python3
"""Compatibility wrapper for release-note regeneration (Round-4 §4).

What this used to do, and why it was removed
--------------------------------------------
This entry point used to *reconstruct publication history*. When a period
had a Baseline release but no Slack-Plus companion on disk, it called
``compute_dmi_for_period`` to synthesize the missing companion in memory
from staged CPI/slack inputs and curated weights, then rendered a release
note describing that synthesized series as though it had been published.

Three things are wrong with that:

1. **It invents history.** A release note is a public statement about what
   was published for a period. A period with no Slack-Plus artifact did
   not publish Slack-Plus, and no amount of recomputation makes it true
   after the fact.

2. **The inputs are not the original inputs.** Staged CPI and slack files
   are refreshed over time and curated weights are revised. Recomputing a
   2026-01 companion today uses today's staging data, so the "recovered"
   numbers need not match what that period would have produced — while
   being presented as that period's figures.

3. **It failed silently upward.** The reconstruction printed a single
   ``!`` line and continued, so a note describing a series that was never
   computed looked exactly like a note describing one that was.

What it does now
----------------
It delegates to ``scripts.regenerate_release_notes``, the safe
existing-artifact-only implementation, which:

- loads the raw Baseline release for the period;
- loads the raw Slack-Plus release **if and only if** it exists on disk;
- renders a note describing only the specifications actually present;
- never calls a DMI computation function.

A period with no Slack-Plus artifact renders a single-row specification
table. That is the honest description of a Baseline-only period.

If you genuinely need a companion release for a historical period, the
answer is to compute and publish it through the normal release path
(``scripts.compute_dmi_release`` then ``scripts.finalize_release``),
where it passes the QA and cross-specification gates like any other
release — not to have a note generator conjure one.
"""

from __future__ import annotations

import sys
from typing import Optional

from scripts.regenerate_release_notes import main as regenerate_main

#: Kept so `python -m scripts.backfill_release_notes --help` still works
#: for anyone with the old command in a runbook.
DEPRECATION_NOTICE = (
    "NOTE: scripts.backfill_release_notes is a compatibility wrapper.\n"
    "      It now delegates to scripts.regenerate_release_notes, which\n"
    "      consumes existing published artifacts ONLY and never\n"
    "      reconstructs a missing release. Prefer calling that directly:\n"
    "        python -m scripts.regenerate_release_notes [--periods YYYY-MM ...]\n"
)


def main(argv: Optional[list[str]] = None) -> int:
    print(DEPRECATION_NOTICE, file=sys.stderr)
    return regenerate_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
