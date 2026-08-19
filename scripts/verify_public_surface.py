#!/usr/bin/env python3
"""Public HTTPS verification after a Core withdrawal.

Separates two things that look identical from the outside: a Core URL
still returning 200 because the origin file survived, and one returning
200 because a CDN is serving a cached copy of a file that is already
gone.

The distinction matters operationally. The first is a failed deletion and
needs the origin fixed. The second is a cache condition — the withdrawal
worked, and the remaining step is a purge, which is a separate authorized
action. Treating the second as the first leads to restoring files that
were correctly removed.

So this checks with cache-busting query strings and reports the condition
rather than deciding what to do about it. It never purges anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

BASE = "https://dmianalysis.org"

#: The public contract this withdrawal must not disturb.
EXPECTED_RELEASE_ID = "2026-07"
EXPECTED_SPECS = frozenset({"baseline", "slack_plus"})

#: Endpoints that must remain healthy.
OPERATIONAL = [
    "/dashboard.html",
    "/health.json",
    "/data/outputs/releases.json",
    "/data/outputs/latest.json",
    "/data/outputs/specifications.json",
    "/data/outputs/dmi_release_2026-07.json",
    "/data/outputs/dmi_release_2026-07_slack_plus.json",
    "/data/outputs/dmi-2026-07-baseline.csv",
    "/data/outputs/dmi-2026-07-slack_plus.parquet",
    "/data/outputs/releases/2026-07.html",
    "/data/outputs/published/dmi_timeseries.json",
]


def _status(url: str, bust: bool = True) -> tuple[int, dict]:
    """Return (status, headers). Cache-busted by default."""
    target = f"{url}?cb={int(time.time()*1000)}" if bust else url
    request = urllib.request.Request(
        target,
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {})
    except Exception:
        return 0, {}


#: HTTP statuses that positively demonstrate withdrawal.
WITHDRAWN_STATUSES = frozenset({404, 410})


def classify_withdrawn(status: int, origin_absent: bool) -> tuple[str, bool]:
    """Classify a withdrawn URL's response. Returns ``(verdict, ok)``.

    An earlier version treated "not 200" as success, which fails open:
    a network error (recorded as 0), a 403 from a misconfigured host, or
    a 500 all looked like a successful withdrawal. None of them
    demonstrate that anything was removed — they demonstrate only that
    this particular request did not return the file.

    Three outcomes, and only the first is a pass:

    - **404/410** — the resource is gone. Withdrawal demonstrated.
    - **200 with the origin file confirmed absent** — the origin was
      deleted and a CDN is still serving a cached copy. Not a failure of
      this operation; a purge is a separate authorized action.
    - **anything else** — inconclusive. That includes 200 when origin
      absence was NOT confirmed, which would mean the deletion did not
      happen.
    """
    if status in WITHDRAWN_STATUSES:
        return ("withdrawn", True)
    if status == 200 and origin_absent:
        return ("cached_after_origin_deletion", True)
    if status == 200:
        return ("still_served_origin_not_confirmed_absent", False)
    if status == 0:
        return ("inconclusive_network_error", False)
    return (f"inconclusive_http_{status}", False)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True)
    parser.add_argument("--operational-report", required=True)
    parser.add_argument(
        "--origin-report",
        help=(
            "Path to the origin post-check JSON. A 200 can only be read "
            "as a cache condition when origin absence was independently "
            "confirmed; without this the verifier will not make that "
            "inference."
        ),
    )
    args = parser.parse_args(argv)

    # Did the origin check confirm every withdrawn file is gone?
    origin_absent = False
    origin_source = "not supplied"
    if args.origin_report and Path(args.origin_report).is_file():
        try:
            origin = json.loads(Path(args.origin_report).read_text())
            origin_absent = bool(origin.get("all_withdrawn_absent"))
            origin_source = args.origin_report
        except Exception as exc:  # pragma: no cover - defensive
            origin_source = f"unreadable ({exc})"

    repo_root = Path(__file__).resolve().parent.parent
    from scripts.verify_withdrawal_inventory import INVENTORY_PATH

    inventory = json.loads((repo_root / INVENTORY_PATH).read_text())
    outputs = inventory["remote_outputs"]
    withdrawn_urls = [
        "/data/outputs/" + record["path"][len(outputs) + 1:]
        for record in inventory["files"]
    ]

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    # --- withdrawn URLs -------------------------------------------------
    withdrawn_rows = []
    cached = []
    inconclusive = []
    for url in sorted(withdrawn_urls):
        status, headers = _status(BASE + url)
        verdict, ok = classify_withdrawn(status, origin_absent)
        row = {
            "url": url,
            "status": status,
            "verdict": verdict,
            "acceptable": ok,
            "cf_cache_status": headers.get("CF-Cache-Status"),
            "age": headers.get("Age"),
            "server": headers.get("Server"),
        }
        withdrawn_rows.append(row)
        if verdict == "cached_after_origin_deletion":
            cached.append(row)
        if not ok:
            inconclusive.append(row)
        print(f"  {status:>3}  {verdict:<44s} {url}"
              + (f"   CF-Cache-Status={row['cf_cache_status']}"
                 if row["cf_cache_status"] else ""))

    # --- operational surface --------------------------------------------
    print()
    operational_rows = []
    degraded = []
    for url in OPERATIONAL:
        status, _headers = _status(BASE + url)
        row = {"url": url, "status": status}
        operational_rows.append(row)
        if status != 200:
            degraded.append(row)
        print(f"  {status}  {url}")

    # --- contract validation --------------------------------------------
    contract: dict = {}
    contract_problems: list[str] = []
    try:
        with urllib.request.urlopen(
            f"{BASE}/data/outputs/latest.json?cb={int(time.time()*1000)}",
            timeout=30,
        ) as response:
            latest = json.loads(response.read())
        release_id = latest.get("current_release_id")
        contract["current_release_id"] = release_id
        contract["current_is_2026_07"] = release_id == EXPECTED_RELEASE_ID
        if release_id != EXPECTED_RELEASE_ID:
            contract_problems.append(
                f"current_release_id is {release_id!r}, expected "
                f"{EXPECTED_RELEASE_ID!r}"
            )

        specs = set()
        for release in latest.get("releases", []):
            specs |= set((release.get("spec_urls") or {}).keys())
        contract["spec_urls_present"] = sorted(specs)
        contract["specs_exactly_operational"] = specs == EXPECTED_SPECS
        if specs != EXPECTED_SPECS:
            contract_problems.append(
                f"advertised specifications are {sorted(specs)}, expected "
                f"exactly {sorted(EXPECTED_SPECS)}"
            )

        with urllib.request.urlopen(
            f"{BASE}/data/outputs/specifications.json?cb={int(time.time()*1000)}",
            timeout=30,
        ) as response:
            spec_manifest = json.loads(response.read())
        spec_ids = {e.get("spec_id") for e in spec_manifest.get("specifications", [])}
        contract["specification_ids"] = sorted(i for i in spec_ids if i)
        if spec_ids != EXPECTED_SPECS:
            contract_problems.append(
                f"specifications.json spec_ids are {sorted(spec_ids)}, "
                f"expected exactly {sorted(EXPECTED_SPECS)}"
            )
    except Exception as exc:
        contract["error"] = str(exc)
        contract_problems.append(f"could not validate the public contract: {exc}")
    contract["problems"] = contract_problems

    cache_condition = bool(cached)
    report = {
        "checked_at_utc": now,
        "origin_absence_confirmed": origin_absent,
        "origin_report_source": origin_source,
        "withdrawn_urls": withdrawn_rows,
        "withdrawn_returning_200": [row["url"] for row in cached],
        "inconclusive": [
            {"url": r["url"], "status": r["status"], "verdict": r["verdict"]}
            for r in inconclusive
        ],
        "all_withdrawn_accounted_for": not inconclusive,
        "cloudflare_cache_condition": cache_condition,
        "cache_note": (
            "Withdrawn URLs still returning 200 while the origin files are "
            "absent indicates a CDN cache serving copies of deleted files. "
            "This is NOT a failed origin deletion. Do not restore files. A "
            "cache purge is a separate, separately authorized action."
            if cache_condition else
            "No withdrawn URL returned 200."
        ),
    }
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    operational = {
        "checked_at_utc": now,
        "endpoints": operational_rows,
        "degraded": degraded,
        "all_healthy": not degraded,
        "public_contract": contract,
    }
    Path(args.operational_report).write_text(
        json.dumps(operational, indent=2, sort_keys=True) + "\n"
    )

    print()
    failed = False

    if cache_condition:
        print(f"NOTE: {len(cached)} withdrawn URL(s) return 200 while the "
              f"origin files are confirmed absent. Recorded as a CDN-cache "
              f"condition. This is not a failed deletion; do not restore "
              f"files. A purge is a separate authorized action.")

    if inconclusive:
        failed = True
        print(f"\nWITHDRAWAL NOT DEMONSTRATED for {len(inconclusive)} URL(s). "
              f"A non-200 response is not proof of removal — only 404/410 "
              f"is, or 200 with origin absence independently confirmed:",
              file=sys.stderr)
        for row in inconclusive:
            print(f"  {row['status']:>3}  {row['verdict']}  {row['url']}",
                  file=sys.stderr)
        if not origin_absent:
            print("  (origin absence was not confirmed; pass "
                  "--origin-report to allow the cache interpretation)",
                  file=sys.stderr)

    if contract_problems:
        failed = True
        print(f"\nPUBLIC CONTRACT INVALID:", file=sys.stderr)
        for problem in contract_problems:
            print(f"  - {problem}", file=sys.stderr)

    if degraded:
        failed = True
        print(f"\nOPERATIONAL SURFACE DEGRADED: {len(degraded)} endpoint(s) "
              f"not returning 200.", file=sys.stderr)

    if failed:
        return 1
    print("Operational surface healthy; public contract valid; every "
          "withdrawn URL accounted for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
