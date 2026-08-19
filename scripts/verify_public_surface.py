#!/usr/bin/env python3
"""Public HTTPS verification of the Core withdrawal.

What this has to get right
--------------------------
Three different things can make a withdrawn URL fail to return content,
and only one of them is evidence that the withdrawal worked:

1. the resource is gone (404/410) — withdrawal publicly demonstrated;
2. a CDN is still serving a cached copy of a deleted file (200, but only
   readable that way when the origin is independently confirmed absent);
3. this client could not reach the resource at all — a WAF 403, a 500, a
   redirect, a DNS or TLS failure.

The third case says nothing about whether anything was deleted, and
treating "not 200" as success would let a total loss of visibility read
as a clean withdrawal.

The 2026-08-19 run made the distinction concrete. Every withdrawn URL
returned 403 — and so did all eleven known-good operational controls, and
so did the contract fetch. Uniform 403 across resources that certainly
exist is not a degraded site; it is a blocked client. The verifier at the
time reported the operational surface as unhealthy, which pointed the
operator at a production incident that was not happening.

So this version separates four questions and answers them independently:

* **origin withdrawal** — supplied by the origin post-check, not measured here;
* **public withdrawn status** — what the CDN serves for the deleted URLs;
* **operational contract** — is the live surface still correct;
* **verifier-client accessibility** — could this client see anything at all.

A run where the client is blocked is inconclusive and exits non-zero. It
is never a pass, and never reported as public degradation.

On identifying honestly
-----------------------
The client sends a stable, truthful project User-Agent. That is not an
attempt to look like a browser: it says what the request is, so an
operator reading server logs can recognise it. No edge allowlist is
required or requested — the corrected client reaches the site as it
stands. Working around a block by impersonating a consumer browser,
disabling TLS verification, or accepting 403 as success would defeat the
check rather than fix it.
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

#: Truthful identification. Stable so it is recognisable in server logs;
#: project-specific so it is never confused with a real visitor. It is
#: not a request for special treatment at the edge.
USER_AGENT = "dmi-public-verifier/1.0 (+https://github.com/dmianalysis/dmi)"

#: The public contract this withdrawal must not disturb.
EXPECTED_RELEASE_ID = "2026-07"
EXPECTED_SPECS = frozenset({"baseline", "slack_plus"})

#: Statuses that positively demonstrate a resource is gone.
WITHDRAWN_STATUSES = frozenset({404, 410})

#: Response headers worth keeping for diagnosis. Bodies are never stored:
#: a WAF block page is large, uninformative, and may echo request data.
DIAGNOSTIC_HEADERS = (
    "Server", "CF-Ray", "CF-Cache-Status", "Age", "Content-Type", "Location",
)

#: Operational endpoints, each with a cheap assertion about its content.
#: A 200 that returns a WAF interstitial or an error page is not a
#: healthy endpoint, so "did it respond" is not the question asked.
OPERATIONAL_ENDPOINTS = (
    ("/dashboard.html", "html"),
    ("/health.json", "json"),
    ("/data/outputs/releases.json", "json"),
    ("/data/outputs/latest.json", "json"),
    ("/data/outputs/specifications.json", "json"),
    ("/data/outputs/dmi_release_2026-07.json", "json"),
    ("/data/outputs/dmi_release_2026-07_slack_plus.json", "json"),
    ("/data/outputs/dmi-2026-07-baseline.csv", "text"),
    ("/data/outputs/dmi-2026-07-slack_plus.parquet", "binary"),
    ("/data/outputs/releases/2026-07.html", "html"),
    ("/data/outputs/published/dmi_timeseries.json", "json"),
)

#: Above this share of known-good controls failing with the SAME status,
#: the client is the problem rather than the site.
CLIENT_BLOCK_THRESHOLD = 0.8


class Response:
    """A single HTTP result: status, diagnostic headers, decoded body."""

    def __init__(self, status: int, headers: dict, body: bytes,
                 error: Optional[str] = None):
        self.status = status
        self.headers = headers
        self.body = body
        self.error = error

    def diagnostics(self) -> dict:
        return {k: self.headers.get(k) for k in DIAGNOSTIC_HEADERS
                if self.headers.get(k) is not None}


def http_get(path_or_url: str, bust: bool = True) -> Response:
    """The one HTTP entry point. Every check goes through here.

    GET rather than HEAD: some CDNs answer HEAD from a different path and
    we want the body for content assertions. Cache-busting query plus
    no-cache headers so a stale edge copy is not mistaken for origin
    state.

    Never raises for an HTTP status, and never returns a body to the
    caller's log — only the caller decides what to assert on.
    """
    url = path_or_url if path_or_url.startswith("http") else BASE + path_or_url
    if bust:
        url = f"{url}{'&' if '?' in url else '?'}cb={int(time.time() * 1000)}"

    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html, text/csv, */*;q=0.1",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return Response(response.status, dict(response.headers),
                            response.read())
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:  # pragma: no cover - defensive
            pass
        return Response(exc.code, dict(exc.headers or {}), body)
    except Exception as exc:
        # DNS, TLS, timeout, connection reset. Status 0 means "no answer",
        # which is emphatically not "the resource is gone".
        return Response(0, {}, b"", error=f"{type(exc).__name__}: {exc}")


def classify_withdrawn(status: int, origin_absent: bool) -> tuple[str, bool]:
    """Classify a withdrawn URL's response. Returns ``(verdict, acceptable)``.

    Two outcomes are acceptable and the rest are not:

    - **404/410** — the resource is gone. Withdrawal demonstrated.
    - **200 with origin absence independently confirmed** — the origin
      file was deleted and a CDN is serving a cached copy. Acceptable,
      but reported separately because a purge may still be wanted.

    Everything else is inconclusive: 200 *without* that confirmation
    (which would mean nothing was deleted), 403 or 401 (this client was
    refused), 5xx, redirects, and status 0 for a network failure. None of
    them is evidence about the resource.
    """
    if status in WITHDRAWN_STATUSES:
        return ("withdrawn", True)
    if status == 200 and origin_absent:
        return ("cached_after_origin_deletion", True)
    if status == 200:
        return ("still_served_origin_not_confirmed_absent", False)
    if status == 0:
        return ("inconclusive_network_error", False)
    if status in (401, 403):
        return (f"inconclusive_client_refused_http_{status}", False)
    if 300 <= status < 400:
        return (f"inconclusive_redirect_http_{status}", False)
    return (f"inconclusive_http_{status}", False)


def check_content(kind: str, response: Response) -> Optional[str]:
    """Assert an operational endpoint returned what it should.

    Returns a problem string, or None. A 200 carrying a block page or an
    error document is not a healthy endpoint, so each endpoint declares
    the shape it must have.
    """
    if response.status != 200:
        return f"HTTP {response.status}"
    if not response.body:
        return "empty body"
    if kind == "json":
        try:
            json.loads(response.body)
        except Exception as exc:
            return f"200 but body is not valid JSON ({type(exc).__name__})"
    elif kind == "html":
        head = response.body[:2048].lower()
        if b"<html" not in head and b"<!doctype" not in head:
            return "200 but body does not look like HTML"
    elif kind == "text":
        if len(response.body) < 16:
            return "200 but body is implausibly short"
    elif kind == "binary":
        if len(response.body) < 16:
            return "200 but body is implausibly short"
    return None


def classify_client_accessibility(
    operational_rows: list[dict], withdrawn_rows: list[dict],
) -> dict:
    """Decide whether this client could see the site at all.

    Known-good operational endpoints are the control group: they
    certainly exist. If nearly all of them fail with the same status —
    and that status is a refusal rather than a 404 — the honest reading
    is that the client was blocked, not that the site broke. Reporting
    that as operational degradation sends an operator hunting a
    production incident that is not happening.
    """
    total = len(operational_rows)
    if not total:
        return {"blocked": False, "reason": "no operational controls checked"}

    counts: dict[int, int] = {}
    for row in operational_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    status, hits = max(counts.items(), key=lambda kv: kv[1])
    share = hits / total

    refusal = status in (401, 403) or status == 0
    if refusal and share >= CLIENT_BLOCK_THRESHOLD:
        withdrawn_same = sum(
            1 for row in withdrawn_rows if row["status"] == status
        )
        return {
            "blocked": True,
            "status": status,
            "operational_share": round(share, 3),
            "operational_with_status": hits,
            "operational_total": total,
            "withdrawn_with_same_status": withdrawn_same,
            "withdrawn_total": len(withdrawn_rows),
            "reason": (
                f"{hits}/{total} known-good operational endpoints returned "
                f"HTTP {status}, as did {withdrawn_same}/{len(withdrawn_rows)} "
                f"withdrawn URLs. Uniform refusal across resources that "
                f"certainly exist indicates this verification client was "
                f"blocked, not that the public surface is degraded. The run "
                f"is inconclusive; it is not a pass and not an outage."
            ),
        }
    return {"blocked": False, "reason": "operational controls were reachable"}


def _load_origin_absence(path: Optional[str]) -> tuple[bool, str]:
    if not path:
        return (False, "not supplied")
    candidate = Path(path)
    if not candidate.is_file():
        return (False, f"not found ({path})")
    try:
        origin = json.loads(candidate.read_text())
    except Exception as exc:
        return (False, f"unreadable ({exc})")
    return (bool(origin.get("all_withdrawn_absent")), path)


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
    parser.add_argument(
        "--inventory",
        default="docs/repair/inventories/core-withdrawal-2026-08-19.json",
        help="Sealed inventory naming the withdrawn URLs.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    origin_absent, origin_source = _load_origin_absence(args.origin_report)

    inventory = json.loads((repo_root / args.inventory).read_text())
    outputs = inventory["remote_outputs"]
    withdrawn_urls = sorted(
        "/data/outputs/" + record["path"][len(outputs) + 1:]
        for record in inventory["files"]
    )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    print(f"verification client: {USER_AGENT}")
    print()

    # ---- 2. public status of the withdrawn URLs ------------------------
    print("withdrawn URLs:")
    withdrawn_rows = []
    cached, inconclusive = [], []
    for url in withdrawn_urls:
        response = http_get(url)
        verdict, ok = classify_withdrawn(response.status, origin_absent)
        row = {
            "url": url,
            "status": response.status,
            "verdict": verdict,
            "acceptable": ok,
            "headers": response.diagnostics(),
        }
        if response.error:
            row["error"] = response.error
        withdrawn_rows.append(row)
        if verdict == "cached_after_origin_deletion":
            cached.append(row)
        if not ok:
            inconclusive.append(row)
        print(f"  {response.status:>3}  {verdict:<46s} {url}")

    # ---- 3. operational contract ---------------------------------------
    print("\noperational endpoints:")
    operational_rows, degraded = [], []
    for url, kind in OPERATIONAL_ENDPOINTS:
        response = http_get(url)
        problem = check_content(kind, response)
        row = {
            "url": url,
            "expected_kind": kind,
            "status": response.status,
            "content_ok": problem is None,
            "headers": response.diagnostics(),
        }
        if problem:
            row["problem"] = problem
        if response.error:
            row["error"] = response.error
        operational_rows.append(row)
        if problem:
            degraded.append(row)
        print(f"  {response.status:>3}  {'ok' if problem is None else problem:<46s} {url}")

    # ---- 4. verifier-client accessibility -------------------------------
    accessibility = classify_client_accessibility(operational_rows, withdrawn_rows)

    # ---- public contract -------------------------------------------------
    contract: dict = {}
    contract_problems: list[str] = []
    if accessibility["blocked"]:
        contract["skipped"] = (
            "not evaluated: the verification client was blocked, so a "
            "contract failure here would describe the client, not the site."
        )
    else:
        latest = http_get("/data/outputs/latest.json")
        if latest.status != 200:
            contract_problems.append(
                f"could not fetch latest.json (HTTP {latest.status})"
            )
        else:
            try:
                doc = json.loads(latest.body)
                release_id = doc.get("current_release_id")
                contract["current_release_id"] = release_id
                contract["current_is_expected"] = release_id == EXPECTED_RELEASE_ID
                if release_id != EXPECTED_RELEASE_ID:
                    contract_problems.append(
                        f"current_release_id is {release_id!r}, expected "
                        f"{EXPECTED_RELEASE_ID!r}"
                    )
                specs = set()
                for release in doc.get("releases", []):
                    specs |= set((release.get("spec_urls") or {}).keys())
                contract["latest_spec_urls"] = sorted(specs)
                if specs != EXPECTED_SPECS:
                    contract_problems.append(
                        f"latest.json advertises {sorted(specs)}, expected "
                        f"exactly {sorted(EXPECTED_SPECS)}"
                    )
            except Exception as exc:
                contract_problems.append(f"latest.json unparseable: {exc}")

        spec_response = http_get("/data/outputs/specifications.json")
        if spec_response.status != 200:
            contract_problems.append(
                f"could not fetch specifications.json "
                f"(HTTP {spec_response.status})"
            )
        else:
            try:
                doc = json.loads(spec_response.body)
                spec_ids = {e.get("spec_id") for e in doc.get("specifications", [])}
                contract["specification_ids"] = sorted(i for i in spec_ids if i)
                if spec_ids != EXPECTED_SPECS:
                    contract_problems.append(
                        f"specifications.json spec_ids are "
                        f"{sorted(spec_ids)}, expected exactly "
                        f"{sorted(EXPECTED_SPECS)}"
                    )
            except Exception as exc:
                contract_problems.append(f"specifications.json unparseable: {exc}")
    contract["problems"] = contract_problems

    # ---- reports ---------------------------------------------------------
    cache_condition = bool(cached)
    report = {
        "checked_at_utc": now,
        "user_agent": USER_AGENT,
        # (1) origin withdrawal — supplied, not measured here
        "origin_withdrawal": {
            "absence_confirmed": origin_absent,
            "source": origin_source,
        },
        # (2) public status of the withdrawn URLs
        "withdrawn_urls": withdrawn_rows,
        "withdrawn_demonstrated": [
            r["url"] for r in withdrawn_rows if r["verdict"] == "withdrawn"
        ],
        "withdrawn_returning_200": [r["url"] for r in cached],
        "inconclusive": [
            {"url": r["url"], "status": r["status"], "verdict": r["verdict"]}
            for r in inconclusive
        ],
        "all_withdrawn_accounted_for": not inconclusive,
        "cloudflare_cache_condition": cache_condition,
        # (4) could this client see anything
        "verifier_client": accessibility,
        "withdrawal_verdict": (
            "unknown" if accessibility["blocked"]
            else ("demonstrated" if not inconclusive else "not_demonstrated")
        ),
        "cache_note": (
            "Withdrawn URLs returning 200 while the origin files are "
            "confirmed absent indicates a CDN serving cached copies of "
            "deleted files. This is NOT a failed origin deletion. Do not "
            "restore files; a purge is a separate authorized action."
            if cache_condition else
            "No withdrawn URL returned 200."
        ),
    }
    Path(args.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    # When the client was blocked, the operational observations describe
    # the client, not the site. Reporting them as `degraded` would assert
    # a health verdict this run is not entitled to make — which is the
    # exact error the 2026-08-19 report made. `all_healthy` is null
    # (unknown, as distinct from true or false), `degraded` stays empty,
    # and the observations move to a field whose name says what they are.
    blocked = accessibility["blocked"]
    operational = {
        "checked_at_utc": now,
        "user_agent": USER_AGENT,
        "endpoints": operational_rows,
        "degraded": [] if blocked else degraded,
        "all_healthy": None if blocked else not degraded,
        "verifier_client": accessibility,
        "public_contract": contract,
    }
    if blocked:
        operational["unassessed_due_to_client_block"] = [
            {
                "url": row["url"],
                "status": row["status"],
                "note": (
                    "not assessed: the verification client was refused, so "
                    "this observation describes the client rather than the "
                    "endpoint"
                ),
            }
            for row in operational_rows
        ]
        operational["health_verdict"] = "unknown"
    else:
        operational["health_verdict"] = "healthy" if not degraded else "degraded"
    Path(args.operational_report).write_text(
        json.dumps(operational, indent=2, sort_keys=True) + "\n"
    )

    # ---- verdict ---------------------------------------------------------
    print()
    failed = False

    if accessibility["blocked"]:
        # Return here deliberately, before any of the degradation or
        # contract reporting below. Those paths would describe the
        # client, and a run that cannot see the site must not emit a
        # verdict about the site's health.
        print("VERIFICATION CLIENT BLOCKED — result inconclusive.",
              file=sys.stderr)
        print(f"  {accessibility['reason']}", file=sys.stderr)
        print(f"  {len(operational_rows)} operational endpoint(s) recorded "
              f"as unassessed; no health verdict is asserted.",
              file=sys.stderr)
        print("  This is NOT evidence of withdrawal and NOT an outage. "
              "Re-run from a client the edge will serve, or verify "
              "manually.", file=sys.stderr)
        return 1

    if cache_condition:
        print(f"NOTE: {len(cached)} withdrawn URL(s) return 200 while the "
              f"origin files are confirmed absent. Recorded as a CDN-cache "
              f"condition. Not a failed deletion; do not restore files. A "
              f"purge is a separate authorized action.")

    if inconclusive:
        failed = True
        print(f"\nWITHDRAWAL NOT DEMONSTRATED for {len(inconclusive)} URL(s). "
              f"Only 404/410 proves removal, or 200 with origin absence "
              f"independently confirmed:", file=sys.stderr)
        for row in inconclusive:
            print(f"  {row['status']:>3}  {row['verdict']}  {row['url']}",
                  file=sys.stderr)

    if contract_problems:
        failed = True
        print("\nPUBLIC CONTRACT INVALID:", file=sys.stderr)
        for problem in contract_problems:
            print(f"  - {problem}", file=sys.stderr)

    if degraded:
        failed = True
        print(f"\nOPERATIONAL SURFACE DEGRADED: {len(degraded)} endpoint(s) "
              f"did not return valid expected content.", file=sys.stderr)
        for row in degraded:
            print(f"  {row['url']}: {row.get('problem')}", file=sys.stderr)

    if failed:
        return 1
    print("Public verification passed: every withdrawn URL accounted for, "
          "operational surface healthy, public contract valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
