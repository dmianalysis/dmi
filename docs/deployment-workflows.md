# DMI Deployment Workflows

This project uses **two separate deployment workflows** because they update different parts of the site and should remain operationally distinct.

## 1) `monthly_dmi.yml`
**Purpose:** compute and publish the monthly DMI release data.

### What it does
- computes the monthly **Baseline**, **Slack-Plus**, and **Core** specifications
- runs QA validation on all specifications
- updates:
  - `data/outputs/`
  - `data/outputs/published/`
  - `web/health.json`
  - release manifests (`latest.json`, `releases.json`, `specifications.json`)
- deploys the updated data and dashboard assets to iFastNet
- creates the monthly release PR

### What it should not do
- update WordPress plugin code
- overwrite WordPress root `.htaccess`
- deploy raw or staging files unless explicitly intended

### When to use it
- monthly scheduled release
- manual rerun of a monthly release
- regeneration of DMI output files for a specific reference period

---

## 2) `deploy_wp_plugins.yml`
**Purpose:** deploy custom WordPress plugin code changes.

### What it does
- deploys only the custom plugin folders stored in the repo under:
  - `web/wp-plugins/dmi-latest-info/`
  - `web/wp-plugins/dmi-release-data/`
- syncs those folders to the live WordPress plugin directory:
  - `wp-content/plugins/dmi-latest-info/`
  - `wp-content/plugins/dmi-release-data/`
- updates plugin PHP/code on the live WordPress site
- does **not** touch DMI monthly data outputs

### What it should not do
- recompute DMI releases
- deploy `data/outputs/`
- deploy dashboard/release files unless they are part of plugin logic
- touch themes, uploads, or third-party plugins

### When to use it
- after changing WordPress plugin code
- after updating shortcode/rendering logic
- after fixing the release/data page presentation

---

## Why they are separate
The monthly DMI release pipeline and the WordPress plugin deployment pipeline solve different problems:

- **`monthly_dmi.yml`** = data production + publication
- **`deploy_wp_plugins.yml`** = WordPress presentation layer updates

Keeping them separate reduces risk:
- a monthly data refresh should not overwrite plugin code unnecessarily
- a plugin change should not trigger a full DMI recomputation
- debugging is easier because failures are isolated to either **data** or **presentation**

---

## Operational guidance

### If the numbers are wrong or missing
Start with:
- `monthly_dmi.yml`

Check:
- Baseline / Slack-Plus / Core outputs
- QA reports
- `latest.json`
- `health.json`

### If the WordPress page layout, links, or shortcode output is wrong
Start with:
- `deploy_wp_plugins.yml`

Check:
- `dmi-latest-info`
- `dmi-release-data`

### If the site shows stale data but raw files are current
Usually this points to:
- page/plugin cache issues
- WordPress rendering issues
- browser cache issues

Start by verifying:
- `health.json`
- `latest.json`
- direct release files

Then determine whether the problem is in:
- the **data deploy** (`monthly_dmi.yml`)
- or the **plugin rendering layer** (`deploy_wp_plugins.yml`)

---

## Source-of-truth principle
- **GitHub repo** is the source of truth for:
  - DMI pipeline code
  - dashboard/release generation code
  - WordPress plugin code
- **iFastNet** is the deployment target, not the editing environment

Avoid making manual production edits on the server unless absolutely necessary.

---

## Current custom plugins

### Repo source
- `web/wp-plugins/dmi-latest-info/`
- `web/wp-plugins/dmi-release-data/`

### Server destination
- `wp-content/plugins/dmi-latest-info/`
- `wp-content/plugins/dmi-release-data/`

These should be updated through `deploy_wp_plugins.yml`, not by manual wp-admin editor changes.

---

## Rule of thumb
- **Changed data logic?** Run or inspect `monthly_dmi.yml`
- **Changed WordPress rendering logic?** Run `deploy_wp_plugins.yml`

---

## Troubleshooting

### 1) Monthly release ran, but the site still shows the previous month
Check in this order:
1. `health.json`
2. `latest.json`
3. direct release files such as:
   - `dmi_release_YYYY-MM.json` (baseline)
   - `dmi_release_YYYY-MM_slack_plus.json` (Slack-Plus companion)

If the raw files are current but the page is stale, the issue is usually:
- WordPress page caching
- plugin rendering logic
- browser cache

### 2) Baseline updates, but Slack-Plus is missing
Start with:
- `monthly_dmi.yml`

Check:
- whether the Slack-Plus compute step ran
- whether the expected file was written:
  - `dmi_release_YYYY-MM_slack_plus.json`
- whether the corresponding QA report exists

> Note (v0.1.12): a "Core" companion was previously advertised but has
> been withdrawn — see `docs/repair/CORE_WITHDRAWAL.md`. No
> `dmi_release_*_core.json` file is written by the current pipeline, and
> the workflows include a guard that fails deployment if such a URL
> appears in `releases.json`.

### 3) Slack-Plus fails for a new month
Likely cause:
- stale staged U-6 data

Check whether the staged file contains the requested reference period. If not, refresh/fetch U-6 before computing Slack-Plus.

### 4) WordPress menu links or slugs break after deploy
Most likely cause:
- root `.htaccess` was overwritten

The DMI deploy should **not** overwrite the WordPress root `.htaccess`. Let WordPress own the root rewrite rules.

### 5) Data page still shows old single-release links
Most likely cause:
- WordPress plugin still renders the old `urls` structure instead of spec-aware links

Update the release plugin to support:
- `spec_urls.baseline`
- `spec_urls.slack_plus`
- `spec_urls.core`

### 6) Weights vintage warning appears
This is expected if the approved weights year lags the current reference year.

Check:
- active weights file
- weights year recorded in metadata
- whether the approved weights vintage should be refreshed

### 7) Plugin code changed, but the live site did not
Start with:
- `deploy_wp_plugins.yml`

Check:
- whether the workflow ran
- whether the plugin folders were actually synced
- whether the plugin version/header was updated
- whether WordPress or browser caching is masking the change

---

## Suggested repository placement
A good home for this note is:

`docs/deployment-workflows.md`

That keeps it close to the code and easy to update.
