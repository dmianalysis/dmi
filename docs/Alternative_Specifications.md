# DMI Alternative Specifications Guide

**Version**: v0.1.12
**Last Updated**: August 2026

---

## Overview

The Distributional Misery Index (DMI) v0.1.12 publishes **two** operational
specifications:

- **Baseline** — CPI-U headline inflation (all items) + **U-3** unemployment.
- **Slack-Plus** — CPI-U headline inflation (all items) + **U-6** unemployment.

Both are computed monthly by `scripts/compute_dmi.py` and published under a
single release: baseline as `dmi_release_YYYY-MM.json` /
`dmi-YYYY-MM-baseline.{csv,parquet}` and Slack-Plus as
`dmi_release_YYYY-MM_slack_plus.json` /
`dmi-YYYY-MM-slack_plus.{csv,parquet}`.

### Core specification: withdrawn

A "Core" alternative was advertised in earlier documentation. It was
withdrawn in v0.1.12 because the code that produced its outputs did not
implement a bona fide core-inflation calculation — the inputs were still
headline CPI. See
[`docs/repair/CORE_WITHDRAWAL.md`](repair/CORE_WITHDRAWAL.md) for the full
rationale and
[`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md)
for the impact on existing consumers.

No release under `releases.schema.json` 3.0.0 advertises a `spec_urls.core`.
Legacy `dmi_release_*_core.json` files are historical artifacts and are not
part of the v0.1.12 published contract.

---

## Slack-Plus (U-6 companion)

### Methodology

- **Inflation input**: same as Baseline (CPI-U headline).
- **Labor slack input**: **U-6** (`LNS13327709`) replacing U-3
  (`LNS14000000`).
- All other formula components (weights, `α = 0.5`, `scale_factor = 2.0`)
  are identical to Baseline.

U-6 includes everyone counted in U-3 plus:

- Discouraged workers (want work, stopped searching)
- Marginally attached workers (want work, available, not actively
  searching)
- Part-time for economic reasons (want full-time, involuntarily
  part-time)

### The Baseline / Slack-Plus identity

Because the only difference between the two specifications is the slack
input, and because U-3 and U-6 are national-level scalars (not
group-specific), the following identity holds **exactly** for every group
`g`:

```
DMI_slackplus(g) − DMI_baseline(g) = (1 − α) × scale_factor × (U6 − U3)
                                   = U6 − U3    (with α = 0.5, scale = 2)
```

The test suite (`tests/test_baseline_slackplus_identity.py`) enforces this
identity for every published release.

### When to use Slack-Plus

Slack-Plus is more appropriate when:

- Analyzing recessions with substantial underemployment.
- The labor market shows slack beyond traditional unemployment (e.g., COVID
  recovery).
- The reader cares about broader economic distress, not just measured
  unemployment.

Slack-Plus DMI values are **not** directly comparable to Baseline DMI
values on the same scale; use the identity above (or the difference series)
when comparing.

---

## Data availability

- **U-3** (`LNS14000000`): monthly, 1948–present.
- **U-6** (`LNS13327709`): monthly, 1994–present. Any Slack-Plus backfill
  is therefore capped at 1994.
- Historical DMI releases prior to 2026-03 are baseline-only; they do not
  advertise a `spec_urls.slack_plus` entry.

---

## Generating both specifications

`compute_dmi.py` produces both Baseline and Slack-Plus in a single run:

```bash
./venv/bin/python -m scripts.compute_dmi
```

Outputs written to `data/outputs/`:

- `dmi_release_YYYY-MM.json` (Baseline)
- `dmi_release_YYYY-MM_slack_plus.json` (Slack-Plus)
- `dmi-YYYY-MM-baseline.{csv,parquet}`
- `dmi-YYYY-MM-slack_plus.{csv,parquet}`

The aggregate manifests (`releases.json`, `latest.json`) are rebuilt with:

```bash
./venv/bin/python -m scripts.rebuild_release_manifests
```

---

## Interpretation guidance

- **Baseline** is the canonical headline series and should be used for
  general-purpose reporting, dashboards, and press releases.
- **Slack-Plus** is a companion series for sensitivity analysis; report it
  alongside Baseline when labor-market slack is unusually wide.
- The **Slack-Plus − Baseline gap** across periods is itself informative:
  a widening gap indicates rising underemployment even when U-3 is stable.

---

## Limitations

- Only two operational specifications are currently published. A validated
  core-inflation specification is not part of v0.1.12; see the withdrawal
  documents linked above.
- CE weights vintage is 2023; alternatives use the same weights as
  Baseline.
- No statistical testing of differences is bundled with the released data.

---

## References

- **U-6 definition**: BLS Labor Force Statistics, Table A-15.
- **Series IDs**:
  - U-3: `LNS14000000`
  - U-6: `LNS13327709`
  - Headline CPI: see `registry/series_catalog_v0_1.json`
- **Core withdrawal**: `docs/repair/CORE_WITHDRAWAL.md`,
  `docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`.

---

**Questions?** See [DMI Methodology Note](DMI_Methodology_Note.md) or open
an issue at https://github.com/dmianalysis/dmi/issues.
