# specifications.json mixed-value provenance investigation (Phase 2d)

**Date:** 2026-08-15
**Branch:** repair/v0.1.12-concept-note-alignment
**File under investigation:** `data/outputs/specifications.json`
**Related audit finding:** V0.1.12_ALIGNMENT_AUDIT.md — specifications.json inconsistency

## 1. Symptom

At the start of the repair (HEAD = 2df37b8), `data/outputs/specifications.json` had internally
inconsistent contents:

| Field | Value in file | What it should have been |
| --- | --- | --- |
| `reference_period` | `2026-06` | `2026-07` (matches `release_json` paths and metric values below) |
| `generated_at` | `2026-08-10T05:08:42.852531Z` | `2026-08-15T…Z` (matches actual regeneration) |
| `specifications[*].release_json` | `/data/outputs/dmi_release_2026-07*.json` | matches 2026-07 (consistent with metrics) |
| `specifications[0].metrics.dmi_median` (baseline) | `7.516957462855907` | matches 2026-07 baseline release |
| `specifications[0].metrics.slack` (baseline) | `4.2` | should be `4.1` (U-3 for 2026-07); `4.2` is the U-3 value for **2026-06** |
| `specifications[1].metrics.slack` (slack_plus) | `7.9` | matches 2026-07 slack_plus release |
| `specifications[2].metrics.slack` (core) | `4.2` | should be `4.1` (Core, when it existed, used U-3); `4.2` again is a June value |

In short: the metadata (`reference_period`, `generated_at`) and the Baseline/Core `slack` numbers
were stale (June 2026), while the numeric summary metrics and `release_json` paths were current
(July 2026). This is not a possible output of any single run of `build_specifications_manifest.py`.

## 2. Root cause: merge commit 45e2682

`data/outputs/specifications.json` was last actually *regenerated* in commit `d641cec`
("Add DMI release for 2026-07") which produced a fully-2026-07 manifest, but **without**
the `slack` field (the manifest builder on `main` at that time didn't emit `slack`).

The stale mixed state was produced by the merge commit **45e2682** ("Merge branch 'main' into
agent/deferred-release-notes"), which combined:

- **Parent 1**  `33f04d6` (agent/deferred-release-notes tip):
  - `reference_period: 2026-06`
  - `generated_at: 2026-08-10T05:08:42.852531Z`
  - `release_json` paths → `2026-06`
  - metric numbers → 2026-06 values
  - `metrics.slack` field **present** (Baseline `4.2`, Slack+ `7.9`, Core `4.2`) — those are the
    correct U-3 / U-6 values for **June 2026**
- **Parent 2**  `a5e940f` (main after d641cec):
  - `reference_period: 2026-07`
  - `generated_at: 2026-08-15T10:42:15.857524Z`
  - `release_json` paths → `2026-07`
  - metric numbers → 2026-07 values
  - `metrics.slack` field **absent**

The merge resolution:

- Kept Parent 1's `reference_period`, `generated_at`, and `metrics.slack` values
- Kept Parent 2's `release_json` paths and numeric summary metrics

Evidence (excerpt of `git show 45e2682 -- data/outputs/specifications.json`):

```
-       "release_json": "/data/outputs/dmi_release_2026-06.json",
+       "release_json": "/data/outputs/dmi_release_2026-07.json",
        "metrics": {
-         "dmi_median": 7.793742264030375,
+         "dmi_median": 7.516957462855907,
          …
          "least_pressured_group": "Q1",
 +        "slack": 4.2,
          "slack_measure": "u3"
```

The single-`+` lines in a `diff --cc` (combined diff) indicate hunks introduced by the merge
resolution itself (present in the merge result but not in either parent as-is at that
position). The `slack: 4.2` (Baseline) and `slack: 4.2` (Core) lines are stale June values
grafted onto a July manifest.

The lines outside the diff range (top of file, containing `reference_period` and
`generated_at`) are identical in the merge result and Parent 1, so combined diff omits them —
but they are stale (June) relative to the metric block below (July).

## 3. Why the regression escaped review

- No test asserts internal coherence between `reference_period`, `release_json` paths, and
  `metrics.slack` values.
- No test asserts that each spec's `metrics.slack` equals the `dmi_by_group[0].slack` in the
  release file it points at.
- The manifest was not regenerated after the merge (a fresh
  `python scripts/build_specifications_manifest.py 2026-07` from July inputs would have
  produced a consistent manifest, because current `build_specifications_manifest.py:49-61`
  reads `slack` from `release["dmi_by_group"][0]["slack"]` in the referenced release).

## 4. Disposition

- **Phase 2d (this commit):** add regression test `tests/test_specifications_manifest_coherence.py`
  that enforces four invariants against any specifications.json in the repo (currently the
  single file at `data/outputs/specifications.json`, once Core has been removed and the file
  regenerated).
- **Phase 2c / Phase 4:** the actual `specifications.json` is not repaired in place. It will
  be **regenerated from scratch** in Phase 4 (after schema-3.0.0 realignment and Core removal
  from the writer), at which point the coherence test will pass. The stale file is a leftover
  artifact and any in-place edit here would be discarded by the Phase 4 regeneration.
- **No history rewrite.** The merge commit is preserved; only the working-tree file is
  regenerated later.

## 5. Files and commits referenced

- File: `data/outputs/specifications.json` (currently on HEAD, still contains stale mixed state
  and a Core entry — will be regenerated in Phase 4)
- Writer: `scripts/build_specifications_manifest.py:49-61` (`metrics_from_release`; correctly
  derives `slack` from the referenced release when re-run)
- Commit that regenerated correctly in July: `d641cec` "Add DMI release for 2026-07"
- Commit that introduced the mixed state via merge resolution: `45e2682` "Merge branch 'main'
  into agent/deferred-release-notes" (parents `33f04d6` and `a5e940f`)
