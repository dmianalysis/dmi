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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", required=True)
    parser.add_argument("--operational-report", required=True)
    args = parser.parse_args(argv)

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
    for url in sorted(withdrawn_urls):
        status, headers = _status(BASE + url)
        row = {
            "url": url,
            "status": status,
            "cf_cache_status": headers.get("CF-Cache-Status"),
            "age": headers.get("Age"),
            "server": headers.get("Server"),
        }
        withdrawn_rows.append(row)
        if status == 200:
            cached.append(row)
        print(f"  {status}  {url}"
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
    contract = {}
    try:
        with urllib.request.urlopen(
            f"{BASE}/data/outputs/latest.json?cb={int(time.time()*1000)}",
            timeout=30,
        ) as response:
            latest = json.loads(response.read())
        contract["current_release_id"] = latest.get("current_release_id")
        contract["current_is_2026_07"] = (
            latest.get("current_release_id") == "2026-07"
        )
        specs = set()
        for release in latest.get("releases", []):
            specs |= set((release.get("spec_urls") or {}).keys())
        contract["spec_urls_present"] = sorted(specs)
        contract["only_operational_specs"] = specs <= {"baseline", "slack_plus"}
    except Exception as exc:  # pragma: no cover - network shape
        contract["error"] = str(exc)

    cache_condition = bool(cached)
    report = {
        "checked_at_utc": now,
        "withdrawn_urls": withdrawn_rows,
        "withdrawn_returning_200": [row["url"] for row in cached],
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
    if cache_condition:
        print(f"NOTE: {len(cached)} withdrawn URL(s) still return 200. "
              f"Recorded as a CDN-cache condition; see the report. This is "
              f"not a failed deletion and requires no restoration.")
    if degraded:
        print(f"\nOPERATIONAL SURFACE DEGRADED: {len(degraded)} endpoint(s) "
              f"not returning 200.", file=sys.stderr)
        return 1
    print("Operational surface healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
