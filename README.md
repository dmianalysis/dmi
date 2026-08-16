# Distributional Misery Index (DMI) v0.1.12

![Status](https://img.shields.io/badge/status-pre--1.0-yellow)
![Python](https://img.shields.io/badge/python-3.9+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Data](https://img.shields.io/badge/data-monthly-blue)
![Coverage](https://img.shields.io/badge/tests-passing-success)

**A transparent, reproducible measure of economic pressure across income
groups.**

📊 **[Live Dashboard](https://dmianalysis.org/dashboard/)** |
📖 **[Methodology](docs/DMI_Methodology_Note.md)** |
🔌 **[API Docs](docs/API.md)**

---

## What v0.1.12 is (and isn't)

v0.1.12 is a **pre-1.0 exceptional breaking public-schema release** that
brings the repository back into agreement with the concept note. It:

- Publishes two specifications only:
  - **Baseline** — U-3 unemployment, headline CPI
  - **Slack-Plus** — U-6 unemployment, headline CPI
- **Withdraws the "Core" specification** that appeared in earlier releases.
  The previously published Core outputs were derived from headline-CPI
  inputs and did not implement a bona fide core-inflation calculation.
  See [`docs/repair/CORE_WITHDRAWAL.md`](docs/repair/CORE_WITHDRAWAL.md).
- Bumps `releases.schema.json` to `3.0.0` and
  `specifications.schema.json` to `0.3.0` to reflect the Core removal.
- Publishes historical baseline-only entries (2025-12..2026-02) that
  correctly advertise only the Baseline artifact.

v0.1.12 does **not** claim:

- Bootstrap confidence intervals on published DMI values
- A validated 2011-2024 historical time series
- A Core-CPI operational specification

Any such claims in older documentation are being removed as part of the
Phase 6 repair.

---

## Overview

The DMI combines group-weighted inflation (π) with labor-market slack (S)
to reveal how economic pressure varies across income groups.

**Formula**:

```
DMI(g) = scale_factor × [α × π(g) + (1 − α) × S]
```

Defaults: `α = 0.5`, `scale_factor = 2.0`.

**Baseline vs Slack-Plus identity** (enforced by the test suite):

```
DMI_slackplus(g) − DMI_baseline(g) = U6 − U3
```

**Core Principles**:

- **Deterministic**: same inputs → identical outputs
- **Transparent**: methodology and code are public
- **Auditable**: full audit trail from raw BLS data to published manifests
- **Coherent**: presentation surfaces (dashboard, WordPress plugins,
  manifests) never disagree with the deployed schema

---

## Project Structure

```
dmi/
├── dmi_calculator/          # Pure deterministic calculator
│   └── core.py
├── dmi_pipeline/
│   └── agents/
│       └── bls_api_client.py
├── scripts/                 # Computation + manifest scripts
│   ├── compute_dmi.py               # Baseline + Slack-Plus
│   ├── backfill_releases.py         # Rebuild releases.json / latest.json
│   └── rebuild_release_manifests.py
├── web/
│   ├── dashboard.html               # Static dashboard
│   ├── health.json
│   └── wp-plugins/
│       ├── dmi-latest-info/
│       └── dmi-release-data/
├── data/
│   ├── curated/                     # CE weights + related inputs
│   └── outputs/                     # Published release JSON/CSV/Parquet
│       ├── releases.json
│       ├── latest.json
│       ├── specifications.json
│       └── releases/*.html
├── schemas/                         # JSON Schema contracts
│   ├── releases.schema.json         # 3.0.0
│   ├── dmi_output.schema.json
│   └── specifications.schema.json   # 0.3.0
├── docs/
│   ├── DMI_Methodology_Note.md
│   ├── API.md
│   ├── Alternative_Specifications.md
│   ├── DEPLOYMENT_GUIDE.md
│   ├── RELEASE_CALENDAR.md
│   └── repair/
│       ├── V0.1.12_ALIGNMENT_AUDIT.md
│       └── CORE_WITHDRAWAL.md
└── tests/
```

---

## Quick Start

### Prerequisites

- Python 3.9+
- BLS API key (register at https://data.bls.gov/registrationEngine/)

### Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/dmianalysis/dmi.git
   cd dmi
   ```

2. **Set up Python environment**:

   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment**:

   ```bash
   cp .env.example .env
   # Edit .env and add your BLS_API_KEY
   ```

4. **Run the DMI computation**:

   ```bash
   ./venv/bin/python -m scripts.compute_dmi
   ```

---

## Usage Examples

### Compute DMI (Baseline + Slack-Plus)

The `compute_dmi.py` script produces both operational specifications:

```bash
./venv/bin/python -m scripts.compute_dmi
```

Outputs written to `data/outputs/`:

- `dmi_release_YYYY-MM.json` (Baseline)
- `dmi_release_YYYY-MM_slack_plus.json` (Slack-Plus companion)
- Baseline CSV/Parquet: `dmi-YYYY-MM-baseline.{csv,parquet}`
- Slack-Plus CSV/Parquet: `dmi-YYYY-MM-slack_plus.{csv,parquet}`

### Rebuild the release manifests

After a new release computes, rebuild the aggregate manifests:

```bash
./venv/bin/python -m scripts.rebuild_release_manifests
```

This regenerates `data/outputs/releases.json` and
`data/outputs/latest.json` — both conforming to `releases.schema.json`
version 3.0.0.

### Access data programmatically

**Python**:

```python
import requests

# Latest release manifest
url = "https://dmianalysis.org/data/outputs/latest.json"
manifest = requests.get(url).json()
current = manifest["releases"][0]
print(current["release_id"], current["metrics"]["dmi_median"])
```

See [`docs/API.md`](docs/API.md) for complete documentation.

---

## Web Dashboard

### Local Preview

```bash
cd web
python3 -m http.server 8000
# Visit http://localhost:8000/dashboard.html
```

### Deployment

Deployment is automated via GitHub Actions on push to `main`:

- `.github/workflows/deploy_web_dashboard.yml` — dashboard, manifests,
  release notes
- `.github/workflows/deploy_wp_plugins.yml` — WordPress plugins
  (`dmi-latest-info`, `dmi-release-data`)

Both workflows expose a `workflow_dispatch` dry-run input for repair
validation.

---

## Data Sources

- **BLS CPI-U** — monthly category index levels (inflation)
- **BLS Consumer Expenditure Survey** — annual expenditure shares by
  income quintile (weights)
- **BLS CPS** — national unemployment (U-3 baseline, U-6 for Slack-Plus)

---

## Documentation

- **[Methodology Note](docs/DMI_Methodology_Note.md)** — technical
  reference
- **[API Documentation](docs/API.md)** — programmatic access guide
- **[Alternative Specifications](docs/Alternative_Specifications.md)** —
  Baseline vs Slack-Plus
- **[Deployment Guide](docs/DEPLOYMENT_GUIDE.md)** — release + deploy
  procedure
- **[Release Calendar](docs/RELEASE_CALENDAR.md)** — publication cadence
- **[v0.1.12 Alignment Audit](docs/repair/V0.1.12_ALIGNMENT_AUDIT.md)** —
  the repair record backing this release
- **[Core Withdrawal Notice](docs/repair/CORE_WITHDRAWAL.md)** — why Core
  was removed

---

## Contributing

This is a measurement tool under active development. Contributions should:

- Preserve deterministic calculator properties
- Follow conservative governance (no silent methodology changes)
- Include tests and documentation
- Keep manifests, schemas, and presentation surfaces in agreement

---

## Citation

**Suggested Format**:

> Williams, T.C. (2026). *Distributional Misery Index: Measuring Economic
> Pressure Across Income Groups.* v0.1.12.

**BibTeX**:

```bibtex
@techreport{williams2026dmi,
  title     = {Distributional Misery Index: Measuring Economic Pressure
               Across Income Groups},
  author    = {Williams, Thomas C.},
  year      = {2026},
  institution = {Independent Research},
  type      = {Software / Data Release},
  version   = {0.1.12},
  url       = {https://github.com/dmianalysis/dmi}
}
```

A preferred concept-note citation with DOI will be added here once the
corrected concept note has been published and the DOI resolves.

---

## License

MIT License — see [LICENSE](LICENSE) for details.

Copyright (c) 2025-2026 Thomas C. Williams.

---

## Contact

**Repository**: https://github.com/dmianalysis/dmi
**Website**: https://dmianalysis.org
**Owner**: Thomas C. Williams

---

## Acknowledgments

Data sources: U.S. Bureau of Labor Statistics (BLS).

Thanks to the open-source community for the tools that made this possible:
pandas, numpy, Chart.js, and the BLS Public Data API.
