# DMI API Documentation

**Version**: v0.1.12
**Last Updated**: August 2026

---

## Overview

The Distributional Misery Index (DMI) is published as a set of static
JSON, CSV, and Parquet files at [dmianalysis.org](https://dmianalysis.org).
There is no live REST API — the data is served as static assets that can
be read by any HTTP client.

**Highlights**:

- No authentication required, no rate limits.
- Stable JSON Schema contracts (see `schemas/`).
- Updated monthly via GitHub Actions
  (`.github/workflows/monthly_dmi.yml`).
- Two operational specifications per release: **Baseline** and
  **Slack-Plus**. The previously advertised Core specification was
  withdrawn in v0.1.12 (see
  [`docs/repair/CORE_WITHDRAWAL.md`](repair/CORE_WITHDRAWAL.md)).

---

## Data Access

### Live site (canonical)

```bash
# Aggregate manifest of all published releases
curl https://dmianalysis.org/data/outputs/releases.json

# Current release only
curl https://dmianalysis.org/data/outputs/latest.json

# Specifications manifest
curl https://dmianalysis.org/data/outputs/specifications.json

# Per-release baseline
curl https://dmianalysis.org/data/outputs/dmi_release_2026-07.json

# Per-release Slack-Plus companion (when advertised)
curl https://dmianalysis.org/data/outputs/dmi_release_2026-07_slack_plus.json

# Baseline CSV / Parquet
curl https://dmianalysis.org/data/outputs/dmi-2026-07-baseline.csv
curl https://dmianalysis.org/data/outputs/dmi-2026-07-baseline.parquet

# Slack-Plus CSV / Parquet
curl https://dmianalysis.org/data/outputs/dmi-2026-07-slack_plus.csv
curl https://dmianalysis.org/data/outputs/dmi-2026-07-slack_plus.parquet

# Health endpoint
curl https://dmianalysis.org/health.json
```

### From the git repository

```bash
git clone https://github.com/dmianalysis/dmi.git
cd dmi/data/outputs
```

### Web dashboard

Interactive dashboard: <https://dmianalysis.org/dashboard.html>
(`/dashboard/` 301-redirects to the canonical URL.)

---

## Manifest Contracts

### `releases.json` (schema `releases.schema.json` 3.0.0)

Lists every published release in reverse-chronological order.

```json
{
  "schema_version": "3.0.0",
  "generated_at": "2026-08-15T00:00:00Z",
  "current_release_id": "2026-07",
  "releases": [
    {
      "release_id": "2026-07",
      "data_through_label": "July 2026",
      "published_at": "2026-08-15",
      "status": "current",
      "methodology_version": "v0.1.12",
      "summary": "...",
      "spec_urls": {
        "baseline": {
          "csv": "/data/outputs/dmi-2026-07-baseline.csv",
          "parquet": "/data/outputs/dmi-2026-07-baseline.parquet",
          "release_note": "/data/outputs/releases/2026-07.html"
        },
        "slack_plus": {
          "csv": "/data/outputs/dmi-2026-07-slack_plus.csv",
          "parquet": "/data/outputs/dmi-2026-07-slack_plus.parquet"
        }
      },
      "metrics": {
        "dmi_median": 7.52,
        "dmi_stress": 7.55,
        "income_pressure_spread": 0.18,
        "income_pressure_tilt": -0.17,
        "most_pressured_group": "Q4",
        "least_pressured_group": "Q1",
        "unemployment": 4.1
      }
    }
  ]
}
```

Historical baseline-only releases (2025-12..2026-02) advertise only the
`baseline` key inside `spec_urls`; they never carry a `slack_plus` key.
**No release entry ever carries a `core` key** under schema 3.0.0.

### `latest.json`

Same shape as `releases.json` but contains only the single current
release.

### `specifications.json` (schema `specifications.schema.json` 0.3.0)

Lists the two operational specifications published under v0.1.12.

```json
{
  "schema_version": "0.3.0",
  "reference_period": "2026-07",
  "specifications": [
    { "spec_id": "baseline",   "label": "Baseline (U-3, headline CPI)", ... },
    { "spec_id": "slack_plus", "label": "Slack-Plus (U-6, headline CPI)", ... }
  ]
}
```

There is no `core` `spec_id` in v0.1.12.

### Per-release JSON (schema `dmi_output.schema.json`)

**Baseline** — `dmi_release_YYYY-MM.json`:

```json
{
  "reference_period": "2026-07",
  "specification": "BASELINE",
  "description": "DMI using U-3 unemployment and headline CPI",
  "parameters": { "alpha": 0.5, "scale_factor": 2.0, "weights_year": 2023 },
  "dmi_by_group": [
    { "group_id": "Q1", "dmi": 7.35, "inflation": 2.65, "slack": 4.1 }
  ],
  "summary_metrics": {
    "dmi_median": 7.52,
    "dmi_stress": 7.55,
    "income_pressure_spread": 0.18,
    "income_pressure_tilt": -0.17,
    "most_pressured_group": "Q4",
    "least_pressured_group": "Q1"
  },
  "inflation_contributions": [ ... ],
  "metadata": { "computed_at": "2026-08-15T00:00:00Z", "num_groups": 5 }
}
```

**Slack-Plus** — `dmi_release_YYYY-MM_slack_plus.json`: same shape, with
`specification: "SLACK_PLUS"` and U-6 in the `slack` field for every
group.

---

## Field Reference

### `dmi_by_group[]`

| Field       | Type   | Required | Description                                    |
|-------------|--------|----------|------------------------------------------------|
| `group_id`  | string | Yes      | Income quintile (`Q1`..`Q5`)                   |
| `dmi`       | number | Yes      | DMI value for the group                        |
| `inflation` | number | Yes      | Group-weighted 12-month inflation (%)          |
| `slack`     | number | Yes      | National unemployment rate (%): U-3 for
                                     Baseline, U-6 for Slack-Plus     |

### `summary_metrics`

| Field                     | Type   | Description                                                 |
|---------------------------|--------|-------------------------------------------------------------|
| `dmi_median`              | number | Median DMI across the five income fifths                    |
| `dmi_stress`              | number | Highest DMI across the five income fifths                   |
| `income_pressure_spread`  | number | `max(DMI) − min(DMI)`; always ≥ 0                            |
| `income_pressure_tilt`    | number | `DMI(Q1) − DMI(Q5)`; signed (positive ⇒ bottom fifth heavier) |
| `most_pressured_group`    | string | `group_id` with the highest DMI                             |
| `least_pressured_group`   | string | `group_id` with the lowest DMI                              |

### `inflation_contributions[]`

| Field                | Type   | Description                                            |
|----------------------|--------|--------------------------------------------------------|
| `group_id`           | string | Income quintile                                        |
| `category_id`        | string | CPI category (e.g., `CPI_FOOD_BEVERAGES`)              |
| `category_inflation` | number | Category 12-month inflation (%)                        |
| `weight`             | number | Expenditure weight for this group / category           |
| `contribution`       | number | Percentage-point contribution to group inflation       |

---

## Usage Examples

### Python

```python
import requests

# Latest release manifest
manifest = requests.get(
    "https://dmianalysis.org/data/outputs/latest.json"
).json()
current = manifest["releases"][0]
print(current["release_id"], current["metrics"]["dmi_median"])

# Fetch the per-release baseline JSON
period = current["release_id"]
release = requests.get(
    f"https://dmianalysis.org/data/outputs/dmi_release_{period}.json"
).json()
for row in release["dmi_by_group"]:
    print(row["group_id"], row["dmi"])
```

### R

```r
library(jsonlite)

manifest <- fromJSON("https://dmianalysis.org/data/outputs/latest.json",
                     simplifyVector = FALSE)
current  <- manifest$releases[[1]]
period   <- current$release_id
release  <- fromJSON(
  sprintf("https://dmianalysis.org/data/outputs/dmi_release_%s.json", period),
  simplifyVector = FALSE
)
```

### JavaScript

```javascript
const manifest = await fetch(
  "https://dmianalysis.org/data/outputs/latest.json"
).then(r => r.json());
const current = manifest.releases[0];
console.log(current.release_id, current.metrics.dmi_median);
```

### jq

```bash
curl -s https://dmianalysis.org/data/outputs/latest.json | \
  jq '.releases[0].metrics'
```

---

## Update Frequency

- **Monthly releases** — published shortly after BLS CPI and CPS data
  become available for a given reference month.
- **Automated** — GitHub Actions
  (`.github/workflows/monthly_dmi.yml`) runs the computation, opens a
  PR with the outputs, and (on merge) triggers the deploy workflows.
- **Breaking changes** — reflected in `releases.schema.json` /
  `specifications.schema.json` major versions.

---

## File Naming

| Pattern                                       | Description                     |
|-----------------------------------------------|---------------------------------|
| `dmi_release_YYYY-MM.json`                    | Baseline release JSON           |
| `dmi_release_YYYY-MM_slack_plus.json`         | Slack-Plus companion JSON       |
| `dmi-YYYY-MM-baseline.{csv,parquet}`          | Baseline tabular exports        |
| `dmi-YYYY-MM-slack_plus.{csv,parquet}`        | Slack-Plus tabular exports      |
| `releases/YYYY-MM.html`                       | Human-readable release note     |
| `releases.json`, `latest.json`                | Aggregate manifests             |
| `specifications.json`                         | Specification manifest          |
| `qa_report_YYYY-MM.json`                      | QA validation report (internal) |

Legacy `dmi_release_*_u6.json`, `dmi_release_*_core.json`, and
`dmi_release_*_with_ci.json` files that predate v0.1.12 are **not** part
of the current published contract.

---

## Terms of Use

**Open data.** Free for research, policy analysis, journalism, and
education.

**Attribution.** Please cite:

> Williams, T.C. (2026). *Distributional Misery Index: Measuring Economic
> Pressure Across Income Groups.* v0.1.12.
> <https://github.com/dmianalysis/dmi>

**Issues.** Report bugs or request features at
<https://github.com/dmianalysis/dmi/issues>.

---

## Support & Contact

- **GitHub Issues**: <https://github.com/dmianalysis/dmi/issues>
- **Methodology**: [DMI Methodology Note](DMI_Methodology_Note.md)
- **Alternative specifications**:
  [Alternative_Specifications.md](Alternative_Specifications.md)
- **Core withdrawal**: [`docs/repair/CORE_WITHDRAWAL.md`](repair/CORE_WITHDRAWAL.md)
