# DMI Deployment Workflows

This project uses **two separate deployment workflows** because they update different parts of the site and should remain operationally distinct.

## 1) `monthly_dmi.yml`
**Purpose:** compute and publish the monthly DMI release data.

### What it does
- computes the monthly **Baseline** and **Slack-Plus** specifications.
  The previously advertised **Core** specification was withdrawn in v0.1.12
  (see [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md));
  the workflow no longer computes it, and a guard rejects any release
  advertising a `*_core.*` URL.
- runs QA validation on both specifications
- updates:
  - `data/outputs/`
  - `data/outputs/published/`
  - `web/health.json` (endpoint keys are re-sanitised against an allow-list, §8)
  - release manifests (`latest.json`, `releases.json`, `specifications.json`)
- deploys the updated data and dashboard assets to iFastNet **only when
  `dry_run=false` is set explicitly** (§6; the default is dry-run)
- creates the monthly release PR **for manual review** (auto-merge was
  removed in §6)

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
- Baseline / Slack-Plus outputs (Core is withdrawn — no `*_core.*`
  artifact is expected; if one appears, the deploy guard will reject it)
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

## Missing-release watchdog (`monthly_release_watchdog.yml`)
**Purpose:** notice when a month's release preparation did not happen.

The release-gate reminder (`release_gate_reminder.yml`) follows up release
PRs that exist. It cannot see a run that failed before opening one, which
is how the November 15, 2026 failure went unnoticed. The watchdog covers
that gap. It only monitors: it never reruns a workflow, merges or closes a
PR, changes repository content or deploys.

### What it does
- runs daily at 16:37 UTC from the 17th to the 28th, two days after
  `monthly_dmi.yml` runs on the 15th;
- works out the expected reference period from the date alone: the
  previous calendar month in UTC (a check on December 17, 2026 expects
  `2026-11`, one on January 17, 2027 expects `2026-12`);
- reads, through the GitHub API, the runs of
  `.github/workflows/monthly_dmi.yml` this month (with the failed job and
  step of any failed run), the release PRs for the period,
  `data/outputs/releases.json` on `main` and
  `registry/unavailable_periods.json` on `main`. For a run that failed at
  the CPI fetch in an approved period it also reads the failed job's log;
- runs on the runner image's own `python3` with the standard library
  only. It does not use `actions/setup-python` or the DMI dependency lock,
  because a failure there is one of the things it reports;
- classifies the result, writes it to the run summary and, when a human
  needs to act, opens or updates one GitHub Issue for the period.

A release PR counts only when its title is `DMI Release: YYYY-MM (not
deployed)`, its branch is `release/YYYY-MM` (with the timestamp suffix),
it targets `main` and it carries the labels `release` and `not-deployed`.
A PR closed without merging is not a release.

### Classifications

| Classification | Meaning | Issue |
|---|---|---|
| `NOT_YET_DUE` | Checked before 10:17 UTC on the 17th | No |
| `RUN_IN_PROGRESS` | The scheduled run is still running | No |
| `RELEASE_PR_PENDING_REVIEW` | A release PR for the period is open. The reminder handles review follow-up | No |
| `RELEASE_MERGED` | The period is in `releases.json` on `main`. Merging does not deploy; this does not say the site was deployed | No |
| `APPROVED_SOURCE_UNAVAILABLE` | The period has a valid registry entry naming the missing base month, the run got through every earlier step and failed at "Fetch CPI data (live only)", and the job log shows the fetch completed and stopped only because CPI has no observations for the 12-month base month (see below) | No |
| `SCHEDULED_RUN_MISSING` | No scheduled run started this cycle. An approved data gap does not excuse this | Yes |
| `SCHEDULED_RUN_FAILED` | The scheduled run failed or was cancelled and no release PR exists. Includes a failure the approved exception does not explain, such as one at "Set up Python" | Yes |
| `SCHEDULED_RUN_STALLED` | The scheduled run has been queued or running for over 24 hours | Yes |
| `RUN_SUCCEEDED_NO_RELEASE_PR` | The run succeeded but no open or merged release PR exists | Yes |
| `MERGED_BUT_NOT_IN_MANIFEST` | A release PR was merged but `releases.json` on `main` lacks the period | Yes |
| `SCHEDULED_TRIGGER_MISSING` | A release PR exists (for example from a manual recovery), but no scheduled run started, so the schedule is not shown to work | Yes |

What counts as positive evidence for an approved exception. A failure at
the right step is not enough. The failed job's log must show all of:

- the fetch ran for the expected period, both BLS requests completed and
  validation ran (`[3/3] Validating required observations...`);
- no traceback;
- exactly one `ERROR: BLS data cannot support DMI reference period
  YYYY-MM; nothing was staged.`, whose only problem is `CPI has no
  observations for <base month> (12-month CPI base month).`;
- `Process completed with exit code 1.`

The registry entry must also name that base month (for October 2026,
"October 2025"). A BLS authentication error, network failure, timeout or
any other exception raises in the BLS client and leaves a traceback, so
it is reported. So is any additional missing observation, a log that
cannot be read, and a log in any other shape. Only this one kind of
exception is recognised; any other kind of approved gap still alerts
until a person looks at it.

The log is fetched with the job token (`actions: read`). GitHub answers
with a redirect to a signed storage URL, which is fetched without the
token.

Manual recovery: a manual `prepare_release`/`live` run that opens a valid
release PR resolves a failed scheduled run. A manual `validate`/`fixture`
run never counts as release preparation; the watchdog reads the run's
step record to tell them apart.

If any GitHub request fails, the run fails with exit code 2 and says so
in the run summary. An error is never read as "no runs" or "no PRs".

### Issues
- Title `[DMI Watchdog] YYYY-MM — release preparation requires attention`,
  with the hidden marker `<!-- dmi-watchdog:YYYY-MM -->` in the body,
  assigned to `tcwilliams79`.
- Before creating one, the watchdog searches open **and closed** Issues
  for the marker, so each period gets at most one Issue.
- Each Issue and update records its state in a hidden marker. Daily
  checks that find the same state post nothing. A changed state adds one
  comment.
- The watchdog never closes or reopens an Issue. When a closed Issue's
  period needs attention again, it comments on it.

Example Issue:

```text
[DMI Watchdog] 2026-10 — release preparation requires attention

Expected reference period: 2026-10
Classification: SCHEDULED_RUN_FAILED
Problem: run 43739957699 ended failure at job 'prepare-dmi', step 'Set up
Python'. 2026-10 is an approved unavailable period, but the record does not
show the run reaching 'Fetch CPI data (live only)' and failing there, so the
approved exception does not explain this failure
Checked at: 2026-11-17 23:59 UTC

Evidence
- Scheduled runs this cycle (.github/workflows/monthly_dmi.yml):
  - run 43739957699 (schedule, 2026-11-15 17:14 UTC, branch main): failure;
    failed at job 'prepare-dmi', step 'Set up Python' — https://github.com/dmianalysis/dmi/actions/runs/43739957699
- Manual runs this cycle: none
- Release PRs for 2026-10: none
- data/outputs/releases.json on main: 2026-10 absent
- registry/unavailable_periods.json: 2026-10 listed (valid), approved in dmianalysis/dmi#40

Suggested action
Open the run, read the failed step's log and fix the cause in a reviewed PR.
Then prepare the release manually: run Monthly DMI Preparation with
mode=prepare_release, data_source=live and reference_period=2026-10. ...
```

### Running it by hand
Manual runs are dry runs unless **notify** is ticked. A dry run prints the
period, the run and PR evidence, the manifest and registry status, the
classification and the Issue action it would take, and writes nothing.

- **Actions → DMI Missing-Release Watchdog → Run workflow**, leaving
  **notify** unticked. Set **as_of** (for example `2026-11-17`) to replay a
  past check; a replayed date is always a dry run.
- Locally, with a token that can read the repository:

  ```bash
  GH_TOKEN="$(gh auth token)" python3 -m scripts.monthly_release_watchdog \
    --repo dmianalysis/dmi --as-of 2026-12-17 --dry-run
  ```

`--notify` creates or updates the Issue and is refused together with
`--as-of`.

### Limitations
- A replayed date filters runs and PRs to that date, but reads the
  manifest and registry as they are on `main` now.
- Recognising an approved exception depends on the wording that
  `scripts.test_bls_api` prints. The tests generate their logs from that
  script, so rewording it fails them. GitHub keeps job logs for a limited
  time (90 days by default); after that the evidence cannot be read and
  the failure is reported.
- A manual run's inputs are not in the GitHub API, so its reference
  period is known only through the release PR it opened.
- The watchdog needs the runner image to provide `python3` (3.9 or
  newer). It shares the runner image with the monthly workflow but not
  its Python setup. If the image itself breaks, both can fail; the
  watchdog's own run then shows as failed and opens no Issue.
- GitHub can start scheduled runs late (the November 15, 2026 run started
  at 17:14 UTC) or drop them under load. The two-day grace period absorbs
  delays; a dropped run is reported as `SCHEDULED_RUN_MISSING`.
- GitHub disables scheduled workflows in a public repository, such as
  this one, after 60 days without activity. That disables the watchdog
  too.

---

## Runtime requirements
- Every workflow that runs DMI code uses **Python 3.12** on
  `ubuntu-latest`. PR CI also tests Python 3.13.
- Dependencies come from the hash-pinned lock for that interpreter in
  `requirements-lock/`. See [requirements-lock/README.md](../requirements-lock/README.md)
  for the support policy and the refresh procedure.
- Deployment uses SSH with pinned host keys and rsync, so it needs a Linux
  runner. It does not need a particular Ubuntu release.
- The web host serves static files and needs no Python.

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

`spec_urls.core` must **not** appear on any v0.1.12 release — Core was
withdrawn (see [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](known-issues/CORE_OUTPUT_WITHDRAWAL.md)).
A plugin that still renders `spec_urls.core` will silently point at a
404 (or, worse, a stale historical file). Remove any `core` branch from
the plugin at the same time as adding `slack_plus`.

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

### 8) A workflow fails at "Set up Python" or "Verify Python runtime"
This means the runner could not provide the declared interpreter. No DMI
code ran and nothing was published.

Do not pin an older Ubuntu image to get past it. Check:
- whether the version in `PYTHON_VERSION` is still supported by
  `actions/setup-python` on `ubuntu-latest`
- whether a matching lock exists at `requirements-lock/python<version>.txt`

If the interpreter must change, follow "Adding or retiring a Python
version" in [requirements-lock/README.md](../requirements-lock/README.md).
A scheduled release missed this way must be prepared again by manual
dispatch of `monthly_dmi.yml` with `mode=prepare_release`,
`data_source=live` and the missed `reference_period`.

### 9) "Fetch CPI data" fails with "BLS data cannot support DMI reference period"
The BLS response lacks an observation the release needs: a CPI category
in the reference month, a CPI category in the same month one year
earlier (the base of 12-month inflation), or U-3 in the reference month.
The step stops before writing anything to `data/staging/`, so no
computation runs and nothing is published.

If BLS has not yet released the month, rerun once it has. If BLS never
published it, the release cannot be computed. Do not estimate,
interpolate or backfill the missing observation. For example, October
2025 CPI was not published because of the 2025 federal government
shutdown, so the October 2026 release, whose base month it is, cannot be
computed.

The next release after a missing month is finalized only if the month
has a reviewed entry in `registry/unavailable_periods.json`: a
substantive reason, https sources, and the approving pull request as
`owner/repo#N`. Without one, "Finalize release" fails, names every
undocumented month, and publishes nothing. Add an entry by hand in a
reviewed pull request, and only when the official data do not exist.
A failed monthly run is not a reason to add one: rerun it instead.

Both the fetch and the compute steps pick their staging files from the
reference period through `scripts/reference_period.py`, never from the
date the workflow runs. A rerun of any period uses the same files.

---

## Suggested repository placement
A good home for this note is:

`docs/deployment-workflows.md`

That keeps it close to the code and easy to update.
