# Update to `docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`

> **TEMPLATE — apply only after a real Phase-2 run.**
> Append the section below to the evidence record, replacing every
> `<…>` placeholder with an observed value. Until a run has happened,
> that document must continue to say remote withdrawal is *not
> authorized and not executed*.

## Section to append

```markdown
## 4. Remote-origin withdrawal — EXECUTED <YYYY-MM-DD>

Distinguish four states; only the ones marked complete below have
happened:

1. **Repository cleanup** — complete. Core is absent from the tracked
   tree, manifests, health file and deployment package.
2. **Production deployment** — complete. The corrected artifacts were
   deployed from the merged commit.
3. **Remote-origin withdrawal** — executed <date>. The 21 withdrawn Core
   files were deleted from the origin filesystem.
4. **CDN-cache removal** — <not required / required / purged <date>>.

### What was deleted

21 files under `/home/agiraces/dmianalysis/data/outputs`, exactly as
enumerated by the sealed inventory:

- 6 × `dmi_release_{2024-11,2026-03..07}_core.json`
- 5 × `dmi-{2026-03..07}-core.csv`
- 5 × `dmi-{2026-03..07}-core.parquet`
- 5 × `qa_report_{2026-03..07}_core.json`

Inventory seal `3812991fa2ed52e4e3cfcc543c28c3f1769c20a3033c307abdb8085fd1887fd6`;
inventory file SHA-256
`ce1e55939c2c10c04c18cb96b2457db802241f9bdfcdf484438f5250ba84e11c`.
Full per-file record: `docs/repair/REMOTE_WITHDRAWAL_LOG_<date>.md`.

### What was not touched

`_u6` and `_with_ci` artifacts are **not** Core. They were outside this
authorization, were refused by the tool's scope rules, and remain on the
server unchanged. Baseline, Slack-Plus, manifests, release notes,
dashboard, health, timeseries and the historical archive are unaffected.

### Backup

`core-withdrawal-backup` artifact ID `<id>`, archive SHA-256 `<sha256>`,
taken and verified against the inventory before any deletion.

### Public surface

<Record observed statuses. If withdrawn URLs still returned 200 while
origin files were absent, state explicitly that this was a Cloudflare
cache condition and not a failed deletion.>
```
