# DMI Release Calendar

**Version**: 0.1.12
**Purpose**: Document data release schedule and publication timeline

---

##  BLS Data Release Schedule

### CPI-U (Consumer Price Index - Inflation)

**Publisher**: U.S. Bureau of Labor Statistics  
**Frequency**: Monthly  
**Release Date**: ~13th of each month (±2 days)  
**Covers**: Previous month  
**Example**: November CPI released December 11, 2024

**Official Schedule**: https://www.bls.gov/schedule/news_release/cpi.htm

**Typical Pattern**:
- January CPI: Released mid-February
- February CPI: Released mid-March
- ... and so on

**Holiday Adjustments**: Releases may shift if 13th falls on weekend/holiday

---

### CPS (Current Population Survey - Unemployment)

**Publisher**: U.S. Bureau of Labor Statistics  
**Frequency**: Monthly  
**Release Date**: First Friday of each month  
**Covers**: Previous month  
**Example**: November unemployment released December 6, 2024

**Official Schedule**: https://www.bls.gov/schedule/news_release/empsit.htm

**Typical Pattern**:
- First Friday after month-end
- Occasionally delayed by federal holidays

---

## DMI Publication Timeline

### Target SLA

**Best Effort**: Within **7 days** of CPI release

**Rationale**:
- CPI typically releases after unemployment (13th vs 1st Friday)
- CPI is the constraining data source
- 7 days allows for:
  - Data verification (1-2 days)
  - QA checks (1 day)
  - Deployment preparation (1 day)
  - Buffer for issues (2-3 days)

---

### Monthly Workflow (Automated)

The monthly release runs unattended via the [`monthly_dmi.yml`](../.github/workflows/monthly_dmi.yml) GitHub Action.

**Day 0**: BLS Publishes CPI (~13th of month)

**Day 2 (15th, 10:17 UTC)**: Scheduled run of `monthly_dmi.yml`
- Cron: `17 10 15 * *` (workflow_dispatch also available with explicit period)
- Default mode is **dry-run**; publishing requires an explicit `dry_run=false` on manual dispatch (§6)
- Fetches latest CPI + slack data from the BLS API
- Computes DMI for the two operational specifications: baseline and slack-plus.
  Core is withdrawn in v0.1.12 — no `*_core.*` artifact is produced
  (see [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md)).
- Builds `specifications.json`, updates the Baseline-only `dmi_timeseries.json`
- Runs QA validation (`qa_report_<period>_*.json`); fails the job on QA error
- Sanity-checks `releases.json`/`latest.json` metrics against the raw baseline release
- Refreshes `web/health.json` (endpoints allow-list; retired keys are stripped, §8)
- Assembles the deploy tree via `scripts.prepare_deployment --verify` (§5)
- Rsyncs the deploy bundle to iFastNet (`/home/agiraces/dmianalysis/`) **only when
  `dry_run=false`**; otherwise the workflow stops at the verify step
- Opens an automated PR (`release/<period>`) for **manual review and merge**
  (auto-merge was removed in §6; scheduled cron runs never deploy without an
  operator explicitly opting in)

**Post-run human review** (required)
- Inspect the opened PR for anomalies before merging
- After merge, confirm `https://dmianalysis.org/health.json` reflects the new period
- Spot-check the dashboard cards

**Out-of-cycle changes** are handled by dedicated workflows so they don't require a full recompute:
- `deploy_web_dashboard.yml` — `web/dashboard.html`, `web/dashboard/.htaccess`, `web/health.json`
- `deploy_wp_plugins.yml` — `web/wp-plugins/**`

---

### Historical Performance

Recent releases (most recent 6, sourced from `data/outputs/releases.json`).
CPI release dates are approximate (BLS publishes ~10th–13th of each month);
see https://www.bls.gov/schedule/news_release/cpi.htm for the official schedule.

| Period | CPI Release (approx.) | DMI Published | Days Elapsed |
|--------|------------------------|----------------|--------------|
| 2025-12 | Jan 14, 2026  | Jan 16, 2026 | 2 days |
| 2026-01 | Feb 13, 2026  | Feb 15, 2026 | 2 days |
| 2026-02 | Mar 12, 2026  | Mar 22, 2026 | 10 days |
| 2026-03 | Apr 10, 2026  | Apr 20, 2026 | 10 days |
| 2026-04 | May 13, 2026  | May 16, 2026 | 3 days |
| 2026-05 | Jun 11, 2026  | Jun 16, 2026 | 5 days |

**Target**: Maintain <7 day average

---

### Known Delay Scenarios

**BLS Delays**:
- Federal government shutdowns
- Natural disasters affecting data collection
- Major holidays (Christmas week, Thanksgiving)
- Technical issues with BLS systems

**Our Delays**:
- Data quality issues requiring investigation
- Methodology updates requiring documentation
- Infrastructure issues
- Weekend timing (may push to Monday)

**Communication**: 
- Monitor https://www.bls.gov/bls/news-release/schedule.htm
- If CPI delayed, DMI inherits delay
- If DMI delayed independently, update health.json status

---

## Projected Release Dates

### 2026 Remaining

| Month | Est. CPI Release | Target DMI | Notes |
|-------|------------------|------------|-------|
| Jun 2026 | Jul 14, 2026 | Jul 21, 2026 | |
| Jul 2026 | Aug 12, 2026 | Aug 19, 2026 | |
| Aug 2026 | Sep 11, 2026 | Sep 18, 2026 | |
| Sep 2026 | Oct 14, 2026 | Oct 21, 2026 | Columbus Day week |
| Oct 2026 | Nov 12, 2026 | Nov 19, 2026 | |
| Nov 2026 | Dec 10, 2026 | Dec 17, 2026 | |
| Dec 2026 | Jan 13, 2027 | Jan 20, 2027 | |

### 2027 Outlook

| Month | Est. CPI Release | Target DMI | Notes |
|-------|------------------|------------|-------|
| Jan 2027 | Feb 11, 2027 | Feb 18, 2027 | |
| Feb 2027 | Mar 11, 2027 | Mar 18, 2027 | |
| Mar 2027 | Apr 13, 2027 | Apr 20, 2027 | |

**Note**: Dates are estimates based on historical BLS patterns (CPI releases ~10th–13th, Target DMI = CPI + 7 days). Check the official BLS schedule for confirmed dates: https://www.bls.gov/schedule/news_release/cpi.htm

---

## Monitoring Data Availability

### How to Check if New Data is Available

**Method 1 - BLS Website**:
- Visit https://www.bls.gov/cpi/
- Look for "Latest Numbers" section
- Check period date

**Method 2 - BLS API**:
```bash
curl "https://api.bls.gov/publicAPI/v2/timeseries/data/CUUR0000SA0?latest=true"
# Check response for latest period
```

**Method 3 - Our Health Endpoint**:
```bash
curl https://dmianalysis.org/health.json | jq '.latest_period'

# If result < current month-1, data is fresh
# If result = current month-2 or older, data is stale
```

---

## Automation Status

### Current: Automated Monthly (shipped)

Implemented in [`monthly_dmi.yml`](../.github/workflows/monthly_dmi.yml).

- **Trigger**: cron `17 10 15 * *` (15th of each month at 10:17 UTC) + `workflow_dispatch`
- **Default mode**: dry-run (§6); `dry_run=false` must be set explicitly on manual
  dispatch to actually publish. Scheduled cron runs never deploy without an operator
  explicitly opting in.
- **Pipeline**: fetch BLS data → compute baseline + slack-plus → build manifests →
  QA validate → sanity-check → `scripts.prepare_deployment --verify` → rsync deploy
  to iFastNet (only when not dry-run) → open release PR **for manual review**
- **Gating**: QA failures and metrics-mismatch sanity checks fail the job before deploy
- **Human effort**: PR review + merge for every release (auto-merge removed in §6)

### Future Enhancements

- **Anomaly detection**: flag releases whose DMI moves more than _N_ σ from the trailing window
- **Notifications**: Slack/email on success and on QA failure (currently visible only in GitHub Actions UI)
- **Rollback automation**: one-click revert of the last release PR + redeploy of the prior period
- **Weights vintage alerting**: surface the existing `WEIGHTS_YEAR` drift warning into the release PR body

**Manual review** of the merged release PR is recommended but not required; the workflow already gates on QA + sanity checks.

---

## Data Staleness Indicators

###  Dashboard Warning (Implemented in v0.1.10)

If `latest_period` > 45 days old:
- Freshness banner shows ⚠️ "Delayed"  
- Color changes to warning yellow
- Indicates attention needed

### Health Endpoint Status

```json
{
  "status": "healthy",     // or "stale" if >45 days
  "latest_period": "2024-11",
  "days_since_update": 35
}
```

Future enhancement: Add computed `days_since_update` field

---

## Communication Plan

### Routine Updates
- No announcement needed (just update health.json)
- Users check dashboard as needed

### Delayed Updates
- If >14 days since CPI: Update health status to "delayed"
- Add note explaining reason (BLS delay, data quality issue, etc.)

### Methodology Changes
- Announce via CHANGELOG
- Email users (if mailing list exists)
- Post on GitHub Releases
- Update methodology note

---

## Support & Contacts

**BLS CPI Questions**: cpi_info@bls.gov  
**BLS CPS Questions**: lausinfo@bls.gov  
**DMI Issues**: https://github.com/dmianalysis/dmi/issues

---

**Last Updated**: June 16, 2026
**For**: DMI v0.1.12
