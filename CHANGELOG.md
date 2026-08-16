# Changelog

All notable changes to the Distributional Misery Index will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.12]

**Pre-1.0 exceptional breaking public-schema release.** v0.1.12 brings the
repository back into agreement with the concept note. It withdraws the
previously advertised Core specification, bumps public schemas, and closes
several coherence gaps between manifests, workflows, and presentation
surfaces. See
[`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](docs/repair/V0.1.12_ALIGNMENT_AUDIT.md)
for the full audit and
[`docs/repair/CORE_WITHDRAWAL.md`](docs/repair/CORE_WITHDRAWAL.md) for the
Core-withdrawal rationale.

### Removed - Core specification (Breaking)
- Withdrew the "Core" (`core`) operational specification. The prior Core
  outputs were derived from headline-CPI inputs and did not implement a
  bona fide core-inflation calculation.
- `data/outputs/specifications.json` no longer contains a `core` entry.
- No `spec_urls.core` is advertised in `releases.json` or `latest.json` for
  any release — including historical entries.
- Public-presentation surfaces (dashboard, WordPress plugin
  `dmi-release-data`, release-note HTML) no longer render a Core column.

### Changed - Metrics Rename (Breaking, unchanged from prior 0.1.12 draft)
- Replaced single signed `income_pressure_gap` with two distinct metrics:
  - `income_pressure_spread` (always ≥ 0): max(DMI) − min(DMI) across
    groups; measures dispersion
  - `income_pressure_tilt` (signed): Q1 DMI − Q5 DMI; measures
    regressivity (positive ⇒ bottom fifth more pressured)
- Added `most_pressured_group` and `least_pressured_group` (group
  identifiers) to `summary_metrics`.
- Dropped legacy `urls` block in releases/latest; only `spec_urls` going
  forward.
- Summary generator: `classify_gap_direction` →
  `classify_spread_direction`; `gap_delta_mom` / `gap_direction` →
  `spread_delta_mom` / `tilt_delta_mom` / `spread_direction`.

### Changed - Schema bumps (Breaking)
- `releases.schema.json`: 2.0.0 → **3.0.0** (Core removal +
  baseline-only historical entries)
- `latest.json` embedded `schema_version`: 2.0.0 → **3.0.0**
- `specifications.schema.json`: 0.2.0 → **0.3.0** (Core entry removed)
- Bumped methodology version to v0.1.12 throughout.

### Added - Baseline + Slack-Plus identity
- Slack-Plus is now advertised as the sole operational companion to
  Baseline. The test suite enforces the identity
  `DMI_slackplus(g) − DMI_baseline(g) = U6 − U3` for every group.
- Historical baseline-only releases (2025-12..2026-02) correctly
  advertise only the Baseline artifact and never a Slack-Plus URL.

### Added - Workflow guards
- `monthly_dmi.yml`: hard-fails if `specifications.json.reference_period`
  disagrees with the requested period; hard-fails on any Core artifact in
  the deploy tree; runs full JSON-schema validation before opening a PR;
  `dry_run` input for repair validation; corrected spread assertion
  (`< 0` instead of `<= 0`); removed stale hard-coded default period.
- `deploy_web_dashboard.yml`: hard-fails on staged Core artifacts and on
  any manifest still advertising Core `spec_urls`; `dry_run` input.
- `deploy_wp_plugins.yml`: hard-fails on Core references (`'core'`,
  `_core.json`, `-core.*`) in staged plugin source; `dry_run` input.

### Added - Coherence tests
- `tests/test_specifications_manifest.py`: enforces that
  `specifications.json` is coherent with `latest.json` and has no Core
  entry.
- `tests/test_baseline_slackplus_identity.py`: enforces the
  Slack-Plus − Baseline = U6 − U3 identity.
- `tests/test_schema_validation.py`: validates every published manifest
  and every standard release JSON against its schema; asserts no Core
  `spec_urls` and no Slack-Plus advertisement for baseline-only history.

### Fixed
- `scripts/backfill_releases.py`: fixed `IndentationError` at the
  module-guard block; removed hard-coded Core `spec_url` block; gated
  Slack-Plus URLs on artifact existence; bumped emitted
  `schema_version` to 3.0.0; switched `datetime.now()` →
  `datetime.utcnow()` for consistency with the timezone suffix.
- `web/wp-plugins/dmi-release-data/dmi_release_data.php`: removed Core
  from `$labels`, `$notes`, and the render loop; plugin version bumped
  to 0.3.0.
- `web/dashboard.html`: removed the "DMI Core" narrative bullet and the
  hard-coded Core references in comments.
- WordPress `dmi-latest-info` plugin: "Most-Pressured Group" row
  previously rendered `dmi_stress` (numeric); now correctly shows
  `group_id`.
- Strict (subscript) access replaces silent `.get(key, default)`
  patterns for required metrics.

### Changed - Identity / metadata
- `LICENSE`: copyright holder corrected to `Thomas C. Williams`
  (previously `tcwilliams79`), year range `2025-2026`.
- `CITATION.cff`: abstract rewritten to remove unsupported claims
  (bootstrap confidence intervals, 2011-2024 historical time series,
  Core CPI specification, Okun 1970 citation). Only supported claims
  remain.
- `README.md`: rewritten around the current v0.1.12 state; removed
  obsolete v0.1.9 feature section and stale `tcwilliams79` URLs.

## [0.1.11] - 2025-12-17

### Added - Dashboard Polish
- Freshness banner showing data currency (latest period, publish date, staleness indicator)
- Data staleness warning (⚠️ if >45 days old)
- Top contributors panel showing top 5 inflation drivers by category
- Interactive quintile switching (Q1, Q3, Q5) for contributors
- Category label mapping for readable chart labels
- Chart.js horizontal bar charts for contribution visualization

### Changed - User Experience
- Updated dashboard version to v0.1.11
- Enhanced transparency with automatic health.json integration
- Improved interpretability with "What's driving inflation?"  insights

### Fixed
- None

---

## [0.1.10] - 2025-12-17

### Added - Production Hardening
- Health/status endpoint (`health.json`) generated during deployment
- Metadata file (`metadata.json`) for programmatic dataset discovery
- Freshness banner on dashboard showing latest period and publish date
- Data staleness indicator (⚠️ if data >45 days old)
- CITATION.cff for proper academic citation (GitHub standard)
- Formal JSON Schema for time series data (`schemas/dmi_timeseries_schema.json`)
- Generic deployment guide supporting cPanel, Plesk, DirectAdmin, Nginx, and custom hosts
- Release calendar documenting BLS data sources and publication timeline
- Platform-specific deployment notes for major hosting providers
- Enhanced smoke test checklist with common issues troubleshooting
- Rollback procedures for deployment

### Changed - Documentation
- Deployment instructions now platform-agnostic (not host-specific)
- `prepare_deployment.sh` generates health.json and metadata.json
- Enhanced deployment package with build metadata

### Fixed
- None

---

## [0.1.9] - 2025-12-17

> **Historical note (added in v0.1.12).** Several items listed here were
> subsequently withdrawn or found to be unsupported: the "Core CPI"
> alternative did not implement a bona fide core-inflation calculation
> (withdrawn in v0.1.12); the bootstrap confidence intervals were not
> carried forward into the published v0.1.12 contract; and the 2011-2024
> historical time series has not been re-validated under v0.1.12. This
> entry is preserved unchanged as the historical record of what shipped
> at v0.1.9.

### Added - Feature Complete
- Historical time series backfill (2011-2024, 835 observations)
- Interactive Chart.js time series visualization
- Historical context panel (percentile rank, vs average, trend analysis)
- Bootstrap confidence intervals (1000 iterations, ~0.12 DMI point width)
- U-6 unemployment alternative specification
- Core CPI alternative specification (excluding food/beverages)
- Comprehensive methodology note (20+ pages, academic-style, citable)
- API documentation with multi-language examples (Python, R, JavaScript)
- Alternative specifications documentation
- Deployment preparation script

### Changed - Infrastructure
- Enhanced BLS API client with retry logic, rate limiting, and structured logging
- Improved error handling in data fetching

### Fixed
- Duplicate series ID in catalog (CPI_OTHER)
- Backfill script column mapping issue
- Symlink handling in deployment

---

## [0.1.8] - 2025-12-16

### Added - Initial Release
- Basic DMI calculation (5 income quintiles)
- Monthly GitHub Actions workflow
- CE weights extraction (2023 vintage)
- CPI data fetching from BLS API
- U-3 unemployment integration
- QA validation framework
- Simple web dashboard

### Methodology
- Formula: DMI = 2.0 × (0.5 × Inflation + 0.5 × Slack)
- Weights: CE Survey 2023, Table 1203
- Inflation: 12-month CPI-U percent change
- Slack: U-3 unemployment rate (national)

---

## Change Categories

**Added**: New features, endpoints, documentation  
**Changed**: Modifications to existing functionality  
**Deprecated**: Soon-to-be removed features  
**Removed**: Deleted features  
**Fixed**: Bug fixes  
**Security**: Security vulnerability patches  
**Methodology**: Changes to DMI calculation formula or data sources (RARE - requires version note)

---

## Versioning Policy

**Patch versions (0.1.x)**: Bug fixes, documentation, non-breaking enhancements  
**Minor versions (0.x.0)**: New features, alternative specifications, significant enhancements  
**Major versions (x.0.0)**: Breaking changes, methodology changes affecting DMI values

**Methodology Changes** (special case):
- Any change to weights source, formula, or data that alters DMI values
- Requires explicit user notification in release notes
- Backward compatibility maintained (old data not recalculated)
- Example: Switching from 2023 to 2024 CE weights

---

## Links

- [GitHub Releases](https://github.com/dmianalysis/dmi/releases)
- [Methodology Note](docs/DMI_Methodology_Note.md)
- [API Documentation](docs/API.md)
