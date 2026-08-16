# Pre-v0.1.12 Quarantine

Round-3 §8. These files predate the v0.1.12 published contract and are
retained here for historical / auditability reasons only. They are NOT
part of the current release surface. They MUST NOT be:

- staged by `scripts/prepare_deployment.py` (they live outside
  `data/outputs/`, which is the only tree the builder walks for
  advertised URLs);
- referenced by any manifest under `data/outputs/`
  (`releases.json`, `latest.json`, `specifications.json`);
- advertised under `web/health.json` `endpoints`
  (the `latest_u6` and `latest_with_ci` keys are in
  `RETIRED_ENDPOINT_KEYS`, see `scripts/health_endpoints.py`);
- uploaded to the live site.

## Files

| File | Predates | Reason for quarantine |
|---|---|---|
| `dmi_release_2024-11_u6.json` | v0.1.12 two-spec contract | Legacy U-6 naming; superseded by `dmi_release_YYYY-MM_slack_plus.json` from 2026-03 onwards. Never rebuilt under the current schema; kept out of `data/outputs/` so no tool mistakes it for a current Slack-Plus release. |
| `dmi_release_2024-11_with_ci.json` | v0.1.12 published contract | Legacy confidence-interval companion produced by `scripts/compute_dmi_with_ci.py`. The CI companion was never part of the v0.1.12 published contract; the `latest_with_ci` health endpoint has been retired (§7). |

## Relationship to the Core withdrawal

These files are NOT `_core.json` and are NOT part of the withdrawn
Core spec. The Core withdrawal is documented separately in
`docs/repair/CORE_WITHDRAWAL.md` and covered by the two-phase
withdrawal tool `scripts/withdraw_remote_artifacts.py` (inventory
then execute --confirm). The pre-v0.1.12 quarantine covers only
the U-6 / with_ci legacy naming.

## Do not delete

Leaving these files here (rather than deleting them) preserves the
historical record and lets a reviewer diff current outputs against a
prior methodology run. The quarantine location is intentionally
outside `data/outputs/` so no automated tool can accidentally treat
them as a current release.
