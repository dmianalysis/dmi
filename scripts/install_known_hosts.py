#!/usr/bin/env python3
"""Install PINNED SSH host material (Round-4 §3).

Why `ssh-keyscan` is not enough
-------------------------------
The previous implementation ran ``ssh-keyscan`` against the deployment
host and checked that the output was non-empty before writing it to
``known_hosts``. That check closes one hole — an empty ``known_hosts``
silently accepted — but it does not authenticate anything.

``ssh-keyscan`` asks the host at the other end of the connection to
introduce itself, and then believes the answer. If an attacker is in a
position to intercept the connection, they answer, and their key lands
in ``known_hosts`` as trusted. ``StrictHostKeyChecking=yes`` afterwards
faithfully verifies the session against the attacker's key. This is
trust-on-first-use, on every single run, which is the weakest form of
it: there is not even a second run to notice the key changed.

The fix is to know the key *before* connecting. The expected host key is
supplied out of band, through a repository or environment secret, and
this script installs it. Nothing on the network can influence what ends
up in ``known_hosts``.

Accepted material
-----------------
``--known-hosts-data`` / ``$DMI_KNOWN_HOSTS_DATA``
    One or more literal ``known_hosts`` lines. Each must name the host
    (and port, in the bracketed form OpenSSH uses for non-22 ports) that
    the deployment will actually contact.

``--fingerprint`` / ``$DMI_HOST_FINGERPRINT``
    A SHA-256 host-key fingerprint, as printed by ``ssh-keygen -lf``.
    Requires ``--allow-fingerprint-scan``: the key is then fetched and
    accepted only if its fingerprint matches the pinned value. This is
    still weaker than supplying the key itself, and is offered because
    §3 permits it, but it is never the default.

Absent, empty, malformed, or host-mismatched material is a hard failure.
There is no fallback that acquires trust dynamically.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


class HostPinError(RuntimeError):
    """Pinned host material is absent, malformed, or inconsistent."""


def expected_host_tokens(host: str, port: str) -> set[str]:
    """The host spellings a known_hosts line may legitimately use.

    OpenSSH writes ``[host]:port`` for any port other than 22, and a
    bare ``host`` for port 22.
    """
    tokens = {f"[{host}]:{port}"}
    if str(port) == "22":
        tokens.add(host)
    return tokens


def parse_known_hosts(data: str) -> list[tuple[str, str, str]]:
    """Parse into ``(hosts_field, keytype, key_b64)`` triples.

    Comments and blank lines are dropped. A line that is not three or
    more whitespace-separated fields is malformed.
    """
    entries: list[tuple[str, str, str]] = []
    for lineno, raw in enumerate(data.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            raise HostPinError(
                f"known_hosts line {lineno} is malformed (expected "
                f"'<host> <keytype> <key>'): {line!r}"
            )
        hosts_field, keytype, key_b64 = parts[0], parts[1], parts[2]
        if not keytype.startswith(("ssh-", "ecdsa-", "sk-")):
            raise HostPinError(
                f"known_hosts line {lineno} has implausible key type "
                f"{keytype!r}"
            )
        try:
            decoded = base64.b64decode(key_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HostPinError(
                f"known_hosts line {lineno} key is not valid base64: {exc}"
            ) from exc
        if not decoded:
            raise HostPinError(f"known_hosts line {lineno} key is empty")
        entries.append((hosts_field, keytype, key_b64))
    if not entries:
        raise HostPinError(
            "pinned host material contains no usable known_hosts entry"
        )
    return entries


def validate_hosts_match(entries, host: str, port: str) -> None:
    """Every pinned entry must name the host:port we will contact."""
    wanted = expected_host_tokens(host, port)
    for hosts_field, keytype, _key in entries:
        names = set(hosts_field.split(","))
        if not (names & wanted):
            raise HostPinError(
                f"pinned host key for {sorted(names)} ({keytype}) does not "
                f"match the configured target {sorted(wanted)}. Refusing to "
                f"deploy: the pinned material is for a different host or port."
            )


def fingerprint_of(keytype: str, key_b64: str) -> str:
    """SHA-256 fingerprint in OpenSSH's ``SHA256:<base64>`` form."""
    digest = hashlib.sha256(base64.b64decode(key_b64)).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def _scan_and_pin(host: str, port: str, fingerprint: str) -> str:
    """Fetch the host key and accept it ONLY if the fingerprint matches."""
    proc = subprocess.run(
        ["ssh-keyscan", "-p", str(port), host],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise HostPinError(
            f"ssh-keyscan failed for {host}:{port} "
            f"(rc={proc.returncode}): {proc.stderr.strip()}"
        )
    entries = parse_known_hosts(proc.stdout)
    validate_hosts_match(entries, host, port)

    wanted = fingerprint.strip()
    if not wanted.startswith("SHA256:"):
        raise HostPinError(
            f"pinned fingerprint must be in SHA256:<base64> form, got "
            f"{wanted!r}"
        )
    matching = [
        line for line in proc.stdout.splitlines()
        if line.strip() and not line.startswith("#")
        and fingerprint_of(line.split()[1], line.split()[2]) == wanted
    ]
    if not matching:
        offered = sorted({
            fingerprint_of(e[1], e[2]) for e in entries
        })
        raise HostPinError(
            f"no host key offered by {host}:{port} matches the pinned "
            f"fingerprint {wanted}. Offered: {offered}. Refusing to deploy."
        )
    return "\n".join(matching) + "\n"


def install(
    host: str,
    port: str,
    known_hosts: Path,
    known_hosts_data: Optional[str] = None,
    fingerprint: Optional[str] = None,
    allow_fingerprint_scan: bool = False,
) -> Path:
    """Write validated, pinned host material to ``known_hosts``."""
    if not host:
        raise HostPinError("no deployment host configured")

    if known_hosts_data and known_hosts_data.strip():
        entries = parse_known_hosts(known_hosts_data)
        validate_hosts_match(entries, host, port)
        payload = known_hosts_data if known_hosts_data.endswith("\n") \
            else known_hosts_data + "\n"
    elif fingerprint and fingerprint.strip():
        if not allow_fingerprint_scan:
            raise HostPinError(
                "a pinned fingerprint was supplied but "
                "--allow-fingerprint-scan was not passed. Fetching the key "
                "and checking it against a fingerprint is weaker than "
                "supplying the key itself, so it must be requested "
                "explicitly."
            )
        payload = _scan_and_pin(host, port, fingerprint)
    else:
        raise HostPinError(
            "no pinned host material. Set IFASTNET_KNOWN_HOSTS (preferred) "
            "or IFASTNET_HOST_FINGERPRINT. Deployment will NOT fall back to "
            "trusting whatever ssh-keyscan returns: that is "
            "trust-on-first-use and authenticates nothing."
        )

    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    known_hosts.write_text(payload)
    known_hosts.chmod(0o600)
    return known_hosts


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("IFASTNET_SSH_HOST", ""))
    parser.add_argument("--port", default=os.environ.get("IFASTNET_SSH_PORT", "1394"))
    parser.add_argument(
        "--known-hosts", required=True,
        help="Path to write the pinned known_hosts file.",
    )
    parser.add_argument(
        "--known-hosts-data",
        default=os.environ.get("IFASTNET_KNOWN_HOSTS")
        or os.environ.get("DMI_KNOWN_HOSTS_DATA"),
        help="Literal known_hosts content (preferred).",
    )
    parser.add_argument(
        "--fingerprint",
        default=os.environ.get("IFASTNET_HOST_FINGERPRINT")
        or os.environ.get("DMI_HOST_FINGERPRINT"),
        help="Pinned SHA-256 host-key fingerprint.",
    )
    parser.add_argument(
        "--allow-fingerprint-scan", action="store_true",
        help="Permit fetching the key and matching it against --fingerprint.",
    )
    args = parser.parse_args(argv)

    try:
        path = install(
            host=args.host,
            port=str(args.port),
            known_hosts=Path(args.known_hosts),
            known_hosts_data=args.known_hosts_data,
            fingerprint=args.fingerprint,
            allow_fingerprint_scan=args.allow_fingerprint_scan,
        )
    except HostPinError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Installed pinned host key for {args.host}:{args.port} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
