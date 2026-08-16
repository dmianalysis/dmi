# Core Specification — Withdrawal Rationale (v0.1.12)

**Status:** Withdrawn. No valid operational Core DMI series currently exists.
**Repair branch:** `repair/v0.1.12-concept-note-alignment`
**Round-3 §11.** Companion evidence:
[`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md).

---

## 1. What was withdrawn

Every DMI artifact labeled *Core* — for every reference period present in
the repository as of the v0.1.12 repair — has been removed from the active
release surface. This covers:

- **JSON release files (6):**
  `dmi_release_{2024-11,2026-03,2026-04,2026-05,2026-06,2026-07}_core.json`
- **Tabular exports (5 CSV + 5 Parquet):**
  `dmi-{2026-03..2026-07}-core.{csv,parquet}`
- **QA reports (5):**
  `qa_report_{2026-03..2026-07}_core.json`
- **Manifest references:** any `spec_urls.core` block in
  `data/outputs/releases.json` and `data/outputs/latest.json`; any
  `specifications[].spec_id == "core"` entry in
  `data/outputs/specifications.json`.
- **Health endpoint:** `latest_core` is not on the allow-list in
  `scripts/health_endpoints.py`. (`latest_with_ci` — a distinct, retired
  U-6/with-CI legacy — is handled separately by §7 / §8.)

The withdrawal is expressed in the current tree by absence: the files are
not staged into `deploy/`, not referenced by any manifest under
`data/outputs/`, and not advertised by `web/health.json`. Git history
retains the withdrawn files verbatim; no destructive history rewrite has
been performed.

---

## 2. Why it was withdrawn

The audit found that files stamped as Core carried metadata claiming the
inflation input excluded food and beverages
(`inflation_measure = "CORE_CPI"`, `excluded_categories =
["CPI_FOOD_BEVERAGES"]`), but the numerical values in those files are
byte-identical to the Baseline (headline-CPI) outputs for the same period.
A genuine Core computation could not produce byte-identity with Baseline,
because food-and-beverages weights vary across income quintiles.

The mechanism is documented in
[`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
§2: the pipeline computed a Baseline release and then relabeled it with
Core-flavored metadata. `build_core_weights(...)` was defined but never
invoked on the release path. No repository code was found that constructs
a food-and-beverages-excluded inflation series or a Core-specific
quintile-weight matrix.

Concept note v0.4.6 lists Core as an **intended future companion
specification** that is not implemented or validated for v0.1.12.
Withdrawing the current Core artifacts is the honest description of that
state: the files were mislabeled Baseline outputs, not a defective Core
computation to be repaired in place.

---

## 3. What is (and is not) affected

**Not affected — remain the two operational specifications:**

- **Baseline** — headline CPI-U + U-3 —
  `dmi_release_YYYY-MM.json`, `dmi-YYYY-MM-baseline.{csv,parquet}`.
- **Slack-Plus** — headline CPI-U + U-6 (from 2026-03 onward) —
  `dmi_release_YYYY-MM_slack_plus.json`,
  `dmi-YYYY-MM-slack_plus.{csv,parquet}`.

Both are computed by `scripts/compute_dmi.py` under the v0.1.12 two-spec
contract and published under `releases.schema.json` v3.0.0.

**Adjacent, distinct legacy artifacts (Round-3 §8):**

The 2024-11 files `dmi_release_2024-11_u6.json` and
`dmi_release_2024-11_with_ci.json` are **not** Core outputs. They are
pre-v0.1.12 U-6 and confidence-interval legacy files quarantined under
`data/quarantine/pre_v0.1.12/`. See that directory's README for
disposition; the `latest_u6` and `latest_with_ci` endpoints are retired in
`scripts/health_endpoints.py` (`RETIRED_ENDPOINT_KEYS`).

**No live-server change is performed by this repair.** Remote artifacts on
iFastNet (`/home/agiraces/dmianalysis/data/outputs/dmi_release_*_core.json`
and friends) are enumerated in
[`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
§3.3. Withdrawal is performed via the two-phase Python tool
`scripts/withdraw_remote_artifacts.py` (`inventory` then `execute
--confirm`), under explicit authorization only. See
[`docs/repair/REMOTE_WITHDRAWAL.md`](REMOTE_WITHDRAWAL.md) for the
operator runbook.

---

## 4. Reversal / dispute path

If a validated Core computation is added in a future repair (v0.1.13 or
later):

1. The new computation is implemented behind a distinct `spec_id`
   (e.g., `core`, if reintroduced under the same identifier) with a
   working `build_core_weights(...)` on the release path and a food-and-
   beverages-excluded CPI-U input.
2. Its outputs are published under a **new** `specifications.json` entry
   at schema-version 3.0.0 or later and advertised under
   `spec_urls.<new_spec_id>` in `releases.json` / `latest.json`.
3. A new health endpoint (`latest_<new_spec_id>`) is added to the
   allow-list in `scripts/health_endpoints.py`.
4. This record and
   [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
   remain in the repository. The release notes for the release in which
   Core is (re)introduced link back to them so consumers can distinguish
   the new validated series from the withdrawn artifacts.

The withdrawn files are not renamed, patched, or "re-explained" in place.
They are absent from the operational surface and preserved in Git history
for auditability.

---

## 5. Related repair records

- [`docs/known-issues/CORE_OUTPUT_WITHDRAWAL.md`](../known-issues/CORE_OUTPUT_WITHDRAWAL.md)
  — deep evidence: byte-level identity of Core vs Baseline numerics, the
  mislabeling code path, per-period file enumeration, remote-surface
  enumeration.
- [`docs/repair/V0.1.12_ALIGNMENT_AUDIT.md`](V0.1.12_ALIGNMENT_AUDIT.md)
  — Phase-1 audit that identified the Core discrepancy.
- [`docs/repair/REMOTE_WITHDRAWAL.md`](REMOTE_WITHDRAWAL.md) — operator
  runbook for the two-phase remote withdrawal tool.
- [`data/quarantine/pre_v0.1.12/README.md`](../../data/quarantine/pre_v0.1.12/README.md)
  — pre-v0.1.12 U-6 / with-CI quarantine (distinct from Core).
- [`scripts/withdraw_remote_artifacts.py`](../../scripts/withdraw_remote_artifacts.py)
  — two-phase inventory/execute tool with SHA-256 verification gate.
